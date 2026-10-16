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
from unittest.mock import Mock, patch

import cli
from game_localizer.hanengine.visual import OcrBox, OcrFrame
from game_localizer.hanengine.visual_evidence import (
    CommandImageVisualJudge,
    VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION,
    VisualEvidenceError,
    VisualEvidenceManifest,
    VisualEvidenceReport,
    ZhipuImageVisualJudge,
    load_visual_evidence_manifest,
    prepare_visual_evidence_manifest,
    run_renderer_overlap_hard_gate,
    run_visual_evidence,
)
from game_localizer.hanengine.renpy_visual_capture import (
    RENPY_RENDERER_OBSERVATION_SCHEMA_VERSION,
    RendererObservation,
    RendererTextRegion,
)
from game_localizer.hanengine.visual_style import (
    VisualComparison,
    VisualGateDecision,
    VisualGateResult,
)


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


class FakeOcrProvider:
    provider_name = "fake-ocr"
    provider_version = "1.2.3"

    def __init__(self, reference: OcrFrame, candidate: OcrFrame):
        self.reference = reference
        self.candidate = candidate

    def recognize(self, image, *, language):
        self.language = language
        return self.candidate if "candidate" in str(image) else self.reference


class VisualEvidenceTests(unittest.TestCase):
    def renderer_region(
        self,
        region_id,
        text,
        x,
        y,
        width,
        height=20,
        *,
        baseline=15,
        render_path=(0,),
        z_index=0,
    ):
        return RendererTextRegion(
            text=text,
            x=x,
            y=y,
            width=width,
            height=height,
            line_count=1,
            baseline=baseline,
            region_id=region_id,
            render_path=render_path,
            z_index=z_index,
        )

    def renderer_observation(self, *regions, viewport=(320, 180)):
        return RendererObservation(
            viewport_width=viewport[0],
            viewport_height=viewport[1],
            text_regions=regions,
            schema_version=RENPY_RENDERER_OBSERVATION_SCHEMA_VERSION,
        )

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
                        "renderer_observation": {
                            "schema_version": "hanengine.renpy-renderer-observation/v1",
                            "coordinate_space": "capture_pixels",
                            "viewport_width": size[0],
                            "viewport_height": size[1],
                            "text_regions": [
                                {
                                    "text": expected_screen,
                                    "x": 1,
                                    "y": 1,
                                    "width": 10,
                                    "height": 8,
                                    "line_count": 1,
                                    "baseline": 6,
                                }
                            ],
                        },
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
            "renderer_observation_verified": True,
            "schema_version": "hanengine.renpy-capture-report/v3",
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
        self.assertEqual(VisualEvidenceReport.from_dict(payload), report)
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

        tampered = json.loads(json.dumps(payload))
        tampered["gate"]["comparisons"][0]["candidate_image_sha256"] = HASH_A
        with self.assertRaisesRegex(ValueError, "image hashes"):
            VisualEvidenceReport.from_dict(tampered)

    def test_manifest_versions_reject_mixed_renderer_shapes(self):
        legacy_with_renderer = self.manifest()
        observation = self.renderer_observation(
            self.renderer_region("title", "开始", 20, 40, 80)
        ).to_dict()
        legacy_with_renderer["samples"][0][
            "reference_renderer_observation"
        ] = observation
        legacy_with_renderer["samples"][0][
            "candidate_renderer_observation"
        ] = observation
        with self.assertRaisesRegex(ValueError, "v2 must not contain"):
            VisualEvidenceManifest.from_dict(legacy_with_renderer)

        current_without_renderer = self.manifest()
        current_without_renderer["schema_version"] = (
            "hanengine.visual-evidence-manifest/v3"
        )
        with self.assertRaisesRegex(ValueError, "v3 requires"):
            VisualEvidenceManifest.from_dict(current_without_renderer)

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
        self.assertEqual(
            payload["samples"][0]["reference_renderer_observation"]["schema_version"],
            "hanengine.renpy-renderer-observation/v1",
        )
        self.assertEqual(
            payload["samples"][0]["candidate_renderer_observation"]["text_regions"][0][
                "text"
            ],
            "main_menu",
        )
        self.assertEqual(VisualEvidenceManifest.from_dict(payload), manifest)

    def test_renderer_overlap_gate_ignores_normal_layout_layers(self):
        parent = self.renderer_region(
            "parent", "设置", 20, 20, 200, 100, render_path=(0,), z_index=0
        )
        child = self.renderer_region(
            "child", "显示", 30, 25, 60, render_path=(0, 1), z_index=1
        )
        shadow = self.renderer_region(
            "shadow", "显示", 31, 26, 60, render_path=(2,), z_index=2
        )
        allowed_left = self.renderer_region(
            "allowed-left", "上一页", 180, 130, 60, render_path=(3,), z_index=3
        )
        allowed_right = self.renderer_region(
            "allowed-right", "下一页", 220, 130, 60, render_path=(4,), z_index=4
        )
        observation = self.renderer_observation(
            parent, child, shadow, allowed_left, allowed_right
        )

        checks = run_renderer_overlap_hard_gate(
            "settings",
            observation,
            observation,
            allowed_pairs=(("allowed-left", "allowed-right"),),
        )

        self.assertTrue(all(check.passed for check in checks))

    def test_renderer_overlap_gate_ignores_unchanged_reference_overlap(self):
        left = self.renderer_region("left", "保存", 40, 50, 80, render_path=(0,), z_index=0)
        right = self.renderer_region("right", "读取", 100, 50, 80, render_path=(1,), z_index=1)
        reference = self.renderer_observation(left, right)
        candidate = self.renderer_observation(
            self.renderer_region("left", "保存", 40, 50, 80, render_path=(0,), z_index=0),
            self.renderer_region("right", "读取", 100, 50, 80, render_path=(1,), z_index=1),
        )

        checks = run_renderer_overlap_hard_gate("save", reference, candidate)

        self.assertTrue(all(check.passed for check in checks))

    def test_renderer_overlap_gate_ignores_different_text_baselines(self):
        reference = self.renderer_observation(
            self.renderer_region("heading", "设置", 20, 20, 200, 100, baseline=15),
            self.renderer_region(
                "option",
                "显示",
                30,
                75,
                180,
                60,
                baseline=45,
                render_path=(1,),
                z_index=1,
            ),
        )

        checks = run_renderer_overlap_hard_gate("settings", reference, reference)

        self.assertTrue(all(check.passed for check in checks))

    def test_renderer_overlap_gate_honors_explicit_allowed_pair(self):
        reference = self.renderer_observation(
            self.renderer_region("left", "Previous", 20, 40, 80, render_path=(0,)),
            self.renderer_region("right", "Next", 120, 40, 80, render_path=(1,), z_index=1),
        )
        candidate = self.renderer_observation(
            self.renderer_region("left", "上一页", 20, 40, 100, render_path=(0,)),
            self.renderer_region("right", "下一页", 90, 40, 100, render_path=(1,), z_index=1),
        )

        checks = run_renderer_overlap_hard_gate(
            "save", reference, candidate, allowed_pairs=(("right", "left"),)
        )

        self.assertTrue(all(check.passed for check in checks))

    def test_renderer_overlap_gate_blocks_new_same_baseline_overlap_with_details(self):
        reference = self.renderer_observation(
            self.renderer_region("left", "开始游戏", 20, 40, 80, render_path=(0,), z_index=0),
            self.renderer_region("right", "读取游戏", 120, 40, 80, render_path=(1,), z_index=1),
        )
        candidate = self.renderer_observation(
            self.renderer_region("left", "开始游戏", 20, 40, 100, render_path=(0,), z_index=0),
            self.renderer_region("right", "读取游戏", 90, 40, 100, render_path=(1,), z_index=7),
        )

        checks = run_renderer_overlap_hard_gate("main-menu", reference, candidate)

        self.assertEqual(len(checks), 1)
        self.assertFalse(checks[0].passed)
        self.assertEqual(checks[0].code, "renderer_text_overlap")
        self.assertEqual(checks[0].details["sample_id"], "main-menu")
        self.assertEqual(checks[0].details["foreground_region_id"], "right")
        self.assertEqual(checks[0].details["regions"][0]["rect"]["x"], 20)
        self.assertGreater(checks[0].details["intersection"]["smaller_region_ratio"], 0.2)
        self.assertEqual(json.loads(json.dumps(checks[0].to_dict())), checks[0].to_dict())

    def test_renderer_overlap_gate_blocks_materially_worsened_reference_overlap(self):
        reference = self.renderer_observation(
            self.renderer_region("left", "保存", 20, 40, 100, render_path=(0,)),
            self.renderer_region("right", "读取", 100, 40, 100, render_path=(1,), z_index=1),
        )
        candidate = self.renderer_observation(
            self.renderer_region("left", "保存", 20, 40, 100, render_path=(0,)),
            self.renderer_region("right", "读取", 70, 40, 100, render_path=(1,), z_index=1),
        )

        checks = run_renderer_overlap_hard_gate("save", reference, candidate)

        self.assertFalse(checks[0].passed)
        self.assertIsNotNone(checks[0].details["reference_intersection"])

    def test_renderer_overlap_gate_blocks_before_image_judge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = self.manifest()
            payload["schema_version"] = "hanengine.visual-evidence-manifest/v3"
            sample = payload["samples"][0]
            sample["reference_renderer_observation"] = self.renderer_observation(
                self.renderer_region("left", "Start", 2, 2, 10, 8, baseline=6, render_path=(0,)),
                self.renderer_region("right", "Load", 20, 2, 10, 8, baseline=6, render_path=(1,), z_index=1),
                viewport=(32, 18),
            ).to_dict()
            sample["candidate_renderer_observation"] = self.renderer_observation(
                self.renderer_region("left", "开始", 2, 2, 16, 8, baseline=6, render_path=(0,)),
                self.renderer_region("right", "读取", 12, 2, 16, 8, baseline=6, render_path=(1,), z_index=1),
                viewport=(32, 18),
            ).to_dict()
            manifest = self.write_fixture(root, payload)
            judge = FakeImageJudge()

            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                judge=judge,
            )
            restored = json.loads((root / "report.json").read_text(encoding="utf-8"))

        self.assertEqual(report.decision, VisualGateDecision.BLOCKED)
        self.assertEqual(judge.calls, 0)
        self.assertIn("renderer_text_overlap", report.gate.hard_gate.failed_codes)
        overlap = next(
            check
            for check in restored["gate"]["hard_gate"]["checks"]
            if check["code"] == "renderer_text_overlap"
        )
        self.assertEqual(overlap["details"]["sample_id"], "main-menu")
        self.assertEqual(
            json.loads(json.dumps(report.gate.to_dict())),
            VisualGateResult.from_dict(restored["gate"]).to_dict(),
        )

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

    def test_ocr_observation_writes_sidecar_and_blocks_candidate_residuals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            sidecar = root / "ocr-observation.json"
            frame = OcrFrame((OcrBox(1, 2, 10, 5, "Start game\nnow", 0.99),), "bg")
            judge = FakeImageJudge()

            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                judge=judge,
                ocr_provider=FakeOcrProvider(frame, frame),
                ocr_language="eng",
                ocr_report_path=sidecar,
                ocr_image_loader=lambda path: path,
            )
            payload = json.loads(sidecar.read_text(encoding="utf-8"))

        self.assertEqual(report.decision, VisualGateDecision.BLOCKED)
        self.assertEqual(judge.calls, 0)
        self.assertIn("ocr_candidate_residual_text", report.gate.hard_gate.failed_codes)
        self.assertEqual(payload["schema_version"], "hanengine.visual-ocr-observation/v2")
        self.assertEqual(payload["provider"], "fake-ocr")
        self.assertEqual(payload["provider_version"], "1.2.3")
        self.assertEqual(
            payload["samples"][0]["candidate"]["residual_texts"],
            ["Start game\nnow"],
        )
        self.assertEqual(payload["minimum_confidence"], 0.80)
        self.assertEqual(payload["allowlist"], ["english", "ren'py"])
        self.assertEqual(payload["samples"][0]["candidate"]["boxes"][0]["line_count"], 2)

    def test_ocr_observation_uses_threshold_for_candidate_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            reference = OcrFrame((OcrBox(1, 2, 10, 5, "Start", 0.99),), "bg")
            candidate = OcrFrame((OcrBox(1, 2, 10, 5, "Start game", 0.79),), "bg")

            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                ocr_provider=FakeOcrProvider(reference, candidate),
                ocr_language="eng",
                ocr_image_loader=lambda path: path,
            )

        self.assertEqual(report.decision, VisualGateDecision.BLOCKED)
        self.assertIn("ocr_candidate_coverage", report.gate.hard_gate.failed_codes)
        self.assertNotIn(
            "ocr_candidate_residual_text",
            report.gate.hard_gate.failed_codes,
        )

    def test_ocr_observation_does_not_block_low_confidence_residual(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            reference = OcrFrame((OcrBox(1, 2, 10, 5, "Start", 0.99),), "bg")
            candidate = OcrFrame(
                (
                    OcrBox(1, 2, 10, 5, "开始", 0.99),
                    OcrBox(1, 8, 10, 5, "Start game", 0.79),
                ),
                "bg",
            )

            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                ocr_provider=FakeOcrProvider(reference, candidate),
                ocr_language="eng",
                ocr_image_loader=lambda path: path,
            )

        self.assertEqual(report.decision, VisualGateDecision.ESCALATE)
        self.assertNotIn(
            "ocr_candidate_residual_text",
            report.gate.hard_gate.failed_codes,
        )

    def test_ocr_observation_rejects_invalid_minimum_confidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            frame = OcrFrame((OcrBox(1, 2, 10, 5, "Start", 0.99),), "bg")

            with self.assertRaisesRegex(ValueError, "ocr_minimum_confidence"):
                run_visual_evidence(
                    manifest,
                    root / "report.json",
                    authorization_reference="repository-owned-test-fixture",
                    ocr_provider=FakeOcrProvider(frame, frame),
                    ocr_language="eng",
                    ocr_minimum_confidence=1.01,
                    ocr_image_loader=lambda path: path,
                )

    def test_ocr_observation_rejects_options_without_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)

            with self.assertRaisesRegex(ValueError, "require an OCR provider"):
                run_visual_evidence(
                    manifest,
                    root / "report.json",
                    authorization_reference="repository-owned-test-fixture",
                    ocr_allowlist=("English",),
                )

    def test_ocr_observation_rejects_sidecar_path_collisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            frame = OcrFrame((OcrBox(1, 2, 10, 5, "开始", 0.99),), "bg")

            for destination in (
                manifest,
                root / "report.json",
            ):
                with self.subTest(destination=destination.name):
                    with self.assertRaisesRegex(VisualEvidenceError, "must not replace"):
                        run_visual_evidence(
                            manifest,
                            root / "report.json",
                            authorization_reference="repository-owned-test-fixture",
                            ocr_provider=FakeOcrProvider(frame, frame),
                            ocr_language="eng",
                            ocr_report_path=destination,
                            ocr_image_loader=lambda path: path,
                        )

            flat_candidate = root / "candidate.png"
            flat_candidate.write_bytes(_png(32, 18, 224))
            payload = self.manifest()
            payload["samples"][0]["candidate_image"] = flat_candidate.name
            manifest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(VisualEvidenceError, "must not replace"):
                run_visual_evidence(
                    manifest,
                    root / "report.json",
                    authorization_reference="repository-owned-test-fixture",
                    ocr_provider=FakeOcrProvider(frame, frame),
                    ocr_language="eng",
                    ocr_report_path=flat_candidate,
                    ocr_image_loader=lambda path: path,
                )

    def test_ocr_observation_allows_configured_language_name_and_records_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            sidecar = root / "ocr-observation.json"
            frame = OcrFrame((OcrBox(1, 2, 10, 5, "Español", 0.99),), "bg")

            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                ocr_provider=FakeOcrProvider(frame, frame),
                ocr_language="eng",
                ocr_allowlist=("Español",),
                ocr_report_path=sidecar,
                ocr_image_loader=lambda path: path,
            )
            self.assertTrue(sidecar.is_file())

        self.assertEqual(report.decision, VisualGateDecision.ESCALATE)
        self.assertNotIn("ocr_candidate_residual_text", report.gate.hard_gate.failed_codes)

    def test_ocr_observation_blocks_when_candidate_has_no_detected_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            reference = OcrFrame((OcrBox(1, 2, 10, 5, "Start", 0.99),), "bg")
            candidate = OcrFrame((), "bg")

            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                ocr_provider=FakeOcrProvider(reference, candidate),
                ocr_language="eng",
                ocr_image_loader=lambda path: path,
            )

        self.assertEqual(report.decision, VisualGateDecision.BLOCKED)
        self.assertIn("ocr_candidate_coverage", report.gate.hard_gate.failed_codes)

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

    def test_zhipu_judge_reads_key_from_environment(self):
        with patch.dict("os.environ", {"ZHIPU_API_KEY": "test-key"}):
            judge = ZhipuImageVisualJudge()

        self.assertEqual(judge.model, "glm-4.6v")
        self.assertEqual(judge.provider_name, "zhipu:glm-4.6v")

    def test_zhipu_judge_cannot_run_without_local_ocr_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            judge = ZhipuImageVisualJudge(api_key="test-key")

            with self.assertRaisesRegex(ValueError, "requires a local OCR provider"):
                run_visual_evidence(
                    manifest,
                    root / "report.json",
                    authorization_reference="repository-owned-test-fixture",
                    judge=judge,
                )

    def test_zhipu_judge_parses_response_and_overrides_model_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.write_fixture(root)
            manifest = load_visual_evidence_manifest(manifest_path)
            sample = manifest.samples[0]
            comparison = VisualComparison(
                sample_id=sample.sample_id,
                reference_image_sha256=HASH_A,
                candidate_image_sha256=HASH_B,
                reference_regions=sample.reference_regions,
                candidate_regions=sample.candidate_regions,
            )
            response = Mock(status_code=200)
            response.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "pass",
                                    "style_score": 0.95,
                                    "confidence": 0.93,
                                    "model": "untrusted-self-report",
                                    "issues": [],
                                }
                            )
                        }
                    }
                ]
            }
            judge = ZhipuImageVisualJudge(api_key="test-key")
            with patch("requests.post", return_value=response) as post:
                result = judge.judge_images(
                    manifest.profile,
                    comparison,
                    root / sample.reference_image,
                    root / sample.candidate_image,
                )

        self.assertEqual(result.model, "glm-4.6v")
        self.assertEqual(result.decision.value, "pass")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "glm-4.6v")
        prompt = post.call_args.kwargs["json"]["messages"][0]["content"][0]["text"]
        self.assertNotIn(sample.sample_id, prompt)
        self.assertIn("低对比度", prompt)

    def test_zhipu_pass_requires_human_review_in_the_release_gate(self):
        class PassingZhipu(ZhipuImageVisualJudge):
            def judge_images(self, profile, comparison, reference_image, candidate_image):
                from game_localizer.hanengine.visual_style import VisualJudgeDecision, VisualJudgeResult

                return VisualJudgeResult(VisualJudgeDecision.PASS, 0.95, 0.93, self.model)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = self.manifest()
            payload["schema_version"] = "hanengine.visual-evidence-manifest/v3"
            observation = self.renderer_observation(
                self.renderer_region("title", "开始", 2, 2, 10, 8, baseline=6),
                viewport=(32, 18),
            ).to_dict()
            payload["samples"][0]["reference_renderer_observation"] = observation
            payload["samples"][0]["candidate_renderer_observation"] = observation
            manifest = self.write_fixture(root, payload)
            frame = OcrFrame((OcrBox(1, 2, 10, 5, "开始", 0.99),), "bg")
            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                judge=PassingZhipu(api_key="test-key"),
                ocr_provider=FakeOcrProvider(frame, frame),
                ocr_language="chi_sim+eng",
                ocr_image_loader=lambda path: path,
            )

        self.assertEqual(report.decision, VisualGateDecision.ESCALATE)
        self.assertIn("visual_judge_pass_requires_human_review", report.gate.reasons)

    def test_zhipu_is_blocked_before_model_call_without_renderer_observation(self):
        class CountingZhipu(ZhipuImageVisualJudge):
            def __init__(self):
                super().__init__(api_key="test-key")
                self.calls = 0

            def judge_images(self, profile, comparison, reference_image, candidate_image):
                self.calls += 1
                raise AssertionError("renderer coverage must block before GLM")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            frame = OcrFrame((OcrBox(1, 2, 10, 5, "开始", 0.99),), "bg")
            judge = CountingZhipu()

            report = run_visual_evidence(
                manifest,
                root / "report.json",
                authorization_reference="repository-owned-test-fixture",
                judge=judge,
                ocr_provider=FakeOcrProvider(frame, frame),
                ocr_language="chi_sim+eng",
                ocr_image_loader=lambda path: path,
            )

        self.assertEqual(report.decision, VisualGateDecision.BLOCKED)
        self.assertEqual(judge.calls, 0)
        self.assertIn(
            "renderer_observation_coverage", report.gate.hard_gate.failed_codes
        )

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

    def test_cli_requires_language_when_ocr_options_are_requested(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            arguments = [
                "verify",
                "--manifest",
                str(manifest),
                "--output",
                str(root / "report.json"),
                "--authorization-reference",
                "repository-owned-test-fixture",
                "--authorized",
                "--ocr-allowlist",
                "English",
            ]
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = cli.run_visual(arguments)

        self.assertEqual(result, 1)
        self.assertIn("require --ocr-language", stderr.getvalue())

    def test_cli_requires_ocr_with_zhipu_judge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            arguments = [
                "verify",
                "--manifest",
                str(manifest),
                "--output",
                str(root / "report.json"),
                "--authorization-reference",
                "repository-owned-test-fixture",
                "--authorized",
                "--zhipu-model",
                "glm-4.6v",
            ]
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = cli.run_visual(arguments)

        self.assertEqual(result, 1)
        self.assertIn("requires --ocr-language", stderr.getvalue())

    def test_cli_rejects_invalid_ocr_minimum_confidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_fixture(root)
            arguments = [
                "verify",
                "--manifest",
                str(manifest),
                "--output",
                str(root / "report.json"),
                "--authorization-reference",
                "repository-owned-test-fixture",
                "--authorized",
                "--ocr-language",
                "eng",
                "--ocr-min-confidence",
                "1.01",
            ]
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = cli.run_visual(arguments)

        self.assertEqual(result, 1)
        self.assertIn("ocr_minimum_confidence", stderr.getvalue())

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
