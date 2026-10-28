from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from game_localizer.hanengine.installed_games import (
    discover_installed_games,
    discover_steam_games,
    parse_appmanifest,
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
            module._windows_registry_steam_paths = lambda: [root]
            module._default_steam_roots = lambda: [root, root]
            try:
                games = module.discover_installed_games()
            finally:
                module._windows_registry_steam_paths = original_registry
                module._default_steam_roots = original_roots
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0]["name"], "Grounded")

    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Steam"
            steamapps = root / "steamapps"
            steamapps.mkdir(parents=True)
            (steamapps / "appmanifest_1.acf").write_text(APPMANIFEST_ACF, encoding="utf-8")
            (steamapps / "common" / "Grounded").mkdir(parents=True)
            games = discover_steam_games(root)
            json.dumps(games)


if __name__ == "__main__":
    unittest.main()
