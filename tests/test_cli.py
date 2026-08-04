import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_cli_processes_resource_and_prints_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.json"
            dictionary = root / "dictionary.json"
            resource.write_text('{"title":"New Game","other":"Options"}', encoding="utf-8")
            dictionary.write_text(
                json.dumps({"New Game": "鏂版父鎴?"}, ensure_ascii=False), encoding="utf-8"
            )
            completed = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), str(resource), str(dictionary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("[鍖归厤]", completed.stdout)
            self.assertIn("瀹為檯鏇挎崲: 1", completed.stdout)
            self.assertIn("鏈炕璇戞潯鐩? 1", completed.stdout)

    def test_cli_returns_nonzero_for_invalid_dictionary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text("[]", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), str(resource), str(dictionary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("閿欒:", completed.stderr)
