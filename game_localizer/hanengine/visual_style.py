from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .segments import JsonValue, normalize_relative_path


VISUAL_STYLE_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


class VisualGateDecision(str, Enum):
    PASS = "pass"
    ESCALATE = "escalate"
    BLOCKED = "blocked"


class VisualJudgeDecision(str, Enum):
    PASS = "pass"
    ESCALATE = "escalate"
    FAIL = "fail"


def _plain_string(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _sha256(value: object, name: str) -> str:
    value = _plain_string(value, name)
    if _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value.casefold()


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _positive(value: object, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _nonnegative(value: object, name: str) -> float:
    number = _finite(value, name)
    if number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _unit(value: object, name: str) -> float:
    number = _finite(value, name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be within [0.0, 1.0]")
    return number


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _strings(value: object, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of strings")
    items = tuple(value)
    for item in items:
        _plain_string(item, name, allow_empty=allow_empty)
    return items


def _json_object(value: object, name: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be a JSON object with string keys")
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        copied = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only finite JSON values") from exc
    if not isinstance(copied, dict):
        raise TypeError(f"{name} must be a JSON object")
    return copied


def _exact_keys(payload: Mapping[str, object], expected: Iterable[str], name: str) -> None:
    if set(payload) != set(expected):
        raise ValueError(f"{name} payload fields do not match schema")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} payload must be a mapping")
    return value


def _mapping_sequence(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of mappings")
    items = tuple(value)
    if any(not isinstance(item, Mapping) for item in items):
        raise TypeError(f"{name} must contain only mappings")
    return items


@dataclass(frozen=True)
class FontAssetReference:
    role: str
    relative_path: str
    sha256: str
    codepoint_ranges: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _plain_string(self.role, "role"))
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_path(self.relative_path),
        )
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "codepoint_ranges",
            _strings(self.codepoint_ranges, "codepoint_ranges"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "role": self.role,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "codepoint_ranges": list(self.codepoint_ranges),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "FontAssetReference":
        payload = _mapping(payload, "font_asset")
        _exact_keys(payload, ("role", "relative_path", "sha256", "codepoint_ranges"), "font_asset")
        return cls(
            role=payload["role"],
            relative_path=payload["relative_path"],
            sha256=payload["sha256"],
            codepoint_ranges=payload["codepoint_ranges"],
        )


@dataclass(frozen=True)
class TextMetrics:
    point_size: float
    line_height: float
    baseline: float
    letter_spacing: float = 0.0
    horizontal_scale: float = 1.0
    outline_width: float = 0.0
    shadow_offset: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "point_size", _positive(self.point_size, "point_size"))
        object.__setattr__(self, "line_height", _positive(self.line_height, "line_height"))
        object.__setattr__(self, "baseline", _finite(self.baseline, "baseline"))
        object.__setattr__(self, "letter_spacing", _finite(self.letter_spacing, "letter_spacing"))
        object.__setattr__(self, "horizontal_scale", _positive(self.horizontal_scale, "horizontal_scale"))
        object.__setattr__(self, "outline_width", _nonnegative(self.outline_width, "outline_width"))
        if (
            isinstance(self.shadow_offset, (str, bytes))
            or not isinstance(self.shadow_offset, Sequence)
            or len(self.shadow_offset) != 2
        ):
            raise TypeError("shadow_offset must contain two numbers")
        object.__setattr__(
            self,
            "shadow_offset",
            (_finite(self.shadow_offset[0], "shadow_offset.x"), _finite(self.shadow_offset[1], "shadow_offset.y")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "point_size": self.point_size,
            "line_height": self.line_height,
            "baseline": self.baseline,
            "letter_spacing": self.letter_spacing,
            "horizontal_scale": self.horizontal_scale,
            "outline_width": self.outline_width,
            "shadow_offset": list(self.shadow_offset),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "TextMetrics":
        payload = _mapping(payload, "text_metrics")
        _exact_keys(
            payload,
            (
                "point_size",
                "line_height",
                "baseline",
                "letter_spacing",
                "horizontal_scale",
                "outline_width",
                "shadow_offset",
            ),
            "text_metrics",
        )
        return cls(
            point_size=payload["point_size"],
            line_height=payload["line_height"],
            baseline=payload["baseline"],
            letter_spacing=payload["letter_spacing"],
            horizontal_scale=payload["horizontal_scale"],
            outline_width=payload["outline_width"],
            shadow_offset=payload["shadow_offset"],
        )


@dataclass(frozen=True)
class VisualStyleProfile:
    profile_id: str
    engine_id: str
    renderer: str
    source_fingerprint: str
    font_assets: tuple[FontAssetReference, ...]
    metrics: TextMetrics
    material_parameters: dict[str, JsonValue]
    scenarios: tuple[str, ...]
    schema_version: int = VISUAL_STYLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != VISUAL_STYLE_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {VISUAL_STYLE_SCHEMA_VERSION}")
        object.__setattr__(self, "profile_id", _plain_string(self.profile_id, "profile_id"))
        object.__setattr__(self, "engine_id", _plain_string(self.engine_id, "engine_id"))
        object.__setattr__(self, "renderer", _plain_string(self.renderer, "renderer"))
        object.__setattr__(self, "source_fingerprint", _sha256(self.source_fingerprint, "source_fingerprint"))
        assets = tuple(self.font_assets)
        if not assets or any(not isinstance(item, FontAssetReference) for item in assets):
            raise ValueError("font_assets must contain at least one FontAssetReference")
        roles = [item.role.casefold() for item in assets]
        if len(roles) != len(set(roles)):
            raise ValueError("font asset roles must be unique")
        object.__setattr__(self, "font_assets", assets)
        if not isinstance(self.metrics, TextMetrics):
            raise TypeError("metrics must be TextMetrics")
        object.__setattr__(self, "material_parameters", _json_object(self.material_parameters, "material_parameters"))
        scenarios = _strings(self.scenarios, "scenarios", allow_empty=False)
        if not scenarios:
            raise ValueError("scenarios must not be empty")
        if len(scenarios) != len(set(scenarios)):
            raise ValueError("scenarios must be unique")
        object.__setattr__(self, "scenarios", scenarios)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "engine_id": self.engine_id,
            "renderer": self.renderer,
            "source_fingerprint": self.source_fingerprint,
            "font_assets": [item.to_dict() for item in self.font_assets],
            "metrics": self.metrics.to_dict(),
            "material_parameters": _json_object(
                self.material_parameters,
                "material_parameters",
            ),
            "scenarios": list(self.scenarios),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualStyleProfile":
        payload = _mapping(payload, "visual_style_profile")
        _exact_keys(
            payload,
            (
                "schema_version",
                "profile_id",
                "engine_id",
                "renderer",
                "source_fingerprint",
                "font_assets",
                "metrics",
                "material_parameters",
                "scenarios",
            ),
            "visual_style_profile",
        )
        assets = payload["font_assets"]
        asset_payloads = _mapping_sequence(assets, "font_assets")
        return cls(
            schema_version=payload["schema_version"],
            profile_id=payload["profile_id"],
            engine_id=payload["engine_id"],
            renderer=payload["renderer"],
            source_fingerprint=payload["source_fingerprint"],
            font_assets=tuple(FontAssetReference.from_dict(item) for item in asset_payloads),
            metrics=TextMetrics.from_dict(_mapping(payload["metrics"], "text_metrics")),
            material_parameters=payload["material_parameters"],
            scenarios=payload["scenarios"],
        )


@dataclass(frozen=True)
class TextRegionObservation:
    region_id: str
    x: int
    y: int
    width: int
    height: int
    line_count: int
    baseline: float
    font_resolved: bool
    missing_codepoints: tuple[str, ...] = ()
    overflow: bool = False
    clipped: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_id", _plain_string(self.region_id, "region_id"))
        for name in ("x", "y"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in ("width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if isinstance(self.line_count, bool) or not isinstance(self.line_count, int) or self.line_count < 1:
            raise ValueError("line_count must be a positive integer")
        object.__setattr__(self, "baseline", _finite(self.baseline, "baseline"))
        object.__setattr__(self, "font_resolved", _bool(self.font_resolved, "font_resolved"))
        object.__setattr__(self, "missing_codepoints", _strings(self.missing_codepoints, "missing_codepoints"))
        object.__setattr__(self, "overflow", _bool(self.overflow, "overflow"))
        object.__setattr__(self, "clipped", _bool(self.clipped, "clipped"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "region_id": self.region_id,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "line_count": self.line_count,
            "baseline": self.baseline,
            "font_resolved": self.font_resolved,
            "missing_codepoints": list(self.missing_codepoints),
            "overflow": self.overflow,
            "clipped": self.clipped,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "TextRegionObservation":
        payload = _mapping(payload, "text_region")
        _exact_keys(
            payload,
            (
                "region_id",
                "x",
                "y",
                "width",
                "height",
                "line_count",
                "baseline",
                "font_resolved",
                "missing_codepoints",
                "overflow",
                "clipped",
            ),
            "text_region",
        )
        return cls(
            region_id=payload["region_id"],
            x=payload["x"],
            y=payload["y"],
            width=payload["width"],
            height=payload["height"],
            line_count=payload["line_count"],
            baseline=payload["baseline"],
            font_resolved=payload["font_resolved"],
            missing_codepoints=payload["missing_codepoints"],
            overflow=payload["overflow"],
            clipped=payload["clipped"],
        )


@dataclass(frozen=True)
class VisualComparison:
    sample_id: str
    reference_image_sha256: str
    candidate_image_sha256: str
    reference_regions: tuple[TextRegionObservation, ...]
    candidate_regions: tuple[TextRegionObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _plain_string(self.sample_id, "sample_id"))
        object.__setattr__(self, "reference_image_sha256", _sha256(self.reference_image_sha256, "reference_image_sha256"))
        object.__setattr__(self, "candidate_image_sha256", _sha256(self.candidate_image_sha256, "candidate_image_sha256"))
        for name in ("reference_regions", "candidate_regions"):
            value = tuple(getattr(self, name))
            if any(not isinstance(item, TextRegionObservation) for item in value):
                raise TypeError(f"{name} must contain TextRegionObservation values")
            if name == "reference_regions" and not value:
                raise ValueError("reference_regions must not be empty")
            ids = [item.region_id for item in value]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} must not contain duplicate region IDs")
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "sample_id": self.sample_id,
            "reference_image_sha256": self.reference_image_sha256,
            "candidate_image_sha256": self.candidate_image_sha256,
            "reference_regions": [item.to_dict() for item in self.reference_regions],
            "candidate_regions": [item.to_dict() for item in self.candidate_regions],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualComparison":
        payload = _mapping(payload, "visual_comparison")
        _exact_keys(
            payload,
            (
                "sample_id",
                "reference_image_sha256",
                "candidate_image_sha256",
                "reference_regions",
                "candidate_regions",
            ),
            "visual_comparison",
        )
        reference_regions = _mapping_sequence(payload["reference_regions"], "reference_regions")
        candidate_regions = _mapping_sequence(payload["candidate_regions"], "candidate_regions")
        return cls(
            sample_id=payload["sample_id"],
            reference_image_sha256=payload["reference_image_sha256"],
            candidate_image_sha256=payload["candidate_image_sha256"],
            reference_regions=tuple(TextRegionObservation.from_dict(item) for item in reference_regions),
            candidate_regions=tuple(TextRegionObservation.from_dict(item) for item in candidate_regions),
        )


@dataclass(frozen=True)
class VisualHardGatePolicy:
    max_position_delta_px: float = 2.0
    max_size_delta_px: float = 2.0
    max_baseline_delta_px: float = 2.0
    max_line_count_delta: int = 1
    require_font_resolution: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_position_delta_px", _nonnegative(self.max_position_delta_px, "max_position_delta_px"))
        object.__setattr__(self, "max_size_delta_px", _nonnegative(self.max_size_delta_px, "max_size_delta_px"))
        object.__setattr__(self, "max_baseline_delta_px", _nonnegative(self.max_baseline_delta_px, "max_baseline_delta_px"))
        if isinstance(self.max_line_count_delta, bool) or not isinstance(self.max_line_count_delta, int) or self.max_line_count_delta < 0:
            raise ValueError("max_line_count_delta must be a non-negative integer")
        object.__setattr__(self, "require_font_resolution", _bool(self.require_font_resolution, "require_font_resolution"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "max_position_delta_px": self.max_position_delta_px,
            "max_size_delta_px": self.max_size_delta_px,
            "max_baseline_delta_px": self.max_baseline_delta_px,
            "max_line_count_delta": self.max_line_count_delta,
            "require_font_resolution": self.require_font_resolution,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualHardGatePolicy":
        payload = _mapping(payload, "visual_hard_gate_policy")
        _exact_keys(
            payload,
            (
                "max_position_delta_px",
                "max_size_delta_px",
                "max_baseline_delta_px",
                "max_line_count_delta",
                "require_font_resolution",
            ),
            "visual_hard_gate_policy",
        )
        return cls(
            max_position_delta_px=payload["max_position_delta_px"],
            max_size_delta_px=payload["max_size_delta_px"],
            max_baseline_delta_px=payload["max_baseline_delta_px"],
            max_line_count_delta=payload["max_line_count_delta"],
            require_font_resolution=payload["require_font_resolution"],
        )


@dataclass(frozen=True)
class VisualCheck:
    code: str
    passed: bool
    message: str
    region_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _plain_string(self.code, "code"))
        object.__setattr__(self, "passed", _bool(self.passed, "passed"))
        object.__setattr__(self, "message", _plain_string(self.message, "message"))
        if self.region_id is not None:
            object.__setattr__(self, "region_id", _plain_string(self.region_id, "region_id"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "passed": self.passed,
            "message": self.message,
            "region_id": self.region_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualCheck":
        payload = _mapping(payload, "visual_check")
        _exact_keys(payload, ("code", "passed", "message", "region_id"), "visual_check")
        return cls(
            code=payload["code"],
            passed=payload["passed"],
            message=payload["message"],
            region_id=payload["region_id"],
        )


@dataclass(frozen=True)
class VisualHardGateReport:
    checks: tuple[VisualCheck, ...]

    def __post_init__(self) -> None:
        checks = tuple(self.checks)
        if any(not isinstance(item, VisualCheck) for item in checks):
            raise TypeError("checks must contain VisualCheck values")
        object.__setattr__(self, "checks", checks)

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.checks)

    @property
    def failed_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "passed": self.passed,
            "failed_codes": list(self.failed_codes),
            "checks": [item.to_dict() for item in self.checks],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualHardGateReport":
        payload = _mapping(payload, "visual_hard_gate_report")
        _exact_keys(payload, ("passed", "failed_codes", "checks"), "visual_hard_gate_report")
        checks = _mapping_sequence(payload["checks"], "checks")
        report = cls(tuple(VisualCheck.from_dict(item) for item in checks))
        if payload["passed"] is not report.passed:
            raise ValueError("visual_hard_gate_report.passed does not match checks")
        if payload["failed_codes"] != list(report.failed_codes):
            raise ValueError("visual_hard_gate_report.failed_codes do not match checks")
        return report


@dataclass(frozen=True)
class VisualJudgeResult:
    decision: VisualJudgeDecision
    style_score: float
    confidence: float
    model: str
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.decision, VisualJudgeDecision):
            raise TypeError("decision must be VisualJudgeDecision")
        object.__setattr__(self, "style_score", _unit(self.style_score, "style_score"))
        object.__setattr__(self, "confidence", _unit(self.confidence, "confidence"))
        object.__setattr__(self, "model", _plain_string(self.model, "model"))
        object.__setattr__(self, "issues", _strings(self.issues, "issues"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "decision": self.decision.value,
            "style_score": self.style_score,
            "confidence": self.confidence,
            "model": self.model,
            "issues": list(self.issues),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualJudgeResult":
        payload = _mapping(payload, "visual_judge_result")
        _exact_keys(payload, ("decision", "style_score", "confidence", "model", "issues"), "visual_judge_result")
        try:
            decision = VisualJudgeDecision(payload["decision"])
        except (TypeError, ValueError) as exc:
            raise ValueError("visual_judge_result.decision is invalid") from exc
        return cls(
            decision=decision,
            style_score=payload["style_score"],
            confidence=payload["confidence"],
            model=payload["model"],
            issues=payload["issues"],
        )


class VisualJudge(Protocol):
    def judge(
        self,
        profile: VisualStyleProfile,
        comparison: VisualComparison,
    ) -> VisualJudgeResult: ...


@dataclass(frozen=True)
class VisualGateResult:
    decision: VisualGateDecision
    hard_gate: VisualHardGateReport
    comparisons: tuple[VisualComparison, ...]
    judge_results: tuple[VisualJudgeResult, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.decision, VisualGateDecision):
            raise TypeError("decision must be VisualGateDecision")
        if not isinstance(self.hard_gate, VisualHardGateReport):
            raise TypeError("hard_gate must be VisualHardGateReport")
        comparisons = tuple(self.comparisons)
        if any(not isinstance(item, VisualComparison) for item in comparisons):
            raise TypeError("comparisons must contain VisualComparison values")
        if len({item.sample_id for item in comparisons}) != len(comparisons):
            raise ValueError("comparisons must contain unique sample IDs")
        object.__setattr__(self, "comparisons", comparisons)
        results = tuple(self.judge_results)
        if any(not isinstance(item, VisualJudgeResult) for item in results):
            raise TypeError("judge_results must contain VisualJudgeResult values")
        object.__setattr__(self, "judge_results", results)
        object.__setattr__(self, "reasons", _strings(self.reasons, "reasons"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "decision": self.decision.value,
            "hard_gate": self.hard_gate.to_dict(),
            "comparisons": [item.to_dict() for item in self.comparisons],
            "judge_results": [item.to_dict() for item in self.judge_results],
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualGateResult":
        payload = _mapping(payload, "visual_gate_result")
        _exact_keys(
            payload,
            ("decision", "hard_gate", "comparisons", "judge_results", "reasons"),
            "visual_gate_result",
        )
        try:
            decision = VisualGateDecision(payload["decision"])
        except (TypeError, ValueError) as exc:
            raise ValueError("visual_gate_result.decision is invalid") from exc
        comparisons = _mapping_sequence(payload["comparisons"], "comparisons")
        judge_results = _mapping_sequence(payload["judge_results"], "judge_results")
        return cls(
            decision=decision,
            hard_gate=VisualHardGateReport.from_dict(_mapping(payload["hard_gate"], "visual_hard_gate_report")),
            comparisons=tuple(VisualComparison.from_dict(item) for item in comparisons),
            judge_results=tuple(VisualJudgeResult.from_dict(item) for item in judge_results),
            reasons=payload["reasons"],
        )


def _check(
    code: str,
    passed: bool,
    message: str,
    region_id: str | None = None,
) -> VisualCheck:
    return VisualCheck(code, passed, message, region_id)


def run_visual_hard_gates(
    reference: VisualComparison,
    policy: VisualHardGatePolicy | None = None,
) -> VisualHardGateReport:
    """Compare reference and candidate layout observations without model calls."""

    if not isinstance(reference, VisualComparison):
        raise TypeError("reference must be a VisualComparison")
    policy = VisualHardGatePolicy() if policy is None else policy
    if not isinstance(policy, VisualHardGatePolicy):
        raise TypeError("policy must be VisualHardGatePolicy or None")
    expected = {item.region_id: item for item in reference.reference_regions}
    actual = {item.region_id: item for item in reference.candidate_regions}
    checks: list[VisualCheck] = []
    checks.append(
        _check(
            "region_set",
            set(expected) == set(actual),
            "Reference and candidate contain the same text regions"
            if set(expected) == set(actual)
            else "Reference and candidate text regions differ",
        )
    )
    for region_id in sorted(set(expected) | set(actual)):
        source = expected.get(region_id)
        candidate = actual.get(region_id)
        if source is None or candidate is None:
            continue
        position_delta = max(abs(source.x - candidate.x), abs(source.y - candidate.y))
        checks.append(
            _check(
                "region_position",
                position_delta <= policy.max_position_delta_px,
                f"region position delta={position_delta:g}px",
                region_id,
            )
        )
        size_delta = max(abs(source.width - candidate.width), abs(source.height - candidate.height))
        checks.append(
            _check(
                "region_size",
                size_delta <= policy.max_size_delta_px,
                f"region size delta={size_delta:g}px",
                region_id,
            )
        )
        line_delta = abs(source.line_count - candidate.line_count)
        checks.append(
            _check(
                "line_count",
                line_delta <= policy.max_line_count_delta,
                f"line count delta={line_delta}",
                region_id,
            )
        )
        baseline_delta = abs(source.baseline - candidate.baseline)
        checks.append(
            _check(
                "baseline",
                baseline_delta <= policy.max_baseline_delta_px,
                f"baseline delta={baseline_delta:g}px",
                region_id,
            )
        )
        checks.append(
            _check(
                "missing_glyphs",
                not candidate.missing_codepoints,
                "candidate has no missing glyphs"
                if not candidate.missing_codepoints
                else "candidate contains missing glyph codepoints",
                region_id,
            )
        )
        checks.append(
            _check(
                "overflow",
                not candidate.overflow,
                "candidate text fits its region" if not candidate.overflow else "candidate text overflows its region",
                region_id,
            )
        )
        checks.append(
            _check(
                "clipped",
                not candidate.clipped,
                "candidate text is not clipped" if not candidate.clipped else "candidate text is clipped",
                region_id,
            )
        )
        if policy.require_font_resolution:
            checks.append(
                _check(
                    "font_resolution",
                    candidate.font_resolved,
                    "candidate font fallback resolved" if candidate.font_resolved else "candidate font fallback did not resolve",
                    region_id,
                )
            )
    return VisualHardGateReport(tuple(checks))


def evaluate_visual_gate(
    profile: VisualStyleProfile,
    comparisons: Sequence[VisualComparison],
    *,
    judge: VisualJudge | None = None,
    policy: VisualHardGatePolicy | None = None,
    minimum_style_score: float = 0.85,
    minimum_confidence: float = 0.80,
) -> VisualGateResult:
    """Apply hard gates first, then ask an optional style judge for escalation decisions."""

    if not isinstance(profile, VisualStyleProfile):
        raise TypeError("profile must be VisualStyleProfile")
    comparisons = tuple(comparisons)
    if any(not isinstance(item, VisualComparison) for item in comparisons):
        raise TypeError("comparisons must contain VisualComparison values")
    if len({item.sample_id for item in comparisons}) != len(comparisons):
        raise ValueError("comparisons must contain unique sample IDs")
    expected_samples = set(profile.scenarios)
    actual_samples = {item.sample_id for item in comparisons}
    reports: list[VisualCheck] = [
        _check(
            "scenario_set",
            expected_samples == actual_samples,
            "all profile scenarios have comparison evidence"
            if expected_samples == actual_samples
            else "comparison evidence does not match profile scenarios",
        )
    ]
    for comparison in comparisons:
        reports.extend(run_visual_hard_gates(comparison, policy).checks)
    hard_gate = VisualHardGateReport(tuple(reports))
    if not hard_gate.passed:
        return VisualGateResult(
            VisualGateDecision.BLOCKED,
            hard_gate,
            comparisons,
            (),
            tuple(f"hard_gate:{code}" for code in hard_gate.failed_codes),
        )
    if judge is None:
        return VisualGateResult(
            VisualGateDecision.ESCALATE,
            hard_gate,
            comparisons,
            (),
            ("visual_judge_unavailable",),
        )
    minimum_style_score = _unit(minimum_style_score, "minimum_style_score")
    minimum_confidence = _unit(minimum_confidence, "minimum_confidence")
    results: list[VisualJudgeResult] = []
    reasons: list[str] = []
    for comparison in comparisons:
        try:
            result = judge.judge(profile, comparison)
        except Exception as exc:
            reasons.append(f"visual_judge_error:{type(exc).__name__}")
            continue
        if not isinstance(result, VisualJudgeResult):
            raise TypeError("visual judge must return VisualJudgeResult")
        results.append(result)
        if result.decision is not VisualJudgeDecision.PASS:
            reasons.append(f"visual_judge:{comparison.sample_id}:{result.decision.value}")
        if result.style_score < minimum_style_score:
            reasons.append(f"style_score_below_threshold:{comparison.sample_id}")
        if result.confidence < minimum_confidence:
            reasons.append(f"judge_confidence_below_threshold:{comparison.sample_id}")
    if len(results) != len(comparisons):
        return VisualGateResult(
            VisualGateDecision.ESCALATE,
            hard_gate,
            comparisons,
            tuple(results),
            tuple(reasons),
        )
    if reasons:
        return VisualGateResult(
            VisualGateDecision.ESCALATE,
            hard_gate,
            comparisons,
            tuple(results),
            tuple(reasons),
        )
    return VisualGateResult(
        VisualGateDecision.PASS,
        hard_gate,
        comparisons,
        tuple(results),
        (),
    )


__all__ = [
    "FontAssetReference",
    "TextMetrics",
    "TextRegionObservation",
    "VisualComparison",
    "VisualGateDecision",
    "VisualGateResult",
    "VisualHardGatePolicy",
    "VisualHardGateReport",
    "VisualJudge",
    "VisualJudgeDecision",
    "VisualJudgeResult",
    "VisualStyleProfile",
    "VISUAL_STYLE_SCHEMA_VERSION",
    "evaluate_visual_gate",
    "run_visual_hard_gates",
]
