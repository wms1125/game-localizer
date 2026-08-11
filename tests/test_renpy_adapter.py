import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.renpy import RenPyAdapter
from game_localizer.detector import detect_project
from game_localizer.models import CapabilityLevel, DetectionStatus


class RenPyAdapterTests(unittest.TestCase):
    def test_source_project_is_auto_selected_with_explainable_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "game").mkdir()
            (root / "game" / "script.rpy").write_text("label start:\n", encoding="utf-8")
            report = detect_project(root, adapters=(RenPyAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "renpy")
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)
        self.assertIn("renpy_scripts", {item.code for item in report.candidates[0].evidence})

    def test_archive_only_distribution_does_not_claim_full_support(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "game").mkdir()
            (root / "renpy").mkdir()
            (root / "game" / "archive.rpa").write_bytes(b"archive")
            report = detect_project(root, adapters=(RenPyAdapter(),))

        self.assertEqual(report.status, DetectionStatus.STOPPED_UNCERTAIN)
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)
        self.assertTrue(report.candidates[0].warnings)
