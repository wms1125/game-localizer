from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from game_localizer.adapters import (
    GodotAdapterV1,
    RenPyAdapterV1,
    RpgMakerMVAdapterV1,
    RpgMakerMZAdapterV1,
    UnityAdapterV1,
    UnrealAdapterV1,
    get_adapters,
)
from game_localizer.adapters.contract import (
    AdapterCapability,
    AdapterError,
    AdapterErrorCode,
    AdapterMaturity,
    BuildRequest,
    BuildResult,
    DeclaredMode,
    DetectionRequest,
    ExtractRequest,
    ExtractResult,
    Operation,
    RollbackRequest,
    ValidationRequest,
    ValidationResult,
    VerifyRequest,
    VerifyResult,
)
from game_localizer.hanengine.routing import RiskLevel
from game_localizer.hanengine.godot import run_godot_style_hard_gate
from game_localizer.hanengine.rpg_maker import run_rpg_maker_style_hard_gate
from game_localizer.hanengine.raster import (
    RASTER_MANIFEST_SCHEMA_VERSION,
    RasterAsset,
    RasterAssetKind,
    RasterManifest,
    RasterSegmentStatus,
    RasterTextSegment,
    RasterTextStyle,
    write_raster_manifest,
)
from game_localizer.hanengine.segments import ScreenRegion, Segment
from game_localizer.hanengine.tasks import TaskContext, TaskControl
from tests.adapter_contract_v1 import AdapterV1ContractMixin, snapshot_tree


def make_context(step_id: str = "adapter") -> TaskContext:
    return TaskContext("task-structured", step_id, TaskControl(), lambda *args: None)


class RpgMakerMVAdapterContractTests(AdapterV1ContractMixin, unittest.TestCase):
    adapter_type = RpgMakerMVAdapterV1
    marker_path = "game.rpgproject"
    marker_content = "RPG Maker MV"

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name).resolve()
        self.matched_root = self.root / "matched"
        self.unmatched_root = self.root / "unmatched"
        self.matched_root.mkdir()
        self.unmatched_root.mkdir()
        marker = self.matched_root / Path(*self.marker_path.split("/"))
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(self.marker_content, encoding="utf-8")

    def make_adapter(self):
        return self.adapter_type()

    def make_detection_request(self):
        return DetectionRequest(
            self.matched_root,
            DeclaredMode.STUDIO,
            "project-structured",
            RiskLevel.H0_PROJECT,
            frozenset({Operation.DETECT}),
            make_context("detect"),
        )

    def make_unmatched_detection_request(self):
        return replace(self.make_detection_request(), input_root=self.unmatched_root)


class RpgMakerMZAdapterContractTests(RpgMakerMVAdapterContractTests):
    adapter_type = RpgMakerMZAdapterV1
    marker_path = "game.rmmzproject"
    marker_content = "RPG Maker MZ"


class GodotAdapterContractTests(RpgMakerMVAdapterContractTests):
    adapter_type = GodotAdapterV1
    marker_path = "project.godot"
    marker_content = "config_version=5\n"


class UnityAdapterContractTests(RpgMakerMVAdapterContractTests):
    adapter_type = UnityAdapterV1
    marker_path = "ProjectSettings/ProjectVersion.txt"
    marker_content = "m_EditorVersion: 2022.3.10f1\n"


class UnrealAdapterContractTests(RpgMakerMVAdapterContractTests):
    adapter_type = UnrealAdapterV1
    marker_path = "Demo.uproject"
    marker_content = '{"EngineAssociation":"5.4"}'


class RenPyAdapterContractTests(RpgMakerMVAdapterContractTests):
    adapter_type = RenPyAdapterV1
    marker_path = "game/script.rpy"
    marker_content = 'e "Hello"\n'


class StructuredPipelineTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name).resolve()

    def _make_mv_project(self) -> tuple[Path, Path]:
        source = self.root / "source"
        data = source / "data"
        data.mkdir(parents=True)
        (source / "game.rpgproject").write_text("RPG Maker MV", encoding="utf-8")
        source_file = data / "Actors.json"
        source_file.write_text(
            json.dumps(
                [None, {"name": "Hero", "nickname": "", "profile": ""}]
            ),
            encoding="utf-8",
        )
        (data / "Map001.json").write_text(
            json.dumps(
                {
                    "displayName": "",
                    "events": [
                        {"list": [{"code": 401, "parameters": ["Hello, {name}!"]}]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return source, source_file

    def _extract_mv(self, source: Path) -> ExtractResult:
        working = self.root / "working"
        working.mkdir(exist_ok=True)
        result = RpgMakerMVAdapterV1().extract(
            ExtractRequest(source, working, (), (), "project-mv", make_context("extract"))
        )
        self.assertIsInstance(result, ExtractResult)
        return result

    @staticmethod
    def _segments(result: ExtractResult) -> tuple[tuple[Segment, ...], tuple[Segment, ...]]:
        originals = tuple(
            Segment.from_draft("project-mv", "zh-CN", draft) for draft in result.segments
        )
        translations = {
            "Hero": "英雄",
            "Hello, {name}!": "你好，{name}!",
        }
        translated = tuple(
            replace(
                segment,
                target_text=translations[segment.source_text],
                translation_source="test",
            )
            for segment in originals
        )
        return originals, translated

    def test_extract_validate_build_verify_round_trip(self):
        source, source_file = self._make_mv_project()
        adapter = RpgMakerMVAdapterV1()
        extracted = self._extract_mv(source)
        originals, translated = self._segments(extracted)

        validation = adapter.validate(
            ValidationRequest(
                extracted.source_tree_fingerprint,
                originals,
                translated,
                "utf-8",
                {},
                make_context("validate"),
            )
        )
        self.assertIsInstance(validation, ValidationResult)
        self.assertTrue(validation.valid)

        staging = self.root / "staging"
        staging.mkdir()
        before_source = snapshot_tree(source)
        built = adapter.build(
            BuildRequest(
                source,
                staging,
                translated,
                extracted.source_tree_fingerprint,
                {},
                make_context("build"),
            )
        )
        self.assertIsInstance(built, BuildResult)
        self.assertEqual(snapshot_tree(source), before_source)
        self.assertEqual(built.modified_files, ("data/Actors.json", "data/Map001.json"))
        localized = json.loads((staging / "data" / "Actors.json").read_text(encoding="utf-8"))
        localized_map = json.loads(
            (staging / "data" / "Map001.json").read_text(encoding="utf-8")
        )
        self.assertEqual(localized[1]["name"], "英雄")
        self.assertEqual(localized_map["events"][0]["list"][0]["parameters"][0], "你好，{name}!")
        self.assertEqual(json.loads(source_file.read_text(encoding="utf-8"))[1]["name"], "Hero")

        verified = adapter.verify(
            VerifyRequest(
                extracted.source_tree_fingerprint,
                staging,
                built.manifest,
                "full",
                make_context("verify"),
            )
        )
        self.assertIsInstance(verified, VerifyResult)
        self.assertTrue(verified.passed)
        self.assertTrue(verified.syntax_passed)
        self.assertTrue(verified.encoding_passed)

        rollback = adapter.rollback(
            RollbackRequest(
                "project-mv",
                built.manifest,
                (),
                staging,
                {},
                make_context("rollback"),
            )
        )
        self.assertIsInstance(rollback, AdapterError)
        self.assertIs(rollback.code, AdapterErrorCode.UNSUPPORTED_INPUT)
        self.assertIs(rollback.operation, Operation.ROLLBACK)

    def test_rpg_maker_build_merges_approved_raster_asset_into_candidate_manifest(self):
        source, _ = self._make_mv_project()
        (source / "img").mkdir()
        (source / "fonts").mkdir()
        (source / "fonts" / "gamefont.css").write_text(
            "@font-face { font-family: GameFont; src: url(\"mplus.ttf\"); }\n",
            encoding="utf-8",
        )
        (source / "fonts" / "mplus.ttf").write_bytes(b"source-font")
        source_raster = source / "img" / "title.png"
        source_raster.write_bytes(b"source-title")
        source_before = snapshot_tree(source)
        cjk_font = self.root / "SourceHanSans.ttf"
        cjk_font.write_bytes(b"localized-font")
        artifact_root = self.root / "raster"
        artifact_root.mkdir()
        localized_raster = artifact_root / "title.zh.png"
        localized_raster.write_bytes(b"localized-title-zh")
        manifest = RasterManifest(
            RASTER_MANIFEST_SCHEMA_VERSION,
            "en",
            "zh-CN",
            (
                RasterAsset(
                    "img/title.png",
                    RasterAssetKind.IMAGE,
                    hashlib.sha256(source_raster.read_bytes()).hexdigest(),
                    "title.zh.png",
                    hashlib.sha256(localized_raster.read_bytes()).hexdigest(),
                    (
                        RasterTextSegment(
                            "title-raster-text",
                            "img/title.png",
                            RasterAssetKind.IMAGE,
                            "HELLO UNDERWORLD",
                            "你好，地下世界",
                            ScreenRegion(20, 30, 320, 64),
                            None,
                            None,
                            0.98,
                            RasterTextStyle(
                                font_family="Source Han Sans",
                                font_size_px=30,
                                fill_color="#ffffff",
                                stroke_color="#000000",
                                stroke_width_px=2,
                            ),
                            RasterSegmentStatus.APPROVED,
                            None,
                        ),
                    ),
                ),
            ),
        )
        manifest_path = write_raster_manifest(manifest, artifact_root / "manifest.json")
        extracted = self._extract_mv(source)
        _, translated = self._segments(extracted)
        output = self.root / "raster-output"
        adapter = RpgMakerMVAdapterV1()

        built = adapter.build(
            BuildRequest(
                source,
                output,
                translated,
                extracted.source_tree_fingerprint,
                {
                    "raster_manifest": str(manifest_path),
                    "rpg_maker_font_paths": [str(cjk_font)],
                },
                make_context("build"),
            )
        )

        self.assertIsInstance(built, BuildResult)
        self.assertIn("img/title.png", built.modified_files)
        self.assertIn("data/Actors.json", built.modified_files)
        self.assertIn("fonts/SourceHanSans.ttf", built.added_files)
        self.assertEqual((output / "img" / "title.png").read_bytes(), b"localized-title-zh")
        self.assertEqual(snapshot_tree(source), source_before)
        verified = adapter.verify(
            VerifyRequest(
                extracted.source_tree_fingerprint,
                output,
                built.manifest,
                "full",
                make_context("verify"),
            )
        )
        self.assertIsInstance(verified, VerifyResult)
        self.assertTrue(verified.passed)

    def test_validation_blocks_placeholder_and_source_metadata_changes(self):
        source, _ = self._make_mv_project()
        extracted = self._extract_mv(source)
        originals, translated = self._segments(extracted)
        placeholder_index = next(
            index for index, segment in enumerate(translated) if "{name}" in segment.source_text
        )
        changed = list(translated)
        changed[placeholder_index] = replace(
            changed[placeholder_index],
            target_text="你好!",
            metadata={**changed[placeholder_index].metadata, "kind": "changed"},
        )
        result = RpgMakerMVAdapterV1().validate(
            ValidationRequest(
                extracted.source_tree_fingerprint,
                originals,
                tuple(changed),
                "utf-8",
                {},
                make_context("validate"),
            )
        )
        self.assertIsInstance(result, ValidationResult)
        self.assertFalse(result.valid)
        self.assertGreaterEqual(result.blocking_issue_count, 2)
        self.assertTrue(
            {"placeholder_mismatch", "source_metadata_changed"}.issubset(
                {issue.code for issue in result.issues}
            )
        )

    def test_rpg_maker_validation_distinguishes_visible_text_from_control_codes(self):
        source, _ = self._make_mv_project()
        map_path = source / "data" / "Map001.json"
        document = json.loads(map_path.read_text(encoding="utf-8"))
        document["events"][0]["list"].extend(
            [
                {"code": 401, "parameters": ["[Hades]"]},
                {"code": 401, "parameters": [r"Over \{TWELVE HOURS\}."]},
                {"code": 401, "parameters": [r"Score: \v[1]"]},
            ]
        )
        map_path.write_text(json.dumps(document), encoding="utf-8")
        extracted = self._extract_mv(source)
        originals = tuple(
            Segment.from_draft("project-mv", "zh-CN", draft) for draft in extracted.segments
        )
        translations = {
            "Hero": "英雄",
            "Hello, {name}!": "你好，{name}!",
            "[Hades]": "[哈迪斯]",
            r"Over \{TWELVE HOURS\}.": r"已经\{十二个小时\}了。",
            r"Score: \v[1]": r"分数：\v[1]",
        }
        translated = tuple(
            replace(
                segment,
                target_text=translations[segment.source_text],
                translation_source="test",
            )
            for segment in originals
        )
        adapter = RpgMakerMVAdapterV1()

        valid = adapter.validate(
            ValidationRequest(
                extracted.source_tree_fingerprint,
                originals,
                translated,
                "utf-8",
                {},
                make_context("validate"),
            )
        )
        self.assertIsInstance(valid, ValidationResult)
        self.assertTrue(valid.valid)
        built = adapter.build(
            BuildRequest(
                source,
                self.root / "rpg-maker-control-output",
                translated,
                extracted.source_tree_fingerprint,
                {},
                make_context("build"),
            )
        )
        self.assertIsInstance(built, BuildResult)

        broken = tuple(
            replace(segment, target_text="分数：1")
            if segment.source_text == r"Score: \v[1]"
            else segment
            for segment in translated
        )
        invalid = adapter.validate(
            ValidationRequest(
                extracted.source_tree_fingerprint,
                originals,
                broken,
                "utf-8",
                {},
                make_context("validate"),
            )
        )
        self.assertIsInstance(invalid, ValidationResult)
        self.assertFalse(invalid.valid)
        self.assertIn("placeholder_mismatch", {issue.code for issue in invalid.issues})

    def test_validation_warns_when_english_natural_language_is_left_unchanged(self):
        source, _ = self._make_mv_project()
        extracted = self._extract_mv(source)
        originals, translated = self._segments(extracted)
        unchanged = tuple(
            replace(segment, target_text=segment.source_text, translation_source="test")
            if segment.source_text == "Hello, {name}!"
            else segment
            for segment in translated
        )
        result = RpgMakerMVAdapterV1().validate(
            ValidationRequest(
                extracted.source_tree_fingerprint,
                originals,
                unchanged,
                "utf-8",
                {},
                make_context("validate"),
            )
        )
        self.assertIsInstance(result, ValidationResult)
        self.assertTrue(result.valid)
        self.assertIn("untranslated_natural_language", {issue.code for issue in result.issues})
        self.assertEqual(result.warning_count, 1)

    def test_build_failure_preserves_existing_staging_contents(self):
        source, _ = self._make_mv_project()
        extracted = self._extract_mv(source)
        _, translated = self._segments(extracted)
        staging = self.root / "staging"
        staging.mkdir()
        sentinel = staging / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        before = snapshot_tree(staging)
        result = RpgMakerMVAdapterV1().build(
            BuildRequest(
                source,
                staging,
                translated,
                extracted.source_tree_fingerprint,
                {},
                make_context("build"),
            )
        )
        self.assertIsInstance(result, AdapterError)
        self.assertIs(result.code, AdapterErrorCode.BUILD_FAILED)
        self.assertEqual(snapshot_tree(staging), before)

    def test_build_rejects_changed_source_and_leaves_empty_staging(self):
        source, source_file = self._make_mv_project()
        extracted = self._extract_mv(source)
        _, translated = self._segments(extracted)
        source_file.write_text('{"name":"Changed"}', encoding="utf-8")
        staging = self.root / "staging"
        staging.mkdir()
        result = RpgMakerMVAdapterV1().build(
            BuildRequest(
                source,
                staging,
                translated,
                extracted.source_tree_fingerprint,
                {},
                make_context("build"),
            )
        )
        self.assertIsInstance(result, AdapterError)
        self.assertEqual(snapshot_tree(staging), ())

    def test_packaged_projects_are_detect_only(self):
        fixtures = (
            (GodotAdapterV1(), "game.pck"),
            (UnityAdapterV1(), "UnityPlayer.dll"),
            (UnrealAdapterV1(), "Content/Paks/game.pak"),
            (RenPyAdapterV1(), "game/archive.rpa"),
        )
        for index, (adapter, relative) in enumerate(fixtures):
            with self.subTest(adapter=type(adapter).__name__):
                root = self.root / f"packaged-{index}"
                marker = root / Path(*relative.split("/"))
                marker.parent.mkdir(parents=True)
                marker.write_bytes(b"package")
                result = adapter.detect(
                    DetectionRequest(
                        root,
                        DeclaredMode.PLAYER,
                        f"project-{index}",
                        RiskLevel.H0_PROJECT,
                        frozenset({Operation.DETECT}),
                        make_context("detect"),
                    )
                )
                self.assertTrue(result.matched)
                self.assertIs(result.maturity, AdapterMaturity.DETECT_ONLY)
                self.assertEqual(result.capabilities, frozenset({AdapterCapability.DETECT}))

    def test_unity_packaged_tsv_resources_are_build_ready(self):
        root = self.root / "repo"
        default = root / "REPO_Data" / "StreamingAssets" / "Localizations" / "Default"
        default.mkdir(parents=True)
        (root / "UnityPlayer.dll").write_bytes(b"fixture")
        (default / "Game.tsv").write_text("GAME.START\tStart\n", encoding="utf-8")
        (default / "HUD.tsv").write_text("HUD.OK\tOK\n", encoding="utf-8")
        (default / "Menu.tsv").write_text("MAIN.SETTINGS\tSettings\n", encoding="utf-8")

        result = UnityAdapterV1().detect(
            DetectionRequest(
                root,
                DeclaredMode.PLAYER,
                "project-repo-tsv",
                RiskLevel.H0_PROJECT,
                frozenset({Operation.DETECT}),
                make_context("detect"),
            )
        )

        self.assertTrue(result.matched)
        self.assertIs(result.maturity, AdapterMaturity.BUILD_READY)
        self.assertEqual(
            result.capabilities,
            frozenset(
                {
                    AdapterCapability.DETECT,
                    AdapterCapability.EXTRACT,
                    AdapterCapability.VALIDATE,
                    AdapterCapability.BUILD,
                    AdapterCapability.VERIFY,
                }
            ),
        )

    def test_each_adapter_extracts_its_plaintext_format(self):
        fixtures = []

        mv = self.root / "mv"
        (mv / "data").mkdir(parents=True)
        (mv / "data" / "System.json").write_text('{"gameTitle":"MV"}', encoding="utf-8")
        fixtures.append((RpgMakerMVAdapterV1(), mv, "MV"))

        mz = self.root / "mz"
        (mz / "data").mkdir(parents=True)
        (mz / "data" / "System.json").write_text('{"gameTitle":"MZ"}', encoding="utf-8")
        fixtures.append((RpgMakerMZAdapterV1(), mz, "MZ"))

        godot = self.root / "godot"
        godot.mkdir()
        (godot / "translation.po").write_text('msgid "Hello Godot"\nmsgstr ""\n', encoding="utf-8")
        fixtures.append((GodotAdapterV1(), godot, "Hello Godot"))

        unity = self.root / "unity"
        unity.mkdir()
        (unity / "strings.xliff").write_text(
            '<xliff><file><body><trans-unit id="1"><source>Hello Unity</source><target/></trans-unit></body></file></xliff>',
            encoding="utf-8",
        )
        fixtures.append((UnityAdapterV1(), unity, "Hello Unity"))

        unreal = self.root / "unreal"
        unreal.mkdir()
        (unreal / "Game.po").write_text('msgid "Hello Unreal"\nmsgstr ""\n', encoding="utf-8")
        fixtures.append((UnrealAdapterV1(), unreal, "Hello Unreal"))

        renpy = self.root / "renpy"
        (renpy / "game").mkdir(parents=True)
        (renpy / "game" / "script.rpy").write_text('e "Hello RenPy"\n', encoding="utf-8")
        fixtures.append((RenPyAdapterV1(), renpy, "Hello RenPy"))

        for index, (adapter, source, expected) in enumerate(fixtures):
            with self.subTest(adapter=type(adapter).__name__):
                working = self.root / f"working-{index}"
                working.mkdir()
                before = snapshot_tree(source)
                result = adapter.extract(
                    ExtractRequest(
                        source,
                        working,
                        (),
                        (),
                        f"project-{index}",
                        make_context("extract"),
                    )
                )
                self.assertIsInstance(result, ExtractResult)
                self.assertIn(expected, {segment.source_text for segment in result.segments})
                self.assertEqual(snapshot_tree(source), before)

    def test_godot_style_build_packages_font_and_preserves_source_typography(self):
        source = self.root / "godot-style-project"
        (source / "translations").mkdir(parents=True)
        (source / "ui").mkdir()
        (source / "project.godot").write_text(
            'config_version=5\n\n[gui]\n\ntheme/custom="res://ui/game.theme"\n',
            encoding="utf-8",
        )
        theme_bytes = b"source-theme-style"
        (source / "ui" / "game.theme").write_bytes(theme_bytes)
        scene_text = '[gd_scene format=3]\n[node name="Title" type="Label"]\ntheme_override_font_sizes/font_size = 18\n'
        (source / "ui" / "title.tscn").write_text(scene_text, encoding="utf-8")
        (source / "translations" / "game.csv").write_text(
            "keys,en\nStart,Start\n", encoding="utf-8"
        )
        font = self.root / "PixelCJK.ttf"
        font.write_bytes(b"font-fixture")
        adapter = GodotAdapterV1()
        working = self.root / "godot-style-working"
        working.mkdir()
        extracted = adapter.extract(
            ExtractRequest(source, working, (), (), "godot-style", make_context("extract"))
        )
        self.assertIsInstance(extracted, ExtractResult)
        originals = tuple(
            Segment.from_draft("godot-style", "zh-CN", draft)
            for draft in extracted.segments
        )
        translated = tuple(
            replace(segment, target_text="\u5f00\u59cb", translation_source="test")
            for segment in originals
        )
        output = self.root / "godot-style-output"

        built = adapter.build(
            BuildRequest(
                source,
                output,
                translated,
                extracted.source_tree_fingerprint,
                {"godot_font_paths": [str(font)]},
                make_context("build"),
            )
        )

        self.assertIsInstance(built, BuildResult)
        self.assertIn("hanengine/fonts/PixelCJK.ttf", built.added_files)
        self.assertIn("hanengine/locale_style.gd", built.added_files)
        self.assertIn("project.godot", built.modified_files)
        self.assertEqual((output / "ui" / "game.theme").read_bytes(), theme_bytes)
        self.assertEqual((output / "ui" / "title.tscn").read_text(encoding="utf-8"), scene_text)
        style_script = (output / "hanengine" / "locale_style.gd").read_text(encoding="utf-8")
        self.assertIn("project_theme.default_font = cjk_font", style_script)
        self.assertNotIn("font_size", style_script)
        self.assertNotIn("font_color", style_script)

        gate = run_godot_style_hard_gate(source, output, (font,))
        self.assertTrue(gate.passed)
        verified = adapter.verify(
            VerifyRequest(
                extracted.source_tree_fingerprint,
                output,
                built.manifest,
                "full",
                make_context("verify"),
            )
        )
        self.assertIsInstance(verified, VerifyResult)
        self.assertTrue(verified.passed)

        (output / "hanengine" / "locale_style.gd").write_text(
            style_script + "\n# default_font_size\n", encoding="utf-8"
        )
        blocked = run_godot_style_hard_gate(source, output, (font,))
        self.assertFalse(blocked.passed)
        self.assertIn("godot_font_size_preserved", blocked.failed_codes)

    def test_rpg_maker_mv_style_build_packages_font_and_preserves_source_typography(self):
        source = self.root / "rpg-mv-style-project"
        (source / "data").mkdir(parents=True)
        (source / "fonts").mkdir()
        (source / "js" / "plugins").mkdir(parents=True)
        (source / "img" / "system").mkdir(parents=True)
        (source / "game.rpgproject").write_text("RPGMV 1.5.2", encoding="utf-8")
        (source / "data" / "Actors.json").write_text(
            json.dumps([None, {"name": "Hero", "nickname": "", "profile": ""}]),
            encoding="utf-8",
        )
        source_css = (
            "@font-face {\n"
            "    font-family: GameFont;\n"
            '    src: url("mplus-1m-regular.ttf");\n'
            "}\n"
        )
        (source / "fonts" / "gamefont.css").write_text(source_css, encoding="utf-8")
        (source / "fonts" / "mplus-1m-regular.ttf").write_bytes(b"source-font")
        source_script = "Window_Base.prototype.standardFontSize = function() { return 28; };\n"
        (source / "js" / "rpg_windows.js").write_text(source_script, encoding="utf-8")
        (source / "js" / "plugins" / "style.js").write_text(
            "// source style plugin\n", encoding="utf-8"
        )
        (source / "img" / "system" / "Window.png").write_bytes(b"source-window-skin")
        font = self.root / "SourceHanSans.ttf"
        font.write_bytes(b"cjk-font")
        adapter = RpgMakerMVAdapterV1()
        working = self.root / "rpg-mv-style-working"
        working.mkdir()
        extracted = adapter.extract(
            ExtractRequest(source, working, (), (), "rpg-mv-style", make_context("extract"))
        )
        self.assertIsInstance(extracted, ExtractResult)
        translated = tuple(
            replace(
                Segment.from_draft("rpg-mv-style", "zh-CN", draft),
                target_text="\u82f1\u96c4",
                translation_source="test",
            )
            for draft in extracted.segments
        )
        output = self.root / "rpg-mv-style-output"

        built = adapter.build(
            BuildRequest(
                source,
                output,
                translated,
                extracted.source_tree_fingerprint,
                {"rpg_maker_font_paths": [str(font)]},
                make_context("build"),
            )
        )

        self.assertIsInstance(built, BuildResult)
        self.assertIn("fonts/SourceHanSans.ttf", built.added_files)
        self.assertIn("fonts/gamefont.css", built.modified_files)
        self.assertEqual((source / "fonts" / "gamefont.css").read_text(encoding="utf-8"), source_css)
        candidate_css = (output / "fonts" / "gamefont.css").read_text(encoding="utf-8")
        self.assertIn('src: url("SourceHanSans.ttf")', candidate_css)
        self.assertNotIn("font-size", candidate_css)
        self.assertEqual((output / "js" / "rpg_windows.js").read_text(encoding="utf-8"), source_script)
        gate = run_rpg_maker_style_hard_gate(
            source, output, "rpg_maker_mv", (font,)
        )
        self.assertTrue(gate.passed)
        verified = adapter.verify(
            VerifyRequest(
                extracted.source_tree_fingerprint,
                output,
                built.manifest,
                "full",
                make_context("verify"),
            )
        )
        self.assertIsInstance(verified, VerifyResult)
        self.assertTrue(verified.passed)

        (output / "js" / "rpg_windows.js").write_text(
            source_script + "// font size override\n", encoding="utf-8"
        )
        blocked = run_rpg_maker_style_hard_gate(
            source, output, "rpg_maker_mv", (font,)
        )
        self.assertFalse(blocked.passed)
        self.assertIn("rpg_maker_typography_scripts_preserved", blocked.failed_codes)

    def test_rpg_maker_mz_style_build_updates_native_main_font_setting(self):
        source = self.root / "rpg-mz-style-project"
        (source / "data").mkdir(parents=True)
        (source / "fonts").mkdir()
        (source / "js").mkdir()
        (source / "img" / "system").mkdir(parents=True)
        (source / "game.rmmzproject").write_text("RPGMZ 1.8.0", encoding="utf-8")
        (source / "data" / "System.json").write_text(
            json.dumps(
                {
                    "gameTitle": "Test Game",
                    "currencyUnit": "G",
                    "armorTypes": [],
                    "elements": [],
                    "equipTypes": [],
                    "skillTypes": [],
                    "weaponTypes": [],
                    "terms": {"basic": [], "commands": [], "params": [], "messages": {}},
                    "advanced": {"mainFontFilename": "mplus-2m-regular.woff"},
                }
            ),
            encoding="utf-8",
        )
        (source / "js" / "rmmz_windows.js").write_text(
            "Window_Base.prototype.resetFontSettings = function() {};\n", encoding="utf-8"
        )
        (source / "img" / "system" / "Window.png").write_bytes(b"source-window-skin")
        font = self.root / "FusionPixel.ttf"
        font.write_bytes(b"cjk-font")
        adapter = RpgMakerMZAdapterV1()
        working = self.root / "rpg-mz-style-working"
        working.mkdir()
        extracted = adapter.extract(
            ExtractRequest(source, working, (), (), "rpg-mz-style", make_context("extract"))
        )
        self.assertIsInstance(extracted, ExtractResult)
        translated = tuple(
            replace(
                Segment.from_draft("rpg-mz-style", "zh-CN", draft),
                target_text={"Test Game": "\u6d4b\u8bd5\u6e38\u620f", "G": "\u91d1"}[draft.source_text],
                translation_source="test",
            )
            for draft in extracted.segments
        )
        output = self.root / "rpg-mz-style-output"

        built = adapter.build(
            BuildRequest(
                source,
                output,
                translated,
                extracted.source_tree_fingerprint,
                {"rpg_maker_font_paths": [str(font)]},
                make_context("build"),
            )
        )

        self.assertIsInstance(built, BuildResult)
        system = json.loads((output / "data" / "System.json").read_text(encoding="utf-8"))
        self.assertEqual(system["gameTitle"], "\u6d4b\u8bd5\u6e38\u620f")
        self.assertEqual(system["advanced"]["mainFontFilename"], "FusionPixel.ttf")
        self.assertIn("fonts/FusionPixel.ttf", built.added_files)
        gate = run_rpg_maker_style_hard_gate(
            source, output, "rpg_maker_mz", (font,)
        )
        self.assertTrue(gate.passed)
        verified = adapter.verify(
            VerifyRequest(
                extracted.source_tree_fingerprint,
                output,
                built.manifest,
                "full",
                make_context("verify"),
            )
        )
        self.assertIsInstance(verified, VerifyResult)
        self.assertTrue(verified.passed)

    def test_v1_adapters_do_not_replace_legacy_detection_registry(self):
        legacy = get_adapters()
        self.assertFalse(any(type(adapter).__name__.endswith("AdapterV1") for adapter in legacy))

    def test_renpy_extract_validate_build_verify_round_trip(self):
        source = self.root / "renpy-project"
        game = source / "game"
        game.mkdir(parents=True)
        source_script = game / "script.rpy"
        source_script.write_text(
            'label start:\n    e "Hello, [name]!"\n    "Start game"\n',
            encoding="utf-8",
        )
        adapter = RenPyAdapterV1()
        working = self.root / "renpy-working"
        working.mkdir()
        extracted = adapter.extract(
            ExtractRequest(
                source,
                working,
                ("utf-8",),
                (),
                "project-renpy",
                make_context("extract"),
            )
        )
        self.assertIsInstance(extracted, ExtractResult)
        originals = tuple(
            Segment.from_draft("project-renpy", "zh-CN", draft)
            for draft in extracted.segments
        )
        translations = {
            "Hello, [name]!": "你好，[name]！",
            "Start game": "开始游戏",
        }
        translated = tuple(
            replace(
                segment,
                target_text=translations[segment.source_text],
                translation_source="test",
            )
            for segment in originals
        )
        validation = adapter.validate(
            ValidationRequest(
                extracted.source_tree_fingerprint,
                originals,
                translated,
                "utf-8",
                {},
                make_context("validate"),
            )
        )
        self.assertIsInstance(validation, ValidationResult)
        self.assertTrue(validation.valid)

        output = self.root / "renpy-output"
        before = snapshot_tree(source)
        built = adapter.build(
            BuildRequest(
                source,
                output,
                translated,
                extracted.source_tree_fingerprint,
                {},
                make_context("build"),
            )
        )
        self.assertIsInstance(built, BuildResult)
        self.assertEqual(snapshot_tree(source), before)
        self.assertEqual(
            built.generated_files,
            (
                "game/tl/zh_cn/hanengine_translations.rpy",
                "game/hanengine_language.rpy",
            ),
        )
        self.assertEqual((output / "game" / "script.rpy").read_bytes(), source_script.read_bytes())
        generated = output / "game" / "tl" / "zh_cn" / "hanengine_translations.rpy"
        self.assertIn("你好", generated.read_text(encoding="utf-8"))
        activation = output / "game" / "hanengine_language.rpy"
        self.assertIn(
            'define config.default_language = "zh_cn"',
            activation.read_text(encoding="utf-8"),
        )

        verified = adapter.verify(
            VerifyRequest(
                extracted.source_tree_fingerprint,
                output,
                built.manifest,
                "full",
                make_context("verify"),
            )
        )
        self.assertIsInstance(verified, VerifyResult)
        self.assertTrue(verified.passed)
        self.assertTrue(verified.syntax_passed)
        self.assertIsNone(verified.smoke_test_passed)

        incomplete = adapter.verify(
            VerifyRequest(
                extracted.source_tree_fingerprint,
                output,
                built.manifest[:1],
                "full",
                make_context("verify-incomplete"),
            )
        )
        self.assertIsInstance(incomplete, VerifyResult)
        self.assertFalse(incomplete.passed)

    def test_renpy_extract_warns_when_dynamic_expressions_are_preserved(self):
        source = self.root / "renpy-dynamic"
        game = source / "game"
        game.mkdir(parents=True)
        script = game / "screens.rpy"
        script.write_text(
            'screen sample:\n    text _("Visible")\n    $ value = _(dynamic_label)\n',
            encoding="utf-8",
        )
        before = snapshot_tree(source)
        working = self.root / "renpy-dynamic-working"
        working.mkdir()

        result = RenPyAdapterV1().extract(
            ExtractRequest(
                source,
                working,
                (),
                (),
                "project-renpy-dynamic",
                make_context("extract"),
            )
        )

        self.assertIsInstance(result, ExtractResult)
        self.assertEqual([item.source_text for item in result.segments], ["Visible"])
        self.assertEqual(result.statistics["unhandled_items"], 1)
        self.assertTrue(any("manual review" in item for item in result.warnings))
        self.assertEqual(snapshot_tree(source), before)

    def test_renpy_validation_preserves_nested_interpolation_and_tag_order(self):
        source = self.root / "renpy-placeholders"
        game = source / "game"
        game.mkdir(parents=True)
        (game / "script.rpy").write_text(
            'label start:\n    e "Stats{#stats}: {color=#f00}[inventory[0][\'name\']!q]{/color}"\n',
            encoding="utf-8",
        )
        adapter = RenPyAdapterV1()
        working = self.root / "renpy-placeholders-working"
        working.mkdir()
        extracted = adapter.extract(
            ExtractRequest(source, working, (), (), "project-renpy-placeholders", make_context("extract"))
        )
        self.assertIsInstance(extracted, ExtractResult)
        self.assertEqual(
            extracted.segments[0].metadata["segment_v2"],
            {
                "schema_version": 2,
                "placeholders": ["{#stats}", "{color=#f00}", "[inventory[0]['name']!q]", "{/color}"],
                "text_tags": ["{#stats}", "{color=#f00}", "{/color}"],
                "line_breaks": [],
                "context": {
                    "speaker": "e",
                    "kind": "dialogue",
                    "text_context": "stats",
                    "before": [],
                    "after": [],
                },
            },
        )
        originals = tuple(
            Segment.from_draft("project-renpy-placeholders", "zh-CN", draft)
            for draft in extracted.segments
        )
        self.assertEqual(
            originals[0].placeholders,
            ("{#stats}", "{color=#f00}", "[inventory[0]['name']!q]", "{/color}"),
        )

        def validate(target_text: str) -> ValidationResult:
            result = adapter.validate(
                ValidationRequest(
                    extracted.source_tree_fingerprint,
                    originals,
                    (
                        replace(
                            originals[0],
                            target_text=target_text,
                            translation_source="test",
                        ),
                    ),
                    "utf-8",
                    {},
                    make_context("validate"),
                )
            )
            self.assertIsInstance(result, ValidationResult)
            return result

        self.assertTrue(
            validate("统计{#stats}：{color=#f00}[inventory[0]['name']!q]{/color}").valid
        )
        for invalid in (
            "统计{#stats}：{color=#f00}[inventory[1]['name']!q]{/color}",
            "统计{#stats}：{/color}[inventory[0]['name']!q]{color=#f00}",
        ):
            with self.subTest(invalid=invalid):
                result = validate(invalid)
                self.assertFalse(result.valid)
                self.assertIn("placeholder_mismatch", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
