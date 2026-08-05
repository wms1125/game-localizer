"""Generate a deterministic SPDX 2.3 SBOM from HanEngine compliance manifests."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DOCUMENT_NAMESPACE = "https://github.com/wms1125/game-localizer/sbom/hanengine-foundation"
CREATED = "2026-08-05T00:00:00Z"
CREATOR = "Tool: HanEngine compliance foundation"
_PROVENANCE_CONTRACT = "hanengine.provenance/v1"
_COMPONENTS_CONTRACT = "hanengine.third-party/v1"
_COMPONENT_FIELDS = frozenset({
    "name", "version", "source_url", "sha256", "license_spdx", "usage", "redistributed",
})
_SHA256 = re.compile(r"[0-9A-Fa-f]{64}\Z")


def _read_object(path: Path, description: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {description}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid {description}")
    return value


def _valid_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _read_project(root: Path) -> dict[str, object]:
    provenance = _read_object(root / "compliance" / "provenance.json", "provenance")
    project = provenance.get("project")
    if provenance.get("contract") != _PROVENANCE_CONTRACT or not isinstance(project, dict):
        raise ValueError("invalid provenance")
    if not all(_valid_text(project.get(field)) for field in ("name", "repository", "version", "license_status", "license_spdx")):
        raise ValueError("invalid provenance")
    return project


def _read_components(root: Path) -> list[dict[str, object]]:
    manifest = _read_object(root / "compliance" / "third_party_components.json", "component manifest")
    components = manifest.get("components")
    if manifest.get("contract") != _COMPONENTS_CONTRACT or not isinstance(components, list):
        raise ValueError("invalid component manifest")
    validated: list[dict[str, object]] = []
    for component in components:
        if not isinstance(component, dict) or not _COMPONENT_FIELDS.issubset(component):
            raise ValueError("invalid component")
        if not all(_valid_text(component[field]) for field in _COMPONENT_FIELDS - {"redistributed"}):
            raise ValueError("invalid component")
        if not isinstance(component["redistributed"], bool) or not _SHA256.fullmatch(component["sha256"]):
            raise ValueError("invalid component")
        validated.append(component)
    return validated


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalized(name)).strip("-")
    if not slug:
        raise ValueError("invalid component name")
    return slug


def build_sbom(root: Path) -> dict[str, object]:
    """Build an SPDX document from validated provenance and component manifests."""
    project = _read_project(root)
    components = _read_components(root)
    ordered_components = sorted(
        components,
        key=lambda component: (
            _normalized(component["name"]),
            _normalized(component["version"]),
            _normalized(component["source_url"]),
        ),
    )
    packages: list[dict[str, object]] = [{
        "SPDXID": "SPDXRef-Package-HanEngine",
        "copyrightText": "NOASSERTION",
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "name": project["name"],
        "versionInfo": project["version"],
    }]
    relationships: list[dict[str, str]] = [{
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": "SPDXRef-Package-HanEngine",
    }]
    identifiers = {"SPDXRef-Package-HanEngine"}
    for component in ordered_components:
        identifier = f"SPDXRef-ThirdParty-{_slug(component['name'])}"
        if identifier in identifiers:
            raise ValueError("duplicate generated SPDX ID")
        identifiers.add(identifier)
        packages.append({
            "SPDXID": identifier,
            "checksums": [{"algorithm": "SHA256", "checksumValue": component["sha256"].upper()}],
            "copyrightText": "NOASSERTION",
            "downloadLocation": component["source_url"],
            "filesAnalyzed": False,
            "licenseConcluded": component["license_spdx"],
            "licenseDeclared": component["license_spdx"],
            "name": component["name"],
            "versionInfo": component["version"],
        })
        relationships.append({
            "spdxElementId": "SPDXRef-Package-HanEngine",
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": identifier,
        })
    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {"created": CREATED, "creators": [CREATOR]},
        "dataLicense": "CC0-1.0",
        "documentNamespace": DOCUMENT_NAMESPACE,
        "name": "HanEngine compliance foundation SBOM",
        "packages": packages,
        "relationships": relationships,
        "spdxVersion": "SPDX-2.3",
    }


def render_sbom(payload: dict[str, object]) -> str:
    """Render an SBOM with canonical JSON formatting."""
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"


def write_sbom(root: Path) -> Path:
    """Write the generated SBOM as UTF-8 bytes with LF-only line endings."""
    path = Path(root) / "compliance" / "sbom.spdx.json"
    path.write_bytes(render_sbom(build_sbom(Path(root))).encode("utf-8"))
    return path


def check_sbom(root: Path) -> bool:
    """Return whether the committed SBOM exactly matches generated UTF-8 bytes."""
    path = Path(root) / "compliance" / "sbom.spdx.json"
    try:
        actual = path.read_bytes()
    except OSError:
        return False
    return actual == render_sbom(build_sbom(Path(root))).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the HanEngine SPDX SBOM.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.check:
        return 0 if check_sbom(arguments.root) else 1
    write_sbom(arguments.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
