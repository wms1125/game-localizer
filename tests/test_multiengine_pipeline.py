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
    extract_placeholders,
)


class MultiEnginePipelineTests(unittest.TestCase):
    def test_unity_tsv_pipeline_writes_parent_override_and_preserves_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            default = root / "REPO_Data" / "StreamingAssets" / "Localizations" / "Default"
            default.mkdir(parents=True)
            (default / "Game.tsv").write_text("GAME.START\tStart\n", encoding="utf-8")
            (default / "HUD.tsv").write_text(
                "TUTORIAL.MOVEMENT.TEXT\tUse [move] to move.\n", encoding="utf-8"
            )
            (default / "Menu.tsv").write_text(
                "MAIN.SETTINGS\tSettings\nPOPUP.BODY\tFirst\\nSecond\n",
                encoding="utf-8",
            )

            catalog = UnityExtractor().extract(root, language="zh-CN")
            translated = catalog.translate(
                {
                    "Start": "开始",
                    "Use [move] to move.": "使用 [move] 移动。",
                    "Settings": "设置",
                    "First\\nSecond": "第一行\\n第二行",
                }
            )
            output = Path(directory) / "candidate"
            result = MultiEngineWriter().build(translated, root, output)

            self.assertEqual(
                result.files_written,
                (
                    "REPO_Data/StreamingAssets/Localizations/Game.tsv",
                    "REPO_Data/StreamingAssets/Localizations/HUD.tsv",
                    "REPO_Data/StreamingAssets/Localizations/Menu.tsv",
                ),
            )
            self.assertIn("MAIN.SETTINGS\t设置", (output / "REPO_Data" / "StreamingAssets" / "Localizations" / "Menu.tsv").read_text(encoding="utf-8"))
            self.assertIn("POPUP.BODY\t第一行\\n第二行", (output / "REPO_Data" / "StreamingAssets" / "Localizations" / "Menu.tsv").read_text(encoding="utf-8"))
            self.assertEqual(
                (output / "REPO_Data" / "StreamingAssets" / "Localizations" / "Default" / "Menu.tsv").read_text(encoding="utf-8"),
                (default / "Menu.tsv").read_text(encoding="utf-8"),
            )

    def test_unity_tsv_rejects_malformed_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            default = root / "REPO_Data" / "StreamingAssets" / "Localizations" / "Default"
            default.mkdir(parents=True)
            (default / "Game.tsv").write_text("GAME.START\tStart\textra\n", encoding="utf-8")
            (default / "HUD.tsv").write_text("HUD.OK\tOK\n", encoding="utf-8")
            (default / "Menu.tsv").write_text("MAIN.SETTINGS\tSettings\n", encoding="utf-8")

            with self.assertRaisesRegex(MultiEngineError, "invalid TSV row"):
                UnityExtractor().extract(root)

    def test_extract_placeholders_balances_nested_expressions_and_legacy_forms(self):
        self.assertEqual(
            extract_placeholders(
                "score=%1$s name=${name} item=[inventory[0]['name']!q]"
            ),
            ("%1$s", "${name}", "[inventory[0]['name']!q]"),
        )

    def test_extract_placeholders_preserves_rich_text_tags(self):
        self.assertEqual(
            extract_placeholders("Open <b><u>the box</u></b> for a reward."),
            ("<b>", "<u>", "</u>", "</b>"),
        )

    def test_rpg_maker_extracts_event_and_database_text_and_builds_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "mv"
            (root / "data").mkdir(parents=True)
            (root / "game.rpgproject").write_text("{}", encoding="utf-8")
            actor_payload = [
                None,
                {"name": "Hero", "nickname": "", "profile": "", "note": "<plugin:keep>"},
            ]
            map_payload = {
                "displayName": "",
                "events": [
                    None,
                    {
                        "list": [
                            {"code": 101, "parameters": ["face", 0, 0, 0, "Hello, {name}!", 0]},
                            {"code": 401, "parameters": ["Continue"]},
                            {"code": 101, "parameters": ["", 0, 0, 0, "", 0]},
                            {"code": 401, "parameters": [""]},
                            {"code": 102, "parameters": [["Accept", "", "Leave"], 0, 0, 0, 0]},
                            {"code": 405, "parameters": ["Ancient inscription"]},
                            {"code": 408, "parameters": ["developer comment"]},
                        ]
                    },
                ],
            }
            source_file = root / "data" / "Actors.json"
            source_file.write_text(json.dumps(actor_payload), encoding="utf-8")
            map_file = root / "data" / "Map001.json"
            map_file.write_text(json.dumps(map_payload), encoding="utf-8")
            catalog = RpgMakerExtractor("rpg_maker_mv").extract(root)
            self.assertEqual(
                {entry.source_text for entry in catalog.entries},
                {
                    "Hero",
                    "Hello, {name}!",
                    "Continue",
                    "Accept",
                    "Leave",
                    "Ancient inscription",
                },
            )
            translated = catalog.translate(
                {
                    "Hero": "\u82f1\u96c4",
                    "Hello, {name}!": "\u4f60\u597d, {name}!",
                    "Continue": "\u7ee7\u7eed",
                    "Accept": "\u63a5\u53d7",
                    "Leave": "\u79bb\u5f00",
                    "Ancient inscription": "\u53e4\u8001\u7684\u94ed\u6587",
                }
            )
            output = Path(directory) / "mv-localized"
            result = MultiEngineWriter().build(translated, root, output)
            self.assertEqual(result.entries_written, 6)
            self.assertEqual(json.loads(source_file.read_text(encoding="utf-8"))[1]["name"], "Hero")
            localized = json.loads((output / "data" / "Actors.json").read_text(encoding="utf-8"))
            localized_map = json.loads((output / "data" / "Map001.json").read_text(encoding="utf-8"))
            self.assertEqual(localized[1]["name"], "\u82f1\u96c4")
            self.assertEqual(localized_map["events"][1]["list"][0]["parameters"][4], "\u4f60\u597d, {name}!")
            self.assertEqual(localized[1]["note"], "<plugin:keep>")
            self.assertEqual(localized_map["events"][1]["list"][6]["parameters"][0], "developer comment")

    def test_rpg_maker_resource_policy_extracts_visible_database_and_system_text(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "mv"
            data = root / "data"
            data.mkdir(parents=True)
            payloads = {
                "Animations.json": [None, {"name": "Editor Animation"}],
                "MapInfos.json": [None, {"name": "Editor Map Name"}],
                "Tilesets.json": [None, {"name": "Editor Tileset"}],
                "Skills.json": [
                    None,
                    {
                        "name": "Heal",
                        "description": "Restore HP.",
                        "message1": " casts Heal!",
                        "message2": "",
                    },
                ],
                "States.json": [
                    None,
                    {
                        "name": "Poison",
                        "message1": " is poisoned!",
                        "message2": " was poisoned!",
                        "message3": " is still poisoned.",
                        "message4": " recovered from poison.",
                    },
                ],
                "System.json": {
                    "gameTitle": "Test Quest",
                    "currencyUnit": "Gold",
                    "armorTypes": ["", "Shield"],
                    "elements": ["", "Flame"],
                    "equipTypes": ["", "Weapon"],
                    "skillTypes": ["", "Magic"],
                    "weaponTypes": ["", "Sword"],
                    "terms": {
                        "basic": ["Level"],
                        "commands": ["Fight"],
                        "params": ["Max HP"],
                        "messages": {"actionFailure": "There was no effect."},
                    },
                },
            }
            for name, payload in payloads.items():
                (data / name).write_text(json.dumps(payload), encoding="utf-8")

            catalog = RpgMakerExtractor("rpg_maker_mv").extract(root)

            source_texts = {entry.source_text for entry in catalog.entries}
            self.assertNotIn("Editor Animation", source_texts)
            self.assertNotIn("Editor Map Name", source_texts)
            self.assertNotIn("Editor Tileset", source_texts)
            self.assertTrue(
                {
                    "Heal",
                    "Restore HP.",
                    " casts Heal!",
                    "Poison",
                    " is poisoned!",
                    " was poisoned!",
                    " is still poisoned.",
                    " recovered from poison.",
                    "Test Quest",
                    "Gold",
                    "Shield",
                    "Flame",
                    "Weapon",
                    "Magic",
                    "Sword",
                    "Level",
                    "Fight",
                    "Max HP",
                    "There was no effect.",
                }
                <= source_texts
            )

            translated = catalog.translate(
                {
                    "Test Quest": "\u6d4b\u8bd5\u4e4b\u65c5",
                    "Fight": "\u6218\u6597",
                    "There was no effect.": "\u6ca1\u6709\u6548\u679c\u3002",
                    " casts Heal!": "\u65bd\u653e\u4e86\u6cbb\u7597\uff01",
                    " recovered from poison.": "\u4ece\u4e2d\u6bd2\u72b6\u6001\u6062\u590d\u4e86\u3002",
                }
            )
            output = workspace / "localized"
            result = MultiEngineWriter().build(translated, root, output)

            self.assertEqual(result.entries_written, 5)
            system = json.loads((output / "data" / "System.json").read_text(encoding="utf-8"))
            skills = json.loads((output / "data" / "Skills.json").read_text(encoding="utf-8"))
            states = json.loads((output / "data" / "States.json").read_text(encoding="utf-8"))
            self.assertEqual(system["gameTitle"], "\u6d4b\u8bd5\u4e4b\u65c5")
            self.assertEqual(system["terms"]["commands"][0], "\u6218\u6597")
            self.assertEqual(system["terms"]["messages"]["actionFailure"], "\u6ca1\u6709\u6548\u679c\u3002")
            self.assertEqual(skills[1]["message1"], "\u65bd\u653e\u4e86\u6cbb\u7597\uff01")
            self.assertEqual(states[1]["message4"], "\u4ece\u4e2d\u6bd2\u72b6\u6001\u6062\u590d\u4e86\u3002")

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
            self.assertIn("zh_CN", (output / "translation.csv").read_text(encoding="utf-8"))
            self.assertIn("\u4f60\u597d {name}!", (output / "translation.csv").read_text(encoding="utf-8"))

    def test_godot_discovers_and_appends_runtime_node_names_from_typed_translation_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "project"
            (root / "translations").mkdir(parents=True)
            (root / "src").mkdir()
            (root / "scenes").mkdir()
            csv_path = root / "translations" / "game_ui_translations.csv"
            csv_path.write_text("keys,en\nStart,Start\n", encoding="utf-8")
            (root / "src" / "battler.gd").write_text(
                "class_name Battler extends Node2D\n", encoding="utf-8"
            )
            (root / "src" / "life_bar.gd").write_text(
                "class_name LifeBar extends Control\n"
                "func setup(battler_name: String) -> void:\n"
                "    $Name.text = tr(battler_name)\n",
                encoding="utf-8",
            )
            (root / "src" / "entry.gd").write_text(
                "class_name Entry extends Control\n"
                "var battler: Battler\n"
                "@onready var life := $Life as LifeBar\n"
                "func refresh() -> void:\n"
                "    life.setup(battler.name)\n",
                encoding="utf-8",
            )
            (root / "scenes" / "arena.tscn").write_text(
                '[gd_scene load_steps=2 format=3]\n\n'
                '[ext_resource type="Script" path="res://src/battler.gd" id="1_battler"]\n\n'
                '[node name="Arena" type="Node2D"]\n'
                '[node name="Battlers" type="Node2D" parent="."]\n'
                '[node name="Bugcat" type="Node2D" parent="Battlers"]\n'
                'script = ExtResource("1_battler")\n'
                '[node name="Wolf" type="Node2D" parent="Battlers"]\n'
                'script = ExtResource("1_battler")\n',
                encoding="utf-8",
            )

            catalog = GodotExtractor().extract(root, language="zh-CN")
            self.assertEqual(
                {entry.source_text for entry in catalog.entries},
                {"Start", "Bugcat", "Wolf"},
            )
            runtime_entries = [
                entry for entry in catalog.entries if entry.kind == "godot_runtime_node_name"
            ]
            self.assertEqual({entry.source_text for entry in runtime_entries}, {"Bugcat", "Wolf"})
            self.assertNotIn("Battlers", {entry.source_text for entry in catalog.entries})

            translated = catalog.translate(
                {"Start": "\u5f00\u59cb", "Bugcat": "\u866b\u732b", "Wolf": "\u72fc"}
            )
            output = workspace / "localized"
            result = MultiEngineWriter().build(translated, root, output)

            self.assertEqual(result.entries_written, 3)
            localized = (output / "translations" / "game_ui_translations.csv").read_text(
                encoding="utf-8"
            )
            self.assertIn("Bugcat,Bugcat,\u866b\u732b", localized)
            self.assertIn("Wolf,Wolf,\u72fc", localized)
            self.assertNotIn("Bugcat", csv_path.read_text(encoding="utf-8"))

    def test_godot_blocks_one_runtime_name_shared_by_different_display_classes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            (root / "translations").mkdir(parents=True)
            (root / "src").mkdir()
            (root / "scenes").mkdir()
            (root / "translations" / "game_ui.csv").write_text(
                "keys,en\nStart,Start\n", encoding="utf-8"
            )
            (root / "src" / "battler.gd").write_text(
                "class_name Battler extends Node2D\n", encoding="utf-8"
            )
            (root / "src" / "marker.gd").write_text(
                "class_name QuestMarker extends Node2D\n", encoding="utf-8"
            )
            (root / "src" / "presenter.gd").write_text(
                "class_name Presenter extends Control\n"
                "var battler: Battler\n"
                "var marker: QuestMarker\n"
                "func refresh() -> void:\n"
                "    $A.text = tr(battler.name)\n"
                "    $B.text = tr(marker.name)\n",
                encoding="utf-8",
            )
            (root / "scenes" / "ambiguous.tscn").write_text(
                '[gd_scene load_steps=3 format=3]\n'
                '[ext_resource type="Script" path="res://src/battler.gd" id="1"]\n'
                '[ext_resource type="Script" path="res://src/marker.gd" id="2"]\n'
                '[node name="Shared" type="Node2D"]\n'
                'script = ExtResource("1")\n'
                '[node name="Shared" type="Node2D" parent="."]\n'
                'script = ExtResource("2")\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(MultiEngineError, "ambiguous.*Shared"):
                GodotExtractor().extract(root, language="zh-CN")

    def test_godot_blocks_default_class_node_names_as_unstable_display_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            (root / "translations").mkdir(parents=True)
            (root / "src").mkdir()
            (root / "scenes").mkdir()
            (root / "translations" / "game_ui.csv").write_text(
                "keys,en\nStart,Start\n", encoding="utf-8"
            )
            (root / "src" / "battler.gd").write_text(
                "class_name Battler extends Node2D\n", encoding="utf-8"
            )
            (root / "src" / "presenter.gd").write_text(
                "class_name Presenter extends Control\n"
                "var battler: Battler\n"
                "func refresh() -> void:\n"
                "    $Name.text = tr(battler.name)\n",
                encoding="utf-8",
            )
            (root / "scenes" / "arena.tscn").write_text(
                '[gd_scene load_steps=2 format=3]\n'
                '[ext_resource type="Script" path="res://src/battler.gd" id="1"]\n'
                '[node name="Battler2" type="Node2D"]\n'
                'script = ExtResource("1")\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(MultiEngineError, "unstable.*Battler2"):
                GodotExtractor().extract(root, language="zh-CN")

    def test_godot_po_fingerprint_tracks_project_context_without_exposing_it_as_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "project"
            (root / "locale").mkdir(parents=True)
            (root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
            scene = root / "main.tscn"
            scene.write_text(
                '[gd_scene format=3]\n[node name="Main" type="Node"]\n',
                encoding="utf-8",
            )
            (root / "locale" / "game.po").write_text(
                'msgid ""\nmsgstr "Language: en\\n"\n\nmsgid "Start"\nmsgstr ""\n',
                encoding="utf-8",
            )

            catalog = GodotExtractor().extract(root, language="zh-CN")

            self.assertEqual(catalog.files, ("locale/game.po",))
            translated = catalog.translate({"Start": "\u5f00\u59cb"})
            scene.write_text(
                '[gd_scene format=3]\n[node name="Changed" type="Node"]\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(MultiEngineError, "changed"):
                MultiEngineWriter().build(translated, root, workspace / "localized")

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
