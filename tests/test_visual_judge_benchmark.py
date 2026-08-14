from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "benchmark_visual_judges.py"
SPEC = importlib.util.spec_from_file_location("benchmark_visual_judges", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load visual judge benchmark module")
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


class VisualJudgeBenchmarkTests(unittest.TestCase):
    def test_zhipu_visual_providers_share_the_same_key_and_endpoint(self):
        zhipu = [provider for provider in benchmark.PROVIDERS if provider.provider_id.startswith("glm")]

        self.assertEqual(len(zhipu), 2)
        self.assertEqual({provider.key_env for provider in zhipu}, {"ZHIPU_API_KEY"})
        self.assertEqual(len({provider.endpoint for provider in zhipu}), 1)
        self.assertEqual(
            {provider.model for provider in zhipu},
            {"glm-4.6v-flashx", "glm-4.6v"},
        )

    def test_data_url_compresses_remote_copy_as_jpeg(self):
        class FakeImage:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def convert(self, mode):
                self.mode = mode
                return self

            def save(self, destination, **options):
                self.options = options
                destination.write(b"jpeg")

        fake = FakeImage()
        with patch("PIL.Image.open", return_value=fake):
            result = benchmark._data_url(Path("unused.png"))

        self.assertEqual(result, "data:image/jpeg;base64,anBlZw==")
        self.assertEqual(fake.mode, "RGB")
        self.assertEqual(fake.options["format"], "JPEG")

    def test_run_rejects_unknown_sample_selection(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            for name in ("reference.png", "candidate.png"):
                (root / name).write_bytes(b"placeholder")
            dataset = root / "dataset.json"
            dataset.write_text(
                json.dumps(
                    {
                        "schema_version": benchmark.SCHEMA_VERSION,
                        "samples": [
                            {
                                "sample_id": "known",
                                "reference_image": "reference.png",
                                "candidate_image": "candidate.png",
                                "expected_defect": True,
                                "expected_issue_codes": ["residual_untranslated_text"],
                            },
                            {
                                "sample_id": "known-negative",
                                "reference_image": "reference.png",
                                "candidate_image": "candidate.png",
                                "expected_defect": False,
                                "expected_issue_codes": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(benchmark.BenchmarkError, "unknown sample IDs"):
                benchmark.run(dataset, root / "unused-benchmark.json", benchmark.PROVIDERS[:1], ("does-not-exist",))

    def test_validate_judge_json_accepts_exact_contract(self):
        payload = {
            "decision": "fail",
            "style_score": 0.4,
            "confidence": 0.9,
            "model": "fixture",
            "issues": ["residual_untranslated_text: Page 1"],
        }

        result, error = benchmark.validate_judge_json(json.dumps(payload))

        self.assertEqual(result, payload)
        self.assertIsNone(error)

    def test_sample_prompt_does_not_leak_truth_from_sample_id(self):
        prompt = benchmark._sample_prompt("style_readability-04")

        self.assertNotIn("style_readability-04", prompt)
        self.assertIn("低对比度", prompt)

    def test_validate_judge_json_does_not_repair_markdown(self):
        raw = "```json\n{\"decision\":\"pass\"}\n```"

        result, error = benchmark.validate_judge_json(raw)

        self.assertIsNone(result)
        self.assertIn("invalid_json", error)

    def test_validate_judge_json_rejects_extra_fields_and_invalid_scores(self):
        base = {
            "decision": "pass",
            "style_score": 1.0,
            "confidence": 0.9,
            "model": "fixture",
            "issues": [],
        }
        extra = {**base, "explanation": "not allowed"}
        invalid_score = {**base, "style_score": 1.1}

        self.assertIsNone(benchmark.validate_judge_json(json.dumps(extra))[0])
        self.assertIsNone(benchmark.validate_judge_json(json.dumps(invalid_score))[0])

    def test_response_usage_accepts_exact_non_negative_token_counts(self):
        payload = {
            "usage": {
                "prompt_tokens": 101,
                "completion_tokens": 12,
                "total_tokens": 113,
                "ignored_provider_field": 9,
            }
        }

        self.assertEqual(
            benchmark._response_usage(payload),
            {"prompt_tokens": 101, "completion_tokens": 12, "total_tokens": 113},
        )
        self.assertIsNone(benchmark._response_usage({"usage": {"total_tokens": 1}}))

    def test_summarize_counts_scene_level_misses_and_false_positives(self):
        provider = benchmark.PROVIDERS[0]
        records = [
            self._record(True, "pass", []),
            self._record(True, "fail", ["residual_untranslated_text: Page 1"]),
            self._record(False, "escalate", []),
            self._record(False, "pass", []),
        ]

        summary = benchmark.summarize(provider, records)

        self.assertEqual(summary["missed_defect_count"], 1)
        self.assertEqual(summary["miss_rate"], 0.5)
        self.assertEqual(summary["false_positive_count"], 1)
        self.assertEqual(summary["false_positive_rate"], 0.5)
        self.assertEqual(summary["json_compliance_rate"], 1.0)
        self.assertTrue(summary["benchmark_complete"])
        self.assertEqual(summary["model_identity_match_rate"], 0.0)

    def test_summarize_reports_detection_classification_and_token_usage_by_issue(self):
        provider = benchmark.PROVIDERS[0]
        records = [
            self._record(
                True,
                "fail",
                ["clipped: button label is cut off"],
                expected_issue_codes=["clipped"],
                token_usage={"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            ),
            self._record(
                True,
                "fail",
                ["overflow: text crosses the panel"],
                expected_issue_codes=["clipped"],
                token_usage={"prompt_tokens": 120, "completion_tokens": 12, "total_tokens": 132},
            ),
            self._record(False, "pass", []),
        ]

        summary = benchmark.summarize(provider, records)

        clipped = summary["issue_code_summaries"]["clipped"]
        self.assertEqual(clipped["detection_recall"], 1.0)
        self.assertEqual(clipped["classification_recall"], 0.5)
        self.assertEqual(
            summary["token_usage"],
            {"prompt_tokens": 220, "completion_tokens": 22, "total_tokens": 242},
        )

    def test_choose_default_prioritizes_miss_rate_over_latency(self):
        fast_but_inaccurate = self._summary("glm-4.6v-flash", miss=0.4, latency=100)
        slow_but_accurate = self._summary("gemini-3.6-flash", miss=0.0, latency=1000)

        selected = benchmark.choose_default([fast_but_inaccurate, slow_but_accurate])

        self.assertEqual(selected, "gemini-3.6-flash")

    def test_choose_default_accepts_one_completed_provider(self):
        only_provider = self._summary("glm-4.6v-flash", miss=0.0, latency=500)

        selected = benchmark.choose_default([only_provider])

        self.assertEqual(selected, "glm-4.6v-flash")

    def test_incomplete_provider_is_not_selected_and_has_no_final_rates(self):
        provider = benchmark.PROVIDERS[0]
        records = [
            self._record(True, "fail", ["residual_untranslated_text: Page 1"]),
            {
                "expected_defect": True,
                "judge_result": None,
                "request_success": False,
                "latency_ms": None,
            },
            self._record(False, "pass", []),
        ]

        summary = benchmark.summarize(provider, records)

        self.assertIsNone(summary["miss_rate"])
        self.assertEqual(summary["observed_miss_rate"], 0.0)
        self.assertEqual(summary["false_positive_rate"], 0.0)
        self.assertFalse(summary["benchmark_complete"])
        self.assertIsNone(benchmark.choose_default([summary]))

    def test_subset_cannot_become_default_for_a_larger_dataset(self):
        provider = benchmark.PROVIDERS[0]
        records = [
            self._record(True, "fail", ["residual_untranslated_text: Page 1"]),
            self._record(False, "pass", []),
        ]

        summary = benchmark.summarize(provider, records, expected_sample_count=6)

        self.assertFalse(summary["dataset_complete"])
        self.assertFalse(summary["default_eligible"])
        self.assertIsNone(benchmark.choose_default([summary]))

    def test_dataset_rejects_all_negative_samples(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            image = root / "sample.png"
            image.write_bytes(b"not decoded during dataset validation")
            dataset = root / "dataset.json"
            dataset.write_text(
                json.dumps(
                    {
                        "schema_version": benchmark.SCHEMA_VERSION,
                        "samples": [
                            {
                                "sample_id": "negative",
                                "reference_image": "sample.png",
                                "candidate_image": "sample.png",
                                "expected_defect": False,
                                "expected_issue_codes": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(benchmark.BenchmarkError, "positive sample"):
                benchmark.load_dataset(dataset)

    @staticmethod
    def _record(
        expected_defect,
        decision,
        issues,
        *,
        expected_issue_codes=None,
        token_usage=None,
    ):
        return {
            "expected_defect": expected_defect,
            "expected_issue_codes": expected_issue_codes or [],
            "request_success": True,
            "judge_result": {
                "decision": decision,
                "style_score": 0.8,
                "confidence": 0.8,
                "model": "fixture",
                "issues": issues,
            },
            "latency_ms": 100.0,
            "token_usage": token_usage,
        }

    @staticmethod
    def _summary(model, *, miss, latency):
        return {
            "model": model,
            "miss_rate": miss,
            "json_compliance_rate": 1.0,
            "false_positive_rate": 0.0,
            "default_eligible": miss == 0.0,
            "latency_ms": {"median": latency},
        }


if __name__ == "__main__":
    unittest.main()
