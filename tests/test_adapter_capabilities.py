import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters import get_adapters_v1
from game_localizer.adapters.contract import (
    AdapterCapability,
    AdapterCapabilityMatrix,
    CapabilityArea,
    CapabilityDeclaration,
    CapabilityStatus,
)


ROOT = Path(__file__).resolve().parents[1]


class AdapterCapabilityContractTests(unittest.TestCase):
    def test_builtins_expose_all_capability_areas_in_canonical_order(self):
        expected = tuple(CapabilityArea)
        adapters = get_adapters_v1()
        self.assertEqual(len(adapters), 6)
        for adapter in adapters:
            matrix = adapter.metadata.capability_matrix
            self.assertEqual(
                tuple(item.capability for item in matrix.declarations),
                expected,
            )
            self.assertEqual(matrix.schema_version, "hanengine.adapter-capabilities/v1")

        verified_evidence = {
            "renpy": {
                "record-renpy-the-question-zhcn-client-language-v11-verified",
                "record-heartfelt-moments-pristine-validation-final",
            },
            "godot": {"godot-dodge-the-creeps-v1"},
        }
        for adapter in adapters:
            native = next(
                item
                for item in adapter.metadata.capability_matrix.declarations
                if item.capability is CapabilityArea.NATIVE_TEXT_REPLACE
            )
            if adapter.engine_id in verified_evidence:
                self.assertIs(native.status, CapabilityStatus.VERIFIED)
                self.assertEqual(set(native.evidence), verified_evidence[adapter.engine_id])
                continue
            self.assertIs(native.status, CapabilityStatus.IMPLEMENTED)
        for adapter in adapters:
            raster = next(
                item
                for item in adapter.metadata.capability_matrix.declarations
                if item.capability is CapabilityArea.RASTER_TEXT
            )
            self.assertIs(raster.status, CapabilityStatus.IMPLEMENTED)
            self.assertEqual(raster.evidence, ())

    def test_matrix_and_metadata_have_strict_json_round_trip(self):
        adapter = next(item for item in get_adapters_v1() if item.engine_id == "renpy")
        matrix = adapter.metadata.capability_matrix
        encoded = json.dumps(matrix.to_dict(), ensure_ascii=False, sort_keys=True)
        decoded = AdapterCapabilityMatrix.from_dict(json.loads(encoded))
        self.assertEqual(decoded, matrix)

        metadata = adapter.metadata
        metadata_encoded = json.dumps(metadata.to_dict(), ensure_ascii=False, sort_keys=True)
        self.assertEqual(
            type(metadata).from_dict(json.loads(metadata_encoded)).to_dict(),
            metadata.to_dict(),
        )
        with self.assertRaises(ValueError):
            AdapterCapabilityMatrix.from_dict(
                {**matrix.to_dict(), "unexpected": True}
            )

    def test_verified_requires_evidence_and_detection_only_downgrades_write_claims(self):
        with self.assertRaises(ValueError):
            CapabilityDeclaration(
                CapabilityArea.NATIVE_TEXT_REPLACE,
                CapabilityStatus.VERIFIED,
                "missing evidence",
            )
        adapter = next(item for item in get_adapters_v1() if item.engine_id == "renpy")
        detected = adapter.metadata.capability_matrix.for_detection(
            frozenset({AdapterCapability.DETECT})
        )
        statuses = {item.capability: item.status for item in detected.declarations}
        self.assertIs(
            statuses[CapabilityArea.NATIVE_TEXT_REPLACE],
            CapabilityStatus.DETECT_ONLY,
        )
        self.assertIs(
            statuses[CapabilityArea.RASTER_TEXT],
            CapabilityStatus.DETECT_ONLY,
        )
        self.assertIs(
            statuses[CapabilityArea.DETECT_ONLY],
            CapabilityStatus.IMPLEMENTED,
        )

    def test_engines_cli_returns_the_same_matrix(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "cli.py"), "engines", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(
            payload[0]["capability_matrix"]["schema_version"],
            "hanengine.adapter-capabilities/v1",
        )
        for item in payload:
            self.assertEqual(len(item["capability_matrix"]["capabilities"]), 4)

    def test_engine_inspect_returns_detection_adjusted_matrix(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as state:
            root = Path(directory)
            (root / "game").mkdir()
            (root / "game" / "script.rpy").write_text("label start:\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "cli.py"),
                    "engine",
                    "inspect",
                    "renpy",
                    str(root),
                    "--json",
                    "--mode",
                    "studio",
                    "--state-root",
                    state,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(
            payload["candidate"]["capability_matrix"],
            payload["capability_matrix"],
        )
        self.assertEqual(
            next(
                item
                for item in payload["capability_matrix"]["capabilities"]
                if item["capability"] == "native_text_replace"
            )["status"],
            "verified",
        )


if __name__ == "__main__":
    unittest.main()
