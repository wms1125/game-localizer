import unittest
from pathlib import Path

from game_localizer.models import (
    CapabilityLevel,
    DetectionEvidence,
    DetectionReport,
    DetectionResult,
    DetectionStatus,
    MaturityLevel,
)


class DetectionModelTests(unittest.TestCase):
    def make_result(self, score: int = 90) -> DetectionResult:
        return DetectionResult(
            engine_id="renpy",
            display_name="Ren'Py",
            score=score,
            capability=CapabilityLevel.DETECT_ONLY,
            maturity=MaturityLevel.EXPERIMENTAL,
            evidence=(
                DetectionEvidence(
                    code="renpy_scripts",
                    path="game/script.rpy",
                    description="发现 Ren'Py 源脚本",
                    weight=65,
                ),
            ),
            warnings=("阶段一仅提供只读检测",),
        )

    def test_detection_result_rejects_score_outside_range(self):
        with self.assertRaisesRegex(ValueError, "0 到 100"):
            self.make_result(101)

    def test_detection_result_requires_evidence_for_positive_score(self):
        with self.assertRaisesRegex(ValueError, "检测证据"):
            DetectionResult(
                engine_id="unknown",
                display_name="Unknown",
                score=1,
                capability=CapabilityLevel.DETECT_ONLY,
                maturity=MaturityLevel.EXPERIMENTAL,
                evidence=(),
            )

    def test_report_serializes_enums_paths_and_nested_results(self):
        report = DetectionReport(
            root=Path("C:/games/example"),
            status=DetectionStatus.AUTO_SELECTED,
            selected_engine="renpy",
            candidates=(self.make_result(),),
        )

        payload = report.to_dict()

        self.assertEqual(payload["status"], "auto_selected")
        self.assertEqual(payload["selected_engine"], "renpy")
        self.assertEqual(payload["candidates"][0]["capability"], "detect_only")
        self.assertEqual(payload["candidates"][0]["evidence"][0]["weight"], 65)


if __name__ == "__main__":
    unittest.main()
