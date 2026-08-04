from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat


DEFAULT_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "binaries",
        "deriveddatacache",
        "intermediate",
        "library",
        "localized-output",
        "obj",
        "temp",
    }
)


class ProjectScanError(ValueError):
    pass


def _normalize(relative_path: Path | str) -> str:
    return Path(relative_path).as_posix().strip("/").casefold()


def _metadata_for(path: Path) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise ProjectScanError(f"无法检查项目路径: {path}: {exc}") from exc


def _has_reparse_attribute(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _reject_reparse_path_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts:
        if part == path.anchor:
            continue
        current /= part
        metadata = _metadata_for(current)
        if stat.S_ISLNK(metadata.st_mode) or _has_reparse_attribute(metadata):
            raise ProjectScanError(f"项目路径不能包含符号链接或重解析点: {current}")


def _is_reparse_point(entry: os.DirEntry[str]) -> bool:
    try:
        metadata = entry.stat(follow_symlinks=False)
        return entry.is_symlink() or _has_reparse_attribute(metadata)
    except OSError as exc:
        raise ProjectScanError(f"无法检查项目路径: {entry.path}: {exc}") from exc


def _validate_queued_directory(path: Path, expected_identity: tuple[int, int]) -> None:
    _reject_reparse_path_components(path)
    metadata = _metadata_for(path)
    if not stat.S_ISDIR(metadata.st_mode) or _identity(metadata) != expected_identity:
        raise ProjectScanError(f"项目目录在扫描过程中发生变化: {path}")


@dataclass(frozen=True)
class ProjectSnapshot:
    root: Path
    files: frozenset[str]
    directories: frozenset[str]
    ignored_directories: frozenset[str]

    def has_file(self, relative_path: str) -> bool:
        return _normalize(relative_path) in self.files

    def has_dir(self, relative_path: str) -> bool:
        return _normalize(relative_path) in self.directories

    def files_named(self, name: str) -> tuple[str, ...]:
        expected = name.casefold()
        return tuple(path for path in sorted(self.files) if Path(path).name.casefold() == expected)

    def files_with_suffix(self, suffix: str) -> tuple[str, ...]:
        expected = suffix.casefold()
        return tuple(path for path in sorted(self.files) if path.endswith(expected))

    def root_files_with_suffix(self, suffix: str) -> tuple[str, ...]:
        return tuple(path for path in self.files_with_suffix(suffix) if "/" not in path)

    def root_dirs_with_suffix(self, suffix: str) -> tuple[str, ...]:
        expected = suffix.casefold()
        return tuple(
            path
            for path in sorted(self.directories)
            if "/" not in path and path.endswith(expected)
        )


def scan_project(root: str | Path) -> ProjectSnapshot:
    try:
        project_root = Path(root).absolute()
    except (OSError, RuntimeError) as exc:
        raise ProjectScanError(f"无法检查项目路径: {root}: {exc}") from exc
    _reject_reparse_path_components(project_root)
    root_metadata = _metadata_for(project_root)
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise ProjectScanError(f"项目目录不存在或不是目录: {project_root}")

    files: set[str] = set()
    directories: set[str] = set()
    ignored: set[str] = set()
    pending = [(project_root, _identity(root_metadata))]

    while pending:
        current, expected_identity = pending.pop()
        _validate_queued_directory(current, expected_identity)
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise ProjectScanError(f"无法扫描项目目录: {current}: {exc}") from exc
        _validate_queued_directory(current, expected_identity)
        for entry in entries:
            try:
                path = Path(entry.path)
                relative = _normalize(path.relative_to(project_root))
            except (OSError, ValueError) as exc:
                raise ProjectScanError(f"无法检查项目路径: {entry.path}: {exc}") from exc
            if _is_reparse_point(entry):
                ignored.add(relative)
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    directories.add(relative)
                    if entry.name.casefold() in DEFAULT_IGNORED_DIRS:
                        ignored.add(relative)
                    else:
                        metadata = _metadata_for(path)
                        if not stat.S_ISDIR(metadata.st_mode):
                            raise ProjectScanError(f"项目目录在扫描过程中发生变化: {path}")
                        pending.append((path, _identity(metadata)))
                elif entry.is_file(follow_symlinks=False):
                    files.add(relative)
            except OSError as exc:
                raise ProjectScanError(f"无法检查项目路径: {path}: {exc}") from exc

    return ProjectSnapshot(
        root=project_root,
        files=frozenset(files),
        directories=frozenset(directories),
        ignored_directories=frozenset(ignored),
    )
