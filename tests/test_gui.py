import unittest
from unittest.mock import Mock, patch

import gui


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
