from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import cli
from game_localizer.hanengine.validation import (
    OfficialValidatorConfig,
    ProjectValidationError,
    ProjectValidationRequest,
    ProjectValidationRunner,
    renpy_sdk_validator,
    run_official_validator,
    tree_sha256,
    validate_font_coverage,
)


SAMPLES_ROOT = Path(__file__).resolve().parents[1] / "examples" / "engine_samples"
SAMPLES = (
    ("renpy", "renpy_tutorial"),
    ("rpg_maker_mv", "rpg_maker_mv"),
    ("rpg_maker_mz", "rpg_maker_mz"),
    ("godot", "godot_dodge_the_creeps"),
    ("unity", "unity_2d_kit"),
    ("unreal", "unreal_lyra"),
)


class ProjectValidationTests(unittest.TestCase):
    def _request(
        self,
        root: Path,
        *,
        engine_id: str = "renpy",
        directory: str = "renpy_tutorial",
        official_validator: OfficialValidatorConfig | None = None,
        font_paths: tuple[Path, ...] = (),
        runtime_smoke: str = "not_run",
        runtime_smoke_reference: str | None = None,
    ) -> ProjectValidationRequest:
        source = SAMPLES_ROOT / directory
        return ProjectValidationRequest(
            record_id=f"synthetic-{engine_id.replace('_', '-')}",
            project_label=f"synthetic-{directory}",
            authorization_reference="repository-owned-synthetic-fixture",
            project_root=source,
            engine_id=engine_id,
            output_root=root / f"output-{engine_id}",
            dictionary_path=source / "dictionary.zh-CN.json",
            state_root=root / "state",
            record_path=root / f"record-{engine_id}.json",
            font_paths=font_paths,
            official_validator=official_validator,
            runtime_smoke=runtime_smoke,
            runtime_smoke_reference=runtime_smoke_reference,
        )

    def test_all_synthetic_adapters_produce_portable_build_ready_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for engine_id, directory in SAMPLES:
                with self.subTest(engine=engine_id):
                    request = self._request(
                        root,
                        engine_id=engine_id,
                        directory=directory,
                    )
                    source_before = tree_sha256(request.project_root)
                    record = ProjectValidationRunner().run(request)
                    disk_payload = json.loads(request.record_path.read_text(encoding="utf-8"))
                    serialized = request.record_path.read_text(encoding="utf-8")

                    self.assertEqual(record.conclusion, "build_ready")
                    self.assertEqual(disk_payload, record.to_dict())
                    self.assertEqual(tree_sha256(request.project_root), source_before)
                    self.assertEqual(
                        record.payload["project"]["source_tree_sha256"],
                        source_before,
                    )
                    self.assertTrue(
                        record.payload["internal_verification"]["source_tree_preserved"]
                    )
                    self.assertTrue(
                        record.payload["internal_verification"]["translation_complete"]
                    )
                    self.assertEqual(
                        record.payload["official_validator"]["status"],
                        "not_configured",
                    )
                    self.assertEqual(record.payload["font_coverage"]["status"], "not_configured")
                    self.assertEqual(record.payload["runtime_smoke"]["status"], "not_run")
                    self.assertEqual(len(record.payload["tasks"]["task_ids"]), 6)
                    self.assertNotIn(str(request.project_root), serialized)
                    self.assertNotIn(str(request.project_root).replace("\\", "\\\\"), serialized)

    def test_all_external_verification_gates_are_required_for_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            validator_script = root / "validator.py"
            validator_script.write_text(
                "import sys\nsys.exit(0)\n",
                encoding="utf-8",
            )
            font_path = root / "fixture.ttf"
            font_path.write_bytes(b"font fixture")
            validator = OfficialValidatorConfig(
                Path(sys.executable),
                (str(validator_script), "{output}"),
            )
            request = self._request(
                root,
                official_validator=validator,
                font_paths=(font_path,),
                runtime_smoke="passed",
                runtime_smoke_reference="manual-smoke-2026-08-08",
            )

            with patch(
                "game_localizer.hanengine.validation.validate_font_coverage",
                return_value={
                    "status": "passed",
                    "fonts": [{"name": "fixture.ttf", "sha256": "fixture"}],
                    "required_codepoints": [],
                    "missing_codepoints": [],
                },
            ), patch(
                "game_localizer.hanengine.renpy._font_unicode_coverage",
                return_value=set(range(0x20, 0x7F))
                | set(map(ord, "请选择目的地。你好！开始游戏欢迎来到教程。\uff0c")),
            ):
                record = ProjectValidationRunner().run(request)

            self.assertEqual(record.conclusion, "verified")
            self.assertEqual(record.payload["official_validator"]["status"], "passed")
            self.assertTrue(record.payload["official_validator"]["output_tree_preserved"])

    def test_official_validator_records_only_portable_result_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            success = root / "success.py"
            success.write_text(
                "import sys\nprint('private-project-output')\nsys.exit(0)\n",
                encoding="utf-8",
            )
            failure = root / "failure.py"
            failure.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")

            passed = run_official_validator(
                OfficialValidatorConfig(
                    Path(sys.executable),
                    (str(success), "{output}"),
                ),
                output,
            )
            failed = run_official_validator(
                OfficialValidatorConfig(
                    Path(sys.executable),
                    (str(failure), "{output}"),
                ),
                output,
            )

            self.assertEqual(passed["status"], "passed")
            self.assertEqual(passed["exit_code"], 0)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["exit_code"], 7)
            self.assertNotIn("private-project-output", json.dumps(passed))

    def test_official_validator_runs_on_shadow_and_reports_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            before = tree_sha256(output)
            validator_script = root / "mutating.py"
            validator_script.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "Path(sys.argv[1], 'validator-output.txt').write_text('generated')\n"
                "sys.exit(0)\n",
                encoding="utf-8",
            )

            result = run_official_validator(
                OfficialValidatorConfig(
                    Path(sys.executable),
                    (str(validator_script), "{output}"),
                ),
                output,
            )

            self.assertEqual(result["status"], "passed")
            self.assertFalse(result["validator_tree_preserved"])
            self.assertEqual(result["validator_modified_paths"], ["validator-output.txt"])
            self.assertEqual(tree_sha256(output), before)

    def test_renpy_sdk_configuration_uses_launcher_project_compile_contract(self):
        config = renpy_sdk_validator(Path(sys.executable), timeout_seconds=45)

        self.assertEqual(config.arguments, ("{output}", "compile"))
        self.assertEqual(config.kind, "renpy_sdk_compile")
        self.assertEqual(config.timeout_seconds, 45)

    def test_font_coverage_uses_unicode_cmap_tables(self):
        with tempfile.TemporaryDirectory() as temporary:
            font_path = Path(temporary) / "fixture.ttf"
            font_path.write_bytes(b"font fixture")
            table = MagicMock()
            table.isUnicode.return_value = True
            table.cmap = {ord("你"): "uni4F60", ord("好"): "uni597D"}
            font = MagicMock()
            font.__getitem__.return_value.tables = [table]

            with patch("fontTools.ttLib.TTFont", return_value=font):
                passed = validate_font_coverage((font_path,), ("你好",))
                failed = validate_font_coverage((font_path,), ("你好！",))

            self.assertEqual(passed["status"], "passed")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["missing_codepoints"], ["U+FF01"])
            self.assertEqual(font.close.call_count, 2)

    def test_tree_hash_is_stable_and_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.txt"
            target.write_text("stable", encoding="utf-8")
            first = tree_sha256(root)
            self.assertEqual(tree_sha256(root), first)
            target.write_text("changed", encoding="utf-8")
            self.assertNotEqual(tree_sha256(root), first)
            link = root / "link.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("current environment does not allow symbolic links")
            with self.assertRaises(ProjectValidationError):
                tree_sha256(root)

    def test_request_keeps_record_outside_source_and_candidate_trees(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = SAMPLES_ROOT / "renpy_tutorial"
            with self.assertRaisesRegex(ValueError, "record_path must be outside output_root"):
                ProjectValidationRequest(
                    record_id="invalid-record-location",
                    project_label="fixture",
                    authorization_reference="fixture-authorization",
                    project_root=source,
                    engine_id="renpy",
                    output_root=root / "output",
                    dictionary_path=source / "dictionary.zh-CN.json",
                    state_root=root / "state",
                    record_path=root / "output" / "record.json",
                )

    def test_cli_requires_authorization_and_writes_build_ready_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = SAMPLES_ROOT / "renpy_tutorial"
            record = root / "record.json"
            arguments = [
                "project",
                "validate",
                "renpy",
                str(source),
                "--output",
                str(root / "output"),
                "--dictionary",
                str(source / "dictionary.zh-CN.json"),
                "--state-root",
                str(root / "state"),
                "--record",
                str(record),
                "--record-id",
                "cli-renpy-fixture",
                "--project-label",
                "renpy-synthetic-fixture",
                "--authorization-reference",
                "repository-owned-synthetic-fixture",
            ]

            with redirect_stderr(io.StringIO()) as errors:
                denied = cli.main(arguments)
            self.assertEqual(denied, 1)
            self.assertIn("--authorized", errors.getvalue())
            self.assertFalse(record.exists())

            with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
                accepted = cli.main([*arguments, "--authorized"])

            self.assertEqual(accepted, 0, errors.getvalue())
            self.assertIn("build_ready", output.getvalue())
            payload = json.loads(record.read_text(encoding="utf-8"))
            self.assertEqual(payload["conclusion"], "build_ready")
            self.assertNotIn(str(source).replace("\\", "\\\\"), record.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
