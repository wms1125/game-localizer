from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from game_localizer.adapters.contract import (
    AdapterMetadata,
    BuildResult,
    DetectionResult,
    ValidationResult,
    VerifyResult,
)
from game_localizer.hanengine.translation import DictionaryTranslationProvider
from game_localizer.hanengine.godot import run_godot_style_hard_gate
from game_localizer.hanengine.multiengine import LocalizationCatalog
from game_localizer.hanengine.nwjs import (
    NwjsRpgMakerValidatorConfig,
    run_nwjs_rpg_maker_validation,
)
from game_localizer.hanengine.raster import (
    load_raster_manifest,
    verify_raster_manifest,
)
from game_localizer.hanengine.rpg_maker import run_rpg_maker_style_hard_gate
from game_localizer.structured_workflow import (
    StructuredValidationFailed,
    StructuredVerificationFailed,
    StructuredWorkflowSession,
)
from translator import load_translation_dictionary


VALIDATION_SCHEMA_VERSION = "hanengine.validation/v1"
_RECORD_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,80}\Z")
_SAFE_TEXT_RE = re.compile(r"[^\r\n]{1,240}\Z")
_OUTPUT_PLACEHOLDER = "{output}"


class ProjectValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OfficialValidatorConfig:
    command: Path
    arguments: tuple[str, ...]
    timeout_seconds: int = 120
    kind: str = "external"
    clean_passes: int = 1
    failure_markers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.command, Path):
            raise TypeError("command must be a Path")
        command = self.command.expanduser().resolve(strict=True)
        if not command.is_file():
            raise ValueError("validator command must be a file")
        object.__setattr__(self, "command", command)
        arguments = tuple(self.arguments)
        if (
            not arguments
            or any(not isinstance(argument, str) or not argument for argument in arguments)
            or _OUTPUT_PLACEHOLDER not in arguments
        ):
            raise ValueError("validator arguments must include the {output} placeholder")
        object.__setattr__(self, "arguments", arguments)
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or not 1 <= self.timeout_seconds <= 900
        ):
            raise ValueError("timeout_seconds must be between 1 and 900")
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("kind must be a non-empty string")
        if (
            isinstance(self.clean_passes, bool)
            or not isinstance(self.clean_passes, int)
            or not 1 <= self.clean_passes <= 3
        ):
            raise ValueError("clean_passes must be between 1 and 3")
        markers = tuple(self.failure_markers)
        if any(
            not isinstance(marker, str)
            or not marker
            or "\r" in marker
            or "\n" in marker
            for marker in markers
        ):
            raise ValueError("failure_markers must contain non-empty single-line strings")
        object.__setattr__(self, "failure_markers", markers)


@dataclass(frozen=True)
class ProjectValidationRequest:
    record_id: str
    project_label: str
    authorization_reference: str
    project_root: Path
    engine_id: str
    output_root: Path
    dictionary_path: Path
    state_root: Path
    record_path: Path
    reviewed_catalog_path: Path | None = None
    target_language: str = "zh-CN"
    source_language: str = "en"
    font_paths: tuple[Path, ...] = ()
    font_probe_texts: tuple[str, ...] = ()
    official_validator: OfficialValidatorConfig | None = None
    runtime_smoke: Literal["not_run", "passed", "failed"] = "not_run"
    runtime_smoke_reference: str | None = None
    raster_manifest_path: Path | None = None
    nwjs_validator: NwjsRpgMakerValidatorConfig | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or _RECORD_ID_RE.fullmatch(self.record_id) is None:
            raise ValueError("record_id must use lower-case letters, digits, dots, underscores or hyphens")
        for field_name in ("project_label", "authorization_reference"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or _SAFE_TEXT_RE.fullmatch(value) is None:
                raise ValueError(f"{field_name} must be a short single-line string")
        if not isinstance(self.engine_id, str) or not self.engine_id:
            raise ValueError("engine_id must not be empty")
        for field_name in (
            "project_root",
            "output_root",
            "dictionary_path",
            "state_root",
            "record_path",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Path):
                raise TypeError(f"{field_name} must be a Path")
            object.__setattr__(self, field_name, value.expanduser().resolve(strict=False))
        if not self.project_root.is_dir():
            raise ValueError("project_root must be an existing directory")
        if not self.dictionary_path.is_file():
            raise ValueError("dictionary_path must be an existing file")
        if self.reviewed_catalog_path is not None:
            if not isinstance(self.reviewed_catalog_path, Path):
                raise TypeError("reviewed_catalog_path must be a Path or None")
            reviewed_catalog = self.reviewed_catalog_path.expanduser().resolve(strict=False)
            if not reviewed_catalog.is_file():
                raise ValueError("reviewed_catalog_path must be an existing file")
            if reviewed_catalog == self.output_root or self.output_root in reviewed_catalog.parents:
                raise ValueError("reviewed_catalog_path must be outside output_root")
            object.__setattr__(self, "reviewed_catalog_path", reviewed_catalog)
        if self.output_root == self.project_root or self.project_root in self.output_root.parents:
            raise ValueError("output_root must be outside project_root")
        if self.record_path == self.project_root or self.project_root in self.record_path.parents:
            raise ValueError("record_path must be outside project_root")
        if self.state_root == self.project_root or self.project_root in self.state_root.parents:
            raise ValueError("state_root must be outside project_root")
        if self.record_path == self.output_root or self.output_root in self.record_path.parents:
            raise ValueError("record_path must be outside output_root")
        fonts = tuple(self.font_paths)
        if any(not isinstance(path, Path) for path in fonts):
            raise TypeError("font_paths must contain Path values")
        object.__setattr__(
            self,
            "font_paths",
            tuple(path.expanduser().resolve(strict=False) for path in fonts),
        )
        if isinstance(self.font_probe_texts, (str, bytes)):
            raise TypeError("font_probe_texts must be a sequence of strings")
        probes = tuple(self.font_probe_texts)
        if any(not isinstance(text, str) or not text for text in probes):
            raise ValueError("font_probe_texts must contain non-empty strings")
        if probes and not fonts:
            raise ValueError("font probe texts require configured font_paths")
        object.__setattr__(self, "font_probe_texts", probes)
        if self.official_validator is not None and not isinstance(
            self.official_validator, OfficialValidatorConfig
        ):
            raise TypeError("official_validator must be an OfficialValidatorConfig or None")
        if self.runtime_smoke not in {"not_run", "passed", "failed"}:
            raise ValueError("runtime_smoke must be not_run, passed or failed")
        if self.runtime_smoke == "passed":
            if (
                not isinstance(self.runtime_smoke_reference, str)
                or _SAFE_TEXT_RE.fullmatch(self.runtime_smoke_reference) is None
            ):
                raise ValueError("a passed runtime smoke test requires a short reference")
        elif self.runtime_smoke_reference is not None:
            raise ValueError("runtime_smoke_reference is only allowed for a passed smoke test")
        if self.raster_manifest_path is not None:
            if not isinstance(self.raster_manifest_path, Path):
                raise TypeError("raster_manifest_path must be a Path or None")
            raster_manifest = self.raster_manifest_path.expanduser().resolve(strict=False)
            if not raster_manifest.is_file():
                raise ValueError("raster_manifest_path must be an existing file")
            object.__setattr__(self, "raster_manifest_path", raster_manifest)
        if self.nwjs_validator is not None:
            if not isinstance(self.nwjs_validator, NwjsRpgMakerValidatorConfig):
                raise TypeError(
                    "nwjs_validator must be an NwjsRpgMakerValidatorConfig or None"
                )
            if self.official_validator is not None:
                raise ValueError("nwjs_validator cannot be combined with official_validator")
            if self.runtime_smoke != "not_run":
                raise ValueError("nwjs_validator provides the runtime smoke result")
            if self.engine_id not in {"auto", "rpg_maker_mv", "rpg_maker_mz"}:
                raise ValueError("nwjs_validator requires an RPG Maker MV or MZ project")
            evidence = self.nwjs_validator.evidence_root
            for root, name in (
                (self.project_root, "project_root"),
                (self.output_root, "output_root"),
            ):
                if evidence == root or root in evidence.parents or evidence in root.parents:
                    raise ValueError(f"NW.js evidence root must be outside {name}")


@dataclass(frozen=True)
class ProjectValidationRecord:
    payload: dict[str, object]

    @property
    def conclusion(self) -> str:
        value = self.payload.get("conclusion")
        if not isinstance(value, str):
            raise ProjectValidationError("validation record has no conclusion")
        return value

    def to_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False, sort_keys=True))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _merge_reviewed_catalog(
    extracted: LocalizationCatalog,
    reviewed: LocalizationCatalog,
) -> LocalizationCatalog:
    for field_name in (
        "engine_id",
        "language",
        "source_language",
        "project_fingerprint",
        "files",
    ):
        if getattr(reviewed, field_name) != getattr(extracted, field_name):
            raise ProjectValidationError(
                f"reviewed catalog {field_name} does not match the fresh extraction"
            )

    reviewed_by_id = {entry.segment_id: entry for entry in reviewed.entries}
    extracted_ids = {entry.segment_id for entry in extracted.entries}
    if set(reviewed_by_id) != extracted_ids:
        raise ProjectValidationError(
            "reviewed catalog segment IDs do not match the fresh extraction"
        )

    merged_entries = []
    for entry in extracted.entries:
        reviewed_entry = reviewed_by_id[entry.segment_id]
        if reviewed_entry.source_hash != entry.source_hash:
            raise ProjectValidationError(
                f"reviewed catalog source hash does not match segment {entry.segment_id}"
            )
        merged_entries.append(replace(entry, target_text=reviewed_entry.target_text))
    return replace(extracted, entries=tuple(merged_entries))


def tree_sha256(root: Path) -> str:
    """Hash a complete regular-file tree without following symbolic links."""

    candidate = root.expanduser().absolute()
    current = Path(candidate.anchor)
    for part in candidate.parts:
        if part == candidate.anchor:
            continue
        current /= part
        if current.is_symlink():
            raise ProjectValidationError("validation does not accept symbolic links")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("root must be a directory")
    paths = sorted(
        resolved.rglob("*"),
        key=lambda item: (item.as_posix().casefold(), item.as_posix()),
    )
    digest = hashlib.sha256()
    for path in paths:
        if path.is_symlink():
            raise ProjectValidationError("validation does not accept symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(resolved).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256_file(path)))
        digest.update(b"\n")
    return digest.hexdigest()


def _tree_file_hashes(root: Path) -> dict[str, str]:
    resolved = root.expanduser().resolve(strict=True)
    return {
        path.relative_to(resolved).as_posix(): _sha256_file(path)
        for path in resolved.rglob("*")
        if path.is_file()
    }


def _adapter_payload(metadata: AdapterMetadata) -> dict[str, object]:
    return {
        "adapter_id": metadata.adapter_id,
        "adapter_version": metadata.adapter_version,
        "contract_version": metadata.contract_version,
        "engine_name": metadata.engine_name,
        "supported_engine_versions": list(metadata.supported_engine_versions),
        "maturity": metadata.maturity.value,
        "platforms": list(metadata.platforms),
        "capabilities": sorted(item.value for item in metadata.capabilities),
        "capability_matrix": metadata.capability_matrix.to_dict(),
        "known_limitations": list(metadata.known_limitations),
    }


def _detection_payload(detection: DetectionResult) -> dict[str, object]:
    return {
        "engine_name": detection.engine_name,
        "engine_version": detection.engine_version,
        "confidence": detection.confidence,
        "maturity": detection.maturity.value,
        "capabilities": sorted(item.value for item in detection.capabilities),
        "limitations": list(detection.limitations),
        "evidence": [
            {
                "code": item.code,
                "source": item.source.value,
                "value": item.value,
                "weight": item.weight,
                "description": item.description,
            }
            for item in detection.evidence
        ],
    }


def _route_payload(route) -> dict[str, object]:
    return {
        "phase": route.phase.value,
        "risk_before": route.risk_before.name,
        "risk_after": route.risk_after.name,
        "allowed_operations": sorted(item.value for item in route.allowed_operations),
        "blocked_operations": sorted(item.value for item in route.blocked_operations),
        "decision_reasons": list(route.decision_reasons),
    }


def _validation_payload(result: ValidationResult) -> dict[str, object]:
    return {
        "passed": result.valid,
        "blocking_issue_count": result.blocking_issue_count,
        "warning_count": result.warning_count,
        "issue_codes": [issue.code for issue in result.issues],
    }


def _verify_payload(result: VerifyResult) -> dict[str, object]:
    return {
        "passed": result.passed,
        "syntax_passed": result.syntax_passed,
        "encoding_passed": result.encoding_passed,
        "smoke_test_passed": result.smoke_test_passed,
        "artifact_hashes": dict(result.artifact_hashes),
        "check_codes": [item.code for item in result.checks],
        "issue_codes": [item.code for item in result.issues],
    }


def validate_font_coverage(
    font_paths: Iterable[Path], translated_texts: Iterable[str]
) -> dict[str, object]:
    """Use fontTools cmap tables to verify that a configured font set covers translated text."""

    paths = tuple(font_paths)
    codepoints = sorted(
        {
            ord(character)
            for text in translated_texts
            for character in text
            if not character.isspace() and ord(character) >= 0x20
        }
    )
    if not paths:
        return {
            "status": "not_configured",
            "fonts": [],
            "required_codepoints": [f"U+{item:04X}" for item in codepoints],
        }
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return {
            "status": "failed",
            "fonts": [],
            "required_codepoints": [f"U+{item:04X}" for item in codepoints],
            "failure": "fonttools_unavailable",
        }
    fonts = []
    coverage: set[int] = set()
    try:
        for path in paths:
            resolved = path.resolve(strict=True)
            if not resolved.is_file() or resolved.suffix.casefold() not in {".otf", ".ttf"}:
                raise ValueError("font must be an existing .ttf or .otf file")
            fonts.append({"name": resolved.name, "sha256": _sha256_file(resolved)})
            font = TTFont(str(resolved), lazy=True)
            try:
                for table in font["cmap"].tables:
                    if table.isUnicode():
                        coverage.update(table.cmap)
            finally:
                font.close()
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        return {
            "status": "failed",
            "fonts": fonts,
            "required_codepoints": [f"U+{item:04X}" for item in codepoints],
            "failure": type(exc).__name__,
        }
    missing = [item for item in codepoints if item not in coverage]
    return {
        "status": "passed" if not missing else "failed",
        "fonts": fonts,
        "required_codepoints": [f"U+{item:04X}" for item in codepoints],
        "missing_codepoints": [f"U+{item:04X}" for item in missing],
    }


def run_official_validator(
    config: OfficialValidatorConfig | None, output_root: Path
) -> dict[str, object]:
    if config is None:
        return {"status": "not_configured"}
    try:
        with tempfile.TemporaryDirectory(
            prefix="hanengine-validator-", dir=output_root.parent
        ) as temporary:
            shadow_root = Path(temporary) / "candidate"
            shutil.copytree(output_root, shadow_root)
            before = _tree_file_hashes(shadow_root)
            arguments = tuple(
                str(shadow_root) if argument == _OUTPUT_PLACEHOLDER else argument
                for argument in config.arguments
            )
            completed = None
            for _ in range(config.clean_passes):
                completed = subprocess.run(
                    [str(config.command), *arguments],
                    cwd=shadow_root,
                    capture_output=True,
                    check=False,
                    timeout=config.timeout_seconds,
                    text=False,
                )
                if completed.returncode != 0:
                    break
            assert completed is not None
            final_output = (completed.stdout + b"\n" + completed.stderr).decode(
                "utf-8", errors="replace"
            )
            reported_failure_markers = [
                marker for marker in config.failure_markers if marker in final_output
            ]
            after = _tree_file_hashes(shadow_root)
            modified_paths = sorted(
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path)
            )
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "kind": config.kind,
            "tool": config.command.name,
            "failure": "timeout",
        }
    except OSError as exc:
        return {
            "status": "failed",
            "kind": config.kind,
            "tool": config.command.name,
            "failure": type(exc).__name__,
        }
    return {
        "status": (
            "passed"
            if completed.returncode == 0 and not reported_failure_markers
            else "failed"
        ),
        "kind": config.kind,
        "tool": config.command.name,
        "exit_code": completed.returncode,
        "passes_run": config.clean_passes,
        "reported_failure_markers": reported_failure_markers,
        "validator_tree_preserved": not modified_paths,
        "validator_modified_paths": modified_paths,
    }


def renpy_sdk_validator(
    renpy_sdk: Path, *, timeout_seconds: int = 120
) -> OfficialValidatorConfig:
    """Configure the Ren'Py launcher CLI as ``renpy <project> compile``."""

    return OfficialValidatorConfig(
        command=renpy_sdk,
        arguments=(_OUTPUT_PLACEHOLDER, "compile"),
        timeout_seconds=timeout_seconds,
        kind="renpy_sdk_compile",
    )


def godot_editor_validator(
    godot_executable: Path, *, timeout_seconds: int = 300
) -> OfficialValidatorConfig:
    """Configure a cold import followed by a clean Godot editor validation pass."""

    return OfficialValidatorConfig(
        command=godot_executable,
        arguments=("--headless", "--editor", "--path", _OUTPUT_PLACEHOLDER, "--quit"),
        timeout_seconds=timeout_seconds,
        kind="godot_headless_editor",
        clean_passes=2,
        failure_markers=("SCRIPT ERROR:", "FATAL ERROR:", "CRASH HANDLER:"),
    )


def _write_record(record: ProjectValidationRecord, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


class ProjectValidationRunner:
    """Run a full AdapterV1 localization workflow and persist portable evidence."""

    def run(self, request: ProjectValidationRequest) -> ProjectValidationRecord:
        source_before = tree_sha256(request.project_root)
        reviewed_catalog_evidence: dict[str, object] = {
            "configured": request.reviewed_catalog_path is not None,
        }
        if request.reviewed_catalog_path is not None:
            reviewed_catalog_evidence.update(
                {
                    "name": request.reviewed_catalog_path.name,
                    "sha256": _sha256_file(request.reviewed_catalog_path),
                }
            )
        raster_resources: dict[str, object] = {
            "configured": request.raster_manifest_path is not None,
        }
        if request.raster_manifest_path is not None:
            raster_resources.update(
                {
                    "manifest_name": request.raster_manifest_path.name,
                    "manifest_sha256": _sha256_file(request.raster_manifest_path),
                }
            )
        payload: dict[str, object] = {
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "record_id": request.record_id,
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "authorization": {"asserted": True, "reference": request.authorization_reference},
            "project": {"label": request.project_label, "source_tree_sha256": source_before},
            "requested_engine": request.engine_id,
            "environment": {
                "operating_system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python_implementation": platform.python_implementation(),
                "python_version": ".".join(str(item) for item in sys.version_info[:3]),
            },
            "workflow": {
                "operations": [
                    "detect",
                    "extract",
                    "translate",
                    "validate",
                    "build",
                    "verify",
                ],
                "source_language": request.source_language,
                "target_language": request.target_language,
            },
            "reviewed_catalog": reviewed_catalog_evidence,
            "raster_resources": raster_resources,
            "raster_verification": {
                "status": (
                    "not_run"
                    if request.raster_manifest_path is not None
                    else "not_configured"
                )
            },
            "runtime_validation": {
                "status": (
                    "not_run"
                    if request.nwjs_validator is not None
                    else "not_configured"
                )
            },
            "conclusion": "failed",
        }
        try:
            dictionary = DictionaryTranslationProvider(
                load_translation_dictionary(request.dictionary_path)
            )
            with StructuredWorkflowSession(
                request.project_root,
                engine_id=request.engine_id,
                target_language=request.target_language,
                source_language=request.source_language,
                state_root=request.state_root,
            ) as workflow:
                selection = workflow.detect()
                adapter = workflow.runtime.registry.get(selection.adapter_id)
                selected_engine = getattr(adapter, "engine_id", request.engine_id)
                extracted = workflow.extract()
                translation_catalog = extracted.catalog
                if request.reviewed_catalog_path is not None:
                    reviewed_payload = json.loads(
                        request.reviewed_catalog_path.read_text(encoding="utf-8")
                    )
                    reviewed_catalog = LocalizationCatalog.from_dict(reviewed_payload)
                    translation_catalog = _merge_reviewed_catalog(
                        extracted.catalog,
                        reviewed_catalog,
                    )
                    reviewed_catalog_evidence.update(
                        {
                            "matched_segment_count": len(translation_catalog.entries),
                            "target_segment_count": sum(
                                entry.target_text is not None
                                for entry in translation_catalog.entries
                            ),
                        }
                    )
                translated = workflow.translate(translation_catalog, dictionary)
                output_options: dict[str, object] = {}
                if selected_engine == "renpy" and request.font_paths:
                    output_options["renpy_font_paths"] = [
                        str(path) for path in request.font_paths
                    ]
                    if request.font_probe_texts:
                        output_options["renpy_font_probe_texts"] = list(
                            request.font_probe_texts
                        )
                elif selected_engine == "godot" and request.font_paths:
                    output_options["godot_font_paths"] = [
                        str(path) for path in request.font_paths
                    ]
                elif selected_engine in {"rpg_maker_mv", "rpg_maker_mz"} and request.font_paths:
                    output_options["rpg_maker_font_paths"] = [
                        str(path) for path in request.font_paths
                    ]
                if request.raster_manifest_path is not None:
                    output_options["raster_manifest"] = str(
                        request.raster_manifest_path
                    )
                built = workflow.build(
                    translated.catalog,
                    request.output_root,
                    output_options=output_options,
                )

            build_result = built.build_result
            verify_result = built.verify_result
            source_after = tree_sha256(request.project_root)
            output_before_validator = tree_sha256(request.output_root)
            if request.raster_manifest_path is None:
                raster_verification: dict[str, object] = {
                    "status": "not_configured"
                }
            else:
                raster_manifest = load_raster_manifest(request.raster_manifest_path)
                raster_report = verify_raster_manifest(
                    request.project_root,
                    request.output_root,
                    raster_manifest,
                    manifest_root=request.raster_manifest_path.parent,
                )
                raster_status = (
                    "failed"
                    if not raster_report.passed
                    else "manual_review"
                    if raster_report.issues
                    else "passed"
                )
                raster_verification = {
                    "status": raster_status,
                    **raster_report.to_dict(),
                }
                raster_resources.update(
                    {
                        "source_language": raster_manifest.source_language,
                        "target_language": raster_manifest.target_language,
                        "asset_count": len(raster_manifest.assets),
                        "segment_count": sum(
                            len(asset.segments) for asset in raster_manifest.assets
                        ),
                    }
                )
            if request.nwjs_validator is None:
                runtime_validation: dict[str, object] = {"status": "not_configured"}
                official = run_official_validator(
                    request.official_validator,
                    request.output_root,
                )
                runtime_smoke = {
                    "status": request.runtime_smoke,
                    "reference": request.runtime_smoke_reference,
                }
            else:
                if selected_engine not in {"rpg_maker_mv", "rpg_maker_mz"}:
                    raise ProjectValidationError(
                        "NW.js validation requires a detected RPG Maker MV or MZ project"
                    )
                runtime_manifest = (
                    raster_manifest
                    if request.raster_manifest_path is not None
                    else None
                )
                runtime_validation = run_nwjs_rpg_maker_validation(
                    request.nwjs_validator,
                    request.project_root,
                    request.output_root,
                    runtime_manifest,
                )
                report_sha256 = runtime_validation.get("report_sha256")
                runtime_status = (
                    "passed"
                    if runtime_validation.get("status") == "passed"
                    and isinstance(report_sha256, str)
                    and re.fullmatch(r"[0-9a-f]{64}", report_sha256) is not None
                    else "failed"
                )
                official = {
                    "status": runtime_status,
                    "kind": "nwjs_rpg_maker_runtime",
                    "command_name": request.nwjs_validator.executable.name,
                    "command_sha256": _sha256_file(
                        request.nwjs_validator.executable
                    ),
                    "report_sha256": report_sha256,
                    "approved_video_count": runtime_validation.get(
                        "approved_video_count"
                    ),
                    "approved_segment_count": runtime_validation.get(
                        "approved_segment_count"
                    ),
                }
                runtime_smoke = {
                    "status": runtime_status,
                    "reference": (
                        f"nwjs-report-sha256:{report_sha256}"
                        if runtime_status == "passed"
                        and isinstance(report_sha256, str)
                        else None
                    ),
                }
            output_after_validator = tree_sha256(request.output_root)
            source_after = tree_sha256(request.project_root)
            coverage_texts = tuple(
                entry.target_text or "" for entry in translated.catalog.entries
            ) + request.font_probe_texts
            font = validate_font_coverage(
                request.font_paths,
                coverage_texts,
            )
            if selected_engine == "godot" and request.font_paths:
                style_report = run_godot_style_hard_gate(
                    request.project_root,
                    request.output_root,
                    request.font_paths,
                )
                visual_style = {
                    "status": "passed" if style_report.passed else "failed",
                    **style_report.to_dict(),
                }
            elif selected_engine in {"rpg_maker_mv", "rpg_maker_mz"} and request.font_paths:
                style_report = run_rpg_maker_style_hard_gate(
                    request.project_root,
                    request.output_root,
                    selected_engine,
                    request.font_paths,
                )
                visual_style = {
                    "status": "passed" if style_report.passed else "failed",
                    **style_report.to_dict(),
                }
            else:
                visual_style = {"status": "not_applicable"}
            internal_passed = (
                verify_result.passed
                and source_before == source_after
                and built.validation.result.valid
                and translated.untranslated_count == 0
                and raster_verification["status"] != "failed"
            )
            attempted_failure = (
                official.get("status") == "failed"
                or font["status"] == "failed"
                or runtime_smoke["status"] == "failed"
                or visual_style["status"] == "failed"
                or raster_verification["status"] == "failed"
                or output_before_validator != output_after_validator
            )
            fully_verified = (
                internal_passed
                and official.get("status") == "passed"
                and runtime_smoke["status"] == "passed"
                and font["status"] == "passed"
                and output_before_validator == output_after_validator
                and visual_style["status"] in {"passed", "not_applicable"}
                and raster_verification["status"] in {"passed", "not_configured"}
            )
            conclusion = (
                "failed"
                if not internal_passed or attempted_failure
                else "verified" if fully_verified else "build_ready"
            )
            deviations = []
            if official.get("status") != "passed":
                deviations.append(f"official_validator_{official.get('status', 'unknown')}")
            if font["status"] != "passed":
                deviations.append(f"font_coverage_{font['status']}")
            if runtime_smoke["status"] != "passed":
                deviations.append(f"runtime_smoke_{runtime_smoke['status']}")
            if visual_style["status"] == "failed":
                deviations.append("visual_style_failed")
            if raster_verification["status"] == "manual_review":
                deviations.append("raster_manual_review_required")
            elif raster_verification["status"] == "failed":
                deviations.append("raster_verification_failed")
            if output_before_validator != output_after_validator:
                deviations.append("official_validator_modified_output")
            if translated.untranslated_count:
                deviations.append("translation_incomplete")
            payload.update(
                {
                    "adapter": _adapter_payload(adapter.metadata),
                    "detection": _detection_payload(selection.detection),
                    "hanguard": _route_payload(selection.final_route),
                    "resources": {
                        "supported_files": list(extracted.catalog.files),
                        "source_resource_fingerprint": extracted.catalog.project_fingerprint,
                        "segment_count": len(extracted.catalog.entries),
                    },
                    "tasks": {
                        "task_ids": [
                            selection.detection_task.task_id,
                            extracted.execution.task.task_id,
                            translated.task.task_id,
                            built.validation.task.task_id,
                            built.build.task.task_id,
                            built.verification.task.task_id,
                        ]
                    },
                    "translation": {
                        "translated_count": translated.translated_count,
                        "resumed_count": translated.resumed_count,
                        "catalog_count": translated.catalog_count,
                        "untranslated_count": translated.untranslated_count,
                    },
                    "build": _build_payload(build_result, output_before_validator),
                    "internal_verification": {
                        "source_tree_preserved": source_before == source_after,
                        "translation_complete": translated.untranslated_count == 0,
                        "translation_validation": _validation_payload(built.validation.result),
                        "candidate_verification": _verify_payload(verify_result),
                    },
                    "official_validator": {
                        **official,
                        "output_tree_preserved": output_before_validator == output_after_validator,
                        "output_tree_sha256_after": output_after_validator,
                    },
                    "font_coverage": font,
                    "visual_style": visual_style,
                    "raster_verification": raster_verification,
                    "runtime_validation": runtime_validation,
                    "runtime_smoke": runtime_smoke,
                    "known_deviations": deviations,
                    "conclusion": conclusion,
                }
            )
        except (StructuredValidationFailed, StructuredVerificationFailed) as exc:
            payload["failure"] = type(exc).__name__
        except Exception as exc:
            payload["failure"] = type(exc).__name__
        record = ProjectValidationRecord(payload)
        _write_record(record, request.record_path)
        return record


def _build_payload(
    result: BuildResult, output_tree_sha256: str
) -> dict[str, object]:
    return {
        "output_tree_sha256": output_tree_sha256,
        "candidate_fingerprint": result.candidate_fingerprint,
        "generated_files": list(result.generated_files),
        "manifest": [
            {
                "relative_path": entry.relative_path,
                "change_kind": entry.change_kind,
                "sha256": entry.sha256,
            }
            for entry in result.manifest
        ],
        "warnings": list(result.warnings),
    }


__all__ = [
    "OfficialValidatorConfig",
    "ProjectValidationError",
    "ProjectValidationRecord",
    "ProjectValidationRequest",
    "ProjectValidationRunner",
    "VALIDATION_SCHEMA_VERSION",
    "godot_editor_validator",
    "renpy_sdk_validator",
    "run_official_validator",
    "tree_sha256",
    "validate_font_coverage",
]
