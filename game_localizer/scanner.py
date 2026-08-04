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


def _is_reparse_point(entry: os.DirEntry[str]) -> bool:
    try:
        metadata = entry.stat(follow_symlinks=False)
    except OSError as exc:
        raise ProjectScanError(f"无法检查项目路径: {entry.path}: {exc}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return entry.is_symlink() or bool(reparse_flag and attributes & reparse_flag)


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
    project_root = Path(root).resolve()
    if not project_root.is_dir():
        raise ProjectScanError(f"项目目录不存在或不是目录: {project_root}")

    files: set[str] = set()
    directories: set[str] = set()
    ignored: set[str] = set()
    pending = [project_root]

    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise ProjectScanError(f"无法扫描项目目录: {current}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = _normalize(path.relative_to(project_root))
            if _is_reparse_point(entry):
                ignored.add(relative)
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    directories.add(relative)
                    if entry.name.casefold() in DEFAULT_IGNORED_DIRS:
                        ignored.add(relative)
                    else:
                        pending.append(path)
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
