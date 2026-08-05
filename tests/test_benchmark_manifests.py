import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"


def load(name: str) -> dict[str, object]:
    return json.loads((BENCHMARKS / name).read_text(encoding="utf-8"))


class BenchmarkManifestTests(unittest.TestCase):
    def test_master_manifest_locks_every_dataset(self):
        payload = load("manifest.json")
        self.assertEqual(payload["contract"], "hanengine.benchmark/v1")
        self.assertEqual(
            payload["counts"],
            {
                "renpy_projects": 4,
                "renpy_segments": 500,
                "player_static_cases": 120,
                "player_dynamic_cases": 60,
                "translation_gold_slots": 300,
                "guard_risk_cases": 80,
            },
        )

    def test_benchmark_license_carrier_and_scope_are_separate(self):
        license_text = (BENCHMARKS / "LICENSE").read_text(encoding="utf-8")
        readme_text = (BENCHMARKS / "README.md").read_text(encoding="utf-8")
        self.assertIn("CC0 1.0", license_text)
        self.assertNotIn("root license remains undecided", license_text)
        self.assertIn("benchmarks/", readme_text)
        self.assertIn("root license remains undecided", readme_text)
        self.assertIn("no third-party code or assets", readme_text.lower())

    def test_git_attributes_pin_benchmark_json_to_lf(self):
        completed = subprocess.run(
            ["git", "check-attr", "text", "eol", "--", "benchmarks/manifest.json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("benchmarks/manifest.json: text: set", completed.stdout)
        self.assertIn("benchmarks/manifest.json: eol: lf", completed.stdout)

    def test_renpy_manifest_locks_versions_and_segment_counts(self):
        payload = load("renpy_projects.json")
        projects = payload["projects"]
        self.assertEqual(payload["renpy_versions"], ["8.5.3", "8.4.1"])
        self.assertEqual(
            {item["project_id"]: item["expected_segments"] for item in projects},
            {
                "rp_core_dialogue": 160,
                "rp_screen_language": 120,
                "rp_branching_context": 120,
                "rp_packaged_smoke": 100,
            },
        )
        self.assertEqual(sum(item["expected_segments"] for item in projects), 500)

    def test_player_and_translation_case_ids_are_unique(self):
        player = load("player_cases.json")
        translation = load("translation_gold_manifest.json")
        static_ids = [item["case_id"] for item in player["static_cases"]]
        dynamic_ids = [item["case_id"] for item in player["dynamic_cases"]]
        slot_ids = [item["slot_id"] for item in translation["slots"]]
        self.assertEqual((len(static_ids), len(dynamic_ids), len(slot_ids)), (120, 60, 300))
        self.assertEqual(len(set(static_ids + dynamic_ids)), 180)
        self.assertEqual(len(set(slot_ids)), 300)
        self.assertEqual(
            Counter(item["category"] for item in translation["slots"]),
            Counter({"dialogue": 180, "menu_ui": 60, "system": 60}),
        )
        self.assertEqual(
            Counter(item["source_language"] for item in translation["slots"]),
            Counter({"en": 240, "ja": 60}),
        )

    def test_guard_cases_have_required_strata_and_expected_routes(self):
        payload = load("guard_risk_cases.json")
        cases = payload["cases"]
        self.assertEqual(len(cases), 80)
        self.assertEqual(len({item["case_id"] for item in cases}), 80)
        self.assertEqual(
            Counter(item["stratum"] for item in cases),
            Counter({"H0": 16, "H1": 16, "H2": 16, "H3": 16, "edge": 16}),
        )
        for case in cases:
            self.assertIn("signals", case)
            self.assertIn("expected_risk", case)
            self.assertIn("expected_allowed_operations", case)
            self.assertIn("expected_blocked_operations", case)
        edge_cases = [item for item in cases if item["stratum"] == "edge"]
        self.assertEqual(
            Counter(item["final_evaluation_status"] for item in edge_cases),
            Counter(
                {
                    "complete": 4,
                    "missing_evidence": 4,
                    "unknown_rule": 4,
                    "evaluation_failed": 4,
                }
            ),
        )

    def test_generator_is_deterministic_and_check_mode_is_clean(self):
        completed = subprocess.run(
            [sys.executable, "tools/generate_benchmark_manifests.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_committed_json_is_canonical_utf8_lf_without_bom(self):
        for name in (
            "manifest.json",
            "guard_risk_cases.json",
            "renpy_projects.json",
            "player_cases.json",
            "translation_gold_manifest.json",
        ):
            raw = (BENCHMARKS / name).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), name)
            self.assertTrue(raw.endswith(b"\n"), name)
            self.assertFalse(raw.endswith(b"\n\n"), name)
            self.assertNotIn(b"\r\n", raw, name)


if __name__ == "__main__":
    unittest.main()
