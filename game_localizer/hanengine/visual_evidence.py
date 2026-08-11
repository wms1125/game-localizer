from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from .segments import JsonValue, normalize_relative_path
from .renpy_visual_capture import (
    RENPY_CAPTURE_PLAN_SCHEMA_VERSION,
    RENPY_CAPTURE_REPORT_SCHEMA_VERSION,
)
from .visual_style import (
    TextRegionObservation,
    VisualComparison,
    VisualGateDecision,
    VisualGateResult,
    VisualHardGatePolicy,
    VisualJudgeResult,
    VisualStyleProfile,
    evaluate_visual_gate,
)


VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION = "hanengine.visual-evidence-annotations/v1"
VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION = "hanengine.visual-evidence-manifest/v2"
VISUAL_EVIDENCE_REPORT_SCHEMA_VERSION = "hanengine.visual-evidence-report/v2"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class VisualEvidenceError(RuntimeError):
    pass


class VisualObservationSource(str, Enum):
    RENDERER = "renderer"
    OCR = "ocr"
    MANUAL = "manual"


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _mapping_sequence(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of objects")
    items = tuple(value)
    if any(not isinstance(item, Mapping) for item in items):
        raise TypeError(f"{name} must contain only objects")
    return items


def _exact_keys(payload: Mapping[str, object], expected: Sequence[str], name: str) -> None:
    if set(payload) != set(expected):
        raise ValueError(f"{name} payload fields do not match schema")


def _plain_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _sha256_string(value: object, name: str) -> str:
    value = _plain_string(value, name).casefold()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _regular_input_file(path: Path, name: str) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise VisualEvidenceError(f"{name} must be a regular file")
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise VisualEvidenceError(f"{name} is unavailable") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != _PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise VisualEvidenceError(f"visual evidence is not a valid PNG: {path.name}")
    width, height = struct.unpack(">II", header[16:24])
    if width < 1 or height < 1:
        raise VisualEvidenceError(f"visual evidence has invalid dimensions: {path.name}")
    return width, height


def _resolve_evidence_file(root: Path, relative_path: str) -> Path:
    normalized = normalize_relative_path(relative_path)
    candidate = root.joinpath(*normalized.split("/"))
    current = root
    for part in normalized.split("/"):
        current /= part
        if current.is_symlink():
            raise VisualEvidenceError("visual evidence paths must not contain symbolic links")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise VisualEvidenceError(f"visual evidence file is unavailable: {normalized}") from exc
    if not resolved.is_file() or root not in resolved.parents:
        raise VisualEvidenceError(f"visual evidence path is not a regular file: {normalized}")
    return resolved


@dataclass(frozen=True)
class VisualEvidenceSample:
    sample_id: str
    reference_image: str
    candidate_image: str
    observation_source: VisualObservationSource
    observation_reference: str
    reference_regions: tuple[TextRegionObservation, ...]
    candidate_regions: tuple[TextRegionObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _plain_string(self.sample_id, "sample_id"))
        object.__setattr__(self, "reference_image", normalize_relative_path(self.reference_image))
        object.__setattr__(self, "candidate_image", normalize_relative_path(self.candidate_image))
        if self.reference_image == self.candidate_image:
            raise ValueError("reference_image and candidate_image must differ")
        if not isinstance(self.observation_source, VisualObservationSource):
            raise TypeError("observation_source must be VisualObservationSource")
        object.__setattr__(
            self,
            "observation_reference",
            normalize_relative_path(self.observation_reference),
        )
        for name in ("reference_regions", "candidate_regions"):
            regions = tuple(getattr(self, name))
            if not regions or any(not isinstance(item, TextRegionObservation) for item in regions):
                raise ValueError(f"{name} must contain TextRegionObservation values")
            object.__setattr__(self, name, regions)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "sample_id": self.sample_id,
            "reference_image": self.reference_image,
            "candidate_image": self.candidate_image,
            "observation_source": self.observation_source.value,
            "observation_reference": self.observation_reference,
            "reference_regions": [item.to_dict() for item in self.reference_regions],
            "candidate_regions": [item.to_dict() for item in self.candidate_regions],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualEvidenceSample":
        payload = _mapping(payload, "visual_evidence_sample")
        _exact_keys(
            payload,
            (
                "sample_id",
                "reference_image",
                "candidate_image",
                "observation_source",
                "observation_reference",
                "reference_regions",
                "candidate_regions",
            ),
            "visual_evidence_sample",
        )
        try:
            source = VisualObservationSource(payload["observation_source"])
        except (TypeError, ValueError) as exc:
            raise ValueError("observation_source is invalid") from exc
        reference = _mapping_sequence(payload["reference_regions"], "reference_regions")
        candidate = _mapping_sequence(payload["candidate_regions"], "candidate_regions")
        return cls(
            sample_id=payload["sample_id"],
            reference_image=payload["reference_image"],
            candidate_image=payload["candidate_image"],
            observation_source=source,
            observation_reference=payload["observation_reference"],
            reference_regions=tuple(TextRegionObservation.from_dict(item) for item in reference),
            candidate_regions=tuple(TextRegionObservation.from_dict(item) for item in candidate),
        )


@dataclass(frozen=True)
class VisualEvidenceManifest:
    profile: VisualStyleProfile
    policy: VisualHardGatePolicy
    samples: tuple[VisualEvidenceSample, ...]
    schema_version: str = VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION}")
        if not isinstance(self.profile, VisualStyleProfile):
            raise TypeError("profile must be VisualStyleProfile")
        if not isinstance(self.policy, VisualHardGatePolicy):
            raise TypeError("policy must be VisualHardGatePolicy")
        samples = tuple(self.samples)
        if not samples or any(not isinstance(item, VisualEvidenceSample) for item in samples):
            raise ValueError("samples must contain VisualEvidenceSample values")
        ids = [item.sample_id for item in samples]
        if len(ids) != len(set(ids)):
            raise ValueError("samples must contain unique sample IDs")
        object.__setattr__(self, "samples", samples)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile.to_dict(),
            "policy": self.policy.to_dict(),
            "samples": [item.to_dict() for item in self.samples],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualEvidenceManifest":
        payload = _mapping(payload, "visual_evidence_manifest")
        _exact_keys(payload, ("schema_version", "profile", "policy", "samples"), "visual_evidence_manifest")
        samples = _mapping_sequence(payload["samples"], "samples")
        return cls(
            schema_version=payload["schema_version"],
            profile=VisualStyleProfile.from_dict(_mapping(payload["profile"], "profile")),
            policy=VisualHardGatePolicy.from_dict(_mapping(payload["policy"], "policy")),
            samples=tuple(VisualEvidenceSample.from_dict(item) for item in samples),
        )


@dataclass(frozen=True)
class ManualVisualAnnotationSample:
    sample_id: str
    reference_regions: tuple[TextRegionObservation, ...]
    candidate_regions: tuple[TextRegionObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _plain_string(self.sample_id, "sample_id"))
        for name in ("reference_regions", "candidate_regions"):
            regions = tuple(getattr(self, name))
            if any(not isinstance(item, TextRegionObservation) for item in regions):
                raise TypeError(f"{name} must contain TextRegionObservation values")
            ids = [item.region_id for item in regions]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} must contain unique region IDs")
            object.__setattr__(self, name, regions)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "sample_id": self.sample_id,
            "reference_regions": [item.to_dict() for item in self.reference_regions],
            "candidate_regions": [item.to_dict() for item in self.candidate_regions],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ManualVisualAnnotationSample":
        payload = _mapping(payload, "manual_visual_annotation_sample")
        _exact_keys(
            payload,
            ("sample_id", "reference_regions", "candidate_regions"),
            "manual_visual_annotation_sample",
        )
        reference = _mapping_sequence(payload["reference_regions"], "reference_regions")
        candidate = _mapping_sequence(payload["candidate_regions"], "candidate_regions")
        return cls(
            sample_id=payload["sample_id"],
            reference_regions=tuple(TextRegionObservation.from_dict(item) for item in reference),
            candidate_regions=tuple(TextRegionObservation.from_dict(item) for item in candidate),
        )


@dataclass(frozen=True)
class ManualVisualAnnotations:
    capture_report_sha256: str
    manual_observation_reference: str
    profile: VisualStyleProfile
    policy: VisualHardGatePolicy
    samples: tuple[ManualVisualAnnotationSample, ...]
    schema_version: str = VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION}")
        object.__setattr__(
            self,
            "capture_report_sha256",
            _sha256_string(self.capture_report_sha256, "capture_report_sha256"),
        )
        object.__setattr__(
            self,
            "manual_observation_reference",
            _plain_string(self.manual_observation_reference, "manual_observation_reference"),
        )
        if not isinstance(self.profile, VisualStyleProfile):
            raise TypeError("profile must be VisualStyleProfile")
        if not isinstance(self.policy, VisualHardGatePolicy):
            raise TypeError("policy must be VisualHardGatePolicy")
        samples = tuple(self.samples)
        if not samples or any(not isinstance(item, ManualVisualAnnotationSample) for item in samples):
            raise ValueError("samples must contain ManualVisualAnnotationSample values")
        ids = [item.sample_id for item in samples]
        if len(ids) != len(set(ids)):
            raise ValueError("samples must contain unique sample IDs")
        object.__setattr__(self, "samples", samples)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "capture_report_sha256": self.capture_report_sha256,
            "manual_observation_reference": self.manual_observation_reference,
            "profile": self.profile.to_dict(),
            "policy": self.policy.to_dict(),
            "samples": [item.to_dict() for item in self.samples],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ManualVisualAnnotations":
        payload = _mapping(payload, "manual_visual_annotations")
        _exact_keys(
            payload,
            (
                "schema_version",
                "capture_report_sha256",
                "manual_observation_reference",
                "profile",
                "policy",
                "samples",
            ),
            "manual_visual_annotations",
        )
        samples = _mapping_sequence(payload["samples"], "samples")
        return cls(
            schema_version=payload["schema_version"],
            capture_report_sha256=payload["capture_report_sha256"],
            manual_observation_reference=payload["manual_observation_reference"],
            profile=VisualStyleProfile.from_dict(_mapping(payload["profile"], "profile")),
            policy=VisualHardGatePolicy.from_dict(_mapping(payload["policy"], "policy")),
            samples=tuple(ManualVisualAnnotationSample.from_dict(item) for item in samples),
        )


@dataclass(frozen=True)
class VisualImageEvidence:
    sample_id: str
    reference_image: str
    candidate_image: str
    reference_image_sha256: str
    candidate_image_sha256: str
    width: int
    height: int
    observation_source: VisualObservationSource
    observation_reference: str

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "sample_id": self.sample_id,
            "reference_image": self.reference_image,
            "candidate_image": self.candidate_image,
            "reference_image_sha256": self.reference_image_sha256,
            "candidate_image_sha256": self.candidate_image_sha256,
            "width": self.width,
            "height": self.height,
            "observation_source": self.observation_source.value,
            "observation_reference": self.observation_reference,
        }


class ImageVisualJudge(Protocol):
    provider_name: str

    def judge_images(
        self,
        profile: VisualStyleProfile,
        comparison: VisualComparison,
        reference_image: Path,
        candidate_image: Path,
    ) -> VisualJudgeResult: ...


class CommandImageVisualJudge:
    """Invoke an explicitly configured local AI/service wrapper without a shell."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int = 120,
        provider_name: str = "external-command",
    ) -> None:
        values = tuple(command)
        if not values or any(not isinstance(item, str) or not item for item in values):
            raise ValueError("command must contain non-empty strings")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 900:
            raise ValueError("timeout_seconds must be between 1 and 900")
        self.command = values
        self.timeout_seconds = timeout_seconds
        self.provider_name = _plain_string(provider_name, "provider_name")

    def judge_images(
        self,
        profile: VisualStyleProfile,
        comparison: VisualComparison,
        reference_image: Path,
        candidate_image: Path,
    ) -> VisualJudgeResult:
        request = {
            "profile": profile.to_dict(),
            "comparison": comparison.to_dict(),
            "reference_image": str(reference_image),
            "candidate_image": str(candidate_image),
        }
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(request, ensure_ascii=False, sort_keys=True),
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VisualEvidenceError(f"visual judge could not run: {type(exc).__name__}") from exc
        if completed.returncode != 0:
            raise VisualEvidenceError(f"visual judge exited with code {completed.returncode}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise VisualEvidenceError("visual judge returned invalid JSON") from exc
        return VisualJudgeResult.from_dict(_mapping(payload, "visual_judge_result"))


class _BoundImageJudge:
    def __init__(self, judge: ImageVisualJudge, images: Mapping[str, tuple[Path, Path]]) -> None:
        self.image_judge = judge
        self.images = dict(images)

    def judge(self, profile: VisualStyleProfile, comparison: VisualComparison) -> VisualJudgeResult:
        reference, candidate = self.images[comparison.sample_id]
        return self.image_judge.judge_images(profile, comparison, reference, candidate)


@dataclass(frozen=True)
class VisualEvidenceReport:
    created_at: str
    authorization_reference: str
    manifest_sha256: str
    profile: VisualStyleProfile
    policy: VisualHardGatePolicy
    images: tuple[VisualImageEvidence, ...]
    gate: VisualGateResult
    judge_provider: str | None
    schema_version: str = VISUAL_EVIDENCE_REPORT_SCHEMA_VERSION

    @property
    def decision(self) -> VisualGateDecision:
        return self.gate.decision

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "authorization_reference": self.authorization_reference,
            "manifest_sha256": self.manifest_sha256,
            "profile": self.profile.to_dict(),
            "policy": self.policy.to_dict(),
            "images": [item.to_dict() for item in self.images],
            "gate": self.gate.to_dict(),
            "judge_provider": self.judge_provider,
        }


def load_visual_evidence_manifest(path: Path) -> VisualEvidenceManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualEvidenceError("visual evidence manifest could not be read") from exc
    return VisualEvidenceManifest.from_dict(_mapping(payload, "visual_evidence_manifest"))


def load_manual_visual_annotations(path: Path) -> ManualVisualAnnotations:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualEvidenceError("manual visual annotations could not be read") from exc
    return ManualVisualAnnotations.from_dict(_mapping(payload, "manual_visual_annotations"))


def _verified_capture_variant(
    root: Path,
    payload: Mapping[str, object],
    variant: str,
) -> tuple[str, tuple[dict[str, object], ...]]:
    _exact_keys(
        payload,
        (
            "returncode",
            "screen_assertions",
            "screenshots",
            "source_preserved",
            "source_tree_sha256",
            "status",
            "stderr_bytes",
            "stdout_bytes",
            "traceback_present",
            "variant",
            "window_geometry",
        ),
        f"capture_report.{variant}",
    )
    if payload["variant"] != variant or payload["status"] != "passed":
        raise VisualEvidenceError(f"capture report {variant} variant did not pass")
    if payload["source_preserved"] is not True or payload["traceback_present"] is not False:
        raise VisualEvidenceError(f"capture report {variant} source or runtime state is invalid")
    source_sha256 = _sha256_string(payload["source_tree_sha256"], f"{variant}.source_tree_sha256")
    assertion_payloads = _mapping_sequence(payload["screen_assertions"], f"{variant}.screen_assertions")
    assertions: list[tuple[str, str]] = []
    for assertion in assertion_payloads:
        _exact_keys(
            assertion,
            ("expected_screen", "observed_screens", "passed", "sample_id"),
            f"{variant}.screen_assertion",
        )
        sample_id = _plain_string(assertion["sample_id"], "sample_id")
        expected_screen = _plain_string(assertion["expected_screen"], "expected_screen")
        observed_screens = assertion["observed_screens"]
        if (
            isinstance(observed_screens, (str, bytes))
            or not isinstance(observed_screens, Sequence)
            or any(not isinstance(item, str) or not item for item in observed_screens)
        ):
            raise VisualEvidenceError(f"capture report {variant} observed screens are invalid")
        if assertion["passed"] is not True or expected_screen not in observed_screens:
            raise VisualEvidenceError(f"capture report {variant} screen assertion did not pass")
        assertions.append((sample_id, expected_screen))
    screenshot_payloads = _mapping_sequence(payload["screenshots"], f"{variant}.screenshots")
    screenshots: list[dict[str, object]] = []
    for screenshot in screenshot_payloads:
        _exact_keys(
            screenshot,
            ("height", "relative_path", "sample_id", "sha256", "width"),
            f"{variant}.screenshot",
        )
        sample_id = _plain_string(screenshot["sample_id"], "sample_id")
        relative_path = normalize_relative_path(screenshot["relative_path"])
        if not relative_path.startswith(f"{variant}/"):
            raise VisualEvidenceError(f"capture report {variant} screenshot path is invalid")
        width = _positive_int(screenshot["width"], "width")
        height = _positive_int(screenshot["height"], "height")
        expected_sha256 = _sha256_string(screenshot["sha256"], "screenshot.sha256")
        image_path = _resolve_evidence_file(root, relative_path)
        if _png_size(image_path) != (width, height):
            raise VisualEvidenceError(f"capture report {variant} screenshot dimensions do not match")
        if _sha256_file(image_path) != expected_sha256:
            raise VisualEvidenceError(f"capture report {variant} screenshot hash does not match")
        screenshots.append(
            {
                "sample_id": sample_id,
                "relative_path": relative_path,
                "width": width,
                "height": height,
            }
        )
    if [item[0] for item in assertions] != [item["sample_id"] for item in screenshots]:
        raise VisualEvidenceError(f"capture report {variant} assertions and screenshots do not match")
    return source_sha256, tuple(screenshots)


def prepare_visual_evidence_manifest(
    capture_report_path: Path,
    annotations_path: Path,
    output_path: Path,
) -> VisualEvidenceManifest:
    capture_report_path = _regular_input_file(capture_report_path, "capture_report_path")
    annotations_path = _regular_input_file(annotations_path, "annotations_path")
    root = capture_report_path.parent.resolve(strict=True)
    try:
        annotations_reference = annotations_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise VisualEvidenceError("annotations_path must be inside the capture evidence directory") from exc
    annotations_reference = normalize_relative_path(annotations_reference)
    try:
        capture_payload = json.loads(capture_report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualEvidenceError("capture report could not be read") from exc
    capture_payload = _mapping(capture_payload, "capture_report")
    _exact_keys(
        capture_payload,
        (
            "authorization_reference",
            "candidate",
            "capture_passed",
            "created_at",
            "passed",
            "plan_schema_version",
            "plan_sha256",
            "reference",
            "schema_version",
            "semantic_alignment_verified",
        ),
        "capture_report",
    )
    if (
        capture_payload["schema_version"] != RENPY_CAPTURE_REPORT_SCHEMA_VERSION
        or capture_payload["plan_schema_version"] != RENPY_CAPTURE_PLAN_SCHEMA_VERSION
    ):
        raise VisualEvidenceError("capture report must use the current Ren'Py v2 schemas")
    if (
        capture_payload["capture_passed"] is not True
        or capture_payload["semantic_alignment_verified"] is not True
        or capture_payload["passed"] is not True
    ):
        raise VisualEvidenceError("capture report must have verified semantic alignment")
    annotations = load_manual_visual_annotations(annotations_path)
    if annotations.capture_report_sha256 != _sha256_file(capture_report_path):
        raise VisualEvidenceError("manual annotations reference a different capture report")
    reference_sha256, reference = _verified_capture_variant(
        root,
        _mapping(capture_payload["reference"], "capture_report.reference"),
        "reference",
    )
    _, candidate = _verified_capture_variant(
        root,
        _mapping(capture_payload["candidate"], "capture_report.candidate"),
        "candidate",
    )
    reference_ids = [item["sample_id"] for item in reference]
    candidate_ids = [item["sample_id"] for item in candidate]
    annotation_ids = [item.sample_id for item in annotations.samples]
    if reference_ids != candidate_ids or reference_ids != annotation_ids:
        raise VisualEvidenceError("capture report and manual annotation scenarios do not match")
    if tuple(reference_ids) != annotations.profile.scenarios:
        raise VisualEvidenceError("visual profile scenarios do not match capture report")
    if annotations.profile.engine_id.casefold() != "renpy":
        raise VisualEvidenceError("Ren'Py capture evidence requires a Ren'Py visual profile")
    if annotations.profile.source_fingerprint != reference_sha256:
        raise VisualEvidenceError("visual profile source fingerprint does not match capture report")
    samples: list[VisualEvidenceSample] = []
    for reference_image, candidate_image, annotation in zip(
        reference,
        candidate,
        annotations.samples,
        strict=True,
    ):
        if (reference_image["width"], reference_image["height"]) != (
            candidate_image["width"],
            candidate_image["height"],
        ):
            raise VisualEvidenceError(f"sample {annotation.sample_id} images must have identical dimensions")
        if not annotation.reference_regions or not annotation.candidate_regions:
            raise VisualEvidenceError(f"sample {annotation.sample_id} must contain manual text regions")
        reference_region_ids = [item.region_id for item in annotation.reference_regions]
        candidate_region_ids = [item.region_id for item in annotation.candidate_regions]
        if reference_region_ids != candidate_region_ids:
            raise VisualEvidenceError(f"sample {annotation.sample_id} manual text regions do not match")
        samples.append(
            VisualEvidenceSample(
                sample_id=annotation.sample_id,
                reference_image=reference_image["relative_path"],
                candidate_image=candidate_image["relative_path"],
                observation_source=VisualObservationSource.MANUAL,
                observation_reference=annotations_reference,
                reference_regions=annotation.reference_regions,
                candidate_regions=annotation.candidate_regions,
            )
        )
    manifest = VisualEvidenceManifest(
        profile=annotations.profile,
        policy=annotations.policy,
        samples=tuple(samples),
    )
    output_path = output_path.expanduser().absolute()
    if output_path.parent.resolve(strict=True) != root:
        raise VisualEvidenceError("output_path must be in the capture evidence directory")
    if output_path.is_symlink() or output_path.is_dir():
        raise VisualEvidenceError("output_path must identify a regular file")
    _write_json(manifest.to_dict(), output_path)
    return manifest


def _write_json(payload: Mapping[str, JsonValue], destination: Path) -> None:
    destination = destination.expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_report(report: VisualEvidenceReport, destination: Path) -> None:
    _write_json(report.to_dict(), destination)


def run_visual_evidence(
    manifest_path: Path,
    output_path: Path,
    *,
    authorization_reference: str,
    judge: ImageVisualJudge | None = None,
) -> VisualEvidenceReport:
    authorization_reference = _plain_string(authorization_reference, "authorization_reference")
    manifest_path = _regular_input_file(manifest_path, "manifest_path")
    root = manifest_path.parent.resolve(strict=True)
    manifest = load_visual_evidence_manifest(manifest_path)
    comparisons: list[VisualComparison] = []
    image_records: list[VisualImageEvidence] = []
    image_paths: dict[str, tuple[Path, Path]] = {}
    for sample in manifest.samples:
        reference = _resolve_evidence_file(root, sample.reference_image)
        candidate = _resolve_evidence_file(root, sample.candidate_image)
        reference_size = _png_size(reference)
        candidate_size = _png_size(candidate)
        if reference_size != candidate_size:
            raise VisualEvidenceError(f"sample {sample.sample_id} images must have identical dimensions")
        reference_hash = _sha256_file(reference)
        candidate_hash = _sha256_file(candidate)
        comparisons.append(
            VisualComparison(
                sample_id=sample.sample_id,
                reference_image_sha256=reference_hash,
                candidate_image_sha256=candidate_hash,
                reference_regions=sample.reference_regions,
                candidate_regions=sample.candidate_regions,
            )
        )
        image_records.append(
            VisualImageEvidence(
                sample_id=sample.sample_id,
                reference_image=sample.reference_image,
                candidate_image=sample.candidate_image,
                reference_image_sha256=reference_hash,
                candidate_image_sha256=candidate_hash,
                width=reference_size[0],
                height=reference_size[1],
                observation_source=sample.observation_source,
                observation_reference=sample.observation_reference,
            )
        )
        image_paths[sample.sample_id] = (reference, candidate)
    bound_judge = None if judge is None else _BoundImageJudge(judge, image_paths)
    gate = evaluate_visual_gate(
        manifest.profile,
        comparisons,
        judge=bound_judge,
        policy=manifest.policy,
    )
    report = VisualEvidenceReport(
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        authorization_reference=authorization_reference,
        manifest_sha256=_sha256_file(manifest_path),
        profile=manifest.profile,
        policy=manifest.policy,
        images=tuple(image_records),
        gate=gate,
        judge_provider=None if judge is None else judge.provider_name,
    )
    _write_report(report, output_path)
    return report


__all__ = [
    "CommandImageVisualJudge",
    "ImageVisualJudge",
    "ManualVisualAnnotationSample",
    "ManualVisualAnnotations",
    "VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION",
    "VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION",
    "VISUAL_EVIDENCE_REPORT_SCHEMA_VERSION",
    "VisualEvidenceError",
    "VisualEvidenceManifest",
    "VisualEvidenceReport",
    "VisualEvidenceSample",
    "VisualImageEvidence",
    "VisualObservationSource",
    "load_manual_visual_annotations",
    "load_visual_evidence_manifest",
    "prepare_visual_evidence_manifest",
    "run_visual_evidence",
]
