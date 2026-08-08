from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import cli
from game_localizer.hanengine.multiengine import (
    MultiEngineError,
    MultiEngineExtractor,
    extract_placeholders,
    validate_resource_syntax,
)
from game_localizer.structured_workflow import project_id_for_root
from game_localizer.hanengine import HanStore, TaskState
from translator import load_translation_dictionary


SAMPLES_ROOT = Path(__file__).resolve().parents[1] / "examples" / "engine_samples"
SAMPLES = (
    ("rpg_maker_mv", "rpg_maker_mv"),
    ("rpg_maker_mz", "rpg_maker_mz"),
    ("godot", "godot_dodge_the_creeps"),
    ("unity", "unity_2d_kit"),
    ("unreal", "unreal_lyra"),
)


def snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


class EngineSampleAcceptanceTests(unittest.TestCase):
    def _sample_paths(self, directory: str) -> tuple[Path, Path]:
        root = SAMPLES_ROOT / directory
        return root, root / "dictionary.zh-CN.json"

    def test_player_workflow_extracts_protects_placeholders_and_builds_all_samples(self):
        for engine_id, directory in SAMPLES:
            with self.subTest(engine=engine_id):
                source, dictionary_path = self._sample_paths(directory)
                before = snapshot_tree(source)
                catalog = MultiEngineExtractor().extract(
                    engine_id,
                    source,
                    language="zh-CN",
                    source_language="en",
                )
                translations = load_translation_dictionary(dictionary_path)
                self.assertGreater(len(catalog.entries), 0)
                self.assertTrue(
                    {entry.source_text for entry in catalog.entries}
                    <= set(translations)
                )

                translated = catalog.translate(translations)
                self.assertTrue(all(entry.target_text for entry in translated.entries))
                placeholder_entries = [
                    entry
                    for entry in catalog.entries
                    if extract_placeholders(entry.source_text)
                ]
                self.assertTrue(placeholder_entries)
                for entry in placeholder_entries:
                    with self.subTest(
                        placeholder=entry.source_text,
                    ):
                        with self.assertRaises(MultiEngineError):
                            catalog.translate({entry.source_text: "broken"})

                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    output = root / "localized"
                    state = root / "state"
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = cli.run_engine(
                            [
                                "localize",
                                engine_id,
                                str(source),
                                "--output",
                                str(output),
                                "--dictionary",
                                str(dictionary_path),
                                "--state-root",
                                str(state),
                                "--mode",
                                "player",
                                "--quiet-progress",
                            ]
                        )
                    self.assertEqual(code, 0, stderr.getvalue())
                    self.assertTrue(output.is_dir())
                    self.assertEqual(snapshot_tree(source), before)
                    for relative in catalog.files:
                        output_file = output / Path(*relative.split("/"))
                        self.assertTrue(output_file.is_file(), relative)
                        resource_text = output_file.read_text(encoding="utf-8")
                        validate_resource_syntax(relative, resource_text)
                    for entry in translated.entries:
                        resource_text = (
                            output / Path(*entry.relative_path.split("/"))
                        ).read_text(encoding="utf-8")
                        self.assertIn(entry.target_text, resource_text)

                    with HanStore(state) as store:
                        statuses = store.list_task_statuses(
                            project_id=project_id_for_root(source)
                        )
                    self.assertGreaterEqual(len(statuses), 5)
                    self.assertTrue(
                        all(status.task.state is TaskState.COMPLETED for status in statuses)
                    )
                    self.assertTrue(
                        any(
                            status.final_route is not None
                            and any(
                                operation.value == "build"
                                for operation in status.final_route.allowed_operations
                            )
                            for status in statuses
                        )
                    )

    def test_studio_mode_runs_the_same_samples_with_explicit_project_authorization(self):
        for engine_id, directory in SAMPLES:
            with self.subTest(engine=engine_id):
                source, dictionary_path = self._sample_paths(directory)
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = cli.run_engine(
                            [
                                "localize",
                                engine_id,
                                str(source),
                                "--output",
                                str(root / "localized"),
                                "--dictionary",
                                str(dictionary_path),
                                "--state-root",
                                str(root / "state"),
                                "--mode",
                                "studio",
                                "--quiet-progress",
                            ]
                        )
                    self.assertEqual(code, 0, stderr.getvalue())
                    self.assertIn("Verified", stdout.getvalue())

    def test_renpy_sample_runs_through_adapter_v1_player_workflow(self):
        source, dictionary_path = self._sample_paths("renpy_tutorial")
        before = snapshot_tree(source)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "localized"
            state = root / "state"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.run_engine(
                    [
                        "localize",
                        "renpy",
                        str(source),
                        "--output",
                        str(output),
                        "--dictionary",
                        str(dictionary_path),
                        "--state-root",
                        str(state),
                        "--mode",
                        "player",
                        "--quiet-progress",
                    ]
                )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(snapshot_tree(source), before)
            self.assertEqual(
                (output / "game" / "script.rpy").read_bytes(),
                (source / "game" / "script.rpy").read_bytes(),
            )
            generated = output / "game" / "tl" / "zh_cn" / "hanengine_translations.rpy"
            rendered = generated.read_text(encoding="utf-8")
            self.assertIn("你好，[player_name]！", rendered)
            self.assertIn("欢迎来到教程。", rendered)
            self.assertIn("Verified 1 files", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
