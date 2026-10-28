from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_localizer.hanengine import (
    LocalizationCatalog,
    LocalizationEntry,
    LocalModelBenchmarkReport,
    TranslationProviderError,
    TranslationResult,
    benchmark_local_model,
    select_local_model_samples,
    write_local_model_benchmark,
)


def _entry(relative_path: str, text: str, index: int) -> LocalizationEntry:
    return LocalizationEntry(
        segment_id=f"unity:{index}",
        relative_path=relative_path,
        source_text=text,
        source_hash=f"hash-{index}",
        kind="tsv",
        locator={"type": "tsv", "line": index, "key": f"KEY.{index}"},
    )


def _catalog(entries: tuple[LocalizationEntry, ...]) -> LocalizationCatalog:
    return LocalizationCatalog(
        engine_id="unity",
        language="zh-CN",
        source_language="en",
        project_fingerprint="fingerprint",
        files=tuple(dict.fromkeys(entry.relative_path for entry in entries)),
        entries=entries,
    )


class LocalModelBenchmarkTests(unittest.TestCase):
    def test_stratified_sampling_round_robins_files(self):
        entries = tuple(
            [_entry("Game.tsv", "Game 1", 1), _entry("Game.tsv", "Game 2", 2)]
            + [_entry("HUD.tsv", "HUD 1", 3), _entry("HUD.tsv", "HUD 2", 4)]
            + [_entry("Menu.tsv", "Menu 1", 5)]
        )
        selected = select_local_model_samples(entries, sample_count=4)
        self.assertEqual(
            [(item.relative_path, item.source_text) for item in selected],
            [("Game.tsv", "Game 1"), ("HUD.tsv", "HUD 1"), ("Menu.tsv", "Menu 1"), ("Game.tsv", "Game 2")],
        )

    def test_sampling_rejects_invalid_count(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            select_local_model_samples((), sample_count=0)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            select_local_model_samples((), sample_count=True)

    def test_benchmark_records_success_failure_latency_and_percentiles(self):
        entries = (_entry("Game.tsv", "Start", 1), _entry("HUD.tsv", "Move [move]", 2))
        catalog = _catalog(entries)

        class FakeProvider:
            def __init__(self, endpoint, **kwargs):
                self.endpoint = endpoint

            def translate(self, request):
                if request.text == "Start":
                    return TranslationResult("开始", "fake", "test", 0.9)
                raise TranslationProviderError("runtime failed")

        with patch("game_localizer.hanengine.local_model.LocalModelTranslationProvider", FakeProvider):
            report = benchmark_local_model(
                catalog,
                "http://127.0.0.1:8080/translate",
                model_name="test-model",
                sample_count=2,
            )

        self.assertIsInstance(report, LocalModelBenchmarkReport)
        self.assertEqual(report.sample_count, 2)
        self.assertEqual(report.translated_count, 1)
        self.assertEqual(report.failed_count, 1)
        self.assertGreaterEqual(report.average_latency_ms, 0.0)
        self.assertGreaterEqual(report.p50_latency_ms, 0.0)
        self.assertGreaterEqual(report.p95_latency_ms, report.p50_latency_ms)
        self.assertFalse(report.passed)
        self.assertTrue(report.items[1].error.startswith("TranslationProviderError:"))

    def test_placeholder_failure_is_routed_to_failed_item(self):
        catalog = _catalog((_entry("HUD.tsv", "Use [move]", 1),))

        class FakeProvider:
            def __init__(self, endpoint, **kwargs):
                pass

            def translate(self, request):
                return TranslationResult("使用", "fake", "test", 0.4)

        with patch("game_localizer.hanengine.local_model.LocalModelTranslationProvider", FakeProvider):
            report = benchmark_local_model(catalog, "http://127.0.0.1:8080/translate", sample_count=1)
        self.assertEqual(report.failed_count, 1)
        self.assertTrue(report.items[0].error.startswith("TranslationProviderError:"))

    def test_write_report_emits_schema_and_utf8_json(self):
        catalog = _catalog((_entry("Game.tsv", "Start", 1),))

        class FakeProvider:
            def __init__(self, endpoint, **kwargs):
                pass

            def translate(self, request):
                return TranslationResult("开始", "fake", "test", 1.0)

        with patch("game_localizer.hanengine.local_model.LocalModelTranslationProvider", FakeProvider):
            report = benchmark_local_model(catalog, "http://127.0.0.1:8080/translate", sample_count=1)
        with tempfile.TemporaryDirectory() as directory:
            path = write_local_model_benchmark(report, Path(directory) / "report.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "hanengine.local-model-benchmark/v1")
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["summary"]["translated_count"], 1)
        self.assertEqual(payload["items"][0]["target_text"], "开始")


if __name__ == "__main__":
    unittest.main()
