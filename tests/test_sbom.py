from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.generate_sbom import (
    CREATED,
    CREATOR,
    DOCUMENT_NAMESPACE,
    build_sbom,
    check_sbom,
    render_sbom,
    write_sbom,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROJECT = {
    "license_spdx": "NOASSERTION",
    "license_status": "UNDECIDED",
    "name": "HanEngine",
    "repository": "https://example.invalid/hanengine",
    "version": "0.0.0-test",
}
COMPONENT = {
    "license_spdx": "MIT",
    "name": "Example Component",
    "redistributed": False,
    "sha256": "a" * 64,
    "source_url": "https://example.invalid/component",
    "usage": "test fixture",
    "version": "1.2.3",
}


class SbomTests(unittest.TestCase):
    def make_repository(self, directory: Path, *, components: list[object] | None = None) -> None:
        (directory / "compliance").mkdir()
        self.write_json(
            directory / "compliance" / "provenance.json",
            {"contract": "hanengine.provenance/v1", "project": PROJECT},
        )
        self.write_json(
            directory / "compliance" / "third_party_components.json",
            {"components": [] if components is None else components, "contract": "hanengine.third-party/v1"},
        )

    def write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_document_uses_required_spdx_metadata_and_hanengine_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            payload = build_sbom(self.make_root(temporary_directory))

        self.assertEqual(payload["spdxVersion"], "SPDX-2.3")
        self.assertEqual(payload["dataLicense"], "CC0-1.0")
        self.assertEqual(payload["SPDXID"], "SPDXRef-DOCUMENT")
        self.assertEqual(
            payload["creationInfo"],
            {"created": CREATED, "creators": [CREATOR]},
        )
        self.assertEqual(payload["documentNamespace"], DOCUMENT_NAMESPACE)
        self.assertEqual(
            payload["packages"][0],
            {
                "SPDXID": "SPDXRef-Package-HanEngine",
                "copyrightText": "NOASSERTION",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "name": "HanEngine",
                "versionInfo": "0.0.0-test",
            },
        )
        self.assertEqual(
            payload["relationships"][0],
            {
                "relatedSpdxElement": "SPDXRef-Package-HanEngine",
                "relationshipType": "DESCRIBES",
                "spdxElementId": "SPDXRef-DOCUMENT",
            },
        )

    def test_rendering_is_deterministic_and_matches_written_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = self.make_root(temporary_directory)
            payload = build_sbom(root)
            self.assertEqual(render_sbom(payload), render_sbom(payload))

            snapshot = write_sbom(root)

            self.assertEqual(snapshot.read_text(encoding="utf-8"), render_sbom(payload))
            self.assertEqual(snapshot.read_bytes(), render_sbom(payload).encode("utf-8"))

    def test_component_converts_to_package_and_dependency_relationship(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root, components=[COMPONENT])
            payload = build_sbom(root)

        self.assertEqual(
            payload["packages"][1],
            {
                "SPDXID": "SPDXRef-ThirdParty-example-component",
                "checksums": [{"algorithm": "SHA256", "checksumValue": "A" * 64}],
                "copyrightText": "NOASSERTION",
                "downloadLocation": "https://example.invalid/component",
                "filesAnalyzed": False,
                "licenseConcluded": "MIT",
                "licenseDeclared": "MIT",
                "name": "Example Component",
                "versionInfo": "1.2.3",
            },
        )
        self.assertEqual(
            payload["relationships"][1],
            {
                "relatedSpdxElement": "SPDXRef-ThirdParty-example-component",
                "relationshipType": "DEPENDS_ON",
                "spdxElementId": "SPDXRef-Package-HanEngine",
            },
        )

    def test_invalid_component_or_provenance_rejects_partial_sbom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.make_repository(root, components=[{"name": "incomplete"}])
            with self.assertRaisesRegex(ValueError, "component"):
                build_sbom(root)

            self.write_json(root / "compliance" / "third_party_components.json", {"components": [], "contract": "hanengine.third-party/v1"})
            self.write_json(root / "compliance" / "provenance.json", {"contract": "hanengine.provenance/v1", "project": {}})
            with self.assertRaisesRegex(ValueError, "provenance"):
                build_sbom(root)

    def test_duplicate_generated_component_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            duplicate = {**COMPONENT, "name": "Example-Component", "version": "2.0.0"}
            self.make_repository(root, components=[COMPONENT, duplicate])

            with self.assertRaisesRegex(ValueError, "duplicate"):
                build_sbom(root)

    def test_check_mode_compares_exact_bytes_and_never_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = self.make_root(temporary_directory)
            snapshot = write_sbom(root)
            before = self.tree_hashes(root)

            self.assertTrue(check_sbom(root))
            self.assertEqual(self.tree_hashes(root), before)

            snapshot.write_bytes(snapshot.read_bytes().replace(b"\n", b"\r\n"))
            drifted = self.tree_hashes(root)
            self.assertFalse(check_sbom(root))
            self.assertEqual(self.tree_hashes(root), drifted)

    def test_cli_check_exit_codes_and_leaves_drift_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = self.make_root(temporary_directory)
            command = [sys.executable, str(REPOSITORY_ROOT / "tools" / "generate_sbom.py"), "--root", str(root), "--check"]
            self.assertEqual(subprocess.run(command, check=False).returncode, 1)
            write_sbom(root)
            self.assertEqual(subprocess.run(command, check=False).returncode, 0)

            snapshot = root / "compliance" / "sbom.spdx.json"
            snapshot.write_bytes(snapshot.read_bytes() + b" ")
            drifted = snapshot.read_bytes()
            self.assertEqual(subprocess.run(command, check=False).returncode, 1)
            self.assertEqual(snapshot.read_bytes(), drifted)

    def test_rendered_bytes_are_utf8_lf_terminated_without_bom_or_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            rendered = render_sbom(build_sbom(self.make_root(temporary_directory))).encode("utf-8")

        self.assertFalse(rendered.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", rendered)
        self.assertTrue(rendered.endswith(b"\n"))
        self.assertFalse(rendered.endswith(b"\n\n"))

    def make_root(self, temporary_directory: str) -> Path:
        root = Path(temporary_directory)
        self.make_repository(root)
        return root

    def tree_hashes(self, root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
