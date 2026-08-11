from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import cli
from game_localizer.hanengine.visual_evidence import (
    CommandImageVisualJudge,
    VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION,
    VisualEvidenceError,
    VisualEvidenceManifest,
    load_visual_evidence_manifest,
    prepare_visual_evidence_manifest,
    run_visual_evidence,
)
from game_localizer.hanengine.visual_style import VisualGateDecision


HASH_A = "a" * 64
HASH_B = "b" * 64


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def _png(width: int, height: int, value: int) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes((value, value, value)) * width
    image = zlib.compress(row * height)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", image) + _png_chunk(b"IEND", b"")


class FakeImageJudge:
    provider_name = "fake-images"

    def __init__(self):
        self.calls = 0

    def judge_images(self, profile, comparison, reference_image, candidate_image):
        self.calls += 1
        raise AssertionError("hard-gate failures must not call the image judge")


class VisualEvidenceTests(unittest.TestCase):
    def manifest(self, *, missing=(), candidate_width=20):
        region = {
            "region_id": "primary-action",
            "x": 1,
            "y": 2,
            "width": 10,
            "height": 5,
            "line_count": 1,
            "baseline": 4,
            "font_resolved": True,
            "missing_codepoints": [],
            "overflow": False,
            "clipped": False,
        }
        candidate = dict(region)
        candidate["width"] = candidate_width
        candidate["missing_codepoints"] = list(missing)
        return {
            "schema_version": "hanengine.visual-evidence-manifest/v2",
            "profile": {
                "schema_version": 1,
                "profile_id": "menu-ui",
                "engine_id": "renpy",
                "renderer": "renpy-text",
                "source_fingerprint": HASH_A,
                "font_assets": [
                    {
                        "role": "cjk",
                        "relative_path": "fonts/cjk.ttf",
                        "sha256": HASH_B,
                        "codepoint_ranges": ["U+4E00-U+9FFF"],
                    }
                ],
                "metrics": {
                    "point_size": 28,
                    "line_height": 34,
                    "baseline": 26,
                    "letter_spacing": 0,
                    "horizontal_scale": 1,
                    "outline_width": 0,
                    "shadow_offset": [0, 0],
                },
                "material_parameters": {"outline": 0},
                "scenarios": ["main-menu"],
            },
            "policy": {
                "max_position_delta_px": 2,
                "max_size_delta_px": 12,
                "max_baseline_delta_px": 2,
                "max_line_count_delta": 1,
                "require_font_resolution": True,
            },
            "samples": [
                {
                    "sample_id": "main-menu",
                    "reference_image": "reference/main-menu.png",
                    "candidate_image": "candidate/main-menu.png",
                    "observation_source": "manual",
                    "observation_reference": "annotations.json",
                    "reference_regions": [region],
                    "candidate_regions": [candidate],
                }
            ],
        }

    def write_fixture(self, root: Path, payload=None, *, candidate_size=(32, 18)) -> Path:
        (root / "reference").mkdir()
        (root / "candidate").mkdir()
        (root / "reference" / "main-menu.png").write_bytes(_png(32, 18, 32))
        (root / "candidate" / "main-menu.png").write_bytes(
            _png(candidate_size[0], candidate_size[1], 224)
        )
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(payload or self.manifest(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest

    def write_preparation_fixture(
        self,
        root: Path,
        *,
        semantic_alignment=True,
        candidate_size=(32, 18),
        missing_regions=False,
        spoofed_source=False,
    ):
        self.write_fixture(root, candidate_size=candidate_size)
        reference_bytes = _png(32, 18, 32)
        candidate_bytes = _png(candidate_size[0], candidate_size[1], 224)

        def variant(name, image_bytes, size, source_hash):
            assertion_passed = semantic_alignment
            expected_screen = "main_menu"
            return {
                "returncode": 1,
                "screen_assertions": [
                    {
                        "expected_screen": expected_screen,
                        "observed_screens": [expected_screen] if assertion_passed else ["say"],
                        "passed": assertion_passed,
                        "sample_id": "main-menu",
                    }
                ],
                "screenshots": [
                    {
                        "height": size[1],
                        "relative_path": f"{name}/main-menu.png",
                        "sample_id": "main-menu",
                        "sha256": hashlib.sha256(image_bytes).hexdigest(),
                        "width": size[0],
                    }
                ],
                "source_preserved": True,
                "source_tree_sha256": source_hash,
                "status": "passed",
                "stderr_bytes": 0,
                "stdout_bytes": 0,
                "traceback_present": False,
                "variant": name,
                "window_geometry": [0, 0, size[0], size[1]],
            }

        capture_report = {
            "authorization_reference": "repository-owned-test-fixture",
            "candidate": variant("candidate", candidate_bytes, candidate_size, HASH_B),
            "capture_passed": True,
            "created_at": "2026-08-11T00:00:00Z",
            "passed": semantic_alignment,
            "plan_schema_version": "hanengine.renpy-capture-plan/v2",
            "plan_sha256": HASH_B,
            "reference": variant("reference", reference_bytes, (32, 18), HASH_A),
            "schema_version": "hanengine.renpy-capture-report/v2",
            "semantic_alignment_verified": semantic_alignment,
        }
        capture_path = root / "capture-report.json"
        capture_path.write_text(
            json.dumps(capture_report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        evidence_manifest = self.manifest()
        sample = evidence_manifest["samples"][0]
        annotations = {
            "schema_version": VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION,
            "capture_report_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
            "manual_observation_reference": "repository-owned-test-fixture-review",
            "profile": evidence_manifest["profile"],
            "policy": evidence_manifest["policy"],
            "samples": [
                {
                    "sample_id": "main-menu",
                    "reference_regions": [] if missing_regions else sample["reference_regions"],
                    "candidate_regions": [] if missing_regions else sample["candidate_regions"],
                }
            ],
        }
        if spoofed_source:
            annotations["observation_source"] = "ocr"
        annotations_path = root / "annotations.json"
        annotations_path.write_text(
            json.dumps(annotations, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return capture_path, annotations_path

    def test_manifest_and_report_round_trip_without_embedding_image_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.write_fixture(root)
            output = root / "report.json"

            manifest = load_visual_evidence_manifest(manifest_path)
            report = run_visual_evidence(
                manifest_path,
                output,
                authorization_reference="repository-owned-test-fixture",
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(VisualEvidenceManifest.from_dict(manifest.to_dict()), manifest)
        self.assertEqual(report.decision, VisualGateDecision.ESCALATE)
        self.assertEqual(payload["gate"]["reasons"], ["visual_judge_unavailable"])
        self.assertEqual(payload["images"][0]["width"], 32)
        self.assertEqual(payload["images"][0]["observation_source"], "manual")
        self.assertEqual(payload["images"][0]["observation_reference"], "annotations.json")
        self.assertEqual(
            payload["images"][0]["reference_image_sha256"],
            hashlib.sha256(_png(32, 18, 32)).hexdigest(),
        )
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(str(root), serialized)
        self.assertNotIn("image_bytes", serialized)

    def test_prepare_builds_manual_manifest_from_verified_capture_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture, annotations = self.write_preparation_fixture(root)
            output = root / "prepared-manifest.json"

            manifest = prepare_visual_evidence_manifest(capture, annotations, output)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(len(manifest.samples), 1)
        self.assertEqual(payload["samples"][0]["observation_source"], "manual")
        self.assertEqual(payload["samples"][0]["observation_reference"], "annotations.json")

    def test_prepare_rejects_capture_without_semantic_alignment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture, annotations = self.write_preparation_fixture(root, semantic_alignment=False)

            with self.assertRaisesRegex(VisualEvidenceError, "semantic alignment"):
                prepare_visual_evidence_manifest(capture, annotations, root / "prepared-manifest.json")

    def test_prepare_rejects_different_capture_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture, annotations = self.write_preparation_fixture(root, candidate_size=(31, 18))

            with self.assertRaisesRegex(VisualEvidenceError, "identical dimensions"):
                prepare_visual_evidence_manifest(capture, annotations, root / "prepared-manifest.json")

    def test_prepare_rejects_missing_manual_regions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture, annotations = self.write_preparation_fixture(root, missing_regions=True)

            with self.assertRaisesRegex(VisualEvidenceError, "manual text regions"):
                prepare_visual_evidence_manifest(capture, annotations, root / "prepared-manifest.json")

    def test_prepare_rejects_spoofed_observation_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture, annotations = self.write_preparation_fixture(root, spoofed_source=True)

            with self.assertRaisesRegex(ValueError, "fields"):
                prepare_visual_evidence_manifest(capture, annotations, root / "prepared-manifest.json")

    def test_hard_gate_blocks_before_image_judge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root, self.manifest(missing=("U+4F60",)))
            judge = FakeImageJudge()

            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                judge=judge,
            )

        self.assertEqual(report.decision, VisualGateDecision.BLOCKED)
        self.assertEqual(judge.calls, 0)
        self.assertIn("hard_gate:missing_glyphs", report.gate.reasons)

    def test_command_image_judge_receives_paths_and_can_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            judge_script = root / "judge.py"
            judge_script.write_text(
                "import json, pathlib, sys\n"
                "request = json.load(sys.stdin)\n"
                "assert pathlib.Path(request['reference_image']).is_file()\n"
                "assert pathlib.Path(request['candidate_image']).is_file()\n"
                "json.dump({'decision':'pass','style_score':0.94,'confidence':0.91,'model':'fixture-v1','issues':[]}, sys.stdout)\n",
                encoding="utf-8",
            )
            judge = CommandImageVisualJudge(
                (sys.executable, str(judge_script)),
                provider_name="fixture-command",
            )

            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                judge=judge,
            )

        self.assertEqual(report.decision, VisualGateDecision.PASS)
        self.assertEqual(report.judge_provider, "fixture-command")
        self.assertEqual(report.gate.judge_results[0].model, "fixture-v1")

    def test_runner_rejects_different_image_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root, candidate_size=(31, 18))

            with self.assertRaisesRegex(VisualEvidenceError, "identical dimensions"):
                run_visual_evidence(
                    manifest,
                    root / "report.json",
                    authorization_reference="repository-owned-test-fixture",
                )

    def test_cli_requires_authorization_and_uses_decision_exit_codes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            output = root / "report.json"
            arguments = [
                "verify",
                "--manifest",
                str(manifest),
                "--output",
                str(output),
                "--authorization-reference",
                "repository-owned-test-fixture",
            ]
            stderr = StringIO()
            with redirect_stderr(stderr):
                unauthorized = cli.run_visual(arguments)
            stdout = StringIO()
            with redirect_stdout(stdout):
                escalated = cli.run_visual([*arguments, "--authorized"])

        self.assertEqual(unauthorized, 1)
        self.assertIn("requires explicit", stderr.getvalue())
        self.assertEqual(escalated, 2)
        self.assertIn("Visual decision: escalate", stdout.getvalue())

    def test_prepare_cli_requires_authorization_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture, annotations = self.write_preparation_fixture(root)
            output = root / "prepared-manifest.json"
            arguments = [
                "prepare",
                "--capture-report",
                str(capture),
                "--annotations",
                str(annotations),
                "--output",
                str(output),
            ]
            stderr = StringIO()
            with redirect_stderr(stderr):
                unauthorized = cli.run_visual(arguments)
            stdout = StringIO()
            with redirect_stdout(stdout):
                prepared = cli.run_visual([*arguments, "--authorized"])

            self.assertEqual(unauthorized, 1)
            self.assertIn("requires explicit", stderr.getvalue())
            self.assertEqual(prepared, 0)
            self.assertTrue(output.is_file())
            self.assertIn("Prepared samples: 1", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
