from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.check_compliance import (
    ComplianceFinding,
    ComplianceReport,
    PROVENANCE_CONTRACT,
    THIRD_PARTY_CONTRACT,
    check_repository,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ComplianceTests(unittest.TestCase):
    def make_repository(self, directory: Path) -> None:
        (directory / "compliance").mkdir()
        (directory / "docs" / "compliance").mkdir(parents=True)
        (directory / "PROVENANCE.md").write_text("Provenance\n", encoding="utf-8")
        (directory / "THIRD_PARTY_NOTICES.md").write_text("Notices\n", encoding="utf-8")
        (directory / "docs" / "compliance" / "CLEAN_ROOM_POLICY.md").write_text(
            "Policy\n", encoding="utf-8"
        )
        self.write_json(
            directory / "compliance" / "provenance.json",
            {
                "contract": PROVENANCE_CONTRACT,
                "project": {
                    "license_spdx": "NOASSERTION",
                    "license_status": "UNDECIDED",
                    "name": "HanEngine",
                    "repository": "https://example.invalid/hanengine",
                    "version": "0.0.0-test",
                },
            },
        )
        self.write_json(
            directory / "compliance" / "third_party_components.json",
            {"components": [], "contract": THIRD_PARTY_CONTRACT},
        )

    def write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_current_repository_audit_has_only_undecided_license_warning(self) -> None:
        report = check_repository(REPOSITORY_ROOT)

        self.assertTrue(report.ok)
        self.assertEqual([finding.code for finding in report.findings], ["PROJECT_LICENSE_UNDECIDED"])

    def test_release_without_root_license_requires_a_license(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)

            report = check_repository(root, release=True)

        self.assertFalse(report.ok)
        self.assertIn("PROJECT_LICENSE_REQUIRED", [finding.code for finding in report.findings])

    def test_forbidden_recovered_material_is_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            restricted = root / "recovered-source" / "embedded-scripts"
            restricted.mkdir(parents=True)
            (restricted / "renpythief.rpy").write_text("", encoding="utf-8")

            report = check_repository(root)

        self.assertIn("RESTRICTED_MATERIAL_TRACKED", [finding.code for finding in report.findings])

    def test_incomplete_third_party_component_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            self.write_json(
                root / "compliance" / "third_party_components.json",
                {"components": [{"name": "Example"}], "contract": THIRD_PARTY_CONTRACT},
            )

            report = check_repository(root)

        self.assertIn("THIRD_PARTY_METADATA_INVALID", [finding.code for finding in report.findings])

    def test_fully_populated_third_party_component_with_valid_sha256_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            self.write_json(
                root / "compliance" / "third_party_components.json",
                {
                    "components": [
                        {
                            "name": "Example",
                            "version": "1.0.0",
                            "source_url": "https://example.invalid/component",
                            "sha256": "a" * 64,
                            "license_spdx": "MIT",
                            "usage": "test fixture",
                            "redistributed": False,
                        }
                    ],
                    "contract": THIRD_PARTY_CONTRACT,
                },
            )

            report = check_repository(root)

        self.assertNotIn("THIRD_PARTY_METADATA_INVALID", [finding.code for finding in report.findings])

    def test_missing_invalid_and_incompatible_manifests_are_errors(self) -> None:
        cases = (
            ("missing", None),
            ("invalid_json", "not json"),
            ("non_object", []),
            ("wrong_contract", {"contract": "wrong", "project": {}}),
            (
                "invalid_state",
                {
                    "contract": PROVENANCE_CONTRACT,
                    "project": {
                        "license_spdx": "MIT",
                        "license_status": "UNDECIDED",
                        "name": "HanEngine",
                    },
                },
            ),
            (
                "incomplete_project",
                {
                    "contract": PROVENANCE_CONTRACT,
                    "project": {
                        "license_spdx": "NOASSERTION",
                        "license_status": "UNDECIDED",
                        "name": "HanEngine",
                    },
                },
            ),
        )
        for name, content in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                self.make_repository(root)
                provenance_path = root / "compliance" / "provenance.json"
                if content is None:
                    provenance_path.unlink()
                elif isinstance(content, str):
                    provenance_path.write_text(content, encoding="utf-8")
                else:
                    self.write_json(provenance_path, content)

                report = check_repository(root)

                self.assertFalse(report.ok)
                self.assertTrue(report.errors)

    def test_finding_and_report_serialization_is_deterministic(self) -> None:
        report = ComplianceReport(
            findings=(
                ComplianceFinding("Z_CODE", "WARNING", "last", "z"),
                ComplianceFinding("A_CODE", "ERROR", "first"),
            )
        )

        self.assertEqual(
            report.to_dict(),
            {
                "findings": [
                    {"code": "A_CODE", "message": "first", "path": None, "severity": "ERROR"},
                    {"code": "Z_CODE", "message": "last", "path": "z", "severity": "WARNING"},
                ],
                "ok": False,
            },
        )
        self.assertEqual(
            json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n",
            '{\n  "findings": [\n    {\n      "code": "A_CODE",\n      "message": "first",\n      "path": null,\n      "severity": "ERROR"\n    },\n    {\n      "code": "Z_CODE",\n      "message": "last",\n      "path": "z",\n      "severity": "WARNING"\n    }\n  ],\n  "ok": false\n}\n',
        )

    def test_finding_rejects_an_invalid_severity(self) -> None:
        with self.assertRaises(ValueError):
            ComplianceFinding("CODE", "INFO", "message")

    def test_cli_json_audit_and_release_exit_codes(self) -> None:
        command = [sys.executable, str(REPOSITORY_ROOT / "tools" / "check_compliance.py"), "--json"]

        audit = subprocess.run(command, cwd=REPOSITORY_ROOT, text=True, capture_output=True, check=False)
        release = subprocess.run(
            [*command, "--release"], cwd=REPOSITORY_ROOT, text=True, capture_output=True, check=False
        )

        self.assertEqual(audit.returncode, 0, audit.stderr)
        self.assertEqual(release.returncode, 1, release.stderr)
        self.assertTrue(json.loads(audit.stdout)["ok"])
        self.assertFalse(json.loads(release.stdout)["ok"])

    def test_checker_does_not_modify_tested_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            before = self.tree_hashes(root)

            check_repository(root)

            self.assertEqual(self.tree_hashes(root), before)

    def tree_hashes(self, root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
