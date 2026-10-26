from __future__ import annotations

import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from game_localizer.hanengine.multiengine import LocalizationCatalog, LocalizationEntry


# The candidate builder is tested with fake bundles, so it does not need UnityPy.
_unitypy_stub = types.ModuleType("UnityPy")
with patch.dict(sys.modules, {"UnityPy": _unitypy_stub}):
    from tools import unity_addressables_localize as unity_tool


class UnityAddressablesLocalizeTests(unittest.TestCase):
    def test_build_translates_only_simplified_chinese_bundle(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "game"
            bundle_directory = (
                source
                / "How to Fish_Data"
                / "StreamingAssets"
                / "aa"
                / "StandaloneWindows64"
            )
            bundle_directory.mkdir(parents=True)
            english = bundle_directory / "localization-string-tables-english(en)_assets_all.bundle"
            chinese = bundle_directory / "localization-string-tables-chinese(simplified)(zh-cn)_assets_all.bundle"
            catalog_file = bundle_directory.parent / "catalog.bin"
            english.write_bytes(b"english-source")
            chinese.write_bytes(b"chinese-source")
            catalog_file.write_bytes(b"catalog-source")

            entry = LocalizationEntry(
                segment_id="unity-addressables:1",
                relative_path=english.relative_to(source).as_posix(),
                source_text="Start",
                source_hash=hashlib.sha256(b"Start").hexdigest(),
                kind="unity_addressables_string",
                locator={"table_name": "Menu", "entry_id": 1},
                target_text="开始",
            )
            catalog = LocalizationCatalog(
                engine_id="unity_addressables",
                language="zh-CN",
                source_language="en",
                project_fingerprint="source-fingerprint",
                files=(entry.relative_path,),
                entries=(entry,),
            )
            candidate = root / "candidate"
            replaced_bundles: list[str] = []
            crc_bundle_pairs: list[tuple[Path, Path]] = []

            def replace_bundle(bundle: Path, translations: dict[tuple[str, int], str]) -> int:
                replaced_bundles.append(bundle.name)
                bundle.write_bytes(b"translated-chinese")
                return len(translations)

            def update_catalog_crcs(
                _project: Path,
                output: Path,
                bundles: tuple[tuple[Path, Path], ...],
            ) -> dict[str, object]:
                crc_bundle_pairs.extend(bundles)
                (output / "How to Fish_Data" / "StreamingAssets" / "aa" / "catalog.bin").write_bytes(
                    b"catalog-updated"
                )
                return {"catalog": "How to Fish_Data/StreamingAssets/aa/catalog.bin", "updates": []}

            with (
                patch.object(unity_tool, "_replace_bundle", side_effect=replace_bundle),
                patch.object(unity_tool, "_update_catalog_crcs", side_effect=update_catalog_crcs),
            ):
                report = unity_tool.build_candidate(source, candidate, catalog)

            candidate_english = candidate / english.relative_to(source)
            candidate_chinese = candidate / chinese.relative_to(source)
            self.assertEqual(replaced_bundles, [chinese.name])
            self.assertEqual(candidate_english.read_bytes(), english.read_bytes())
            self.assertEqual(candidate_chinese.read_bytes(), b"translated-chinese")
            self.assertEqual(crc_bundle_pairs, [(chinese, candidate_chinese)])
            self.assertEqual(report["changed_bundles"], [chinese.name])
            self.assertEqual(report["changed_entries"], {chinese.name: 1})


if __name__ == "__main__":
    unittest.main()
