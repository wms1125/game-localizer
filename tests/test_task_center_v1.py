import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import cli
from game_localizer.hanengine import (
    EvaluationStatus,
    EventType,
    HanStore,
    RiskLevel,
    RouteOperation,
    RoutePhase,
    RoutePlan,
    StepState,
    TaskEvent,
    TaskPlan,
    TaskRetrySpec,
    TaskState,
    TaskStep,
    TranslationResult,
)


PROJECT_ID = "44444444-4444-4444-8444-444444444444"


def make_route(project_id: str) -> RoutePlan:
    allowed = frozenset({RouteOperation.DETECT})
    return RoutePlan(
        project_id=project_id,
        phase=RoutePhase.PROVISIONAL,
        risk_before=RiskLevel.H0_PROJECT,
        risk_after=RiskLevel.H0_PROJECT,
        allowed_operations=allowed,
        blocked_operations=frozenset(RouteOperation) - allowed,
        matches=(),
        evaluation_status=EvaluationStatus.COMPLETE,
        unknown_evidence=False,
        decision_reasons=(),
    )


class TaskCenterCliTests(unittest.TestCase):
    def test_tasks_list_show_and_cancel_use_persisted_store(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            with HanStore(state_root) as store:
                project = store.create_project("Task Center", project_id=PROJECT_ID)
                task = TaskPlan(
                    task_id="task-cli-control",
                    project_id=project.project_id,
                    kind="adapter-detect",
                    state=TaskState.QUEUED,
                    steps=(
                        TaskStep(
                            "adapter-detect",
                            "Detect engine",
                            RouteOperation.DETECT,
                        ),
                    ),
                )
                with store.open_project(project.project_id) as project_store:
                    project_store.save_route(make_route(project.project_id))
                    project_store.save_task(task)
                    project_store.append_event(
                        TaskEvent(
                            task_id=task.task_id,
                            step_id=None,
                            sequence=1,
                            event_type=EventType.QUEUED,
                            timestamp="2026-08-07T00:00:00Z",
                            summary="queued",
                        )
                    )
                    project_store.save_task_retry_spec(
                        task.task_id,
                        TaskRetrySpec.create(
                            "engine",
                            ("extract", "auto", "C:/Games/Demo"),
                        ),
                    )

            list_output = io.StringIO()
            with redirect_stdout(list_output):
                list_code = cli.run_tasks(
                    ["list", "--state-root", str(state_root), "--json"]
                )
            listed = json.loads(list_output.getvalue())

            show_output = io.StringIO()
            with redirect_stdout(show_output):
                show_code = cli.run_tasks(
                    [
                        "show",
                        task.task_id,
                        "--state-root",
                        str(state_root),
                        "--json",
                    ]
                )
            shown = json.loads(show_output.getvalue())

            cancel_output = io.StringIO()
            with redirect_stdout(cancel_output):
                cancel_code = cli.run_tasks(
                    ["cancel", task.task_id, "--state-root", str(state_root)]
                )

            self.assertEqual((list_code, show_code, cancel_code), (0, 0, 0))
            self.assertEqual([item["task_id"] for item in listed], [task.task_id])
            self.assertEqual(shown["task_id"], task.task_id)
            self.assertTrue(shown["retryable"])
            self.assertIn("Cancellation requested", cancel_output.getvalue())
            with HanStore(state_root) as reopened:
                status = reopened.find_task_status(task.task_id)
            self.assertIsNotNone(status.cancel_requested_at)

    def test_retry_after_restart_reads_fresh_cloud_token_and_resumes_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            data = project / "data"
            data.mkdir(parents=True)
            (project / "game.rpgproject").write_text("MV", encoding="utf-8")
            (data / "System.json").write_text(
                json.dumps({"gameTitle": "Demo", "currencyUnit": "Gold"}),
                encoding="utf-8",
            )
            state_root = root / "state"
            output = root / "output"
            observed_tokens = []
            provider = Mock()
            provider.translate.side_effect = (
                TranslationResult(
                    "Localized Demo",
                    "cloud",
                    "test-model",
                    1.0,
                ),
                RuntimeError("temporary cloud failure"),
            )

            def make_provider(_endpoint, *, token_provider):
                observed_tokens.append(token_provider())
                return provider

            old_token = os.environ.get("HANENGINE_TRANSLATION_TOKEN")
            try:
                os.environ["HANENGINE_TRANSLATION_TOKEN"] = "first-process-token"
                with (
                    patch.object(
                        cli,
                        "CloudTranslationProvider",
                        side_effect=make_provider,
                    ),
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    first_code = cli.run_engine(
                        [
                            "localize",
                            "rpg_maker_mv",
                            str(project),
                            "--output",
                            str(output),
                            "--cloud-endpoint",
                            "https://example.test/translate",
                            "--state-root",
                            str(state_root),
                            "--quiet-progress",
                        ]
                    )

                with HanStore(state_root) as store:
                    retryable = [
                        item
                        for item in store.list_task_statuses()
                        if item.retry_spec is not None
                        and item.task.kind == "pipeline-translate"
                    ]
                    self.assertEqual(len(retryable), 1)
                    old_task_id = retryable[0].task.task_id
                    with store.open_project(
                        retryable[0].project.project_id
                    ) as project_store:
                        stale = project_store.get_task(old_task_id)
                        stale.state = TaskState.RUNNING
                        stale.steps[0].state = StepState.RUNNING
                        project_store.save_task(stale)

                os.environ["HANENGINE_TRANSLATION_TOKEN"] = "second-process-token"
                provider.translate.side_effect = None
                provider.translate.return_value = TranslationResult(
                    "Localized Gold",
                    "cloud",
                    "test-model",
                    1.0,
                )
                retry_output = io.StringIO()
                with (
                    patch.object(
                        cli,
                        "CloudTranslationProvider",
                        side_effect=make_provider,
                    ),
                    redirect_stdout(retry_output),
                ):
                    retry_code = cli.run_tasks(
                        ["retry", old_task_id, "--state-root", str(state_root)]
                    )
            finally:
                if old_token is None:
                    os.environ.pop("HANENGINE_TRANSLATION_TOKEN", None)
                else:
                    os.environ["HANENGINE_TRANSLATION_TOKEN"] = old_token

            self.assertEqual((first_code, retry_code), (1, 0))
            self.assertEqual(
                observed_tokens,
                ["first-process-token", "second-process-token"],
            )
            self.assertEqual(provider.translate.call_count, 3)
            self.assertIn("resumed 1", retry_output.getvalue())

            with HanStore(state_root) as reopened:
                old_status = reopened.find_task_status(old_task_id)
                descendants = [
                    item
                    for item in reopened.list_task_statuses()
                    if item.retry_spec is not None
                    and item.retry_spec.parent_task_id == old_task_id
                    and item.task.kind == "pipeline-translate"
                ]
            self.assertIs(old_status.task.state, TaskState.FAILED)
            self.assertIn("process_restart", old_status.failure_reason)
            self.assertEqual(len(descendants), 1)
            persisted = b"".join(path.read_bytes() for path in state_root.rglob("*.db"))
            self.assertNotIn(b"first-process-token", persisted)
            self.assertNotIn(b"second-process-token", persisted)


if __name__ == "__main__":
    unittest.main()
