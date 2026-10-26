from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .visual_style import VisualCheck, VisualHardGateReport


_FONT_SUFFIXES = frozenset({".otf", ".ttf"})
_MV_FONT_FACE_RE = re.compile(
    r"(@font-face\s*\{(?=[^{}]*\bfont-family\s*:\s*['\"]?GameFont['\"]?\s*;)[^{}]*\})",
    re.IGNORECASE,
)
_FONT_SOURCE_RE = re.compile(r"(\bsrc\s*:\s*)url\([^;]+\)(\s*;)", re.IGNORECASE)


class RpgMakerStyleError(ValueError):
    pass


@dataclass(frozen=True)
class RpgMakerStyleBuildResult:
    relative_paths: tuple[str, ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _project_base(root: Path) -> Path:
    return root / "www" if (root / "www" / "data").is_dir() else root


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _require_font(font_paths: tuple[Path, ...]) -> Path:
    if len(font_paths) != 1:
        raise RpgMakerStyleError("RPG Maker style currently requires exactly one complete font")
    source = font_paths[0].expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.casefold() not in _FONT_SUFFIXES:
        raise RpgMakerStyleError("RPG Maker font must be an existing .ttf or .otf file")
    return source


def _package_font(root: Path, base: Path, source: Path) -> tuple[Path, str]:
    fonts = base / "fonts"
    if not fonts.is_dir() or fonts.is_symlink():
        raise RpgMakerStyleError("RPG Maker candidate has no safe fonts directory")
    destination = fonts / source.name
    if destination.exists():
        raise RpgMakerStyleError("RPG Maker candidate already contains the configured font name")
    shutil.copy2(source, destination)
    return destination, _relative(destination, root)


def _apply_mv_style(root: Path, base: Path, source: Path) -> tuple[str, ...]:
    stylesheet = base / "fonts" / "gamefont.css"
    if not stylesheet.is_file() or stylesheet.is_symlink():
        raise RpgMakerStyleError("RPG Maker MV candidate has no safe fonts/gamefont.css")
    text = stylesheet.read_text(encoding="utf-8-sig")
    face = _MV_FONT_FACE_RE.search(text)
    if face is None:
        raise RpgMakerStyleError("RPG Maker MV GameFont declaration was not found")
    replacement, count = _FONT_SOURCE_RE.subn(
        rf'\1url("{source.name}")\2', face.group(1), count=1
    )
    if count != 1:
        raise RpgMakerStyleError("RPG Maker MV GameFont source was not found")
    stylesheet.write_text(
        text[: face.start(1)] + replacement + text[face.end(1) :],
        encoding="utf-8",
        newline="\n",
    )
    destination, font_relative = _package_font(root, base, source)
    return tuple(sorted((_relative(stylesheet, root), font_relative)))


def _apply_mz_style(root: Path, base: Path, source: Path) -> tuple[str, ...]:
    system_path = base / "data" / "System.json"
    if not system_path.is_file() or system_path.is_symlink():
        raise RpgMakerStyleError("RPG Maker MZ candidate has no safe data/System.json")
    try:
        document = json.loads(system_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RpgMakerStyleError("RPG Maker MZ System.json is invalid") from exc
    advanced = document.get("advanced") if isinstance(document, dict) else None
    if not isinstance(advanced, dict) or not isinstance(advanced.get("mainFontFilename"), str):
        raise RpgMakerStyleError("RPG Maker MZ main font setting was not found")
    advanced["mainFontFilename"] = source.name
    system_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    destination, font_relative = _package_font(root, base, source)
    return tuple(sorted((_relative(system_path, root), font_relative)))


def apply_rpg_maker_font_style(
    candidate_root: Path,
    engine_id: str,
    font_paths: tuple[Path, ...],
) -> RpgMakerStyleBuildResult:
    root = candidate_root.resolve(strict=True)
    source = _require_font(font_paths)
    base = _project_base(root)
    if engine_id == "rpg_maker_mv":
        paths = _apply_mv_style(root, base, source)
    elif engine_id == "rpg_maker_mz":
        paths = _apply_mz_style(root, base, source)
    else:
        raise RpgMakerStyleError("unsupported RPG Maker engine id")
    return RpgMakerStyleBuildResult(paths)


def _matching_hashes(source_base: Path, candidate_base: Path, patterns: tuple[str, ...]) -> bool:
    source_files = {
        path.relative_to(source_base).as_posix(): _sha256_file(path)
        for pattern in patterns
        for path in source_base.glob(pattern)
        if path.is_file() and not path.is_symlink()
    }
    return bool(source_files) and all(
        (candidate_base / Path(*relative.split("/"))).is_file()
        and _sha256_file(candidate_base / Path(*relative.split("/"))) == digest
        for relative, digest in source_files.items()
    )


def run_rpg_maker_style_hard_gate(
    source_root: Path,
    candidate_root: Path,
    engine_id: str,
    font_paths: tuple[Path, ...],
) -> VisualHardGateReport:
    source = source_root.resolve(strict=True)
    candidate = candidate_root.resolve(strict=True)
    source_base = _project_base(source)
    candidate_base = _project_base(candidate)
    configured_font = _require_font(font_paths)
    candidate_font = candidate_base / "fonts" / configured_font.name
    checks = [
        VisualCheck(
            "rpg_maker_font_asset_packaged",
            candidate_font.is_file() and _sha256_file(candidate_font) == _sha256_file(configured_font),
            "Configured RPG Maker font is packaged with a matching hash",
        ),
        VisualCheck(
            "rpg_maker_typography_scripts_preserved",
            _matching_hashes(source_base, candidate_base, ("js/*.js", "js/plugins/*.js")),
            "RPG Maker typography and plugin scripts are unchanged",
        ),
        VisualCheck(
            "rpg_maker_window_skin_preserved",
            _matching_hashes(source_base, candidate_base, ("img/system/Window.png",)),
            "RPG Maker window skin is unchanged",
        ),
    ]
    if engine_id == "rpg_maker_mv":
        stylesheet = candidate_base / "fonts" / "gamefont.css"
        text = stylesheet.read_text(encoding="utf-8-sig") if stylesheet.is_file() else ""
        face = _MV_FONT_FACE_RE.search(text)
        points_to_font = face is not None and f'url("{configured_font.name}")' in face.group(1)
    elif engine_id == "rpg_maker_mz":
        system_path = candidate_base / "data" / "System.json"
        try:
            system = json.loads(system_path.read_text(encoding="utf-8-sig"))
            points_to_font = system["advanced"]["mainFontFilename"] == configured_font.name
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            points_to_font = False
    else:
        points_to_font = False
    checks.append(
        VisualCheck(
            "rpg_maker_font_reference",
            points_to_font,
            "RPG Maker native font configuration references the packaged font",
        )
    )
    return VisualHardGateReport(tuple(checks))


__all__ = [
    "RpgMakerStyleBuildResult",
    "RpgMakerStyleError",
    "apply_rpg_maker_font_style",
    "run_rpg_maker_style_hard_gate",
]
