from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.check_compliance import (
    ComplianceFinding,
    ComplianceReport,
    PROVENANCE_CONTRACT,
    THIRD_PARTY_CONTRACT,
    check_repository,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESTRICTED_NAME = "RenpyThief 6.7.7 authorized recovery package"
RESTRICTED_PURPOSE = "static architecture analysis only"
RESTRICTED_SHA256 = "2DF39E113C8CA2401749A2F985E00EB96F1FA2BC5FB82F47F77A3747EF67767A"
REQUIRED_IMPLEMENTATION_SOURCES = [
    {
        "kind": "project_owned",
        "scope": "game_localizer/** and repository-owned synthetic fixtures",
    },
    {
        "kind": "official_documentation",
        "scope": "documented per implementation change",
    },
]


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
                "restricted_reference_material": [
                    {
                        "name": RESTRICTED_NAME,
                        "purpose": RESTRICTED_PURPOSE,
                        "repository_inclusion": "FORBIDDEN",
                        "sha256": RESTRICTED_SHA256,
                    }
                ],
                "implementation_sources": REQUIRED_IMPLEMENTATION_SOURCES,
            },
        )
        self.write_json(
            directory / "compliance" / "third_party_components.json",
            {"components": [], "contract": THIRD_PARTY_CONTRACT},
        )

    def write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def read_provenance(self, root: Path) -> dict[str, object]:
        return json.loads((root / "compliance" / "provenance.json").read_text(encoding="utf-8"))

    def provenance_error_codes(self, root: Path) -> list[str]:
        return [finding.code for finding in check_repository(root).errors]

    def scandir_context(self, entries: list[object]) -> mock.MagicMock:
        context = mock.MagicMock()
        context.__enter__.return_value = iter(entries)
        context.__exit__.return_value = False
        return context

    def regular_tree_hashes(self, root: Path) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for current, _, files in os.walk(root, followlinks=False):
            for name in files:
                path = Path(current) / name
                if stat.S_ISREG(os.lstat(path).st_mode):
                    hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes

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

    def test_root_license_file_is_inconsistent_with_undecided_v1_state_and_cannot_release(self) -> None:
        for contents in ("", "A placeholder is not a license decision.\n"):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                self.make_repository(root)
                (root / "LICENSE").write_text(contents, encoding="utf-8")

                audit = check_repository(root)
                release = check_repository(root, release=True)

                self.assertIn("PROJECT_LICENSE_STATE_INCONSISTENT", [item.code for item in audit.errors])
                self.assertIn("PROJECT_LICENSE_STATE_INCONSISTENT", [item.code for item in release.errors])
                self.assertIn("PROJECT_LICENSE_REQUIRED", [item.code for item in release.errors])

    def test_v1_rejects_any_project_license_state_other_than_undecided_noassertion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            provenance = self.read_provenance(root)
            provenance["project"]["license_status"] = "DECIDED"
            provenance["project"]["license_spdx"] = "MIT"
            self.write_json(root / "compliance" / "provenance.json", provenance)

            report = check_repository(root)

        self.assertIn("PROJECT_LICENSE_STATE_INVALID", [item.code for item in report.errors])

    def test_forbidden_recovered_material_is_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            restricted = root / "recovered-source" / "embedded-scripts"
            restricted.mkdir(parents=True)
            (restricted / "renpythief.rpy").write_text("", encoding="utf-8")

            report = check_repository(root)

        self.assertIn("RESTRICTED_MATERIAL_TRACKED", [finding.code for finding in report.findings])

    def test_forbidden_path_segments_are_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            restricted = root / "ReCoVeReD-SoUrCe"
            restricted.mkdir(parents=True)
            (restricted / "synthetic.txt").write_text("synthetic", encoding="utf-8")

            report = check_repository(root)

        self.assertIn("RESTRICTED_MATERIAL_TRACKED", [finding.code for finding in report.errors])

    def test_skipped_path_segments_are_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            skipped = root / ".GIT" / "embedded-scripts"
            skipped.mkdir(parents=True)
            (skipped / "ignored.rpy").write_text("synthetic", encoding="utf-8")

            report = check_repository(root)

        self.assertNotIn("RESTRICTED_MATERIAL_TRACKED", [finding.code for finding in report.errors])

    def test_registered_recovery_archive_name_is_blocked_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            (root / "RENPYTHIEF-6.7.7-AUTHORIZED-RECOVERED-SOURCE.7Z").write_bytes(b"synthetic")

            report = check_repository(root)

        self.assertIn("RESTRICTED_MATERIAL_TRACKED", [finding.code for finding in report.errors])

    def test_registered_restricted_hash_blocks_a_renamed_synthetic_file(self) -> None:
        payload = b"synthetic restricted fixture"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            provenance = self.read_provenance(root)
            provenance["restricted_reference_material"].append(
                {
                    "name": "Synthetic restricted fixture",
                    "purpose": "compliance checker regression test",
                    "repository_inclusion": "FORBIDDEN",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            self.write_json(root / "compliance" / "provenance.json", provenance)
            (root / "renamed.bin").write_bytes(payload)

            report = check_repository(root)

        self.assertIn("RESTRICTED_MATERIAL_TRACKED", [finding.code for finding in report.errors])

    def test_unreadable_scanned_file_fails_closed_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            (root / "candidate.bin").write_bytes(b"synthetic")

            with mock.patch("tools.check_compliance._sha256_file", side_effect=OSError("denied")):
                report = check_repository(root)

        unreadable = [item for item in report.errors if item.code == "COMPLIANCE_FILE_UNREADABLE"]
        self.assertTrue(unreadable)
        self.assertEqual(
            [(item.code, item.message) for item in unreadable],
            [("COMPLIANCE_FILE_UNREADABLE", "Repository file could not be hashed.")] * len(unreadable),
        )

    def test_file_symlink_to_outside_is_rejected_before_hashing_and_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            root = base / "root"
            root.mkdir()
            self.make_repository(root)
            outside = base / "outside.bin"
            outside.write_bytes(b"outside synthetic fixture")
            link = root / "outside-link.bin"
            os.symlink(outside, link)
            before_root = self.regular_tree_hashes(root)
            before_outside = hashlib.sha256(outside.read_bytes()).hexdigest()
            hashed: list[Path] = []

            def record_hash(path: Path) -> str:
                hashed.append(path)
                return "0" * 64

            with mock.patch("tools.check_compliance._sha256_file", side_effect=record_hash):
                report = check_repository(root)

            self.assertIn("COMPLIANCE_PATH_UNSAFE", [item.code for item in report.errors])
            self.assertNotIn(link, hashed)
            self.assertEqual(self.regular_tree_hashes(root), before_root)
            self.assertEqual(hashlib.sha256(outside.read_bytes()).hexdigest(), before_outside)

    def test_directory_symlink_to_outside_is_rejected_without_descending_or_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            root = base / "root"
            root.mkdir()
            self.make_repository(root)
            outside = base / "outside"
            outside.mkdir()
            secret = outside / "secret.bin"
            secret.write_bytes(b"outside directory fixture")
            link = root / "linked-directory"
            os.symlink(outside, link, target_is_directory=True)
            before_root = self.regular_tree_hashes(root)
            before_outside = self.regular_tree_hashes(outside)
            hashed: list[Path] = []

            with mock.patch(
                "tools.check_compliance._sha256_file",
                side_effect=lambda path: hashed.append(path) or "0" * 64,
            ):
                report = check_repository(root)

            self.assertIn("COMPLIANCE_PATH_UNSAFE", [item.code for item in report.errors])
            self.assertFalse(any(path == link or link in path.parents for path in hashed))
            self.assertEqual(self.regular_tree_hashes(root), before_root)
            self.assertEqual(self.regular_tree_hashes(outside), before_outside)

    def test_windows_reparse_attribute_is_rejected_before_type_checks_or_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            entry = mock.MagicMock()
            entry.name = "junction"
            entry.path = str(root / entry.name)
            entry.stat.return_value = mock.Mock(
                st_mode=stat.S_IFDIR,
                st_dev=1,
                st_ino=2,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )

            with mock.patch("os.scandir", return_value=self.scandir_context([entry])), mock.patch(
                "tools.check_compliance._sha256_file"
            ) as hash_file:
                report = check_repository(root)

            self.assertIn("COMPLIANCE_PATH_UNSAFE", [item.code for item in report.errors])
            entry.stat.assert_called_once_with(follow_symlinks=False)
            entry.is_dir.assert_not_called()
            entry.is_file.assert_not_called()
            hash_file.assert_not_called()

    def test_scandir_permission_error_fails_closed_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)

            with mock.patch("os.scandir", side_effect=PermissionError("denied")):
                report = check_repository(root)

        failures = [item for item in report.errors if item.code == "COMPLIANCE_SCAN_FAILED"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].message, "Repository directory could not be enumerated.")

    def test_directory_lstat_error_fails_closed_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)

            with mock.patch("tools.check_compliance.os.lstat", side_effect=PermissionError("denied")):
                report = check_repository(root)

        failures = [item for item in report.errors if item.code == "COMPLIANCE_SCAN_FAILED"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].message, "Repository directory could not be inspected.")

    def test_queued_directory_identity_change_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            queued = root / "queued"
            queued.mkdir()
            (queued / "hidden.bin").write_bytes(b"synthetic")
            displaced = root / "queued-before-swap"
            real_scandir = os.scandir
            replaced = False

            def replace_before_enumeration(path: object):
                nonlocal replaced
                if Path(path) == queued and not replaced:
                    queued.rename(displaced)
                    queued.mkdir()
                    replaced = True
                return real_scandir(path)

            with mock.patch("os.scandir", side_effect=replace_before_enumeration):
                report = check_repository(root)

        changed = [item for item in report.errors if item.code == "COMPLIANCE_PATH_UNSAFE"]
        self.assertTrue(changed)
        self.assertIn("Repository directory changed during scan.", [item.message for item in changed])

    def test_entry_lstat_and_type_errors_fail_closed_deterministically(self) -> None:
        cases = ("stat", "is_dir", "is_file")
        for failing_method in cases:
            with self.subTest(failing_method=failing_method), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                self.make_repository(root)
                candidate = root / "candidate.bin"
                candidate.write_bytes(b"synthetic")
                metadata = os.lstat(candidate)
                entry = mock.MagicMock()
                entry.name = candidate.name
                entry.path = str(candidate)
                entry.stat.return_value = metadata
                entry.is_dir.return_value = False
                entry.is_file.return_value = True
                getattr(entry, failing_method).side_effect = OSError("denied")

                with mock.patch("os.scandir", return_value=self.scandir_context([entry])):
                    report = check_repository(root)

                failures = [item for item in report.errors if item.code == "COMPLIANCE_SCAN_FAILED"]
                self.assertEqual(len(failures), 1)
                self.assertEqual(failures[0].message, "Repository entry could not be inspected.")

    def test_safe_regular_entry_uses_nonfollowing_checks_and_is_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root)
            candidate = root / "candidate.bin"
            candidate.write_bytes(b"synthetic")
            entry = mock.MagicMock()
            entry.name = candidate.name
            entry.path = str(candidate)
            entry.stat.return_value = os.lstat(candidate)
            entry.is_dir.return_value = False
            entry.is_file.return_value = True

            with mock.patch("os.scandir", return_value=self.scandir_context([entry])), mock.patch(
                "tools.check_compliance._sha256_file", return_value="0" * 64
            ) as hash_file:
                report = check_repository(root)

            self.assertTrue(report.ok)
            entry.stat.assert_called_once_with(follow_symlinks=False)
            entry.is_dir.assert_called_once_with(follow_symlinks=False)
            entry.is_file.assert_called_once_with(follow_symlinks=False)
            hash_file.assert_called_once_with(candidate)

    def test_restricted_reference_material_requires_complete_nonempty_records(self) -> None:
        cases = {
            "missing_array": None,
            "non_array": {},
            "empty_array": [],
            "missing_field": [{"name": RESTRICTED_NAME}],
            "bad_hash": [
                {
                    "name": RESTRICTED_NAME,
                    "purpose": RESTRICTED_PURPOSE,
                    "repository_inclusion": "FORBIDDEN",
                    "sha256": "bad",
                }
            ],
            "non_forbidden": [
                {
                    "name": RESTRICTED_NAME,
                    "purpose": RESTRICTED_PURPOSE,
                    "repository_inclusion": "ALLOWED",
                    "sha256": RESTRICTED_SHA256,
                }
            ],
            "known_name_changed": [
                {
                    "name": "Different package",
                    "purpose": RESTRICTED_PURPOSE,
                    "repository_inclusion": "FORBIDDEN",
                    "sha256": RESTRICTED_SHA256,
                }
            ],
            "known_purpose_changed": [
                {
                    "name": RESTRICTED_NAME,
                    "purpose": "different purpose",
                    "repository_inclusion": "FORBIDDEN",
                    "sha256": RESTRICTED_SHA256,
                }
            ],
            "known_hash_changed": [
                {
                    "name": RESTRICTED_NAME,
                    "purpose": RESTRICTED_PURPOSE,
                    "repository_inclusion": "FORBIDDEN",
                    "sha256": "a" * 64,
                }
            ],
        }
        for name, records in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                self.make_repository(root)
                provenance = self.read_provenance(root)
                if records is None:
                    del provenance["restricted_reference_material"]
                else:
                    provenance["restricted_reference_material"] = records
                self.write_json(root / "compliance" / "provenance.json", provenance)

                codes = self.provenance_error_codes(root)

                self.assertIn("PROVENANCE_RESTRICTED_MATERIAL_INVALID", codes)

    def test_implementation_sources_require_complete_nonempty_required_records(self) -> None:
        cases = {
            "missing_array": None,
            "non_array": {},
            "empty_array": [],
            "missing_field": [{"kind": "project_owned"}],
            "empty_field": [{"kind": "project_owned", "scope": ""}],
            "missing_project_owned": [REQUIRED_IMPLEMENTATION_SOURCES[1]],
            "missing_official_documentation": [REQUIRED_IMPLEMENTATION_SOURCES[0]],
        }
        for name, records in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                self.make_repository(root)
                provenance = self.read_provenance(root)
                if records is None:
                    del provenance["implementation_sources"]
                else:
                    provenance["implementation_sources"] = records
                self.write_json(root / "compliance" / "provenance.json", provenance)

                codes = self.provenance_error_codes(root)

                self.assertIn("PROVENANCE_IMPLEMENTATION_SOURCES_INVALID", codes)

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
