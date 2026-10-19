from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .segments import JsonValue, normalize_relative_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class BackupEntry:
    relative_path: str
    sha256_before: str | None
    backup_relative_path: str | None
    existed_before: bool

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "relative_path": self.relative_path,
            "sha256_before": self.sha256_before,
            "backup_relative_path": self.backup_relative_path,
            "existed_before": self.existed_before,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> BackupEntry:
        if not isinstance(payload, Mapping) or set(payload) != {
            "relative_path", "sha256_before", "backup_relative_path", "existed_before"
        }:
            raise ValueError("BackupEntry payload fields do not match schema")
        return cls(
            relative_path=normalize_relative_path(payload["relative_path"]),
            sha256_before=payload["sha256_before"],
            backup_relative_path=payload["backup_relative_path"],
            existed_before=payload["existed_before"],
        )


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    source_root: str
    backup_root: str
    created_at: str
    entries: tuple[BackupEntry, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.backup_id, self.source_root, self.backup_root, self.created_at)):
            raise TypeError("BackupManifest identity fields must be non-empty strings")
        if isinstance(self.entries, (str, bytes)):
            raise TypeError("entries must be ordered")
        entries = tuple(self.entries)
        if any(not isinstance(entry, BackupEntry) for entry in entries):
            raise TypeError("entries must contain BackupEntry values")
        if len({entry.relative_path for entry in entries}) != len(entries):
            raise ValueError("backup entries must be unique")
        object.__setattr__(self, "entries", entries)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "backup_id": self.backup_id,
            "source_root": self.source_root,
            "backup_root": self.backup_root,
            "created_at": self.created_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> BackupManifest:
        if not isinstance(payload, Mapping) or set(payload) != {
            "backup_id", "source_root", "backup_root", "created_at", "entries"
        }:
            raise ValueError("BackupManifest payload fields do not match schema")
        entries = payload["entries"]
        if isinstance(entries, (str, bytes)) or not isinstance(entries, Iterable):
            raise TypeError("entries must be ordered")
        return cls(
            backup_id=payload["backup_id"],
            source_root=payload["source_root"],
            backup_root=payload["backup_root"],
            created_at=payload["created_at"],
            entries=tuple(BackupEntry.from_dict(entry) for entry in entries),
        )


class BackupManager:
    def create(
        self,
        source_root: Path,
        relative_paths: Iterable[Path],
        *,
        backup_root: Path | None = None,
    ) -> BackupManifest:
        root = self._root(source_root)
        relative = tuple(self._relative(path) for path in relative_paths)
        if len(set(relative)) != len(relative):
            raise ValueError("backup paths must be unique")
        destination = (backup_root or root / ".hanengine" / "backups" / str(uuid.uuid4())).resolve(strict=False)
        if destination == root or root in destination.parents:
            if destination == root:
                raise ValueError("backup root must be separate from source root")
        destination.mkdir(parents=True, exist_ok=False)
        entries: list[BackupEntry] = []
        try:
            for item in relative:
                target = self._child(root, item)
                if target.exists() and target.is_symlink():
                    raise ValueError(f"backup refuses symlink: {item}")
                if target.exists() and not target.is_file():
                    raise ValueError(f"backup target is not a regular file: {item}")
                if not target.exists():
                    entries.append(BackupEntry(item, None, None, False))
                    continue
                backup_file = destination / item
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup_file)
                entries.append(BackupEntry(item, _sha256(target), item, True))
            manifest = BackupManifest(
                backup_id=destination.name,
                source_root=str(root),
                backup_root=str(destination),
                created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                entries=tuple(entries),
            )
            (destination / "manifest.json").write_text(
                json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
                newline="\n",
            )
            return manifest
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def apply(
        self,
        source_root: Path,
        replacements: Mapping[Path, bytes],
        manifest: BackupManifest,
    ) -> None:
        root = self._root(source_root)
        if str(root) != manifest.source_root:
            raise ValueError("backup manifest source root does not match")
        entries = {entry.relative_path: entry for entry in manifest.entries}
        normalized: dict[str, bytes] = {}
        for path, data in replacements.items():
            relative = self._relative(path)
            if relative not in entries:
                raise OSError(f"replacement path is not covered by backup: {relative}")
            if not isinstance(data, bytes):
                raise TypeError("replacement data must be bytes")
            normalized[relative] = data
        staging = Path(tempfile.mkdtemp(prefix=".hanengine-stage-", dir=root))
        try:
            for relative, data in normalized.items():
                staged = staging / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(data)
            try:
                for relative in normalized:
                    target = self._child(root, relative)
                    if target.exists() and target.is_symlink():
                        raise OSError(f"replacement refuses symlink: {relative}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staging / relative, target)
            except BaseException:
                self.restore(root, manifest)
                raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def restore(self, source_root: Path, manifest: BackupManifest) -> None:
        root = self._root(source_root)
        if str(root) != manifest.source_root:
            raise ValueError("backup manifest source root does not match")
        for entry in manifest.entries:
            target = self._child(root, entry.relative_path)
            if not entry.existed_before:
                if target.exists() and target.is_file() and not target.is_symlink():
                    target.unlink()
                continue
            if entry.backup_relative_path is None:
                raise ValueError("existing backup entry has no backup file")
            backup_file = self._child(Path(manifest.backup_root), entry.backup_relative_path)
            if not backup_file.is_file() or _sha256(backup_file) != entry.sha256_before:
                raise ValueError(f"backup hash verification failed: {entry.relative_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".hanengine-restore")
            shutil.copy2(backup_file, temporary)
            os.replace(temporary, target)

    @staticmethod
    def _root(root: Path) -> Path:
        if not isinstance(root, Path):
            raise TypeError("source_root must be a Path")
        resolved = root.resolve(strict=True)
        if not resolved.is_dir() or resolved.is_symlink():
            raise ValueError("source_root must be a regular directory")
        return resolved

    @staticmethod
    def _relative(path: Path) -> str:
        if not isinstance(path, Path):
            raise TypeError("backup paths must be Paths")
        return normalize_relative_path(path.as_posix())

    @staticmethod
    def _child(root: Path, relative: str) -> Path:
        child = (root / relative).resolve(strict=False)
        try:
            child.relative_to(root)
        except ValueError as exc:
            raise ValueError("backup path escapes its root") from exc
        return child


__all__ = ["BackupEntry", "BackupManifest", "BackupManager"]
