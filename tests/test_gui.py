import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import gui
from translator import ProcessingResult, TranslationError


class GuiTests(unittest.TestCase):
    def test_gui_exports_app_entrypoint_and_selected_palette(self):
        self.assertTrue(callable(gui.main))
        self.assertEqual(gui.PALETTE["background"], "#f7f3ec")
        self.assertEqual(gui.PALETTE["primary"], "#c83b2b")
        self.assertEqual(gui.PALETTE["text"], "#242321")

    def test_missing_files_write_the_warning_message_to_the_log(self):
        app = object.__new__(gui.GameTranslatorApp)
        app.resource_path = Mock()
        app.resource_path.get.return_value = ""
        app.dictionary_path = Mock()
        app.dictionary_path.get.return_value = ""
        app._append_log = Mock()
        prompt = (
            "\u8bf7\u5148\u9009\u62e9\u8d44\u6e90\u6587\u4ef6"
            "\u5e76\u52a0\u8f7d\u7ffb\u8bd1\u5b57\u5178\u3002"
        )

        with patch.object(gui.messagebox, "showwarning") as showwarning:
            app.run_translation()

        app._append_log.assert_called_once_with(prompt)
        showwarning.assert_called_once_with("\u7f3a\u5c11\u6587\u4ef6", prompt)

    def test_success_delegates_to_core_and_logs_summary_with_overwrite_notice(self):
        app = self.make_app("game.txt", "dictionary.json")
        result = self.make_result()
        result.overwritten_paths = (result.output_path,)

        with (
            patch.object(gui, "process_resource", return_value=result) as process,
            patch.object(gui.messagebox, "showinfo") as showinfo,
        ):
            app.run_translation()

        process.assert_called_once_with("game.txt", "dictionary.json")
        self.assertEqual(app._append_log.call_args_list[0].args[0], "\u5f00\u59cb\u6c49\u5316\u5904\u7406\u2026")
        self.assertIn("[\u8986\u76d6]", app._append_log.call_args_list[1].args[0])
        showinfo.assert_called_once_with(
            "\u6c49\u5316\u5b8c\u6210",
            f"\u6c49\u5316\u6587\u4ef6\u5df2\u8f93\u51fa\u5230\uff1a\n{result.output_path}",
        )

    def test_failure_delegates_to_core_and_logs_and_shows_error(self):
        app = self.make_app("game.txt", "dictionary.json")

        with (
            patch.object(gui, "process_resource", side_effect=TranslationError("bad data")) as process,
            patch.object(gui.messagebox, "showerror") as showerror,
        ):
            app.run_translation()

        process.assert_called_once_with("game.txt", "dictionary.json")
        self.assertEqual(
            [call.args[0] for call in app._append_log.call_args_list],
            ["\u5f00\u59cb\u6c49\u5316\u5904\u7406\u2026", "\u9519\u8bef: bad data"],
        )
        showerror.assert_called_once_with("\u6c49\u5316\u5931\u8d25", "bad data")

    def test_path_resolution_failure_uses_the_translation_error_dialog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            loop = root / "loop"
            resource.write_text("New Game", encoding="utf-8")
            os.symlink(loop, loop, target_is_directory=True)
            app = self.make_app(str(resource), str(loop))

            with patch.object(gui.messagebox, "showerror") as showerror:
                app.run_translation()

        error_message = app._append_log.call_args_list[-1].args[0]
        self.assertIn("Symlink loop", error_message)
        showerror.assert_called_once()
        self.assertEqual(showerror.call_args.args[0], "汉化失败")
        self.assertIn("Symlink loop", showerror.call_args.args[1])

    @staticmethod
    def make_app(resource: str, dictionary: str):
        app = object.__new__(gui.GameTranslatorApp)
        app.resource_path = Mock()
        app.resource_path.get.return_value = resource
        app.dictionary_path = Mock()
        app.dictionary_path.get.return_value = dictionary
        app._append_log = Mock()
        return app

    @staticmethod
    def make_result() -> ProcessingResult:
        return ProcessingResult(
            input_encoding="utf-8",
            output_encoding="utf-8",
            output_path=Path("translated.txt"),
            untranslated_path=Path("untranslated.json"),
            matched_keys=set(),
            replacement_count=0,
            untranslated={},
            matches=[],
            unmatched=[],
            warnings=[],
        )
