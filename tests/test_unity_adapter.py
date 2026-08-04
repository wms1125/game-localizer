import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.unity import UnityAdapter
from game_localizer.detector import detect_project
from game_localizer.models import CapabilityLevel, DetectionStatus


def touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class UnityAdapterTests(unittest.TestCase):
    def test_source_project_is_auto_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Assets").mkdir()
            touch(root, "ProjectSettings/ProjectVersion.txt")
            touch(root, "Packages/manifest.json")
            report = detect_project(root, adapters=(UnityAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "unity")
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)

    def test_packaged_windows_build_is_auto_selected_but_detect_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "UnityPlayer.dll")
            (root / "Game_Data").mkdir()
            touch(root, "Game_Data/globalgamemanagers")
            report = detect_project(root, adapters=(UnityAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)
        self.assertTrue(report.candidates[0].warnings)

    def test_assets_directory_alone_does_not_auto_select_unity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Assets").mkdir()
            report = detect_project(root, adapters=(UnityAdapter(),))

        self.assertEqual(report.status, DetectionStatus.UNKNOWN)
        self.assertIsNone(report.selected_engine)
