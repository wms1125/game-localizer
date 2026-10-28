"""Discover installed games for the quick-localization starting flow.

Read-only metadata scan: Steam registry/install paths, libraryfolders.vdf and
appmanifest_*.acf files.  No game files are opened, modified, or cracked; the
result is a plain list the player can pick from, and HanEngine's normal
detection + HanGuard checks still apply to whichever game is chosen.
"""
from __future__ import annotations

import re
from pathlib import Path

_STEAM_PATH_RE = re.compile(r'"path"\s*"([^"]+)"')
_ACF_NAME_RE = re.compile(r'"name"\s*"((?:[^"\\]|\\.)*)"')
_ACF_INSTALLDIR_RE = re.compile(r'"installdir"\s*"((?:[^"\\]|\\.)*)"')
_ACF_APPID_RE = re.compile(r'"appid"\s*"(\d+)"')

_COMMON_STEAM_ROOTS = (
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"D:\Steam",
    "C:/Program Files (x86)/Steam",
)


def _unescape(value: str) -> str:
    return value.replace("\\\\", "\\").replace('\\"', '"')


def parse_library_folders(vdf_text: str) -> list[Path]:
    """Return every library path declared in a libraryfolders.vdf file."""
    paths: list[Path] = []
    for match in _STEAM_PATH_RE.finditer(vdf_text):
        raw = _unescape(match.group(1)).strip()
        if not raw:
            continue
        candidate = Path(raw)
        if candidate not in paths:
            paths.append(candidate)
    return paths


def parse_appmanifest(acf_text: str) -> dict[str, str] | None:
    """Extract appid/name/installdir from an appmanifest_*.acf file."""
    name = _ACF_NAME_RE.search(acf_text)
    install_dir = _ACF_INSTALLDIR_RE.search(acf_text)
    app_id = _ACF_APPID_RE.search(acf_text)
    if not name or not install_dir or not app_id:
        return None
    return {
        "app_id": app_id.group(1),
        "name": _unescape(name.group(1)),
        "installdir": _unescape(install_dir.group(1)),
    }


def discover_steam_games(steam_root: Path) -> list[dict[str, str]]:
    """Scan one Steam root (plus its declared libraries) for installed games."""
    results: list[dict[str, str]] = []
    seen_dirs: set[str] = set()
    libraries: list[Path] = []
    library_file = steam_root / "steamapps" / "libraryfolders.vdf"
    if library_file.is_file():
        try:
            libraries.extend(parse_library_folders(library_file.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass
    if steam_root not in libraries:
        libraries.insert(0, steam_root)
    for library in libraries:
        steamapps = library / "steamapps"
        if not steamapps.is_dir():
            continue
        for manifest_path in sorted(steamapps.glob("appmanifest_*.acf")):
            try:
                entry = parse_appmanifest(manifest_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if not entry:
                continue
            install_dir = steamapps / "common" / entry["installdir"]
            if not install_dir.is_dir():
                continue
            key = str(install_dir).casefold()
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            results.append({
                "source": "steam",
                "app_id": entry["app_id"],
                "name": entry["name"],
                "install_dir": str(install_dir),
            })
    return results


def _windows_registry_steam_paths() -> list[Path]:
    paths: list[Path] = []
    try:
        import winreg  # noqa: PLC0415 - Windows only
    except ImportError:
        return paths
    for hive, key_path in (
        ("HKCU", r"Software\Valve\Steam"),
    ):
        try:
            hive_enum = getattr(winreg, {"HKCU": "HKEY_CURRENT_USER"}.get(hive, "HKEY_CURRENT_USER"))
            with winreg.OpenKey(hive_enum, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "SteamPath")
                paths.append(Path(value))
        except OSError:
            continue
    return paths


def _default_steam_roots() -> list[Path]:
    roots = [Path(entry) for entry in _COMMON_STEAM_ROOTS]
    roots.extend([
        Path.home() / ".steam" / "steam",
        Path.home() / ".local" / "share" / "Steam",
    ])
    return roots


def discover_installed_games() -> list[dict[str, str]]:
    """Scan every reachable Steam root for installed games, sorted by name."""
    roots: list[Path] = []
    for root in [*_windows_registry_steam_paths(), *_default_steam_roots()]:
        if root.is_dir() and root not in roots:
            roots.append(root)
    games: list[dict[str, str]] = []
    seen_dirs: set[str] = set()
    for root in roots:
        for game in discover_steam_games(root):
            key = game["install_dir"].casefold()
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            games.append(game)
    games.sort(key=lambda game: game["name"].casefold())
    return games
