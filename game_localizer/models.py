from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class CapabilityLevel(str, Enum):
    FULL = "full"
    ASSISTED = "assisted"
    DETECT_ONLY = "detect_only"
    UNSUPPORTED = "unsupported"


class MaturityLevel(str, Enum):
    EXPERIMENTAL = "experimental"
    BETA = "beta"
    STABLE = "stable"


class DetectionStatus(str, Enum):
    AUTO_SELECTED = "auto_selected"
    STOPPED_UNCERTAIN = "stopped_uncertain"
    STOPPED_CONFLICT = "stopped_conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DetectionEvidence:
    code: str
    path: str
    description: str
    weight: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "description": self.description,
            "weight": self.weight,
        }


@dataclass(frozen=True)
class DetectionResult:
    engine_id: str
    display_name: str
    score: int
    capability: CapabilityLevel
    maturity: MaturityLevel
    evidence: tuple[DetectionEvidence, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("检测分数必须位于 0 到 100")
        if self.score > 0 and not self.evidence:
            raise ValueError("非零检测分数必须包含检测证据")

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "display_name": self.display_name,
            "score": self.score,
            "capability": self.capability.value,
            "maturity": self.maturity.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class DetectionReport:
    root: Path
    status: DetectionStatus
    selected_engine: str | None
    candidates: tuple[DetectionResult, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "status": self.status.value,
            "selected_engine": self.selected_engine,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "warnings": list(self.warnings),
        }
