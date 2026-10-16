from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from game_localizer.adapters.contract import DeclaredMode
from game_localizer.hanengine.routing import RiskLevel, RouteOperation
from game_localizer.hanengine.store import TaskRetrySpec
from game_localizer.structured_workflow import (
    StructuredValidationFailed,
    StructuredWorkflowSession,
    format_guard_decision,
    format_persisted_task_event,
    project_id_for_root,
)


class StructuredWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / "data").mkdir(parents=True)
        (self.project / "data" / "System.json").write_text(
            json.dumps({"gameTitle": "Demo"}),
            encoding="utf-8",
        )
        self.state_root = self.root / "state"

    def test_project_id_is_stable_canonical_uuid4(self):
        first = project_id_for_root(self.project)
        second = project_id_for_root(self.project / "child" / "..")
        self.assertEqual(first, second)
        parsed = uuid.UUID(first)
        self.assertEqual(parsed.version, 4)
        self.assertEqual(str(parsed), first)

    def test_explicit_engine_runs_full_persisted_workflow_without_project_marker(self):
        events = []
        retry_spec = TaskRetrySpec.create(
            "engine",
            ("build", "rpg_maker_mv", str(self.project)),
        )
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            target_language="zh-CN",
            source_language="en",
            state_root=self.state_root,
            event_listener=events.append,
            retry_spec=retry_spec,
        ) as workflow:
            extracted = workflow.extract()
            self.assertEqual(extracted.catalog.engine_id, "rpg_maker_mv")
            self.assertEqual(extracted.selection.detection.engine_version, "user-declared")
            translated = extracted.catalog.translate({"Demo": "测试"})
            built = workflow.build(translated, self.root / "output")

            task_ids = (
                extracted.selection.detection_task.task_id,
                extracted.execution.task.task_id,
                built.validation.task.task_id,
                built.build.task.task_id,
                built.verification.task.task_id,
            )
            for task_id in task_ids:
                persisted = workflow.persisted_events(task_id)
                observed = tuple(event for event in events if event.task_id == task_id)
                self.assertEqual(observed, persisted)
                self.assertEqual(
                    [event.sequence for event in persisted],
                    list(range(1, len(persisted) + 1)),
                )
                self.assertEqual(
                    workflow.project_store.get_task_retry_spec(task_id),
                    retry_spec,
                )

            decision = format_guard_decision(extracted.selection.final_route)
            self.assertIn("risk=H0_PROJECT->H0_PROJECT", decision)
            self.assertIn("build", decision)
            self.assertIn("[HanTask persisted]", format_persisted_task_event(events[0]))
            self.assertTrue(built.verify_result.passed)

        localized = json.loads(
            (self.root / "output" / "data" / "System.json").read_text(encoding="utf-8")
        )
        self.assertEqual(localized["gameTitle"], "测试")
        self.assertTrue((self.state_root / "config.db").is_file())

    def test_restricted_baseline_exposes_detect_only_guard_decision(self):
        (self.project / "game.rpgproject").write_text("MV", encoding="utf-8")
        with StructuredWorkflowSession(
            self.project,
            engine_id="auto",
            state_root=self.state_root,
            declared_mode=DeclaredMode.PLAYER,
            user_baseline=RiskLevel.H2_RESTRICTED,
            adapter_baseline=RiskLevel.H2_RESTRICTED,
        ) as workflow:
            selection = workflow.detect()
            self.assertEqual(
                selection.final_route.allowed_operations,
                frozenset({RouteOperation.DETECT}),
            )
            self.assertIn("allowed=detect", format_guard_decision(selection.final_route))

    def test_validation_failure_is_persisted_and_never_creates_output(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            extracted = workflow.extract()
            output = self.root / "output"
            with self.assertRaises(StructuredValidationFailed) as raised:
                workflow.build(extracted.catalog, output)
            self.assertFalse(output.exists())
            persisted = workflow.persisted_events(raised.exception.execution.task.task_id)
            completion = next(
                event for event in persisted if event.step_id == "adapter-validate" and event.event_type.value == "completed"
            )
            self.assertFalse(completion.data["data"]["valid"])

    def test_state_root_inside_source_is_rejected_before_creation(self):
        unsafe = self.project / "state"
        with self.assertRaisesRegex(ValueError, "outside"):
            StructuredWorkflowSession(
                self.project,
                engine_id="rpg_maker_mv",
                state_root=unsafe,
            )
        self.assertFalse(unsafe.exists())

    def test_event_listener_failure_does_not_break_persisted_task(self):
        def fail_listener(event):
            raise RuntimeError("display unavailable")

        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
            event_listener=fail_listener,
        ) as workflow:
            outcome = workflow.extract()
            self.assertTrue(workflow.persisted_events(outcome.execution.task.task_id))


if __name__ == "__main__":
    unittest.main()
