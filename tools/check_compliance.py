"""Read-only HanEngine provenance and compliance checker."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


PROVENANCE_CONTRACT = "hanengine.provenance/v1"
THIRD_PARTY_CONTRACT = "hanengine.third-party/v1"
LICENSE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "COPYING.txt", "COPYING.md")
FORBIDDEN_PATH_SEGMENTS = frozenset({
    "decompiled-native", "decompiled-dotnet", "runtime-dump-raw",
    "embedded-scripts", "unpacked", "injector-source", "ghidra-scripts",
})
SKIPPED_PATH_SEGMENTS = frozenset({".git", ".superpowers", "__pycache__"})
COMPONENT_FIELDS = frozenset({
    "name", "version", "source_url", "sha256", "license_spdx", "usage", "redistributed",
})
_SHA256_PATTERN = re.compile(r"[0-9A-Fa-f]{64}\\Z")


@dataclass(frozen=True)
class ComplianceFinding:
    code: str
    severity: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True)
class ComplianceReport:
    findings: tuple[ComplianceFinding, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "findings",
            tuple(sorted(self.findings, key=lambda item: (item.severity, item.code, item.path or "", item.message))),
        )

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def errors(self) -> tuple[ComplianceFinding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "ERROR")

    @property
    def warnings(self) -> tuple[ComplianceFinding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "WARNING")

    def to_dict(self) -> dict[str, object]:
        return {"findings": [finding.to_dict() for finding in self.findings], "ok": self.ok}


def _finding(code: str, severity: str, message: str, path: Path | str | None = None) -> ComplianceFinding:
    return ComplianceFinding(code, severity, message, None if path is None else Path(path).as_posix())


def _read_manifest(root: Path, relative_path: str, findings: list[ComplianceFinding]) -> dict[str, object] | None:
    path = root / relative_path
    if not path.is_file():
        findings.append(_finding("COMPLIANCE_FILE_MISSING", "ERROR", "Required compliance file is missing.", relative_path))
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        findings.append(_finding("COMPLIANCE_JSON_INVALID", "ERROR", "Compliance JSON is invalid.", relative_path))
        return None
    if not isinstance(data, dict):
        findings.append(_finding("COMPLIANCE_MANIFEST_INVALID", "ERROR", "Compliance manifest root must be an object.", relative_path))
        return None
    return data


def _validate_provenance(root: Path, has_license: bool, findings: list[ComplianceFinding]) -> None:
    relative_path = "compliance/provenance.json"
    manifest = _read_manifest(root, relative_path, findings)
    if manifest is None:
        return
    if manifest.get("contract") != PROVENANCE_CONTRACT:
        findings.append(_finding("PROVENANCE_CONTRACT_INVALID", "ERROR", "Provenance contract is invalid.", relative_path))
    project = manifest.get("project")
    if not isinstance(project, dict) or not all(
        isinstance(project.get(field), str) and project[field].strip()
        for field in ("name", "repository", "version", "license_status", "license_spdx")
    ):
        findings.append(_finding("PROVENANCE_METADATA_INVALID", "ERROR", "Provenance project data is invalid.", relative_path))
        return
    if not has_license and (
        project["license_status"] != "UNDECIDED" or project["license_spdx"] != "NOASSERTION"
    ):
        findings.append(
            _finding(
                "PROJECT_LICENSE_STATE_INVALID",
                "ERROR",
                "A repository without a root license must declare UNDECIDED and NOASSERTION.",
                relative_path,
            )
        )


def _valid_component(component: object) -> bool:
    if not isinstance(component, dict) or not COMPONENT_FIELDS.issubset(component):
        return False
    if not all(isinstance(component[field], str) and component[field].strip() for field in COMPONENT_FIELDS - {"redistributed"}):
        return False
    return isinstance(component["redistributed"], bool) and bool(_SHA256_PATTERN.fullmatch(component["sha256"]))


def _validate_components(root: Path, findings: list[ComplianceFinding]) -> None:
    relative_path = "compliance/third_party_components.json"
    manifest = _read_manifest(root, relative_path, findings)
    if manifest is None:
        return
    if manifest.get("contract") != THIRD_PARTY_CONTRACT:
        findings.append(_finding("THIRD_PARTY_CONTRACT_INVALID", "ERROR", "Third-party contract is invalid.", relative_path))
    components = manifest.get("components")
    if not isinstance(components, list):
        findings.append(_finding("THIRD_PARTY_METADATA_INVALID", "ERROR", "Third-party components must be a list.", relative_path))
        return
    for index, component in enumerate(components):
        if not _valid_component(component):
            findings.append(
                _finding(
                    "THIRD_PARTY_METADATA_INVALID",
                    "ERROR",
                    "Third-party component metadata is invalid.",
                    f"{relative_path}#{index}",
                )
            )


def _validate_required_documents(root: Path, findings: list[ComplianceFinding]) -> None:
    for relative_path in ("PROVENANCE.md", "THIRD_PARTY_NOTICES.md", "docs/compliance/CLEAN_ROOM_POLICY.md"):
        if not (root / relative_path).is_file():
            findings.append(_finding("COMPLIANCE_FILE_MISSING", "ERROR", "Required compliance file is missing.", relative_path))


def _scan_restricted_material(root: Path, findings: list[ComplianceFinding]) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if SKIPPED_PATH_SEGMENTS.intersection(relative_path.parts):
            continue
        if FORBIDDEN_PATH_SEGMENTS.intersection(relative_path.parts):
            findings.append(
                _finding(
                    "RESTRICTED_MATERIAL_TRACKED",
                    "ERROR",
                    "Restricted material path is forbidden in the repository.",
                    relative_path,
                )
            )


def check_repository(root: Path, *, release: bool = False) -> ComplianceReport:
    """Check a repository without changing any file or directory beneath it."""
    root = Path(root)
    findings: list[ComplianceFinding] = []
    has_license = any((root / name).is_file() for name in LICENSE_NAMES)
    _validate_required_documents(root, findings)
    _validate_provenance(root, has_license, findings)
    _validate_components(root, findings)
    _scan_restricted_material(root, findings)
    if not has_license:
        severity = "ERROR" if release else "WARNING"
        code = "PROJECT_LICENSE_REQUIRED" if release else "PROJECT_LICENSE_UNDECIDED"
        message = "A root project license is required for release." if release else "Root project license remains undecided."
        findings.append(_finding(code, severity, message))
    return ComplianceReport(tuple(findings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check HanEngine compliance metadata.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    arguments = parser.parse_args(argv)
    report = check_repository(arguments.root, release=arguments.release)
    if arguments.as_json:
        sys.stdout.write(json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n")
    else:
        for finding in report.findings:
            location = f" [{finding.path}]" if finding.path else ""
            print(f"{finding.severity} {finding.code}{location}: {finding.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
