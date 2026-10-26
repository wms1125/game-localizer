import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.rpgmaker import RpgMakerMVAdapter, RpgMakerMZAdapter
from game_localizer.detector import detect_project
from game_localizer.models import DetectionStatus
from game_localizer.scanner import scan_project


def touch(root: Path, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RpgMakerAdapterTests(unittest.TestCase):
    def test_mz_project_selects_mz_without_mv_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "game.rmmzproject")
            touch(root, "js/rmmz_core.js")
            touch(root, "data/System.json", "{}")
            report = detect_project(root, adapters=(RpgMakerMZAdapter(), RpgMakerMVAdapter()))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "rpg_maker_mz")

    def test_mv_project_selects_mv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "game.rpgproject")
            touch(root, "js/rpg_core.js")
            touch(root, "data/System.json", "{}")
            report = detect_project(root, adapters=(RpgMakerMZAdapter(), RpgMakerMVAdapter()))

        self.assertEqual(report.selected_engine, "rpg_maker_mv")

    def test_shared_system_json_alone_is_not_enough(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "data/System.json", "{}")
            report = detect_project(root, adapters=(RpgMakerMZAdapter(), RpgMakerMVAdapter()))

        self.assertEqual(report.status, DetectionStatus.UNKNOWN)
        self.assertIsNone(report.selected_engine)

    def test_www_package_evidence_reports_its_actual_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "www/package.json", "{}")

            result = RpgMakerMZAdapter().detect(scan_project(root))

        self.assertIsNotNone(result)
        evidence = next(item for item in result.evidence if item.code == "rpgmaker_package")
        self.assertEqual(evidence.path, "www/package.json")
