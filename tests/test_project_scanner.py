import os
import tempfile
import unittest
from pathlib import Path

from game_localizer.scanner import ProjectScanError, scan_project


class ProjectScannerTests(unittest.TestCase):
    def test_snapshot_normalizes_paths_and_skips_generated_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Game").mkdir()
            (root / "Game" / "Script.RPY").write_text("label start:", encoding="utf-8")
            (root / "Library").mkdir()
            (root / "Library" / "secret.asset").write_bytes(b"binary")

            snapshot = scan_project(root)

            self.assertTrue(snapshot.has_dir("game"))
            self.assertTrue(snapshot.has_file("game/script.rpy"))
            self.assertFalse(snapshot.has_file("library/secret.asset"))
            self.assertIn("library", snapshot.ignored_directories)

    def test_snapshot_does_not_follow_directory_symlinks(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            target = Path(outside)
            (target / "outside.rpy").write_text("label outside:", encoding="utf-8")
            link = root / "linked"
            try:
                os.symlink(target, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("current environment does not allow directory symlinks")

            snapshot = scan_project(root)

            self.assertFalse(snapshot.has_file("linked/outside.rpy"))
            self.assertIn("linked", snapshot.ignored_directories)

    def test_scan_rejects_non_directory_input(self):
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "game.exe"
            file_path.write_bytes(b"not a directory")

            with self.assertRaisesRegex(ProjectScanError, "项目目录"):
                scan_project(file_path)
