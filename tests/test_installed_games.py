from __future__ import annotations

import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from game_localizer.hanengine.installed_games import (
    discover_ea_games,
    discover_epic_games,
    discover_gog_games,
    discover_installed_games,
    discover_steam_games,
    discover_xbox_games,
    parse_ea_manifest,
    parse_appmanifest,
    parse_epic_manifest,
    parse_library_folders,
)

LIBRARY_FOLDERS_VDF = r"""
"libraryfolders"
{
	"0"
	{
		"path"		"C:\Program Files (x86)\Steam"
	}
	"1"
	{
		"path"		"D:\SteamLibrary"
	}
	"2"
	{
		"path"		"E:\\Games\\Steam"
	}
}
"""

APPMANIFEST_ACF = r"""
"AppState"
{
	"appid"		"1284210"
	"Universe"		"1"
	"name"		"Grounded"
	"StateFlags"		"4"
	"installdir"		"Grounded"
	"LastUpdated"		"1660000000"
}
"""

APPMANIFEST_ESCAPED = r"""
"AppState"
{
	"appid"		"413150"
	"name"		"Stardew \"Valley\" Edition"
	"installdir"		"Stardew Valley"
}
"""


class LibraryFoldersTests(unittest.TestCase):
    def test_parses_all_declared_library_paths_and_unescapes(self):
        paths = parse_library_folders(LIBRARY_FOLDERS_VDF)
        self.assertEqual(
            [str(path) for path in paths],
            [
                "C:\\Program Files (x86)\\Steam",
                "D:\\SteamLibrary",
                "E:\\Games\\Steam",
            ],
        )


class AppManifestTests(unittest.TestCase):
    def test_extracts_appid_name_and_installdir(self):
        entry = parse_appmanifest(APPMANIFEST_ACF)
        assert entry is not None
        self.assertEqual(entry["app_id"], "1284210")
        self.assertEqual(entry["name"], "Grounded")
        self.assertEqual(entry["installdir"], "Grounded")

    def test_unescapes_quoted_names(self):
        entry = parse_appmanifest(APPMANIFEST_ESCAPED)
        assert entry is not None
        self.assertEqual(entry["name"], 'Stardew "Valley" Edition')

    def test_returns_none_for_garbled_manifest(self):
        self.assertIsNone(parse_appmanifest('"AppState" { "Universe" "1" }'))


class DiscoverSteamGamesTests(unittest.TestCase):
    def test_discovers_games_across_libraries_and_dedupes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main_steamapps = root / "steamapps"
            main_steamapps.mkdir(parents=True)
            (main_steamapps / "libraryfolders.vdf").write_text(
                f'"libraryfolders"\n{{\n\t"1"\n\t{{\n\t\t"path"\t\t"{root / "library2"}"\n\t}}\n}}',
                encoding="utf-8",
            )
            (main_steamapps / "appmanifest_1.acf").write_text(APPMANIFEST_ACF, encoding="utf-8")
            game_dir = main_steamapps / "common" / "Grounded"
            game_dir.mkdir(parents=True)

            library2 = root / "library2"
            library2_steamapps = library2 / "steamapps"
            library2_steamapps.mkdir(parents=True)
            (library2_steamapps / "appmanifest_2.acf").write_text(APPMANIFEST_ESCAPED, encoding="utf-8")
            (library2_steamapps / "common" / "Stardew Valley").mkdir(parents=True)
            # A manifest whose install dir is missing must be skipped silently.
            (library2_steamapps / "appmanifest_3.acf").write_text(
                '"AppState"\n{\n\t"appid"\t\t"9"\n\t"name"\t\t"Ghost"\n\t"installdir"\t\t"Ghost"\n}',
                encoding="utf-8",
            )

            games = discover_steam_games(root)
            self.assertEqual([game["name"] for game in games], ["Grounded", 'Stardew "Valley" Edition'])
            self.assertTrue(all(game["source"] == "steam" for game in games))
            self.assertTrue(games[0]["install_dir"].endswith("Grounded"))


class DiscoverInstalledGamesTests(unittest.TestCase):
    def test_scans_registry_and_default_roots_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Steam"
            steamapps = root / "steamapps"
            steamapps.mkdir(parents=True)
            (steamapps / "appmanifest_1.acf").write_text(APPMANIFEST_ACF, encoding="utf-8")
            (steamapps / "common" / "Grounded").mkdir(parents=True)

            import game_localizer.hanengine.installed_games as module

            original_registry = module._windows_registry_steam_paths
            original_roots = module._default_steam_roots
            original_epic = module.discover_epic_games
            original_gog = module.discover_gog_games
            original_ea = module.discover_ea_games
            original_xbox = module.discover_xbox_games
            module._windows_registry_steam_paths = lambda: [root]
            module._default_steam_roots = lambda: [root, root]
            module.discover_epic_games = lambda **_: []
            module.discover_gog_games = lambda **_: []
            module.discover_ea_games = lambda **_: []
            module.discover_xbox_games = lambda **_: []
            try:
                games = module.discover_installed_games()
            finally:
                module._windows_registry_steam_paths = original_registry
                module._default_steam_roots = original_roots
                module.discover_epic_games = original_epic
                module.discover_gog_games = original_gog
                module.discover_ea_games = original_ea
                module.discover_xbox_games = original_xbox
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0]["name"], "Grounded")

    def test_aggregates_platforms_and_dedupes_by_install_dir(self):
        import game_localizer.hanengine.installed_games as module

        with tempfile.TemporaryDirectory() as directory:
            fake_root = Path(directory) / "SteamRoot"
            fake_root.mkdir()
            original = {name: getattr(module, name) for name in (
                "_windows_registry_steam_paths", "_default_steam_roots",
                "discover_steam_games", "discover_epic_games", "discover_gog_games",
                "discover_ea_games", "discover_xbox_games",
            )}
            module._windows_registry_steam_paths = lambda: []
            module._default_steam_roots = lambda: [fake_root]
            module.discover_steam_games = lambda root: [
                {"source": "steam", "app_id": "1", "name": "Zed", "install_dir": "C:/Games/Zed"},
            ]
            module.discover_epic_games = lambda **_: [
                {"source": "epic", "app_id": "abc", "name": "Astra", "install_dir": "C:/Epic/Astra"},
                {"source": "epic", "app_id": "dup", "name": "Dup", "install_dir": "C:/Games/Zed"},
            ]
            module.discover_gog_games = lambda **_: [
                {"source": "gog", "app_id": "12", "name": "Oldschool", "install_dir": "C:/GOG/Oldschool"},
            ]
            module.discover_ea_games = lambda **_: []
            module.discover_xbox_games = lambda **_: [
                {"source": "xbox", "app_id": "xbox-forza", "name": "Forza", "install_dir": "C:/XboxGames/Forza/Content"},
            ]
            try:
                games = module.discover_installed_games()
            finally:
                for name, value in original.items():
                    setattr(module, name, value)
        self.assertEqual([game["name"] for game in games], ["Astra", "Forza", "Oldschool", "Zed"])
        self.assertEqual({game["source"] for game in games}, {"steam", "epic", "gog", "xbox"})

    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Steam"
            steamapps = root / "steamapps"
            steamapps.mkdir(parents=True)
            (steamapps / "appmanifest_1.acf").write_text(APPMANIFEST_ACF, encoding="utf-8")
            (steamapps / "common" / "Grounded").mkdir(parents=True)
            games = discover_steam_games(root)
            json.dumps(games)


class EpicGamesTests(unittest.TestCase):
    EOS_ITEM = json.dumps({
        "DisplayName": "Epic Online Services",
        "AppName": "EOS",
        "InstallLocation": "C:/Program Files (x86)/Epic Games/Epic Online Services",
    })
    LAUNCHER_ITEM = json.dumps({
        "DisplayName": "Some Tool",
        "InstallLocation": "C:/Program Files (x86)/EasyAntiCheat/Tool",
    })

    def _make_manifests(self, root: Path) -> Path:
        install_dir = root / "Epic Games" / "Astra"
        install_dir.mkdir(parents=True)
        manifests = root / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        manifests.mkdir(parents=True)
        game_item = json.dumps({
            "FormatVersion": 11,
            "DisplayName": "Astra Game",
            "AppName": "AstraGame",
            "CatalogItemId": "5f6c2b1e",
            "InstallLocation": install_dir.as_posix(),
        })
        (manifests / "a.item").write_text(game_item, encoding="utf-8")
        (manifests / "b.item").write_text(self.EOS_ITEM, encoding="utf-8")
        (manifests / "c.item").write_text(self.LAUNCHER_ITEM, encoding="utf-8")
        (manifests / "broken.item").write_text("{not json", encoding="utf-8")
        return manifests

    def test_parses_manifest_fields(self):
        game_item = json.dumps({
            "DisplayName": "Astra Game",
            "AppName": "AstraGame",
            "CatalogItemId": "5f6c2b1e",
            "InstallLocation": "C:/Program Files/Epic Games/Astra",
        })
        entry = parse_epic_manifest(game_item)
        assert entry is not None
        self.assertEqual(entry["name"], "Astra Game")
        self.assertEqual(entry["app_id"], "5f6c2b1e")
        self.assertTrue(entry["install_dir"].endswith("Astra"))
        self.assertIsNone(parse_epic_manifest("{not json"))
        self.assertIsNone(parse_epic_manifest(json.dumps({"DisplayName": "No Location"})))

    def test_discovers_games_and_skips_platform_noise(self):
        with tempfile.TemporaryDirectory() as directory:
            self._make_manifests(Path(directory))
            games = discover_epic_games(program_data=Path(directory))
            self.assertEqual([game["name"] for game in games], ["Astra Game"])
            self.assertEqual(games[0]["source"], "epic")

    def test_skips_missing_install_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            manifests = Path(directory) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
            manifests.mkdir(parents=True)
            (manifests / "gone.item").write_text(
                json.dumps({"DisplayName": "Ghost Game", "InstallLocation": "Q:/Nowhere/Game"}),
                encoding="utf-8",
            )
            self.assertEqual(discover_epic_games(program_data=Path(directory)), [])


class GogGamesTests(unittest.TestCase):
    def test_discovers_registry_entries_with_existing_paths_only(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "Witcher"
            real.mkdir()
            entries = [
                {"app_id": "1207658924", "name": "The Witcher 3", "install_dir": str(real)},
                {"app_id": "9", "name": "Ghost", "install_dir": "Q:/Nowhere/Ghost"},
                {"app_id": "10", "name": "Dup", "install_dir": str(real)},
            ]
            games = discover_gog_games(registry_entries=entries)
            self.assertEqual([game["name"] for game in games], ["The Witcher 3"])
            self.assertEqual(games[0]["source"], "gog")


class EaGamesTests(unittest.TestCase):
    def test_parses_mfst_id_and_encoded_path(self):
        entry = parse_ea_manifest(
            "?id=1039084&dipinstallpath=C%3A%5CProgram+Files%20%28x86%29%5COrigin+Games%5CApex+Legends&locale=en_US"
        )
        assert entry is not None
        self.assertEqual(entry["app_id"], "1039084")
        self.assertEqual(entry["name"], "Apex Legends")
        self.assertTrue(entry["install_dir"].endswith("Apex Legends"))
        self.assertIsNone(parse_ea_manifest("?locale=en_US"))

    def test_discovers_from_ea_and_origin_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            game_dir = base / "ProgramDataFake" / "Apex"
            for local_content in ("EA", "Origin"):
                folder = base / local_content / "LocalContent" / "apex"
                folder.mkdir(parents=True)
                (folder / "apex.mfst").write_text(
                    f"?id=1&dipinstallpath={urllib.parse.quote(str(game_dir))}", encoding="utf-8",
                )
            game_dir.mkdir(parents=True)
            games = discover_ea_games(program_data=base)
            self.assertEqual([game["name"] for game in games], ["Apex"])
            self.assertEqual(games[0]["source"], "ea")


class XboxGamesTests(unittest.TestCase):
    def test_discovers_gaming_root_folders_and_prefers_content(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = Path(directory)
            game = drive / "XboxGames" / "Forza Horizon"
            (game / "Content").mkdir(parents=True)
            (game / "GamingRoot").write_bytes(b"\x01")
            (drive / "XboxGames" / "NotAGame").mkdir(parents=True)
            games = discover_xbox_games(drives=[drive])
            self.assertEqual([game_entry["name"] for game_entry in games], ["Forza Horizon"])
            self.assertEqual(games[0]["source"], "xbox")
            self.assertTrue(games[0]["install_dir"].endswith("Content"))

    def test_falls_back_to_folder_without_content(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = Path(directory)
            game = drive / "XboxGames" / "Solo Game"
            game.mkdir(parents=True)
            (game / "GamingRoot").write_bytes(b"\x01")
            games = discover_xbox_games(drives=[drive])
            self.assertEqual(games[0]["install_dir"], str(game))


if __name__ == "__main__":
    unittest.main()
