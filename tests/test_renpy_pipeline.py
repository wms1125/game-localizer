import json
import tempfile
import unittest
from pathlib import Path

from game_localizer.hanengine.renpy import (
    RenPyCatalog,
    RenPyExtractor,
    RenPyValidationError,
    RenPyWriter,
    renpy_language_identifier,
    validate_renpy_language_activation_text,
    validate_renpy_translation_text,
)


SCRIPT = '''# comments are not translatable
define narrator = Character("Narrator")
label start:
    e "Hello, [name]! {b}Welcome{/b}."
    scene bg room
    menu:
        "Start game":
            jump begin
    $ python_value = "do not extract"
    "A narration line."
    play music "audio/theme.ogg"
'''


SCREEN_SCRIPT = '''screen sample:
    style_prefix "sample"
    variant "small"
    text "Screen title"
    text "Screen title" style "caption"
    text who id "who"
    add "gui/frame.png"
'''

WRAPPED_SCREEN_SCRIPT = '''screen wrapped:
    text _("Wrapped title") style "caption"
    textbutton _("Begin") action Start()
    label _("Screen label")
'''


class RenPyPipelineTests(unittest.TestCase):
    def make_project(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        (root / "game").mkdir()
        (root / "game" / "script.rpy").write_text(SCRIPT, encoding="utf-8")
        return directory, root

    def test_extracts_dialogue_menu_and_narration_but_skips_code_and_assets(self):
        temporary, root = self.make_project()
        self.addCleanup(temporary.cleanup)
        catalog = RenPyExtractor().extract(root, language="zh_cn")
        texts = {entry.source_text for entry in catalog.entries}
        self.assertEqual(
            texts,
            {"Hello, [name]! {b}Welcome{/b}.", "Start game", "A narration line."},
        )
        self.assertEqual(len(catalog.entries), 3)
        self.assertTrue(all(entry.source_hash for entry in catalog.entries))
        self.assertEqual(
            [entry.segment_id for entry in catalog.entries],
            [entry.segment_id for entry in RenPyExtractor().extract(root).entries],
        )

    def test_catalog_json_is_canonical_and_translation_preserves_placeholders(self):
        temporary, root = self.make_project()
        self.addCleanup(temporary.cleanup)
        catalog = RenPyExtractor().extract(root, language="zh_cn")
        translated = catalog.translate(
            {
                "Hello, [name]! {b}Welcome{/b}.": "你好，[name]！{b}欢迎{/b}。",
                "Start game": "开始游戏",
                "A narration line.": "一行旁白。",
            }
        )
        payload = translated.to_dict()
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(RenPyCatalog.from_dict(json.loads(encoded)), translated)
        with self.assertRaisesRegex(RenPyValidationError, "placeholder"):
            catalog.translate({"Hello, [name]! {b}Welcome{/b}.": "你好！"})

    def test_screen_properties_are_not_treated_as_duplicate_dialogue(self):
        temporary, root = self.make_project()
        self.addCleanup(temporary.cleanup)
        (root / "game" / "screen.rpy").write_text(SCREEN_SCRIPT, encoding="utf-8")

        catalog = RenPyExtractor().extract(root, language="zh_cn")

        self.assertCountEqual(
            [entry.source_text for entry in catalog.entries],
            [
                "Hello, [name]! {b}Welcome{/b}.",
                "Start game",
                "A narration line.",
                "Screen title",
                "Screen title",
            ],
        )
        self.assertEqual(len(catalog.entries), 5)
        self.assertEqual(len({entry.segment_id for entry in catalog.entries}), 5)

    def test_wrapped_screen_text_is_extracted_as_strings(self):
        temporary, root = self.make_project()
        self.addCleanup(temporary.cleanup)
        (root / "game" / "screen.rpy").write_text(
            WRAPPED_SCREEN_SCRIPT,
            encoding="utf-8",
        )
        (root / "game" / "wrapped-dialogue.rpy").write_text(
            'label wrapped:\n    e _("Wrapped dialogue")\n',
            encoding="utf-8",
        )

        catalog = RenPyExtractor().extract(root, language="zh_cn")
        screen_entries = [
            entry for entry in catalog.entries if entry.relative_path == "game/screen.rpy"
        ]

        self.assertEqual(
            [entry.source_text for entry in screen_entries],
            ["Wrapped title", "Begin", "Screen label"],
        )
        self.assertTrue(all(entry.kind == "narration" for entry in screen_entries))
        dialogue = next(
            entry for entry in catalog.entries if entry.source_text == "Wrapped dialogue"
        )
        self.assertEqual((dialogue.kind, dialogue.speaker), ("dialogue", "e"))
        translated = catalog.translate(
            {
                "Wrapped title": "包装标题",
                "Begin": "开始",
                "Screen label": "屏幕标签",
            }
        )
        result = RenPyWriter().build(
            translated,
            root / "localized-output",
            source_root=root,
        )
        rendered = result.path.read_text(encoding="utf-8")
        self.assertIn("translate zh_cn strings:", rendered)
        self.assertIn('old "Wrapped title"', rendered)
        self.assertNotIn("hanengine_renpy", rendered)

    def test_writer_generates_tl_output_without_modifying_source(self):
        temporary, root = self.make_project()
        self.addCleanup(temporary.cleanup)
        source_before = (root / "game" / "script.rpy").read_bytes()
        catalog = RenPyExtractor().extract(root, language="zh_cn").translate(
            {"Hello, [name]! {b}Welcome{/b}.": "你好，[name]！{b}欢迎{/b}。", "Start game": "开始游戏", "A narration line.": "一行旁白。"}
        )
        output = root / "localized-output"
        result = RenPyWriter().build(catalog, output, source_root=root)
        self.assertTrue(result.path.is_file())
        self.assertEqual((root / "game" / "script.rpy").read_bytes(), source_before)
        rendered = result.path.read_text(encoding="utf-8")
        self.assertIn("translate zh_cn", rendered)
        self.assertIn("你好", rendered)
        self.assertNotIn("$ python_value", rendered)
        self.assertEqual(validate_renpy_translation_text(rendered), 3)
        activation = result.activation_path.read_text(encoding="utf-8")
        self.assertEqual(
            validate_renpy_language_activation_text(
                activation,
                expected_language="zh-CN",
            ),
            "zh_cn",
        )
        self.assertIn('define config.default_language = "zh_cn"', activation)
        self.assertNotIn("config.language =", activation)

    def test_writer_deduplicates_repeated_source_text(self):
        temporary, root = self.make_project()
        self.addCleanup(temporary.cleanup)
        (root / "game" / "script.rpy").write_text(
            SCRIPT + '\n    "A narration line."\n', encoding="utf-8"
        )
        catalog = RenPyExtractor().extract(root).translate(
            {
                "Hello, [name]! {b}Welcome{/b}.": "中[name] {b}Welcome{/b}.",
                "Start game": "中Start game",
                "A narration line.": "中A narration line.",
            }
        )

        result = RenPyWriter().build(catalog, root / "localized-output", source_root=root)
        rendered = result.path.read_text(encoding="utf-8")

        self.assertEqual(rendered.count('old "A narration line."'), 1)
        self.assertEqual(validate_renpy_translation_text(rendered), 3)

    def test_language_identifier_is_safe_and_generated_syntax_fails_closed(self):
        self.assertEqual(renpy_language_identifier("zh-CN"), "zh_cn")
        self.assertEqual(renpy_language_identifier("123"), "lang_123")
        with self.assertRaisesRegex(RenPyValidationError, "statement"):
            validate_renpy_translation_text(
                'translate zh_cn strings:\n    new "missing old"\n'
            )
        with self.assertRaisesRegex(RenPyValidationError, "activation statement"):
            validate_renpy_language_activation_text(
                'define config.language = "zh_cn"\n'
            )

    def test_writer_rejects_stale_source_and_in_place_output_by_default(self):
        temporary, root = self.make_project()
        self.addCleanup(temporary.cleanup)
        catalog = RenPyExtractor().extract(root).translate({"A narration line.": "旁白"})
        (root / "game" / "script.rpy").write_text(SCRIPT + "\n# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            RenPyWriter().build(catalog, root / "localized-output", source_root=root)
        fresh = RenPyExtractor().extract(root).translate({"A narration line.": "旁白"})
        with self.assertRaisesRegex(ValueError, "source root"):
            RenPyWriter().build(fresh, root, source_root=root)

    def test_writer_refuses_reserved_activation_path_in_source(self):
        temporary, root = self.make_project()
        self.addCleanup(temporary.cleanup)
        (root / "game" / "hanengine_language.rpy").write_text(
            'define config.default_language = "ja"\n',
            encoding="utf-8",
        )
        catalog = RenPyExtractor().extract(root).translate(
            {"A narration line.": "旁白"}
        )

        with self.assertRaisesRegex(ValueError, "reserved"):
            RenPyWriter().build(catalog, root / "localized-output", source_root=root)


if __name__ == "__main__":
    unittest.main()
