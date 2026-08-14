import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import cli
from game_localizer.hanengine import TranslationResult


class FeatureCliTests(unittest.TestCase):
    def test_engine_inspect_reports_build_ready_capabilities_and_hanguard_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            (project / "data").mkdir(parents=True)
            (project / "game.rpgproject").write_text("MV", encoding="utf-8")
            (project / "data" / "System.json").write_text(
                '{"gameTitle":"Demo"}',
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli.run_engine(
                    [
                        "inspect",
                        "auto",
                        str(project),
                        "--json",
                        "--mode",
                        "player",
                        "--state-root",
                        str(root / "state"),
                    ]
                )
            payload = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(payload["selected_engine"], "rpg_maker_mv")
            self.assertTrue(
                {"extract", "validate", "build", "verify"}.issubset(
                    payload["capabilities"]
                )
            )
            self.assertTrue(
                {"extract", "validate", "build", "verify"}.issubset(
                    payload["allowed_operations"]
                )
            )
            self.assertEqual(payload["hanguard"]["phase"], "final")

    def test_engine_inspect_keeps_packaged_unity_detection_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            (project / "Demo_Data").mkdir(parents=True)
            (project / "UnityPlayer.dll").write_bytes(b"fixture")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli.run_engine(
                    [
                        "inspect",
                        "auto",
                        str(project),
                        "--json",
                        "--mode",
                        "player",
                        "--state-root",
                        str(root / "state"),
                    ]
                )
            payload = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "detect_only")
            self.assertEqual(payload["selected_engine"], "unity")
            self.assertEqual(payload["capabilities"], ["detect"])
            self.assertEqual(payload["allowed_operations"], ["detect"])

    def test_engine_localize_pipeline_resumes_persisted_dictionary_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            (project / "data").mkdir(parents=True)
            (project / "game.rpgproject").write_text("MV", encoding="utf-8")
            (project / "data" / "Actors.json").write_text(
                json.dumps(
                    {
                        "name": "Hero",
                        "events": [
                            {"code": 401, "parameters": ["Hello, {name}!"]}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            dictionary = root / "dictionary.json"
            dictionary.write_text(
                json.dumps(
                    {
                        "Hero": "英雄",
                        "Hello, {name}!": "你好，{name}!",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state = root / "state"
            translated_catalog = root / "translated.json"

            first_output = io.StringIO()
            with redirect_stdout(first_output):
                first_code = cli.run_engine(
                    [
                        "localize",
                        "rpg_maker_mv",
                        str(project),
                        "--output",
                        str(root / "output-1"),
                        "--dictionary",
                        str(dictionary),
                        "--state-root",
                        str(state),
                        "--translated-catalog",
                        str(translated_catalog),
                        "--quiet-progress",
                    ]
                )

            second_output = io.StringIO()
            with redirect_stdout(second_output):
                second_code = cli.run_engine(
                    [
                        "localize",
                        "rpg_maker_mv",
                        str(project),
                        "--output",
                        str(root / "output-2"),
                        "--dictionary",
                        str(dictionary),
                        "--state-root",
                        str(state),
                        "--quiet-progress",
                    ]
                )

            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertIn("Translated 2 new, resumed 0", first_output.getvalue())
            self.assertIn("Translated 0 new, resumed 2", second_output.getvalue())
            self.assertTrue(translated_catalog.is_file())
            localized = json.loads(
                (root / "output-2" / "data" / "Actors.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(localized["name"], "英雄")

    def test_engine_localize_uses_cloud_provider_without_persisting_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            (project / "data").mkdir(parents=True)
            (project / "game.rpgproject").write_text("MV", encoding="utf-8")
            (project / "data" / "System.json").write_text(
                json.dumps({"gameTitle": "Demo"}),
                encoding="utf-8",
            )
            state = root / "state"
            provider = unittest.mock.Mock()
            provider.translate.return_value = TranslationResult(
                "云端译文",
                "cloud",
                "test-model",
                0.95,
            )
            token = "pipeline-secret-token"
            previous = os.environ.get("HANENGINE_TRANSLATION_TOKEN")
            os.environ["HANENGINE_TRANSLATION_TOKEN"] = token
            try:
                with (
                    patch.object(
                        cli,
                        "CloudTranslationProvider",
                        return_value=provider,
                    ) as constructor,
                    redirect_stdout(io.StringIO()),
                ):
                    code = cli.run_engine(
                        [
                            "localize",
                            "rpg_maker_mv",
                            str(project),
                            "--output",
                            str(root / "output"),
                            "--cloud-endpoint",
                            "https://example.test/translate",
                            "--state-root",
                            str(state),
                            "--quiet-progress",
                        ]
                    )
            finally:
                if previous is None:
                    os.environ.pop("HANENGINE_TRANSLATION_TOKEN", None)
                else:
                    os.environ["HANENGINE_TRANSLATION_TOKEN"] = previous

            self.assertEqual(code, 0)
            provider.translate.assert_called_once()
            token_provider = constructor.call_args.kwargs["token_provider"]
            previous = os.environ.get("HANENGINE_TRANSLATION_TOKEN")
            os.environ["HANENGINE_TRANSLATION_TOKEN"] = token
            try:
                self.assertEqual(token_provider(), token)
            finally:
                if previous is None:
                    os.environ.pop("HANENGINE_TRANSLATION_TOKEN", None)
                else:
                    os.environ["HANENGINE_TRANSLATION_TOKEN"] = previous
            persisted = b"".join(path.read_bytes() for path in state.rglob("*.db"))
            self.assertNotIn(token.encode("utf-8"), persisted)
            localized = json.loads(
                (root / "output" / "data" / "System.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(localized["gameTitle"], "云端译文")

    def test_engine_cli_hanguard_restriction_blocks_extract_without_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            (project / "data").mkdir(parents=True)
            (project / "game.rpgproject").write_text("MV", encoding="utf-8")
            (project / "data" / "System.json").write_text(
                '{"gameTitle":"Demo"}',
                encoding="utf-8",
            )
            catalog = root / "catalog.json"
            output = io.StringIO()
            errors = io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                code = cli.run_engine(
                    [
                        "extract",
                        "auto",
                        str(project),
                        "--output",
                        str(catalog),
                        "--state-root",
                        str(root / "state"),
                        "--risk-level",
                        "H2_RESTRICTED",
                    ]
                )

            self.assertEqual(code, 1)
            self.assertFalse(catalog.exists())
            self.assertIn("allowed=detect", output.getvalue())
            self.assertIn("does not authorize extract", errors.getvalue())
            self.assertNotIn("Traceback", errors.getvalue())

    def test_renpy_extract_and_build_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            game = project / "game"
            game.mkdir(parents=True)
            (game / "script.rpy").write_text(
                'e "Hello"\n"Start"\n$ dynamic = _(runtime_label)\n',
                encoding="utf-8",
            )
            catalog = root / "catalog.json"
            output = root / "output"
            dictionary = root / "dictionary.json"
            dictionary.write_text(
                json.dumps({"Hello": "\u4f60\u597d", "Start": "\u5f00\u59cb"}, ensure_ascii=False),
                encoding="utf-8",
            )

            errors = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(errors):
                extract_code = cli.run_renpy(
                    ["extract", str(project), "--output", str(catalog), "--language", "zh_cn"]
                )
                build_code = cli.run_renpy(
                    [
                        "build",
                        str(project),
                        str(catalog),
                        "--output",
                        str(output),
                        "--dictionary",
                        str(dictionary),
                    ]
                )

            self.assertEqual(extract_code, 0)
            self.assertEqual(build_code, 0)
            payload = json.loads(catalog.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["entries"]), 2)
            self.assertEqual(len(payload["unhandled_items"]), 1)
            self.assertIn("runtime/manual review", errors.getvalue())
            generated = output / "game" / "tl" / "zh_cn" / "hanengine_translations.rpy"
            self.assertIn("\u4f60\u597d", generated.read_text(encoding="utf-8"))

    def test_renpy_adapter_v1_inspect_and_one_click_localize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            game = project / "game"
            game.mkdir(parents=True)
            source = game / "script.rpy"
            source.write_text(
                'label start:\n    e "Hello, [name]!"\n    "Start"\n',
                encoding="utf-8",
            )
            dictionary = root / "dictionary.json"
            dictionary.write_text(
                json.dumps(
                    {
                        "Hello, [name]!": "你好，[name]！",
                        "Start": "开始",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            inspected = io.StringIO()
            with redirect_stdout(inspected):
                inspect_code = cli.run_engine(
                    [
                        "inspect",
                        "auto",
                        str(project),
                        "--json",
                        "--mode",
                        "player",
                        "--state-root",
                        str(root / "state"),
                    ]
                )
            report = json.loads(inspected.getvalue())
            self.assertEqual(inspect_code, 0)
            self.assertEqual(report["selected_engine"], "renpy")
            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["hanguard"]["phase"], "final")

            before = source.read_bytes()
            output = root / "output"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
                localize_code = cli.run_engine(
                    [
                        "localize",
                        "auto",
                        str(project),
                        "--output",
                        str(output),
                        "--dictionary",
                        str(dictionary),
                        "--state-root",
                        str(root / "state"),
                        "--mode",
                        "player",
                        "--quiet-progress",
                    ]
                )
            self.assertEqual(localize_code, 0, errors.getvalue())
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual((output / "game" / "script.rpy").read_bytes(), before)
            generated = output / "game" / "tl" / "zh_cn" / "hanengine_translations.rpy"
            self.assertIn("你好", generated.read_text(encoding="utf-8"))

    def test_renpy_compiled_project_remains_detection_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            game = project / "game"
            game.mkdir(parents=True)
            (game / "script.rpyc").write_bytes(b"compiled fixture")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli.run_engine(
                    [
                        "inspect",
                        "auto",
                        str(project),
                        "--json",
                        "--mode",
                        "player",
                        "--state-root",
                        str(root / "state"),
                    ]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["selected_engine"], "renpy")
            self.assertEqual(payload["status"], "detect_only")
            self.assertEqual(payload["capabilities"], ["detect"])

    def test_package_command_builds_copy_and_apply_gate_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "game.zip"
            patch_path = root / "patch.json"
            output = root / "localized.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("game/data.txt", b"old")
            patch_path.write_text('{"game/data.txt":"new"}', encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                result = cli.run_package([str(archive), str(patch_path), "--output", str(output)])
            self.assertEqual(result, 0)
            with zipfile.ZipFile(output, "r") as package:
                self.assertEqual(package.read("game/data.txt"), b"new")

            errors = io.StringIO()
            with redirect_stderr(errors):
                denied = cli.run_package([str(archive), str(patch_path), "--apply"])
            self.assertEqual(denied, 1)
            self.assertIn("--authorized", errors.getvalue())
            with zipfile.ZipFile(archive, "r") as package:
                self.assertEqual(package.read("game/data.txt"), b"old")

    def test_cloud_translation_can_use_an_endpoint_without_persisting_a_token(self):
        provider = unittest.mock.Mock()
        provider.translate.return_value = TranslationResult("\u4f60\u597d", "cloud", "test", 1.0)
        previous = os.environ.pop("HANENGINE_TRANSLATION_TOKEN", None)
        try:
            with (
                patch.object(cli, "CloudTranslationProvider", return_value=provider) as constructor,
                redirect_stdout(io.StringIO()) as output,
            ):
                result = cli.run_cloud_translate(["Hello", "--endpoint", "https://example.test/translate"])
        finally:
            if previous is not None:
                os.environ["HANENGINE_TRANSLATION_TOKEN"] = previous

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "\u4f60\u597d")
        token_provider = constructor.call_args.kwargs["token_provider"]
        self.assertIsNone(token_provider())

    def test_cloud_translation_argument_error_and_tts_failure_are_clean(self):
        with redirect_stderr(io.StringIO()) as cloud_errors:
            self.assertEqual(cli.run_cloud_translate([]), 1)
        self.assertIn("--endpoint", cloud_errors.getvalue())

        provider = unittest.mock.Mock()
        provider.synthesize.side_effect = RuntimeError("SAPI unavailable")
        with (
            patch.object(cli, "WindowsSapiTts", return_value=provider),
            redirect_stderr(io.StringIO()) as tts_errors,
        ):
            result = cli.run_tts(["Hello", "--output", "voice.wav"])
        self.assertEqual(result, 1)
        self.assertIn("SAPI unavailable", tts_errors.getvalue())
        self.assertNotIn("Traceback", tts_errors.getvalue())


if __name__ == "__main__":
    unittest.main()
