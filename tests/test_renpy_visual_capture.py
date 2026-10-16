from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from game_localizer.hanengine.renpy_visual_capture import (
    BackendCaptureResult,
    CaptureAction,
    RENPY_CAPTURE_PLAN_SCHEMA_VERSION,
    RENPY_CAPTURE_REPORT_SCHEMA_VERSION,
    RENPY_RENDERER_OBSERVATION_SCHEMA_VERSION,
    RenPyCapturePlan,
    RenPyVisualCaptureError,
    RendererObservation,
    RendererTextRegion,
    ScreenAssertionResult,
    WindowsRenPyCaptureBackend,
    load_renpy_capture_plan,
    run_renpy_capture_pair,
)
from game_localizer.hanengine.validation import tree_sha256


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def _png(width: int, height: int, value: int) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes((value, value, value)) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(row * height))
        + _png_chunk(b"IEND", b"")
    )


class FakeCaptureBackend:
    def __init__(
        self,
        *,
        mismatch=False,
        omit_assertions=False,
        omit_renderer=False,
    ):
        self.calls = []
        self.mismatch = mismatch
        self.omit_assertions = omit_assertions
        self.omit_renderer = omit_renderer

    def capture(self, launcher, project_root, output_root, save_root, plan):
        call_index = len(self.calls)
        self.calls.append((launcher, project_root, output_root, save_root, plan))
        output_root.mkdir(parents=True)
        width = 41 if self.mismatch and call_index == 1 else 40
        for index, scenario in enumerate(plan.scenarios):
            (output_root / f"{scenario.sample_id}.png").write_bytes(
                _png(width, 24, 32 + index)
            )
        (project_root / "runtime-generated.txt").write_text("shadow only", encoding="utf-8")
        return BackendCaptureResult(
            status="passed",
            returncode=1,
            window_geometry=(10, 20, width, 24),
            traceback_present=False,
            stdout_bytes=0,
            stderr_bytes=0,
            screen_assertions=(
                ()
                if self.omit_assertions
                else tuple(
                    ScreenAssertionResult(
                        sample_id=scenario.sample_id,
                        expected_screen=scenario.expected_screen,
                        observed_screens=(scenario.expected_screen,),
                        passed=True,
                        renderer_observation=(
                            None
                            if self.omit_renderer
                            else RendererObservation(
                                viewport_width=width,
                                viewport_height=24,
                                schema_version="hanengine.renpy-renderer-observation/v1",
                                text_regions=(
                                    RendererTextRegion(
                                        text=scenario.expected_screen,
                                        x=2,
                                        y=3,
                                        width=20,
                                        height=10,
                                        line_count=1,
                                        baseline=8,
                                    ),
                                ),
                            )
                        ),
                    )
                    for scenario in plan.scenarios
                    if scenario.expected_screen is not None
                )
            ),
        )


class RenPyVisualCaptureTests(unittest.TestCase):
    OVERLAP_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "renpy_renderer_overlap"

    def plan_payload(self):
        return {
            "schema_version": "hanengine.renpy-capture-plan/v1",
            "window_title": "The Question",
            "window_timeout_seconds": 20,
            "post_focus_wait_seconds": 0.5,
            "scenarios": [
                {"sample_id": "main-menu", "actions": []},
                {
                    "sample_id": "dialogue",
                    "actions": [
                        {
                            "kind": "click",
                            "x": 0.1,
                            "y": 0.3,
                            "key": None,
                            "delay_seconds": 1,
                            "repeat": 1,
                        }
                    ],
                },
                {
                    "sample_id": "game-menu",
                    "actions": [
                        {
                            "kind": "press",
                            "x": None,
                            "y": None,
                            "key": "escape",
                            "delay_seconds": 0.5,
                            "repeat": 1,
                        }
                    ],
                },
            ],
        }

    def fixture(self, root: Path):
        launcher = root / "renpy.exe"
        launcher.write_bytes(b"fixture launcher")
        reference = root / "source"
        candidate = root / "candidate"
        reference.mkdir()
        candidate.mkdir()
        (reference / "game").mkdir()
        (candidate / "game").mkdir()
        (reference / "game" / "script.rpy").write_text("label start:\n    'Hello'\n", encoding="utf-8")
        (candidate / "game" / "script.rpy").write_text("label start:\n    '你好'\n", encoding="utf-8")
        plan = root / "plan.json"
        plan.write_text(json.dumps(self.plan_payload(), indent=2), encoding="utf-8")
        return launcher, reference, candidate, plan

    def v2_plan_payload(self):
        payload = self.plan_payload()
        payload["schema_version"] = RENPY_CAPTURE_PLAN_SCHEMA_VERSION
        expected_screens = ("main_menu", "say", "game_menu")
        for scenario, expected_screen in zip(payload["scenarios"], expected_screens, strict=True):
            scenario["expected_screen"] = expected_screen
            scenario["screen_timeout_seconds"] = 3
        return payload

    def test_plan_round_trip_and_action_validation(self):
        plan = RenPyCapturePlan.from_dict(self.plan_payload())

        self.assertEqual(RenPyCapturePlan.from_dict(plan.to_dict()), plan)
        right_click = CaptureAction.from_dict(
            {
                "kind": "right_click",
                "x": 0.5,
                "y": 0.5,
                "key": None,
                "delay_seconds": 0,
                "repeat": 1,
            }
        )
        self.assertEqual(right_click.kind.value, "right_click")
        with self.assertRaisesRegex(ValueError, "mouse actions"):
            CaptureAction.from_dict(
                {
                    "kind": "click",
                    "x": 0.5,
                    "y": 0.5,
                    "key": "escape",
                    "delay_seconds": 0,
                    "repeat": 1,
                }
            )

    def test_renderer_overlap_runtime_fixture_has_one_controlled_layout_change(self):
        root = self.OVERLAP_FIXTURE_ROOT
        plan = load_renpy_capture_plan(root / "capture-plan.json")
        reference = (root / "reference" / "game" / "script.rpy").read_text(
            encoding="utf-8"
        )
        candidate = (root / "candidate" / "game" / "script.rpy").read_text(
            encoding="utf-8"
        )

        self.assertEqual(plan.schema_version, RENPY_CAPTURE_PLAN_SCHEMA_VERSION)
        self.assertEqual(len(plan.scenarios), 1)
        self.assertEqual(plan.scenarios[0].sample_id, "main-menu")
        self.assertEqual(plan.scenarios[0].expected_screen, "main_menu")
        self.assertIn('xpos 650 ypos 220 size 40', reference)
        self.assertEqual(
            reference.replace("xpos 650 ypos 220 size 40", "xpos 250 ypos 220 size 40"),
            candidate,
        )

    def test_renderer_observation_round_trip_rejects_unknown_fields(self):
        observation = RendererObservation(
            viewport_width=1280,
            viewport_height=720,
            schema_version="hanengine.renpy-renderer-observation/v1",
            text_regions=(
                RendererTextRegion(
                    text="开始游戏",
                    x=44,
                    y=244,
                    width=96,
                    height=31,
                    line_count=1,
                    baseline=24,
                ),
            ),
        )

        self.assertEqual(
            RendererObservation.from_dict(observation.to_dict()), observation
        )
        invalid = observation.to_dict()
        invalid["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "fields"):
            RendererObservation.from_dict(invalid)

    def test_renderer_observation_v2_round_trip_preserves_hierarchy(self):
        observation = RendererObservation(
            viewport_width=1280,
            viewport_height=720,
            schema_version=RENPY_RENDERER_OBSERVATION_SCHEMA_VERSION,
            text_regions=(
                RendererTextRegion(
                    text="开始游戏",
                    x=44,
                    y=244,
                    width=96,
                    height=31,
                    line_count=1,
                    baseline=24,
                    region_id="render:0.2:text:0",
                    render_path=(0, 2),
                    z_index=7,
                ),
            ),
        )

        restored = RendererObservation.from_dict(observation.to_dict())

        self.assertEqual(restored, observation)
        self.assertEqual(restored.text_regions[0].render_path, (0, 2))
        self.assertEqual(restored.text_regions[0].z_index, 7)

    def test_renderer_observation_v2_requires_complete_hierarchy(self):
        with self.assertRaisesRegex(ValueError, "metadata"):
            RendererTextRegion(
                text="开始游戏",
                x=44,
                y=244,
                width=96,
                height=31,
                line_count=1,
                baseline=24,
                region_id="render:0:text:0",
            )

    def test_renderer_observation_v2_requires_unique_ids_and_z_indices(self):
        first = RendererTextRegion(
            "开始", 10, 10, 40, 20, 1, 15, "render:0:text:0", (0,), 0
        )
        duplicate_id = RendererTextRegion(
            "读取", 60, 10, 40, 20, 1, 15, "render:0:text:0", (1,), 1
        )
        duplicate_z = RendererTextRegion(
            "读取", 60, 10, 40, 20, 1, 15, "render:1:text:0", (1,), 0
        )

        with self.assertRaisesRegex(ValueError, "unique region IDs"):
            RendererObservation(320, 180, (first, duplicate_id))
        with self.assertRaisesRegex(ValueError, "unique z-index"):
            RendererObservation(320, 180, (first, duplicate_z))

    def test_legacy_renderer_text_region_still_round_trips_independently(self):
        region = RendererTextRegion("Start", 44, 244, 96, 31, 1, 24)

        self.assertEqual(RendererTextRegion.from_dict(region.to_dict()), region)

    def test_renderer_observation_maps_client_area_to_capture_pixels(self):
        observation = RendererObservation(
            viewport_width=1280,
            viewport_height=720,
            schema_version="hanengine.renpy-renderer-observation/v1",
            coordinate_space="renpy_virtual_pixels",
            text_regions=(
                RendererTextRegion(
                    text="Start",
                    x=44,
                    y=244,
                    width=96,
                    height=31,
                    line_count=1,
                    baseline=24,
                ),
            ),
        )

        mapped = observation.to_capture_space(
            capture_width=1296,
            capture_height=759,
            content_x=8,
            content_y=31,
            content_width=1280,
            content_height=720,
        )

        self.assertEqual(mapped.coordinate_space, "capture_pixels")
        self.assertEqual((mapped.viewport_width, mapped.viewport_height), (1296, 759))
        self.assertEqual((mapped.text_regions[0].x, mapped.text_regions[0].y), (52, 275))

    def test_windows_geometry_helper_maps_runtime_observation(self):
        class FakeUser32:
            @staticmethod
            def GetClientRect(hwnd, pointer):
                pointer._obj.right = 1280
                pointer._obj.bottom = 720
                return 1

            @staticmethod
            def ClientToScreen(hwnd, pointer):
                pointer._obj.x = 108
                pointer._obj.y = 231
                return 1

        observation = RendererObservation(
            viewport_width=1280,
            viewport_height=720,
            schema_version="hanengine.renpy-renderer-observation/v1",
            coordinate_space="renpy_virtual_pixels",
            text_regions=(
                RendererTextRegion("Start", 44, 244, 96, 31, 1, 24),
            ),
        )

        mapped = WindowsRenPyCaptureBackend._renderer_observation_to_capture(
            observation,
            123,
            (100, 200, 1296, 759),
            FakeUser32(),
        )

        self.assertEqual((mapped.text_regions[0].x, mapped.text_regions[0].y), (52, 275))

    def test_v2_plan_requires_screen_assertions(self):
        payload = self.v2_plan_payload()
        plan = RenPyCapturePlan.from_dict(payload)

        self.assertEqual(RenPyCapturePlan.from_dict(plan.to_dict()), plan)
        del payload["scenarios"][0]["expected_screen"]
        with self.assertRaisesRegex(ValueError, "fields"):
            RenPyCapturePlan.from_dict(payload)

    def test_v2_pair_report_records_satisfied_screen_assertions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, reference, candidate, plan_path = self.fixture(root)
            plan_path.write_text(json.dumps(self.v2_plan_payload(), indent=2), encoding="utf-8")

            report = run_renpy_capture_pair(
                launcher,
                reference,
                candidate,
                plan_path,
                root / "evidence",
                authorization_reference="repository-owned-test-fixture",
                backend_factory=FakeCaptureBackend,
            )

        self.assertTrue(report.capture_passed)
        self.assertTrue(report.semantic_alignment_verified)
        self.assertTrue(report.renderer_observation_verified)
        self.assertTrue(report.passed)
        self.assertEqual(report.schema_version, RENPY_CAPTURE_REPORT_SCHEMA_VERSION)
        self.assertEqual(
            [item.expected_screen for item in report.reference.screen_assertions],
            ["main_menu", "say", "game_menu"],
        )

    def test_v2_pair_fails_when_renderer_observation_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, reference, candidate, plan_path = self.fixture(root)
            plan_path.write_text(
                json.dumps(self.v2_plan_payload(), indent=2), encoding="utf-8"
            )

            report = run_renpy_capture_pair(
                launcher,
                reference,
                candidate,
                plan_path,
                root / "evidence",
                authorization_reference="repository-owned-test-fixture",
                backend_factory=lambda: FakeCaptureBackend(omit_renderer=True),
            )

        self.assertTrue(report.semantic_alignment_verified)
        self.assertFalse(report.renderer_observation_verified)
        self.assertFalse(report.passed)

    def test_v2_pair_rejects_backend_that_omits_screen_assertions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, reference, candidate, plan_path = self.fixture(root)
            plan_path.write_text(json.dumps(self.v2_plan_payload(), indent=2), encoding="utf-8")

            with self.assertRaisesRegex(RenPyVisualCaptureError, "every screen assertion"):
                run_renpy_capture_pair(
                    launcher,
                    reference,
                    candidate,
                    plan_path,
                    root / "evidence",
                    authorization_reference="repository-owned-test-fixture",
                    backend_factory=lambda: FakeCaptureBackend(omit_assertions=True),
                )

    def test_pair_capture_uses_shadows_preserves_sources_and_writes_portable_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, reference, candidate, plan_path = self.fixture(root)
            output = root / "evidence"
            reference_before = tree_sha256(reference)
            candidate_before = tree_sha256(candidate)
            backend = FakeCaptureBackend()

            report = run_renpy_capture_pair(
                launcher,
                reference,
                candidate,
                plan_path,
                output,
                authorization_reference="repository-owned-test-fixture",
                backend_factory=lambda: backend,
            )
            payload = json.loads((output / "capture-report.json").read_text(encoding="utf-8"))

            self.assertEqual(tree_sha256(reference), reference_before)
            self.assertEqual(tree_sha256(candidate), candidate_before)

        self.assertTrue(report.capture_passed)
        self.assertFalse(report.semantic_alignment_verified)
        self.assertFalse(report.passed)
        self.assertEqual(len(backend.calls), 2)
        self.assertNotEqual(backend.calls[0][1], reference)
        self.assertNotEqual(backend.calls[1][1], candidate)
        self.assertFalse(backend.calls[0][1].exists())
        self.assertEqual(
            [item["relative_path"] for item in payload["reference"]["screenshots"]],
            ["reference/main-menu.png", "reference/dialogue.png", "reference/game-menu.png"],
        )
        self.assertNotIn(str(reference), json.dumps(payload, sort_keys=True))
        self.assertNotIn(str(candidate), json.dumps(payload, sort_keys=True))

    def test_pair_capture_rejects_mismatched_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, reference, candidate, plan_path = self.fixture(root)

            with self.assertRaisesRegex(RenPyVisualCaptureError, "identical dimensions"):
                run_renpy_capture_pair(
                    launcher,
                    reference,
                    candidate,
                    plan_path,
                    root / "evidence",
                    authorization_reference="repository-owned-test-fixture",
                    backend_factory=lambda: FakeCaptureBackend(mismatch=True),
                )

    def test_pair_capture_requires_empty_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, reference, candidate, plan_path = self.fixture(root)
            output = root / "evidence"
            output.mkdir()
            (output / "unrelated.txt").write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(RenPyVisualCaptureError, "must be empty"):
                run_renpy_capture_pair(
                    launcher,
                    reference,
                    candidate,
                    plan_path,
                    output,
                    authorization_reference="repository-owned-test-fixture",
                    backend_factory=FakeCaptureBackend,
                )
            self.assertEqual((output / "unrelated.txt").read_text(encoding="utf-8"), "keep")

    def test_plan_loader_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "plan.json"
            payload = self.plan_payload()
            payload["unexpected"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "fields"):
                load_renpy_capture_plan(path)


if __name__ == "__main__":
    unittest.main()
