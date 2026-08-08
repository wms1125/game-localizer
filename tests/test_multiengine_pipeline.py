import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing, redirect_stdout

import cli
from game_localizer.hanengine import (
    GodotExtractor,
    LocalizationCatalog,
    MultiEngineError,
    MultiEngineExtractor,
    MultiEngineWriter,
    RpgMakerExtractor,
    UnityExtractor,
    UnrealExtractor,
)


class MultiEnginePipelineTests(unittest.TestCase):
    def test_rpg_maker_extracts_event_and_database_text_and_builds_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "mv"
            (root / "data").mkdir(parents=True)
            (root / "game.rpgproject").write_text("{}", encoding="utf-8")
            payload = {
                "name": "Hero",
                "note": "<plugin:keep>",
                "events": [
                    None,
                    {
                        "list": [
                            {"code": 101, "parameters": ["face", 0, 0, 0, "Hello, {name}!", 0]},
                            {"code": 401, "parameters": ["Continue"]},
                        ]
                    },
                ],
            }
            source_file = root / "data" / "Actors.json"
            source_file.write_text(json.dumps(payload), encoding="utf-8")
            catalog = RpgMakerExtractor("rpg_maker_mv").extract(root)
            self.assertEqual(
                {entry.source_text for entry in catalog.entries},
                {"Hero", "Hello, {name}!", "Continue"},
            )
            translated = catalog.translate(
                {"Hero": "\u82f1\u96c4", "Hello, {name}!": "\u4f60\u597d, {name}!", "Continue": "\u7ee7\u7eed"}
            )
            output = Path(directory) / "mv-localized"
            result = MultiEngineWriter().build(translated, root, output)
            self.assertEqual(result.entries_written, 3)
            self.assertEqual(json.loads(source_file.read_text(encoding="utf-8"))["name"], "Hero")
            localized = json.loads((output / "data" / "Actors.json").read_text(encoding="utf-8"))
            self.assertEqual(localized["name"], "\u82f1\u96c4")
            self.assertEqual(localized["events"][1]["list"][0]["parameters"][4], "\u4f60\u597d, {name}!")
            self.assertEqual(localized["note"], "<plugin:keep>")

    def test_csv_pipeline_adds_target_language_column(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "project"
            root.mkdir()
            csv_path = root / "translation.csv"
            csv_path.write_text("keys,en\nhello,Hello {name}!\n", encoding="utf-8")
            catalog = GodotExtractor().extract(root, language="zh-CN")
            translated = catalog.translate({"Hello {name}!": "\u4f60\u597d {name}!"})
            output = workspace / "godot-out"
            result = MultiEngineWriter().build(translated, root, output)
            self.assertEqual(result.entries_written, 1)
            self.assertIn("zh-CN", (output / "translation.csv").read_text(encoding="utf-8"))
            self.assertIn("\u4f60\u597d {name}!", (output / "translation.csv").read_text(encoding="utf-8"))

    def test_po_pipeline_updates_msgstr_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "project"
            po_path = root / "Content" / "Localization" / "Game.po"
            po_path.parent.mkdir(parents=True)
            po_path.write_text('msgid ""\nmsgstr "Language: en\\n"\n\nmsgid "Start"\nmsgstr ""\n', encoding="utf-8")
            catalog = UnrealExtractor().extract(root, language="zh-CN")
            translated = catalog.translate({"Start": "\u5f00\u59cb"})
            output = workspace / "unreal-localized"
            MultiEngineWriter().build(translated, root, output)
            self.assertIn('msgstr "\u5f00\u59cb"', (output / "Content" / "Localization" / "Game.po").read_text(encoding="utf-8"))
            self.assertIn('msgstr ""', po_path.read_text(encoding="utf-8"))

    def test_xliff_pipeline_updates_target(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "project"
            path = root / "Assets" / "Localization" / "Game.xliff"
            path.parent.mkdir(parents=True)
            path.write_text(
                '<?xml version="1.0"?><xliff><file><body><trans-unit id="1"><source>Hello</source><target/></trans-unit></body></file></xliff>',
                encoding="utf-8",
            )
            catalog = UnityExtractor().extract(root, language="zh-CN")
            translated = catalog.translate({"Hello": "\u4f60\u597d"})
            output = workspace / "unity-localized"
            MultiEngineWriter().build(translated, root, output)
            self.assertIn("\u4f60\u597d", (output / "Assets" / "Localization" / "Game.xliff").read_text(encoding="utf-8"))

    def test_catalog_rejects_changed_source_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            path = root / "data" / "Actors.json"
            path.write_text('{"name":"Hero"}', encoding="utf-8")
            catalog = RpgMakerExtractor("rpg_maker_mv").extract(root).translate({"Hero": "\u82f1\u96c4"})
            path.write_text('{"name":"Changed"}', encoding="utf-8")
            with self.assertRaisesRegex(MultiEngineError, "changed"):
                MultiEngineWriter().build(catalog, root, Path(directory) / "out")

    def test_engine_cli_extract_and_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            (project / "data").mkdir(parents=True)
            (project / "data" / "System.json").write_text('{"gameTitle":"Demo"}', encoding="utf-8")
            catalog_path = root / "catalog.json"
            output = root / "output"
            dictionary = root / "dictionary.json"
            state_root = root / "state"
            dictionary.write_text(json.dumps({"Demo": "\u6d4b\u8bd5"}), encoding="utf-8")
            log = io.StringIO()
            with redirect_stdout(log):
                self.assertEqual(
                    cli.run_engine(
                        [
                            "extract",
                            "rpg_maker_mv",
                            str(project),
                            "--output",
                            str(catalog_path),
                            "--state-root",
                            str(state_root),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    cli.run_engine(
                        [
                            "build",
                            "rpg_maker_mv",
                            str(project),
                            str(catalog_path),
                            "--output",
                            str(output),
                            "--dictionary",
                            str(dictionary),
                            "--state-root",
                            str(state_root),
                        ]
                    ),
                    0,
                )
            self.assertIn("[HanTask persisted]", log.getvalue())
            self.assertIn("[HanGuard]", log.getvalue())
            with closing(sqlite3.connect(state_root / "config.db")) as connection:
                project_id = connection.execute(
                    "SELECT project_id FROM projects"
                ).fetchone()[0]
            project_db = state_root / "projects" / project_id / "hanengine.db"
            with closing(sqlite3.connect(project_db)) as connection:
                self.assertGreaterEqual(
                    connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
                    5,
                )
                self.assertGreater(
                    connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM route_plans WHERE phase='final'"
                    ).fetchone()[0],
                    1,
                )
            self.assertIn("\u6d4b\u8bd5", (output / "data" / "System.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
