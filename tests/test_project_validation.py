from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import cli
from game_localizer.hanengine import (
    RASTER_MANIFEST_SCHEMA_VERSION,
    RasterAsset,
    RasterAssetKind,
    RasterManifest,
    RasterSegmentStatus,
    RasterTextSegment,
    RasterTextStyle,
    RpgMakerExtractor,
    ScreenRegion,
    write_raster_manifest,
)
from game_localizer.hanengine.validation import (
    OfficialValidatorConfig,
    ProjectValidationError,
    ProjectValidationRequest,
    ProjectValidationRunner,
    godot_editor_validator,
    renpy_sdk_validator,
    run_official_validator,
    tree_sha256,
    validate_font_coverage,
)
from game_localizer.hanengine.nwjs import NwjsRpgMakerValidatorConfig


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
        font_probe_texts: tuple[str, ...] = (),
        runtime_smoke: str = "not_run",
        runtime_smoke_reference: str | None = None,
        raster_manifest_path: Path | None = None,
        nwjs_validator: NwjsRpgMakerValidatorConfig | None = None,
        reviewed_catalog_path: Path | None = None,
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
            reviewed_catalog_path=reviewed_catalog_path,
            state_root=root / "state",
            record_path=root / f"record-{engine_id}.json",
            font_paths=font_paths,
            font_probe_texts=font_probe_texts,
            official_validator=official_validator,
            runtime_smoke=runtime_smoke,
            runtime_smoke_reference=runtime_smoke_reference,
            raster_manifest_path=raster_manifest_path,
            nwjs_validator=nwjs_validator,
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
                    self.assertEqual(
                        record.payload["raster_verification"]["status"],
                        "not_configured",
                    )
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
                font_probe_texts=("★",),
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
            ) as coverage_validator, patch(
                "game_localizer.hanengine.renpy._font_unicode_coverage",
                return_value=set(range(0x20, 0x7F))
                | set(map(ord, "请选择目的地。你好！开始游戏欢迎来到教程。\uff0c★")),
            ):
                record = ProjectValidationRunner().run(request)

            self.assertEqual(record.conclusion, "verified")
            self.assertEqual(record.payload["official_validator"]["status"], "passed")
            self.assertTrue(record.payload["official_validator"]["output_tree_preserved"])
            self.assertIn("★", coverage_validator.call_args.args[1])

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

    def test_official_validator_rechecks_a_warmed_shadow_and_blocks_output_markers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            validator_script = root / "two_pass_validator.py"
            validator_script.write_text(
                "from pathlib import Path\n"
                "marker = Path('warm-cache')\n"
                "if marker.exists():\n"
                "    print('SCRIPT ERROR: persistent project failure')\n"
                "else:\n"
                "    marker.write_text('ready')\n",
                encoding="utf-8",
            )

            result = run_official_validator(
                OfficialValidatorConfig(
                    Path(sys.executable),
                    (str(validator_script), "{output}"),
                    clean_passes=2,
                    failure_markers=("SCRIPT ERROR:",),
                ),
                output,
            )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["passes_run"], 2)
            self.assertEqual(result["reported_failure_markers"], ["SCRIPT ERROR:"])
            self.assertNotIn("persistent project failure", json.dumps(result))
            self.assertFalse((output / "warm-cache").exists())

    def test_renpy_sdk_configuration_uses_launcher_project_compile_contract(self):
        config = renpy_sdk_validator(Path(sys.executable), timeout_seconds=45)

        self.assertEqual(config.arguments, ("{output}", "compile"))
        self.assertEqual(config.kind, "renpy_sdk_compile")
        self.assertEqual(config.timeout_seconds, 45)

    def test_godot_configuration_requires_a_clean_second_editor_pass(self):
        config = godot_editor_validator(Path(sys.executable), timeout_seconds=45)

        self.assertEqual(
            config.arguments,
            ("--headless", "--editor", "--path", "{output}", "--quit"),
        )
        self.assertEqual(config.kind, "godot_headless_editor")
        self.assertEqual(config.clean_passes, 2)
        self.assertIn("SCRIPT ERROR:", config.failure_markers)

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

    def test_request_rejects_font_probe_without_configured_fonts(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "require configured font_paths"):
                self._request(Path(temporary), font_probe_texts=("★",))

    def test_reviewed_catalog_preserves_segment_specific_targets_before_dictionary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "project"
            shutil.copytree(SAMPLES_ROOT / "rpg_maker_mv", source)
            actors_path = source / "data" / "Actors.json"
            actors = json.loads(actors_path.read_text(encoding="utf-8"))
            actors[1]["name"] = "Attack"
            actors_path.write_text(
                json.dumps(actors, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            dictionary_path = root / "dictionary.json"
            dictionary = json.loads(
                (source / "dictionary.zh-CN.json").read_text(encoding="utf-8")
            )
            dictionary_path.write_text(
                json.dumps(dictionary, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            catalog = RpgMakerExtractor("rpg_maker_mv").extract(source).translate(
                dictionary
            )
            reviewed = replace(
                catalog,
                entries=tuple(
                    replace(entry, target_text="阿塔克")
                    if entry.relative_path == "data/Actors.json"
                    and entry.source_text == "Attack"
                    else entry
                    for entry in catalog.entries
                ),
            )
            reviewed_path = root / "reviewed.json"
            reviewed_path.write_text(
                json.dumps(reviewed.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            output = root / "output"
            record_path = root / "record.json"
            arguments = [
                "project",
                "validate",
                "rpg_maker_mv",
                str(source),
                "--output",
                str(output),
                "--dictionary",
                str(dictionary_path),
                "--reviewed-catalog",
                str(reviewed_path),
                "--state-root",
                str(root / "state"),
                "--record",
                str(record_path),
                "--record-id",
                "reviewed-context-fixture",
                "--project-label",
                "reviewed-context-fixture",
                "--authorization-reference",
                "repository-owned-synthetic-fixture",
                "--authorized",
            ]

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
                code = cli.main(arguments)

            self.assertEqual(code, 0, errors.getvalue())
            localized_actors = json.loads(
                (output / "data" / "Actors.json").read_text(encoding="utf-8")
            )
            localized_system = json.loads(
                (output / "data" / "System.json").read_text(encoding="utf-8")
            )
            self.assertEqual(localized_actors[1]["name"], "阿塔克")
            self.assertEqual(localized_system["terms"]["basic"][0], "攻击")
            payload = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["reviewed_catalog"]["matched_segment_count"],
                len(catalog.entries),
            )
            self.assertEqual(
                payload["translation"]["catalog_count"], len(catalog.entries)
            )

    def test_reviewed_catalog_must_match_fresh_project_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = SAMPLES_ROOT / "rpg_maker_mv"
            catalog = RpgMakerExtractor("rpg_maker_mv").extract(source)
            reviewed = replace(catalog, project_fingerprint="0" * 64)
            reviewed_path = root / "reviewed.json"
            reviewed_path.write_text(
                json.dumps(reviewed.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            request = ProjectValidationRequest(
                record_id="reviewed-mismatch-fixture",
                project_label="reviewed-mismatch-fixture",
                authorization_reference="repository-owned-synthetic-fixture",
                project_root=source,
                engine_id="rpg_maker_mv",
                output_root=root / "output",
                dictionary_path=source / "dictionary.zh-CN.json",
                reviewed_catalog_path=reviewed_path,
                state_root=root / "state",
                record_path=root / "record.json",
            )

            record = ProjectValidationRunner().run(request)

            self.assertEqual(record.conclusion, "failed")
            self.assertEqual(record.payload["failure"], "ProjectValidationError")
            self.assertFalse(request.output_root.exists())

    def test_request_restricts_nwjs_to_rpg_maker_with_external_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "manifest.json"
            manifest.write_text("{}\n", encoding="utf-8")
            config = NwjsRpgMakerValidatorConfig(
                Path(sys.executable), root / "evidence"
            )
            with self.assertRaisesRegex(ValueError, "requires an RPG Maker"):
                self._request(
                    root,
                    raster_manifest_path=manifest,
                    nwjs_validator=config,
                )

            overlapping = NwjsRpgMakerValidatorConfig(
                Path(sys.executable), root / "output-rpg_maker_mv" / "evidence"
            )
            with self.assertRaisesRegex(ValueError, "outside output_root"):
                self._request(
                    root,
                    engine_id="rpg_maker_mv",
                    directory="rpg_maker_mv",
                    raster_manifest_path=manifest,
                    nwjs_validator=overlapping,
                )

    def test_cli_nwjs_pass_populates_runtime_gates_and_can_verify(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "project"
            shutil.copytree(SAMPLES_ROOT / "rpg_maker_mv", source)
            (source / "fonts").mkdir()
            (source / "fonts" / "gamefont.css").write_text(
                "@font-face { font-family: GameFont; src: url(\"mplus.ttf\"); }\n",
                encoding="utf-8",
            )
            (source / "fonts" / "mplus.ttf").write_bytes(b"source-font")
            font = root / "SourceHanSans.ttf"
            font.write_bytes(b"localized-font")
            record = root / "record.json"
            evidence = root / "nwjs-evidence"
            arguments = [
                "project",
                "validate",
                "auto",
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
                "cli-rpg-mv-nwjs",
                "--project-label",
                "rpg-mv-nwjs-fixture",
                "--authorization-reference",
                "repository-owned-synthetic-fixture",
                "--font",
                str(font),
                "--nwjs",
                sys.executable,
                "--nwjs-evidence",
                str(evidence),
                "--authorized",
            ]
            style_report = MagicMock()
            style_report.passed = True
            style_report.to_dict.return_value = {"passed": True, "issues": []}
            runtime_report = {
                "status": "passed",
                "report_sha256": "a" * 64,
                "approved_video_count": 0,
                "approved_segment_count": 0,
                "candidate_tree_sha256_before": "b" * 64,
                "candidate_tree_sha256_after": "b" * 64,
            }

            with patch(
                "game_localizer.hanengine.validation.validate_font_coverage",
                return_value={
                    "status": "passed",
                    "fonts": [{"name": font.name, "sha256": "fixture"}],
                    "required_codepoints": [],
                    "missing_codepoints": [],
                },
            ), patch(
                "game_localizer.hanengine.validation.run_rpg_maker_style_hard_gate",
                return_value=style_report,
            ), patch(
                "game_localizer.hanengine.validation.run_nwjs_rpg_maker_validation",
                return_value=runtime_report,
            ) as runtime_validator, redirect_stdout(io.StringIO()), redirect_stderr(
                io.StringIO()
            ) as errors:
                code = cli.main(arguments)

            self.assertEqual(code, 0, errors.getvalue())
            payload = json.loads(record.read_text(encoding="utf-8"))
            self.assertEqual(payload["conclusion"], "verified")
            self.assertEqual(payload["official_validator"]["status"], "passed")
            self.assertEqual(
                payload["official_validator"]["kind"],
                "nwjs_rpg_maker_runtime",
            )
            self.assertEqual(payload["runtime_smoke"]["status"], "passed")
            self.assertEqual(payload["runtime_validation"], runtime_report)
            self.assertIsNone(runtime_validator.call_args.args[3])

    def test_cli_nwjs_requires_evidence_directory_without_a_raster_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = SAMPLES_ROOT / "rpg_maker_mv"
            arguments = [
                "project",
                "validate",
                "rpg_maker_mv",
                str(source),
                "--output",
                str(root / "output"),
                "--dictionary",
                str(source / "dictionary.zh-CN.json"),
                "--state-root",
                str(root / "state"),
                "--record",
                str(root / "record.json"),
                "--record-id",
                "cli-nwjs-dependencies",
                "--project-label",
                "rpg-mv-fixture",
                "--authorization-reference",
                "repository-owned-synthetic-fixture",
                "--nwjs",
                sys.executable,
                "--authorized",
            ]

            with redirect_stderr(io.StringIO()) as errors:
                code = cli.main(arguments)

            self.assertEqual(code, 1)
            self.assertIn("--nwjs requires --nwjs-evidence", errors.getvalue())

    def test_cli_project_validation_builds_font_and_approved_raster_in_one_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "project"
            shutil.copytree(SAMPLES_ROOT / "rpg_maker_mv", source)
            (source / "fonts").mkdir()
            (source / "fonts" / "gamefont.css").write_text(
                "@font-face { font-family: GameFont; src: url(\"mplus.ttf\"); }\n",
                encoding="utf-8",
            )
            (source / "fonts" / "mplus.ttf").write_bytes(b"source-font")
            (source / "img" / "system").mkdir(parents=True)
            (source / "img" / "system" / "Window.png").write_bytes(
                b"source-window"
            )
            (source / "img" / "title.png").write_bytes(b"source-title")
            font = root / "SourceHanSans.ttf"
            font.write_bytes(b"localized-font")
            raster_root = root / "raster"
            raster_root.mkdir()
            localized_raster = raster_root / "title.zh.png"
            localized_raster.write_bytes(b"localized-title")
            manifest_path = write_raster_manifest(
                RasterManifest(
                    RASTER_MANIFEST_SCHEMA_VERSION,
                    "en",
                    "zh-CN",
                    (
                        RasterAsset(
                            "img/title.png",
                            RasterAssetKind.IMAGE,
                            hashlib.sha256(b"source-title").hexdigest(),
                            "title.zh.png",
                            hashlib.sha256(b"localized-title").hexdigest(),
                            (
                                RasterTextSegment(
                                    "title-text",
                                    "img/title.png",
                                    RasterAssetKind.IMAGE,
                                    "START",
                                    "开始",
                                    ScreenRegion(0, 0, 100, 30),
                                    None,
                                    None,
                                    0.99,
                                    RasterTextStyle(
                                        font_family="Source Han Sans",
                                        font_size_px=18,
                                        fill_color="#ffffff",
                                    ),
                                    RasterSegmentStatus.APPROVED,
                                    None,
                                ),
                            ),
                        ),
                    ),
                ),
                raster_root / "manifest.json",
            )
            output = root / "output"
            record = root / "record.json"
            source_before = tree_sha256(source)
            arguments = [
                "project",
                "validate",
                "auto",
                str(source),
                "--output",
                str(output),
                "--dictionary",
                str(source / "dictionary.zh-CN.json"),
                "--state-root",
                str(root / "state"),
                "--record",
                str(record),
                "--record-id",
                "cli-rpg-mv-raster-font",
                "--project-label",
                "rpg-mv-raster-font-fixture",
                "--authorization-reference",
                "repository-owned-synthetic-fixture",
                "--font",
                str(font),
                "--raster-manifest",
                str(manifest_path),
                "--authorized",
            ]

            with patch(
                "game_localizer.hanengine.validation.validate_font_coverage",
                return_value={
                    "status": "passed",
                    "fonts": [{"name": font.name, "sha256": "fixture"}],
                    "required_codepoints": [],
                    "missing_codepoints": [],
                },
            ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
                code = cli.main(arguments)

            self.assertEqual(code, 0, errors.getvalue())
            payload = json.loads(record.read_text(encoding="utf-8"))
            self.assertEqual(payload["conclusion"], "build_ready")
            self.assertEqual(payload["raster_verification"]["status"], "passed")
            self.assertTrue(payload["raster_verification"]["passed"])
            self.assertEqual(payload["raster_resources"]["asset_count"], 1)
            manifest_paths = {
                entry["relative_path"] for entry in payload["build"]["manifest"]
            }
            self.assertIn("img/title.png", manifest_paths)
            self.assertIn("fonts/SourceHanSans.ttf", manifest_paths)
            self.assertEqual(
                (output / "img" / "title.png").read_bytes(), b"localized-title"
            )
            self.assertEqual(tree_sha256(source), source_before)

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

            with redirect_stderr(io.StringIO()) as errors:
                missing_font = cli.main(
                    [*arguments, "--authorized", "--font-probe-text", "★"]
                )
            self.assertEqual(missing_font, 1)
            self.assertIn("require configured font_paths", errors.getvalue())

            with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
                accepted = cli.main([*arguments, "--authorized"])

            self.assertEqual(accepted, 0, errors.getvalue())
            self.assertIn("build_ready", output.getvalue())
            payload = json.loads(record.read_text(encoding="utf-8"))
            self.assertEqual(payload["conclusion"], "build_ready")
            self.assertNotIn(str(source).replace("\\", "\\\\"), record.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
