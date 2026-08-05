from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Condition, RLock
from typing import Callable, TypeVar

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
        canonical = json.loads(encoded)
        _validate_json_value(canonical)
        return canonical
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


def _canonical_string(value: object, field_name: str) -> str:
    checked = _require_string(value, field_name)
    canonical = _copy_json_object({"value": checked}, field_name)["value"]
    if type(canonical) is not str:
        raise TypeError(f"{field_name} must be a string")
    return canonical


def _canonical_artifact_payload(artifact: object) -> dict[str, JsonValue]:
    if not isinstance(artifact, Artifact):
        raise TypeError("artifact must be an Artifact")
    canonical = _copy_json_object(
        {"artifact": Artifact.to_dict(artifact)},
        "artifact",
    )["artifact"]
    if not isinstance(canonical, dict):
        raise TypeError("artifact must serialize to a JSON object")
    trusted = Artifact.from_dict(canonical)
    return Artifact.to_dict(trusted)


class TaskCancelled(RuntimeError):
    pass


class TaskControl:
    def __init__(self) -> None:
        self._condition = Condition()
        self._paused = False
        self._cancelled = False

    def pause(self) -> None:
        with self._condition:
            self._paused = True

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    def cancel(self) -> None:
        with self._condition:
            self._cancelled = True
            self._condition.notify_all()

    def is_cancelled(self) -> bool:
        with self._condition:
            return self._cancelled

    def checkpoint(self) -> None:
        with self._condition:
            while self._paused and not self._cancelled:
                self._condition.wait()
            if self._cancelled:
                raise TaskCancelled("task cancelled")


EventSink = Callable[[TaskEvent], None]
ContextEventEmitter = Callable[
    [str, str, EventType, str, TaskProgress | None, dict[str, JsonValue]],
    TaskEvent,
]


class TaskContext:
    def __init__(
        self,
        task_id: str,
        step_id: str,
        control: TaskControl,
        emit_event: ContextEventEmitter,
    ):
        self._task_id = _canonical_string(task_id, "task_id")
        self._step_id = _canonical_string(step_id, "step_id")
        if not isinstance(control, TaskControl):
            raise TypeError("control must be a TaskControl")
        if not callable(emit_event):
            raise TypeError("emit_event must be callable")
        self._control = control
        self._emit_event = emit_event
        self._emitted_artifacts: list[dict[str, JsonValue]] = []

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def step_id(self) -> str:
        return self._step_id

    def progress(
        self,
        completed: int,
        total: int | None,
        *,
        current_item: str | None = None,
        data: dict[str, JsonValue] | None = None,
    ) -> None:
        progress = TaskProgress(completed, total, current_item)
        self._emit_event(
            self._task_id,
            self._step_id,
            EventType.PROGRESS,
            "step progress",
            progress,
            {} if data is None else data,
        )

    def log(
        self,
        summary: str,
        data: dict[str, JsonValue] | None = None,
    ) -> None:
        self._emit_event(
            self._task_id,
            self._step_id,
            EventType.LOG,
            summary,
            None,
            {} if data is None else data,
        )

    def warning(
        self,
        summary: str,
        data: dict[str, JsonValue] | None = None,
    ) -> None:
        self._emit_event(
            self._task_id,
            self._step_id,
            EventType.WARNING,
            summary,
            None,
            {} if data is None else data,
        )

    def artifact(self, artifact: Artifact) -> None:
        payload = _canonical_artifact_payload(artifact)
        if payload["task_id"] != self._task_id:
            raise ValueError("artifact task_id must match the context")
        if payload["step_id"] != self._step_id:
            raise ValueError("artifact step_id must match the context")
        self._emit_event(
            self._task_id,
            self._step_id,
            EventType.ARTIFACT,
            "artifact created",
            None,
            {"artifact": payload},
        )
        self._emitted_artifacts.append(payload)

    def checkpoint(self) -> None:
        self._control.checkpoint()


StepHandler = Callable[[TaskContext], StepResult]


class TaskRunner:
    def __init__(self, event_sink: EventSink):
        if not callable(event_sink):
            raise TypeError("event_sink must be callable")
        self._event_sink = event_sink

    def run(
        self,
        plan: TaskPlan,
        handlers: Mapping[str, StepHandler],
        control: TaskControl | None = None,
    ) -> TaskPlan:
        handler_snapshot = self._validate_invocation(plan, handlers, control)
        task_control = TaskControl() if control is None else control
        sequence = 0
        event_lock = RLock()

        def emit_event(
            task_id: str,
            step_id: str | None,
            event_type: EventType,
            summary: str,
            progress: TaskProgress | None,
            data: dict[str, JsonValue],
        ) -> TaskEvent:
            nonlocal sequence
            with event_lock:
                next_sequence = sequence + 1
                event = TaskEvent(
                    task_id=task_id,
                    step_id=step_id,
                    sequence=next_sequence,
                    event_type=event_type,
                    timestamp=datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    summary=summary,
                    progress=progress,
                    data=data,
                )
                sequence = next_sequence
                self._event_sink(event)
                return event

        emit_event(
            plan.task_id,
            None,
            EventType.QUEUED,
            "task queued",
            None,
            {},
        )
        plan.state = TaskState.RUNNING
        emit_event(
            plan.task_id,
            None,
            EventType.STARTED,
            "task started",
            None,
            {},
        )

        for step_index, step in enumerate(plan.steps):
            context = TaskContext(
                plan.task_id,
                step.step_id,
                task_control,
                emit_event,
            )
            while True:
                try:
                    task_control.checkpoint()
                except TaskCancelled:
                    return self._cancel(plan, step_index, emit_event)

                step.attempt += 1
                step.state = StepState.RUNNING
                plan.state = TaskState.RUNNING
                try:
                    result = handler_snapshot[step_index](context)
                    if not isinstance(result, StepResult):
                        raise TypeError("handler must return a StepResult")
                    canonical_artifacts = tuple(
                        _canonical_artifact_payload(artifact)
                        for artifact in result.artifacts
                    )
                    canonical_data = _copy_json_object(result.data, "data")
                    for artifact_payload in canonical_artifacts:
                        if artifact_payload not in context._emitted_artifacts:
                            raise ValueError(
                                "returned artifacts must be emitted through the context"
                            )

                    unique_artifacts: list[dict[str, JsonValue]] = []
                    artifact_ids: set[str] = set()
                    for artifact_payload in canonical_artifacts:
                        artifact_id = artifact_payload["artifact_id"]
                        if artifact_id not in artifact_ids:
                            artifact_ids.add(artifact_id)
                            unique_artifacts.append(artifact_payload)
                    completion_data = _copy_json_object(
                        {
                            "artifacts": unique_artifacts,
                            "data": canonical_data,
                        },
                        "data",
                    )
                except TaskCancelled:
                    return self._cancel(plan, step_index, emit_event)
                except Exception as exc:
                    failure_data = {"exception_type": type(exc).__name__}
                    if step.attempt <= step.max_retries:
                        step.state = StepState.RETRYING
                        plan.state = TaskState.RETRYING
                        emit_event(
                            plan.task_id,
                            step.step_id,
                            EventType.RETRYING,
                            "step failed",
                            None,
                            failure_data,
                        )
                        continue
                    step.state = StepState.FAILED
                    plan.state = TaskState.FAILED
                    emit_event(
                        plan.task_id,
                        step.step_id,
                        EventType.FAILED,
                        "step failed",
                        None,
                        failure_data,
                    )
                    return plan

                step.state = StepState.COMPLETED
                emit_event(
                    plan.task_id,
                    step.step_id,
                    EventType.COMPLETED,
                    "step completed",
                    None,
                    completion_data,
                )
                break

        plan.state = TaskState.COMPLETED
        emit_event(
            plan.task_id,
            None,
            EventType.COMPLETED,
            "task completed",
            None,
            {},
        )
        return plan

    def _validate_invocation(
        self,
        plan: TaskPlan,
        handlers: Mapping[str, StepHandler],
        control: TaskControl | None,
    ) -> tuple[StepHandler, ...]:
        if not isinstance(plan, TaskPlan):
            raise TypeError("plan must be a TaskPlan")
        if plan.state is not TaskState.QUEUED:
            raise ValueError("plan must be queued")
        if not isinstance(handlers, Mapping):
            raise TypeError("handlers must be a mapping")
        if control is not None and not isinstance(control, TaskControl):
            raise TypeError("control must be a TaskControl or None")

        step_ids: list[str] = []
        for step in plan.steps:
            if not isinstance(step.step_id, str) or not step.step_id:
                raise ValueError("step IDs must not be empty")
            if step.step_id in step_ids:
                raise ValueError("step IDs must be unique")
            step_ids.append(step.step_id)

        handler_snapshot: list[StepHandler] = []
        for step_id in step_ids:
            try:
                handler = handlers[step_id]
            except KeyError as exc:
                raise ValueError("every step must have a handler") from exc
            if not callable(handler):
                raise TypeError("step handlers must be callable")
            handler_snapshot.append(handler)
        return tuple(handler_snapshot)

    @staticmethod
    def _cancel(
        plan: TaskPlan,
        active_index: int,
        emit_event: Callable[
            [
                str,
                str | None,
                EventType,
                str,
                TaskProgress | None,
                dict[str, JsonValue],
            ],
            TaskEvent,
        ],
    ) -> TaskPlan:
        plan.steps[active_index].state = StepState.CANCELLED
        for step in plan.steps[active_index + 1 :]:
            if step.state is StepState.QUEUED:
                step.state = StepState.CANCELLED
        plan.state = TaskState.CANCELLED
        emit_event(
            plan.task_id,
            None,
            EventType.CANCELLED,
            "task cancelled",
            None,
            {},
        )
        return plan


__all__ = [
    "Artifact",
    "ArtifactKind",
    "ContextEventEmitter",
    "EventSink",
    "EventType",
    "StepHandler",
    "StepResult",
    "StepState",
    "TaskCancelled",
    "TaskContext",
    "TaskControl",
    "TaskEvent",
    "TaskPlan",
    "TaskProgress",
    "TaskRunner",
    "TaskState",
    "TaskStep",
]
