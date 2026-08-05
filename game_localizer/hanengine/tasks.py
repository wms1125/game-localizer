from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TypeVar

from .routing import RouteOperation
from .segments import JsonValue, normalize_relative_path


EnumType = TypeVar("EnumType", bound=Enum)

_RESERVED_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "secret",
        "token",
        "request_body",
        "screenshot",
        "chain_of_thought",
        "reasoning_trace",
    }
)


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    QUEUED = "queued"
    STARTED = "started"
    PROGRESS = "progress"
    LOG = "log"
    WARNING = "warning"
    RETRYING = "retrying"
    ARTIFACT = "artifact"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(str, Enum):
    PATCH = "patch"
    MANIFEST = "manifest"
    BACKUP = "backup"
    REPORT = "report"
    UNTRANSLATED_LIST = "untranslated_list"


def _require_mapping(value: object, model_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{model_name} payload must be a mapping")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: tuple[str, ...],
    model_name: str,
) -> None:
    actual = set(payload)
    required = set(expected)
    if actual != required:
        missing = sorted(required - actual)
        unknown = sorted(str(key) for key in actual - required)
        raise ValueError(
            f"{model_name} payload fields do not match schema; "
            f"missing={missing}, unknown={unknown}"
        )


def _require_string(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


def _optional_string(
    value: object,
    field_name: str,
    *,
    allow_empty: bool,
) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name, allow_empty=allow_empty)


def _require_integer(value: object, field_name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return value


def _optional_integer(value: object, field_name: str, *, minimum: int) -> int | None:
    if value is None:
        return None
    return _require_integer(value, field_name, minimum=minimum)


def _require_enum(value: object, enum_type: type[EnumType], field_name: str) -> EnumType:
    if not isinstance(value, enum_type):
        raise TypeError(f"{field_name} must be a {enum_type.__name__}")
    return value


def _enum_from_value(
    value: object,
    enum_type: type[EnumType],
    field_name: str,
) -> EnumType:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid {enum_type.__name__}") from exc


def _ordered_items(value: object, field_name: str) -> tuple[object, ...]:
    if (
        isinstance(value, (str, bytes, Mapping, set, frozenset))
        or not isinstance(value, Iterable)
    ):
        raise TypeError(f"{field_name} must be an ordered iterable collection")
    return tuple(value)


def _typed_tuple(value: object, item_type: type, field_name: str) -> tuple:
    items = _ordered_items(value, field_name)
    if any(not isinstance(item, item_type) for item in items):
        raise TypeError(f"{field_name} must contain only {item_type.__name__} values")
    return items


def _validate_json_value(value: object) -> None:
    if callable(value):
        raise ValueError("callable values are not permitted")
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if callable(key):
                raise ValueError("callable JSON object keys are not permitted")
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            if str.casefold(key) in _RESERVED_KEYS:
                raise ValueError("reserved key is not permitted")
            _validate_json_value(item)
        return
    raise ValueError("value is not a JSON value")


def _copy_json_object(value: object, field_name: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    try:
        _validate_json_value(value)
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must contain only finite, non-sensitive JSON values"
        ) from exc


def _require_utc_timestamp(value: object) -> str:
    timestamp = _require_string(value, "timestamp")
    if not timestamp.endswith("Z") or "T" not in timestamp:
        raise ValueError("timestamp must be a UTC ISO 8601 string ending in Z")
    try:
        parsed = datetime.fromisoformat(f"{timestamp[:-1]}+00:00")
    except ValueError as exc:
        raise ValueError("timestamp must be a UTC ISO 8601 string ending in Z") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be a UTC ISO 8601 string ending in Z")
    return timestamp


@dataclass(frozen=True)
class TaskProgress:
    completed: int
    total: int | None
    current_item: str | None = None

    _FIELDS = ("completed", "total", "current_item")

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "completed",
            _require_integer(self.completed, "completed", minimum=0),
        )
        object.__setattr__(
            self,
            "total",
            _optional_integer(self.total, "total", minimum=0),
        )
        object.__setattr__(
            self,
            "current_item",
            _optional_string(self.current_item, "current_item", allow_empty=True),
        )
        if self.total is not None and self.completed > self.total:
            raise ValueError("completed must not exceed total")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "completed": self.completed,
            "total": self.total,
            "current_item": self.current_item,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> TaskProgress:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        return cls(
            completed=values["completed"],
            total=values["total"],
            current_item=values["current_item"],
        )


@dataclass
class TaskStep:
    step_id: str
    title: str
    operation: RouteOperation
    state: StepState = StepState.QUEUED
    attempt: int = 0
    max_retries: int = 0

    _FIELDS = ("step_id", "title", "operation", "state", "attempt", "max_retries")

    def __post_init__(self) -> None:
        self.step_id = _require_string(self.step_id, "step_id")
        self.title = _require_string(self.title, "title")
        _require_enum(self.operation, RouteOperation, "operation")
        _require_enum(self.state, StepState, "state")
        self.attempt = _require_integer(self.attempt, "attempt", minimum=0)
        self.max_retries = _require_integer(
            self.max_retries,
            "max_retries",
            minimum=0,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "operation": self.operation.value,
            "state": self.state.value,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> TaskStep:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        return cls(
            step_id=values["step_id"],
            title=values["title"],
            operation=_enum_from_value(
                values["operation"],
                RouteOperation,
                "operation",
            ),
            state=_enum_from_value(values["state"], StepState, "state"),
            attempt=values["attempt"],
            max_retries=values["max_retries"],
        )


@dataclass
class TaskPlan:
    task_id: str
    project_id: str
    kind: str
    state: TaskState
    steps: tuple[TaskStep, ...]

    _FIELDS = ("task_id", "project_id", "kind", "state", "steps")

    def __post_init__(self) -> None:
        self.task_id = _require_string(self.task_id, "task_id")
        self.project_id = _require_string(self.project_id, "project_id")
        self.kind = _require_string(self.kind, "kind")
        _require_enum(self.state, TaskState, "state")
        self.steps = _typed_tuple(self.steps, TaskStep, "steps")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "kind": self.kind,
            "state": self.state.value,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> TaskPlan:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        steps = _ordered_items(values["steps"], "steps")
        return cls(
            task_id=values["task_id"],
            project_id=values["project_id"],
            kind=values["kind"],
            state=_enum_from_value(values["state"], TaskState, "state"),
            steps=tuple(TaskStep.from_dict(step) for step in steps),
        )


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    step_id: str | None
    sequence: int
    event_type: EventType
    timestamp: str
    summary: str
    progress: TaskProgress | None = None
    data: dict[str, JsonValue] = field(default_factory=dict)

    _FIELDS = (
        "task_id",
        "step_id",
        "sequence",
        "event_type",
        "timestamp",
        "summary",
        "progress",
        "data",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _require_string(self.task_id, "task_id"))
        object.__setattr__(
            self,
            "step_id",
            _optional_string(self.step_id, "step_id", allow_empty=False),
        )
        object.__setattr__(
            self,
            "sequence",
            _require_integer(self.sequence, "sequence", minimum=1),
        )
        _require_enum(self.event_type, EventType, "event_type")
        object.__setattr__(self, "timestamp", _require_utc_timestamp(self.timestamp))
        object.__setattr__(self, "summary", _require_string(self.summary, "summary"))
        if self.progress is not None and not isinstance(self.progress, TaskProgress):
            raise TypeError("progress must be a TaskProgress or None")
        object.__setattr__(self, "data", _copy_json_object(self.data, "data"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "summary": self.summary,
            "progress": None if self.progress is None else self.progress.to_dict(),
            "data": _copy_json_object(self.data, "data"),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> TaskEvent:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        progress_payload = values["progress"]
        if progress_payload is None:
            progress = None
        elif isinstance(progress_payload, Mapping):
            progress = TaskProgress.from_dict(progress_payload)
        else:
            raise TypeError("progress must be a mapping or None")
        return cls(
            task_id=values["task_id"],
            step_id=values["step_id"],
            sequence=values["sequence"],
            event_type=_enum_from_value(values["event_type"], EventType, "event_type"),
            timestamp=values["timestamp"],
            summary=values["summary"],
            progress=progress,
            data=values["data"],
        )


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    task_id: str
    step_id: str
    kind: ArtifactKind
    relative_path: str
    sha256: str | None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    _FIELDS = (
        "artifact_id",
        "task_id",
        "step_id",
        "kind",
        "relative_path",
        "sha256",
        "metadata",
    )

    def __post_init__(self) -> None:
        for field_name in ("artifact_id", "task_id", "step_id"):
            object.__setattr__(
                self,
                field_name,
                _require_string(getattr(self, field_name), field_name),
            )
        _require_enum(self.kind, ArtifactKind, "kind")
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_path(self.relative_path),
        )
        object.__setattr__(
            self,
            "sha256",
            _optional_string(self.sha256, "sha256", allow_empty=True),
        )
        object.__setattr__(
            self,
            "metadata",
            _copy_json_object(self.metadata, "metadata"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "artifact_id": self.artifact_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "kind": self.kind.value,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "metadata": _copy_json_object(self.metadata, "metadata"),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> Artifact:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        return cls(
            artifact_id=values["artifact_id"],
            task_id=values["task_id"],
            step_id=values["step_id"],
            kind=_enum_from_value(values["kind"], ArtifactKind, "kind"),
            relative_path=values["relative_path"],
            sha256=values["sha256"],
            metadata=values["metadata"],
        )


@dataclass(frozen=True)
class StepResult:
    artifacts: tuple[Artifact, ...] = ()
    data: dict[str, JsonValue] = field(default_factory=dict)

    _FIELDS = ("artifacts", "data")

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifacts",
            _typed_tuple(self.artifacts, Artifact, "artifacts"),
        )
        object.__setattr__(self, "data", _copy_json_object(self.data, "data"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "data": _copy_json_object(self.data, "data"),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> StepResult:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        artifacts = _ordered_items(values["artifacts"], "artifacts")
        return cls(
            artifacts=tuple(Artifact.from_dict(artifact) for artifact in artifacts),
            data=values["data"],
        )


__all__ = [
    "Artifact",
    "ArtifactKind",
    "EventType",
    "StepResult",
    "StepState",
    "TaskEvent",
    "TaskPlan",
    "TaskProgress",
    "TaskState",
    "TaskStep",
]
