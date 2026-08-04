import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.base import EngineAdapter
from game_localizer.detector import detect_project, resolve_detection
from game_localizer.models import (
    CapabilityLevel,
    DetectionEvidence,
    DetectionResult,
    DetectionStatus,
    MaturityLevel,
)
from game_localizer.scanner import ProjectSnapshot


class FixedAdapter(EngineAdapter):
    display_name = "Fixed"
    maturity = MaturityLevel.EXPERIMENTAL

    def __init__(self, engine_id: str, score: int):
        self.engine_id = engine_id
        self.score = score

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        if self.score == 0:
            return None
        return self.build_result(
            evidence=(
                DetectionEvidence(
                    code=f"{self.engine_id}_signal",
                    path="signal.file",
                    description=f"{self.engine_id} signal",
                    weight=self.score,
                ),
            )
        )


class DetectorTests(unittest.TestCase):
    def test_auto_selects_single_high_confidence_candidate(self):
        report = resolve_detection(
            Path("C:/game"),
            (FixedAdapter("first", 91).detect(self.empty_snapshot()),),
        )
        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "first")

    def test_stops_when_top_candidates_are_within_ten_points(self):
        candidates = tuple(
            adapter.detect(self.empty_snapshot())
            for adapter in (FixedAdapter("first", 90), FixedAdapter("second", 82))
        )
        report = resolve_detection(Path("C:/game"), candidates)
        self.assertEqual(report.status, DetectionStatus.STOPPED_CONFLICT)
        self.assertIsNone(report.selected_engine)

    def test_stops_on_medium_confidence_and_marks_low_confidence_unknown(self):
        medium = resolve_detection(
            Path("C:/game"),
            (FixedAdapter("medium", 70).detect(self.empty_snapshot()),),
        )
        low = resolve_detection(
            Path("C:/game"),
            (FixedAdapter("low", 40).detect(self.empty_snapshot()),),
        )
        self.assertEqual(medium.status, DetectionStatus.STOPPED_UNCERTAIN)
        self.assertEqual(low.status, DetectionStatus.UNKNOWN)

    def test_detect_project_scans_once_and_uses_injected_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            report = detect_project(directory, adapters=(FixedAdapter("fixed", 90),))
        self.assertEqual(report.selected_engine, "fixed")

    def test_detect_project_does_not_modify_project_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signal = root / "signal.file"
            signal.write_bytes(b"unchanged")
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            detect_project(root, adapters=(FixedAdapter("fixed", 90),))

            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
        self.assertEqual(after, before)

    @staticmethod
    def empty_snapshot() -> ProjectSnapshot:
        return ProjectSnapshot(
            root=Path("C:/game"),
            files=frozenset(),
            directories=frozenset(),
            ignored_directories=frozenset(),
        )
