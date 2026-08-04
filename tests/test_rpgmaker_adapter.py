import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.rpgmaker import RpgMakerMVAdapter, RpgMakerMZAdapter
from game_localizer.detector import detect_project
from game_localizer.models import DetectionStatus


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
