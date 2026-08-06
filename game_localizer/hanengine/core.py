from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import cast

from .routing import RouteOperation, RoutePhase, RoutePlan
from .segments import Segment, SegmentDraft
from .store import ProjectStore
from .tasks import (
    Artifact,
    EventType,
    StepHandler,
    TaskControl,
    TaskEvent,
    TaskPlan,
    TaskRunner,
    TaskState,
    TaskStep,
)


class RouteBlockedError(PermissionError):
    pass


class SegmentConflictError(ValueError):
    pass


def _require_route(route: object) -> RoutePlan:
    if not isinstance(route, RoutePlan):
        raise TypeError("route must be a RoutePlan")
    return route


def _require_task(task: object) -> TaskPlan:
    if not isinstance(task, TaskPlan):
        raise TypeError("task must be a TaskPlan")
    return task


class HanCore:
    def __init__(self, store: ProjectStore):
        if not isinstance(store, ProjectStore):
            raise TypeError("store must be a ProjectStore")
        self.store = store

    def ingest_segments(
        self,
        drafts: Iterable[SegmentDraft],
        *,
        target_language: str,
    ) -> tuple[Segment, ...]:
        if not isinstance(target_language, str) or not target_language:
            raise ValueError("target_language must not be empty")
        draft_items = tuple(drafts)
        if any(not isinstance(draft, SegmentDraft) for draft in draft_items):
            raise TypeError("drafts must contain SegmentDraft values")
        pending: dict[str, Segment] = {}
        for draft in draft_items:
            segment = Segment.from_draft(self.store.project_id, target_language, draft)
            existing = pending.get(segment.segment_id)
            if existing is not None:
                if existing.source_fingerprint != segment.source_fingerprint:
                    raise SegmentConflictError(
                        f"segment conflict for {segment.segment_id}"
                    )
                continue
            pending[segment.segment_id] = segment

        persisted = {item.segment_id: item for item in self.store.list_segments()}
        for segment_id, segment in pending.items():
            existing = persisted.get(segment_id)
            if existing is not None and existing.source_fingerprint != segment.source_fingerprint:
                raise SegmentConflictError(f"segment conflict for {segment_id}")
            if existing is not None:
                pending[segment_id] = existing
        new_segments = tuple(
            pending[item.segment_id]
            for item in draft_items
            if item.segment_id in pending
        )
        unique: dict[str, Segment] = {}
        for item in new_segments:
            unique.setdefault(item.segment_id, item)
        to_save = tuple(item for key, item in unique.items() if key not in persisted)
        if to_save:
            self.store.save_segments(to_save)
        return tuple(pending.values())

    @staticmethod
    def _validate_authorization(task: TaskPlan, route: RoutePlan, project_id: str) -> None:
        if route.project_id != project_id or task.project_id != project_id:
            raise ValueError("task, route and store must belong to the same project")
        if route.phase is RoutePhase.PROVISIONAL and any(
            step.operation is not RouteOperation.DETECT for step in task.steps
        ):
            blocked = next(
                step.operation.value
                for step in task.steps
                if step.operation is not RouteOperation.DETECT
            )
            raise RouteBlockedError(f"route does not authorize {blocked}")
        for step in task.steps:
            if step.operation not in route.allowed_operations:
                raise RouteBlockedError(
                    f"route does not authorize {step.operation.value}"
                )

    def create_task(
        self,
        *,
        kind: str,
        route: RoutePlan,
        steps: Iterable[TaskStep],
        task_id: str | None = None,
    ) -> TaskPlan:
        route = _require_route(route)
        step_items = tuple(steps)
        if any(not isinstance(step, TaskStep) for step in step_items):
            raise TypeError("steps must contain TaskStep values")
        task = TaskPlan(
            task_id=str(uuid.uuid4()) if task_id is None else task_id,
            project_id=self.store.project_id,
            kind=kind,
            state=TaskState.QUEUED,
            steps=step_items,
        )
        self._validate_authorization(task, route, self.store.project_id)
        self.store.save_route(route)
        self.store.save_task(task)
        return task

    def run_task(
        self,
        task: TaskPlan,
        *,
        route: RoutePlan,
        handlers: Mapping[str, StepHandler],
        control: TaskControl | None = None,
    ) -> TaskPlan:
        task = _require_task(task)
        route = _require_route(route)
        self._validate_authorization(task, route, self.store.project_id)
        self.store.save_route(route)
        if self.store.get_task(task.task_id) is None:
            self.store.save_task(task)

        def sink(event: TaskEvent) -> None:
            self.store.append_event(event)
            if event.event_type is EventType.ARTIFACT:
                if set(event.data) != {"artifact"} or not isinstance(event.data.get("artifact"), Mapping):
                    raise ValueError("artifact event data must contain exactly artifact")
                artifact = Artifact.from_dict(cast(Mapping[str, object], event.data["artifact"]))
                if artifact.task_id != task.task_id or artifact.step_id != event.step_id:
                    raise ValueError("artifact event ownership mismatch")
                self.store.save_artifact(artifact)
            current = self.store.get_task(task.task_id)
            if current is not None and (
                event.event_type in {EventType.COMPLETED, EventType.FAILED, EventType.CANCELLED}
                or event.step_id is not None
            ):
                self.store.save_task(task)

        try:
            result = TaskRunner(sink).run(task, handlers, control)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            task.state = TaskState.FAILED
            try:
                existing_events = self.store.list_events(task.task_id)
                next_sequence = (existing_events[-1].sequence if existing_events else 0) + 1
                self.store.append_event(
                    TaskEvent(
                        task_id=task.task_id,
                        step_id=None,
                        sequence=next_sequence,
                        event_type=EventType.FAILED,
                        timestamp=datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        summary="task orchestration failed",
                        data={"exception_type": type(exc).__name__},
                    )
                )
            finally:
                self.store.save_task(task)
            raise exc
        self.store.save_task(result)
        return result


__all__ = ["HanCore", "RouteBlockedError", "SegmentConflictError"]
