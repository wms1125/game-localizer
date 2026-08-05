from __future__ import annotations

import json
import math
import unittest
from dataclasses import FrozenInstanceError

from game_localizer.hanengine.routing import RouteOperation
from game_localizer.hanengine.tasks import (
    Artifact,
    ArtifactKind,
    EventType,
    StepResult,
    StepState,
    TaskEvent,
    TaskPlan,
    TaskProgress,
    TaskState,
    TaskStep,
)


def make_step(**changes: object) -> TaskStep:
    values: dict[str, object] = {
        "step_id": "detect",
        "title": "Detect engine",
        "operation": RouteOperation.DETECT,
        "state": StepState.QUEUED,
        "attempt": 0,
        "max_retries": 1,
    }
    values.update(changes)
    return TaskStep(**values)


def make_event(**changes: object) -> TaskEvent:
    values: dict[str, object] = {
        "task_id": "task-1",
        "step_id": "detect",
        "sequence": 1,
        "event_type": EventType.PROGRESS,
        "timestamp": "2026-08-05T12:30:45.123456Z",
        "summary": "Detection in progress",
        "progress": TaskProgress(completed=1, total=2, current_item="game.exe"),
        "data": {"engine": "renpy", "nested": {"candidates": ["renpy", "unity"]}},
    }
    values.update(changes)
    return TaskEvent(**values)


def make_artifact(**changes: object) -> Artifact:
    values: dict[str, object] = {
        "artifact_id": "artifact-1",
        "task_id": "task-1",
        "step_id": "build",
        "kind": ArtifactKind.PATCH,
        "relative_path": "output/patch.zip",
        "sha256": "abc123",
        "metadata": {"files": 3, "nested": {"languages": ["zh-Hans"]}},
    }
    values.update(changes)
    return Artifact(**values)


class EnumContractTests(unittest.TestCase):
    def test_enum_values_are_exact(self):
        expected_states = [
            "queued",
            "running",
            "paused",
            "retrying",
            "completed",
            "failed",
            "cancelled",
        ]
        self.assertEqual([item.value for item in TaskState], expected_states)
        self.assertEqual([item.value for item in StepState], expected_states)
        self.assertEqual(
            [item.value for item in EventType],
            [
                "queued",
                "started",
                "progress",
                "log",
                "warning",
                "retrying",
                "artifact",
                "completed",
                "failed",
                "cancelled",
            ],
        )
        self.assertEqual(
            [item.value for item in ArtifactKind],
            ["patch", "manifest", "backup", "report", "untranslated_list"],
        )


class TaskProgressTests(unittest.TestCase):
    def test_progress_round_trips_exact_schema(self):
        progress = TaskProgress(completed=2, total=5, current_item="script.rpy")
        self.assertEqual(
            progress.to_dict(),
            {"completed": 2, "total": 5, "current_item": "script.rpy"},
        )
        self.assertEqual(TaskProgress.from_dict(progress.to_dict()), progress)
        self.assertEqual(
            TaskProgress(completed=2, total=None).to_dict(),
            {"completed": 2, "total": None, "current_item": None},
        )

    def test_progress_rejects_invalid_counts(self):
        for values in (
            {"completed": -1, "total": None},
            {"completed": True, "total": None},
            {"completed": 1, "total": -1},
            {"completed": 1, "total": False},
            {"completed": 2, "total": 1},
        ):
            with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                TaskProgress(**values)


class TaskPlanTests(unittest.TestCase):
    def test_task_step_round_trips_and_normalizes_values(self):
        step = make_step()
        self.assertEqual(
            step.to_dict(),
            {
                "step_id": "detect",
                "title": "Detect engine",
                "operation": "detect",
                "state": "queued",
                "attempt": 0,
                "max_retries": 1,
            },
        )
        self.assertEqual(TaskStep.from_dict(step.to_dict()), step)

    def test_task_step_validates_strings_enums_and_retry_counts(self):
        for changes in (
            {"step_id": ""},
            {"title": ""},
            {"operation": "detect"},
            {"state": "queued"},
            {"attempt": -1},
            {"attempt": True},
            {"max_retries": -1},
            {"max_retries": False},
        ):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                make_step(**changes)

    def test_task_plan_round_trips_with_steps(self):
        plan = TaskPlan(
            task_id="task-1",
            project_id="project-a",
            kind="extract",
            state=TaskState.QUEUED,
            steps=(
                TaskStep(
                    step_id="detect",
                    title="Detect engine",
                    operation=RouteOperation.DETECT,
                    state=StepState.QUEUED,
                    max_retries=0,
                ),
            ),
        )
        self.assertEqual(TaskPlan.from_dict(plan.to_dict()), plan)
        self.assertEqual(
            tuple(plan.to_dict()),
            ("task_id", "project_id", "kind", "state", "steps"),
        )

    def test_task_plan_copies_ordered_steps_and_rejects_invalid_inputs(self):
        steps = [make_step()]
        plan = TaskPlan("task-1", "project-a", "detect", TaskState.QUEUED, steps)
        steps.clear()
        self.assertEqual(plan.steps, (make_step(),))

        for values in (
            ("", "project-a", "detect", TaskState.QUEUED, ()),
            ("task-1", "", "detect", TaskState.QUEUED, ()),
            ("task-1", "project-a", "", TaskState.QUEUED, ()),
            ("task-1", "project-a", "detect", "queued", ()),
            ("task-1", "project-a", "detect", TaskState.QUEUED, frozenset()),
            ("task-1", "project-a", "detect", TaskState.QUEUED, ("bad",)),
        ):
            with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                TaskPlan(*values)


class TaskEventTests(unittest.TestCase):
    def test_event_round_trips_exact_schema_and_allows_task_level_events(self):
        event = make_event(step_id=None)
        payload = event.to_dict()
        self.assertEqual(
            tuple(payload),
            (
                "task_id",
                "step_id",
                "sequence",
                "event_type",
                "timestamp",
                "summary",
                "progress",
                "data",
            ),
        )
        self.assertEqual(payload["event_type"], "progress")
        self.assertEqual(TaskEvent.from_dict(payload), event)
        self.assertEqual(json.loads(json.dumps(payload, allow_nan=False)), payload)

    def test_event_is_frozen_and_defensively_copies_nested_data(self):
        candidates = ["renpy"]
        data = {"nested": {"candidates": candidates}}
        event = make_event(data=data)
        candidates.append("unity")
        data["extra"] = True
        self.assertEqual(event.data, {"nested": {"candidates": ["renpy"]}})

        payload = event.to_dict()
        payload["data"]["nested"]["candidates"].append("godot")
        self.assertEqual(event.data, {"nested": {"candidates": ["renpy"]}})
        with self.assertRaises(FrozenInstanceError):
            event.sequence = 2

    def test_event_rejects_invalid_sequence_enums_timestamp_and_strings(self):
        for changes in (
            {"task_id": ""},
            {"step_id": ""},
            {"sequence": 0},
            {"sequence": True},
            {"event_type": "progress"},
            {"timestamp": "2026-08-05T12:30:45+00:00"},
            {"timestamp": "2026-08-05T12:30:45+08:00Z"},
            {"timestamp": "not-a-timestampZ"},
            {"summary": ""},
        ):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                make_event(**changes)


class ArtifactTests(unittest.TestCase):
    def test_artifact_round_trips_normalized_path_and_exact_schema(self):
        artifact = make_artifact(relative_path="output\\patch.zip", sha256=None)
        self.assertEqual(
            artifact.to_dict(),
            {
                "artifact_id": "artifact-1",
                "task_id": "task-1",
                "step_id": "build",
                "kind": "patch",
                "relative_path": "output/patch.zip",
                "sha256": None,
                "metadata": {"files": 3, "nested": {"languages": ["zh-Hans"]}},
            },
        )
        self.assertEqual(Artifact.from_dict(artifact.to_dict()), artifact)

    def test_artifact_rejects_unsafe_relative_paths(self):
        invalid_paths = (
            "../escape.json",
            "..\\escape.json",
            "/rooted/patch.zip",
            "\\rooted\\patch.zip",
            "C:drive-relative.zip",
            "C:/rooted/patch.zip",
            "C:\\rooted\\patch.zip",
            "\\\\server\\share\\patch.zip",
            "\\\\?\\C:\\device\\patch.zip",
            "\\\\.\\C:\\device\\patch.zip",
        )
        for relative_path in invalid_paths:
            with self.subTest(relative_path=relative_path), self.assertRaises(ValueError):
                make_artifact(relative_path=relative_path)

    def test_artifact_rejects_plain_or_unknown_kind_values(self):
        with self.assertRaises(TypeError):
            make_artifact(kind="patch")
        with self.assertRaises(ValueError):
            Artifact.from_dict({**make_artifact().to_dict(), "kind": "unknown"})

    def test_artifact_validates_identifiers_and_sha256_type(self):
        for changes in (
            {"artifact_id": ""},
            {"task_id": ""},
            {"step_id": ""},
            {"step_id": None},
            {"sha256": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                make_artifact(**changes)

    def test_artifact_is_frozen_and_defensively_copies_nested_metadata(self):
        languages = ["zh-Hans"]
        metadata = {"nested": {"languages": languages}}
        artifact = make_artifact(metadata=metadata)
        languages.append("zh-Hant")
        metadata["extra"] = True
        self.assertEqual(artifact.metadata, {"nested": {"languages": ["zh-Hans"]}})

        payload = artifact.to_dict()
        payload["metadata"]["nested"]["languages"].append("ja")
        self.assertEqual(artifact.metadata, {"nested": {"languages": ["zh-Hans"]}})
        with self.assertRaises(FrozenInstanceError):
            artifact.relative_path = "other.zip"


class JsonPayloadTests(unittest.TestCase):
    def test_payloads_reject_reserved_keys_case_insensitively_at_any_depth(self):
        reserved_keys = (
            "api_key",
            "AUTHORIZATION",
            "Secret",
            "ToKeN",
            "request_body",
            "screenshot",
            "chain_of_thought",
            "reasoning_trace",
        )
        for key in reserved_keys:
            for builder in (
                lambda value: make_event(data={"outer": [{key: value}]}),
                lambda value: make_artifact(metadata={"outer": [{key: value}]}),
                lambda value: StepResult(data={"outer": [{key: value}]}),
            ):
                with self.subTest(key=key, builder=builder), self.assertRaises(ValueError):
                    builder("sensitive")

    def test_payloads_reject_non_json_values(self):
        invalid_payloads = (
            {"bad": object()},
            {"bad": lambda: None},
            {"bad": RuntimeError("failure")},
            {1: "non-string key"},
            {"bad": math.nan},
            {"bad": math.inf},
            {"bad": -math.inf},
            {"bad": {"unordered"}},
            {"bad": ("not", "json")},
        )
        for payload in invalid_payloads:
            for builder in (
                lambda value: make_event(data=value),
                lambda value: make_artifact(metadata=value),
                lambda value: StepResult(data=value),
            ):
                with self.subTest(payload=payload, builder=builder):
                    with self.assertRaises((TypeError, ValueError)):
                        builder(payload)


class StepResultTests(unittest.TestCase):
    def test_step_result_round_trips_and_copies_ordered_artifacts(self):
        artifacts = [make_artifact()]
        data = {"counts": {"written": 3}}
        result = StepResult(artifacts=artifacts, data=data)
        artifacts.clear()
        data["counts"]["written"] = 99
        self.assertEqual(result.artifacts, (make_artifact(),))
        self.assertEqual(result.data, {"counts": {"written": 3}})
        self.assertEqual(StepResult.from_dict(result.to_dict()), result)
        self.assertEqual(tuple(result.to_dict()), ("artifacts", "data"))

    def test_step_result_rejects_invalid_or_unordered_artifacts(self):
        with self.assertRaises(TypeError):
            StepResult(artifacts=("bad",))
        with self.assertRaises(TypeError):
            StepResult(artifacts=frozenset())


class PersistenceSchemaTests(unittest.TestCase):
    def test_all_from_dict_methods_reject_missing_and_extra_fields(self):
        models = (
            TaskProgress(0, None),
            make_step(),
            TaskPlan("task-1", "project-a", "detect", TaskState.QUEUED, (make_step(),)),
            make_event(),
            make_artifact(),
            StepResult((make_artifact(),), {"ok": True}),
        )
        for model in models:
            model_type = type(model)
            payload = model.to_dict()
            missing = dict(payload)
            missing.pop(next(iter(missing)))
            with self.subTest(model=model_type.__name__, shape="missing"):
                with self.assertRaises(ValueError):
                    model_type.from_dict(missing)
            with self.subTest(model=model_type.__name__, shape="extra"):
                with self.assertRaises(ValueError):
                    model_type.from_dict({**payload, "extra": None})

    def test_all_to_dict_payloads_are_finite_json(self):
        models = (
            TaskProgress(0, None),
            make_step(),
            TaskPlan("task-1", "project-a", "detect", TaskState.QUEUED, (make_step(),)),
            make_event(),
            make_artifact(),
            StepResult((make_artifact(),), {"ok": True}),
        )
        for model in models:
            with self.subTest(model=type(model).__name__):
                payload = model.to_dict()
                self.assertEqual(
                    json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False)),
                    payload,
                )


class PublicExportsTests(unittest.TestCase):
    def test_hanengine_reexports_all_task_four_public_types(self):
        import game_localizer.hanengine as hanengine

        expected = {
            "Artifact": Artifact,
            "ArtifactKind": ArtifactKind,
            "EventType": EventType,
            "StepResult": StepResult,
            "StepState": StepState,
            "TaskEvent": TaskEvent,
            "TaskPlan": TaskPlan,
            "TaskProgress": TaskProgress,
            "TaskState": TaskState,
            "TaskStep": TaskStep,
        }
        for name, exported in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, hanengine.__all__)
                self.assertIs(getattr(hanengine, name), exported)


if __name__ == "__main__":
    unittest.main()
