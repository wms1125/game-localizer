from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from game_localizer.hanengine.raster import (
    RASTER_MANIFEST_SCHEMA_VERSION,
    RasterAsset,
    RasterAssetKind,
    RasterManifest,
    RasterSegmentStatus,
    RasterTextSegment,
    RasterTextStyle,
    RasterVerificationReport,
    apply_raster_manifest,
    discover_raster_assets,
    verify_raster_manifest,
)
from game_localizer.hanengine.segments import ScreenRegion


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def snapshot_tree(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    )


class RasterPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        (self.source / "img").mkdir(parents=True)
        (self.source / "movies").mkdir()
        self.source_image = b"source-image"
        self.source_video = b"source-video"
        (self.source / "img" / "title.png").write_bytes(self.source_image)
        (self.source / "movies" / "intro.webm").write_bytes(self.source_video)
        self.manifest_root = self.root / "manifest"
        (self.manifest_root / "artifacts").mkdir(parents=True)
        self.localized_image = b"localized-image-zh"
        self.localized_video = b"localized-video-zh"
        (self.manifest_root / "artifacts" / "title.zh.png").write_bytes(
            self.localized_image
        )
        (self.manifest_root / "artifacts" / "intro.zh.webm").write_bytes(
            self.localized_video
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _segment(
        self,
        segment_id: str,
        asset_path: str,
        kind: RasterAssetKind,
        *,
        status: RasterSegmentStatus = RasterSegmentStatus.APPROVED,
    ) -> RasterTextSegment:
        return RasterTextSegment(
            segment_id=segment_id,
            asset_path=asset_path,
            asset_kind=kind,
            source_text="THE UNDERWORLD",
            target_text="地下世界",
            region=ScreenRegion(10, 20, 240, 48),
            frame_start_ms=0 if kind is RasterAssetKind.VIDEO else None,
            frame_end_ms=1500 if kind is RasterAssetKind.VIDEO else None,
            ocr_confidence=0.97,
            style=RasterTextStyle(
                font_family="Source Han Sans",
                font_size_px=28,
                fill_color="#f2d9a0",
                stroke_color="#21180f",
                stroke_width_px=2,
                angle_degrees=0,
            ),
            status=status,
            review_reason=(
                "Awaiting art-direction approval"
                if status is RasterSegmentStatus.MANUAL_REVIEW
                else None
            ),
        )

    def _manifest(self) -> RasterManifest:
        return RasterManifest(
            schema_version=RASTER_MANIFEST_SCHEMA_VERSION,
            source_language="en",
            target_language="zh-CN",
            assets=(
                RasterAsset(
                    relative_path="img/title.png",
                    kind=RasterAssetKind.IMAGE,
                    source_sha256=sha256_bytes(self.source_image),
                    localized_artifact_path="artifacts/title.zh.png",
                    localized_sha256=sha256_bytes(self.localized_image),
                    segments=(
                        self._segment(
                            "raster-title",
                            "img/title.png",
                            RasterAssetKind.IMAGE,
                        ),
                    ),
                ),
                RasterAsset(
                    relative_path="movies/intro.webm",
                    kind=RasterAssetKind.VIDEO,
                    source_sha256=sha256_bytes(self.source_video),
                    localized_artifact_path="artifacts/intro.zh.webm",
                    localized_sha256=sha256_bytes(self.localized_video),
                    segments=(
                        self._segment(
                            "raster-intro",
                            "movies/intro.webm",
                            RasterAssetKind.VIDEO,
                        ),
                    ),
                ),
            ),
        )

    def test_manifest_has_strict_json_round_trip_and_blocks_traversal(self):
        manifest = self._manifest()
        encoded = json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True)
        self.assertEqual(RasterManifest.from_dict(json.loads(encoded)), manifest)

        with self.assertRaises(ValueError):
            RasterManifest.from_dict({**manifest.to_dict(), "unexpected": True})
        invalid_asset = manifest.assets[0].to_dict()
        invalid_asset["relative_path"] = "../outside.png"
        with self.assertRaises(ValueError):
            RasterAsset.from_dict(invalid_asset)

    def test_discovery_inventories_images_and_videos_without_fake_ocr_text(self):
        manifest = discover_raster_assets(self.source)

        self.assertEqual(
            tuple(asset.relative_path for asset in manifest.assets),
            ("img/title.png", "movies/intro.webm"),
        )
        self.assertEqual(
            tuple(asset.kind for asset in manifest.assets),
            (RasterAssetKind.IMAGE, RasterAssetKind.VIDEO),
        )
        self.assertTrue(all(not asset.segments for asset in manifest.assets))
        self.assertTrue(all(asset.review_reason for asset in manifest.assets))

    def test_approved_image_and_video_are_applied_and_verified_without_changing_source(self):
        staging = self.root / "staging"
        shutil.copytree(self.source, staging)
        source_before = snapshot_tree(self.source)

        result = apply_raster_manifest(
            self.source,
            staging,
            self._manifest(),
            manifest_root=self.manifest_root,
        )

        self.assertEqual(
            tuple(asset.relative_path for asset in result.applied_assets),
            ("img/title.png", "movies/intro.webm"),
        )
        self.assertEqual((staging / "img" / "title.png").read_bytes(), self.localized_image)
        self.assertEqual((staging / "movies" / "intro.webm").read_bytes(), self.localized_video)
        self.assertEqual(snapshot_tree(self.source), source_before)
        report = verify_raster_manifest(
            self.source,
            staging,
            self._manifest(),
            manifest_root=self.manifest_root,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.issues, ())
        self.assertEqual(
            RasterVerificationReport.from_dict(
                json.loads(json.dumps(report.to_dict(), sort_keys=True))
            ),
            report,
        )

    def test_source_and_localized_artifact_hash_mismatches_fail_before_write(self):
        staging = self.root / "staging"
        shutil.copytree(self.source, staging)
        before = snapshot_tree(staging)
        manifest = self._manifest()
        changed_source = replace(
            manifest.assets[0],
            source_sha256=sha256_bytes(b"different-source"),
        )
        with self.assertRaisesRegex(ValueError, "source raster asset hash changed"):
            apply_raster_manifest(
                self.source,
                staging,
                replace(manifest, assets=(changed_source, *manifest.assets[1:])),
                manifest_root=self.manifest_root,
            )
        self.assertEqual(snapshot_tree(staging), before)

        changed_artifact = replace(
            manifest.assets[0],
            localized_sha256=sha256_bytes(b"different-artifact"),
        )
        with self.assertRaisesRegex(ValueError, "localized raster artifact hash changed"):
            apply_raster_manifest(
                self.source,
                staging,
                replace(manifest, assets=(changed_artifact, *manifest.assets[1:])),
                manifest_root=self.manifest_root,
            )
        self.assertEqual(snapshot_tree(staging), before)

    def test_unapproved_asset_is_not_written_and_is_reported_for_review(self):
        staging = self.root / "staging"
        shutil.copytree(self.source, staging)
        manifest = self._manifest()
        pending_asset = replace(
            manifest.assets[0],
            segments=(
                self._segment(
                    "raster-title",
                    "img/title.png",
                    RasterAssetKind.IMAGE,
                    status=RasterSegmentStatus.MANUAL_REVIEW,
                ),
            ),
        )
        pending_manifest = replace(manifest, assets=(pending_asset,))

        result = apply_raster_manifest(
            self.source,
            staging,
            pending_manifest,
            manifest_root=self.manifest_root,
        )

        self.assertEqual(result.applied_assets, ())
        self.assertEqual(result.skipped_assets, ("img/title.png",))
        self.assertEqual((staging / "img" / "title.png").read_bytes(), self.source_image)
        report = verify_raster_manifest(
            self.source,
            staging,
            pending_manifest,
            manifest_root=self.manifest_root,
        )
        self.assertTrue(report.passed)
        self.assertEqual(
            {issue.code for issue in report.issues},
            {"raster_manual_review_required"},
        )


if __name__ == "__main__":
    unittest.main()
