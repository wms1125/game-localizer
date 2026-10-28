import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cli import format_result
from translator import MatchPreview, ProcessingResult, UnmatchedPreview


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_cli_processes_resource_and_prints_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.json"
            dictionary = root / "dictionary.json"
            resource.write_text('{"title":"New Game","other":"Options"}', encoding="utf-8")
            dictionary.write_text(
                json.dumps({"New Game": "\u65b0\u6e38\u620f"}, ensure_ascii=False), encoding="utf-8"
            )
            completed = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), str(resource), str(dictionary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("[\u5339\u914d]", completed.stdout)
            self.assertIn("\u5b9e\u9645\u66ff\u6362: 1", completed.stdout)
            self.assertIn("\u672a\u7ffb\u8bd1\u6761\u76ee: 1", completed.stdout)

    def test_cli_returns_nonzero_for_invalid_dictionary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text("[]", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), str(resource), str(dictionary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("\u9519\u8bef:", completed.stderr)

    def test_cli_reports_unencodable_dictionary_text_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text('{"New Game":"\\ud800"}', encoding="ascii")

            completed = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), str(resource), str(dictionary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertIn("\u9519\u8bef:", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_cli_rejects_duplicate_dictionary_keys_without_outputs_or_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text(
                '{"New Game":"甲","New Game":"乙"}',
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), str(resource), str(dictionary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertIn("重复键", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertFalse((root / "game.zh.txt").exists())
            self.assertFalse((root / "game.untranslated.json").exists())

    def test_cli_wraps_integer_digit_limit_without_outputs_or_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.json"
            dictionary = root / "dictionary.json"
            resource.write_text('{"value":' + "1" * 5000 + "}", encoding="utf-8")
            dictionary.write_text("{}", encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), str(resource), str(dictionary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertIn("错误:", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertFalse((root / "game.zh.json").exists())
            self.assertFalse((root / "game.untranslated.json").exists())

    def test_cli_reports_output_resolve_runtime_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            loop = root / "loop"
            cyclic_output = loop / "translated.txt"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")
            os.symlink(loop, loop, target_is_directory=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "cli.py"),
                    str(resource),
                    str(dictionary),
                    "--output",
                    str(cyclic_output),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertIn("错误:", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_format_result_escapes_preview_values_to_one_line(self):
        original = 'Quote " slash \\ newline\nnext'
        translated = 'Translated " slash \\ newline\nnext'
        result = self.make_result(matches=[MatchPreview("JSON $.title", original, translated)])

        output = format_result(result)

        self.assertEqual(
            output.splitlines()[0],
            f"[\u5339\u914d] JSON $.title: {json.dumps(original, ensure_ascii=False)} -> "
            f"{json.dumps(translated, ensure_ascii=False)}",
        )
        self.assertEqual(len(output.splitlines()), 9)

    def test_format_result_has_no_preview_lines_when_nothing_matches(self):
        output = format_result(self.make_result())

        self.assertNotIn("[\u5339\u914d]", output)
        self.assertNotIn("[\u672a\u5339\u914d]", output)
        self.assertIn("\u5339\u914d\u6761\u76ee: 0", output)
        self.assertIn("\u672a\u7ffb\u8bd1\u6761\u76ee: 0", output)

    def test_format_result_limits_each_preview_category_to_fifty_items(self):
        matches = [MatchPreview(f"match-{index}", f"source-{index}", f"target-{index}") for index in range(51)]
        unmatched = [UnmatchedPreview(f"unmatched-{index}", f"source-{index}") for index in range(51)]

        output = format_result(self.make_result(matches=matches, unmatched=unmatched))
        lines = output.splitlines()
        match_lines = [line for line in lines if line.startswith("[\u5339\u914d]")]
        unmatched_lines = [line for line in lines if line.startswith("[\u672a\u5339\u914d]")]

        self.assertEqual(len([line for line in match_lines if ":" in line]), 50)
        self.assertEqual(len([line for line in unmatched_lines if ":" in line]), 50)
        self.assertIn("[\u5339\u914d] \u53e6\u6709 1 \u9879\u5df2\u7701\u7565", match_lines)
        self.assertIn("[\u672a\u5339\u914d] \u53e6\u6709 1 \u9879\u5df2\u7701\u7565", unmatched_lines)

    def test_format_result_normalizes_negative_preview_limit_to_zero(self):
        result = self.make_result(
            matches=[MatchPreview("match", "source", "target")],
            unmatched=[UnmatchedPreview("unmatched", "source")],
        )

        output = format_result(result, preview_limit=-1)

        self.assertNotIn("match: ", output)
        self.assertNotIn("unmatched: ", output)
        self.assertIn("[\u5339\u914d] \u53e6\u6709 1 \u9879\u5df2\u7701\u7565", output)
        self.assertIn("[\u672a\u5339\u914d] \u53e6\u6709 1 \u9879\u5df2\u7701\u7565", output)

    def test_format_result_lists_each_target_overwritten_by_this_run(self):
        result = self.make_result()
        result.overwritten_paths = (Path("translated.json"), Path("untranslated.json"))

        output = format_result(result)

        self.assertIn("[\u8986\u76d6] \u5df2\u8986\u76d6\u73b0\u6709\u6587\u4ef6: translated.json", output)
        self.assertIn("[\u8986\u76d6] \u5df2\u8986\u76d6\u73b0\u6709\u6587\u4ef6: untranslated.json", output)

    @staticmethod
    def make_result(
        matches: list[MatchPreview] | None = None,
        unmatched: list[UnmatchedPreview] | None = None,
    ) -> ProcessingResult:
        return ProcessingResult(
            input_encoding="utf-8",
            output_encoding="utf-8",
            output_path=Path("translated.json"),
            untranslated_path=Path("untranslated.json"),
            matched_keys=set(),
            replacement_count=0,
            untranslated={},
            matches=matches or [],
            unmatched=unmatched or [],
            warnings=[],
        )
