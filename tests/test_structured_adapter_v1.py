from __future__ import annotations

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
from game_localizer.hanengine.segments import Segment
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
                {
                    "name": "Hero",
                    "events": [
                        {"code": 401, "parameters": ["Hello, {name}!"]},
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
        self.assertEqual(built.modified_files, ("data/Actors.json",))
        localized = json.loads((staging / "data" / "Actors.json").read_text(encoding="utf-8"))
        self.assertEqual(localized["name"], "英雄")
        self.assertEqual(localized["events"][0]["parameters"][0], "你好，{name}!")
        self.assertEqual(json.loads(source_file.read_text(encoding="utf-8"))["name"], "Hero")

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
