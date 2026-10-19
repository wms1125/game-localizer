import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from game_localizer.hanengine.backup import BackupManager
from game_localizer.hanengine.packaging import UnsafePackageError, ZipPackageModifier
from game_localizer.hanengine.routing import (
    EvaluationStatus,
    RiskLevel,
    RouteOperation,
    RoutePhase,
    RoutePlan,
)


def route(project_id="project"):
    allowed = frozenset({RouteOperation.INSTALL_PATCH})
    return RoutePlan(
        project_id=project_id,
        phase=RoutePhase.FINAL,
        risk_before=RiskLevel.H0_PROJECT,
        risk_after=RiskLevel.H0_PROJECT,
        allowed_operations=allowed,
        blocked_operations=frozenset(RouteOperation) - allowed,
        matches=(),
        evaluation_status=EvaluationStatus.COMPLETE,
        unknown_evidence=False,
        decision_reasons=(),
    )


class BackupTests(unittest.TestCase):
    def test_apply_and_restore_round_trip_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "game"
            backup_root = Path(directory) / "backups"
            root.mkdir()
            target = root / "game.txt"
            target.write_text("original", encoding="utf-8")
            manager = BackupManager()
            manifest = manager.create(root, (Path("game.txt"),), backup_root=backup_root)
            manager.apply(root, {Path("game.txt"): b"translated"}, manifest)
            self.assertEqual(target.read_bytes(), b"translated")
            manager.restore(root, manifest)
            self.assertEqual(target.read_text(encoding="utf-8"), "original")
            self.assertEqual(manifest.entries[0].sha256_before, hashlib.sha256(b"original").hexdigest())

    def test_apply_rolls_back_when_staging_or_commit_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "game"
            root.mkdir()
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / "b.txt").write_text("b", encoding="utf-8")
            manager = BackupManager()
            manifest = manager.create(root, (Path("a.txt"), Path("b.txt")), backup_root=Path(directory) / "backups")
            with self.assertRaises(OSError):
                manager.apply(root, {Path("a.txt"): b"new-a", Path("missing/b.txt"): b"bad"}, manifest)
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "a")
            self.assertEqual((root / "b.txt").read_text(encoding="utf-8"), "b")

    def test_manifest_round_trip_is_json_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "game"
            root.mkdir()
            (root / "a.txt").write_text("a", encoding="utf-8")
            manifest = BackupManager().create(root, (Path("a.txt"),), backup_root=Path(directory) / "backups")
            self.assertEqual(type(manifest).from_dict(manifest.to_dict()), manifest)


class PackageTests(unittest.TestCase):
    def make_zip(self, path: Path, *, encrypted: bool = False):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("game/script.rpy", b'"Hello"')
            if encrypted:
                info = zipfile.ZipInfo("encrypted.txt")
                archive.writestr(info, b"secret")
        if encrypted:
            payload = bytearray(path.read_bytes())
            for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
                cursor = 0
                while True:
                    cursor = payload.find(signature, cursor)
                    if cursor < 0:
                        break
                    payload[cursor + flag_offset] |= 0x1
                    cursor += len(signature)
            path.write_bytes(payload)

    def test_builds_modified_copy_and_keeps_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "game.zip"
            output = root / "localized.zip"
            self.make_zip(source)
            original = source.read_bytes()
            result = ZipPackageModifier().build(source, {Path("game/script.rpy"): b'"Hello"\n"\u4f60\u597d"'}, output)
            self.assertTrue(result.output_path.is_file())
            self.assertEqual(source.read_bytes(), original)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("game/script.rpy"), b'"Hello"\n"\u4f60\u597d"')

    def test_rejects_unsafe_paths_encrypted_entries_and_in_place_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "game.zip"
            self.make_zip(source)
            with self.assertRaises(UnsafePackageError):
                ZipPackageModifier().build(source, {Path("../escape"): b"bad"}, root / "out.zip")
            with self.assertRaises(ValueError):
                ZipPackageModifier().build(source, {}, source)

            encrypted = root / "encrypted.zip"
            self.make_zip(encrypted, encrypted=True)
            with self.assertRaises(UnsafePackageError):
                ZipPackageModifier().build(encrypted, {}, root / "out-encrypted.zip")

    def test_apply_to_project_requires_final_route_with_install_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "game.zip"
            self.make_zip(source)
            result = ZipPackageModifier().apply_to_project(
                source,
                {Path("game/script.rpy"): b"translated"},
                route=route(),
                backup_root=root / "backups",
            )
            self.assertEqual(zipfile.ZipFile(source).read("game/script.rpy"), b"translated")
            self.assertTrue(result.backup.entries)


if __name__ == "__main__":
    unittest.main()
