import json
import tempfile
import unittest
from pathlib import Path

from translator import (
    TranslationError,
    decode_bytes,
    load_translation_dictionary,
    missing_placeholders,
    transform_csv,
    transform_json,
    transform_plaintext,
)


class EncodingAndDictionaryTests(unittest.TestCase):
    def test_decode_bytes_supports_utf8_bom_and_cp932(self):
        self.assertEqual(decode_bytes("ゲーム開始".encode("utf-8-sig")), ("ゲーム開始", "utf-8-sig"))
        self.assertEqual(decode_bytes("ゲーム開始".encode("cp932")), ("ゲーム開始", "cp932"))

    def test_dictionary_requires_nonempty_string_keys_and_string_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "dictionary.json")
            path.write_text(json.dumps({"": "空"}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(TranslationError, "不能为空"):
                load_translation_dictionary(path)

            path.write_text(json.dumps({"Start": 1}), encoding="utf-8")
            with self.assertRaisesRegex(TranslationError, "字符串"):
                load_translation_dictionary(path)

    def test_placeholder_check_reports_only_missing_occurrences(self):
        self.assertEqual(
            missing_placeholders("Hello {name}, %1\\n", "你好 %1，{name}\\n"),
            (),
        )
        self.assertEqual(
            missing_placeholders("HP %1 / %1", "生命值 %1"),
            ("%1",),
        )


class TransformationTests(unittest.TestCase):
    def test_json_changes_only_string_values_and_reports_json_paths(self):
        source = '{"New Game": "New Game", "menu": [{"label": "Options"}]}'
        result = transform_json(source, {"New Game": "新游戏"})
        parsed = json.loads(result.content)
        self.assertEqual(parsed["New Game"], "新游戏")
        self.assertEqual(parsed["menu"][0]["label"], "Options")
        self.assertIn("New Game", parsed)
        self.assertEqual(result.matches[0].location, "JSON $['New Game']")
        self.assertEqual(result.unmatched[0].location, "JSON $.menu[0].label")

    def test_csv_sniffs_semicolon_and_matches_complete_cells(self):
        result = transform_csv("id;text\n1;New Game\n2;Options\n", {"New Game": "新游戏"})
        self.assertIn("1;新游戏", result.content)
        self.assertEqual(result.replacement_count, 1)
        self.assertIn("CSV 第 3 行第 2 列", [item.location for item in result.unmatched])

    def test_plaintext_uses_single_pass_longest_first_matching(self):
        result = transform_plaintext(
            "Start New Game, {name}!\nOptions\n",
            {"Start": "开始", "New Game": "新游戏", "Start New Game, {name}!": "开始新游戏，{name}！"},
        )
        self.assertEqual(result.content.splitlines()[0], "开始新游戏，{name}！")
        self.assertEqual(result.replacement_count, 1)
        self.assertEqual(result.matches[0].location, "TXT 第 1 行")
        self.assertEqual(result.untranslated, {"Options": ""})

    def test_plaintext_partial_match_exports_the_complete_original_line(self):
        result = transform_plaintext("Open New Game\n", {"New Game": "新游戏"})
        self.assertEqual(result.content, "Open 新游戏\n")
        self.assertEqual(result.untranslated, {"Open New Game": ""})
        self.assertEqual(result.unmatched[0].original, "Open New Game")
