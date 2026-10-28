"""Discover installed games for the quick-localization starting flow.

Read-only metadata scan: Steam registry/install paths, libraryfolders.vdf and
appmanifest_*.acf files; Epic Games Launcher *.item manifests; GOG registry
entries; EA/Origin *.mfst manifests; Xbox app install folders.  No game files
are opened, modified, or cracked; the result is a plain list the player can
pick from, and HanEngine's normal detection + HanGuard checks still apply to
whichever game is chosen.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
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

# Exact-name blocklist for well-known non-game Steam entries (tools, engines,
# redistributables) that would never be a sensible localization target.
_STEAM_TOOL_NAMES = {
    "steamworks common redistributables",
    "steamworks .net",
    "steam client",
    "sharex",
    "blender",
    "godot engine",
    "unreal engine",
    "gamemaker",
    "gamemaker studio 2",
    "rpg maker mv",
    "rpg maker mz",
    "rpg maker vx ace",
    "rpg maker vx",
    "rpg maker xp",
    "rpg maker 2003",
    "rpg maker 2000",
    "wallpaper engine",
    "unity hub",
}


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
            if entry["name"].casefold() in _STEAM_TOOL_NAMES:
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
    """Scan every reachable source for installed games, sorted by name."""
    roots: list[Path] = []
    for root in [*_windows_registry_steam_paths(), *_default_steam_roots()]:
        if root.is_dir() and root not in roots:
            roots.append(root)
    games: list[dict[str, str]] = []
    seen_dirs: set[str] = set()
    for game in [
        *(game for root in roots for game in discover_steam_games(root)),
        *discover_epic_games(),
        *discover_gog_games(),
        *discover_ea_games(),
        *discover_xbox_games(),
    ]:
        key = game["install_dir"].casefold()
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        games.append(game)
    games.sort(key=lambda game: game["name"].casefold())
    return games


# ---------------------------------------------------------------------------
# Epic Games Launcher: ProgramData/Epic/EpicGamesLauncher/Data/Manifests/*.item
# ---------------------------------------------------------------------------

_EPIC_NOISE_NAMES = {"Epic Online Services", "Epic Games Launcher"}
_EPIC_NOISE_PATHS = (
    "epic games\\launcher",
    "epic games/launcher",
    "easyanticheat",
    "battleye",
)


def parse_epic_manifest(item_text: str) -> dict[str, str] | None:
    """Extract display name / install location from one Epic .item manifest."""

    try:
        data = json.loads(item_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("DisplayName")
    install_location = data.get("InstallLocation")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(install_location, str) or not install_location.strip():
        return None
    app_id = data.get("CatalogItemId") or data.get("AppName") or ""
    namespace = data.get("CatalogNamespace") or ""
    return {
        "app_id": f"{app_id}@{namespace}" if app_id and namespace else str(app_id),
        "name": name.strip(),
        "install_dir": str(Path(install_location.strip())),
    }


def discover_epic_games(program_data: Path | None = None) -> list[dict[str, str]]:
    """Scan Epic Games Launcher manifests for installed games."""

    base = program_data if program_data is not None else _program_data_root()
    if base is None:
        return []
    manifests = base / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if not manifests.is_dir():
        return []
    results: list[dict[str, str]] = []
    for manifest_path in sorted(manifests.glob("*.item")):
        try:
            entry = parse_epic_manifest(manifest_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if not entry:
            continue
        # namespace "ue" entries are Unreal Engine assets/plugins, not games.
        if entry["app_id"].endswith("@ue"):
            continue
        lowered = entry["install_dir"].casefold()
        if entry["name"] in _EPIC_NOISE_NAMES or any(token in lowered for token in _EPIC_NOISE_PATHS):
            continue
        if not Path(entry["install_dir"]).is_dir():
            continue
        entry["source"] = "epic"
        results.append(entry)
    return results


def _program_data_root() -> Path | None:
    value = os.environ.get("ProgramData") or os.environ.get("ALLUSERSPROFILE")
    if value:
        return Path(value)
    if os.name == "nt":
        # Some shells run with a stripped environment; the Windows default is
        # stable, and Epic/EA manifests always live under it.
        return Path("C:/ProgramData")
    return None


# ---------------------------------------------------------------------------
# GOG: HKLM\SOFTWARE\[WOW6432Node\]GOG.com\Games\<appid> with path/gameID/displayName
# ---------------------------------------------------------------------------


def _read_gog_registry() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    try:
        import winreg  # noqa: PLC0415 - Windows only
    except ImportError:
        return entries
    hive = winreg.HKEY_LOCAL_MACHINE
    for view in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
        try:
            with winreg.OpenKey(hive, view) as games_key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(games_key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(games_key, subkey_name) as subkey:
                            values = {}
                            for value_name in ("path", "gameID", "displayName"):
                                try:
                                    values[value_name] = str(winreg.QueryValueEx(subkey, value_name)[0])
                                except OSError:
                                    values[value_name] = ""
                    except OSError:
                        continue
                    if values.get("path") and values.get("displayName"):
                        entries.append({
                            "app_id": values.get("gameID", "") or subkey_name,
                            "name": values["displayName"],
                            "install_dir": str(Path(values["path"])),
                        })
        except OSError:
            continue
    return entries


def discover_gog_games(registry_entries: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """Scan GOG registry entries for installed games."""

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in registry_entries if registry_entries is not None else _read_gog_registry():
        install_dir = Path(entry["install_dir"])
        if not install_dir.is_dir():
            continue
        key = str(install_dir).casefold()
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "source": "gog",
            "app_id": entry["app_id"],
            "name": entry["name"],
            "install_dir": str(install_dir),
        })
    return results


# ---------------------------------------------------------------------------
# EA / Origin: ProgramData/{EA,Origin}/LocalContent/<slug>/<slug>.mfst with
# "?id=<id>&dipinstallpath=<url-encoded path>&..."
# ---------------------------------------------------------------------------


def parse_ea_manifest(mfst_text: str) -> dict[str, str] | None:
    """Extract id and install path from one .mfst manifest line."""

    try:
        params = urllib.parse.parse_qs(mfst_text.strip().lstrip("?"), keep_blank_values=True)
    except ValueError:
        return None
    app_id = (params.get("id") or [""])[0]
    install_raw = (params.get("dipinstallpath") or [""])[0]
    if not app_id or not install_raw:
        return None
    install_dir = urllib.parse.unquote(install_raw).split("&")[0]
    if not install_dir:
        return None
    return {
        "app_id": app_id,
        "name": Path(install_dir).name,
        "install_dir": str(Path(install_dir)),
    }


def discover_ea_games(program_data: Path | None = None) -> list[dict[str, str]]:
    """Scan EA app and Origin LocalContent manifests for installed games."""

    base = program_data if program_data is not None else _program_data_root()
    if base is None:
        return []
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for folder in (base / "EA" / "LocalContent", base / "Origin" / "LocalContent"):
        if not folder.is_dir():
            continue
        for game_folder in sorted(folder.iterdir()):
            if not game_folder.is_dir():
                continue
            for manifest_path in sorted(game_folder.glob("*.mfst")):
                try:
                    entry = parse_ea_manifest(manifest_path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                if not entry:
                    continue
                if not Path(entry["install_dir"]).is_dir():
                    continue
                key = entry["install_dir"].casefold()
                if key in seen:
                    continue
                seen.add(key)
                results.append({"source": "ea", **entry})
    return results


# ---------------------------------------------------------------------------
# Xbox app / Microsoft Store: <fixed drive>\XboxGames\<Game>\ with a GamingRoot
# marker file and a Content folder holding the actual game files.
# ---------------------------------------------------------------------------


def discover_xbox_games(drives: list[Path] | None = None) -> list[dict[str, str]]:
    """Scan fixed drives' XboxGames folders for installed Xbox app games."""

    roots = drives if drives is not None else _fixed_drive_roots()
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for drive in roots:
        xbox_games = drive / "XboxGames"
        if not xbox_games.is_dir():
            continue
        for game_folder in sorted(xbox_games.iterdir()):
            if not game_folder.is_dir() or not (game_folder / "GamingRoot").is_file():
                continue
            content = game_folder / "Content"
            install_dir = content if content.is_dir() else game_folder
            key = str(install_dir).casefold()
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "source": "xbox",
                "app_id": f"xbox-{game_folder.name.casefold().replace(' ', '-')}",
                "name": game_folder.name,
                "install_dir": str(install_dir),
            })
    return results


def _fixed_drive_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        import ctypes  # noqa: PLC0415 - Windows only

        buffer = ctypes.create_unicode_buffer(512)
        if not ctypes.windll.kernel32.GetLogicalDriveStringsW(511, buffer):
            return roots
        for raw in buffer.value.split("\x00"):
            if not raw:
                continue
            if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(raw)) != 3:  # DRIVE_FIXED
                continue
            roots.append(Path(raw))
    except (ImportError, OSError, AttributeError):
        return []
    return roots
