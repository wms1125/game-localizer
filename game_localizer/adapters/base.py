from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from game_localizer.models import (
    CapabilityLevel,
    DetectionEvidence,
    DetectionResult,
    MaturityLevel,
)
from game_localizer.scanner import ProjectSnapshot


class EngineAdapter(ABC):
    engine_id: str
    display_name: str
    maturity: MaturityLevel

    @abstractmethod
    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        raise NotImplementedError

    def build_result(
        self,
        evidence: Iterable[DetectionEvidence],
        warnings: Iterable[str] = (),
    ) -> DetectionResult:
        evidence_tuple = tuple(evidence)
        return DetectionResult(
            engine_id=self.engine_id,
            display_name=self.display_name,
            score=min(100, sum(item.weight for item in evidence_tuple)),
            capability=CapabilityLevel.DETECT_ONLY,
            maturity=self.maturity,
            evidence=evidence_tuple,
            warnings=tuple(warnings),
        )
