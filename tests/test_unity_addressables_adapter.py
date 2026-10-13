from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from game_localizer.adapters import UnityAdapterV1
from game_localizer.adapters.contract import (
    AdapterCapability,
    AdapterMaturity,
    BuildRequest,
    BuildResult,
    DeclaredMode,
    DetectionRequest,
    ExtractRequest,
    ExtractResult,
    Operation,
    VerifyRequest,
    VerifyResult,
)
from game_localizer.adapters.unity_addressables import (
    UnityAddressablesAdapterV1,
    _AddressablesLayout,
    _AddressablesProfile,
    _TableRecord,
    _fingerprint,
    _profile,
    _update_catalog,
)
from game_localizer.hanengine.routing import RiskLevel
from game_localizer.hanengine.segments import Segment
from game_localizer.hanengine.tasks import TaskContext, TaskControl
from game_localizer.hanengine import AdapterRuntimeV1, HanCore, HanGuard, HanStore, RouteOperation
from tests.adapter_contract_v1 import snapshot_tree


def make_context(step_id: str) -> TaskContext:
    return TaskContext("addressables-test", step_id, TaskControl(), lambda *args: None)


class UnityAddressablesAdapterTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name).resolve()
        self.source = self.root / "game"
        self.data = self.source / "Sample_Data"
        self.aa_root = self.data / "StreamingAssets" / "aa"
        self.platform = self.aa_root / "StandaloneWindows64"
        self.platform.mkdir(parents=True)
        self.english = self.platform / "localization-string-tables-english_assets_all.bundle"
        self.chinese = self.platform / "localization-string-tables-chinese(simplified)_assets_all.bundle"
        self.catalog = self.aa_root / "catalog.bin"
        self.english.write_bytes(b"english-source-bundle")
        self.chinese.write_bytes(b"chinese-source-bundle")
        self.catalog.write_bytes(b"catalog-source")
        (self.source / "UnityPlayer.dll").write_bytes(b"player")

    def _profile(self, root: Path) -> _AddressablesProfile:
        root = root.resolve(strict=True)
        data = root / "Sample_Data"
        aa_root = data / "StreamingAssets" / "aa"
        platform = aa_root / "StandaloneWindows64"
        english = platform / self.english.name
        chinese = platform / self.chinese.name
        catalog = aa_root / "catalog.bin"

        def records(bundle: Path, default: str, object_path_id: int):
            try:
                values = json.loads(bundle.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                values = [{"table": "Menu", "id": 7, "text": default}]
            return tuple(
                _TableRecord(item["table"], item["id"], item["text"], object_path_id, index)
                for index, item in enumerate(values)
            )

        files = tuple(path.relative_to(root).as_posix() for path in (english, chinese, catalog))
        digest = hashlib.sha256()
        for relative in sorted(files):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256((root / relative).read_bytes()).digest())
            digest.update(b"\n")
        return _AddressablesProfile(
            _AddressablesLayout(aa_root, english, chinese, catalog),
            files,
            records(english, "Start", 101),
            records(chinese, "Start", 102),
            digest.hexdigest(),
        )

    def _detection(self):
        return DetectionRequest(
            self.source,
            DeclaredMode.PLAYER,
            "addressables-game",
            RiskLevel.H1_OFFLINE,
            frozenset({Operation.DETECT}),
            make_context("detect"),
        )

    def test_find_layout_requires_exact_english_chinese_bundles_and_catalog(self):
        adapter = UnityAddressablesAdapterV1()
        profile = self._profile(self.source)
        from game_localizer.adapters.unity_addressables import _find_layout

        found = _find_layout(self.source)
        self.assertIsNotNone(found)
        self.assertEqual(found.english_bundle, profile.layout.english_bundle)
        self.assertEqual(found.chinese_bundle, profile.layout.chinese_bundle)

        self.chinese.rename(self.platform / "localization-string-tables-japanese.bundle")
        self.assertIsNone(_find_layout(self.source))
        unsupported = adapter.detect(self._detection())
        self.assertTrue(unsupported.matched)
        self.assertIs(unsupported.maturity, AdapterMaturity.DETECT_ONLY)

    def test_profile_requires_matching_table_ids_and_catalog_bundle_crcs(self):
        english_crc = 0x11223344
        chinese_crc = 0x55667788
        self.catalog.write_bytes(english_crc.to_bytes(4, "little") + chinese_crc.to_bytes(4, "little"))

        def read_records(bundle: Path, _suffix: str):
            text = "Start" if bundle == self.english else "开始"
            return (_TableRecord("Menu", 7, text, 101, 0),)

        with (
            patch("game_localizer.adapters.unity_addressables._read_tables", side_effect=read_records),
            patch(
                "game_localizer.adapters.unity_addressables._bundle_crc",
                side_effect=lambda bundle: english_crc if bundle == self.english else chinese_crc,
            ),
        ):
            profile = _profile(self.source)

        self.assertIsNotNone(profile)
        self.assertEqual(len(profile.english_records), 1)
        self.assertEqual(profile.project_fingerprint, _fingerprint(self.source, profile.files))

        self.catalog.write_bytes(english_crc.to_bytes(4, "little"))
        with (
            patch("game_localizer.adapters.unity_addressables._read_tables", side_effect=read_records),
            patch(
                "game_localizer.adapters.unity_addressables._bundle_crc",
                side_effect=lambda bundle: english_crc if bundle == self.english else chinese_crc,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "one unambiguous CRC reference"):
                _profile(self.source)

    def test_update_catalog_changes_only_one_unambiguous_crc_reference(self):
        old_crc = 0x11223344
        new_crc = 0x55667788
        original = b"prefix" + old_crc.to_bytes(4, "little") + b"middle"
        self.catalog.write_bytes(original)
        candidate_catalog = self.root / "candidate-catalog.bin"
        candidate_catalog.write_bytes(original)
        candidate_chinese = self.root / "candidate-chinese.bundle"
        candidate_chinese.write_bytes(b"candidate bundle")

        with patch(
            "game_localizer.adapters.unity_addressables._bundle_crc",
            side_effect=lambda bundle: old_crc if bundle == self.chinese else new_crc,
        ):
            _update_catalog(
                self.catalog,
                candidate_catalog,
                (self.chinese,),
                (candidate_chinese,),
            )

        expected = b"prefix" + new_crc.to_bytes(4, "little") + b"middle"
        self.assertEqual(candidate_catalog.read_bytes(), expected)

        self.catalog.write_bytes(original + b"duplicate:" + old_crc.to_bytes(4, "little"))
        candidate_catalog.write_bytes(self.catalog.read_bytes())
        with patch(
            "game_localizer.adapters.unity_addressables._bundle_crc",
            side_effect=lambda bundle: old_crc if bundle == self.chinese else new_crc,
        ):
            with self.assertRaisesRegex(ValueError, "one unambiguous CRC reference"):
                _update_catalog(
                    self.catalog,
                    candidate_catalog,
                    (self.chinese,),
                    (candidate_chinese,),
                )

    def test_profile_rejects_mismatched_english_and_chinese_entry_ids(self):
        self.catalog.write_bytes((1).to_bytes(4, "little") + (2).to_bytes(4, "little"))

        def read_records(bundle: Path, _suffix: str):
            entry_id = 7 if bundle == self.english else 8
            return (_TableRecord("Menu", entry_id, "Text", 101, 0),)

        with (
            patch("game_localizer.adapters.unity_addressables._read_tables", side_effect=read_records),
            patch(
                "game_localizer.adapters.unity_addressables._bundle_crc",
                side_effect=lambda bundle: 1 if bundle == self.english else 2,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "different entry IDs"):
                _profile(self.source)

    def test_missing_catalog_crc_keeps_packaged_detection_only(self):
        def read_records(bundle: Path, _suffix: str):
            text = "Start" if bundle == self.english else "开始"
            return (_TableRecord("Menu", 7, text, 101, 0),)

        with (
            patch("game_localizer.adapters.unity_addressables._read_tables", side_effect=read_records),
            patch(
                "game_localizer.adapters.unity_addressables._bundle_crc",
                side_effect=lambda bundle: 1 if bundle == self.english else 2,
            ),
        ):
            detected = UnityAdapterV1().detect(self._detection())

        self.assertTrue(detected.matched)
        self.assertIs(detected.maturity, AdapterMaturity.DETECT_ONLY)
        self.assertEqual(detected.capabilities, frozenset({AdapterCapability.DETECT}))

    def test_unknown_packaged_layout_remains_detect_only(self):
        with patch("game_localizer.adapters.unity_addressables._profile", return_value=None):
            result = UnityAdapterV1().detect(self._detection())

        self.assertTrue(result.matched)
        self.assertIs(result.maturity, AdapterMaturity.DETECT_ONLY)
        self.assertEqual(result.capabilities, frozenset({AdapterCapability.DETECT}))

    def test_supported_profile_opens_player_capabilities_and_extracts_stable_segments(self):
        with patch.object(UnityAddressablesAdapterV1, "_supported_profile", side_effect=self._profile):
            adapter = UnityAdapterV1()
            detected = adapter.detect(self._detection())
            working = self.root / "working"
            working.mkdir()
            extracted = adapter.extract(
                ExtractRequest(
                    self.source,
                    working,
                    (),
                    (),
                    "addressables-game",
                    make_context("extract"),
                )
            )

        self.assertTrue(detected.matched)
        self.assertIs(detected.maturity, AdapterMaturity.BUILD_READY)
        self.assertIn(AdapterCapability.EXTRACT, detected.capabilities)
        self.assertIsInstance(extracted, ExtractResult)
        self.assertEqual(len(extracted.segments), 1)
        self.assertEqual(extracted.segments[0].source_text, "Start")
        self.assertEqual(extracted.segments[0].source_location.relative_path, self.english.relative_to(self.source).as_posix())
        self.assertEqual(extracted.segments[0].metadata["kind"], "unity_addressables_string")

    def test_hanguard_and_adapter_runtime_allow_supported_player_extraction(self):
        project_id = "819c49a1-509a-4333-9f22-0b67c974cb42"
        store = HanStore(self.root / "state")
        self.addCleanup(store.close)
        store.create_project("Addressables runtime fixture", source_root=self.source, project_id=project_id)
        project = store.open_project(project_id)
        self.addCleanup(project.close)
        runtime = AdapterRuntimeV1(HanCore(project), HanGuard(()))

        with patch.object(UnityAddressablesAdapterV1, "_supported_profile", side_effect=self._profile):
            selection = runtime.detect(
                self.source,
                DeclaredMode.PLAYER,
                user_baseline=RiskLevel.H1_OFFLINE,
                adapter_baseline=RiskLevel.H1_OFFLINE,
            )

        self.assertIs(selection.detection.maturity, AdapterMaturity.BUILD_READY)
        self.assertIn(RouteOperation.EXTRACT, selection.final_route.allowed_operations)
        working = self.root / "runtime-working"
        working.mkdir()
        with patch.object(UnityAddressablesAdapterV1, "_supported_profile", side_effect=self._profile):
            execution = runtime.run_operation(
                selection,
                Operation.EXTRACT,
                lambda context: ExtractRequest(
                    self.source,
                    working,
                    (),
                    (),
                    project_id,
                    context,
                ),
                target_language="zh-CN",
            )

        self.assertIsInstance(execution.result, ExtractResult)
        self.assertEqual(len(execution.ingested_segments), 1)
        self.assertEqual(execution.ingested_segments[0].source_text, "Start")

    def test_build_and_verify_preserve_english_and_read_back_chinese_table(self):
        source_before = snapshot_tree(self.source)
        adapter = UnityAdapterV1()
        with patch.object(UnityAddressablesAdapterV1, "_supported_profile", side_effect=self._profile):
            working = self.root / "working"
            working.mkdir()
            extracted = adapter.extract(
                ExtractRequest(
                    self.source,
                    working,
                    (),
                    (),
                    "addressables-game",
                    make_context("extract"),
                )
            )
        self.assertIsInstance(extracted, ExtractResult)
        translated = tuple(
            replace(
                Segment.from_draft("addressables-game", "zh-CN", draft),
                target_text="开始",
                translation_source="test-provider",
            )
            for draft in extracted.segments
        )
        candidate = self.root / "candidate"

        def write_translations(bundle, _suffix, translations, _context, **_progress):
            bundle.write_text(
                json.dumps(
                    [
                        {"table": table, "id": entry_id, "text": value}
                        for (table, entry_id), value in translations.items()
                    ]
                ),
                encoding="utf-8",
            )
            return len(translations)

        def update_catalog(_source_catalog, candidate_catalog, _source_bundles, _candidate_bundles):
            candidate_catalog.write_bytes(b"catalog-updated")

        with (
            patch.object(UnityAddressablesAdapterV1, "_supported_profile", side_effect=self._profile),
            patch("game_localizer.adapters.unity_addressables._profile", side_effect=self._profile),
            patch("game_localizer.adapters.unity_addressables._replace_bundle", side_effect=write_translations),
            patch("game_localizer.adapters.unity_addressables._update_catalog", side_effect=update_catalog),
        ):
            built = adapter.build(
                BuildRequest(
                    self.source,
                    candidate,
                    translated,
                    extracted.source_tree_fingerprint,
                    {},
                    make_context("build"),
                )
            )
            self.assertIsInstance(built, BuildResult)
            verified = adapter.verify(
                VerifyRequest(
                    extracted.source_tree_fingerprint,
                    candidate,
                    built.manifest,
                    "full",
                    make_context("verify"),
                )
            )

        self.assertIsInstance(verified, VerifyResult)
        self.assertTrue(verified.passed)
        self.assertEqual(len(built.modified_files), 2)
        self.assertEqual(built.statistics["english_entries_preserved"], 1)
        self.assertEqual(built.statistics["chinese_entries"], 1)
        self.assertEqual(snapshot_tree(self.source), source_before)
        self.assertEqual(self.english.read_bytes(), b"english-source-bundle")
        self.assertEqual(self.chinese.read_bytes(), b"chinese-source-bundle")
        candidate_english = candidate / self.english.relative_to(self.source)
        candidate_chinese = candidate / self.chinese.relative_to(self.source)
        self.assertEqual(
            candidate_english.read_bytes(),
            self.english.read_bytes(),
        )
        self.assertEqual(
            json.loads(candidate_chinese.read_text(encoding="utf-8"))[0]["text"],
            "开始",
        )


if __name__ == "__main__":
    unittest.main()
