import json
import unittest

from game_localizer.hanengine.visual_style import (
    FontAssetReference,
    TextMetrics,
    TextRegionObservation,
    VisualComparison,
    VisualGateDecision,
    VisualGateResult,
    VisualHardGatePolicy,
    VisualHardGateReport,
    VisualJudgeDecision,
    VisualJudgeResult,
    VisualStyleProfile,
    evaluate_visual_gate,
    run_visual_hard_gates,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


class FakeJudge:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def judge(self, profile, comparison):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class VisualStyleTests(unittest.TestCase):
    def profile(self, *scenarios):
        return VisualStyleProfile(
            profile_id="menu-ui",
            engine_id="unity",
            renderer="textmeshpro",
            source_fingerprint=HASH_A,
            font_assets=(
                FontAssetReference("latin", "fonts/source.ttf", HASH_B, ("U+0000-U+007F",)),
                FontAssetReference("cjk", "fonts/cjk.ttf", HASH_C, ("U+4E00-U+9FFF",)),
            ),
            metrics=TextMetrics(
                point_size=28,
                line_height=34,
                baseline=26,
                horizontal_scale=0.86,
                outline_width=1.25,
            ),
            material_parameters={"face_color": "#F6F1E8", "outline": 0.12},
            scenarios=scenarios or ("main-menu",),
        )

    def region(self, *, x=20, y=40, width=210, height=38, lines=1, baseline=28, **changes):
        values = {
            "region_id": "primary-action",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "line_count": lines,
            "baseline": baseline,
            "font_resolved": True,
        }
        values.update(changes)
        return TextRegionObservation(**values)

    def comparison(self, sample_id="main-menu", *, reference=None, candidate=None):
        return VisualComparison(
            sample_id=sample_id,
            reference_image_sha256=HASH_A,
            candidate_image_sha256=HASH_B,
            reference_regions=(reference or self.region(),),
            candidate_regions=(candidate or self.region(),),
        )

    def test_profile_round_trip_is_json_safe_and_copies_material(self):
        profile = self.profile("main-menu", "settings")
        payload = profile.to_dict()
        payload["material_parameters"]["outline"] = 0.5

        self.assertEqual(profile.material_parameters["outline"], 0.12)
        self.assertEqual(VisualStyleProfile.from_dict(profile.to_dict()), profile)

    def test_visual_evidence_round_trip_survives_json_storage(self):
        comparison = self.comparison(
            candidate=self.region(lines=2, x=21, baseline=29),
        )
        gate = run_visual_hard_gates(comparison)
        result = evaluate_visual_gate(
            self.profile(),
            (comparison,),
            judge=FakeJudge(
                VisualJudgeResult(VisualJudgeDecision.PASS, 0.92, 0.88, "fake-v1")
            ),
        )

        encoded = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
        restored = VisualGateResult.from_dict(json.loads(encoded))

        self.assertEqual(restored, result)
        self.assertEqual(VisualHardGateReport.from_dict(gate.to_dict()), gate)

    def test_visual_evidence_rejects_tampered_derived_fields_and_unknown_nested_data(self):
        comparison = self.comparison()
        result = evaluate_visual_gate(
            self.profile(),
            (comparison,),
            judge=FakeJudge(
                VisualJudgeResult(VisualJudgeDecision.PASS, 0.92, 0.88, "fake-v1")
            ),
        )
        payload = result.to_dict()
        payload["hard_gate"]["passed"] = False
        with self.assertRaisesRegex(ValueError, "passed"):
            VisualGateResult.from_dict(payload)

        payload = result.to_dict()
        payload["comparisons"][0]["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "fields"):
            VisualGateResult.from_dict(payload)

        payload = result.to_dict()
        payload["judge_results"][0]["decision"] = "unknown"
        with self.assertRaisesRegex(ValueError, "decision"):
            VisualGateResult.from_dict(payload)

    def test_profile_rejects_duplicate_font_roles_and_unknown_schema_fields(self):
        with self.assertRaisesRegex(ValueError, "roles"):
            VisualStyleProfile(
                profile_id="menu-ui",
                engine_id="unity",
                renderer="textmeshpro",
                source_fingerprint=HASH_A,
                font_assets=(
                    FontAssetReference("cjk", "fonts/a.ttf", HASH_B),
                    FontAssetReference("CJK", "fonts/b.ttf", HASH_C),
                ),
                metrics=TextMetrics(28, 34, 26),
                material_parameters={},
                scenarios=("main-menu",),
            )
        payload = self.profile().to_dict()
        payload["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "fields"):
            VisualStyleProfile.from_dict(payload)

    def test_hard_gates_accept_allowed_line_growth(self):
        report = run_visual_hard_gates(
            self.comparison(candidate=self.region(lines=2, x=21, baseline=29)),
            VisualHardGatePolicy(
                max_position_delta_px=2,
                max_size_delta_px=2,
                max_baseline_delta_px=2,
                max_line_count_delta=1,
            ),
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.failed_codes, ())

    def test_line_budgets_block_long_text_and_accept_text_within_budget(self):
        policy = VisualHardGatePolicy(
            max_line_count_delta=5,
            max_line_counts={"main-menu": {"primary-action": 2}},
        )

        accepted = run_visual_hard_gates(
            self.comparison(candidate=self.region(lines=2)),
            policy,
        )
        blocked = run_visual_hard_gates(
            self.comparison(candidate=self.region(lines=3)),
            policy,
        )

        self.assertTrue(accepted.passed)
        self.assertEqual(blocked.failed_codes, ("line_budget",))

    def test_line_budget_policy_reads_legacy_payload_and_rejects_unknown_targets(self):
        legacy = {
            "max_position_delta_px": 2.0,
            "max_size_delta_px": 2.0,
            "max_baseline_delta_px": 2.0,
            "max_line_count_delta": 1,
            "require_font_resolution": True,
        }
        restored = VisualHardGatePolicy.from_dict(legacy)
        self.assertEqual(restored.max_line_counts, {})

        policy = VisualHardGatePolicy(
            max_line_counts={"main-menu": {"missing-region": 2}}
        )
        report = run_visual_hard_gates(self.comparison(), policy)
        self.assertIn("line_budget_regions", report.failed_codes)

        result = evaluate_visual_gate(
            self.profile(),
            (self.comparison(),),
            policy=VisualHardGatePolicy(
                max_line_counts={"missing-scenario": {"primary-action": 2}}
            ),
        )
        self.assertEqual(result.decision, VisualGateDecision.BLOCKED)
        self.assertIn("line_budget_scenarios", result.hard_gate.failed_codes)

        unknown = dict(legacy, unexpected=True)
        with self.assertRaisesRegex(ValueError, "fields"):
            VisualHardGatePolicy.from_dict(unknown)

    def test_hard_gates_block_missing_glyphs_overflow_and_unresolved_font(self):
        report = run_visual_hard_gates(
            self.comparison(
                candidate=self.region(
                    missing_codepoints=("U+4F60",),
                    overflow=True,
                    clipped=True,
                    font_resolved=False,
                )
            )
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            set(report.failed_codes),
            {"missing_glyphs", "overflow", "clipped", "font_resolution"},
        )

    def test_hard_gates_block_missing_regions_and_geometry_drift(self):
        report = run_visual_hard_gates(
            self.comparison(candidate=self.region(x=30, width=230))
        )
        self.assertFalse(report.passed)
        self.assertEqual(set(report.failed_codes), {"region_position", "region_size"})

        missing = VisualComparison(
            sample_id="main-menu",
            reference_image_sha256=HASH_A,
            candidate_image_sha256=HASH_B,
            reference_regions=(self.region(),),
            candidate_regions=(),
        )
        self.assertIn("region_set", run_visual_hard_gates(missing).failed_codes)

    def test_gate_blocks_before_calling_judge_when_hard_gate_fails(self):
        judge = FakeJudge(
            VisualJudgeResult(VisualJudgeDecision.PASS, 0.99, 0.99, "fake-v1")
        )

        result = evaluate_visual_gate(
            self.profile(),
            (self.comparison(candidate=self.region(overflow=True)),),
            judge=judge,
        )

        self.assertEqual(result.decision, VisualGateDecision.BLOCKED)
        self.assertEqual(judge.calls, 0)
        self.assertIn("hard_gate:overflow", result.reasons)

    def test_gate_escalates_when_no_judge_is_configured(self):
        result = evaluate_visual_gate(self.profile(), (self.comparison(),))

        self.assertEqual(result.decision, VisualGateDecision.ESCALATE)
        self.assertEqual(result.reasons, ("visual_judge_unavailable",))

    def test_gate_passes_only_with_high_confidence_judge_result(self):
        judge = FakeJudge(
            VisualJudgeResult(VisualJudgeDecision.PASS, 0.92, 0.88, "fake-v1")
        )
        result = evaluate_visual_gate(self.profile(), (self.comparison(),), judge=judge)

        self.assertEqual(result.decision, VisualGateDecision.PASS)
        self.assertEqual(result.reasons, ())
        self.assertEqual(result.judge_results[0].model, "fake-v1")
        payload = result.to_dict()
        self.assertEqual(payload["comparisons"][0]["reference_image_sha256"], HASH_A)
        self.assertNotIn("image_bytes", json.dumps(payload, sort_keys=True))
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_gate_can_require_human_review_after_a_clean_judge_pass(self):
        result = evaluate_visual_gate(
            self.profile(),
            (self.comparison(),),
            judge=FakeJudge(
                VisualJudgeResult(VisualJudgeDecision.PASS, 0.92, 0.88, "fake-v1")
            ),
            judge_can_authorize_pass=False,
        )

        self.assertEqual(result.decision, VisualGateDecision.ESCALATE)
        self.assertEqual(result.reasons, ("visual_judge_pass_requires_human_review",))
        self.assertEqual(result.judge_results[0].decision, VisualJudgeDecision.PASS)

    def test_gate_escalates_on_style_rejection_low_confidence_or_judge_error(self):
        rejected = evaluate_visual_gate(
            self.profile(),
            (self.comparison(),),
            judge=FakeJudge(
                VisualJudgeResult(VisualJudgeDecision.FAIL, 0.40, 0.95, "fake-v1")
            ),
        )
        self.assertEqual(rejected.decision, VisualGateDecision.ESCALATE)
        self.assertIn("visual_judge:main-menu:fail", rejected.reasons)

        uncertain = evaluate_visual_gate(
            self.profile(),
            (self.comparison(),),
            judge=FakeJudge(
                VisualJudgeResult(VisualJudgeDecision.PASS, 0.91, 0.40, "fake-v1")
            ),
        )
        self.assertEqual(uncertain.decision, VisualGateDecision.ESCALATE)
        self.assertIn("judge_confidence_below_threshold:main-menu", uncertain.reasons)

        unavailable = evaluate_visual_gate(
            self.profile(),
            (self.comparison(),),
            judge=FakeJudge(error=RuntimeError("offline")),
        )
        self.assertEqual(unavailable.decision, VisualGateDecision.ESCALATE)
        self.assertEqual(unavailable.reasons, ("visual_judge_error:RuntimeError",))

    def test_gate_requires_evidence_for_every_profile_scenario(self):
        result = evaluate_visual_gate(
            self.profile("main-menu", "settings"),
            (self.comparison("main-menu"),),
        )

        self.assertEqual(result.decision, VisualGateDecision.BLOCKED)
        self.assertIn("hard_gate:scenario_set", result.reasons)


if __name__ == "__main__":
    unittest.main()
