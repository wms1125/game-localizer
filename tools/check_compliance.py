"""Read-only HanEngine provenance and compliance checker."""

from __future__ import annotations

import argparse
import hashlib
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
    "embedded-scripts", "unpacked", "injector-source", "ghidra-scripts", "recovered-source",
})
SKIPPED_PATH_SEGMENTS = frozenset({".git", ".superpowers", "__pycache__"})
COMPONENT_FIELDS = frozenset({
    "name", "version", "source_url", "sha256", "license_spdx", "usage", "redistributed",
})
RESTRICTED_ARCHIVE_NAMES = frozenset({"renpythief-6.7.7-authorized-recovered-source.7z"})
RESTRICTED_REFERENCE = {
    "name": "RenpyThief 6.7.7 authorized recovery package",
    "purpose": "static architecture analysis only",
    "repository_inclusion": "FORBIDDEN",
    "sha256": "2DF39E113C8CA2401749A2F985E00EB96F1FA2BC5FB82F47F77A3747EF67767A",
}
REQUIRED_IMPLEMENTATION_SOURCES = frozenset({
    ("project_owned", "game_localizer/** and repository-owned synthetic fixtures"),
    ("official_documentation", "documented per implementation change"),
})
_SHA256_PATTERN = re.compile(r"[0-9A-Fa-f]{64}\Z")


@dataclass(frozen=True)
class ComplianceFinding:
    code: str
    severity: str
    message: str
    path: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in {"ERROR", "WARNING"}:
            raise ValueError("severity must be ERROR or WARNING")

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


def _valid_restricted_record(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    for field in ("name", "purpose", "repository_inclusion", "sha256"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            return False
    return (
        record["repository_inclusion"] == "FORBIDDEN"
        and bool(_SHA256_PATTERN.fullmatch(record["sha256"]))
    )


def _valid_implementation_source(source: object) -> bool:
    return (
        isinstance(source, dict)
        and isinstance(source.get("kind"), str)
        and bool(source["kind"].strip())
        and isinstance(source.get("scope"), str)
        and bool(source["scope"].strip())
    )


def _validate_provenance(root: Path, has_license: bool, findings: list[ComplianceFinding]) -> frozenset[str]:
    relative_path = "compliance/provenance.json"
    restricted_hashes = {RESTRICTED_REFERENCE["sha256"].casefold()}
    manifest = _read_manifest(root, relative_path, findings)
    if manifest is None:
        return frozenset(restricted_hashes)
    if manifest.get("contract") != PROVENANCE_CONTRACT:
        findings.append(_finding("PROVENANCE_CONTRACT_INVALID", "ERROR", "Provenance contract is invalid.", relative_path))
    project = manifest.get("project")
    if not isinstance(project, dict) or not all(
        isinstance(project.get(field), str) and project[field].strip()
        for field in ("name", "repository", "version", "license_status", "license_spdx")
    ):
        findings.append(_finding("PROVENANCE_METADATA_INVALID", "ERROR", "Provenance project data is invalid.", relative_path))
    elif project["license_status"] != "UNDECIDED" or project["license_spdx"] != "NOASSERTION":
        findings.append(
            _finding(
                "PROJECT_LICENSE_STATE_INVALID",
                "ERROR",
                "Provenance v1 must declare UNDECIDED and NOASSERTION.",
                relative_path,
            )
        )
    elif has_license:
        findings.append(
            _finding(
                "PROJECT_LICENSE_STATE_INCONSISTENT",
                "ERROR",
                "A root license file exists while provenance v1 remains undecided.",
                relative_path,
            )
        )

    restricted_records = manifest.get("restricted_reference_material")
    restricted_valid = isinstance(restricted_records, list) and bool(restricted_records)
    if restricted_valid:
        restricted_valid = all(_valid_restricted_record(record) for record in restricted_records)
    if restricted_valid:
        restricted_valid = any(
            all(record.get(field) == value for field, value in RESTRICTED_REFERENCE.items())
            for record in restricted_records
        )
    if not restricted_valid:
        findings.append(
            _finding(
                "PROVENANCE_RESTRICTED_MATERIAL_INVALID",
                "ERROR",
                "Restricted reference material metadata is invalid or missing the required record.",
                relative_path,
            )
        )
    elif isinstance(restricted_records, list):
        restricted_hashes.update(record["sha256"].casefold() for record in restricted_records)

    implementation_sources = manifest.get("implementation_sources")
    sources_valid = isinstance(implementation_sources, list) and bool(implementation_sources)
    if sources_valid:
        sources_valid = all(_valid_implementation_source(source) for source in implementation_sources)
    if sources_valid:
        source_pairs = {(source["kind"], source["scope"]) for source in implementation_sources}
        sources_valid = REQUIRED_IMPLEMENTATION_SOURCES.issubset(source_pairs)
    if not sources_valid:
        findings.append(
            _finding(
                "PROVENANCE_IMPLEMENTATION_SOURCES_INVALID",
                "ERROR",
                "Implementation sources are invalid or missing required records.",
                relative_path,
            )
        )
    return frozenset(restricted_hashes)


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_restricted_material(
    root: Path,
    restricted_hashes: frozenset[str],
    findings: list[ComplianceFinding],
) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        casefolded_parts = frozenset(part.casefold() for part in relative_path.parts)
        if SKIPPED_PATH_SEGMENTS.intersection(casefolded_parts):
            continue
        restricted_by_path = bool(FORBIDDEN_PATH_SEGMENTS.intersection(casefolded_parts))
        restricted_by_name = path.name.casefold() in RESTRICTED_ARCHIVE_NAMES
        try:
            restricted_by_hash = _sha256_file(path).casefold() in restricted_hashes
        except OSError:
            findings.append(
                _finding(
                    "COMPLIANCE_FILE_UNREADABLE",
                    "ERROR",
                    "Repository file could not be hashed.",
                    relative_path,
                )
            )
            continue
        if restricted_by_path or restricted_by_name or restricted_by_hash:
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
    restricted_hashes = _validate_provenance(root, has_license, findings)
    _validate_components(root, findings)
    _scan_restricted_material(root, restricted_hashes, findings)
    if release:
        findings.append(
            _finding(
                "PROJECT_LICENSE_REQUIRED",
                "ERROR",
                "A versioned project-license decision is required for release.",
            )
        )
    elif not has_license:
        findings.append(_finding("PROJECT_LICENSE_UNDECIDED", "WARNING", "Root project license remains undecided."))
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
