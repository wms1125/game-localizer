from __future__ import annotations

import json
import math
import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread

from .routing import RoutePhase, RoutePlan
from .segments import JsonValue, Segment
from .tasks import (
    Artifact,
    EventType,
    StepState,
    TaskEvent,
    TaskPlan,
    TaskProgress,
    TaskState,
    _copy_json_object,
)


_CONFIG_SCHEMA_VERSION = 1
_PROJECT_SCHEMA_VERSION = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp must be valid UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return parsed


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


@dataclass(frozen=True)
class TaskRetrySpec:
    command: str
    arguments: tuple[str, ...]
    parent_task_id: str | None
    created_at: str

    _FIELDS = ("command", "arguments", "parent_task_id", "created_at")
    _SENSITIVE_OPTIONS = frozenset(
        {"--api-key", "--authorization", "--secret", "--token"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", _require_text(self.command, "command"))
        if isinstance(self.arguments, (str, bytes)):
            raise TypeError("arguments must be an ordered collection")
        arguments = tuple(self.arguments)
        if any(not isinstance(item, str) or not item for item in arguments):
            raise ValueError("arguments must contain non-empty strings")
        for item in arguments:
            option = item.split("=", 1)[0].casefold()
            if option in self._SENSITIVE_OPTIONS:
                raise ValueError("retry arguments must not contain credentials")
        object.__setattr__(self, "arguments", arguments)
        if self.parent_task_id is not None:
            object.__setattr__(
                self,
                "parent_task_id",
                _require_text(self.parent_task_id, "parent_task_id"),
            )
        object.__setattr__(self, "created_at", _timestamp(self.created_at))

    @classmethod
    def create(
        cls,
        command: str,
        arguments: Iterable[str],
        *,
        parent_task_id: str | None = None,
    ) -> TaskRetrySpec:
        return cls(command, tuple(arguments), parent_task_id, _utc_now())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "command": self.command,
            "arguments": list(self.arguments),
            "parent_task_id": self.parent_task_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> TaskRetrySpec:
        if not isinstance(payload, Mapping) or set(payload) != set(cls._FIELDS):
            raise ValueError("TaskRetrySpec payload fields do not match schema")
        return cls(
            command=payload["command"],
            arguments=payload["arguments"],
            parent_task_id=payload["parent_task_id"],
            created_at=payload["created_at"],
        )


@dataclass(frozen=True)
class ProjectLockRecord:
    lock_name: str
    owner_id: str
    task_id: str | None
    acquired_at: str
    heartbeat_at: str
    expires_at: str

    def __post_init__(self) -> None:
        for field_name in ("lock_name", "owner_id"):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), field_name),
            )
        if self.task_id is not None:
            object.__setattr__(self, "task_id", _require_text(self.task_id, "task_id"))
        for field_name in ("acquired_at", "heartbeat_at", "expires_at"):
            value = _require_text(getattr(self, field_name), field_name)
            _parse_utc(value)
            object.__setattr__(self, field_name, value)

    @property
    def expired(self) -> bool:
        return _parse_utc(self.expires_at) <= datetime.now(timezone.utc)


@dataclass(frozen=True)
class TaskStatus:
    project: ProjectRecord
    task: TaskPlan
    first_event: TaskEvent | None
    last_event: TaskEvent | None
    latest_checkpoint: Checkpoint | None
    progress: TaskProgress | None
    failure_reason: str | None
    artifacts: tuple[Artifact, ...]
    retry_spec: TaskRetrySpec | None
    cancel_requested_at: str | None
    final_route: RoutePlan | None
    engine_id: str | None

    @property
    def stage(self) -> str:
        active_states = {
            StepState.RUNNING,
            StepState.PAUSED,
            StepState.RETRYING,
            StepState.FAILED,
        }
        active = next(
            (step for step in self.task.steps if step.state in active_states),
            None,
        )
        if active is not None:
            return active.step_id
        if self.last_event is not None and self.last_event.step_id is not None:
            return self.last_event.step_id
        return self.task.kind

    @property
    def created_at(self) -> str | None:
        return None if self.first_event is None else self.first_event.timestamp

    @property
    def updated_at(self) -> str | None:
        return None if self.last_event is None else self.last_event.timestamp

    def to_dict(self) -> dict[str, JsonValue]:
        progress = None if self.progress is None else self.progress.to_dict()
        return {
            "project_id": self.project.project_id,
            "project_name": self.project.name,
            "source_root": self.project.source_root,
            "task_id": self.task.task_id,
            "kind": self.task.kind,
            "state": self.task.state.value,
            "stage": self.stage,
            "engine_id": self.engine_id,
            "progress": progress,
            "failure_reason": self.failure_reason,
            "latest_checkpoint": (
                None
                if self.latest_checkpoint is None
                else self.latest_checkpoint.to_dict()
            ),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "retryable": self.retry_spec is not None,
            "retry": (
                None if self.retry_spec is None else self.retry_spec.to_dict()
            ),
            "parent_task_id": (
                None if self.retry_spec is None else self.retry_spec.parent_task_id
            ),
            "cancel_requested_at": self.cancel_requested_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "hanguard": (
                None if self.final_route is None else self.final_route.to_dict()
            ),
        }


class ProjectBusyError(RuntimeError):
    pass


class ProjectLease:
    def __init__(
        self,
        database_path: Path,
        lock_name: str,
        owner_id: str,
        ttl_seconds: float,
    ) -> None:
        self.database_path = database_path
        self.lock_name = lock_name
        self.owner_id = owner_id
        self.ttl_seconds = ttl_seconds
        self._stop = Event()
        self._closed = False
        self._thread = Thread(
            target=self._heartbeat_loop,
            name=f"hanengine-lock-{lock_name}",
            daemon=True,
        )
        self._thread.start()

    def _heartbeat_loop(self) -> None:
        interval = max(0.25, self.ttl_seconds / 3.0)
        while not self._stop.wait(interval):
            now = _utc_now()
            expires = (
                datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
            ).isoformat().replace("+00:00", "Z")
            try:
                with closing(sqlite3.connect(self.database_path, timeout=2.0)) as connection:
                    with connection:
                        connection.execute(
                            "UPDATE project_locks SET heartbeat_at=?,expires_at=? "
                            "WHERE lock_name=? AND owner_id=?",
                            (now, expires, self.lock_name, self.owner_id),
                        )
            except sqlite3.Error:
                continue

    def bind_task(self, task_id: str) -> None:
        task_id = _require_text(task_id, "task_id")
        with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE project_locks SET task_id=? WHERE lock_name=? AND owner_id=?",
                    (task_id, self.lock_name, self.owner_id),
                )
                if cursor.rowcount != 1:
                    raise ProjectBusyError("project lock is no longer owned")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        self._thread.join(timeout=2.0)
        try:
            with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
                with connection:
                    connection.execute(
                        "DELETE FROM project_locks WHERE lock_name=? AND owner_id=?",
                        (self.lock_name, self.owner_id),
                    )
        except sqlite3.Error:
            pass

    def __enter__(self) -> ProjectLease:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


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
        connection.execute("INSERT INTO schema_info(version) VALUES (?)", (_CONFIG_SCHEMA_VERSION,))
    elif row[0] != _CONFIG_SCHEMA_VERSION:
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
        CREATE TABLE IF NOT EXISTS task_retry_specs (
            project_id TEXT NOT NULL, task_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS task_cancel_requests (
            project_id TEXT NOT NULL, task_id TEXT PRIMARY KEY, requested_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS project_locks (
            project_id TEXT NOT NULL, lock_name TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            task_id TEXT, acquired_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """
    )
    row = connection.execute("SELECT version FROM schema_info").fetchone()
    if row is None:
        connection.execute("INSERT INTO schema_info(version) VALUES (?)", (_PROJECT_SCHEMA_VERSION,))
    elif row[0] == 1:
        connection.execute(
            "UPDATE schema_info SET version=?",
            (_PROJECT_SCHEMA_VERSION,),
        )
    elif row[0] != _PROJECT_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported project schema version: {row[0]}")
    meta = connection.execute(
        "SELECT project_id,name,created_at FROM project_meta LIMIT 1"
    ).fetchone()
    if meta is not None and tuple(meta) != (record.project_id, record.name, record.created_at):
        raise ValueError("project database identity does not match the project index")
    if meta is None:
        connection.execute(
            "INSERT INTO project_meta(project_id,name,created_at) VALUES (?,?,?)",
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
        if source_root is not None and not isinstance(source_root, Path):
            raise TypeError("source_root must be a Path or None")
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

    def list_task_statuses(
        self,
        *,
        project_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[TaskStatus, ...]:
        if project_id is not None:
            project_ids = (_require_project_id(project_id),)
        else:
            project_ids = tuple(item.project_id for item in self.list_projects())
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise ValueError("limit must be a positive integer or None")
        statuses: list[TaskStatus] = []
        for current_project_id in project_ids:
            with self.open_project(current_project_id) as project:
                statuses.extend(
                    project.task_status(task.task_id)
                    for task in project.list_tasks()
                )
        statuses.sort(
            key=lambda item: (
                item.updated_at or item.created_at or item.project.created_at,
                item.task.task_id,
            ),
            reverse=True,
        )
        return tuple(statuses if limit is None else statuses[:limit])

    def find_task_status(self, task_id: str) -> TaskStatus | None:
        task_id = _require_text(task_id, "task_id")
        for record in self.list_projects():
            with self.open_project(record.project_id) as project:
                if project.get_task(task_id) is not None:
                    return project.task_status(task_id)
        return None

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
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            _initialize_project(self._connection, record)
        except Exception:
            self._connection.close()
            self._connection = None
            raise

    @property
    def project_id(self) -> str:
        return self._record.project_id

    @property
    def source_root(self) -> Path | None:
        if self._record.source_root is None:
            return None
        return Path(self._record.source_root)

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

    def replace_segments(self, segments: Iterable[Segment]) -> None:
        items = tuple(segments)
        for segment in items:
            if not isinstance(segment, Segment):
                raise TypeError("segments must contain Segment values")
            self._check_project(segment.project_id)
        existing = {
            row[0]
            for row in self._connection.execute(
                "SELECT segment_id FROM segments WHERE project_id=?",
                (self.project_id,),
            ).fetchall()
        }
        missing = sorted(item.segment_id for item in items if item.segment_id not in existing)
        if missing:
            raise ValueError("cannot replace unknown segments: " + ",".join(missing))
        with self._connection:
            self._connection.executemany(
                "UPDATE segments SET payload_json=? WHERE project_id=? AND segment_id=?",
                [
                    (
                        _canonical_json(item.to_dict(), "segment"),
                        self.project_id,
                        item.segment_id,
                    )
                    for item in items
                ],
            )

    def list_segments(self) -> tuple[Segment, ...]:
        rows = self._connection.execute("SELECT payload_json FROM segments WHERE project_id=? ORDER BY segment_id", (self.project_id,)).fetchall()
        return tuple(Segment.from_dict(_parse_json_object(row[0], "Segment")) for row in rows)

    def get_segment(self, segment_id: str) -> Segment | None:
        segment_id = _require_text(segment_id, "segment_id")
        row = self._connection.execute(
            "SELECT payload_json FROM segments WHERE project_id=? AND segment_id=?",
            (self.project_id, segment_id),
        ).fetchone()
        return None if row is None else Segment.from_dict(_parse_json_object(row[0], "Segment"))

    def save_segment_checkpoint(self, segment: Segment, checkpoint: Checkpoint) -> None:
        if not isinstance(segment, Segment):
            raise TypeError("segment must be a Segment")
        if not isinstance(checkpoint, Checkpoint):
            raise TypeError("checkpoint must be a Checkpoint")
        self._check_project(segment.project_id)
        self._check_task(checkpoint.task_id, checkpoint.step_id)
        if checkpoint.payload.get("segment_id") != segment.segment_id:
            raise ValueError("checkpoint segment_id must match the segment")
        with self._connection:
            self._connection.execute(
                "INSERT INTO segments(project_id,segment_id,payload_json) VALUES (?,?,?) "
                "ON CONFLICT(project_id,segment_id) DO UPDATE SET payload_json=excluded.payload_json",
                (
                    self.project_id,
                    segment.segment_id,
                    _canonical_json(segment.to_dict(), "segment"),
                ),
            )
            self._connection.execute(
                "INSERT INTO checkpoints(project_id,checkpoint_id,task_id,step_id,sequence,payload_json) "
                "VALUES (?,?,?,?,?,?)",
                (
                    self.project_id,
                    checkpoint.checkpoint_id,
                    checkpoint.task_id,
                    checkpoint.step_id,
                    checkpoint.sequence,
                    _canonical_json(checkpoint.to_dict(), "checkpoint"),
                ),
            )

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

    def delete_route(self, phase: RoutePhase) -> None:
        if not isinstance(phase, RoutePhase):
            raise TypeError("phase must be a RoutePhase")
        with self._connection:
            self._connection.execute(
                "DELETE FROM route_plans WHERE project_id=? AND phase=?",
                (self.project_id, phase.value),
            )

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

    def list_tasks(self) -> tuple[TaskPlan, ...]:
        rows = self._connection.execute(
            "SELECT payload_json FROM tasks WHERE project_id=? ORDER BY rowid DESC",
            (self.project_id,),
        ).fetchall()
        return tuple(
            TaskPlan.from_dict(_parse_json_object(row[0], "TaskPlan"))
            for row in rows
        )

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

    def list_checkpoints(
        self,
        task_id: str,
        step_id: str | None = None,
    ) -> tuple[Checkpoint, ...]:
        self._check_task(task_id, step_id)
        if step_id is None:
            rows = self._connection.execute(
                "SELECT payload_json FROM checkpoints WHERE project_id=? AND task_id=? "
                "ORDER BY sequence,checkpoint_id",
                (self.project_id, task_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT payload_json FROM checkpoints WHERE project_id=? AND task_id=? AND step_id=? "
                "ORDER BY sequence,checkpoint_id",
                (self.project_id, task_id, step_id),
            ).fetchall()
        return tuple(
            Checkpoint.from_dict(_parse_json_object(row[0], "Checkpoint"))
            for row in rows
        )

    def latest_checkpoint(self, task_id: str) -> Checkpoint | None:
        self._check_task(task_id)
        row = self._connection.execute(
            "SELECT payload_json FROM checkpoints WHERE project_id=? AND task_id=? "
            "ORDER BY sequence DESC,rowid DESC LIMIT 1",
            (self.project_id, task_id),
        ).fetchone()
        return None if row is None else Checkpoint.from_dict(
            _parse_json_object(row[0], "Checkpoint")
        )

    def save_task_retry_spec(self, task_id: str, spec: TaskRetrySpec) -> None:
        self._check_task(task_id)
        if not isinstance(spec, TaskRetrySpec):
            raise TypeError("spec must be a TaskRetrySpec")
        with self._connection:
            self._connection.execute(
                "INSERT INTO task_retry_specs(project_id,task_id,payload_json) VALUES (?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET payload_json=excluded.payload_json",
                (
                    self.project_id,
                    task_id,
                    _canonical_json(spec.to_dict(), "task retry spec"),
                ),
            )

    def get_task_retry_spec(self, task_id: str) -> TaskRetrySpec | None:
        self._check_task(task_id)
        row = self._connection.execute(
            "SELECT payload_json FROM task_retry_specs WHERE project_id=? AND task_id=?",
            (self.project_id, task_id),
        ).fetchone()
        return None if row is None else TaskRetrySpec.from_dict(
            _parse_json_object(row[0], "TaskRetrySpec")
        )

    def request_task_cancel(self, task_id: str) -> str:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"task does not belong to project {self.project_id}")
        if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            raise ValueError("terminal tasks cannot be cancelled")
        requested_at = _utc_now()
        with self._connection:
            self._connection.execute(
                "INSERT INTO task_cancel_requests(project_id,task_id,requested_at) VALUES (?,?,?) "
                "ON CONFLICT(task_id) DO NOTHING",
                (self.project_id, task_id, requested_at),
            )
        return self.cancel_requested_at(task_id) or requested_at

    def cancel_requested_at(self, task_id: str) -> str | None:
        self._check_task(task_id)
        row = self._connection.execute(
            "SELECT requested_at FROM task_cancel_requests WHERE project_id=? AND task_id=?",
            (self.project_id, task_id),
        ).fetchone()
        return None if row is None else row[0]

    def is_task_cancel_requested(self, task_id: str) -> bool:
        return self.cancel_requested_at(task_id) is not None

    def mark_task_abandoned(self, task_id: str) -> TaskPlan:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"task does not belong to project {self.project_id}")
        if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            return task
        for step in task.steps:
            if step.state in {StepState.RUNNING, StepState.PAUSED, StepState.RETRYING}:
                step.state = StepState.FAILED
            elif step.state is StepState.QUEUED:
                step.state = StepState.CANCELLED
        task.state = TaskState.FAILED
        events = self.list_events(task_id)
        sequence = (events[-1].sequence if events else 0) + 1
        self.save_task(task)
        self.append_event(
            TaskEvent(
                task_id=task_id,
                step_id=None,
                sequence=sequence,
                event_type=EventType.FAILED,
                timestamp=_utc_now(),
                summary="task abandoned before retry",
                data={"reason_code": "process_restart"},
            )
        )
        return task

    def task_status(self, task_id: str) -> TaskStatus:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"task does not belong to project {self.project_id}")
        events = self.list_events(task_id)
        first_event = events[0] if events else None
        last_event = events[-1] if events else None
        progress = next(
            (event.progress for event in reversed(events) if event.progress is not None),
            None,
        )
        failure_event = next(
            (event for event in reversed(events) if event.event_type is EventType.FAILED),
            None,
        )
        if failure_event is None:
            failure_reason = None
        else:
            exception_type = failure_event.data.get("exception_type")
            reason_code = failure_event.data.get("reason_code")
            detail = exception_type if isinstance(exception_type, str) else reason_code
            failure_reason = failure_event.summary
            if isinstance(detail, str) and detail:
                failure_reason += f" ({detail})"
        retry_spec = self.get_task_retry_spec(task_id)
        engine_id = None
        if (
            retry_spec is not None
            and retry_spec.command == "engine"
            and len(retry_spec.arguments) >= 2
        ):
            engine_id = retry_spec.arguments[1]
        if engine_id is None:
            for event in reversed(events):
                data = event.data.get("data")
                if isinstance(data, dict):
                    adapter_id = data.get("adapter_id")
                    if isinstance(adapter_id, str) and adapter_id:
                        engine_id = adapter_id
                        break
        return TaskStatus(
            project=self._record,
            task=task,
            first_event=first_event,
            last_event=last_event,
            latest_checkpoint=self.latest_checkpoint(task_id),
            progress=progress,
            failure_reason=failure_reason,
            artifacts=self.list_artifacts(task_id),
            retry_spec=retry_spec,
            cancel_requested_at=self.cancel_requested_at(task_id),
            final_route=self.get_route(RoutePhase.FINAL),
            engine_id=engine_id,
        )

    def active_project_lock(self, lock_name: str) -> ProjectLockRecord | None:
        lock_name = _require_text(lock_name, "lock_name")
        row = self._connection.execute(
            "SELECT lock_name,owner_id,task_id,acquired_at,heartbeat_at,expires_at "
            "FROM project_locks WHERE project_id=? AND lock_name=?",
            (self.project_id, lock_name),
        ).fetchone()
        if row is None:
            return None
        record = ProjectLockRecord(*row)
        if not record.expired:
            return record
        with self._connection:
            self._connection.execute(
                "DELETE FROM project_locks WHERE project_id=? AND lock_name=? AND owner_id=?",
                (self.project_id, lock_name, record.owner_id),
            )
        return None

    def active_lock_for_task(self, task_id: str) -> ProjectLockRecord | None:
        self._check_task(task_id)
        rows = self._connection.execute(
            "SELECT lock_name,owner_id,task_id,acquired_at,heartbeat_at,expires_at "
            "FROM project_locks WHERE project_id=? AND task_id=?",
            (self.project_id, task_id),
        ).fetchall()
        for row in rows:
            record = ProjectLockRecord(*row)
            if not record.expired:
                return record
        return None

    def acquire_project_lock(
        self,
        lock_name: str = "structured-workflow",
        *,
        ttl_seconds: float = 10.0,
    ) -> ProjectLease:
        lock_name = _require_text(lock_name, "lock_name")
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not math.isfinite(float(ttl_seconds))
            or float(ttl_seconds) < 1.0
        ):
            raise ValueError("ttl_seconds must be a finite number of at least 1")
        ttl = float(ttl_seconds)
        owner_id = str(uuid.uuid4())
        acquired_at = _utc_now()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl)
        ).isoformat().replace("+00:00", "Z")
        with closing(sqlite3.connect(self._path, timeout=5.0)) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT lock_name,owner_id,task_id,acquired_at,heartbeat_at,expires_at "
                    "FROM project_locks WHERE project_id=? AND lock_name=?",
                    (self.project_id, lock_name),
                ).fetchone()
                if row is not None and not ProjectLockRecord(*row).expired:
                    raise ProjectBusyError(
                        f"project workflow is already running: {lock_name}"
                    )
                connection.execute(
                    "DELETE FROM project_locks WHERE project_id=? AND lock_name=?",
                    (self.project_id, lock_name),
                )
                connection.execute(
                    "INSERT INTO project_locks(project_id,lock_name,owner_id,task_id,"
                    "acquired_at,heartbeat_at,expires_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        self.project_id,
                        lock_name,
                        owner_id,
                        None,
                        acquired_at,
                        acquired_at,
                        expires_at,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return ProjectLease(self._path, lock_name, owner_id, ttl)

    def close(self) -> None:
        if getattr(self, "_connection", None) is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> ProjectStore:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = [
    "Checkpoint",
    "HanStore",
    "ProjectBusyError",
    "ProjectLease",
    "ProjectLockRecord",
    "ProjectRecord",
    "ProjectStore",
    "TaskRetrySpec",
    "TaskStatus",
    "default_data_root",
]
