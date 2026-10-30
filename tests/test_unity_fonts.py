from __future__ import annotations

import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from game_localizer.hanengine import unity_fonts
from game_localizer.hanengine.unity_fonts import (
    FontCoverage,
    UnityFontError,
    coverage,
    font_codepoints,
    merge_fonts,
    repair_font,
    required_codepoints,
    subset_font,
)

try:  # fontTools is an optional dependency, exactly like UnityPy
    import fontTools  # noqa: F401

    HAVE_FONTTOOLS = True
except ImportError:  # pragma: no cover - depends on the local runtime
    HAVE_FONTTOOLS = False


def build_font(characters: dict[str, int], *, family: str = "Test") -> bytes:
    """Build a minimal static TTF whose cmap covers ``characters``.

    The mapping is character -> advance width, so tests can assert that a merge
    keeps the shipped face's metrics for glyphs it already had.
    """

    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    units_per_em = 1000
    names = {character: f"uni{ord(character):04X}" for character in characters}
    order = [".notdef", *names.values()]
    builder = FontBuilder(units_per_em, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({ord(character): name for character, name in names.items()})
    glyphs = {}
    metrics = {".notdef": (units_per_em // 2, 0)}
    for character, advance in characters.items():
        pen = TTGlyphPen(None)
        pen.moveTo((50, 0))
        pen.lineTo((50, 500))
        pen.lineTo((400, 500))
        pen.lineTo((400, 0))
        pen.closePath()
        glyphs[names[character]] = pen.glyph()
        metrics[names[character]] = (advance, 50)
    empty = TTGlyphPen(None).glyph()
    builder.setupGlyf({".notdef": empty, **glyphs})
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable(
        {
            "familyName": family,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"{family} Regular 1.0",
            "fullName": f"{family} Regular",
            "psName": f"{family}-Regular",
        }
    )
    builder.setupOS2()
    builder.setupPost()
    buffer = io.BytesIO()
    builder.save(buffer)
    return buffer.getvalue()


class RequiredCodepointsTests(unittest.TestCase):
    def test_ignores_whitespace_and_controls(self):
        self.assertEqual(required_codepoints(["a b\n\tc\x00"]), {ord("a"), ord("b"), ord("c")})

    def test_unions_every_text(self):
        self.assertEqual(required_codepoints(["ab", "bc", ""]), {ord("a"), ord("b"), ord("c")})

    def test_empty_input_yields_nothing(self):
        self.assertEqual(required_codepoints([]), frozenset())


@unittest.skipUnless(HAVE_FONTTOOLS, "fontTools is not installed")
class FontCodepointsTests(unittest.TestCase):
    def test_reads_cmap_of_a_real_font(self):
        data = build_font({"A": 600, "B": 620})
        self.assertEqual(font_codepoints(data), {ord("A"), ord("B")})

    def test_empty_data_is_empty_coverage_not_an_error(self):
        self.assertEqual(font_codepoints(b""), frozenset())

    def test_rejects_garbage(self):
        with self.assertRaises(UnityFontError) as caught:
            font_codepoints(b"not a font at all")
        self.assertIn("not a readable TTF/OTF file", str(caught.exception))

    def test_rejects_non_bytes(self):
        with self.assertRaises(TypeError):
            font_codepoints("A")

    def test_coverage_reports_the_missing_glyphs(self):
        data = build_font({"A": 600})
        report = coverage("Underdog", data, frozenset({ord("A"), ord("你")}))
        self.assertIsInstance(report, FontCoverage)
        self.assertEqual(report.missing, {ord("你")})
        self.assertFalse(report.complete)


@unittest.skipUnless(HAVE_FONTTOOLS, "fontTools is not installed")
class SubsetAndMergeTests(unittest.TestCase):
    def test_subset_keeps_requested_characters_only(self):
        donor = build_font({"A": 500, "你": 900, "好": 900}, family="Donor")
        subset = subset_font(donor, {ord("你")})
        self.assertIn(ord("你"), font_codepoints(subset))
        self.assertNotIn(ord("A"), font_codepoints(subset))
        self.assertLess(len(subset), len(donor))

    def test_subset_of_nothing_is_empty(self):
        self.assertEqual(subset_font(build_font({"A": 500}), set()), b"")

    def test_merge_keeps_the_base_advance_for_shared_glyphs(self):
        base = build_font({"A": 600}, family="Base")
        addition = build_font({"A": 400, "你": 900}, family="Addition")
        merged = merge_fonts(base, addition)
        self.assertEqual(font_codepoints(merged), {ord("A"), ord("你")})
        from fontTools.ttLib import TTFont

        font = TTFont(io.BytesIO(merged))
        try:
            glyph_name = font.getBestCmap()[ord("A")]
            self.assertEqual(font["hmtx"][glyph_name][0], 600)
        finally:
            font.close()

    def test_merge_without_addition_is_a_passthrough(self):
        base = build_font({"A": 600})
        self.assertEqual(merge_fonts(base, b""), base)

    def test_merge_rejects_empty_base(self):
        with self.assertRaises(UnityFontError) as caught:
            merge_fonts(b"", build_font({"A": 600}))
        self.assertIn("base font data is empty", str(caught.exception))

    def test_merge_rejects_garbage(self):
        with self.assertRaises(UnityFontError) as caught:
            merge_fonts(build_font({"A": 600}), b"nonsense")
        self.assertIn("font merge failed", str(caught.exception))

    def test_merge_retries_after_flattening_an_unmergeable_base(self):
        base = build_font({"A": 600}, family="Base")
        addition = build_font({"你": 900}, family="Addition")
        good = merge_fonts(base, addition)
        calls = []

        def fake_merge_once(merger, one, two):
            calls.append(one)
            if len(calls) == 1:
                raise AttributeError("type object 'VarStore' has no attribute 'mergeMap'")
            return good

        with patch.object(unity_fonts, "_merge_once", side_effect=fake_merge_once):
            merged = merge_fonts(base, addition)
        self.assertEqual(merged, good)
        self.assertEqual(len(calls), 2)

    def test_merge_failure_after_flattening_is_still_an_error(self):
        base = build_font({"A": 600})
        with patch.object(unity_fonts, "_merge_once", side_effect=TypeError("boom")):
            with self.assertRaises(UnityFontError) as caught:
                merge_fonts(base, build_font({"你": 900}))
        self.assertIn("font merge failed", str(caught.exception))


class FlattenFontTests(unittest.TestCase):
    def test_drops_variation_and_layout_tables(self):
        from fontTools.ttLib import TTFont
        from fontTools.ttLib.tables.DefaultTable import DefaultTable

        font = TTFont(io.BytesIO(build_font({"A": 600})))
        try:
            for tag in ("BASE", "GDEF", "GSUB", "fvar"):
                table = DefaultTable(tag)
                table.data = b"\x00\x01\x00\x00"
                font[tag] = table
            buffer = io.BytesIO()
            font.save(buffer)
        finally:
            font.close()
        flattened = unity_fonts._flatten_font(buffer.getvalue())
        self.assertIsNotNone(flattened)
        font = TTFont(io.BytesIO(flattened))
        try:
            for tag in ("BASE", "GDEF", "GSUB", "fvar"):
                self.assertNotIn(tag, font)
            self.assertIn("glyf", font)
        finally:
            font.close()

    def test_garbage_is_not_repairable(self):
        self.assertIsNone(unity_fonts._flatten_font(b"nonsense"))


@unittest.skipUnless(HAVE_FONTTOOLS, "fontTools is not installed")
class RepairFontTests(unittest.TestCase):
    def test_complete_coverage_returns_the_shipped_bytes_untouched(self):
        shipped = build_font({"A": 600})
        self.assertEqual(repair_font(shipped, build_font({"你": 900}), required=frozenset({ord("A")})), shipped)

    def test_missing_glyphs_are_added_from_the_donor(self):
        shipped = build_font({"A": 600}, family="Shipped")
        donor = build_font({"你": 900, "好": 900}, family="Donor")
        repaired = repair_font(shipped, donor, required=frozenset({ord("A"), ord("你")}))
        self.assertEqual(font_codepoints(repaired), {ord("A"), ord("你")})
        from fontTools.ttLib import TTFont

        font = TTFont(io.BytesIO(repaired))
        try:
            cmap = font.getBestCmap()
            self.assertEqual(font["hmtx"][cmap[ord("A")]][0], 600)
            self.assertEqual(font["hmtx"][cmap[ord("你")]][0], 900)
        finally:
            font.close()

    def test_donor_that_still_lacks_glyphs_is_an_error(self):
        shipped = build_font({"A": 600})
        donor = build_font({"好": 900})
        with self.assertRaises(UnityFontError) as caught:
            repair_font(shipped, donor, required=frozenset({ord("A"), ord("你")}))
        self.assertIn("does not cover", str(caught.exception))
        self.assertIn("U+4F60", str(caught.exception))


class FontToolsUnavailableTests(unittest.TestCase):
    def test_missing_fonttools_names_the_dependency(self):
        original = sys.modules.get("fontTools.ttLib")
        sys.modules["fontTools.ttLib"] = None  # type: ignore[assignment]
        try:
            with self.assertRaises(UnityFontError) as caught:
                unity_fonts.font_codepoints(b"\x00\x01\x02\x03")
        finally:
            if original is None:
                del sys.modules["fontTools.ttLib"]
            else:
                sys.modules["fontTools.ttLib"] = original
        self.assertIn("fontTools is required", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
