from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import struct
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from .segments import JsonValue, normalize_relative_path
from .visual import (
    DEFAULT_OCR_RESIDUAL_ALLOWLIST,
    OcrBox,
    OcrFrame,
    OcrProvider,
    detect_english_residuals,
)
from .renpy_visual_capture import (
    RENPY_CAPTURE_PLAN_SCHEMA_VERSION,
    RENPY_CAPTURE_REPORT_SCHEMA_VERSION,
    RendererObservation,
)
from .visual_style import (
    TextRegionObservation,
    VisualComparison,
    VisualCheck,
    VisualGateDecision,
    VisualGateResult,
    VisualHardGatePolicy,
    VisualJudgeResult,
    VisualStyleProfile,
    evaluate_visual_gate,
)


VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION = "hanengine.visual-evidence-annotations/v1"
VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION = "hanengine.visual-evidence-manifest/v3"
VISUAL_EVIDENCE_REPORT_SCHEMA_VERSION = "hanengine.visual-evidence-report/v2"
VISUAL_OCR_OBSERVATION_SCHEMA_VERSION = "hanengine.visual-ocr-observation/v2"
_LEGACY_VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION = "hanengine.visual-evidence-manifest/v2"
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


def _load_ocr_image(path: Path) -> object:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.convert("RGB")
    except Exception as exc:
        raise VisualEvidenceError("OCR image loading is unavailable") from exc


def _ocr_box_payload(box: OcrBox, residual: bool) -> dict[str, JsonValue]:
    return {
        "x": box.x,
        "y": box.y,
        "width": box.width,
        "height": box.height,
        "text": box.text,
        "line_count": len(box.text.splitlines()),
        "confidence": box.confidence,
        "residual_english": residual,
    }


def _ocr_frame_payload(
    frame: OcrFrame, residuals: tuple[OcrBox, ...]
) -> dict[str, JsonValue]:
    residual_set = set(residuals)
    return {
        "background_fingerprint": frame.background_fingerprint,
        "box_count": len(frame.boxes),
        "boxes": [
            _ocr_box_payload(box, box in residual_set)
            for box in frame.boxes
        ],
        "residual_texts": [box.text for box in residuals],
    }


def _ocr_provider_metadata(provider: OcrProvider) -> tuple[str, str]:
    name = getattr(provider, "provider_name", provider.__class__.__name__)
    version = getattr(provider, "provider_version", "unknown")
    if callable(version):
        version = version()
    return str(name), str(version)


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
    reference_renderer_observation: RendererObservation | None = None
    candidate_renderer_observation: RendererObservation | None = None

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
        renderer_observations = (
            self.reference_renderer_observation,
            self.candidate_renderer_observation,
        )
        if any(item is None for item in renderer_observations) and any(
            item is not None for item in renderer_observations
        ):
            raise ValueError("reference and candidate renderer observations must be paired")
        if any(
            item is not None and not isinstance(item, RendererObservation)
            for item in renderer_observations
        ):
            raise TypeError("renderer observations must be RendererObservation values")

    def to_dict(self) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "sample_id": self.sample_id,
            "reference_image": self.reference_image,
            "candidate_image": self.candidate_image,
            "observation_source": self.observation_source.value,
            "observation_reference": self.observation_reference,
            "reference_regions": [item.to_dict() for item in self.reference_regions],
            "candidate_regions": [item.to_dict() for item in self.candidate_regions],
        }
        if self.reference_renderer_observation is not None:
            payload["reference_renderer_observation"] = (
                self.reference_renderer_observation.to_dict()
            )
            payload["candidate_renderer_observation"] = (
                self.candidate_renderer_observation.to_dict()
            )
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualEvidenceSample":
        payload = _mapping(payload, "visual_evidence_sample")
        base_fields = {
            "sample_id",
            "reference_image",
            "candidate_image",
            "observation_source",
            "observation_reference",
            "reference_regions",
            "candidate_regions",
        }
        renderer_fields = {
            "reference_renderer_observation",
            "candidate_renderer_observation",
        }
        if set(payload) not in (base_fields, base_fields | renderer_fields):
            raise ValueError("visual_evidence_sample payload fields do not match schema")
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
            reference_renderer_observation=(
                RendererObservation.from_dict(
                    _mapping(
                        payload["reference_renderer_observation"],
                        "reference_renderer_observation",
                    )
                )
                if "reference_renderer_observation" in payload
                else None
            ),
            candidate_renderer_observation=(
                RendererObservation.from_dict(
                    _mapping(
                        payload["candidate_renderer_observation"],
                        "candidate_renderer_observation",
                    )
                )
                if "candidate_renderer_observation" in payload
                else None
            ),
        )


@dataclass(frozen=True)
class VisualEvidenceManifest:
    profile: VisualStyleProfile
    policy: VisualHardGatePolicy
    samples: tuple[VisualEvidenceSample, ...]
    schema_version: str = VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version not in {
            VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION,
            _LEGACY_VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION,
        }:
            raise ValueError("visual evidence manifest schema_version is unsupported")
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
        if self.schema_version == VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION and any(
            item.reference_renderer_observation is None for item in samples
        ):
            raise ValueError("visual evidence manifest v3 requires renderer observations")
        if self.schema_version == _LEGACY_VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION and any(
            item.reference_renderer_observation is not None for item in samples
        ):
            raise ValueError("visual evidence manifest v2 must not contain renderer observations")

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

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _plain_string(self.sample_id, "sample_id"))
        object.__setattr__(
            self, "reference_image", normalize_relative_path(self.reference_image)
        )
        object.__setattr__(
            self, "candidate_image", normalize_relative_path(self.candidate_image)
        )
        if self.reference_image == self.candidate_image:
            raise ValueError("reference_image and candidate_image must differ")
        object.__setattr__(
            self,
            "reference_image_sha256",
            _sha256_string(self.reference_image_sha256, "reference_image_sha256"),
        )
        object.__setattr__(
            self,
            "candidate_image_sha256",
            _sha256_string(self.candidate_image_sha256, "candidate_image_sha256"),
        )
        object.__setattr__(self, "width", _positive_int(self.width, "width"))
        object.__setattr__(self, "height", _positive_int(self.height, "height"))
        if not isinstance(self.observation_source, VisualObservationSource):
            raise TypeError("observation_source must be VisualObservationSource")
        object.__setattr__(
            self,
            "observation_reference",
            normalize_relative_path(self.observation_reference),
        )

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

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualImageEvidence":
        payload = _mapping(payload, "visual_image_evidence")
        _exact_keys(
            payload,
            (
                "sample_id",
                "reference_image",
                "candidate_image",
                "reference_image_sha256",
                "candidate_image_sha256",
                "width",
                "height",
                "observation_source",
                "observation_reference",
            ),
            "visual_image_evidence",
        )
        try:
            observation_source = VisualObservationSource(payload["observation_source"])
        except (TypeError, ValueError) as exc:
            raise ValueError("observation_source is invalid") from exc
        return cls(
            sample_id=payload["sample_id"],
            reference_image=payload["reference_image"],
            candidate_image=payload["candidate_image"],
            reference_image_sha256=payload["reference_image_sha256"],
            candidate_image_sha256=payload["candidate_image_sha256"],
            width=payload["width"],
            height=payload["height"],
            observation_source=observation_source,
            observation_reference=payload["observation_reference"],
        )


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


class ZhipuImageVisualJudge:
    """Call a configured Zhipu GLM vision model for non-text visual review.

    Residual-language OCR and deterministic layout gates run before this judge.
    A model response can therefore only add an escalation/failure, never bypass
    a hard gate. Screenshots are JPEG-compressed only for the remote request;
    evidence hashes and local validation continue to use the original files.
    """

    DEFAULT_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    DEFAULT_MODEL = "glm-4.6v"
    DEFAULT_KEY_ENV = "ZHIPU_API_KEY"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_seconds: int = 180,
        jpeg_quality: int = 90,
    ) -> None:
        self.model = _plain_string(model, "model")
        self.endpoint = _plain_string(endpoint, "endpoint")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 900:
            raise ValueError("timeout_seconds must be between 1 and 900")
        if isinstance(jpeg_quality, bool) or not isinstance(jpeg_quality, int) or not 60 <= jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be between 60 and 100")
        key = os.environ.get(self.DEFAULT_KEY_ENV) if api_key is None else api_key
        self._api_key = _plain_string(key, "api_key")
        self.timeout_seconds = timeout_seconds
        self.jpeg_quality = jpeg_quality
        self.provider_name = f"zhipu:{self.model}"

    @staticmethod
    def _image_data_url(path: Path, quality: int) -> str:
        try:
            from PIL import Image

            encoded = io.BytesIO()
            with Image.open(path) as image:
                image.convert("RGB").save(
                    encoded,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                )
        except (ImportError, OSError) as exc:
            raise VisualEvidenceError("Pillow is required for the Zhipu visual judge") from exc
        return "data:image/jpeg;base64," + base64.b64encode(encoded.getvalue()).decode("ascii")

    def judge_images(
        self,
        profile: VisualStyleProfile,
        comparison: VisualComparison,
        reference_image: Path,
        candidate_image: Path,
    ) -> VisualJudgeResult:
        prompt = (
            "你是游戏本地化发布前的视觉复核器。第一张图是原文参考，第二张图是简体中文候选。\n"
            "先独立观察候选图，再逐个文本区域与参考图对照。必须逐项检查截断、溢出、遮挡、缺字、乱码、"
            "错误换行和明显破坏可读性的布局/视觉问题。两行文字的字形相互穿插、压住或无法分别阅读算 overlap；"
            "把正常词语拆成孤立单字行算 bad_wrapping；正文相对参考图或同页标题明显过小、过淡、低对比度算 style_readability。"
            "不要把 English、Español、日本語等语言名称或 Ren'Py/品牌名当成漏翻；不要根据截图之外的信息猜测。\n"
            f"配置模型名必须原样写入 model：{self.model}。\n"
            "只输出且只能输出以下 JSON 字段："
            '{"decision":"pass|escalate|fail","style_score":0到1,"confidence":0到1,'
            f'"model":"{self.model}","issues":["问题代码: 截图证据"]}}。'
            "问题代码只使用 clipped、overflow、overlap、missing_glyphs、garbled_text、"
            "bad_wrapping、style_readability。没有问题时 decision=pass 且 issues=[]。"
        )
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": self._image_data_url(reference_image, self.jpeg_quality)}},
                        {"type": "image_url", "image_url": {"url": self._image_data_url(candidate_image, self.jpeg_quality)}},
                    ],
                }
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            import requests
        except ImportError as exc:
            raise VisualEvidenceError("requests is required for the Zhipu visual judge") from exc
        response_payload: Mapping[str, object] | None = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 429 and attempt < 2:
                    last_error = VisualEvidenceError("Zhipu visual judge is rate limited")
                    time.sleep((2, 5, 10)[attempt])
                    continue
                if not 200 <= response.status_code < 300:
                    raise VisualEvidenceError(
                        f"Zhipu visual judge HTTP {response.status_code}: {response.text[:500]}"
                    )
                parsed = response.json()
                response_payload = _mapping(parsed, "zhipu_response")
                break
            except (OSError, requests.RequestException) as exc:
                last_error = exc
                if attempt == 2:
                    raise VisualEvidenceError("Zhipu visual judge request failed") from exc
                time.sleep((2, 5, 10)[attempt])
            except (json.JSONDecodeError, TypeError) as exc:
                raise VisualEvidenceError("Zhipu visual judge returned invalid JSON") from exc
        if response_payload is None:
            raise VisualEvidenceError("Zhipu visual judge returned no response") from last_error
        try:
            text = response_payload["choices"][0]["message"]["content"]
            result = VisualJudgeResult.from_dict(_mapping(json.loads(text), "visual_judge_result"))
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise VisualEvidenceError("Zhipu visual judge returned invalid JSON") from exc
        # Do not trust a model's self-reported identity in the persisted report.
        return VisualJudgeResult(
            decision=result.decision,
            style_score=result.style_score,
            confidence=result.confidence,
            model=self.model,
            issues=result.issues,
        )


class _BoundImageJudge:
    def __init__(self, judge: ImageVisualJudge, images: Mapping[str, tuple[Path, Path]]) -> None:
        self.image_judge = judge
        self.images = dict(images)

    def judge(self, profile: VisualStyleProfile, comparison: VisualComparison) -> VisualJudgeResult:
        reference, candidate = self.images[comparison.sample_id]
        return self.image_judge.judge_images(profile, comparison, reference, candidate)


def _renderer_region_id(region: object, index: int) -> str:
    region_id = getattr(region, "region_id", None)
    return region_id if region_id is not None else f"legacy:{index}"


def _renderer_rect(region: object) -> dict[str, JsonValue]:
    return {
        "x": round(region.x, 3),
        "y": round(region.y, 3),
        "width": round(region.width, 3),
        "height": round(region.height, 3),
    }


def _renderer_intersection(left: object, right: object) -> dict[str, float] | None:
    x = max(left.x, right.x)
    y = max(left.y, right.y)
    width = min(left.x + left.width, right.x + right.width) - x
    height = min(left.y + left.height, right.y + right.height) - y
    if width <= 0 or height <= 0:
        return None
    area = width * height
    left_ratio = area / (left.width * left.height)
    right_ratio = area / (right.width * right.height)
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "area": area,
        "left_ratio": left_ratio,
        "right_ratio": right_ratio,
        "left_visible_ratio": 1.0 - left_ratio,
        "right_visible_ratio": 1.0 - right_ratio,
        "left_visible_area": left.width * left.height - area,
        "right_visible_area": right.width * right.height - area,
        "smaller_region_ratio": max(left_ratio, right_ratio),
    }


def _renderer_path_contains(left: object, right: object) -> bool:
    left_path = getattr(left, "render_path", None)
    right_path = getattr(right, "render_path", None)
    if left_path is None or right_path is None or left_path == right_path:
        return False
    shorter, longer = sorted((left_path, right_path), key=len)
    return len(shorter) < len(longer) and longer[: len(shorter)] == shorter


def _renderer_duplicate_layer(left: object, right: object) -> bool:
    if " ".join(left.text.split()) != " ".join(right.text.split()):
        return False
    geometry_delta = max(
        abs(left.x - right.x),
        abs(left.y - right.y),
        abs(left.width - right.width),
        abs(left.height - right.height),
    )
    if geometry_delta > 2.0:
        return False
    if left.baseline is None or right.baseline is None:
        return True
    return abs((left.y + left.baseline) - (right.y + right.baseline)) <= 2.0


def _renderer_baselines_collide(
    left: object,
    right: object,
    intersection: Mapping[str, float],
) -> bool:
    minimum_height = min(left.height, right.height)
    vertical_ratio = intersection["height"] / minimum_height
    if vertical_ratio < 0.25:
        return False
    if left.baseline is None or right.baseline is None:
        left_center = left.y + left.height / 2
        right_center = right.y + right.height / 2
        estimated_line_height = min(minimum_height, 32.0)
        return abs(left_center - right_center) <= max(3.0, estimated_line_height * 0.5)
    left_baseline = left.y + left.baseline
    right_baseline = right.y + right.baseline
    estimated_line_height = min(left.baseline, right.baseline, 32.0)
    return abs(left_baseline - right_baseline) <= max(4.0, estimated_line_height * 0.6)


def _renderer_suspicious_overlap(
    left: object,
    right: object,
    intersection: Mapping[str, float] | None,
) -> bool:
    return bool(
        intersection is not None
        and intersection["area"] >= 16.0
        and intersection["smaller_region_ratio"] >= 0.20
        and not _renderer_path_contains(left, right)
        and not _renderer_duplicate_layer(left, right)
        and _renderer_baselines_collide(left, right, intersection)
    )


def _renderer_pair_map(
    observation: RendererObservation,
    region_ids: Sequence[str] | None = None,
) -> dict[tuple[str, str], dict[str, float]]:
    regions = observation.text_regions
    if region_ids is None:
        region_ids = tuple(
            _renderer_region_id(region, index) for index, region in enumerate(regions)
        )
    else:
        region_ids = tuple(region_ids)
        if len(region_ids) != len(regions):
            raise ValueError("renderer region IDs must match text regions")
    overlaps: dict[tuple[str, str], dict[str, float]] = {}
    for left_index, left in enumerate(regions):
        for right_index in range(left_index + 1, len(regions)):
            right = regions[right_index]
            intersection = _renderer_intersection(left, right)
            if not _renderer_suspicious_overlap(left, right, intersection):
                continue
            pair = tuple(
                sorted(
                    (
                        region_ids[left_index],
                        region_ids[right_index],
                    )
                )
            )
            overlaps[pair] = intersection
    return overlaps


def _legacy_renderer_region_ids(
    reference: RendererObservation,
    candidate: RendererObservation,
) -> tuple[str, ...]:
    """Match v1 nodes to reference geometry without inventing hierarchy."""

    reference_regions = reference.text_regions
    candidate_regions = candidate.text_regions
    unmatched_reference = set(range(len(reference_regions)))
    unmatched_candidate = set(range(len(candidate_regions)))
    assignments: dict[int, int] = {}

    def normalized_text(region: object) -> str:
        return " ".join(region.text.split())

    def geometry_key(candidate_index: int, reference_index: int) -> tuple[float, float, int, int]:
        source = reference_regions[reference_index]
        target = candidate_regions[candidate_index]
        position_delta = abs(source.x - target.x) + abs(source.y - target.y)
        size_delta = abs(source.width - target.width) + abs(source.height - target.height)
        return (position_delta, size_delta, candidate_index, reference_index)

    for require_same_text in (True, False):
        edges = []
        for candidate_index in unmatched_candidate:
            for reference_index in unmatched_reference:
                if require_same_text and (
                    not normalized_text(candidate_regions[candidate_index])
                    or normalized_text(candidate_regions[candidate_index])
                    != normalized_text(reference_regions[reference_index])
                ):
                    continue
                edges.append(geometry_key(candidate_index, reference_index))
        for _, _, candidate_index, reference_index in sorted(edges):
            if (
                candidate_index not in unmatched_candidate
                or reference_index not in unmatched_reference
            ):
                continue
            assignments[candidate_index] = reference_index
            unmatched_candidate.remove(candidate_index)
            unmatched_reference.remove(reference_index)

    return tuple(
        (
            f"legacy:{assignments[index]}"
            if index in assignments
            else f"candidate:{index}"
        )
        for index in range(len(candidate_regions))
    )


def _renderer_region_details(region: object, region_id: str) -> dict[str, JsonValue]:
    text = " ".join(region.text.split())
    absolute_baseline = (
        None if region.baseline is None else round(region.y + region.baseline, 3)
    )
    return {
        "region_id": region_id,
        "text": text[:80],
        "rect": _renderer_rect(region),
        "baseline": absolute_baseline,
        "render_path": (
            None if region.render_path is None else list(region.render_path)
        ),
        "render_depth": (
            None if region.render_path is None else len(region.render_path)
        ),
        "z_index": region.z_index,
    }


def run_renderer_overlap_hard_gate(
    sample_id: str,
    reference: RendererObservation,
    candidate: RendererObservation,
    *,
    allowed_pairs: Sequence[Sequence[str]] = (),
) -> tuple[VisualCheck, ...]:
    """Block new or materially worsened renderer text collisions."""

    sample_id = _plain_string(sample_id, "sample_id")
    if not isinstance(reference, RendererObservation) or not isinstance(
        candidate, RendererObservation
    ):
        raise TypeError("renderer overlap gate requires RendererObservation values")
    if (
        reference.coordinate_space != candidate.coordinate_space
        or reference.viewport_width != candidate.viewport_width
        or reference.viewport_height != candidate.viewport_height
    ):
        return (
            VisualCheck(
                "renderer_observation_geometry",
                False,
                "reference and candidate renderer observation geometry differs",
                details={"sample_id": sample_id},
            ),
        )
    candidate_ids = (
        _legacy_renderer_region_ids(reference, candidate)
        if reference.text_regions
        and candidate.text_regions
        and reference.text_regions[0].region_id is None
        and candidate.text_regions[0].region_id is None
        else tuple(
            _renderer_region_id(region, index)
            for index, region in enumerate(candidate.text_regions)
        )
    )
    candidate_regions = dict(zip(candidate_ids, candidate.text_regions, strict=True))
    normalized_allowed = {
        tuple(sorted(tuple(pair))) for pair in allowed_pairs
    }
    invalid_allowed = sorted(
        pair
        for pair in normalized_allowed
        if len(pair) != 2 or not set(pair).issubset(candidate_regions)
    )
    if invalid_allowed:
        return (
            VisualCheck(
                "renderer_overlap_allowlist",
                False,
                "renderer overlap allowlist references unknown regions",
                details={
                    "sample_id": sample_id,
                    "unknown_pairs": [list(pair) for pair in invalid_allowed],
                },
            ),
        )
    reference_overlaps = _renderer_pair_map(reference)
    candidate_overlaps = _renderer_pair_map(candidate, candidate_ids)
    failures: list[VisualCheck] = []
    for pair, intersection in sorted(candidate_overlaps.items()):
        if pair in normalized_allowed:
            continue
        previous = reference_overlaps.get(pair)
        materially_worse = previous is None or (
            intersection["area"] >= previous["area"] + 16.0
            and intersection["smaller_region_ratio"]
            >= previous["smaller_region_ratio"] + 0.15
        )
        if not materially_worse:
            continue
        left = candidate_regions[pair[0]]
        right = candidate_regions[pair[1]]
        foreground = (
            None
            if all(candidate_regions[region_id].z_index is None for region_id in pair)
            else max(
                pair,
                key=lambda region_id: (
                    candidate_regions[region_id].z_index
                    if candidate_regions[region_id].z_index is not None
                    else -1
                ),
            )
        )
        overlap_details = {
            key: round(value, 4) for key, value in intersection.items()
        }
        failures.append(
            VisualCheck(
                "renderer_text_overlap",
                False,
                (
                    f"renderer text regions overlap in {sample_id}: "
                    f"{pair[0]} and {pair[1]} "
                    f"({intersection['smaller_region_ratio']:.1%} of smaller region)"
                ),
                region_id=pair[0],
                details={
                    "sample_id": sample_id,
                    "regions": [
                        _renderer_region_details(left, pair[0]),
                        _renderer_region_details(right, pair[1]),
                    ],
                    "intersection": overlap_details,
                    "reference_intersection": (
                        None
                        if previous is None
                        else {key: round(value, 4) for key, value in previous.items()}
                    ),
                    "foreground_region_id": foreground,
                },
            )
        )
    if failures:
        return tuple(failures)
    return (
        VisualCheck(
            "renderer_text_overlap",
            True,
            f"renderer text overlap scan passed for {sample_id}",
            details={
                "sample_id": sample_id,
                "candidate_pair_count": len(candidate_overlaps),
                "reference_pair_count": len(reference_overlaps),
                "renderer_schema_version": candidate.schema_version,
            },
        ),
    )


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

    def __post_init__(self) -> None:
        if self.schema_version != VISUAL_EVIDENCE_REPORT_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {VISUAL_EVIDENCE_REPORT_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "created_at", _plain_string(self.created_at, "created_at"))
        object.__setattr__(
            self,
            "authorization_reference",
            _plain_string(self.authorization_reference, "authorization_reference"),
        )
        object.__setattr__(
            self,
            "manifest_sha256",
            _sha256_string(self.manifest_sha256, "manifest_sha256"),
        )
        if not isinstance(self.profile, VisualStyleProfile):
            raise TypeError("profile must be VisualStyleProfile")
        if not isinstance(self.policy, VisualHardGatePolicy):
            raise TypeError("policy must be VisualHardGatePolicy")
        images = tuple(self.images)
        if not images or any(not isinstance(item, VisualImageEvidence) for item in images):
            raise ValueError("images must contain VisualImageEvidence values")
        sample_ids = [item.sample_id for item in images]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("images must contain unique sample IDs")
        object.__setattr__(self, "images", images)
        if not isinstance(self.gate, VisualGateResult):
            raise TypeError("gate must be VisualGateResult")
        comparison_ids = [item.sample_id for item in self.gate.comparisons]
        if tuple(sample_ids) != self.profile.scenarios or comparison_ids != sample_ids:
            raise ValueError(
                "report profile, images, and gate comparisons must contain the same ordered samples"
            )
        comparisons = {
            item.sample_id: item for item in self.gate.comparisons
        }
        for image in images:
            comparison = comparisons[image.sample_id]
            if (
                image.reference_image_sha256 != comparison.reference_image_sha256
                or image.candidate_image_sha256 != comparison.candidate_image_sha256
            ):
                raise ValueError("report image hashes must match gate comparisons")
        if self.judge_provider is not None:
            object.__setattr__(
                self,
                "judge_provider",
                _plain_string(self.judge_provider, "judge_provider"),
            )

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

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualEvidenceReport":
        payload = _mapping(payload, "visual_evidence_report")
        _exact_keys(
            payload,
            (
                "schema_version",
                "created_at",
                "authorization_reference",
                "manifest_sha256",
                "profile",
                "policy",
                "images",
                "gate",
                "judge_provider",
            ),
            "visual_evidence_report",
        )
        images = _mapping_sequence(payload["images"], "images")
        return cls(
            schema_version=payload["schema_version"],
            created_at=payload["created_at"],
            authorization_reference=payload["authorization_reference"],
            manifest_sha256=payload["manifest_sha256"],
            profile=VisualStyleProfile.from_dict(_mapping(payload["profile"], "profile")),
            policy=VisualHardGatePolicy.from_dict(_mapping(payload["policy"], "policy")),
            images=tuple(VisualImageEvidence.from_dict(item) for item in images),
            gate=VisualGateResult.from_dict(_mapping(payload["gate"], "gate")),
            judge_provider=payload["judge_provider"],
        )


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
    assertions: list[tuple[str, str, RendererObservation]] = []
    for assertion in assertion_payloads:
        _exact_keys(
            assertion,
            (
                "expected_screen",
                "observed_screens",
                "passed",
                "renderer_observation",
                "sample_id",
            ),
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
        try:
            renderer_observation = RendererObservation.from_dict(
                _mapping(assertion["renderer_observation"], "renderer_observation")
            )
        except (TypeError, ValueError) as exc:
            raise VisualEvidenceError(
                f"capture report {variant} renderer observation is invalid"
            ) from exc
        assertions.append((sample_id, expected_screen, renderer_observation))
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
    for assertion, screenshot in zip(assertions, screenshots, strict=True):
        observation = assertion[2]
        if (
            observation.coordinate_space != "capture_pixels"
            or observation.viewport_width != screenshot["width"]
            or observation.viewport_height != screenshot["height"]
        ):
            raise VisualEvidenceError(
                f"capture report {variant} renderer viewport does not match screenshot"
            )
        screenshot["renderer_observation"] = observation
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
            "renderer_observation_verified",
            "schema_version",
            "semantic_alignment_verified",
        ),
        "capture_report",
    )
    if (
        capture_payload["schema_version"] != RENPY_CAPTURE_REPORT_SCHEMA_VERSION
        or capture_payload["plan_schema_version"] != RENPY_CAPTURE_PLAN_SCHEMA_VERSION
    ):
        raise VisualEvidenceError(
            "capture report must use the current Ren'Py report and plan schemas"
        )
    if (
        capture_payload["capture_passed"] is not True
        or capture_payload["semantic_alignment_verified"] is not True
        or capture_payload["renderer_observation_verified"] is not True
        or capture_payload["passed"] is not True
    ):
        raise VisualEvidenceError(
            "capture report must have verified semantic alignment and renderer observation"
        )
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
                reference_renderer_observation=reference_image[
                    "renderer_observation"
                ],
                candidate_renderer_observation=candidate_image[
                    "renderer_observation"
                ],
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
    ocr_provider: OcrProvider | None = None,
    ocr_language: str | None = None,
    ocr_allowlist: Sequence[str] = (),
    ocr_minimum_confidence: float = 0.80,
    ocr_report_path: Path | None = None,
    ocr_image_loader: Callable[[Path], object] = _load_ocr_image,
) -> VisualEvidenceReport:
    authorization_reference = _plain_string(authorization_reference, "authorization_reference")
    manifest_path = _regular_input_file(manifest_path, "manifest_path")
    root = manifest_path.parent.resolve(strict=True)
    manifest = load_visual_evidence_manifest(manifest_path)
    if isinstance(judge, ZhipuImageVisualJudge) and ocr_provider is None:
        raise ValueError("Zhipu visual judge requires a local OCR provider")
    if (
        isinstance(ocr_minimum_confidence, bool)
        or not isinstance(ocr_minimum_confidence, (int, float))
        or not 0.0 <= ocr_minimum_confidence <= 1.0
    ):
        raise ValueError("ocr_minimum_confidence must be in [0.0, 1.0]")
    if ocr_provider is not None:
        if not isinstance(ocr_language, str) or not ocr_language.strip():
            raise ValueError("ocr_language is required when OCR observation is enabled")
        if isinstance(ocr_allowlist, (str, bytes)):
            raise TypeError("ocr_allowlist must be a sequence of strings")
        ocr_allowlist = tuple(ocr_allowlist)
        if not callable(ocr_image_loader):
            raise TypeError("ocr_image_loader must be callable")
    elif (
        ocr_language is not None
        or ocr_allowlist
        or ocr_minimum_confidence != 0.80
        or ocr_report_path is not None
    ):
        raise ValueError("OCR options require an OCR provider")
    comparisons: list[VisualComparison] = []
    image_records: list[VisualImageEvidence] = []
    image_paths: dict[str, tuple[Path, Path]] = {}
    renderer_checks: list[VisualCheck] = []
    ocr_checks: list[VisualCheck] = []
    ocr_samples: list[dict[str, JsonValue]] = []
    if isinstance(judge, ZhipuImageVisualJudge):
        missing_renderer_samples = [
            sample.sample_id
            for sample in manifest.samples
            if sample.reference_renderer_observation is None
        ]
        renderer_checks.append(
            VisualCheck(
                "renderer_observation_coverage",
                not missing_renderer_samples,
                (
                    "all model-reviewed scenes contain renderer observations"
                    if not missing_renderer_samples
                    else "model review requires renderer observations for every scene"
                ),
                details={"missing_sample_ids": missing_renderer_samples},
            )
        )
    for sample in manifest.samples:
        reference = _resolve_evidence_file(root, sample.reference_image)
        candidate = _resolve_evidence_file(root, sample.candidate_image)
        reference_size = _png_size(reference)
        candidate_size = _png_size(candidate)
        if reference_size != candidate_size:
            raise VisualEvidenceError(f"sample {sample.sample_id} images must have identical dimensions")
        for observation in (
            sample.reference_renderer_observation,
            sample.candidate_renderer_observation,
        ):
            if observation is not None and (
                observation.coordinate_space != "capture_pixels"
                or (observation.viewport_width, observation.viewport_height)
                != reference_size
            ):
                raise VisualEvidenceError(
                    f"sample {sample.sample_id} renderer viewport does not match images"
                )
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
        if sample.reference_renderer_observation is not None:
            renderer_checks.extend(
                run_renderer_overlap_hard_gate(
                    sample.sample_id,
                    sample.reference_renderer_observation,
                    sample.candidate_renderer_observation,
                    allowed_pairs=manifest.policy.allowed_renderer_overlap_pairs.get(
                        sample.sample_id, ()
                    ),
                )
            )
        if ocr_provider is not None:
            try:
                reference_frame = ocr_provider.recognize(
                    ocr_image_loader(reference),
                    language=ocr_language.strip(),
                )
                candidate_frame = ocr_provider.recognize(
                    ocr_image_loader(candidate),
                    language=ocr_language.strip(),
                )
            except Exception as exc:
                raise VisualEvidenceError(
                    f"OCR observation failed for sample {sample.sample_id}"
                ) from exc
            if not isinstance(reference_frame, OcrFrame) or not isinstance(
                candidate_frame, OcrFrame
            ):
                raise VisualEvidenceError("OCR provider must return OcrFrame values")
            reference_residuals = detect_english_residuals(
                reference_frame,
                allowlist=ocr_allowlist,
                minimum_confidence=ocr_minimum_confidence,
            )
            candidate_residuals = detect_english_residuals(
                candidate_frame,
                allowlist=ocr_allowlist,
                minimum_confidence=ocr_minimum_confidence,
            )
            reference_confident_boxes = tuple(
                box
                for box in reference_frame.boxes
                if box.confidence >= ocr_minimum_confidence
            )
            candidate_confident_boxes = tuple(
                box
                for box in candidate_frame.boxes
                if box.confidence >= ocr_minimum_confidence
            )
            candidate_covered = (
                bool(candidate_confident_boxes) or not reference_confident_boxes
            )
            residual_preview = ", ".join(
                repr(box.text) for box in candidate_residuals[:5]
            )
            ocr_checks.extend(
                (
                    VisualCheck(
                        "ocr_candidate_coverage",
                        candidate_covered,
                        "candidate OCR detected text"
                        if candidate_covered
                        else "candidate OCR detected no text while reference OCR did",
                    ),
                    VisualCheck(
                        "ocr_candidate_residual_text",
                        not candidate_residuals,
                        "candidate OCR found no residual English natural language"
                        if not candidate_residuals
                        else f"candidate OCR found residual English: {residual_preview}",
                    ),
                )
            )
            ocr_samples.append(
                {
                    "sample_id": sample.sample_id,
                    "reference": _ocr_frame_payload(
                        reference_frame, reference_residuals
                    ),
                    "candidate": _ocr_frame_payload(
                        candidate_frame, candidate_residuals
                    ),
                }
            )
    if ocr_provider is not None:
        ocr_provider_name, ocr_provider_version = _ocr_provider_metadata(
            ocr_provider
        )
        output_destination = output_path.expanduser().absolute().resolve(strict=False)
        ocr_path = (
            output_destination.with_name("ocr-observation.json")
            if ocr_report_path is None
            else ocr_report_path.expanduser().absolute().resolve(strict=False)
        )
        if ocr_path.parent.resolve(strict=False) != root:
            raise VisualEvidenceError(
                "ocr_report_path must be in the capture evidence directory"
            )
        protected_paths = {
            manifest_path.resolve(strict=True),
            output_destination,
            *(
                path.resolve(strict=True)
                for pair in image_paths.values()
                for path in pair
            ),
        }
        if ocr_path in protected_paths:
            raise VisualEvidenceError(
                "ocr_report_path must not replace the manifest, report, or evidence images"
            )
        _write_json(
            {
                "schema_version": VISUAL_OCR_OBSERVATION_SCHEMA_VERSION,
                "created_at": datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "provider": ocr_provider_name,
                "provider_version": ocr_provider_version,
                "language": ocr_language.strip(),
                "minimum_confidence": ocr_minimum_confidence,
                "allowlist": sorted(
                    {
                        *DEFAULT_OCR_RESIDUAL_ALLOWLIST,
                        *(
                            " ".join(value.split()).casefold()
                            for value in ocr_allowlist
                        ),
                    }
                ),
                "samples": ocr_samples,
            },
            ocr_path,
        )
        ocr_checks.append(
            VisualCheck(
                "ocr_observation_artifact",
                True,
                f"OCR observations written to {ocr_path.relative_to(root).as_posix()}",
            )
        )
    bound_judge = None if judge is None else _BoundImageJudge(judge, image_paths)
    gate = evaluate_visual_gate(
        manifest.profile,
        comparisons,
        judge=bound_judge,
        policy=manifest.policy,
        judge_can_authorize_pass=not isinstance(judge, ZhipuImageVisualJudge),
        extra_hard_checks=(*renderer_checks, *ocr_checks),
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
    "ZhipuImageVisualJudge",
    "ManualVisualAnnotationSample",
    "ManualVisualAnnotations",
    "VISUAL_EVIDENCE_ANNOTATIONS_SCHEMA_VERSION",
    "VISUAL_EVIDENCE_MANIFEST_SCHEMA_VERSION",
    "VISUAL_EVIDENCE_REPORT_SCHEMA_VERSION",
    "VISUAL_OCR_OBSERVATION_SCHEMA_VERSION",
    "VisualEvidenceError",
    "VisualEvidenceManifest",
    "VisualEvidenceReport",
    "VisualEvidenceSample",
    "VisualImageEvidence",
    "VisualObservationSource",
    "load_manual_visual_annotations",
    "load_visual_evidence_manifest",
    "prepare_visual_evidence_manifest",
    "run_renderer_overlap_hard_gate",
    "run_visual_evidence",
]
