import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.godot import GodotAdapter
from game_localizer.detector import detect_project
from game_localizer.models import DetectionStatus


class GodotAdapterTests(unittest.TestCase):
    def test_project_godot_is_a_strong_source_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "project.godot").write_text("[application]\n", encoding="utf-8")
            report = detect_project(root, adapters=(GodotAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "godot")

    def test_matching_pck_and_executable_detect_packaged_godot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.pck").write_bytes(b"pack")
            (root / "sample.exe").write_bytes(b"executable")
            report = detect_project(root, adapters=(GodotAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertTrue(report.candidates[0].warnings)

    def test_pck_evidence_uses_the_pack_matching_the_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.pck").write_bytes(b"pack")
            (root / "b.pck").write_bytes(b"pack")
            (root / "b.exe").write_bytes(b"executable")
            report = detect_project(root, adapters=(GodotAdapter(),))

        evidence = {item.code: item.path for item in report.candidates[0].evidence}
        self.assertEqual(evidence["godot_pack"], "b.pck")
        self.assertEqual(evidence["godot_executable"], "b.exe")
