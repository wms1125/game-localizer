from __future__ import annotations

import hashlib
import json
import math
import unittest
from dataclasses import replace

from game_localizer.hanengine.segments import (
    ScreenRegion,
    Segment,
    SegmentDraft,
    SourceLocation,
    normalize_relative_path,
)


class RelativePathTests(unittest.TestCase):
    def test_normalizes_posix_and_backslash_relative_paths(self):
        self.assertEqual(normalize_relative_path("game/scripts/script.rpy"), "game/scripts/script.rpy")
        self.assertEqual(normalize_relative_path("game\\scripts\\script.rpy"), "game/scripts/script.rpy")
        self.assertEqual(normalize_relative_path("game/./script.rpy"), "game/script.rpy")

    def test_rejects_paths_that_are_not_safe_relative_paths_on_any_host(self):
        invalid_paths = (
            "",
            "/game/script.rpy",
            "C:/game/script.rpy",
            "C:\\game\\script.rpy",
            "C:game\\script.rpy",
            "\\game\\script.rpy",
            "\\\\server\\share\\script.rpy",
            "\\\\?\\C:\\game\\script.rpy",
            "\\\\.\\C:\\game\\script.rpy",
            "../script.rpy",
            "..\\script.rpy",
            "safe/..\\script.rpy",
        )
        for value in invalid_paths:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_relative_path(value)

    def test_rejects_mixed_separators_even_without_traversal(self):
        with self.assertRaisesRegex(ValueError, "mixed path separators"):
            normalize_relative_path("game\\scripts/file.rpy")

    def test_rejects_non_string_paths(self):
        with self.assertRaises(TypeError):
            normalize_relative_path(1)  # type: ignore[arg-type]


class LocationModelTests(unittest.TestCase):
    def test_screen_region_round_trips(self):
        region = ScreenRegion(x=1, y=2, width=320, height=180)
        self.assertEqual(region.to_dict(), {"x": 1, "y": 2, "width": 320, "height": 180})
        self.assertEqual(ScreenRegion.from_dict(region.to_dict()), region)

    def test_screen_region_requires_real_integers(self):
        for field_name, value in (("x", True), ("y", 1.5), ("width", False), ("height", "2")):
            payload = {"x": 0, "y": 0, "width": 10, "height": 10, field_name: value}
            with self.subTest(field=field_name), self.assertRaises(TypeError):
                ScreenRegion(**payload)

    def test_screen_region_rejects_invalid_coordinates_and_dimensions(self):
        for payload in (
            {"x": -1, "y": 0, "width": 10, "height": 10},
            {"x": 0, "y": -1, "width": 10, "height": 10},
            {"x": 0, "y": 0, "width": 0, "height": 10},
            {"x": 0, "y": 0, "width": 10, "height": -1},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ScreenRegion(**payload)

    def test_source_location_requires_a_real_locator(self):
        with self.assertRaisesRegex(ValueError, "locator"):
            SourceLocation()

    def test_source_location_normalizes_and_round_trips_nullable_fields(self):
        location = SourceLocation(
            relative_path="game\\script.rpy",
            logical_path="label:start",
            line=12,
            column=3,
            byte_offset=42,
            screen_region=ScreenRegion(4, 5, 640, 120),
        )
        expected = {
            "relative_path": "game/script.rpy",
            "logical_path": "label:start",
            "line": 12,
            "column": 3,
            "byte_offset": 42,
            "screen_region": {"x": 4, "y": 5, "width": 640, "height": 120},
        }
        self.assertEqual(location.to_dict(), expected)
        self.assertEqual(SourceLocation.from_dict(expected), location)

        minimal = SourceLocation(relative_path="game/script.rpy")
        self.assertEqual(
            minimal.to_dict(),
            {
                "relative_path": "game/script.rpy",
                "logical_path": None,
                "line": None,
                "column": None,
                "byte_offset": None,
                "screen_region": None,
            },
        )
        self.assertEqual(SourceLocation.from_dict(minimal.to_dict()), minimal)

    def test_source_location_validates_numeric_locators(self):
        for field_name, value in (
            ("line", 0),
            ("line", True),
            ("column", 0),
            ("column", False),
            ("byte_offset", -1),
            ("byte_offset", True),
        ):
            with self.subTest(field=field_name, value=value), self.assertRaises((TypeError, ValueError)):
                SourceLocation(logical_path="entry", **{field_name: value})

    def test_source_location_from_dict_rejects_wrong_shape_and_nested_type(self):
        payload = SourceLocation(relative_path="game/script.rpy").to_dict()
        with self.assertRaises(ValueError):
            SourceLocation.from_dict({**payload, "extra": "value"})
        with self.assertRaises(TypeError):
            SourceLocation.from_dict({**payload, "screen_region": "not-a-region"})


class SegmentModelTests(unittest.TestCase):
    def make_draft(self, **changes: object) -> SegmentDraft:
        values: dict[str, object] = {
            "segment_id": "script.rpy:line:12",
            "source_text": "Start Game",
            "source_language": "en",
            "speaker": None,
            "context_before": ("Main Menu",),
            "context_after": ("Load Game",),
            "placeholders": ("{player}",),
            "tags": ("menu",),
            "constraints": ("single-line",),
            "source_location": SourceLocation(relative_path="game/script.rpy", line=12),
            "source_fingerprint": "sha256:source",
            "ocr_confidence": None,
            "region_confidence": None,
            "metadata": {"engine": "renpy", "nested": {"pages": [1, 2]}},
        }
        values.update(changes)
        return SegmentDraft(**values)

    def test_draft_copies_sequences_and_nested_metadata(self):
        before = ["Main Menu"]
        pages = [1, 2]
        metadata = {"engine": "renpy", "nested": {"pages": pages}}
        draft = self.make_draft(context_before=before, metadata=metadata)

        before.append("mutated")
        pages.append(3)
        metadata["engine"] = "other"

        self.assertEqual(draft.context_before, ("Main Menu",))
        self.assertEqual(draft.metadata, {"engine": "renpy", "nested": {"pages": [1, 2]}})

    def test_draft_rejects_invalid_confidence_types_and_ranges(self):
        invalid_values = (True, False, -0.01, 1.01, math.nan, math.inf, "0.5")
        for field_name in ("ocr_confidence", "region_confidence"):
            for value in invalid_values:
                with self.subTest(field=field_name, value=value), self.assertRaises((TypeError, ValueError)):
                    self.make_draft(**{field_name: value})

    def test_draft_rejects_non_json_metadata(self):
        for metadata in ({"bad": object()}, {"bad": math.nan}, {1: "non-string key"}):
            with self.subTest(metadata=metadata), self.assertRaisesRegex((TypeError, ValueError), "JSON"):
                self.make_draft(metadata=metadata)

    def test_draft_rejects_invalid_string_sequences(self):
        for field_name in (
            "context_before",
            "context_after",
            "placeholders",
            "tags",
            "constraints",
        ):
            with self.subTest(field=field_name), self.assertRaises(TypeError):
                self.make_draft(**{field_name: ("valid", 2)})

    def test_draft_to_dict_and_from_dict_are_exact_and_isolated(self):
        draft = self.make_draft()
        payload = draft.to_dict()
        self.assertEqual(
            tuple(payload),
            (
                "segment_id",
                "source_text",
                "source_language",
                "speaker",
                "context_before",
                "context_after",
                "placeholders",
                "tags",
                "constraints",
                "source_location",
                "source_fingerprint",
                "ocr_confidence",
                "region_confidence",
                "metadata",
            ),
        )
        self.assertIsInstance(payload["context_before"], list)
        self.assertEqual(SegmentDraft.from_dict(payload), draft)
        self.assertEqual(json.loads(json.dumps(payload, allow_nan=False)), payload)

        payload["metadata"]["nested"]["pages"].append(99)
        self.assertEqual(draft.metadata["nested"]["pages"], [1, 2])

    def test_draft_from_dict_rejects_unknown_or_malformed_values(self):
        payload = self.make_draft().to_dict()
        with self.assertRaises(ValueError):
            SegmentDraft.from_dict({**payload, "extra": None})
        with self.assertRaises(TypeError):
            SegmentDraft.from_dict({**payload, "source_location": "bad"})

    def test_from_draft_uses_exact_canonical_seven_field_fingerprint(self):
        draft = self.make_draft()
        segment = Segment.from_draft("project-a", "zh-Hans", draft)
        fingerprint_payload = {
            "project_id": "project-a",
            "target_language": "zh-Hans",
            "speaker": None,
            "context_before": ["Main Menu"],
            "context_after": ["Load Game"],
            "constraints": ["single-line"],
            "source_location": draft.source_location.to_dict(),
        }
        canonical = json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(segment.context_fingerprint, hashlib.sha256(canonical).hexdigest())
        self.assertIsNone(segment.target_text)
        self.assertIsNone(segment.translation_source)

    def test_fingerprint_is_project_language_context_and_location_scoped(self):
        draft = self.make_draft()
        original = Segment.from_draft("project-a", "zh-Hans", draft)
        equivalent = Segment.from_draft("project-a", "zh-Hans", draft)
        self.assertEqual(original.context_fingerprint, equivalent.context_fingerprint)

        variants = (
            Segment.from_draft("project-b", "zh-Hans", draft),
            Segment.from_draft("project-a", "zh-Hant", draft),
            Segment.from_draft("project-a", "zh-Hans", self.make_draft(speaker="Narrator")),
            Segment.from_draft("project-a", "zh-Hans", self.make_draft(context_before=("Options",))),
            Segment.from_draft("project-a", "zh-Hans", self.make_draft(context_after=("Quit",))),
            Segment.from_draft("project-a", "zh-Hans", self.make_draft(constraints=("multiline",))),
            Segment.from_draft(
                "project-a",
                "zh-Hans",
                self.make_draft(source_location=SourceLocation(relative_path="game/other.rpy", line=12)),
            ),
        )
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertNotEqual(original.context_fingerprint, variant.context_fingerprint)

    def test_fingerprint_excludes_fields_outside_the_seven_field_contract(self):
        original = Segment.from_draft("project-a", "zh-Hans", self.make_draft())
        changed = Segment.from_draft(
            "project-a",
            "zh-Hans",
            self.make_draft(
                segment_id="other-id",
                source_text="Changed text",
                source_language="ja",
                placeholders=("%s",),
                tags=("dialogue",),
                source_fingerprint="sha256:different",
                metadata={"engine": "other"},
            ),
        )
        self.assertEqual(original.context_fingerprint, changed.context_fingerprint)

    def test_segment_round_trips_translated_fields_and_does_not_leak_metadata(self):
        base = Segment.from_draft("project-a", "zh-Hans", self.make_draft())
        translated = replace(base, target_text="开始游戏", translation_source="local-dictionary")
        payload = translated.to_dict()

        self.assertEqual(Segment.from_dict(payload), translated)
        self.assertEqual(json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False)), payload)
        payload["metadata"]["nested"]["pages"].append(99)
        self.assertEqual(translated.metadata["nested"]["pages"], [1, 2])

    def test_segment_constructor_copies_mutable_input(self):
        draft = self.make_draft()
        base = Segment.from_draft("project-a", "zh-Hans", draft)
        metadata = {"items": ["one"]}
        segment = replace(base, context_before=["before"], metadata=metadata)
        metadata["items"].append("two")
        self.assertEqual(segment.context_before, ("before",))
        self.assertEqual(segment.metadata, {"items": ["one"]})

    def test_segment_from_dict_revalidates_confidence_and_metadata(self):
        payload = Segment.from_draft("project-a", "zh-Hans", self.make_draft()).to_dict()
        with self.assertRaises((TypeError, ValueError)):
            Segment.from_dict({**payload, "ocr_confidence": True})
        with self.assertRaisesRegex((TypeError, ValueError), "JSON"):
            Segment.from_dict({**payload, "metadata": {"bad": math.nan}})


class PublicExportsTests(unittest.TestCase):
    def test_hanengine_keeps_task_two_public_symbols(self):
        import game_localizer.hanengine as hanengine

        expected = {
            "ScreenRegion": ScreenRegion,
            "Segment": Segment,
            "SegmentDraft": SegmentDraft,
            "SourceLocation": SourceLocation,
            "normalize_relative_path": normalize_relative_path,
        }
        for name, exported in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, hanengine.__all__)
                self.assertIs(getattr(hanengine, name), exported)


if __name__ == "__main__":
    unittest.main()
