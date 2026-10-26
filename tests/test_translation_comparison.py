from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from game_localizer.adapters.unity_addressables import _AddressablesProfile, _AddressablesLayout, _TableRecord
from game_localizer.hanengine.comparison import compare_unity_catalog, comparison_html
from game_localizer.hanengine.multiengine import LocalizationCatalog, LocalizationEntry


class TranslationComparisonTests(unittest.TestCase):
    def _catalog(self, entries: list[LocalizationEntry]) -> LocalizationCatalog:
        return LocalizationCatalog(
            engine_id="unity",
            language="zh-CN",
            source_language="en",
            project_fingerprint="fingerprint",
            files=("strings.bundle",),
            entries=tuple(entries),
        )

    def _entry(
        self,
        entry_id: int,
        source: str,
        target: str | None,
        *,
        table: str = "UI",
    ) -> LocalizationEntry:
        return LocalizationEntry(
            segment_id=f"unity:{entry_id}",
            relative_path="strings.bundle",
            source_text=source,
            source_hash="hash",
            kind="unity_addressables_string",
            locator={"table_name": table, "entry_id": entry_id},
            target_text=target,
        )

    def _profile(self, official: dict[tuple[str, int], str], sources: dict[tuple[str, int], str]):
        layout = _AddressablesLayout(Path("/project"), Path("/en.bundle"), Path("/zh.bundle"), Path("/catalog.bin"))
        chinese = tuple(_TableRecord(table, entry_id, text, 1, index) for index, ((table, entry_id), text) in enumerate(official.items()))
        english = tuple(_TableRecord(table, entry_id, text, 1, index) for index, ((table, entry_id), text) in enumerate(sources.items()))
        return _AddressablesProfile(layout, (), english, chinese, "fingerprint")

    def test_comparison_marks_matches_differences_and_quality_errors(self):
        entries = [
            self._entry(1, "Play", "开始"),
            self._entry(2, "Invite Friend", "邀请朋友"),
            self._entry(3, "Revive {0}", "复活"),
            self._entry(4, "Inspect", "检查�"),
            self._entry(5, "Credits", "Credits"),
            self._entry(6, "Missing", None),
            self._entry(7, "English", "中文"),
        ]
        official = {
            ("UI", 1): "开始",
            ("UI", 2): "邀请好友",
            ("UI", 3): "复活 {0}",
            ("UI", 4): "检查",
            ("UI", 5): "名单",
            ("UI", 6): "缺失",
            ("UI", 7): "英文",
        }
        sources = {("UI", index): entry.source_text for index, entry in enumerate(entries, 1)}
        sources[("UI", 7)] = "Different English source"
        with patch(
            "game_localizer.adapters.unity_addressables._profile",
            return_value=self._profile(official, sources),
        ):
            report = compare_unity_catalog(Path("/project"), self._catalog(entries))

        by_id = {item["entry_id"]: item for item in report["entries"]}
        self.assertEqual(by_id[1]["category"], "match")
        self.assertEqual(by_id[2]["category"], "difference")
        self.assertEqual(by_id[3]["category"], "format_error")
        self.assertEqual(by_id[4]["category"], "corrupt_output")
        self.assertEqual(by_id[5]["category"], "untranslated")
        self.assertEqual(by_id[5]["severity"], "warning")
        self.assertEqual(by_id[6]["category"], "missing_target")
        self.assertEqual(by_id[7]["category"], "source_mismatch")
        self.assertEqual(by_id[2]["recommended_text"], "邀请好友")
        self.assertEqual(report["summary"]["entry_count"], 7)

    def test_html_escapes_translation_text_and_supports_search(self):
        report = {
            "summary": {"entry_count": 1, "match_count": 0, "difference_count": 1, "error_count": 0, "review_count": 1},
            "entries": [{
                "severity": "review",
                "category": "difference",
                "table_name": "UI",
                "entry_id": 1,
                "source_text": "<script>",
                "official_zh": "官方",
                "candidate_zh": "候选",
                "reasons": ["candidate_differs_from_official"],
            }],
        }
        page = comparison_html(report)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("id=\"search\"", page)
        self.assertNotIn("<td><script></td>", page)


if __name__ == "__main__":
    unittest.main()
