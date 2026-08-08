from __future__ import annotations

import inspect
import json
import threading
import time
import unittest
from datetime import datetime

from game_localizer.hanengine.routing import RouteOperation
from game_localizer.hanengine.tasks import (
    Artifact,
    ArtifactKind,
    ContextEventEmitter,
    EventSink,
    EventType,
    StepHandler,
    StepResult,
    StepState,
    TaskCancelled,
    TaskContext,
    TaskControl,
    TaskEvent,
    TaskPlan,
    TaskProgress,
    TaskRunner,
    TaskState,
    TaskStep,
)


def make_step(
    step_id: str = "extract",
    *,
    operation: RouteOperation = RouteOperation.EXTRACT,
    max_retries: int = 0,
) -> TaskStep:
    return TaskStep(
        step_id=step_id,
        title=f"Run {step_id}",
        operation=operation,
        max_retries=max_retries,
    )


def make_plan(*steps: TaskStep, state: TaskState = TaskState.QUEUED) -> TaskPlan:
    if not steps:
        steps = (make_step(),)
    return TaskPlan(
        task_id="task-1",
        project_id="project-1",
        kind="localize",
        state=state,
        steps=steps,
    )


def make_artifact(
    context: TaskContext,
    *,
    artifact_id: str = "artifact-1",
    relative_path: str = "reports/extract.json",
) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        task_id=context.task_id,
        step_id=context.step_id,
        kind=ArtifactKind.REPORT,
        relative_path=relative_path,
        sha256=None,
    )


class PublicContractTests(unittest.TestCase):
    def test_public_signatures_are_exact(self):
        self.assertEqual(str(inspect.signature(TaskControl.pause)), "(self) -> 'None'")
        self.assertEqual(str(inspect.signature(TaskControl.resume)), "(self) -> 'None'")
        self.assertEqual(str(inspect.signature(TaskControl.cancel)), "(self) -> 'None'")
        self.assertEqual(
            str(inspect.signature(TaskControl.is_cancelled)),
            "(self) -> 'bool'",
        )
        self.assertEqual(
            str(inspect.signature(TaskControl.checkpoint)),
            "(self) -> 'None'",
        )
        self.assertEqual(
            str(inspect.signature(TaskContext)),
            "(task_id: 'str', step_id: 'str', control: 'TaskControl', "
            "emit_event: 'ContextEventEmitter')",
        )
        self.assertEqual(
            str(inspect.signature(TaskContext.progress)),
            "(self, completed: 'int', total: 'int | None', *, "
            "current_item: 'str | None' = None, "
            "data: 'dict[str, JsonValue] | None' = None) -> 'None'",
        )
        self.assertEqual(
            str(inspect.signature(TaskContext.log)),
            "(self, summary: 'str', data: 'dict[str, JsonValue] | None' = None) "
            "-> 'None'",
        )
        self.assertEqual(
            str(inspect.signature(TaskContext.warning)),
            "(self, summary: 'str', data: 'dict[str, JsonValue] | None' = None) "
            "-> 'None'",
        )
        self.assertEqual(
            str(inspect.signature(TaskContext.artifact)),
            "(self, artifact: 'Artifact') -> 'None'",
        )
        self.assertEqual(
            str(inspect.signature(TaskContext.checkpoint)),
            "(self) -> 'None'",
        )
        self.assertEqual(
            str(inspect.signature(TaskRunner)),
            "(event_sink: 'EventSink')",
        )
        self.assertEqual(
            str(inspect.signature(TaskRunner.run)),
            "(self, plan: 'TaskPlan', handlers: 'Mapping[str, StepHandler]', "
            "control: 'TaskControl | None' = None) -> 'TaskPlan'",
        )

    def test_task_five_exports_preserve_task_four_symbol_identities(self):
        import game_localizer.hanengine as hanengine
        import game_localizer.hanengine.tasks as tasks

        task_four_names = (
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
        )
        task_five_names = (
            "ContextEventEmitter",
            "EventSink",
            "StepHandler",
            "TaskCancelled",
            "TaskContext",
            "TaskControl",
            "TaskRunner",
        )
        for name in task_four_names + task_five_names:
            with self.subTest(name=name):
                self.assertIn(name, tasks.__all__)
                self.assertIn(name, hanengine.__all__)
                self.assertIs(getattr(hanengine, name), getattr(tasks, name))

        self.assertIs(hanengine.Artifact, Artifact)
        self.assertIs(hanengine.TaskEvent, TaskEvent)
        self.assertIs(hanengine.TaskPlan, TaskPlan)
        self.assertIs(hanengine.TaskProgress, TaskProgress)
        self.assertTrue(issubclass(TaskCancelled, RuntimeError))
        self.assertIsNotNone(EventSink)
        self.assertIsNotNone(ContextEventEmitter)
        self.assertIsNotNone(StepHandler)


class RunnerSuccessTests(unittest.TestCase):
    def test_happy_path_has_exact_event_order_and_nested_artifact(self):
        events: list[TaskEvent] = []
        plan = make_plan()

        def handler(context: TaskContext) -> StepResult:
            context.progress(1, 2, current_item="game/script.rpy")
            artifact = make_artifact(context)
            context.artifact(artifact)
            return StepResult(artifacts=(artifact,), data={"processed": 1})

        completed = TaskRunner(events.append).run(plan, {"extract": handler})

        self.assertIs(completed, plan)
        self.assertEqual(completed.state, TaskState.COMPLETED)
        self.assertEqual(completed.steps[0].state, StepState.COMPLETED)
        self.assertEqual(completed.steps[0].attempt, 1)
        self.assertEqual(
            [event.event_type for event in events],
            [
                EventType.QUEUED,
                EventType.STARTED,
                EventType.PROGRESS,
                EventType.ARTIFACT,
                EventType.COMPLETED,
                EventType.COMPLETED,
            ],
        )
        self.assertEqual(
            [event.step_id for event in events],
            [None, None, "extract", "extract", "extract", None],
        )
        self.assertEqual([event.task_id for event in events], ["task-1"] * 6)
        self.assertEqual([event.sequence for event in events], list(range(1, 7)))
        for event in events:
            self.assertTrue(event.timestamp.endswith("Z"))
            parsed = datetime.fromisoformat(f"{event.timestamp[:-1]}+00:00")
            self.assertEqual(parsed.utcoffset().total_seconds(), 0)

        artifact_event = events[3]
        expected_artifact = make_artifact_for_ids("task-1", "extract")
        self.assertEqual(
            artifact_event.data,
            {"artifact": expected_artifact.to_dict()},
        )
        self.assertEqual(
            Artifact.from_dict(artifact_event.data["artifact"]),
            expected_artifact,
        )
        self.assertEqual(
            events[4].data,
            {
                "artifacts": [expected_artifact.to_dict()],
                "data": {"processed": 1},
            },
        )

    def test_adapter_like_context_events_share_the_runner_sequence(self):
        events: list[TaskEvent] = []

        def adapter_like_handler(context: TaskContext) -> StepResult:
            context.progress(1, 3, data={"phase": "scan"})
            context.log("adapter inspected project", {"matched": True})
            context.warning("adapter used fallback", {"fallback": "safe"})
            return StepResult(data={"matched": True})

        TaskRunner(events.append).run(
            make_plan(),
            {"extract": adapter_like_handler},
        )
        self.assertEqual(
            [event.event_type for event in events],
            [
                EventType.QUEUED,
                EventType.STARTED,
                EventType.PROGRESS,
                EventType.LOG,
                EventType.WARNING,
                EventType.COMPLETED,
                EventType.COMPLETED,
            ],
        )
        self.assertEqual(
            [event.sequence for event in events],
            list(range(1, len(events) + 1)),
        )

    def test_completion_artifacts_are_stably_deduplicated_without_reemission(self):
        events: list[TaskEvent] = []

        def handler(context: TaskContext) -> StepResult:
            first = make_artifact(context, artifact_id="first")
            second = make_artifact(
                context,
                artifact_id="second",
                relative_path="reports/second.json",
            )
            context.artifact(first)
            context.artifact(second)
            return StepResult(artifacts=(first, second, first), data={"count": 3})

        TaskRunner(events.append).run(make_plan(), {"extract": handler})
        artifact_events = [
            event for event in events if event.event_type is EventType.ARTIFACT
        ]
        self.assertEqual(len(artifact_events), 2)
        completion = [
            event
            for event in events
            if event.event_type is EventType.COMPLETED
            and event.step_id == "extract"
        ][0]
        self.assertEqual(
            [item["artifact_id"] for item in completion.data["artifacts"]],
            ["first", "second"],
        )
        self.assertEqual(completion.data["data"], {"count": 3})


def make_artifact_for_ids(task_id: str, step_id: str) -> Artifact:
    return Artifact(
        artifact_id="artifact-1",
        task_id=task_id,
        step_id=step_id,
        kind=ArtifactKind.REPORT,
        relative_path="reports/extract.json",
        sha256=None,
    )


class RetryAndFailureTests(unittest.TestCase):
    def test_recoverable_exception_retries_and_succeeds(self):
        class RecoverableError(RuntimeError):
            pass

        events: list[TaskEvent] = []
        calls = 0

        def handler(context: TaskContext) -> StepResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RecoverableError("token=do-not-persist")
            context.log("retry succeeded")
            return StepResult(data={"processed": 1})

        plan = make_plan(make_step(max_retries=1))
        TaskRunner(events.append).run(plan, {"extract": handler})

        self.assertEqual(plan.state, TaskState.COMPLETED)
        self.assertEqual(plan.steps[0].state, StepState.COMPLETED)
        self.assertEqual(plan.steps[0].attempt, 2)
        retry_event = events[2]
        self.assertEqual(retry_event.event_type, EventType.RETRYING)
        self.assertEqual(retry_event.summary, "step failed")
        self.assertEqual(retry_event.data, {"exception_type": "RecoverableError"})
        self.assertNotIn("do-not-persist", json.dumps([e.to_dict() for e in events]))

    def test_exhausted_retries_fail_and_sanitize_exception(self):
        class CredentialFailure(RuntimeError):
            pass

        events: list[TaskEvent] = []

        def handler(context: TaskContext) -> StepResult:
            raise CredentialFailure("api_key=super-secret request_body=private")

        plan = make_plan(make_step(max_retries=1))
        TaskRunner(events.append).run(plan, {"extract": handler})

        self.assertEqual(plan.state, TaskState.FAILED)
        self.assertEqual(plan.steps[0].state, StepState.FAILED)
        self.assertEqual(plan.steps[0].attempt, 2)
        self.assertEqual(
            [event.event_type for event in events],
            [
                EventType.QUEUED,
                EventType.STARTED,
                EventType.RETRYING,
                EventType.FAILED,
            ],
        )
        for event in events[2:]:
            self.assertEqual(event.summary, "step failed")
            self.assertEqual(
                event.data,
                {"exception_type": "CredentialFailure"},
            )
        serialized = json.dumps([event.to_dict() for event in events])
        for secret in ("super-secret", "api_key", "request_body", "private"):
            self.assertNotIn(secret, serialized)

    def test_invalid_return_and_unemitted_artifact_are_handler_failures(self):
        cases = []

        def invalid_return(context: TaskContext):
            return None

        def unemitted_artifact(context: TaskContext) -> StepResult:
            return StepResult(artifacts=(make_artifact(context),))

        cases.append((invalid_return, "TypeError"))
        cases.append((unemitted_artifact, "ValueError"))
        for handler, exception_type in cases:
            events: list[TaskEvent] = []
            plan = make_plan()
            with self.subTest(exception_type=exception_type):
                TaskRunner(events.append).run(plan, {"extract": handler})
                self.assertEqual(plan.state, TaskState.FAILED)
                self.assertEqual(plan.steps[0].state, StepState.FAILED)
                self.assertEqual(events[-1].event_type, EventType.FAILED)
                self.assertEqual(
                    events[-1].data,
                    {"exception_type": exception_type},
                )


class CancellationAndPauseTests(unittest.TestCase):
    def test_cancellation_before_second_step_marks_remaining_steps(self):
        events: list[TaskEvent] = []
        control = TaskControl()
        first = make_step("first")
        second = make_step("second", operation=RouteOperation.BUILD)
        third = make_step("third", operation=RouteOperation.VERIFY)

        def first_handler(context: TaskContext) -> StepResult:
            control.cancel()
            return StepResult()

        def must_not_run(context: TaskContext) -> StepResult:
            self.fail("cancelled handler ran")

        plan = make_plan(first, second, third)
        TaskRunner(events.append).run(
            plan,
            {
                "first": first_handler,
                "second": must_not_run,
                "third": must_not_run,
            },
            control,
        )

        self.assertEqual(plan.state, TaskState.CANCELLED)
        self.assertEqual(
            [step.state for step in plan.steps],
            [StepState.COMPLETED, StepState.CANCELLED, StepState.CANCELLED],
        )
        self.assertEqual(
            sum(event.event_type is EventType.CANCELLED for event in events),
            1,
        )
        self.assertEqual(events[-1].event_type, EventType.CANCELLED)
        self.assertIsNone(events[-1].step_id)

    def test_pause_blocks_checkpoint_until_resume_without_leaking_thread(self):
        control = TaskControl()
        control.pause()
        entered = threading.Event()
        passed = threading.Event()

        def wait_at_checkpoint() -> None:
            entered.set()
            control.checkpoint()
            passed.set()

        thread = threading.Thread(target=wait_at_checkpoint)
        thread.start()
        try:
            self.assertTrue(entered.wait(1.0))
            self.assertFalse(passed.wait(0.05))
            self.assertTrue(thread.is_alive())
            control.resume()
            thread.join(1.0)
            self.assertFalse(thread.is_alive())
            self.assertTrue(passed.is_set())
        finally:
            control.resume()
            thread.join(1.0)

    def test_cancel_wakes_paused_runner_with_one_terminal_event(self):
        events: list[TaskEvent] = []
        started = threading.Event()
        failures: list[BaseException] = []
        control = TaskControl()
        control.pause()
        plan = make_plan(make_step("first"), make_step("second"))

        def sink(event: TaskEvent) -> None:
            events.append(event)
            if event.event_type is EventType.STARTED:
                started.set()

        def handler(context: TaskContext) -> StepResult:
            self.fail("paused handler ran")

        def run() -> None:
            try:
                TaskRunner(sink).run(
                    plan,
                    {"first": handler, "second": handler},
                    control,
                )
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(started.wait(1.0))
            self.assertTrue(thread.is_alive())
            control.cancel()
            thread.join(1.0)
            self.assertFalse(thread.is_alive())
        finally:
            control.cancel()
            thread.join(1.0)

        self.assertEqual(failures, [])
        self.assertEqual(plan.state, TaskState.CANCELLED)
        self.assertEqual(
            [step.state for step in plan.steps],
            [StepState.CANCELLED, StepState.CANCELLED],
        )
        self.assertEqual(
            [event.event_type for event in events],
            [EventType.QUEUED, EventType.STARTED, EventType.CANCELLED],
        )


class PreflightTests(unittest.TestCase):
    def test_invalid_plan_and_handler_inputs_do_not_mutate_or_start(self):
        invalid_cases = []

        nonqueued = make_plan(state=TaskState.RUNNING)
        invalid_cases.append((nonqueued, {"extract": lambda context: StepResult()}, None))

        duplicate = make_plan(make_step("same"), make_step("same"))
        invalid_cases.append((duplicate, {"same": lambda context: StepResult()}, None))

        empty_id = make_plan()
        empty_id.steps[0].step_id = ""
        invalid_cases.append((empty_id, {"": lambda context: StepResult()}, None))

        invalid_cases.append((make_plan(), [], None))
        invalid_cases.append((make_plan(), {}, None))
        invalid_cases.append((make_plan(), {"extract": object()}, None))
        invalid_cases.append(
            (make_plan(), {"extract": lambda context: StepResult()}, object())
        )

        for plan, handlers, control in invalid_cases:
            events: list[TaskEvent] = []
            before = plan.to_dict()
            with self.subTest(plan=before, handlers=handlers, control=control):
                with self.assertRaises((TypeError, ValueError)):
                    TaskRunner(events.append).run(plan, handlers, control)
                self.assertEqual(plan.to_dict(), before)
                self.assertNotIn(
                    EventType.STARTED,
                    [event.event_type for event in events],
                )

        events = []
        with self.assertRaises(TypeError):
            TaskRunner(events)

    def test_non_task_plan_is_rejected_before_started(self):
        events: list[TaskEvent] = []
        with self.assertRaises(TypeError):
            TaskRunner(events.append).run(object(), {})
        self.assertEqual(events, [])


class ContextValidationTests(unittest.TestCase):
    def test_artifact_rejects_wrong_type_and_mismatched_ids_before_emitting(self):
        calls: list[tuple] = []

        def emit(*args):
            calls.append(args)

        context = TaskContext("task-1", "extract", TaskControl(), emit)
        with self.assertRaises(TypeError):
            context.artifact(object())
        with self.assertRaises(ValueError):
            context.artifact(make_artifact_for_ids("other-task", "extract"))
        with self.assertRaises(ValueError):
            context.artifact(make_artifact_for_ids("task-1", "other-step"))
        self.assertEqual(calls, [])

    def test_sensitive_and_non_json_context_data_are_rejected_at_event_boundary(self):
        events: list[TaskEvent] = []

        def handler(context: TaskContext) -> StepResult:
            with self.assertRaises(ValueError):
                context.log("unsafe", {"nested": {"ToKeN": "secret"}})
            with self.assertRaises(ValueError):
                context.warning("unsafe", {"bad": object()})
            with self.assertRaises(ValueError):
                context.progress(2, 1)
            return StepResult()

        plan = make_plan()
        TaskRunner(events.append).run(plan, {"extract": handler})
        self.assertEqual(plan.state, TaskState.COMPLETED)
        self.assertNotIn(EventType.LOG, [event.event_type for event in events])
        self.assertNotIn(EventType.WARNING, [event.event_type for event in events])
        self.assertNotIn(EventType.PROGRESS, [event.event_type for event in events])
        self.assertNotIn("secret", json.dumps([event.to_dict() for event in events]))


class IndependentReviewRegressionTests(unittest.TestCase):
    class TwoViewDict(dict):
        def __init__(self):
            super().__init__({"safe": 1})
            self._changed = False

        def items(self):
            if not self._changed:
                safe_items = list(dict.items(self))
                dict.__setitem__(self, "token", "TOP-SECRET")
                self._changed = True
                return safe_items
            return dict.items(self)

    def test_event_constructor_revalidates_the_canonical_json_snapshot(self):
        with self.assertRaises(ValueError):
            TaskEvent(
                task_id="task-1",
                step_id="extract",
                sequence=1,
                event_type=EventType.LOG,
                timestamp="2026-08-05T12:30:45Z",
                summary="stateful data",
                data=self.TwoViewDict(),
            )

    def test_context_log_rejects_a_stateful_second_sensitive_view(self):
        events: list[TaskEvent] = []

        def handler(context: TaskContext) -> StepResult:
            with self.assertRaises(ValueError):
                context.log("stateful data", self.TwoViewDict())
            return StepResult()

        plan = make_plan()
        TaskRunner(events.append).run(plan, {"extract": handler})

        self.assertEqual(plan.state, TaskState.COMPLETED)
        self.assertNotIn(EventType.LOG, [event.event_type for event in events])
        self.assertNotIn("TOP-SECRET", json.dumps([event.to_dict() for event in events]))

    def test_queued_sink_mutation_cannot_replace_the_preflight_handler(self):
        events: list[TaskEvent] = []
        approved_calls = 0
        replacement_calls = 0

        def approved(context: TaskContext) -> StepResult:
            nonlocal approved_calls
            approved_calls += 1
            return StepResult()

        def replacement(context: TaskContext) -> StepResult:
            nonlocal replacement_calls
            replacement_calls += 1
            return StepResult()

        handlers = {"extract": approved}

        def sink(event: TaskEvent) -> None:
            events.append(event)
            if event.event_type is EventType.QUEUED:
                handlers["extract"] = replacement

        plan = make_plan()
        TaskRunner(sink).run(plan, handlers)

        self.assertEqual(plan.state, TaskState.COMPLETED)
        self.assertEqual(approved_calls, 1)
        self.assertEqual(replacement_calls, 0)
        self.assertEqual(
            [event.event_type for event in events],
            [EventType.QUEUED, EventType.STARTED, EventType.COMPLETED, EventType.COMPLETED],
        )

    def test_context_and_artifact_ids_use_plain_exact_strings(self):
        class DeceptiveString(str):
            def __eq__(self, other):
                return True

            def __ne__(self, other):
                return False

            __hash__ = str.__hash__

        context = TaskContext(
            DeceptiveString("task-real"),
            DeceptiveString("step-real"),
            TaskControl(),
            lambda *args: None,
        )
        self.assertIs(type(context.task_id), str)
        self.assertIs(type(context.step_id), str)

        events: list[TaskEvent] = []

        def handler(active_context: TaskContext) -> StepResult:
            artifact = Artifact(
                artifact_id="artifact-1",
                task_id=DeceptiveString("task-other"),
                step_id=DeceptiveString("step-other"),
                kind=ArtifactKind.REPORT,
                relative_path="reports/deceptive.json",
                sha256=None,
            )
            active_context.artifact(artifact)
            return StepResult(artifacts=(artifact,))

        plan = make_plan()
        TaskRunner(events.append).run(plan, {"extract": handler})

        self.assertEqual(plan.state, TaskState.FAILED)
        self.assertEqual(plan.steps[0].state, StepState.FAILED)
        self.assertNotIn(EventType.ARTIFACT, [event.event_type for event in events])
        self.assertEqual(events[-1].data, {"exception_type": "ValueError"})

    def test_artifact_serialization_does_not_dispatch_to_a_subclass_override(self):
        class ArtifactWithVirtualTrap(Artifact):
            def to_dict(self):
                raise AssertionError("virtual to_dict must not run")

        events: list[TaskEvent] = []

        def handler(context: TaskContext) -> StepResult:
            artifact = ArtifactWithVirtualTrap(
                artifact_id="artifact-1",
                task_id=context.task_id,
                step_id=context.step_id,
                kind=ArtifactKind.REPORT,
                relative_path="reports/trusted.json",
                sha256=None,
            )
            context.artifact(artifact)
            return StepResult(artifacts=(artifact,))

        plan = make_plan()
        TaskRunner(events.append).run(plan, {"extract": handler})

        self.assertEqual(plan.state, TaskState.COMPLETED)
        artifact_event = [
            event for event in events if event.event_type is EventType.ARTIFACT
        ][0]
        self.assertEqual(artifact_event.data["artifact"]["artifact_id"], "artifact-1")

    def test_returned_artifact_provenance_does_not_use_virtual_equality(self):
        class AlwaysEqualArtifact(Artifact):
            def __eq__(self, other):
                return True

        events: list[TaskEvent] = []

        def handler(context: TaskContext) -> StepResult:
            emitted = make_artifact(context, artifact_id="emitted")
            context.artifact(emitted)
            never_emitted = AlwaysEqualArtifact(
                artifact_id="never-emitted",
                task_id=context.task_id,
                step_id=context.step_id,
                kind=ArtifactKind.REPORT,
                relative_path="reports/never-emitted.json",
                sha256=None,
            )
            return StepResult(artifacts=(never_emitted,))

        plan = make_plan()
        TaskRunner(events.append).run(plan, {"extract": handler})

        self.assertEqual(plan.state, TaskState.FAILED)
        self.assertEqual(plan.steps[0].state, StepState.FAILED)
        self.assertEqual(events[-1].event_type, EventType.FAILED)
        self.assertEqual(events[-1].data, {"exception_type": "ValueError"})
        self.assertFalse(
            any(
                event.event_type is EventType.COMPLETED
                and event.step_id == "extract"
                for event in events
            )
        )

    def test_mutated_step_result_data_fails_inside_the_attempt_boundary(self):
        mutations = (
            ("reserved", "token", "TOP-SECRET"),
            ("non-json", "bad", object()),
        )
        for label, key, value in mutations:
            events: list[TaskEvent] = []

            def handler(context: TaskContext) -> StepResult:
                result = StepResult(data={"safe": 1})
                result.data[key] = value
                return result

            plan = make_plan()
            with self.subTest(label=label):
                completed = TaskRunner(events.append).run(plan, {"extract": handler})
                self.assertIs(completed, plan)
                self.assertEqual(plan.state, TaskState.FAILED)
                self.assertEqual(plan.steps[0].state, StepState.FAILED)
                self.assertEqual(
                    [event.event_type for event in events],
                    [EventType.QUEUED, EventType.STARTED, EventType.FAILED],
                )
                self.assertEqual(events[-1].data, {"exception_type": "ValueError"})
                serialized = json.dumps([event.to_dict() for event in events])
                self.assertNotIn("TOP-SECRET", serialized)
                self.assertNotIn("token", serialized)

    def test_concurrent_context_events_are_delivered_in_strict_sequence(self):
        class SlowDict(dict):
            def items(self):
                time.sleep(0.01)
                return dict.items(self)

        events: list[TaskEvent] = []
        worker_count = 8

        def handler(context: TaskContext) -> StepResult:
            barrier = threading.Barrier(worker_count + 1)
            errors: list[BaseException] = []

            def emit_log(worker_id: int) -> None:
                try:
                    barrier.wait(timeout=1.0)
                    context.log(
                        f"worker {worker_id}",
                        SlowDict({"worker_id": worker_id}),
                    )
                except BaseException as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=emit_log, args=(worker_id,))
                for worker_id in range(worker_count)
            ]
            for thread in threads:
                thread.start()
            barrier.wait(timeout=1.0)
            for thread in threads:
                thread.join(1.0)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            return StepResult()

        plan = make_plan()
        TaskRunner(events.append).run(plan, {"extract": handler})

        self.assertEqual(plan.state, TaskState.COMPLETED)
        self.assertEqual(
            [event.sequence for event in events],
            list(range(1, len(events) + 1)),
        )
        self.assertEqual(
            sum(event.event_type is EventType.LOG for event in events),
            worker_count,
        )


if __name__ == "__main__":
    unittest.main()
