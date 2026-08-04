import csv
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from translator import (
    TranslationError,
    atomic_write_many,
    atomic_write_text,
    decode_bytes,
    default_output_paths,
    load_translation_dictionary,
    missing_placeholders,
    process_resource,
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

    def test_dictionary_keys_and_values_must_be_utf8_encodable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "dictionary.json")
            for document in ('{"\\ud800":"value"}', '{"key":"\\ud800"}'):
                with self.subTest(document=document):
                    path.write_text(document, encoding="ascii")
                    with self.assertRaisesRegex(TranslationError, "UTF-8"):
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

    def test_json_rejects_duplicate_object_keys(self):
        with self.assertRaisesRegex(TranslationError, "重复键"):
            transform_json('{"title":"first","title":"second"}', {})

    def test_json_rejects_non_finite_numeric_constants(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                with self.assertRaisesRegex(TranslationError, "非有限"):
                    transform_json(f'{{"value":{constant}}}', {})

    def test_json_rejects_decimal_values_that_float_cannot_preserve(self):
        for number in (
            "0.12345678901234567890123456789",
            "1e400",
            "1e9999999999999999999",
        ):
            with self.subTest(number=number):
                with self.assertRaisesRegex(TranslationError, "数值"):
                    transform_json(f'{{"value":{number}}}', {})

    def test_json_preserves_ordinary_finite_numbers_and_translates_strings(self):
        result = transform_json('{"value":1.5,"title":"New Game"}', {"New Game": "新游戏"})

        self.assertEqual(json.loads(result.content), {"value": 1.5, "title": "新游戏"})

    def test_csv_sniffs_semicolon_and_matches_complete_cells(self):
        result = transform_csv("id;text\n1;New Game\n2;Options\n", {"New Game": "新游戏"})
        self.assertIn("1;新游戏", result.content)
        self.assertEqual(result.replacement_count, 1)
        self.assertIn("CSV 第 3 行第 2 列", [item.location for item in result.unmatched])

    def test_csv_limits_sniffing_so_single_column_text_remains_complete_cells(self):
        result = transform_csv("New Game\nLoad Game\n", {"New Game": "新游戏"})

        self.assertEqual(result.content, "新游戏\nLoad Game\n")
        self.assertEqual(result.replacement_count, 1)
        self.assertEqual(result.untranslated, {"Load Game": ""})

    def test_csv_writes_translation_containing_delimiter_and_double_quote_safely(self):
        result = transform_csv(
            "id|text\n1|'New Game'\n",
            {"New Game": '译文|带"引号"'},
        )

        rows = list(csv.reader(result.content.splitlines(), delimiter="|", quotechar='"'))
        self.assertEqual(rows[1], ["1", '译文|带"引号"'])
        self.assertIn('"译文|带""引号"""', result.content)

    def test_csv_wraps_reader_errors_as_translation_errors(self):
        with self.assertRaisesRegex(TranslationError, "CSV.*解析"):
            transform_csv('id,text\n1,"unterminated\n', {})

    def test_csv_wraps_writer_errors_as_translation_errors(self):
        with patch("translator.csv.writer", side_effect=csv.Error("cannot write")):
            with self.assertRaisesRegex(TranslationError, "CSV.*写出"):
                transform_csv("id,text\n1,New Game\n", {})

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

    def test_plaintext_untranslated_keys_preserve_horizontal_whitespace_for_lf_and_crlf(self):
        result = transform_plaintext(
            "  Open New Game  \n\tLoad Game \t\r\n",
            {"New Game": "新游戏"},
        )

        self.assertEqual(result.content, "  Open 新游戏  \n\tLoad Game \t\r\n")
        self.assertEqual(
            result.untranslated,
            {"  Open New Game  ": "", "\tLoad Game \t": ""},
        )

    def test_plaintext_preserves_complete_whitespace_lines(self):
        source = " \t\r\n\nOptions\n"

        result = transform_plaintext(source, {})

        self.assertEqual(result.content, source)
        self.assertEqual(result.untranslated, {"Options": ""})

    def test_halfwidth_katakana_is_an_untranslated_candidate(self):
        result = transform_json('{"label":"ｶﾀｶﾅ"}', {})

        self.assertEqual(result.untranslated, {"ｶﾀｶﾅ": ""})


class ProcessingTests(unittest.TestCase):
    def test_default_paths_and_json_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.json"
            dictionary = root / "dictionary.json"
            resource.write_text('{"title":"New Game","missing":"Options"}', encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")

            result = process_resource(resource, dictionary)

            self.assertEqual(result.output_path, root / "game.zh.json")
            self.assertEqual(result.untranslated_path, root / "game.untranslated.json")
            self.assertEqual(json.loads(result.output_path.read_text(encoding="utf-8"))["title"], "新游戏")
            self.assertEqual(
                json.loads(result.untranslated_path.read_text(encoding="utf-8")),
                {"Options": ""},
            )
            self.assertEqual(default_output_paths(resource), (result.output_path, result.untranslated_path))

    def test_process_resource_rejects_source_as_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")

            with self.assertRaisesRegex(TranslationError, "不能覆盖源文件"):
                process_resource(resource, dictionary, output_path=resource)

    def test_process_resource_rejects_either_output_aliasing_resource_or_dictionary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alias_parent = root / "alias"
            alias_parent.mkdir()
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")
            aliases = {
                "resource": alias_parent / ".." / resource.name,
                "dictionary": alias_parent / ".." / dictionary.name,
            }

            for protected_name, protected_path in aliases.items():
                for role in ("output", "untranslated"):
                    with self.subTest(protected=protected_name, role=role):
                        dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")
                        kwargs = {
                            "output_path": root / "safe.zh.txt",
                            "untranslated_path": root / "safe.untranslated.json",
                        }
                        kwargs[f"{role}_path"] = protected_path
                        with self.assertRaisesRegex(TranslationError, "不能覆盖"):
                            process_resource(resource, dictionary, **kwargs)

    def test_unsupported_extension_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.exe"
            dictionary = root / "dictionary.json"
            resource.write_bytes(b"not a resource")
            dictionary.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(TranslationError, "不支持"):
                process_resource(resource, dictionary)

            self.assertFalse((root / "game.zh.exe").exists())

    def test_process_resource_rejects_colliding_output_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            shared_output = root / "same.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")

            with self.assertRaisesRegex(TranslationError, "输出路径不能相同"):
                process_resource(resource, dictionary, shared_output, shared_output)

    def test_process_resource_invalid_json_does_not_create_either_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.json"
            dictionary = root / "dictionary.json"
            resource.write_text('{"title":"first","title":"second"}', encoding="utf-8")
            dictionary.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(TranslationError, "重复键"):
                process_resource(resource, dictionary)

            output, untranslated = default_output_paths(resource)
            self.assertFalse(output.exists())
            self.assertFalse(untranslated.exists())

    def test_process_resource_wraps_output_resolve_runtime_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            loop = root / "loop"
            cyclic_output = loop / "translated.txt"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")
            os.symlink(loop, loop, target_is_directory=True)

            with self.assertRaisesRegex(TranslationError, "Symlink loop"):
                process_resource(resource, dictionary, output_path=cyclic_output)

    def test_atomic_write_many_wraps_lstat_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "output.txt"

            with patch("translator.os.lstat", side_effect=OSError("metadata unavailable")):
                with self.assertRaisesRegex(TranslationError, "metadata unavailable"):
                    atomic_write_many({target: "content"})

            self.assertFalse(target.exists())

    def test_atomic_write_cleans_temporary_file_when_fsync_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "output.txt")
            target.write_text("old", encoding="utf-8")

            with patch("translator.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(TranslationError, "disk full"):
                    atomic_write_text(target, "new")

            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])

    def test_atomic_write_many_rolls_back_when_second_commit_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            translated = root / "game.zh.txt"
            untranslated = root / "game.untranslated.json"
            translated.write_text("old translated", encoding="utf-8")
            untranslated.write_text("old todo", encoding="utf-8")
            real_replace = os.replace
            replace_calls = 0

            def fail_second_commit(source, destination):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 4:
                    raise OSError("second commit failed")
                return real_replace(source, destination)

            with patch("translator.os.replace", side_effect=fail_second_commit):
                with self.assertRaisesRegex(TranslationError, "second commit failed"):
                    atomic_write_many({translated: "new translated", untranslated: "new todo"})

            self.assertEqual(translated.read_text(encoding="utf-8"), "old translated")
            self.assertEqual(untranslated.read_text(encoding="utf-8"), "old todo")
            self.assertEqual(list(root.glob(".*.tmp")), [])
            self.assertEqual(list(root.glob(".*.bak")), [])

    def test_atomic_write_many_rolls_back_and_reraises_keyboard_interrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            translated = root / "game.zh.txt"
            untranslated = root / "game.untranslated.json"
            translated.write_text("old translated", encoding="utf-8")
            untranslated.write_text("old todo", encoding="utf-8")
            real_replace = os.replace
            replace_calls = 0

            def interrupt_second_commit(source, destination):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 4:
                    raise KeyboardInterrupt()
                return real_replace(source, destination)

            with patch("translator.os.replace", side_effect=interrupt_second_commit):
                with self.assertRaises(KeyboardInterrupt):
                    atomic_write_many({translated: "new translated", untranslated: "new todo"})

            self.assertEqual(translated.read_text(encoding="utf-8"), "old translated")
            self.assertEqual(untranslated.read_text(encoding="utf-8"), "old todo")
            self.assertEqual(list(root.glob(".*.tmp")), [])
            self.assertEqual(list(root.glob(".*.bak")), [])

    def test_process_resource_stops_if_output_directory_identity_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            outputs = root / "outputs"
            displaced_outputs = root / "displaced-outputs"
            inputs.mkdir()
            outputs.mkdir()
            resource = inputs / "game.txt"
            dictionary = inputs / "dictionary.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")
            (outputs / "game.txt").write_text("old output", encoding="utf-8")
            (outputs / "dictionary.json").write_text("old todo", encoding="utf-8")
            real_named_temporary_file = tempfile.NamedTemporaryFile
            temporary_file_calls = 0

            @contextmanager
            def replace_output_directory_after_staging(*args, **kwargs):
                nonlocal temporary_file_calls
                with real_named_temporary_file(*args, **kwargs) as handle:
                    yield handle
                temporary_file_calls += 1
                if temporary_file_calls == 2:
                    outputs.rename(displaced_outputs)
                    inputs.rename(outputs)

            with patch(
                "translator.tempfile.NamedTemporaryFile",
                side_effect=replace_output_directory_after_staging,
            ):
                with self.assertRaisesRegex(TranslationError, "发生变化"):
                    process_resource(
                        resource,
                        dictionary,
                        output_path=outputs / "game.txt",
                        untranslated_path=outputs / "dictionary.json",
                    )

            self.assertEqual((outputs / "game.txt").read_text(encoding="utf-8"), "New Game")
            self.assertEqual(
                (outputs / "dictionary.json").read_text(encoding="utf-8"),
                '{"New Game":"新游戏"}',
            )

    def test_atomic_write_many_wraps_unicode_errors_and_cleans_staged_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("old first", encoding="utf-8")
            second.write_text("old second", encoding="utf-8")

            with self.assertRaisesRegex(TranslationError, "事务方式"):
                atomic_write_many({first: "new first", second: "bad \ud800"})

            self.assertEqual(first.read_text(encoding="utf-8"), "old first")
            self.assertEqual(second.read_text(encoding="utf-8"), "old second")
            self.assertEqual(list(root.glob(".*.tmp")), [])
            self.assertEqual(list(root.glob(".*.bak")), [])

    def test_atomic_write_many_returns_only_targets_actually_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing.txt"
            new = root / "new.txt"
            existing.write_text("old", encoding="utf-8")

            overwritten = atomic_write_many({existing: "updated", new: "created"})

            self.assertEqual(overwritten, (existing,))
            self.assertEqual(existing.read_text(encoding="utf-8"), "updated")
            self.assertEqual(new.read_text(encoding="utf-8"), "created")

    def test_process_resource_reports_mixed_existing_and_new_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            output = root / "game.zh.txt"
            untranslated = root / "game.untranslated.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")
            output.write_text("old", encoding="utf-8")

            result = process_resource(resource, dictionary, output, untranslated)

            self.assertEqual(result.overwritten_paths, (output,))
