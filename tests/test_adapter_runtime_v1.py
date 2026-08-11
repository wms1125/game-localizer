from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from game_localizer.adapters import (
    GodotAdapterV1,
    RpgMakerMVAdapterV1,
    RpgMakerMZAdapterV1,
    get_adapters,
    get_adapters_v1,
)
from game_localizer.adapters.contract import (
    AdapterCapability,
    AdapterError,
    AdapterErrorCode,
    BuildRequest,
    BuildResult,
    DeclaredMode,
    ExtractRequest,
    ExtractResult,
    Operation,
    ValidationRequest,
    ValidationResult,
    VerifyRequest,
    VerifyResult,
    route_operations_for_capabilities,
)
from game_localizer.hanengine import (
    AdapterAmbiguityError,
    AdapterNotDetectedError,
    AdapterRegistryV1,
    AdapterRuntimeV1,
    AdapterTaskFailedError,
    EvaluationStatus,
    EventType,
    HanCore,
    HanGuard,
    HanGuardRule,
    HanStore,
    RiskLevel,
    RiskSignal,
    RouteBlockedError,
    RouteOperation,
    RoutePhase,
    SignalType,
    TaskContext,
    TaskControl,
    TaskState,
)


PROJECT_ID = "33333333-3333-4333-8333-333333333333"


def external_context() -> TaskContext:
    return TaskContext("external-task", "external-step", TaskControl(), lambda *args: None)


class AdapterRuntimeV1Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        data = self.source / "data"
        data.mkdir(parents=True)
        (self.source / "game.rpgproject").write_text("RPG Maker MV", encoding="utf-8")
        (data / "Actors.json").write_text(
            json.dumps(
                {
                    "name": "Hero",
                    "events": [{"code": 401, "parameters": ["Hello, {name}!"]}],
                }
            ),
            encoding="utf-8",
        )
        self.store = HanStore(self.root / "state")
        self.addCleanup(self.store.close)
        self.store.create_project(
            "Adapter runtime",
            source_root=self.source,
            project_id=PROJECT_ID,
        )
        self.project = self.store.open_project(PROJECT_ID)
        self.addCleanup(self.project.close)
        self.core = HanCore(self.project)

    def make_runtime(self, *adapters, guard: HanGuard | None = None) -> AdapterRuntimeV1:
        return AdapterRuntimeV1(
            self.core,
            HanGuard(()) if guard is None else guard,
            adapters or (RpgMakerMVAdapterV1(),),
        )

    def select_mv(self, runtime: AdapterRuntimeV1 | None = None):
        active = self.make_runtime() if runtime is None else runtime
        return active.detect(
            self.source,
            DeclaredMode.STUDIO,
            user_baseline=RiskLevel.H0_PROJECT,
            adapter_baseline=RiskLevel.H0_PROJECT,
        )

    def test_detection_runs_as_provisional_task_and_persists_final_capability_route(self):
        selection = self.select_mv()
        expected = frozenset(
            {
                RouteOperation.DETECT,
                RouteOperation.EXTRACT,
                RouteOperation.VALIDATE,
                RouteOperation.BUILD,
                RouteOperation.VERIFY,
            }
        )
        self.assertEqual(selection.final_route.allowed_operations, expected)
        self.assertNotIn(RouteOperation.ROLLBACK, selection.final_route.allowed_operations)
        self.assertEqual(
            self.project.get_route(RoutePhase.PROVISIONAL),
            selection.provisional_route,
        )
        self.assertEqual(self.project.get_route(RoutePhase.FINAL), selection.final_route)
        self.assertEqual(
            self.project.get_task(selection.detection_task.task_id),
            selection.detection_task,
        )
        events = self.project.list_events(selection.detection_task.task_id)
        self.assertEqual(events[0].event_type, EventType.QUEUED)
        self.assertEqual(events[-1].event_type, EventType.COMPLETED)
        step_completion = next(
            event
            for event in events
            if event.step_id == "adapter-detect" and event.event_type is EventType.COMPLETED
        )
        self.assertEqual(
            step_completion.data["data"]["adapter_id"],
            "hanengine.rpg-maker-mv",
        )

    def test_default_runtime_uses_the_separate_v1_registry(self):
        runtime = AdapterRuntimeV1(self.core, HanGuard(()))
        selection = self.select_mv(runtime)
        self.assertEqual(selection.adapter_id, "hanengine.rpg-maker-mv")
        self.assertEqual(len(runtime.registry.adapters), 6)

    def test_extract_validate_build_verify_use_hantask_and_persist_segments(self):
        runtime = self.make_runtime()
        selection = self.select_mv(runtime)
        working = self.root / "working"
        working.mkdir()

        extracted = runtime.run_operation(
            selection,
            Operation.EXTRACT,
            lambda context: ExtractRequest(
                self.source,
                working,
                (),
                (),
                PROJECT_ID,
                context,
            ),
            target_language="zh-CN",
        )
        self.assertIsInstance(extracted.result, ExtractResult)
        self.assertEqual(
            sorted(extracted.ingested_segments, key=lambda item: item.segment_id),
            list(self.project.list_segments()),
        )
        self.assertEqual(extracted.task.state, TaskState.COMPLETED)
        extract_completion = next(
            event
            for event in self.project.list_events(extracted.task.task_id)
            if event.step_id == "adapter-extract" and event.event_type is EventType.COMPLETED
        )
        self.assertEqual(
            extract_completion.data["data"]["ingested_segments"],
            len(extracted.ingested_segments),
        )

        translations = {
            "Hero": "英雄",
            "Hello, {name}!": "你好，{name}!",
        }
        translated = tuple(
            replace(
                segment,
                target_text=translations[segment.source_text],
                translation_source="test",
            )
            for segment in extracted.ingested_segments
        )
        validated = runtime.run_operation(
            selection,
            Operation.VALIDATE,
            lambda context: ValidationRequest(
                extracted.result.source_tree_fingerprint,
                extracted.ingested_segments,
                translated,
                "utf-8",
                {},
                context,
            ),
        )
        self.assertIsInstance(validated.result, ValidationResult)
        self.assertTrue(validated.result.valid)

        staging = self.root / "staging"
        staging.mkdir()
        built = runtime.run_operation(
            selection,
            Operation.BUILD,
            lambda context: BuildRequest(
                self.source,
                staging,
                translated,
                extracted.result.source_tree_fingerprint,
                {},
                context,
            ),
        )
        self.assertIsInstance(built.result, BuildResult)
        build_completion = next(
            event
            for event in self.project.list_events(built.task.task_id)
            if event.step_id == "adapter-build" and event.event_type is EventType.COMPLETED
        )
        self.assertEqual(
            build_completion.data["data"]["manifest"][0]["relative_path"],
            "data/Actors.json",
        )

        verified = runtime.run_operation(
            selection,
            Operation.VERIFY,
            lambda context: VerifyRequest(
                extracted.result.source_tree_fingerprint,
                staging,
                built.result.manifest,
                "full",
                context,
            ),
        )
        self.assertIsInstance(verified.result, VerifyResult)
        self.assertTrue(verified.result.passed)
        self.assertTrue(
            all(
                execution.task.state is TaskState.COMPLETED
                for execution in (extracted, validated, built, verified)
            )
        )

    def test_missing_baselines_fail_closed_to_detect_only(self):
        selection = self.make_runtime().detect(
            self.source,
            DeclaredMode.STUDIO,
            user_baseline=None,
            adapter_baseline=None,
            provisional_evaluation_status=EvaluationStatus.COMPLETE,
            final_evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(
            selection.final_route.allowed_operations,
            frozenset({RouteOperation.DETECT}),
        )
        self.assertIs(selection.final_route.risk_after, RiskLevel.H2_RESTRICTED)
        self.assertIn("missing_user_baseline", selection.final_route.decision_reasons)
        self.assertIn("missing_adapter_baseline", selection.final_route.decision_reasons)

    def test_hanguard_rule_blocks_build_before_request_factory_runs(self):
        rule = HanGuardRule(
            rule_id="block-build",
            rule_version="1",
            signal_type=SignalType.USER_DECLARATION,
            match_value="protected",
            minimum_risk=RiskLevel.H0_PROJECT,
            blocked_operations=frozenset({RouteOperation.BUILD}),
            reason="build_requires_external_approval",
            evidence_source="test-policy",
            last_verified_date="2026-08-07",
        )
        runtime = self.make_runtime(guard=HanGuard((rule,)))
        selection = runtime.detect(
            self.source,
            DeclaredMode.STUDIO,
            user_baseline=RiskLevel.H0_PROJECT,
            adapter_baseline=RiskLevel.H0_PROJECT,
            final_signals=(
                RiskSignal(
                    SignalType.USER_DECLARATION,
                    "protected",
                    "test",
                    "authorized policy fixture",
                ),
            ),
        )
        self.assertNotIn(RouteOperation.BUILD, selection.final_route.allowed_operations)
        calls = []
        with self.assertRaisesRegex(RouteBlockedError, "build"):
            runtime.run_operation(
                selection,
                Operation.BUILD,
                lambda context: calls.append(context),
            )
        self.assertEqual(calls, [])

    def test_packaged_detection_capabilities_keep_final_route_detect_only(self):
        (self.source / "game.rpgproject").unlink()
        (self.source / "game.pck").write_bytes(b"package")
        runtime = self.make_runtime(GodotAdapterV1())
        selection = runtime.detect(
            self.source,
            DeclaredMode.PLAYER,
            user_baseline=RiskLevel.H0_PROJECT,
            adapter_baseline=RiskLevel.H0_PROJECT,
        )
        self.assertEqual(
            selection.final_route.allowed_operations,
            frozenset({RouteOperation.DETECT}),
        )
        calls = []
        with self.assertRaisesRegex(RouteBlockedError, "extract"):
            runtime.run_operation(
                selection,
                Operation.EXTRACT,
                lambda context: calls.append(context),
                target_language="zh-CN",
            )
        self.assertEqual(calls, [])

    def test_similar_detection_scores_fail_closed_as_ambiguous(self):
        self.select_mv()
        self.assertIsNotNone(self.project.get_route(RoutePhase.FINAL))
        (self.source / "game.rmmzproject").write_text("RPG Maker MZ", encoding="utf-8")
        runtime = self.make_runtime(RpgMakerMVAdapterV1(), RpgMakerMZAdapterV1())
        with self.assertRaises(AdapterAmbiguityError) as raised:
            runtime.detect(
                self.source,
                DeclaredMode.STUDIO,
                user_baseline=RiskLevel.H0_PROJECT,
                adapter_baseline=RiskLevel.H0_PROJECT,
            )
        self.assertEqual(
            raised.exception.adapter_ids,
            ("hanengine.rpg-maker-mv", "hanengine.rpg-maker-mz"),
        )
        self.assertIs(raised.exception.task.state, TaskState.COMPLETED)
        self.assertIsNone(self.project.get_route(RoutePhase.FINAL))

    def test_unmatched_detection_completes_audit_task_without_final_route(self):
        (self.source / "game.rpgproject").unlink()
        runtime = self.make_runtime()
        with self.assertRaises(AdapterNotDetectedError) as raised:
            runtime.detect(
                self.source,
                DeclaredMode.STUDIO,
                user_baseline=RiskLevel.H0_PROJECT,
                adapter_baseline=RiskLevel.H0_PROJECT,
            )
        self.assertIs(raised.exception.task.state, TaskState.COMPLETED)
        self.assertEqual(
            self.project.get_route(RoutePhase.PROVISIONAL),
            raised.exception.provisional_route,
        )
        self.assertIsNone(self.project.get_route(RoutePhase.FINAL))

    def test_forged_selection_route_is_rejected_before_request_factory(self):
        runtime = self.make_runtime()
        selection = self.select_mv(runtime)
        forged = replace(
            selection,
            final_route=replace(
                selection.final_route,
                decision_reasons=("caller_supplied_route",),
            ),
        )
        calls = []
        with self.assertRaisesRegex(ValueError, "final route is not current"):
            runtime.run_operation(
                forged,
                Operation.EXTRACT,
                lambda context: calls.append(context),
                target_language="zh-CN",
            )
        self.assertEqual(calls, [])

    def test_wrong_task_context_marks_operation_failed_without_ingesting(self):
        runtime = self.make_runtime()
        selection = self.select_mv(runtime)
        working = self.root / "working"
        working.mkdir()
        with self.assertRaises(AdapterTaskFailedError) as raised:
            runtime.run_operation(
                selection,
                Operation.EXTRACT,
                lambda context: ExtractRequest(
                    self.source,
                    working,
                    (),
                    (),
                    PROJECT_ID,
                    external_context(),
                ),
                target_language="zh-CN",
            )
        self.assertIs(raised.exception.task.state, TaskState.FAILED)
        self.assertEqual(self.project.list_segments(), ())
        events = self.project.list_events(raised.exception.task.task_id)
        self.assertEqual(events[-1].data, {"exception_type": "ValueError"})

    def test_adapter_error_becomes_sanitized_failed_task(self):
        class FailingAdapter(RpgMakerMVAdapterV1):
            def extract(self, request):
                return AdapterError(
                    code=AdapterErrorCode.UNSUPPORTED_INPUT,
                    operation=Operation.EXTRACT,
                    message="Source resource cannot be extracted",
                    recoverable=False,
                )

        runtime = self.make_runtime(FailingAdapter())
        selection = self.select_mv(runtime)
        working = self.root / "working"
        working.mkdir()
        with self.assertRaises(AdapterTaskFailedError) as raised:
            runtime.run_operation(
                selection,
                Operation.EXTRACT,
                lambda context: ExtractRequest(
                    self.source,
                    working,
                    (),
                    (),
                    PROJECT_ID,
                    context,
                ),
                target_language="zh-CN",
            )
        self.assertIs(raised.exception.adapter_error.code, AdapterErrorCode.UNSUPPORTED_INPUT)
        events = self.project.list_events(raised.exception.task.task_id)
        serialized = json.dumps([event.to_dict() for event in events])
        self.assertNotIn("Source resource cannot be extracted", serialized)
        self.assertEqual(events[-1].data, {"exception_type": "_AdapterInvocationFailed"})

    def test_configured_project_source_root_is_enforced_before_task_creation(self):
        other = self.root / "other-source"
        other.mkdir()
        runtime = self.make_runtime()
        with self.assertRaisesRegex(ValueError, "project source root"):
            runtime.detect(
                other,
                DeclaredMode.STUDIO,
                user_baseline=RiskLevel.H0_PROJECT,
                adapter_baseline=RiskLevel.H0_PROJECT,
            )
        self.assertIsNone(self.project.get_route(RoutePhase.PROVISIONAL))


class AdapterRuntimeRegistryTests(unittest.TestCase):
    def test_v1_registry_is_separate_and_deterministic(self):
        adapters = get_adapters_v1()
        self.assertEqual(len(adapters), 6)
        self.assertFalse(any(type(adapter).__name__.endswith("AdapterV1") for adapter in get_adapters()))
        registry = AdapterRegistryV1(reversed(adapters))
        self.assertEqual(
            [adapter.metadata.adapter_id for adapter in registry.adapters],
            sorted(adapter.metadata.adapter_id for adapter in adapters),
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            AdapterRegistryV1((RpgMakerMVAdapterV1(), RpgMakerMVAdapterV1()))

    def test_capability_bridge_maps_only_adapter_contract_operations(self):
        result = route_operations_for_capabilities(
            frozenset({AdapterCapability.DETECT, AdapterCapability.BUILD})
        )
        self.assertEqual(
            result,
            frozenset({RouteOperation.DETECT, RouteOperation.BUILD}),
        )
        with self.assertRaises(TypeError):
            route_operations_for_capabilities({"detect"})


if __name__ == "__main__":
    unittest.main()
