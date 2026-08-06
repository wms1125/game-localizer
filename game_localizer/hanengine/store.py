from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .routing import RoutePhase, RoutePlan
from .segments import JsonValue, Segment
from .tasks import (
    Artifact,
    TaskEvent,
    TaskPlan,
    _copy_json_object,
)


_SCHEMA_VERSION = 1
def _canonical_json(value: Mapping[str, JsonValue], field_name: str) -> str:
    copied = _copy_json_object(dict(value), field_name)
    return json.dumps(
        copied,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _parse_json_object(value: str, model_name: str) -> Mapping[str, JsonValue]:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{model_name} payload is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{model_name} payload must be a JSON object")
    return payload


def _require_text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


def _require_project_id(value: object) -> str:
    project_id = _require_text(value, "project_id")
    try:
        parsed = uuid.UUID(project_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("project_id must be a UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != project_id.lower() or project_id != project_id.lower():
        raise ValueError("project_id must be a canonical lower-case UUIDv4")
    return project_id


def _timestamp(value: object) -> str:
    timestamp = _require_text(value, "created_at")
    if not timestamp.endswith("Z"):
        raise ValueError("created_at must be a UTC timestamp ending in Z")
    return timestamp


def _ensure_project_path(data_root: Path, project_id: str) -> Path:
    path = (data_root / "projects" / project_id).resolve(strict=False)
    projects_root = (data_root / "projects").resolve(strict=False)
    try:
        path.relative_to(projects_root)
    except ValueError as exc:
        raise ValueError("project_id escapes the projects directory") from exc
    return path


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    name: str
    source_root: str | None
    created_at: str

    _FIELDS = ("project_id", "name", "source_root", "created_at")

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _require_project_id(self.project_id))
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        if self.source_root is not None:
            object.__setattr__(self, "source_root", _require_text(self.source_root, "source_root"))
        object.__setattr__(self, "created_at", _timestamp(self.created_at))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "source_root": self.source_root,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> ProjectRecord:
        if not isinstance(payload, Mapping) or set(payload) != set(cls._FIELDS):
            raise ValueError("ProjectRecord payload fields do not match schema")
        return cls(
            project_id=payload["project_id"],
            name=payload["name"],
            source_root=payload["source_root"],
            created_at=payload["created_at"],
        )


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    task_id: str
    step_id: str
    sequence: int
    payload: dict[str, JsonValue]

    _FIELDS = ("checkpoint_id", "task_id", "step_id", "sequence", "payload")

    def __post_init__(self) -> None:
        for field_name in ("checkpoint_id", "task_id", "step_id"):
            object.__setattr__(self, field_name, _require_text(getattr(self, field_name), field_name))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        object.__setattr__(self, "payload", _copy_json_object(self.payload, "payload"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "sequence": self.sequence,
            "payload": _copy_json_object(self.payload, "payload"),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> Checkpoint:
        if not isinstance(payload, Mapping) or set(payload) != set(cls._FIELDS):
            raise ValueError("Checkpoint payload fields do not match schema")
        return cls(
            checkpoint_id=payload["checkpoint_id"],
            task_id=payload["task_id"],
            step_id=payload["step_id"],
            sequence=payload["sequence"],
            payload=payload["payload"],
        )


def default_data_root(local_app_data: Path | None = None) -> Path:
    if local_app_data is None:
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise RuntimeError("LOCALAPPDATA is not available; provide local_app_data")
        local_app_data = Path(base)
    if not isinstance(local_app_data, Path):
        raise TypeError("local_app_data must be a Path or None")
    return local_app_data / "HanEngine"


def _initialize_config(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_info (version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_root TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    row = connection.execute("SELECT version FROM schema_info").fetchone()
    if row is None:
        connection.execute("INSERT INTO schema_info(version) VALUES (?)", (_SCHEMA_VERSION,))
    elif row[0] != _SCHEMA_VERSION:
        raise RuntimeError(f"unsupported config schema version: {row[0]}")
    connection.commit()


def _initialize_project(connection: sqlite3.Connection, record: ProjectRecord) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_info (version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS project_meta (
            project_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS segments (
            project_id TEXT NOT NULL, segment_id TEXT NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY(project_id, segment_id)
        );
        CREATE TABLE IF NOT EXISTS route_plans (
            project_id TEXT NOT NULL, phase TEXT NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY(project_id, phase)
        );
        CREATE TABLE IF NOT EXISTS tasks (
            project_id TEXT NOT NULL, task_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_steps (
            project_id TEXT NOT NULL, task_id TEXT NOT NULL, step_id TEXT NOT NULL,
            payload_json TEXT NOT NULL, PRIMARY KEY(task_id, step_id),
            FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS task_events (
            project_id TEXT NOT NULL, task_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            payload_json TEXT NOT NULL, PRIMARY KEY(task_id, sequence),
            FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            project_id TEXT NOT NULL, artifact_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
            step_id TEXT NOT NULL, payload_json TEXT NOT NULL,
            FOREIGN KEY(task_id, step_id) REFERENCES task_steps(task_id, step_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS checkpoints (
            project_id TEXT NOT NULL, checkpoint_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
            step_id TEXT NOT NULL, sequence INTEGER NOT NULL, payload_json TEXT NOT NULL,
            FOREIGN KEY(task_id, step_id) REFERENCES task_steps(task_id, step_id) ON DELETE CASCADE
        );
        """
    )
    row = connection.execute("SELECT version FROM schema_info").fetchone()
    if row is None:
        connection.execute("INSERT INTO schema_info(version) VALUES (?)", (_SCHEMA_VERSION,))
    elif row[0] != _SCHEMA_VERSION:
        raise RuntimeError(f"unsupported project schema version: {row[0]}")
    connection.execute(
        "INSERT OR REPLACE INTO project_meta(project_id,name,created_at) VALUES (?,?,?)",
        (record.project_id, record.name, record.created_at),
    )
    connection.commit()


class HanStore:
    def __init__(self, data_root: Path):
        if not isinstance(data_root, Path):
            raise TypeError("data_root must be a Path")
        self.root = data_root.resolve(strict=False)
        self.projects_root = self.root / "projects"
        self.root.mkdir(parents=True, exist_ok=True)
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "config.db"
        with closing(sqlite3.connect(self.config_path)) as connection:
            _initialize_config(connection)

    def project_path(self, project_id: str) -> Path:
        return _ensure_project_path(self.root, _require_project_id(project_id)) / "hanengine.db"

    def create_project(
        self,
        name: str,
        source_root: Path | None = None,
        project_id: str | None = None,
    ) -> ProjectRecord:
        project_id = str(uuid.uuid4()) if project_id is None else _require_project_id(project_id)
        name = _require_text(name, "name")
        source = None if source_root is None else str(source_root.resolve(strict=False))
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = ProjectRecord(project_id, name, source, created_at)
        project_dir = _ensure_project_path(self.root, project_id)
        project_dir.mkdir(parents=True, exist_ok=False)
        try:
            with closing(sqlite3.connect(self.config_path)) as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO projects(project_id,name,source_root,created_at) VALUES (?,?,?,?)",
                        (record.project_id, record.name, record.source_root, record.created_at),
                    )
            connection = sqlite3.connect(project_dir / "hanengine.db")
            try:
                _initialize_project(connection, record)
            finally:
                connection.close()
        except Exception:
            with closing(sqlite3.connect(self.config_path)) as connection:
                with connection:
                    connection.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
            if project_dir.exists():
                for child in project_dir.iterdir():
                    child.unlink()
                project_dir.rmdir()
            raise
        return record

    def get_project(self, project_id: str) -> ProjectRecord | None:
        project_id = _require_project_id(project_id)
        with closing(sqlite3.connect(self.config_path)) as connection:
            row = connection.execute(
                "SELECT project_id,name,source_root,created_at FROM projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
        return None if row is None else ProjectRecord(*row)

    def list_projects(self) -> tuple[ProjectRecord, ...]:
        with closing(sqlite3.connect(self.config_path)) as connection:
            rows = connection.execute("SELECT project_id,name,source_root,created_at FROM projects ORDER BY created_at, project_id").fetchall()
        return tuple(ProjectRecord(*row) for row in rows)

    def open_project(self, project_id: str) -> ProjectStore:
        project_id = _require_project_id(project_id)
        record = self.get_project(project_id)
        if record is None:
            raise KeyError(f"project not found: {project_id}")
        path = self.project_path(project_id)
        if not path.is_file():
            raise FileNotFoundError(path)
        return ProjectStore(path, record)

    def close(self) -> None:
        pass

    def __enter__(self) -> HanStore:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class ProjectStore:
    def __init__(self, path: Path, record: ProjectRecord):
        self._path = path.resolve(strict=False)
        self._record = record
        self._connection = sqlite3.connect(self._path)
        self._connection.execute("PRAGMA foreign_keys = ON")
        _initialize_project(self._connection, record)

    @property
    def project_id(self) -> str:
        return self._record.project_id

    @property
    def path(self) -> Path:
        return self._path

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def _check_project(self, value: object, field_name: str = "project_id") -> None:
        if value != self.project_id:
            raise ValueError(f"{field_name} does not belong to project {self.project_id}")

    def _check_task(self, task_id: str, step_id: str | None = None) -> None:
        row = self._connection.execute("SELECT project_id FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError(f"task does not belong to project {self.project_id}")
        self._check_project(row[0])
        if step_id is not None:
            step = self._connection.execute("SELECT project_id FROM task_steps WHERE task_id=? AND step_id=?", (task_id, step_id)).fetchone()
            if step is None:
                raise ValueError("step does not belong to task")
            self._check_project(step[0])

    def save_segments(self, segments: Iterable[Segment]) -> None:
        items = tuple(segments)
        for segment in items:
            if not isinstance(segment, Segment):
                raise TypeError("segments must contain Segment values")
            self._check_project(segment.project_id)
        with self._connection:
            self._connection.executemany(
                "INSERT INTO segments(project_id,segment_id,payload_json) VALUES (?,?,?)",
                [(self.project_id, item.segment_id, _canonical_json(item.to_dict(), "segment")) for item in items],
            )

    def list_segments(self) -> tuple[Segment, ...]:
        rows = self._connection.execute("SELECT payload_json FROM segments WHERE project_id=? ORDER BY segment_id", (self.project_id,)).fetchall()
        return tuple(Segment.from_dict(_parse_json_object(row[0], "Segment")) for row in rows)

    def save_route(self, route: RoutePlan) -> None:
        if not isinstance(route, RoutePlan):
            raise TypeError("route must be a RoutePlan")
        self._check_project(route.project_id)
        with self._connection:
            self._connection.execute("INSERT OR REPLACE INTO route_plans(project_id,phase,payload_json) VALUES (?,?,?)", (self.project_id, route.phase.value, _canonical_json(route.to_dict(), "route")))

    def get_route(self, phase: RoutePhase) -> RoutePlan | None:
        if not isinstance(phase, RoutePhase):
            raise TypeError("phase must be a RoutePhase")
        row = self._connection.execute("SELECT payload_json FROM route_plans WHERE project_id=? AND phase=?", (self.project_id, phase.value)).fetchone()
        return None if row is None else RoutePlan.from_dict(_parse_json_object(row[0], "RoutePlan"))

    def save_task(self, task: TaskPlan) -> None:
        if not isinstance(task, TaskPlan):
            raise TypeError("task must be a TaskPlan")
        self._check_project(task.project_id)
        with self._connection:
            self._connection.execute("INSERT INTO tasks(project_id,task_id,payload_json) VALUES (?,?,?) ON CONFLICT(task_id) DO UPDATE SET project_id=excluded.project_id,payload_json=excluded.payload_json", (self.project_id, task.task_id, _canonical_json(task.to_dict(), "task")))
            for step in task.steps:
                self._connection.execute("INSERT INTO task_steps(project_id,task_id,step_id,payload_json) VALUES (?,?,?,?) ON CONFLICT(task_id,step_id) DO UPDATE SET project_id=excluded.project_id,payload_json=excluded.payload_json", (self.project_id, task.task_id, step.step_id, _canonical_json(step.to_dict(), "task step")))

    def get_task(self, task_id: str) -> TaskPlan | None:
        row = self._connection.execute("SELECT payload_json FROM tasks WHERE project_id=? AND task_id=?", (self.project_id, task_id)).fetchone()
        return None if row is None else TaskPlan.from_dict(_parse_json_object(row[0], "TaskPlan"))

    def append_event(self, event: TaskEvent) -> None:
        if not isinstance(event, TaskEvent):
            raise TypeError("event must be a TaskEvent")
        self._check_task(event.task_id, event.step_id)
        with self._connection:
            self._connection.execute("INSERT INTO task_events(project_id,task_id,sequence,payload_json) VALUES (?,?,?,?)", (self.project_id, event.task_id, event.sequence, _canonical_json(event.to_dict(), "event")))

    def list_events(self, task_id: str, after_sequence: int = 0) -> tuple[TaskEvent, ...]:
        self._check_task(task_id)
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        rows = self._connection.execute("SELECT payload_json FROM task_events WHERE project_id=? AND task_id=? AND sequence>? ORDER BY sequence", (self.project_id, task_id, after_sequence)).fetchall()
        return tuple(TaskEvent.from_dict(_parse_json_object(row[0], "TaskEvent")) for row in rows)

    def save_artifact(self, artifact: Artifact) -> None:
        if not isinstance(artifact, Artifact):
            raise TypeError("artifact must be an Artifact")
        self._check_task(artifact.task_id, artifact.step_id)
        with self._connection:
            self._connection.execute("INSERT INTO artifacts(project_id,artifact_id,task_id,step_id,payload_json) VALUES (?,?,?,?,?)", (self.project_id, artifact.artifact_id, artifact.task_id, artifact.step_id, _canonical_json(artifact.to_dict(), "artifact")))

    def list_artifacts(self, task_id: str) -> tuple[Artifact, ...]:
        self._check_task(task_id)
        rows = self._connection.execute("SELECT payload_json FROM artifacts WHERE project_id=? AND task_id=? ORDER BY artifact_id", (self.project_id, task_id)).fetchall()
        return tuple(Artifact.from_dict(_parse_json_object(row[0], "Artifact")) for row in rows)

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        if not isinstance(checkpoint, Checkpoint):
            raise TypeError("checkpoint must be a Checkpoint")
        self._check_task(checkpoint.task_id, checkpoint.step_id)
        with self._connection:
            self._connection.execute("INSERT INTO checkpoints(project_id,checkpoint_id,task_id,step_id,sequence,payload_json) VALUES (?,?,?,?,?,?)", (self.project_id, checkpoint.checkpoint_id, checkpoint.task_id, checkpoint.step_id, checkpoint.sequence, _canonical_json(checkpoint.to_dict(), "checkpoint")))

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        row = self._connection.execute("SELECT payload_json FROM checkpoints WHERE project_id=? AND checkpoint_id=?", (self.project_id, checkpoint_id)).fetchone()
        return None if row is None else Checkpoint.from_dict(_parse_json_object(row[0], "Checkpoint"))

    def close(self) -> None:
        if getattr(self, "_connection", None) is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> ProjectStore:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = ["Checkpoint", "HanStore", "ProjectRecord", "ProjectStore", "default_data_root"]
