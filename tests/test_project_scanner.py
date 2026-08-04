import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_scan_rejects_a_root_directory_symlink(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            target = Path(outside)
            (target / "outside.rpy").write_text("label outside:", encoding="utf-8")
            link = root / "linked-project"
            try:
                os.symlink(target, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("current environment does not allow directory symlinks")

            with self.assertRaises(ProjectScanError):
                scan_project(link)

    def test_scan_rejects_a_root_path_with_a_symlink_component(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            target = Path(outside)
            nested = target / "nested"
            nested.mkdir()
            link = root / "linked-parent"
            try:
                os.symlink(target, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("current environment does not allow directory symlinks")

            with self.assertRaises(ProjectScanError):
                scan_project(link / nested.name)

    @unittest.skipUnless(os.name == "nt", "junctions are Windows reparse points")
    def test_snapshot_does_not_follow_directory_junctions(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            target = Path(outside)
            (target / "outside.rpy").write_text("label outside:", encoding="utf-8")
            junction = root / "linked-junction"
            command = f'mklink /J "{junction}" "{target}"'
            completed = subprocess.run(
                ["cmd", "/d", "/c", command],
                capture_output=True,
                check=False,
                text=True,
            )
            if completed.returncode:
                self.skipTest("current environment does not allow directory junctions")

            snapshot = scan_project(root)

            self.assertFalse(snapshot.has_file("linked-junction/outside.rpy"))
            self.assertIn("linked-junction", snapshot.ignored_directories)

    def test_scan_wraps_is_symlink_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = Mock()
            entry.path = str(root / "unreadable")
            entry.stat.return_value = os.lstat(root)
            entry.is_symlink.side_effect = OSError("access denied")

            with patch("game_localizer.scanner.os.scandir", return_value=[entry]):
                with self.assertRaisesRegex(ProjectScanError, "access denied"):
                    scan_project(root)

    def test_scan_wraps_lexical_absolute_path_errors(self):
        with patch("game_localizer.scanner.Path.absolute", side_effect=OSError("cwd unavailable")):
            with self.assertRaisesRegex(ProjectScanError, "cwd unavailable"):
                scan_project("project")

    def test_scan_rejects_non_directory_input(self):
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "game.exe"
            file_path.write_bytes(b"not a directory")

            with self.assertRaisesRegex(ProjectScanError, "项目目录"):
                scan_project(file_path)
