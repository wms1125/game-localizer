import hashlib
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.generate_benchmark_manifests import check_payloads, write_payloads


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"
EXPECTED_CONTRACT = "hanengine.benchmark/v1"
MANAGED_JSON = (
    "manifest.json",
    "guard_risk_cases.json",
    "renpy_projects.json",
    "player_cases.json",
    "translation_gold_manifest.json",
)
EXPECTED_OPERATIONS = (
    "detect",
    "extract",
    "validate",
    "build",
    "verify",
    "rollback",
    "install_patch",
    "capture",
    "ocr",
    "visual_replace",
)
EXPECTED_EXTERNAL_OPERATIONS = ("detect", "capture", "ocr", "visual_replace")
EXPECTED_GUARD_CASE_KEYS = {
    "case_id",
    "stratum",
    "project_id",
    "user_baseline",
    "adapter_baseline",
    "available_operations",
    "rules",
    "signals",
    "provisional_evaluation_status",
    "final_evaluation_status",
    "expected_risk",
    "expected_allowed_operations",
    "expected_blocked_operations",
}
EXPECTED_RULE_KEYS = {
    "rule_id",
    "rule_version",
    "signal_type",
    "match_value",
    "minimum_risk",
    "blocked_operations",
    "reason",
    "evidence_source",
    "last_verified_date",
}
EXPECTED_SIGNAL_KEYS = {"signal_type", "value", "source", "evidence"}


def load(name: str) -> dict[str, object]:
    return json.loads((BENCHMARKS / name).read_text(encoding="utf-8"))


def expected_language(index: int) -> str:
    return "ja" if index % 5 == 0 else "en"


def expected_rule(
    rule_id: str,
    match_value: str,
    minimum_risk: str,
    blocked_operations: list[str] | None = None,
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "rule_version": "1.0.0",
        "signal_type": "capture_result",
        "match_value": match_value,
        "minimum_risk": minimum_risk,
        "blocked_operations": blocked_operations or [],
        "reason": f"synthetic {rule_id} benchmark rule",
        "evidence_source": "repository-owned synthetic benchmark",
        "last_verified_date": "2026-08-05",
    }


def expected_signal(value: str) -> dict[str, str]:
    return {
        "signal_type": "capture_result",
        "value": value,
        "source": "synthetic_benchmark",
        "evidence": f"synthetic signal: {value}",
    }


def expected_guard_case(
    *,
    case_id: str,
    stratum: str,
    user_baseline: str,
    adapter_baseline: str,
    expected_risk: str,
    allowed_operations: list[str],
    rules: list[dict[str, object]] | None = None,
    signals: list[dict[str, str]] | None = None,
    final_status: str = "complete",
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "stratum": stratum,
        "project_id": f"benchmark-{case_id}",
        "user_baseline": user_baseline,
        "adapter_baseline": adapter_baseline,
        "available_operations": list(EXPECTED_OPERATIONS),
        "rules": rules or [],
        "signals": signals or [],
        "provisional_evaluation_status": "complete",
        "final_evaluation_status": final_status,
        "expected_risk": expected_risk,
        "expected_allowed_operations": allowed_operations,
        "expected_blocked_operations": [
            operation
            for operation in EXPECTED_OPERATIONS
            if operation not in allowed_operations
        ],
    }


def expected_guard_cases() -> list[dict[str, object]]:
    cases = []
    fixed = (
        ("h0", "H0", "H0_PROJECT", list(EXPECTED_OPERATIONS)),
        ("h1", "H1", "H1_OFFLINE", list(EXPECTED_OPERATIONS)),
        ("h2", "H2", "H2_RESTRICTED", list(EXPECTED_EXTERNAL_OPERATIONS)),
    )
    for prefix, stratum, risk, allowed in fixed:
        for index in range(1, 17):
            cases.append(
                expected_guard_case(
                    case_id=f"guard-{prefix}-{index:02d}",
                    stratum=stratum,
                    user_baseline=risk,
                    adapter_baseline=risk,
                    expected_risk=risk,
                    allowed_operations=allowed,
                )
            )

    for index in range(1, 17):
        rules = []
        signals = []
        allowed = list(EXPECTED_EXTERNAL_OPERATIONS)
        if index > 8:
            value = "overlay_forbidden" if index <= 12 else "capture_black_frame"
            rule_id = f"synthetic-{value}"
            rules = [
                expected_rule(
                    rule_id,
                    value,
                    "H3_PROTECTED",
                    ["capture", "ocr", "visual_replace"],
                )
            ]
            signals = [expected_signal(value)]
            allowed = ["detect"]
        cases.append(
            expected_guard_case(
                case_id=f"guard-h3-{index:02d}",
                stratum="H3",
                user_baseline="H3_PROTECTED",
                adapter_baseline="H3_PROTECTED",
                expected_risk="H3_PROTECTED",
                allowed_operations=allowed,
                rules=rules,
                signals=signals,
            )
        )

    conflicts = (
        ("H0_PROJECT", "H1_OFFLINE", "H2_RESTRICTED", "H2_RESTRICTED"),
        ("H1_OFFLINE", "H0_PROJECT", "H3_PROTECTED", "H3_PROTECTED"),
        ("H3_PROTECTED", "H0_PROJECT", "H1_OFFLINE", "H3_PROTECTED"),
        ("H2_RESTRICTED", "H1_OFFLINE", "H0_PROJECT", "H2_RESTRICTED"),
    )
    for index, (user_risk, adapter_risk, rule_risk, result_risk) in enumerate(
        conflicts, 1
    ):
        value = f"risk_conflict_{index}"
        cases.append(
            expected_guard_case(
                case_id=f"guard-edge-{index:02d}",
                stratum="edge",
                user_baseline=user_risk,
                adapter_baseline=adapter_risk,
                expected_risk=result_risk,
                allowed_operations=list(EXPECTED_EXTERNAL_OPERATIONS),
                rules=[
                    expected_rule(
                        f"synthetic-conflict-{index}",
                        value,
                        rule_risk,
                    )
                ],
                signals=[expected_signal(value)],
            )
        )

    non_complete_statuses = (
        "missing_evidence",
        "unknown_rule",
        "evaluation_failed",
    )
    for status_index, status in enumerate(non_complete_statuses):
        for offset in range(4):
            case_number = 5 + status_index * 4 + offset
            cases.append(
                expected_guard_case(
                    case_id=f"guard-edge-{case_number:02d}",
                    stratum="edge",
                    user_baseline="H0_PROJECT",
                    adapter_baseline="H0_PROJECT",
                    expected_risk="H2_RESTRICTED",
                    allowed_operations=list(EXPECTED_EXTERNAL_OPERATIONS),
                    final_status=status,
                )
            )
    return cases


def snapshot_files(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


class BenchmarkManifestTests(unittest.TestCase):
    def test_master_manifest_locks_every_dataset(self):
        self.assertEqual(
            load("manifest.json"),
            {
                "contract": EXPECTED_CONTRACT,
                "counts": {
                    "renpy_projects": 4,
                    "renpy_segments": 500,
                    "player_static_cases": 120,
                    "player_dynamic_cases": 60,
                    "translation_gold_slots": 300,
                    "guard_risk_cases": 80,
                },
            },
        )

    def test_every_managed_json_uses_the_exact_contract(self):
        for name in MANAGED_JSON:
            with self.subTest(name=name):
                self.assertEqual(load(name)["contract"], EXPECTED_CONTRACT)

    def test_benchmark_license_bytes_and_scope_are_separate(self):
        raw = (BENCHMARKS / "LICENSE").read_bytes()
        self.assertEqual(len(raw), 7048)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest().upper(),
            "A2010F343487D3F7618AFFE54F789F5487602331C0A8D03F49E9A7C547CF0499",
        )
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        license_text = raw.decode("utf-8", errors="strict")
        readme_text = (BENCHMARKS / "README.md").read_text(encoding="utf-8")
        self.assertIn("CC0 1.0", license_text)
        self.assertNotIn("root license remains undecided", license_text)
        self.assertIn("benchmarks/", readme_text)
        self.assertIn("root license remains undecided", readme_text)
        self.assertIn("no third-party code or assets", readme_text.lower())

    def test_git_attributes_are_exact_and_pin_every_managed_json_to_lf(self):
        self.assertEqual(
            (ROOT / ".gitattributes").read_bytes(),
            (
                b"/benchmarks/*.json text eol=lf\n"
                b"/benchmarks/visual_judge_controlled/*.json text eol=lf\n"
            ),
        )
        paths = [f"benchmarks/{name}" for name in MANAGED_JSON]
        completed = subprocess.run(
            ["git", "check-attr", "text", "eol", "--", *paths],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for path in paths:
            self.assertIn(f"{path}: text: set", completed.stdout)
            self.assertIn(f"{path}: eol: lf", completed.stdout)

    def test_renpy_manifest_locks_versions_and_ordered_segment_counts(self):
        self.assertEqual(
            load("renpy_projects.json"),
            {
                "contract": EXPECTED_CONTRACT,
                "renpy_versions": ["8.5.3", "8.4.1"],
                "projects": [
                    {"project_id": "rp_core_dialogue", "expected_segments": 160},
                    {"project_id": "rp_screen_language", "expected_segments": 120},
                    {"project_id": "rp_branching_context", "expected_segments": 120},
                    {"project_id": "rp_packaged_smoke", "expected_segments": 100},
                ],
            },
        )

    def test_player_cases_match_the_exact_ordered_matrices(self):
        resolutions = ("1280x720", "1920x1080", "2560x1440", "3840x2160")
        backgrounds = (
            "solid",
            "translucent",
            "textured",
            "static_scene",
            "low_contrast",
        )
        layouts = ("single_line", "multi_line", "menu")
        font_rotations = ("sans_serif", "serif_sans")
        expected_static = []
        index = 0
        for resolution in resolutions:
            for background in backgrounds:
                for layout in layouts:
                    for font_rotation in font_rotations:
                        index += 1
                        expected_static.append(
                            {
                                "case_id": f"static-{index:03d}",
                                "resolution": resolution,
                                "background": background,
                                "layout": layout,
                                "font_rotation": font_rotation,
                                "source_language": expected_language(index),
                            }
                        )

        dynamic_kinds = (
            "typewriter",
            "fade_slide",
            "animated_background",
            "camera_motion",
        )
        expected_dynamic = []
        index = 0
        for kind in dynamic_kinds:
            for _ in range(15):
                index += 1
                expected_dynamic.append(
                    {
                        "case_id": f"dynamic-{index:03d}",
                        "kind": kind,
                        "frame_count": 30,
                        "source_language": expected_language(index),
                    }
                )

        self.assertEqual(
            load("player_cases.json"),
            {
                "contract": EXPECTED_CONTRACT,
                "static_cases": expected_static,
                "dynamic_cases": expected_dynamic,
            },
        )

    def test_translation_slots_match_exact_ranges_and_languages(self):
        expected_slots = []
        for index in range(1, 301):
            if index <= 180:
                category = "dialogue"
            elif index <= 240:
                category = "menu_ui"
            else:
                category = "system"
            expected_slots.append(
                {
                    "slot_id": f"gold-{index:03d}",
                    "category": category,
                    "source_language": expected_language(index),
                }
            )
        self.assertEqual(
            load("translation_gold_manifest.json"),
            {"contract": EXPECTED_CONTRACT, "slots": expected_slots},
        )

    def test_guard_cases_match_the_exact_ordered_policy_matrix(self):
        payload = load("guard_risk_cases.json")
        self.assertEqual(set(payload), {"contract", "cases"})
        cases = payload["cases"]
        self.assertEqual(payload["contract"], EXPECTED_CONTRACT)
        self.assertEqual(cases, expected_guard_cases())
        self.assertEqual(
            [item["case_id"] for item in cases],
            [f"guard-h0-{index:02d}" for index in range(1, 17)]
            + [f"guard-h1-{index:02d}" for index in range(1, 17)]
            + [f"guard-h2-{index:02d}" for index in range(1, 17)]
            + [f"guard-h3-{index:02d}" for index in range(1, 17)]
            + [f"guard-edge-{index:02d}" for index in range(1, 17)],
        )
        for case in cases:
            self.assertEqual(set(case), EXPECTED_GUARD_CASE_KEYS)
            self.assertEqual(case["project_id"], f"benchmark-{case['case_id']}")
            self.assertEqual(case["available_operations"], list(EXPECTED_OPERATIONS))
            self.assertEqual(case["provisional_evaluation_status"], "complete")
            self.assertEqual(
                set(case["expected_allowed_operations"])
                | set(case["expected_blocked_operations"]),
                set(EXPECTED_OPERATIONS),
            )
            self.assertFalse(
                set(case["expected_allowed_operations"])
                & set(case["expected_blocked_operations"])
            )
            for rule in case["rules"]:
                self.assertEqual(set(rule), EXPECTED_RULE_KEYS)
            for signal in case["signals"]:
                self.assertEqual(set(signal), EXPECTED_SIGNAL_KEYS)
            self.assertEqual(
                [rule["match_value"] for rule in case["rules"]],
                [signal["value"] for signal in case["signals"]],
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

    def test_write_and_check_manage_only_five_json_files_without_repairing_drift(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            expected_paths = tuple(root / "benchmarks" / name for name in MANAGED_JSON)
            self.assertEqual(write_payloads(root), expected_paths)
            self.assertEqual(
                tuple(path.relative_to(root).as_posix() for path in expected_paths),
                tuple(f"benchmarks/{name}" for name in MANAGED_JSON),
            )
            self.assertEqual(
                tuple(
                    path.relative_to(root).as_posix()
                    for path in sorted(root.rglob("*"))
                    if path.is_file()
                ),
                tuple(sorted(f"benchmarks/{name}" for name in MANAGED_JSON)),
            )

            corrupted = root / "benchmarks" / "manifest.json"
            corrupted.write_bytes(b"corrupted\r\n")
            before = snapshot_files(root)
            diagnostic = io.StringIO()
            with redirect_stdout(diagnostic):
                result = check_payloads(root)
            self.assertEqual(result, 1)
            self.assertIn("manifest.json", diagnostic.getvalue())
            self.assertEqual(snapshot_files(root), before)

            missing_root = root / "missing"
            missing_diagnostic = io.StringIO()
            with redirect_stdout(missing_diagnostic):
                missing_result = check_payloads(missing_root)
            self.assertEqual(missing_result, 1)
            for name in MANAGED_JSON:
                self.assertIn(name, missing_diagnostic.getvalue())
            self.assertFalse(missing_root.exists())

    def test_committed_json_is_canonical_utf8_lf_without_bom(self):
        for name in MANAGED_JSON:
            raw = (BENCHMARKS / name).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), name)
            self.assertTrue(raw.endswith(b"\n"), name)
            self.assertFalse(raw.endswith(b"\n\n"), name)
            self.assertNotIn(b"\r\n", raw, name)


if __name__ == "__main__":
    unittest.main()
