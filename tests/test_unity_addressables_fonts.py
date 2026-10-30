from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from game_localizer.adapters import unity_addressables as module
from game_localizer.adapters.unity_addressables import (
    _AddressablesLayout,
    _FontRecord,
    _catalog_crc_references,
    _repair_project_fonts,
)


class _Context:
    def checkpoint(self) -> None:
        return None


def make_layout(platform: Path) -> _AddressablesLayout:
    return _AddressablesLayout(
        root=platform.parent,
        english_bundle=platform / "localization-string-tables-english(en)_assets_all.bundle",
        chinese_bundle=platform / "localization-string-tables-chinese(simplified)(zh-cn)_assets_all.bundle",
        catalog=platform.parent / "catalog.bin",
    )


class CatalogReferenceTests(unittest.TestCase):
    def test_counts_matching_crc_only(self):
        catalog = Path(__file__).with_name("test_unity_fonts.py")
        data = b"\x01\x02\x03\x04" + b"junk" + b"\x01\x02\x03\x04"
        with patch.object(module, "_bundle_crc", return_value=0x04030201):
            self.assertEqual(_catalog_crc_references(data, catalog), 2)

    def test_zero_references_are_reported(self):
        catalog = Path(__file__).with_name("test_unity_fonts.py")
        with patch.object(module, "_bundle_crc", return_value=0xDEADBEEF):
            self.assertEqual(_catalog_crc_references(b"nothing here", catalog), 0)


class FontRepairPlanningTests(unittest.TestCase):
    """The planning step decides which bundles to rewrite and with which donor."""

    def setUp(self):
        self.root = Path("D:/fake/game")
        self.platform = self.root / "Game_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64"
        self.layout = make_layout(self.platform)
        self.missing = frozenset({ord("你")})
        self.present = frozenset({ord("A")})

    def _run(self, inventory, *, translations=None, donors=()):
        with (
            patch.object(module, "_font_inventory", return_value=inventory),
            patch.object(module, "_font_payload", return_value=None),
            patch.object(module, "font_codepoints", return_value=self.present | self.missing),
            patch.object(module, "_repair_fonts", return_value=1) as repair,
        ):
            result = _repair_project_fonts(
                self.layout,
                translations if translations is not None else {("t", 1): "你"},
                donors,
                _Context(),
            )
        return result, repair

    def test_no_fonts_means_no_work(self):
        (bundles, statistics, warnings), repair = self._run(())
        self.assertEqual(bundles, ())
        self.assertEqual(statistics, {"fonts_repaired": 0, "font_bundles": 0})
        self.assertEqual(warnings, ())
        repair.assert_not_called()

    def test_complete_coverage_is_left_byte_identical(self):
        record = _FontRecord(self.platform / "fonts.bundle", "Noto", self.present | self.missing)
        (bundles, statistics, warnings), repair = self._run((record,))
        self.assertEqual(bundles, ())
        self.assertEqual(statistics["fonts_repaired"], 0)
        self.assertEqual(warnings, ())
        repair.assert_not_called()

    def test_empty_translations_skip_repair(self):
        record = _FontRecord(self.platform / "fonts.bundle", "Underdog", self.present)
        (bundles, _statistics, warnings), repair = self._run((record,), translations={("t", 1): ""})
        self.assertEqual(bundles, ())
        self.assertEqual(warnings, ())
        repair.assert_not_called()

    def test_missing_glyphs_without_a_donor_warns_instead_of_failing(self):
        record = _FontRecord(self.platform / "fonts.bundle", "Underdog", self.present)
        (bundles, statistics, warnings), repair = self._run((record,))
        self.assertEqual(bundles, ())
        self.assertEqual(statistics["fonts_repaired"], 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Underdog is missing 1 glyph", warnings[0])
        self.assertIn("--font", warnings[0])
        repair.assert_not_called()

    def test_configured_donor_repairs_the_bundles_that_need_it(self):
        weak = _FontRecord(self.platform / "weak.bundle", "Underdog", self.present)
        strong = _FontRecord(self.platform / "strong.bundle", "Noto", self.present | self.missing)
        donor = Path("D:/fonts/NotoSansSC.otf")
        with patch.object(Path, "read_bytes", return_value=b"donor-bytes"):
            (bundles, statistics, warnings), repair = self._run((weak, strong), donors=(donor,))
        self.assertEqual(bundles, (self.platform / "weak.bundle",))
        self.assertEqual(statistics, {"fonts_repaired": 1, "font_bundles": 1})
        self.assertEqual(warnings, ())
        repair.assert_called_once()
        self.assertEqual(repair.call_args.args[0], self.platform / "weak.bundle")
        self.assertEqual(repair.call_args.kwargs["donor"], b"donor-bytes")

    def test_shipped_cjk_font_is_reused_as_a_donor(self):
        weak = _FontRecord(self.platform / "weak.bundle", "Underdog", self.present)
        strong = _FontRecord(self.platform / "strong.bundle", "Noto", self.present | self.missing)
        with (
            patch.object(module, "_font_inventory", return_value=(weak, strong)),
            patch.object(module, "_font_payload", return_value=b"shipped-cjk") as payload,
            patch.object(module, "font_codepoints", return_value=self.present | self.missing),
            patch.object(module, "_repair_fonts", return_value=1) as repair,
        ):
            bundles, statistics, warnings = _repair_project_fonts(
                self.layout,
                {("t", 1): "你"},
                (),
                _Context(),
            )
        self.assertEqual(bundles, (self.platform / "weak.bundle",))
        self.assertEqual(statistics["fonts_repaired"], 1)
        self.assertEqual(warnings, ())
        payload.assert_called_once_with(strong.bundle, "Noto")
        self.assertEqual(repair.call_args.kwargs["donor"], b"shipped-cjk")

    def test_each_broken_bundle_is_repaired_once(self):
        first = _FontRecord(self.platform / "a.bundle", "One", self.present)
        second = _FontRecord(self.platform / "a.bundle", "Two", self.present)
        third = _FontRecord(self.platform / "b.bundle", "Three", self.present)
        with patch.object(Path, "read_bytes", return_value=b"donor-bytes"):
            (bundles, statistics, _warnings), repair = self._run(
                (first, second, third), donors=(Path("D:/fonts/donor.ttf"),)
            )
        self.assertEqual(bundles, (self.platform / "a.bundle", self.platform / "b.bundle"))
        self.assertEqual(statistics["font_bundles"], 2)
        self.assertEqual(statistics["fonts_repaired"], 2)
        self.assertEqual(repair.call_count, 2)


if __name__ == "__main__":
    unittest.main()
