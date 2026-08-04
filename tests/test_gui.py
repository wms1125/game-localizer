import unittest

import gui


class GuiTests(unittest.TestCase):
    def test_gui_exports_app_entrypoint_and_selected_palette(self):
        self.assertTrue(callable(gui.main))
        self.assertEqual(gui.PALETTE["background"], "#f7f3ec")
        self.assertEqual(gui.PALETTE["primary"], "#c83b2b")
        self.assertEqual(gui.PALETTE["text"], "#242321")
