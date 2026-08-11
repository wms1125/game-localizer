import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DetectionCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "cli.py"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_detect_outputs_json_and_zero_for_high_confidence_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "game").mkdir()
            (root / "game" / "script.rpy").write_text("label start:\n", encoding="utf-8")
            completed = self.run_cli("detect", str(root), "--json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "auto_selected")
        self.assertEqual(payload["selected_engine"], "renpy")

    def test_detect_returns_two_for_unknown_project(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli("detect", directory)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("无法确定", completed.stdout)

    def test_detect_returns_one_for_missing_directory_without_traceback(self):
        completed = self.run_cli("detect", "missing-project")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("错误:", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_detect_returns_one_for_missing_project_argument(self):
        completed = self.run_cli("detect")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("usage:", completed.stderr)
        self.assertIn("error:", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_detect_returns_one_for_unknown_argument(self):
        completed = self.run_cli("detect", ".", "--bad")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("usage:", completed.stderr)
        self.assertIn("error:", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_engines_returns_one_for_extra_argument(self):
        completed = self.run_cli("engines", "extra")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("usage:", completed.stderr)
        self.assertIn("error:", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_detect_help_returns_zero(self):
        completed = self.run_cli("detect", "--help")
        self.assertEqual(completed.returncode, 0)
        self.assertIn("usage:", completed.stdout)

    def test_engines_help_returns_zero(self):
        completed = self.run_cli("engines", "--help")
        self.assertEqual(completed.returncode, 0)
        self.assertIn("usage:", completed.stdout)

    def test_engines_lists_all_registered_engine_ids(self):
        completed = self.run_cli("engines", "--json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        ids = {item["engine_id"] for item in json.loads(completed.stdout)}
        self.assertEqual(
            ids,
            {"renpy", "rpg_maker_mz", "rpg_maker_mv", "godot", "unity", "unreal"},
        )
