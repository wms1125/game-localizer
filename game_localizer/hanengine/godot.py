from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .visual_style import VisualCheck, VisualHardGateReport


GODOT_STYLE_SCRIPT = "hanengine/locale_style.gd"
GODOT_FONT_DIRECTORY = "hanengine/fonts"
_AUTOLOAD_NAME = "HanEngineLocaleStyle"
_FONT_SUFFIXES = frozenset({".otf", ".ttf"})
_UI_RESOURCE_SUFFIXES = frozenset({".theme", ".tres", ".tscn"})


class GodotStyleError(ValueError):
    pass


@dataclass(frozen=True)
class GodotStyleBuildResult:
    relative_paths: tuple[str, ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _language_identifier(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Godot language must not be empty")
    return value.replace("-", "_")


def _register_autoload(project_text: str) -> str:
    assignment = f'{_AUTOLOAD_NAME}="*res://{GODOT_STYLE_SCRIPT}"'
    existing = re.search(rf"(?m)^{re.escape(_AUTOLOAD_NAME)}=.*$", project_text)
    if existing is not None:
        if existing.group(0) != assignment:
            raise GodotStyleError(f"Godot autoload name {_AUTOLOAD_NAME} is already in use")
        return project_text
    section = re.search(r"(?m)^\[autoload\]\s*$", project_text)
    if section is None:
        return project_text.rstrip() + f"\n\n[autoload]\n\n{assignment}\n"
    insertion = section.end()
    return project_text[:insertion] + f"\n\n{assignment}" + project_text[insertion:]


def apply_godot_font_style(
    candidate_root: Path,
    font_paths: tuple[Path, ...],
    *,
    target_language: str,
    source_language: str,
) -> GodotStyleBuildResult:
    """Package one complete font while leaving source typography resources unchanged."""

    root = candidate_root.resolve(strict=True)
    if len(font_paths) != 1:
        raise GodotStyleError("Godot style currently requires exactly one complete font")
    source_font = font_paths[0].expanduser().resolve(strict=True)
    if not source_font.is_file() or source_font.suffix.casefold() not in _FONT_SUFFIXES:
        raise GodotStyleError("Godot font must be an existing .ttf or .otf file")
    project_path = root / "project.godot"
    if not project_path.is_file() or project_path.is_symlink():
        raise GodotStyleError("Godot style requires a plaintext project.godot")

    relative_font = f"{GODOT_FONT_DIRECTORY}/{source_font.name}"
    destination_font = root / Path(*relative_font.split("/"))
    script_path = root / Path(*GODOT_STYLE_SCRIPT.split("/"))
    if destination_font.exists() or script_path.exists():
        raise GodotStyleError("Godot candidate already contains HanEngine style assets")
    destination_font.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_font, destination_font)

    target = _language_identifier(target_language)
    source = _language_identifier(source_language)
    font_resource = "res://" + relative_font
    script = (
        "extends Node\n\n"
        f"const CJK_FONT_PATH := {json.dumps(font_resource)}\n\n\n"
        "func _enter_tree() -> void:\n"
        "\tvar requested_language := OS.get_environment(\"HANENGINE_GAME_LANGUAGE\").strip_edges()\n"
        f"\tTranslationServer.set_locale({json.dumps(source)} if requested_language == \"source\" else {json.dumps(target)})\n\n"
        "\tif Engine.is_editor_hint():\n"
        "\t\treturn\n\n"
        "\tvar project_theme: Theme\n"
        "\tvar theme_setting: Variant = ProjectSettings.get_setting(\"gui/theme/custom\")\n"
        "\tif theme_setting is Theme:\n"
        "\t\tproject_theme = theme_setting\n"
        "\telif theme_setting is String and ResourceLoader.exists(theme_setting):\n"
        "\t\tproject_theme = load(theme_setting) as Theme\n\n"
        "\tvar cjk_font := load(CJK_FONT_PATH) as Font\n"
        "\tif project_theme and cjk_font:\n"
        "\t\tproject_theme.default_font = cjk_font\n"
    )
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8", newline="\n")
    project_text = project_path.read_text(encoding="utf-8-sig")
    project_path.write_text(_register_autoload(project_text), encoding="utf-8", newline="\n")
    return GodotStyleBuildResult(
        tuple(sorted(("project.godot", GODOT_STYLE_SCRIPT, relative_font)))
    )


def run_godot_style_hard_gate(
    source_root: Path,
    candidate_root: Path,
    font_paths: tuple[Path, ...],
) -> VisualHardGateReport:
    source = source_root.resolve(strict=True)
    candidate = candidate_root.resolve(strict=True)
    checks: list[VisualCheck] = []

    source_ui = {
        path.relative_to(source).as_posix(): _sha256_file(path)
        for path in source.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.casefold() in _UI_RESOURCE_SUFFIXES
        and ".godot" not in path.relative_to(source).parts
    }
    changed_ui = sorted(
        relative
        for relative, digest in source_ui.items()
        if not (candidate / Path(*relative.split("/"))).is_file()
        or _sha256_file(candidate / Path(*relative.split("/"))) != digest
    )
    checks.append(
        VisualCheck(
            "godot_source_typography_preserved",
            not changed_ui,
            "Godot source theme and scene typography resources are unchanged"
            if not changed_ui
            else "Godot source typography resources changed",
            details={"changed_paths": changed_ui},
        )
    )

    script_path = candidate / Path(*GODOT_STYLE_SCRIPT.split("/"))
    script_text = script_path.read_text(encoding="utf-8") if script_path.is_file() else ""
    has_font_override = "project_theme.default_font = cjk_font" in script_text
    checks.append(
        VisualCheck(
            "godot_cjk_font_override",
            has_font_override,
            "Godot candidate installs the configured CJK font"
            if has_font_override
            else "Godot candidate has no CJK font override",
        )
    )
    forbidden_groups = {
        "godot_font_size_preserved": ("default_font_size", "font_size"),
        "godot_text_colors_preserved": ("font_color", "font_outline_color"),
        "godot_outline_preserved": ("outline_size",),
    }
    for code, markers in forbidden_groups.items():
        found = [marker for marker in markers if marker in script_text]
        checks.append(
            VisualCheck(
                code,
                not found,
                "Godot candidate preserves source typography styling"
                if not found
                else "Godot candidate overrides source typography styling",
                details={"override_markers": found},
            )
        )

    project_path = candidate / "project.godot"
    project_text = project_path.read_text(encoding="utf-8-sig") if project_path.is_file() else ""
    autoload = f'{_AUTOLOAD_NAME}="*res://{GODOT_STYLE_SCRIPT}"'
    checks.append(
        VisualCheck(
            "godot_style_autoload_registered",
            autoload in project_text,
            "Godot style autoload is registered"
            if autoload in project_text
            else "Godot style autoload is missing",
        )
    )

    packaged_fonts = []
    for font_path in font_paths:
        resolved = font_path.expanduser().resolve(strict=True)
        destination = candidate / GODOT_FONT_DIRECTORY / resolved.name
        packaged_fonts.append(
            destination.is_file() and _sha256_file(destination) == _sha256_file(resolved)
        )
    checks.append(
        VisualCheck(
            "godot_font_assets_packaged",
            bool(packaged_fonts) and all(packaged_fonts),
            "Configured Godot font assets are packaged with matching hashes"
            if packaged_fonts and all(packaged_fonts)
            else "Configured Godot font assets are missing or changed",
            details={"font_count": len(packaged_fonts)},
        )
    )
    return VisualHardGateReport(tuple(checks))


__all__ = [
    "GODOT_FONT_DIRECTORY",
    "GODOT_STYLE_SCRIPT",
    "GodotStyleBuildResult",
    "GodotStyleError",
    "apply_godot_font_style",
    "run_godot_style_hard_gate",
]
