from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import cli


class QualityReportTests(unittest.TestCase):
    def test_localize_writes_portable_quality_report_with_complete_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            (project / "data").mkdir(parents=True)
            (project / "game.rpgproject").write_text("RPG Maker MV", encoding="utf-8")
            (project / "data" / "System.json").write_text(
                json.dumps({"gameTitle": "Demo"}), encoding="utf-8"
            )
            dictionary = root / "dictionary.json"
            dictionary.write_text(json.dumps({"Demo": "演示"}, ensure_ascii=False), encoding="utf-8")
            output = root / "candidate"
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                code = cli.run_engine(
                    [
                        "localize",
                        "auto",
                        str(project),
                        "--output",
                        str(output),
                        "--dictionary",
                        str(dictionary),
                        "--state-root",
                        str(root / "state"),
                        "--quiet-progress",
                    ]
                )
            self.assertEqual(code, 0)
            report_path = Path(f"{output}.quality.json")
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "hanengine.quality-report/v1")
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["summary"]["segment_count"], 1)
            self.assertEqual(payload["summary"]["untranslated_count"], 0)
            # Build statistics must reach the report: they are the only place a
            # caller can see how many files were written and what the build did.
            self.assertEqual(payload["build"]["statistics"]["segments"], 1)
            self.assertEqual(payload["build"]["statistics"]["files"], 1)
            self.assertIn("Quality report:", stdout.getvalue())

    def test_localize_writes_failed_report_when_translation_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            (project / "data").mkdir(parents=True)
            (project / "game.rpgproject").write_text("RPG Maker MV", encoding="utf-8")
            (project / "data" / "System.json").write_text(
                json.dumps({"gameTitle": "Demo"}), encoding="utf-8"
            )
            dictionary = root / "dictionary.json"
            dictionary.write_text("{}", encoding="utf-8")
            output = root / "candidate"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = cli.run_engine(
                    [
                        "localize",
                        "auto",
                        str(project),
                        "--output",
                        str(output),
                        "--dictionary",
                        str(dictionary),
                        "--state-root",
                        str(root / "state"),
                        "--quiet-progress",
                    ]
                )
            self.assertEqual(code, 1)
            payload = json.loads(Path(f"{output}.quality.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["summary"]["untranslated_count"], 1)
            # Build never ran, so the adapter validation section stays honest
            # about having no verdict instead of inventing issues.
            self.assertIsNone(payload["validation"]["valid"])
            self.assertEqual(payload["validation"]["issues"], [])
            self.assertEqual(payload["review"]["reasons"], ["translation_incomplete"])
            queue = payload["review"]["queue"]
            self.assertEqual(queue["count"], 1)
            self.assertEqual(queue["items"][0]["reasons"], ["missing_translation"])
            self.assertIsNone(queue["items"][0]["target_text"])


if __name__ == "__main__":
    unittest.main()
