from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionReport, DetectionResult, DetectionStatus
from game_localizer.scanner import scan_project


def resolve_detection(
    root: Path,
    candidates: Iterable[DetectionResult | None],
) -> DetectionReport:
    ordered = tuple(
        sorted(
            (candidate for candidate in candidates if candidate is not None and candidate.score > 0),
            key=lambda item: (-item.score, item.engine_id),
        )
    )
    if not ordered or ordered[0].score < 50:
        return DetectionReport(root, DetectionStatus.UNKNOWN, None, ordered)

    highest = ordered[0]
    if highest.score < 80:
        return DetectionReport(root, DetectionStatus.STOPPED_UNCERTAIN, None, ordered)

    if len(ordered) > 1:
        second = ordered[1]
        if second.score >= 80 or highest.score - second.score <= 10:
            return DetectionReport(root, DetectionStatus.STOPPED_CONFLICT, None, ordered)

    return DetectionReport(root, DetectionStatus.AUTO_SELECTED, highest.engine_id, ordered)


def detect_project(
    root: str | Path,
    adapters: Iterable[EngineAdapter] | None = None,
) -> DetectionReport:
    snapshot = scan_project(root)
    if adapters is None:
        from game_localizer.adapters import get_adapters

        adapters = get_adapters()
    return resolve_detection(
        snapshot.root,
        (adapter.detect(snapshot) for adapter in adapters),
    )
