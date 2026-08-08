from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .backup import BackupManager, BackupManifest
from .routing import RouteOperation, RoutePhase, RoutePlan
from .segments import normalize_relative_path


class UnsafePackageError(ValueError):
    pass


@dataclass(frozen=True)
class PackageBuildResult:
    output_path: Path
    sha256: str
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class PackageApplyResult:
    package: PackageBuildResult
    backup: BackupManifest


class ZipPackageModifier:
    """Patch ordinary, unencrypted ZIP packages into a separate output file."""

    def build(
        self,
        source_archive: Path,
        replacements: Mapping[Path, bytes],
        output_archive: Path,
    ) -> PackageBuildResult:
        source = self._archive(source_archive)
        output = output_archive.resolve(strict=False)
        if output == source:
            raise ValueError("output archive must be separate from source archive")
        normalized = self._replacements(replacements)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".hanengine-package-",
            suffix=".zip",
            dir=output.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        try:
            with zipfile.ZipFile(source, "r") as incoming:
                names: set[str] = set()
                infos: list[zipfile.ZipInfo] = []
                for info in incoming.infolist():
                    if info.flag_bits & 0x1:
                        raise UnsafePackageError("encrypted ZIP entries are not supported")
                    if info.filename.endswith("/"):
                        name = normalize_relative_path(info.filename.rstrip("/"))
                    else:
                        name = normalize_relative_path(info.filename)
                    if name in names:
                        raise UnsafePackageError(f"duplicate ZIP path: {name}")
                    names.add(name)
                    infos.append(info)
                with zipfile.ZipFile(temporary, "w") as outgoing:
                    for info in infos:
                        name = normalize_relative_path(info.filename.rstrip("/")) if info.filename.endswith("/") else normalize_relative_path(info.filename)
                        cloned = copy.copy(info)
                        if name in normalized:
                            if info.filename.endswith("/"):
                                raise UnsafePackageError(f"cannot replace a ZIP directory: {name}")
                            outgoing.writestr(cloned, normalized[name])
                        else:
                            outgoing.writestr(cloned, incoming.read(info))
                    for name, data in normalized.items():
                        if name not in names:
                            outgoing.writestr(name, data)
            os.replace(temporary, output)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        content = output.read_bytes()
        return PackageBuildResult(output, hashlib.sha256(content).hexdigest(), tuple(sorted(normalized)))

    def apply_to_project(
        self,
        source_archive: Path,
        replacements: Mapping[Path, bytes],
        *,
        route: RoutePlan,
        backup_root: Path,
    ) -> PackageApplyResult:
        if not isinstance(route, RoutePlan):
            raise TypeError("route must be a RoutePlan")
        if route.phase is not RoutePhase.FINAL:
            raise PermissionError("package installation requires a final route")
        if RouteOperation.INSTALL_PATCH not in route.allowed_operations:
            raise PermissionError("route does not authorize package installation")
        source = self._archive(source_archive)
        root = source.parent.resolve(strict=True)
        relative = Path(source.name)
        manager = BackupManager()
        backup = manager.create(root, (relative,), backup_root=backup_root)
        with tempfile.NamedTemporaryFile(
            prefix=".hanengine-package-",
            suffix=source.suffix,
            dir=source.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        try:
            package = self.build(source, replacements, temporary)
            os.replace(temporary, source)
            return PackageApplyResult(
                PackageBuildResult(source, hashlib.sha256(source.read_bytes()).hexdigest(), package.changed_paths),
                backup,
            )
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            manager.restore(root, backup)
            raise

    @staticmethod
    def _archive(path: Path) -> Path:
        if not isinstance(path, Path):
            raise TypeError("source_archive must be a Path")
        archive = path.resolve(strict=True)
        if archive.suffix.casefold() != ".zip":
            raise UnsafePackageError("only unencrypted ZIP packages are supported")
        if not archive.is_file() or archive.is_symlink():
            raise UnsafePackageError("source archive must be a regular file")
        return archive

    @staticmethod
    def _replacements(replacements: Mapping[Path, bytes]) -> dict[str, bytes]:
        if not isinstance(replacements, Mapping):
            raise TypeError("replacements must be a mapping")
        normalized: dict[str, bytes] = {}
        for path, data in replacements.items():
            if not isinstance(data, bytes):
                raise TypeError("replacement data must be bytes")
            try:
                name = normalize_relative_path(path.as_posix() if isinstance(path, Path) else path)
            except (TypeError, ValueError) as exc:
                raise UnsafePackageError("replacement path is not a safe relative path") from exc
            if name in normalized:
                raise UnsafePackageError(f"duplicate replacement path: {name}")
            normalized[name] = data
        return normalized


__all__ = ["PackageApplyResult", "PackageBuildResult", "UnsafePackageError", "ZipPackageModifier"]
