import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.unreal import UnrealAdapter
from game_localizer.detector import detect_project
from game_localizer.models import CapabilityLevel, DetectionStatus


def touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class UnrealAdapterTests(unittest.TestCase):
    def test_source_project_is_auto_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "Sample.uproject")
            (root / "Config").mkdir()
            (root / "Content").mkdir()
            report = detect_project(root, adapters=(UnrealAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "unreal")
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)

    def test_iostore_package_is_auto_selected_but_detect_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "Content/Paks/game.pak")
            touch(root, "Content/Paks/game.ucas")
            touch(root, "Content/Paks/game.utoc")
            report = detect_project(root, adapters=(UnrealAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertTrue(report.candidates[0].warnings)

    def test_unrelated_container_files_do_not_form_a_packaged_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "Paks/resources.pak")
            touch(root, "Other/chunk.ucas")
            touch(root, "More/other.utoc")
            report = detect_project(root, adapters=(UnrealAdapter(),))

        self.assertEqual(report.status, DetectionStatus.UNKNOWN)
        self.assertIsNone(report.selected_engine)

    def test_lone_pak_is_low_confidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "Content/Paks/game.pak")
            report = detect_project(root, adapters=(UnrealAdapter(),))

        self.assertEqual(report.status, DetectionStatus.UNKNOWN)
        self.assertIsNone(report.selected_engine)
