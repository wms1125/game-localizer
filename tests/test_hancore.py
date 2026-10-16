import tempfile
import threading
import time
import unittest
from pathlib import Path

from game_localizer.hanengine import (
    Artifact,
    ArtifactKind,
    EvaluationStatus,
    EventType,
    HanCore,
    HanStore,
    RiskLevel,
    RouteBlockedError,
    RouteOperation,
    RoutePhase,
    RoutePlan,
    SegmentConflictError,
    SegmentDraft,
    SourceLocation,
    StepResult,
    TaskControl,
    TaskPlan,
    TaskState,
    TaskStep,
)


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_PROJECT_ID = "22222222-2222-4222-8222-222222222222"


def make_draft(
    *,
    segment_id: str = "line-1",
    source_fingerprint: str = "source-a",
) -> SegmentDraft:
    return SegmentDraft(
        segment_id=segment_id,
        source_text="Hello",
        source_language="en",
        speaker=None,
        context_before=(),
        context_after=(),
        placeholders=(),
        tags=("dialogue",),
        constraints=(),
        source_location=SourceLocation(relative_path="game/script.rpy", line=1),
        source_fingerprint=source_fingerprint,
        ocr_confidence=None,
        region_confidence=None,
        metadata={},
    )


def make_route(
    project_id: str = PROJECT_ID,
    *,
    provisional: bool = False,
    allowed: frozenset[RouteOperation] | None = None,
) -> RoutePlan:
    if allowed is None:
        allowed = (
            frozenset({RouteOperation.DETECT})
            if provisional
            else frozenset({RouteOperation.DETECT, RouteOperation.EXTRACT})
        )
    return RoutePlan(
        project_id=project_id,
        phase=RoutePhase.PROVISIONAL if provisional else RoutePhase.FINAL,
        risk_before=RiskLevel.H0_PROJECT,
        risk_after=RiskLevel.H0_PROJECT,
        allowed_operations=allowed,
        blocked_operations=frozenset(RouteOperation) - allowed,
        matches=(),
        evaluation_status=EvaluationStatus.COMPLETE,
        unknown_evidence=False,
        decision_reasons=(),
    )


class HanCoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = HanStore(Path(self.temporary.name))
        self.project = self.store.create_project("First", project_id=PROJECT_ID)
        self.project_db = self.store.open_project(PROJECT_ID)
        self.core = HanCore(self.project_db)

    def tearDown(self):
        self.project_db.close()
        self.store.close()
        self.temporary.cleanup()


class SegmentIngestionTests(HanCoreTestCase):
    def test_ingest_builds_deterministic_project_scoped_segments(self):
        first = self.core.ingest_segments((make_draft(),), target_language="zh-CN")
        self.assertEqual(first, self.project_db.list_segments())
        self.assertEqual(first[0].project_id, PROJECT_ID)
        self.assertEqual(first[0].target_language, "zh-CN")

        second = self.core.ingest_segments((make_draft(),), target_language="zh-CN")
        self.assertEqual(second, first)
        self.assertEqual(len(self.project_db.list_segments()), 1)

    def test_equal_duplicate_fingerprints_deduplicate(self):
        segments = self.core.ingest_segments(
            (make_draft(), make_draft()),
            target_language="zh-CN",
        )
        self.assertEqual(len(segments), 1)
        self.assertEqual(len(self.project_db.list_segments()), 1)

    def test_conflicting_duplicate_fingerprints_write_nothing(self):
        with self.assertRaisesRegex(SegmentConflictError, "line-1"):
            self.core.ingest_segments(
                (
                    make_draft(source_fingerprint="source-a"),
                    make_draft(source_fingerprint="source-b"),
                ),
                target_language="zh-CN",
            )
        self.assertEqual(self.project_db.list_segments(), ())


class RouteEnforcementTests(HanCoreTestCase):
    def test_provisional_route_rejects_extract_task(self):
        provisional_route = make_route(provisional=True)
        with self.assertRaisesRegex(RouteBlockedError, "extract"):
            self.core.create_task(
                kind="extract",
                route=provisional_route,
                steps=(
                    TaskStep(
                        "extract",
                        "Extract text",
                        RouteOperation.EXTRACT,
                    ),
                ),
            )

    def test_final_h0_route_persists_detect_and_extract_task(self):
        route = make_route()
        task = self.core.create_task(
            kind="extract",
            route=route,
            task_id="task-1",
            steps=(
                TaskStep("detect", "Detect", RouteOperation.DETECT),
                TaskStep("extract", "Extract", RouteOperation.EXTRACT),
            ),
        )
        self.assertEqual(self.project_db.get_task(task.task_id), task)
        self.assertEqual(self.project_db.get_route(RoutePhase.FINAL), route)

    def test_store_route_and_task_project_mismatches_are_rejected(self):
        foreign_route = make_route(OTHER_PROJECT_ID)
        with self.assertRaisesRegex(ValueError, "project"):
            self.core.create_task(
                kind="detect",
                route=foreign_route,
                steps=(TaskStep("detect", "Detect", RouteOperation.DETECT),),
            )

        task = TaskPlan(
            task_id="foreign-task",
            project_id=OTHER_PROJECT_ID,
            kind="detect",
            state=TaskState.QUEUED,
            steps=(TaskStep("detect", "Detect", RouteOperation.DETECT),),
        )
        with self.assertRaisesRegex(ValueError, "project"):
            self.core.run_task(
                task,
                route=make_route(),
                handlers={"detect": lambda context: StepResult()},
            )

    def test_run_task_rechecks_blocked_steps_before_handler_or_events(self):
        route = make_route(allowed=frozenset({RouteOperation.DETECT}))
        task = TaskPlan(
            task_id="manual-task",
            project_id=PROJECT_ID,
            kind="extract",
            state=TaskState.QUEUED,
            steps=(TaskStep("extract", "Extract", RouteOperation.EXTRACT),),
        )
        self.project_db.save_task(task)
        calls = []
        before_events = self.project_db.list_events(task.task_id)
        before_artifacts = self.project_db.list_artifacts(task.task_id)

        with self.assertRaisesRegex(RouteBlockedError, "extract"):
            self.core.run_task(
                task,
                route=route,
                handlers={"extract": lambda context: calls.append(context)},
            )

        self.assertEqual(calls, [])
        self.assertEqual(self.project_db.list_events(task.task_id), before_events)
        self.assertEqual(self.project_db.list_artifacts(task.task_id), before_artifacts)


class TaskExecutionTests(HanCoreTestCase):
    def test_success_persists_ordered_events_artifact_and_terminal_state(self):
        task = self.core.create_task(
            kind="detect",
            route=make_route(),
            task_id="task-success",
            steps=(TaskStep("detect", "Detect", RouteOperation.DETECT),),
        )
        artifact = Artifact(
            artifact_id="report-1",
            task_id=task.task_id,
            step_id="detect",
            kind=ArtifactKind.REPORT,
            relative_path="reports/detect.json",
            sha256="a" * 64,
        )

        def handler(context):
            context.log("detecting")
            context.artifact(artifact)
            return StepResult(artifacts=(artifact,), data={"matched": True})

        result = self.core.run_task(
            task,
            route=make_route(),
            handlers={"detect": handler},
        )
        restored = self.project_db.get_task(task.task_id)
        events = self.project_db.list_events(task.task_id)
        self.assertIs(result.state, TaskState.COMPLETED)
        self.assertEqual(restored, result)
        self.assertEqual([event.sequence for event in events], list(range(1, 7)))
        self.assertEqual(
            [event.event_type for event in events],
            [
                EventType.QUEUED,
                EventType.STARTED,
                EventType.LOG,
                EventType.ARTIFACT,
                EventType.COMPLETED,
                EventType.COMPLETED,
            ],
        )
        self.assertEqual(self.project_db.list_artifacts(task.task_id), (artifact,))

    def test_failed_and_cancelled_runs_persist_terminal_states(self):
        failed = self.core.create_task(
            kind="detect",
            route=make_route(),
            task_id="task-failed",
            steps=(TaskStep("detect", "Detect", RouteOperation.DETECT),),
        )

        def fail(context):
            raise RuntimeError("failure")

        failed_result = self.core.run_task(
            failed,
            route=make_route(),
            handlers={"detect": fail},
        )
        self.assertIs(failed_result.state, TaskState.FAILED)
        self.assertEqual(self.project_db.get_task(failed.task_id), failed_result)

        cancelled = self.core.create_task(
            kind="detect",
            route=make_route(),
            task_id="task-cancelled",
            steps=(TaskStep("detect", "Detect", RouteOperation.DETECT),),
        )
        control = TaskControl()
        control.cancel()
        cancelled_result = self.core.run_task(
            cancelled,
            route=make_route(),
            handlers={"detect": lambda context: StepResult()},
            control=control,
        )
        self.assertIs(cancelled_result.state, TaskState.CANCELLED)
        self.assertEqual(self.project_db.get_task(cancelled.task_id), cancelled_result)

    def test_running_task_observes_cancel_request_from_another_connection(self):
        task = self.core.create_task(
            kind="detect",
            route=make_route(),
            task_id="task-cross-process-cancel",
            steps=(TaskStep("detect", "Detect", RouteOperation.DETECT),),
        )
        started = threading.Event()
        results = []

        def worker() -> None:
            with self.store.open_project(PROJECT_ID) as worker_store:
                worker_core = HanCore(worker_store)
                restored = worker_store.get_task(task.task_id)

                def wait_for_cancel(context):
                    started.set()
                    while True:
                        context.checkpoint()
                        time.sleep(0.01)

                results.append(
                    worker_core.run_task(
                        restored,
                        route=make_route(),
                        handlers={"detect": wait_for_cancel},
                    )
                )

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.assertTrue(started.wait(timeout=2))

        requested_at = self.project_db.request_task_cancel(task.task_id)
        thread.join(timeout=3)

        self.assertFalse(thread.is_alive())
        self.assertTrue(requested_at.endswith("Z"))
        self.assertEqual(len(results), 1)
        self.assertIs(results[0].state, TaskState.CANCELLED)
        self.assertIs(
            self.project_db.get_task(task.task_id).state,
            TaskState.CANCELLED,
        )


if __name__ == "__main__":
    unittest.main()
