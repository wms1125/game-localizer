import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from game_localizer.hanengine import (
    Artifact,
    ArtifactKind,
    EvaluationStatus,
    EventType,
    RiskLevel,
    RouteOperation,
    RoutePhase,
    RoutePlan,
    Segment,
    SegmentDraft,
    SourceLocation,
    TaskEvent,
    TaskPlan,
    TaskState,
    TaskStep,
)
from game_localizer.hanengine.store import (
    Checkpoint,
    HanStore,
    ProjectRecord,
    default_data_root,
)


FIRST_PROJECT = "11111111-1111-4111-8111-111111111111"
SECOND_PROJECT = "22222222-2222-4222-8222-222222222222"
THIRD_PROJECT = "33333333-3333-4333-8333-333333333333"


def make_segment(
    project_id: str,
    *,
    segment_id: str = "line-1",
    source_fingerprint: str = "source-a",
) -> Segment:
    draft = SegmentDraft(
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
        metadata={"engine": "renpy"},
    )
    return Segment.from_draft(project_id, "zh-CN", draft)


def make_route(project_id: str, *, provisional: bool = False) -> RoutePlan:
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


def make_task(project_id: str, *, task_id: str = "task-1") -> TaskPlan:
    return TaskPlan(
        task_id=task_id,
        project_id=project_id,
        kind="detect",
        state=TaskState.QUEUED,
        steps=(
            TaskStep(
                step_id="detect",
                title="Detect engine",
                operation=RouteOperation.DETECT,
            ),
        ),
    )


class StoreModelTests(unittest.TestCase):
    def test_default_data_root_uses_injected_or_environment_base(self):
        base = Path("C:/LocalData")
        self.assertEqual(default_data_root(base), base / "HanEngine")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "LOCALAPPDATA"):
                default_data_root()

    def test_project_record_and_checkpoint_round_trip_canonical_json(self):
        record = ProjectRecord(
            project_id=FIRST_PROJECT,
            name="First",
            source_root="C:/Games/First",
            created_at="2026-08-06T00:00:00Z",
        )
        checkpoint = Checkpoint(
            checkpoint_id="checkpoint-1",
            task_id="task-1",
            step_id="detect",
            sequence=1,
            payload={"cursor": 7, "paths": ["game/script.rpy"]},
        )
        for model in (record, checkpoint):
            payload = model.to_dict()
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            self.assertEqual(type(model).from_dict(json.loads(encoded)), model)

        with self.assertRaisesRegex(ValueError, "sensitive"):
            Checkpoint(
                checkpoint_id="bad",
                task_id="task-1",
                step_id="detect",
                sequence=1,
                payload={"API_KEY": "not-persisted"},
            )

    def test_project_ids_are_canonical_uuid4_values(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HanStore(Path(directory))
            for project_id in (
                "../escape",
                "projects/escape",
                "11111111-1111-1111-8111-111111111111",
                "not-a-uuid",
            ):
                with self.subTest(project_id=project_id):
                    with self.assertRaises((TypeError, ValueError)):
                        store.create_project("Invalid", project_id=project_id)


class HanStoreTests(unittest.TestCase):
    def test_config_and_project_databases_have_schema_v1_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = HanStore(root)
            project = store.create_project("First", project_id=FIRST_PROJECT)
            expected = root.resolve() / "projects" / FIRST_PROJECT / "hanengine.db"
            self.assertEqual(store.config_path, root.resolve() / "config.db")
            self.assertEqual(store.project_path(FIRST_PROJECT), expected)
            self.assertTrue(store.config_path.is_file())
            self.assertTrue(expected.is_file())

            with closing(sqlite3.connect(store.config_path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT version FROM schema_info").fetchone(),
                    (1,),
                )
            with store.open_project(project.project_id) as project_db:
                self.assertEqual(
                    project_db.connection.execute("PRAGMA foreign_keys").fetchone(),
                    (1,),
                )
                self.assertEqual(
                    project_db.connection.execute(
                        "SELECT version FROM schema_info"
                    ).fetchone(),
                    (1,),
                )

    def test_two_projects_isolate_equal_segment_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HanStore(Path(directory))
            first = store.create_project("First", project_id=FIRST_PROJECT)
            second = store.create_project("Second", project_id=SECOND_PROJECT)
            with (
                store.open_project(first.project_id) as first_db,
                store.open_project(second.project_id) as second_db,
            ):
                first_db.save_segments((make_segment(first.project_id),))
                second_db.save_segments((make_segment(second.project_id),))
                self.assertEqual(first_db.list_segments(), (make_segment(first.project_id),))
                self.assertEqual(second_db.list_segments(), (make_segment(second.project_id),))
                self.assertNotEqual(first_db.path, second_db.path)
                with self.assertRaisesRegex(ValueError, "project"):
                    first_db.save_segments((make_segment(second.project_id, segment_id="x"),))

    def test_route_task_event_artifact_and_checkpoint_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HanStore(Path(directory))
            project = store.create_project("Checkpoint Project", project_id=THIRD_PROJECT)
            route = make_route(project.project_id)
            task = make_task(project.project_id)
            event = TaskEvent(
                task_id=task.task_id,
                step_id="detect",
                sequence=1,
                event_type=EventType.LOG,
                timestamp="2026-08-06T00:00:00Z",
                summary="detecting",
                data={"engine": "renpy"},
            )
            artifact = Artifact(
                artifact_id="artifact-1",
                task_id=task.task_id,
                step_id="detect",
                kind=ArtifactKind.REPORT,
                relative_path="reports/detect.json",
                sha256="a" * 64,
                metadata={"format": "json"},
            )
            checkpoint = Checkpoint(
                checkpoint_id="checkpoint-1",
                task_id=task.task_id,
                step_id="detect",
                sequence=1,
                payload={"cursor": 7, "paths": ["game/script.rpy"]},
            )
            with store.open_project(project.project_id) as project_db:
                project_db.save_route(route)
                project_db.save_task(task)
                project_db.append_event(event)
                project_db.save_artifact(artifact)
                project_db.save_checkpoint(checkpoint)
                self.assertEqual(project_db.get_route(RoutePhase.FINAL), route)
                self.assertEqual(project_db.get_task(task.task_id), task)
                self.assertEqual(project_db.list_events(task.task_id), (event,))
                self.assertEqual(project_db.list_artifacts(task.task_id), (artifact,))

            with store.open_project(project.project_id) as reopened:
                self.assertEqual(reopened.get_checkpoint(checkpoint.checkpoint_id), checkpoint)

    def test_duplicate_event_sequence_is_rejected_without_replacing_original(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HanStore(Path(directory))
            project = store.create_project("First", project_id=FIRST_PROJECT)
            task = make_task(project.project_id)
            original = TaskEvent(
                task_id=task.task_id,
                step_id=None,
                sequence=1,
                event_type=EventType.QUEUED,
                timestamp="2026-08-06T00:00:00Z",
                summary="queued",
            )
            duplicate = TaskEvent(
                task_id=task.task_id,
                step_id=None,
                sequence=1,
                event_type=EventType.STARTED,
                timestamp="2026-08-06T00:00:01Z",
                summary="started",
            )
            with store.open_project(project.project_id) as project_db:
                project_db.save_task(task)
                project_db.append_event(original)
                with self.assertRaises(sqlite3.IntegrityError):
                    project_db.append_event(duplicate)
                self.assertEqual(project_db.list_events(task.task_id), (original,))

    def test_failed_segment_batch_rolls_back_every_insert(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HanStore(Path(directory))
            project = store.create_project("First", project_id=FIRST_PROJECT)
            duplicate = make_segment(project.project_id)
            with store.open_project(project.project_id) as project_db:
                with self.assertRaises(sqlite3.IntegrityError):
                    project_db.save_segments((duplicate, duplicate))
                self.assertEqual(project_db.list_segments(), ())

    def test_config_index_round_trips_and_unknown_project_is_not_searched(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HanStore(Path(directory))
            first = store.create_project("First", project_id=FIRST_PROJECT)
            second = store.create_project("Second", project_id=SECOND_PROJECT)
            self.assertEqual(store.get_project(first.project_id), first)
            self.assertEqual(store.list_projects(), (first, second))
            with self.assertRaisesRegex(KeyError, "project"):
                store.open_project(THIRD_PROJECT)

    def test_schema_and_persisted_payloads_have_no_api_key_field(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HanStore(Path(directory))
            project = store.create_project("First", project_id=FIRST_PROJECT)
            with store.open_project(project.project_id) as project_db:
                task = make_task(project.project_id)
                project_db.save_task(task)
                rows = project_db.connection.execute(
                    "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
                ).fetchall()
                payloads = project_db.connection.execute(
                    "SELECT payload_json FROM tasks"
                ).fetchall()
            persisted = "\n".join(
                item[0] for item in rows + payloads if item[0] is not None
            ).casefold()
            self.assertNotIn("api_key", persisted)


if __name__ == "__main__":
    unittest.main()
