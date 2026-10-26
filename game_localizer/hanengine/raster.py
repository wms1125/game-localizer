from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from .segments import ScreenRegion, normalize_relative_path


RASTER_MANIFEST_SCHEMA_VERSION = "hanengine.raster-manifest/v1"
RASTER_VERIFICATION_REPORT_SCHEMA_VERSION = "hanengine.raster-verification-report/v1"

_IMAGE_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png", ".webp"})
_VIDEO_EXTENSIONS = frozenset({".mp4", ".webm"})
_SHA256_LENGTH = 64


class RasterAssetKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class RasterSegmentStatus(str, Enum):
    DETECTED = "detected"
    TRANSLATED = "translated"
    APPROVED = "approved"
    MANUAL_REVIEW = "manual_review"


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _exact_keys(payload: Mapping[str, object], expected: tuple[str, ...], name: str) -> None:
    actual = set(payload)
    required = set(expected)
    if actual != required:
        missing = sorted(required - actual)
        unexpected = sorted(actual - required)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected keys: {', '.join(unexpected)}")
        raise ValueError(f"{name} has invalid keys ({'; '.join(details)})")


def _string(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _optional_string(value: object, name: str, *, allow_empty: bool = False) -> str | None:
    if value is None:
        return None
    return _string(value, name, allow_empty=allow_empty)


def _number(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _optional_number(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
) -> float | None:
    if value is None:
        return None
    return _number(value, name, minimum=minimum)


def _optional_integer(value: object, name: str, *, minimum: int = 0) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer or None")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _sha256(value: object, name: str) -> str:
    result = _string(value, name).casefold()
    if len(result) != _SHA256_LENGTH or any(character not in "0123456789abcdef" for character in result):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return result


def _optional_sha256(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, name)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _kind_for_path(path: str) -> RasterAssetKind:
    suffix = Path(path).suffix.casefold()
    if suffix in _IMAGE_EXTENSIONS:
        return RasterAssetKind.IMAGE
    if suffix in _VIDEO_EXTENSIONS:
        return RasterAssetKind.VIDEO
    raise ValueError(f"unsupported raster asset extension: {suffix or '<none>'}")


def _safe_path(root: Path, relative_path: str, *, require_file: bool) -> Path:
    relative = normalize_relative_path(relative_path)
    resolved_root = root.resolve(strict=True)
    candidate = resolved_root / Path(*relative.split("/"))
    resolved = candidate.resolve(strict=require_file)
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise ValueError(f"path escapes its declared root: {relative}")
    if require_file and (not resolved.is_file() or candidate.is_symlink()):
        raise ValueError(f"path is not a regular file: {relative}")
    return resolved


@dataclass(frozen=True)
class RasterTextStyle:
    font_family: str | None = None
    font_size_px: float | None = None
    fill_color: str | None = None
    stroke_color: str | None = None
    stroke_width_px: float | None = None
    angle_degrees: float = 0.0

    _FIELDS = (
        "font_family",
        "font_size_px",
        "fill_color",
        "stroke_color",
        "stroke_width_px",
        "angle_degrees",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "font_family", _optional_string(self.font_family, "font_family"))
        object.__setattr__(self, "font_size_px", _optional_number(self.font_size_px, "font_size_px", minimum=0.01))
        object.__setattr__(self, "fill_color", _optional_string(self.fill_color, "fill_color"))
        object.__setattr__(self, "stroke_color", _optional_string(self.stroke_color, "stroke_color"))
        object.__setattr__(self, "stroke_width_px", _optional_number(self.stroke_width_px, "stroke_width_px", minimum=0.0))
        object.__setattr__(self, "angle_degrees", _number(self.angle_degrees, "angle_degrees"))

    def to_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self._FIELDS}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RasterTextStyle:
        values = _mapping(payload, cls.__name__)
        _exact_keys(values, cls._FIELDS, cls.__name__)
        return cls(**values)


@dataclass(frozen=True)
class RasterTextSegment:
    segment_id: str
    asset_path: str
    asset_kind: RasterAssetKind
    source_text: str
    target_text: str | None
    region: ScreenRegion
    frame_start_ms: int | None
    frame_end_ms: int | None
    ocr_confidence: float | None
    style: RasterTextStyle
    status: RasterSegmentStatus
    review_reason: str | None

    _FIELDS = (
        "segment_id",
        "asset_path",
        "asset_kind",
        "source_text",
        "target_text",
        "region",
        "frame_start_ms",
        "frame_end_ms",
        "ocr_confidence",
        "style",
        "status",
        "review_reason",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "segment_id", _string(self.segment_id, "segment_id"))
        object.__setattr__(self, "asset_path", normalize_relative_path(self.asset_path))
        if not isinstance(self.asset_kind, RasterAssetKind):
            raise TypeError("asset_kind must be a RasterAssetKind")
        if _kind_for_path(self.asset_path) is not self.asset_kind:
            raise ValueError("asset_kind does not match asset_path")
        object.__setattr__(self, "source_text", _string(self.source_text, "source_text"))
        object.__setattr__(self, "target_text", _optional_string(self.target_text, "target_text", allow_empty=True))
        if not isinstance(self.region, ScreenRegion):
            raise TypeError("region must be a ScreenRegion")
        object.__setattr__(self, "frame_start_ms", _optional_integer(self.frame_start_ms, "frame_start_ms"))
        object.__setattr__(self, "frame_end_ms", _optional_integer(self.frame_end_ms, "frame_end_ms"))
        if (self.frame_start_ms is None) != (self.frame_end_ms is None):
            raise ValueError("frame_start_ms and frame_end_ms must be provided together")
        if self.frame_start_ms is not None and self.frame_end_ms <= self.frame_start_ms:
            raise ValueError("frame_end_ms must be greater than frame_start_ms")
        if self.asset_kind is RasterAssetKind.IMAGE and self.frame_start_ms is not None:
            raise ValueError("image segments must not define a frame range")
        confidence = _optional_number(self.ocr_confidence, "ocr_confidence", minimum=0.0)
        if confidence is not None and confidence > 1.0:
            raise ValueError("ocr_confidence must not exceed 1.0")
        object.__setattr__(self, "ocr_confidence", confidence)
        if not isinstance(self.style, RasterTextStyle):
            raise TypeError("style must be a RasterTextStyle")
        if not isinstance(self.status, RasterSegmentStatus):
            raise TypeError("status must be a RasterSegmentStatus")
        object.__setattr__(self, "review_reason", _optional_string(self.review_reason, "review_reason"))
        if self.status in {RasterSegmentStatus.TRANSLATED, RasterSegmentStatus.APPROVED} and self.target_text is None:
            raise ValueError(f"{self.status.value} segments require target_text")
        if self.status is RasterSegmentStatus.DETECTED and self.target_text is not None:
            raise ValueError("detected segments must not define target_text")
        if self.status is RasterSegmentStatus.MANUAL_REVIEW and self.review_reason is None:
            raise ValueError("manual_review segments require review_reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "asset_path": self.asset_path,
            "asset_kind": self.asset_kind.value,
            "source_text": self.source_text,
            "target_text": self.target_text,
            "region": self.region.to_dict(),
            "frame_start_ms": self.frame_start_ms,
            "frame_end_ms": self.frame_end_ms,
            "ocr_confidence": self.ocr_confidence,
            "style": self.style.to_dict(),
            "status": self.status.value,
            "review_reason": self.review_reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RasterTextSegment:
        values = _mapping(payload, cls.__name__)
        _exact_keys(values, cls._FIELDS, cls.__name__)
        region = _mapping(values["region"], "region")
        style = _mapping(values["style"], "style")
        return cls(
            segment_id=values["segment_id"],
            asset_path=values["asset_path"],
            asset_kind=RasterAssetKind(values["asset_kind"]),
            source_text=values["source_text"],
            target_text=values["target_text"],
            region=ScreenRegion.from_dict(region),
            frame_start_ms=values["frame_start_ms"],
            frame_end_ms=values["frame_end_ms"],
            ocr_confidence=values["ocr_confidence"],
            style=RasterTextStyle.from_dict(style),
            status=RasterSegmentStatus(values["status"]),
            review_reason=values["review_reason"],
        )


@dataclass(frozen=True)
class RasterAsset:
    relative_path: str
    kind: RasterAssetKind
    source_sha256: str
    localized_artifact_path: str | None
    localized_sha256: str | None
    segments: tuple[RasterTextSegment, ...]
    review_reason: str | None = None

    _FIELDS = (
        "relative_path",
        "kind",
        "source_sha256",
        "localized_artifact_path",
        "localized_sha256",
        "segments",
        "review_reason",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_path", normalize_relative_path(self.relative_path))
        if not isinstance(self.kind, RasterAssetKind):
            raise TypeError("kind must be a RasterAssetKind")
        if _kind_for_path(self.relative_path) is not self.kind:
            raise ValueError("kind does not match relative_path")
        object.__setattr__(self, "source_sha256", _sha256(self.source_sha256, "source_sha256"))
        localized_path = self.localized_artifact_path
        if localized_path is not None:
            localized_path = normalize_relative_path(localized_path)
            if _kind_for_path(localized_path) is not self.kind:
                raise ValueError("localized artifact kind does not match source asset kind")
        object.__setattr__(self, "localized_artifact_path", localized_path)
        object.__setattr__(self, "localized_sha256", _optional_sha256(self.localized_sha256, "localized_sha256"))
        if (self.localized_artifact_path is None) != (self.localized_sha256 is None):
            raise ValueError("localized_artifact_path and localized_sha256 must be provided together")
        if not isinstance(self.segments, tuple) or any(not isinstance(item, RasterTextSegment) for item in self.segments):
            raise TypeError("segments must be a tuple of RasterTextSegment values")
        segment_ids: set[str] = set()
        for segment in self.segments:
            if segment.segment_id in segment_ids:
                raise ValueError(f"duplicate raster segment_id: {segment.segment_id}")
            segment_ids.add(segment.segment_id)
            if segment.asset_path != self.relative_path or segment.asset_kind is not self.kind:
                raise ValueError("raster segment asset identity does not match its parent asset")
        object.__setattr__(self, "review_reason", _optional_string(self.review_reason, "review_reason"))
        if not self.segments and self.review_reason is None:
            raise ValueError("assets without text segments require review_reason")

    @property
    def is_approved(self) -> bool:
        return bool(self.segments) and all(
            segment.status is RasterSegmentStatus.APPROVED for segment in self.segments
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "kind": self.kind.value,
            "source_sha256": self.source_sha256,
            "localized_artifact_path": self.localized_artifact_path,
            "localized_sha256": self.localized_sha256,
            "segments": [segment.to_dict() for segment in self.segments],
            "review_reason": self.review_reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RasterAsset:
        values = _mapping(payload, cls.__name__)
        _exact_keys(values, cls._FIELDS, cls.__name__)
        raw_segments = values["segments"]
        if not isinstance(raw_segments, list):
            raise TypeError("segments must be a list")
        return cls(
            relative_path=values["relative_path"],
            kind=RasterAssetKind(values["kind"]),
            source_sha256=values["source_sha256"],
            localized_artifact_path=values["localized_artifact_path"],
            localized_sha256=values["localized_sha256"],
            segments=tuple(RasterTextSegment.from_dict(_mapping(item, "segment")) for item in raw_segments),
            review_reason=values["review_reason"],
        )


@dataclass(frozen=True)
class RasterManifest:
    schema_version: str
    source_language: str
    target_language: str
    assets: tuple[RasterAsset, ...]

    _FIELDS = ("schema_version", "source_language", "target_language", "assets")

    def __post_init__(self) -> None:
        if self.schema_version != RASTER_MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported raster manifest schema: {self.schema_version}")
        object.__setattr__(self, "source_language", _string(self.source_language, "source_language"))
        object.__setattr__(self, "target_language", _string(self.target_language, "target_language"))
        if not isinstance(self.assets, tuple) or any(not isinstance(item, RasterAsset) for item in self.assets):
            raise TypeError("assets must be a tuple of RasterAsset values")
        paths: set[str] = set()
        segment_ids: set[str] = set()
        for asset in self.assets:
            if asset.relative_path in paths:
                raise ValueError(f"duplicate raster asset path: {asset.relative_path}")
            paths.add(asset.relative_path)
            for segment in asset.segments:
                if segment.segment_id in segment_ids:
                    raise ValueError(f"duplicate raster segment_id: {segment.segment_id}")
                segment_ids.add(segment.segment_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "assets": [asset.to_dict() for asset in self.assets],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RasterManifest:
        values = _mapping(payload, cls.__name__)
        _exact_keys(values, cls._FIELDS, cls.__name__)
        raw_assets = values["assets"]
        if not isinstance(raw_assets, list):
            raise TypeError("assets must be a list")
        return cls(
            schema_version=values["schema_version"],
            source_language=values["source_language"],
            target_language=values["target_language"],
            assets=tuple(RasterAsset.from_dict(_mapping(item, "asset")) for item in raw_assets),
        )


@dataclass(frozen=True)
class RasterAppliedAsset:
    relative_path: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_path", normalize_relative_path(self.relative_path))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))


@dataclass(frozen=True)
class RasterBuildResult:
    applied_assets: tuple[RasterAppliedAsset, ...]
    skipped_assets: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RasterVerificationIssue:
    code: str
    asset_path: str
    message: str
    blocking: bool

    _FIELDS = ("code", "asset_path", "message", "blocking")

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _string(self.code, "code"))
        object.__setattr__(self, "asset_path", normalize_relative_path(self.asset_path))
        object.__setattr__(self, "message", _string(self.message, "message"))
        if type(self.blocking) is not bool:
            raise TypeError("blocking must be a bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "asset_path": self.asset_path,
            "message": self.message,
            "blocking": self.blocking,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RasterVerificationIssue:
        values = _mapping(payload, cls.__name__)
        _exact_keys(values, cls._FIELDS, cls.__name__)
        return cls(
            code=values["code"],
            asset_path=values["asset_path"],
            message=values["message"],
            blocking=values["blocking"],
        )


@dataclass(frozen=True)
class RasterVerificationReport:
    schema_version: str
    passed: bool
    artifact_hashes: dict[str, str]
    issues: tuple[RasterVerificationIssue, ...]

    _FIELDS = ("schema_version", "passed", "artifact_hashes", "issues")

    def __post_init__(self) -> None:
        if self.schema_version != RASTER_VERIFICATION_REPORT_SCHEMA_VERSION:
            raise ValueError(f"unsupported raster verification report schema: {self.schema_version}")
        if type(self.passed) is not bool:
            raise TypeError("passed must be a bool")
        normalized = {
            normalize_relative_path(path): _sha256(digest, f"artifact_hashes[{path!r}]")
            for path, digest in self.artifact_hashes.items()
        }
        object.__setattr__(self, "artifact_hashes", normalized)
        if not isinstance(self.issues, tuple) or any(not isinstance(item, RasterVerificationIssue) for item in self.issues):
            raise TypeError("issues must be a tuple of RasterVerificationIssue values")
        if self.passed != (not any(item.blocking for item in self.issues)):
            raise ValueError("passed must match the absence of blocking issues")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "passed": self.passed,
            "artifact_hashes": dict(sorted(self.artifact_hashes.items())),
            "issues": [issue.to_dict() for issue in self.issues],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RasterVerificationReport:
        values = _mapping(payload, cls.__name__)
        _exact_keys(values, cls._FIELDS, cls.__name__)
        raw_hashes = values["artifact_hashes"]
        if not isinstance(raw_hashes, Mapping) or any(
            not isinstance(path, str) or not isinstance(digest, str)
            for path, digest in raw_hashes.items()
        ):
            raise TypeError("artifact_hashes must be a string mapping")
        raw_issues = values["issues"]
        if not isinstance(raw_issues, list):
            raise TypeError("issues must be a list")
        return cls(
            schema_version=values["schema_version"],
            passed=values["passed"],
            artifact_hashes=dict(raw_hashes),
            issues=tuple(
                RasterVerificationIssue.from_dict(_mapping(item, "issue"))
                for item in raw_issues
            ),
        )


def discover_raster_assets(
    source_root: Path,
    *,
    source_language: str = "en",
    target_language: str = "zh-CN",
) -> RasterManifest:
    root = source_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source_root must be a directory")
    assets = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.is_symlink():
            continue
        suffix = path.suffix.casefold()
        if suffix not in _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS:
            continue
        relative = path.relative_to(root).as_posix()
        assets.append(
            RasterAsset(
                relative_path=relative,
                kind=_kind_for_path(relative),
                source_sha256=_sha256_file(path),
                localized_artifact_path=None,
                localized_sha256=None,
                segments=(),
                review_reason="OCR and text-region extraction have not been run",
            )
        )
    return RasterManifest(
        schema_version=RASTER_MANIFEST_SCHEMA_VERSION,
        source_language=source_language,
        target_language=target_language,
        assets=tuple(assets),
    )


def load_raster_manifest(path: Path) -> RasterManifest:
    payload = json.loads(path.expanduser().resolve(strict=True).read_text(encoding="utf-8"))
    return RasterManifest.from_dict(_mapping(payload, RasterManifest.__name__))


def write_raster_manifest(manifest: RasterManifest, path: Path) -> Path:
    if not isinstance(manifest, RasterManifest):
        raise TypeError("manifest must be a RasterManifest")
    output = path.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output


def apply_raster_manifest(
    source_root: Path,
    staging_root: Path,
    manifest: RasterManifest,
    *,
    manifest_root: Path,
) -> RasterBuildResult:
    if not isinstance(manifest, RasterManifest):
        raise TypeError("manifest must be a RasterManifest")
    source = source_root.resolve(strict=True)
    staging = staging_root.resolve(strict=True)
    if source == staging or source in staging.parents or staging in source.parents:
        raise ValueError("source_root and staging_root must be separate trees")
    artifacts_root = manifest_root.resolve(strict=True)

    approved: list[tuple[RasterAsset, Path, Path]] = []
    skipped = []
    warnings = []
    for asset in manifest.assets:
        source_path = _safe_path(source, asset.relative_path, require_file=True)
        if _sha256_file(source_path) != asset.source_sha256:
            raise ValueError(f"source raster asset hash changed: {asset.relative_path}")
        if not asset.is_approved:
            skipped.append(asset.relative_path)
            warnings.append(f"Raster asset requires review and was not written: {asset.relative_path}")
            continue
        if asset.localized_artifact_path is None or asset.localized_sha256 is None:
            raise ValueError(f"approved raster asset has no localized artifact: {asset.relative_path}")
        artifact_path = _safe_path(artifacts_root, asset.localized_artifact_path, require_file=True)
        if _sha256_file(artifact_path) != asset.localized_sha256:
            raise ValueError(f"localized raster artifact hash changed: {asset.relative_path}")
        destination = _safe_path(staging, asset.relative_path, require_file=False)
        approved.append((asset, artifact_path, destination))

    applied = []
    for asset, artifact_path, destination in approved:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copyfile(artifact_path, temporary)
            if _sha256_file(temporary) != asset.localized_sha256:
                raise OSError(f"localized raster copy hash changed: {asset.relative_path}")
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        applied.append(RasterAppliedAsset(asset.relative_path, asset.localized_sha256))

    return RasterBuildResult(tuple(applied), tuple(skipped), tuple(warnings))


def verify_raster_manifest(
    source_root: Path,
    staging_root: Path,
    manifest: RasterManifest,
    *,
    manifest_root: Path,
) -> RasterVerificationReport:
    if not isinstance(manifest, RasterManifest):
        raise TypeError("manifest must be a RasterManifest")
    source = source_root.resolve(strict=True)
    staging = staging_root.resolve(strict=True)
    artifacts_root = manifest_root.resolve(strict=True)
    issues = []
    hashes: dict[str, str] = {}

    for asset in manifest.assets:
        try:
            source_path = _safe_path(source, asset.relative_path, require_file=True)
            source_matches = _sha256_file(source_path) == asset.source_sha256
        except (OSError, ValueError):
            source_matches = False
        if not source_matches:
            issues.append(
                RasterVerificationIssue(
                    "raster_source_hash_mismatch",
                    asset.relative_path,
                    "Source raster asset is missing, unsafe, or differs from the manifest",
                    True,
                )
            )

        if asset.is_approved:
            artifact_valid = False
            if asset.localized_artifact_path is not None and asset.localized_sha256 is not None:
                try:
                    artifact_path = _safe_path(artifacts_root, asset.localized_artifact_path, require_file=True)
                    artifact_valid = _sha256_file(artifact_path) == asset.localized_sha256
                except (OSError, ValueError):
                    artifact_valid = False
            if not artifact_valid:
                issues.append(
                    RasterVerificationIssue(
                        "raster_artifact_hash_mismatch",
                        asset.relative_path,
                        "Localized raster artifact is missing, unsafe, or differs from the manifest",
                        True,
                    )
                )
            try:
                candidate_path = _safe_path(staging, asset.relative_path, require_file=True)
                candidate_hash = _sha256_file(candidate_path)
                hashes[asset.relative_path] = candidate_hash
                candidate_matches = candidate_hash == asset.localized_sha256
            except (OSError, ValueError):
                candidate_matches = False
            if not candidate_matches:
                issues.append(
                    RasterVerificationIssue(
                        "raster_candidate_hash_mismatch",
                        asset.relative_path,
                        "Candidate raster asset does not match the approved localized artifact",
                        True,
                    )
                )
        else:
            issues.append(
                RasterVerificationIssue(
                    "raster_manual_review_required",
                    asset.relative_path,
                    asset.review_reason or "One or more raster text segments are not approved",
                    False,
                )
            )
            try:
                candidate_path = _safe_path(staging, asset.relative_path, require_file=True)
                candidate_hash = _sha256_file(candidate_path)
                hashes[asset.relative_path] = candidate_hash
                candidate_unchanged = candidate_hash == asset.source_sha256
            except (OSError, ValueError):
                candidate_unchanged = False
            if not candidate_unchanged:
                issues.append(
                    RasterVerificationIssue(
                        "unapproved_raster_asset_changed",
                        asset.relative_path,
                        "An unapproved raster asset differs from its source",
                        True,
                    )
                )

    passed = not any(issue.blocking for issue in issues)
    return RasterVerificationReport(
        schema_version=RASTER_VERIFICATION_REPORT_SCHEMA_VERSION,
        passed=passed,
        artifact_hashes=hashes,
        issues=tuple(issues),
    )
