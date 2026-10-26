from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.mine_glossary import mine_glossary


def _report(entries):
    return {
        "schema_version": "hanengine.translation-comparison/v1",
        "engine_id": "unity",
        "project_fingerprint": "f" * 64,
        "entries": entries,
    }


class MineGlossaryTests(unittest.TestCase):
    def test_mines_consistent_short_terms_with_frequency(self):
        report = _report(
            [
                {"source_text": "Clownfish", "official_zh": "小丑鱼"},
                {"source_text": "Clownfish", "official_zh": "小丑鱼"},
                {"source_text": "Headshot", "official_zh": "爆头"},
                {"source_text": "kg", "official_zh": "kg"},
                {"source_text": "m", "official_zh": "分"},
            ]
        )
        terms, mining = mine_glossary(report)
        self.assertEqual(
            terms,
            {"Clownfish": "小丑鱼", "Headshot": "爆头", "kg": "kg", "m": "分"},
        )
        self.assertEqual(mining["term_count"], 4)
        self.assertEqual(mining["conflict_count"], 0)
        self.assertEqual(mining["frequencies"]["Clownfish"], 2)

    def test_sentences_numbers_and_empty_references_are_skipped(self):
        report = _report(
            [
                {"source_text": "I have some spare snacks.", "official_zh": "我有一些多余的零食。"},
                {"source_text": "360", "official_zh": "360度转体击杀"},
                {"source_text": "Options", "official_zh": ""},
                {"source_text": "", "official_zh": "空"},
            ]
        )
        terms, mining = mine_glossary(report)
        self.assertEqual(terms, {})
        self.assertEqual(mining["term_count"], 0)

    def test_conflicting_renderings_go_to_conflicts_not_terms(self):
        report = _report(
            [
                {"source_text": "Boss", "official_zh": "首领"},
                {"source_text": "Boss", "official_zh": "Boss"},
                {"source_text": "Boss", "official_zh": "头目"},
            ]
        )
        terms, mining = mine_glossary(report)
        self.assertEqual(terms, {})
        self.assertEqual(mining["conflict_count"], 1)
        conflict = mining["conflicts"][0]
        self.assertEqual(conflict["source"], "Boss")
        self.assertEqual(conflict["count"], 3)
        self.assertEqual(
            list(conflict["renderings"].items()),
            [("首领", 1), ("Boss", 1), ("头目", 1)],
        )

    def test_rejects_unsupported_schema(self):
        with self.assertRaisesRegex(ValueError, "unsupported schema"):
            mine_glossary({"schema_version": "other/v1", "entries": []})


class MineGlossaryCliTests(unittest.TestCase):
    def test_cli_writes_glossary_and_report(self):
        from tools.mine_glossary import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "comparison.json"
            report_path.write_text(
                json.dumps(
                    _report([{"source_text": "Clownfish", "official_zh": "小丑鱼"}]),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            glossary_path = root / "glossary.json"
            mining_path = root / "mining.json"
            code = main(
                [
                    str(report_path),
                    "--output",
                    str(glossary_path),
                    "--report-out",
                    str(mining_path),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(glossary_path.read_text(encoding="utf-8")),
                {"Clownfish": "小丑鱼"},
            )
            self.assertEqual(
                json.loads(mining_path.read_text(encoding="utf-8"))["term_count"], 1
            )


if __name__ == "__main__":
    unittest.main()
