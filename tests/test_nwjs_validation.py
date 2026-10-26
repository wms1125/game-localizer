from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from game_localizer.hanengine import (
    RASTER_MANIFEST_SCHEMA_VERSION,
    RasterAsset,
    RasterAssetKind,
    RasterManifest,
    RasterSegmentStatus,
    RasterTextSegment,
    RasterTextStyle,
    ScreenRegion,
)
from game_localizer.hanengine import nwjs
from game_localizer.hanengine.nwjs import (
    NWJS_RPG_MAKER_PROBE_SCHEMA_VERSION,
    NWJS_RPG_MAKER_VALIDATION_SCHEMA_VERSION,
    NwjsRpgMakerValidatorConfig,
    run_nwjs_rpg_maker_validation,
)


class NwjsRpgMakerValidationTests(unittest.TestCase):
    def _write_project(self, root: Path, *, localized: bool) -> None:
        (root / "data").mkdir(parents=True)
        (root / "movies").mkdir()
        (root / "package.json").write_text(
            json.dumps({"name": "fixture", "main": "index.html"}),
            encoding="utf-8",
        )
        (root / "index.html").write_text(
            "<!doctype html><html><body></body></html>\n",
            encoding="utf-8",
        )
        title = "\u51a5\u754c" if localized else "Underworld"
        actor = "\u6d1b\u4f0a" if localized else "Lloyd"
        enemy = "\u5e7d\u7075" if localized else "Ghost"
        database = {
            "System.json": {"gameTitle": title},
            "Actors.json": [None, {"id": 1, "name": actor}],
            "Enemies.json": [None, {"id": 1, "name": enemy}],
        }
        for name, payload in database.items():
            (root / "data" / name).write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        for index in range(1, 4):
            (root / "movies" / f"cutscene-{index}.webm").write_bytes(
                f"video-{index}".encode("ascii")
            )

    def _manifest(self) -> RasterManifest:
        assets = []
        segment_counts = (5, 4, 5)
        for asset_index, segment_count in enumerate(segment_counts, 1):
            relative_path = f"movies/cutscene-{asset_index}.webm"
            segments = tuple(
                RasterTextSegment(
                    segment_id=f"video-{asset_index}-segment-{segment_index}",
                    asset_path=relative_path,
                    asset_kind=RasterAssetKind.VIDEO,
                    source_text=f"SOURCE {segment_index}",
                    target_text=f"TARGET {segment_index}",
                    region=ScreenRegion(0, 0, 64, 32),
                    frame_start_ms=segment_index * 1000,
                    frame_end_ms=segment_index * 1000 + 500,
                    ocr_confidence=0.99,
                    style=RasterTextStyle(),
                    status=RasterSegmentStatus.APPROVED,
                    review_reason=None,
                )
                for segment_index in range(1, segment_count + 1)
            )
            assets.append(
                RasterAsset(
                    relative_path=relative_path,
                    kind=RasterAssetKind.VIDEO,
                    source_sha256=hashlib.sha256(
                        f"source-{asset_index}".encode("ascii")
                    ).hexdigest(),
                    localized_artifact_path=f"localized/cutscene-{asset_index}.webm",
                    localized_sha256=hashlib.sha256(
                        f"localized-{asset_index}".encode("ascii")
                    ).hexdigest(),
                    segments=segments,
                )
            )
        return RasterManifest(
            RASTER_MANIFEST_SCHEMA_VERSION,
            "en",
            "zh-CN",
            tuple(assets),
        )

    def _fake_probe(
        self,
        manifest: RasterManifest | None,
        *,
        blank_map: bool = False,
        blank_segment: bool = False,
        wrong_loaded_path: bool = False,
    ):
        video_plan = nwjs._video_plan(manifest)

        def run(_config, shadow_root: Path, evidence_root: Path, label: str):
            evidence_root.mkdir(parents=True, exist_ok=True)
            screenshots = []
            relative_paths = ["title.png", "map.png"] + [
                segment["screenshot_file"]
                for asset in video_plan
                for segment in asset["segments"]
            ]
            for index, relative in enumerate(relative_paths):
                destination = evidence_root / Path(*relative.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                image = Image.new("RGB", (8, 8), (index + 10, 20, 30))
                blank = (blank_map and index == 1) or (
                    blank_segment and index == 2
                )
                if not blank:
                    image.putpixel((0, 0), (0, 0, 0))
                image.save(destination)
                screenshots.append(
                    {
                        "file": relative,
                        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                        "size_bytes": destination.stat().st_size,
                    }
                )
            names = nwjs._database_names(shadow_root)
            report = {
                "schema_version": NWJS_RPG_MAKER_PROBE_SCHEMA_VERSION,
                "label": label,
                "runtime_versions": {
                    "nw": "0.29.4",
                    "chromium": "65.0.3325.181",
                    "node": "9.11.1",
                },
                "title_observation": {
                    "scene": "Scene_Title",
                    "game_title": names["game_title"],
                    "actors": names["actors"],
                    "enemies": names["enemies"],
                },
                "map_observation": {"scene": "Scene_Map", "map_id": 12},
                "video_runs": [
                    {
                        "path": asset["path"],
                        "loaded_path": (
                            "movies/wrong.webm"
                            if wrong_loaded_path and index == 0
                            else asset["path"]
                        ),
                        "command_code": 261,
                        "status": "passed",
                        "segments": [
                            {"segment_id": segment["segment_id"]}
                            for segment in asset["segments"]
                        ],
                    }
                    for index, asset in enumerate(video_plan)
                ],
                "screenshots": screenshots,
                "runtime_events": [],
            }
            (evidence_root / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return report

        return run

    def test_runtime_smoke_does_not_require_raster_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            candidate = root / "candidate"
            self._write_project(source, localized=False)
            self._write_project(candidate, localized=True)
            config = NwjsRpgMakerValidatorConfig(
                Path(sys.executable), root / "evidence"
            )

            with patch.object(
                nwjs,
                "_run_probe",
                side_effect=self._fake_probe(None),
            ):
                result = run_nwjs_rpg_maker_validation(
                    config,
                    source,
                    candidate,
                )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["approved_video_count"], 0)
            self.assertEqual(result["approved_segment_count"], 0)
            self.assertTrue(
                all(check["passed"] for check in result["checks"])
            )

    def test_config_requires_an_existing_executable_and_bounded_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = NwjsRpgMakerValidatorConfig(
                Path(sys.executable), root / "evidence", timeout_seconds=30
            )
            self.assertEqual(config.executable, Path(sys.executable).resolve())
            self.assertEqual(config.evidence_root, (root / "evidence").resolve())
            with self.assertRaisesRegex(ValueError, "between 30 and 900"):
                NwjsRpgMakerValidatorConfig(
                    Path(sys.executable), root / "other", timeout_seconds=29
                )

    def test_runtime_report_is_candidate_bound_and_preserves_both_projects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            candidate = root / "candidate"
            self._write_project(source, localized=False)
            self._write_project(candidate, localized=True)
            manifest = self._manifest()
            evidence = root / "evidence"
            config = NwjsRpgMakerValidatorConfig(Path(sys.executable), evidence)
            source_before = nwjs._tree_sha256(source)
            candidate_before = nwjs._tree_sha256(candidate)

            with patch.object(
                nwjs,
                "_run_probe",
                side_effect=self._fake_probe(manifest, blank_map=True),
            ):
                result = run_nwjs_rpg_maker_validation(
                    config,
                    source,
                    candidate,
                    manifest,
                )

            report_path = evidence / "validation-report.json"
            published = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "passed")
            self.assertEqual(
                result["schema_version"], NWJS_RPG_MAKER_VALIDATION_SCHEMA_VERSION
            )
            self.assertEqual(result["approved_video_count"], 3)
            self.assertEqual(result["approved_segment_count"], 14)
            self.assertEqual(result["source_tree_sha256_before"], source_before)
            self.assertEqual(result["candidate_tree_sha256_before"], candidate_before)
            self.assertEqual(nwjs._tree_sha256(source), source_before)
            self.assertEqual(nwjs._tree_sha256(candidate), candidate_before)
            self.assertEqual(
                result["report_sha256"],
                hashlib.sha256(report_path.read_bytes()).hexdigest(),
            )
            self.assertNotIn(
                "validation-report.json",
                {item["relative_path"] for item in published["evidence_files"]},
            )
            self.assertEqual(len(published["evidence_files"]), 34)
            self.assertTrue(all(check["passed"] for check in published["checks"]))

    def test_blank_segment_screenshot_fails_the_runtime_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            candidate = root / "candidate"
            self._write_project(source, localized=False)
            self._write_project(candidate, localized=True)
            manifest = self._manifest()
            config = NwjsRpgMakerValidatorConfig(
                Path(sys.executable), root / "evidence"
            )

            with patch.object(
                nwjs,
                "_run_probe",
                side_effect=self._fake_probe(manifest, blank_segment=True),
            ):
                result = run_nwjs_rpg_maker_validation(
                    config,
                    source,
                    candidate,
                    manifest,
                )

            self.assertEqual(result["status"], "failed")
            self.assertIn(
                "source:screenshots",
                {issue["code"] for issue in result["issues"]},
            )

    def test_wrong_loaded_video_path_fails_even_when_segments_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            candidate = root / "candidate"
            self._write_project(source, localized=False)
            self._write_project(candidate, localized=True)
            manifest = self._manifest()
            config = NwjsRpgMakerValidatorConfig(
                Path(sys.executable), root / "evidence"
            )

            with patch.object(
                nwjs,
                "_run_probe",
                side_effect=self._fake_probe(
                    manifest,
                    wrong_loaded_path=True,
                ),
            ):
                result = run_nwjs_rpg_maker_validation(
                    config,
                    source,
                    candidate,
                    manifest,
                )

            self.assertEqual(result["status"], "failed")
            self.assertIn(
                "source:video:movies/cutscene-1.webm",
                {issue["code"] for issue in result["issues"]},
            )


if __name__ == "__main__":
    unittest.main()
