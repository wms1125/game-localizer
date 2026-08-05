from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from game_localizer.hanengine.routing import (
    EvaluationStatus,
    HanGuard,
    HanGuardRule,
    RiskLevel,
    RiskSignal,
    RouteOperation,
    RoutePhase,
    RoutePlan,
    RuleMatch,
    SignalType,
)


ROOT = Path(__file__).resolve().parents[1]
ALL_OPERATIONS = frozenset(RouteOperation)
SAFE_EXTERNAL_OPERATIONS = frozenset(
    {
        RouteOperation.DETECT,
        RouteOperation.CAPTURE,
        RouteOperation.OCR,
        RouteOperation.VISUAL_REPLACE,
    }
)


def make_rule(
    *,
    rule_id: str = "known-anticheat",
    signal_type: SignalType = SignalType.PATH,
    match_value: str = "knownac.exe",
    minimum_risk: RiskLevel = RiskLevel.H3_PROTECTED,
    blocked_operations: object = frozenset(
        {RouteOperation.INSTALL_PATCH, RouteOperation.EXTRACT}
    ),
    reason: str = "protected environment",
) -> HanGuardRule:
    return HanGuardRule(
        rule_id=rule_id,
        rule_version="1.0.0",
        signal_type=signal_type,
        match_value=match_value,
        minimum_risk=minimum_risk,
        blocked_operations=blocked_operations,
        reason=reason,
        evidence_source="synthetic test rule",
        last_verified_date="2026-08-05",
    )


def make_signal(
    *,
    signal_type: SignalType = SignalType.PATH,
    value: str = "KnownAC.EXE",
    source: str = "install_root",
) -> RiskSignal:
    return RiskSignal(
        signal_type=signal_type,
        value=value,
        source=source,
        evidence="public file name",
    )


class RoutingModelTests(unittest.TestCase):
    def test_enum_values_are_the_frozen_contract(self):
        self.assertEqual(
            [(item.name, item.value) for item in RiskLevel],
            [
                ("H0_PROJECT", 0),
                ("H1_OFFLINE", 1),
                ("H2_RESTRICTED", 2),
                ("H3_PROTECTED", 3),
            ],
        )
        self.assertEqual(
            [item.value for item in RoutePhase], ["provisional", "final"]
        )
        self.assertEqual(
            [item.value for item in EvaluationStatus],
            [
                "complete",
                "missing_evidence",
                "unknown_rule",
                "evaluation_failed",
            ],
        )
        self.assertEqual(
            [item.value for item in SignalType],
            [
                "user_declaration",
                "path",
                "manifest_key",
                "process_name",
                "service_name",
                "capture_result",
            ],
        )
        self.assertEqual(
            [item.value for item in RouteOperation],
            [
                "detect",
                "extract",
                "validate",
                "build",
                "verify",
                "rollback",
                "install_patch",
                "capture",
                "ocr",
                "visual_replace",
            ],
        )

    def test_models_are_frozen_and_normalize_collections(self):
        rule = make_rule(blocked_operations=[RouteOperation.EXTRACT])
        match = RuleMatch(
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            actual_signal="KnownAC.EXE",
            source="install_root",
            risk_before=RiskLevel.H0_PROJECT,
            risk_after=RiskLevel.H3_PROTECTED,
            blocked_operations=[RouteOperation.EXTRACT],
            reason=rule.reason,
        )
        plan = RoutePlan(
            project_id="project-a",
            phase=RoutePhase.FINAL,
            risk_before=RiskLevel.H0_PROJECT,
            risk_after=RiskLevel.H3_PROTECTED,
            allowed_operations=[RouteOperation.DETECT],
            blocked_operations=(item for item in RouteOperation if item is not RouteOperation.DETECT),
            matches=[match],
            evaluation_status=EvaluationStatus.COMPLETE,
            unknown_evidence=False,
            decision_reasons=[rule.reason],
        )
        self.assertIsInstance(rule.blocked_operations, frozenset)
        self.assertIsInstance(match.blocked_operations, frozenset)
        self.assertIsInstance(plan.allowed_operations, frozenset)
        self.assertIsInstance(plan.blocked_operations, frozenset)
        self.assertIsInstance(plan.matches, tuple)
        self.assertIsInstance(plan.decision_reasons, tuple)
        with self.assertRaises(FrozenInstanceError):
            plan.project_id = "other"

    def test_models_validate_strings_enums_and_collection_members(self):
        invalid_builders = (
            lambda: RiskSignal(SignalType.PATH, "", "source", "evidence"),
            lambda: RiskSignal("path", "value", "source", "evidence"),
            lambda: make_rule(rule_id=""),
            lambda: make_rule(blocked_operations=["extract"]),
            lambda: RuleMatch(
                "rule", "1", "value", "source", RiskLevel.H0_PROJECT,
                RiskLevel.H1_OFFLINE, ["extract"], "reason"
            ),
            lambda: RoutePlan(
                "project", RoutePhase.FINAL, RiskLevel.H0_PROJECT,
                RiskLevel.H0_PROJECT, ["detect"], [], (),
                EvaluationStatus.COMPLETE, False, ()
            ),
        )
        for builder in invalid_builders:
            with self.subTest(builder=builder):
                with self.assertRaises((TypeError, ValueError)):
                    builder()

    def test_ordered_model_collections_reject_unordered_inputs(self):
        match = RuleMatch(
            "rule",
            "1.0.0",
            "signal",
            "source",
            RiskLevel.H0_PROJECT,
            RiskLevel.H0_PROJECT,
            (),
            "reason",
        )
        common = {
            "project_id": "project-a",
            "phase": RoutePhase.FINAL,
            "risk_before": RiskLevel.H0_PROJECT,
            "risk_after": RiskLevel.H0_PROJECT,
            "allowed_operations": ALL_OPERATIONS,
            "blocked_operations": (),
            "evaluation_status": EvaluationStatus.COMPLETE,
            "unknown_evidence": False,
        }
        with self.assertRaises(TypeError):
            RoutePlan(matches={match}, decision_reasons=(), **common)
        with self.assertRaises(TypeError):
            RoutePlan(matches=(), decision_reasons={"reason"}, **common)

    def test_route_plan_constructor_rejects_policy_contradictions(self):
        h3_match = RuleMatch(
            "protected",
            "1.0.0",
            "ac.exe",
            "root",
            RiskLevel.H0_PROJECT,
            RiskLevel.H3_PROTECTED,
            (),
            "protected",
        )
        blocking_match = RuleMatch(
            "block-extract",
            "1.0.0",
            "resource_write",
            "manifest",
            RiskLevel.H0_PROJECT,
            RiskLevel.H0_PROJECT,
            {RouteOperation.EXTRACT},
            "extract blocked",
        )
        cases = (
            {
                "phase": RoutePhase.FINAL,
                "risk_after": RiskLevel.H0_PROJECT,
                "allowed": ALL_OPERATIONS,
                "matches": (h3_match,),
                "status": EvaluationStatus.COMPLETE,
                "unknown": False,
            },
            {
                "phase": RoutePhase.PROVISIONAL,
                "risk_after": RiskLevel.H0_PROJECT,
                "allowed": frozenset(),
                "matches": (),
                "status": EvaluationStatus.COMPLETE,
                "unknown": False,
            },
            {
                "phase": RoutePhase.PROVISIONAL,
                "risk_after": RiskLevel.H0_PROJECT,
                "allowed": {RouteOperation.DETECT, RouteOperation.EXTRACT},
                "matches": (),
                "status": EvaluationStatus.COMPLETE,
                "unknown": False,
            },
            {
                "phase": RoutePhase.FINAL,
                "risk_after": RiskLevel.H2_RESTRICTED,
                "allowed": {
                    RouteOperation.DETECT,
                    RouteOperation.EXTRACT,
                },
                "matches": (),
                "status": EvaluationStatus.COMPLETE,
                "unknown": False,
            },
            {
                "phase": RoutePhase.FINAL,
                "risk_after": RiskLevel.H0_PROJECT,
                "allowed": ALL_OPERATIONS,
                "matches": (blocking_match,),
                "status": EvaluationStatus.COMPLETE,
                "unknown": False,
            },
            {
                "phase": RoutePhase.FINAL,
                "risk_after": RiskLevel.H2_RESTRICTED,
                "allowed": SAFE_EXTERNAL_OPERATIONS,
                "matches": (),
                "status": EvaluationStatus.UNKNOWN_RULE,
                "unknown": False,
            },
        )
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    RoutePlan(
                        project_id="project-a",
                        phase=case["phase"],
                        risk_before=RiskLevel.H0_PROJECT,
                        risk_after=case["risk_after"],
                        allowed_operations=case["allowed"],
                        blocked_operations=ALL_OPERATIONS - case["allowed"],
                        matches=case["matches"],
                        evaluation_status=case["status"],
                        unknown_evidence=case["unknown"],
                        decision_reasons=("policy test",),
                    )

    def test_route_plan_from_dict_rejects_policy_mutations(self):
        h3_match = RuleMatch(
            "protected",
            "1.0.0",
            "ac.exe",
            "root",
            RiskLevel.H0_PROJECT,
            RiskLevel.H3_PROTECTED,
            (),
            "protected",
        )
        valid = RoutePlan(
            project_id="project-a",
            phase=RoutePhase.FINAL,
            risk_before=RiskLevel.H0_PROJECT,
            risk_after=RiskLevel.H3_PROTECTED,
            allowed_operations=SAFE_EXTERNAL_OPERATIONS,
            blocked_operations=ALL_OPERATIONS - SAFE_EXTERNAL_OPERATIONS,
            matches=(h3_match,),
            evaluation_status=EvaluationStatus.COMPLETE,
            unknown_evidence=False,
            decision_reasons=("protected",),
        ).to_dict()
        mutations = []

        low_risk = {**valid, "risk_after": "H0_PROJECT"}
        mutations.append(low_risk)

        provisional = {
            **valid,
            "phase": "provisional",
            "allowed_operations": ["detect", "extract"],
            "blocked_operations": sorted(
                item.value
                for item in ALL_OPERATIONS
                - {RouteOperation.DETECT, RouteOperation.EXTRACT}
            ),
        }
        mutations.append(provisional)

        unsafe_h2 = {
            **valid,
            "risk_after": "H2_RESTRICTED",
            "matches": [],
            "allowed_operations": ["detect", "extract"],
            "blocked_operations": sorted(
                item.value
                for item in ALL_OPERATIONS
                - {RouteOperation.DETECT, RouteOperation.EXTRACT}
            ),
        }
        mutations.append(unsafe_h2)

        blocked_match = {
            **h3_match.to_dict(),
            "risk_after": "H0_PROJECT",
            "blocked_operations": ["extract"],
        }
        blocked_operation = {
            **valid,
            "risk_after": "H0_PROJECT",
            "matches": [blocked_match],
            "allowed_operations": sorted(item.value for item in ALL_OPERATIONS),
            "blocked_operations": [],
        }
        mutations.append(blocked_operation)

        unknown_without_flag = {
            **valid,
            "risk_after": "H2_RESTRICTED",
            "matches": [],
            "evaluation_status": "unknown_rule",
            "unknown_evidence": False,
        }
        mutations.append(unknown_without_flag)

        for payload in mutations:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    RoutePlan.from_dict(payload)

    def test_evidence_rule_match_and_plan_round_trip_exact_schemas(self):
        signal = make_signal()
        rule = make_rule(
            blocked_operations={
                RouteOperation.VISUAL_REPLACE,
                RouteOperation.CAPTURE,
                RouteOperation.OCR,
            }
        )
        match = RuleMatch(
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            actual_signal=signal.value,
            source=signal.source,
            risk_before=RiskLevel.H0_PROJECT,
            risk_after=RiskLevel.H3_PROTECTED,
            blocked_operations=rule.blocked_operations,
            reason=rule.reason,
        )
        plan = RoutePlan(
            project_id="project-a",
            phase=RoutePhase.FINAL,
            risk_before=RiskLevel.H0_PROJECT,
            risk_after=RiskLevel.H3_PROTECTED,
            allowed_operations={RouteOperation.DETECT},
            blocked_operations=ALL_OPERATIONS - {RouteOperation.DETECT},
            matches=(match,),
            evaluation_status=EvaluationStatus.COMPLETE,
            unknown_evidence=False,
            decision_reasons=(rule.reason,),
        )
        for model, model_type in (
            (signal, RiskSignal),
            (rule, HanGuardRule),
            (match, RuleMatch),
            (plan, RoutePlan),
        ):
            with self.subTest(model_type=model_type.__name__):
                payload = model.to_dict()
                json.dumps(payload, ensure_ascii=False, sort_keys=True)
                self.assertEqual(model_type.from_dict(payload), model)

        self.assertEqual(
            rule.to_dict(),
            {
                "rule_id": "known-anticheat",
                "rule_version": "1.0.0",
                "signal_type": "path",
                "match_value": "knownac.exe",
                "minimum_risk": "H3_PROTECTED",
                "blocked_operations": ["capture", "ocr", "visual_replace"],
                "reason": "protected environment",
                "evidence_source": "synthetic test rule",
                "last_verified_date": "2026-08-05",
            },
        )
        self.assertEqual(
            plan.to_dict()["blocked_operations"],
            sorted(item.value for item in ALL_OPERATIONS - {RouteOperation.DETECT}),
        )

    def test_from_dict_rejects_missing_unknown_and_malformed_fields(self):
        payload = make_signal().to_dict()
        for invalid in (
            {key: value for key, value in payload.items() if key != "evidence"},
            {**payload, "unknown": True},
            {**payload, "signal_type": "not-a-signal-type"},
        ):
            with self.subTest(payload=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    RiskSignal.from_dict(invalid)
        with self.assertRaises(TypeError):
            RoutePlan.from_dict([])


class PublicExportsTests(unittest.TestCase):
    def test_hanengine_reexports_all_task_three_public_types(self):
        import game_localizer.hanengine as hanengine

        expected = {
            "EvaluationStatus": EvaluationStatus,
            "HanGuard": HanGuard,
            "HanGuardRule": HanGuardRule,
            "RiskLevel": RiskLevel,
            "RiskSignal": RiskSignal,
            "RouteOperation": RouteOperation,
            "RoutePhase": RoutePhase,
            "RoutePlan": RoutePlan,
            "RuleMatch": RuleMatch,
            "SignalType": SignalType,
        }
        for name, exported in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, hanengine.__all__)
                self.assertIs(getattr(hanengine, name), exported)


class HanGuardRoutingTests(unittest.TestCase):
    def setUp(self):
        self.rules = (make_rule(),)
        self.guard = HanGuard(self.rules)

    def test_provisional_route_only_allows_detect(self):
        plan = self.guard.evaluate_provisional(
            project_id="project-a",
            user_baseline=RiskLevel.H0_PROJECT,
            signals=(),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(plan.phase, RoutePhase.PROVISIONAL)
        self.assertEqual(plan.allowed_operations, frozenset({RouteOperation.DETECT}))
        self.assertEqual(plan.blocked_operations, ALL_OPERATIONS - plan.allowed_operations)

    def test_final_route_never_lowers_provisional_risk(self):
        provisional = self.guard.evaluate_provisional(
            "project-a",
            RiskLevel.H2_RESTRICTED,
            (),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        final = self.guard.evaluate_final(
            provisional,
            adapter_baseline=RiskLevel.H0_PROJECT,
            signals=(),
            available_operations=ALL_OPERATIONS,
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(final.risk_before, RiskLevel.H2_RESTRICTED)
        self.assertEqual(final.risk_after, RiskLevel.H2_RESTRICTED)

    def test_rule_match_is_casefold_exact_and_requires_same_signal_type(self):
        matching = self.guard.evaluate_provisional(
            "project-a",
            RiskLevel.H1_OFFLINE,
            (make_signal(),),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(matching.risk_after, RiskLevel.H3_PROTECTED)
        self.assertEqual(matching.matches[0].actual_signal, "KnownAC.EXE")
        self.assertEqual(matching.matches[0].source, "install_root")

        for signal in (
            make_signal(value="knownac.exe.extra"),
            make_signal(signal_type=SignalType.PROCESS_NAME),
        ):
            with self.subTest(signal=signal):
                plan = self.guard.evaluate_provisional(
                    "project-a",
                    RiskLevel.H1_OFFLINE,
                    (signal,),
                    evaluation_status=EvaluationStatus.COMPLETE,
                )
                self.assertEqual(plan.risk_after, RiskLevel.H1_OFFLINE)
                self.assertEqual(plan.matches, ())

    def test_casefold_equivalent_signals_have_deterministic_match_order(self):
        rule = make_rule(match_value="strasse")
        guard = HanGuard((rule,))
        signals = (
            make_signal(value="STRASSE"),
            make_signal(value="Straße"),
        )
        forward = guard.evaluate_provisional(
            "project-a",
            RiskLevel.H0_PROJECT,
            signals,
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        reverse = guard.evaluate_provisional(
            "project-a",
            RiskLevel.H0_PROJECT,
            reversed(signals),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(forward.to_dict(), reverse.to_dict())

    def test_conflicting_versioned_rules_are_rejected_in_both_orders(self):
        low = make_rule(
            rule_id="same-rule",
            match_value="ac.exe",
            minimum_risk=RiskLevel.H0_PROJECT,
            blocked_operations=(),
            reason="same reason",
        )
        high = make_rule(
            rule_id="same-rule",
            match_value="ac.exe",
            minimum_risk=RiskLevel.H3_PROTECTED,
            blocked_operations=(),
            reason="same reason",
        )
        for rules in ((low, high), (high, low)):
            with self.subTest(risks=[rule.minimum_risk for rule in rules]):
                with self.assertRaisesRegex(ValueError, "conflicting"):
                    HanGuard(rules)

    def test_identical_duplicate_versioned_rules_are_normalized(self):
        rule = make_rule(minimum_risk=RiskLevel.H3_PROTECTED)
        duplicate = HanGuardRule.from_dict(rule.to_dict())
        guard = HanGuard((rule, duplicate, rule))
        plan = guard.evaluate_provisional(
            "project-a",
            RiskLevel.H0_PROJECT,
            (make_signal(),),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(plan.risk_after, RiskLevel.H3_PROTECTED)
        self.assertEqual(len(plan.matches), 1)

    def test_final_route_intersects_capabilities_then_applies_rule_blocks(self):
        blocking_rule = make_rule(
            minimum_risk=RiskLevel.H0_PROJECT,
            blocked_operations={RouteOperation.EXTRACT},
        )
        guard = HanGuard((blocking_rule,))
        signal = make_signal()
        provisional = guard.evaluate_provisional(
            "project-a",
            RiskLevel.H0_PROJECT,
            (),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        final = guard.evaluate_final(
            provisional,
            adapter_baseline=RiskLevel.H0_PROJECT,
            signals=(signal,),
            available_operations=frozenset(
                {RouteOperation.DETECT, RouteOperation.EXTRACT, RouteOperation.BUILD}
            ),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(
            final.allowed_operations,
            frozenset({RouteOperation.DETECT, RouteOperation.BUILD}),
        )
        self.assertEqual(final.blocked_operations, ALL_OPERATIONS - final.allowed_operations)

    def test_final_base_policies_are_exact_for_all_risk_levels(self):
        expected = {
            RiskLevel.H0_PROJECT: ALL_OPERATIONS,
            RiskLevel.H1_OFFLINE: ALL_OPERATIONS,
            RiskLevel.H2_RESTRICTED: SAFE_EXTERNAL_OPERATIONS,
            RiskLevel.H3_PROTECTED: SAFE_EXTERNAL_OPERATIONS,
        }
        for risk, allowed in expected.items():
            with self.subTest(risk=risk):
                provisional = HanGuard(()).evaluate_provisional(
                    "project-a",
                    risk,
                    (),
                    evaluation_status=EvaluationStatus.COMPLETE,
                )
                final = HanGuard(()).evaluate_final(
                    provisional,
                    adapter_baseline=RiskLevel.H0_PROJECT,
                    signals=(),
                    available_operations=ALL_OPERATIONS,
                    evaluation_status=EvaluationStatus.COMPLETE,
                )
                self.assertEqual(final.allowed_operations, allowed)
                self.assertEqual(final.blocked_operations, ALL_OPERATIONS - allowed)

    def test_h3_capture_or_overlay_rule_leaves_only_detect(self):
        for match_value in ("capture_black_frame", "overlay_forbidden"):
            with self.subTest(match_value=match_value):
                rule = make_rule(
                    rule_id=match_value,
                    signal_type=SignalType.CAPTURE_RESULT,
                    match_value=match_value,
                    blocked_operations={
                        RouteOperation.CAPTURE,
                        RouteOperation.OCR,
                        RouteOperation.VISUAL_REPLACE,
                    },
                )
                signal = make_signal(
                    signal_type=SignalType.CAPTURE_RESULT,
                    value=match_value.upper(),
                )
                guard = HanGuard((rule,))
                provisional = guard.evaluate_provisional(
                    "project-a",
                    RiskLevel.H0_PROJECT,
                    (),
                    evaluation_status=EvaluationStatus.COMPLETE,
                )
                final = guard.evaluate_final(
                    provisional,
                    RiskLevel.H0_PROJECT,
                    (signal,),
                    available_operations=ALL_OPERATIONS,
                    evaluation_status=EvaluationStatus.COMPLETE,
                )
                self.assertEqual(final.risk_after, RiskLevel.H3_PROTECTED)
                self.assertEqual(final.allowed_operations, {RouteOperation.DETECT})

    def test_each_non_complete_status_fails_closed_with_distinct_reason(self):
        for status in (
            EvaluationStatus.MISSING_EVIDENCE,
            EvaluationStatus.UNKNOWN_RULE,
            EvaluationStatus.EVALUATION_FAILED,
        ):
            with self.subTest(status=status):
                plan = HanGuard(()).evaluate_provisional(
                    "project-a",
                    RiskLevel.H0_PROJECT,
                    (),
                    evaluation_status=status,
                )
                self.assertEqual(plan.risk_after, RiskLevel.H2_RESTRICTED)
                self.assertTrue(plan.unknown_evidence)
                self.assertEqual(plan.evaluation_status, status)
                self.assertIn(status.value, plan.decision_reasons)

    def test_missing_baselines_fail_closed_with_auditable_reasons(self):
        provisional = HanGuard(()).evaluate_provisional(
            "project-a",
            None,
            (),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(provisional.risk_after, RiskLevel.H2_RESTRICTED)
        self.assertTrue(provisional.unknown_evidence)
        self.assertIn("missing_user_baseline", provisional.decision_reasons)

        low_provisional = HanGuard(()).evaluate_provisional(
            "project-b",
            RiskLevel.H0_PROJECT,
            (),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        final = HanGuard(()).evaluate_final(
            low_provisional,
            None,
            (),
            available_operations=ALL_OPERATIONS,
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(final.risk_after, RiskLevel.H2_RESTRICTED)
        self.assertTrue(final.unknown_evidence)
        self.assertIn("missing_adapter_baseline", final.decision_reasons)

    def test_final_status_precedence_preserves_prior_reasons_and_deduplicates(self):
        signal = make_signal()
        provisional = self.guard.evaluate_provisional(
            "project-a",
            RiskLevel.H0_PROJECT,
            (signal, signal),
            evaluation_status=EvaluationStatus.UNKNOWN_RULE,
        )
        final = self.guard.evaluate_final(
            provisional,
            RiskLevel.H0_PROJECT,
            (signal,),
            available_operations=ALL_OPERATIONS,
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(final.evaluation_status, EvaluationStatus.UNKNOWN_RULE)
        self.assertEqual(len(final.matches), 1)
        self.assertEqual(final.decision_reasons.count("unknown_rule"), 1)
        self.assertEqual(final.decision_reasons.count("protected environment"), 1)

        failed = self.guard.evaluate_final(
            provisional,
            RiskLevel.H0_PROJECT,
            (),
            available_operations=ALL_OPERATIONS,
            evaluation_status=EvaluationStatus.EVALUATION_FAILED,
        )
        self.assertEqual(failed.evaluation_status, EvaluationStatus.EVALUATION_FAILED)
        self.assertEqual(
            failed.decision_reasons,
            ("protected environment", "unknown_rule", "evaluation_failed"),
        )

    def test_final_defends_against_corrupted_predecessor_risk_and_unknown_flag(self):
        signal = make_signal()
        provisional = self.guard.evaluate_provisional(
            "project-a",
            RiskLevel.H0_PROJECT,
            (signal,),
            evaluation_status=EvaluationStatus.UNKNOWN_RULE,
        )
        self.assertEqual(provisional.risk_after, RiskLevel.H3_PROTECTED)
        object.__setattr__(provisional, "risk_after", RiskLevel.H0_PROJECT)
        object.__setattr__(provisional, "unknown_evidence", False)

        final = self.guard.evaluate_final(
            provisional,
            RiskLevel.H0_PROJECT,
            (),
            available_operations=ALL_OPERATIONS,
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(final.risk_before, RiskLevel.H3_PROTECTED)
        self.assertEqual(final.risk_after, RiskLevel.H3_PROTECTED)
        self.assertEqual(final.evaluation_status, EvaluationStatus.UNKNOWN_RULE)
        self.assertTrue(final.unknown_evidence)

    def test_final_rejects_wrong_phase_and_invalid_capabilities(self):
        provisional = HanGuard(()).evaluate_provisional(
            "project-a",
            RiskLevel.H0_PROJECT,
            (),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        final = HanGuard(()).evaluate_final(
            provisional,
            RiskLevel.H0_PROJECT,
            (),
            available_operations=ALL_OPERATIONS,
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        with self.assertRaises(ValueError):
            HanGuard(()).evaluate_final(
                final,
                RiskLevel.H0_PROJECT,
                (),
                available_operations=ALL_OPERATIONS,
                evaluation_status=EvaluationStatus.COMPLETE,
            )
        for capabilities in ({RouteOperation.DETECT}, frozenset({"detect"})):
            with self.subTest(capabilities=capabilities):
                with self.assertRaises(TypeError):
                    HanGuard(()).evaluate_final(
                        provisional,
                        RiskLevel.H0_PROJECT,
                        (),
                        available_operations=capabilities,
                        evaluation_status=EvaluationStatus.COMPLETE,
                    )

    def test_invalid_api_arguments_are_rejected(self):
        with self.assertRaises(TypeError):
            HanGuard(("not-a-rule",))
        with self.assertRaises(TypeError):
            HanGuard(()).evaluate_provisional(
                "project-a",
                "H0_PROJECT",
                (),
                evaluation_status=EvaluationStatus.COMPLETE,
            )
        with self.assertRaises(TypeError):
            HanGuard(()).evaluate_provisional(
                "project-a",
                RiskLevel.H0_PROJECT,
                ("not-a-signal",),
                evaluation_status=EvaluationStatus.COMPLETE,
            )

    def test_all_fixed_guard_cases_match_expected_route(self):
        payload = json.loads(
            (ROOT / "benchmarks/guard_risk_cases.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(payload["cases"]), 80)
        for case in payload["cases"]:
            with self.subTest(case_id=case["case_id"]):
                rules = tuple(HanGuardRule.from_dict(item) for item in case["rules"])
                signals = tuple(RiskSignal.from_dict(item) for item in case["signals"])
                guard = HanGuard(rules)
                provisional = guard.evaluate_provisional(
                    case["project_id"],
                    RiskLevel[case["user_baseline"]] if case["user_baseline"] else None,
                    signals,
                    evaluation_status=EvaluationStatus(
                        case["provisional_evaluation_status"]
                    ),
                )
                plan = guard.evaluate_final(
                    provisional,
                    adapter_baseline=(
                        RiskLevel[case["adapter_baseline"]]
                        if case["adapter_baseline"]
                        else None
                    ),
                    signals=signals,
                    available_operations=frozenset(
                        RouteOperation(item) for item in case["available_operations"]
                    ),
                    evaluation_status=EvaluationStatus(
                        case["final_evaluation_status"]
                    ),
                )
                self.assertEqual(plan.risk_after.name, case["expected_risk"])
                self.assertEqual(
                    plan.evaluation_status.value,
                    case["final_evaluation_status"],
                )
                if plan.evaluation_status is not EvaluationStatus.COMPLETE:
                    self.assertIn(plan.evaluation_status.value, plan.decision_reasons)
                self.assertEqual(
                    sorted(item.value for item in plan.allowed_operations),
                    sorted(case["expected_allowed_operations"]),
                )
                self.assertEqual(
                    sorted(item.value for item in plan.blocked_operations),
                    sorted(case["expected_blocked_operations"]),
                )


if __name__ == "__main__":
    unittest.main()
