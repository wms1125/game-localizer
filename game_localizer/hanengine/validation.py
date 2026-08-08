from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
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
    target_language: str = "zh-CN"
    source_language: str = "en"
    font_paths: tuple[Path, ...] = ()
    official_validator: OfficialValidatorConfig | None = None
    runtime_smoke: Literal["not_run", "passed", "failed"] = "not_run"
    runtime_smoke_reference: str | None = None

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
    arguments = tuple(
        str(output_root) if argument == _OUTPUT_PLACEHOLDER else argument
        for argument in config.arguments
    )
    try:
        completed = subprocess.run(
            [str(config.command), *arguments],
            cwd=output_root,
            capture_output=True,
            check=False,
            timeout=config.timeout_seconds,
            text=False,
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
        "status": "passed" if completed.returncode == 0 else "failed",
        "kind": config.kind,
        "tool": config.command.name,
        "exit_code": completed.returncode,
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
                extracted = workflow.extract()
                translated = workflow.translate(extracted.catalog, dictionary)
                built = workflow.build(translated.catalog, request.output_root)

            build_result = built.build_result
            verify_result = built.verify_result
            source_after = tree_sha256(request.project_root)
            output_before_validator = tree_sha256(request.output_root)
            official = run_official_validator(request.official_validator, request.output_root)
            output_after_validator = tree_sha256(request.output_root)
            font = validate_font_coverage(
                request.font_paths,
                (entry.target_text or "" for entry in translated.catalog.entries),
            )
            runtime_smoke = {
                "status": request.runtime_smoke,
                "reference": request.runtime_smoke_reference,
            }
            internal_passed = (
                verify_result.passed
                and source_before == source_after
                and built.validation.result.valid
                and translated.untranslated_count == 0
            )
            attempted_failure = (
                official.get("status") == "failed"
                or font["status"] == "failed"
                or runtime_smoke["status"] == "failed"
                or output_before_validator != output_after_validator
            )
            fully_verified = (
                internal_passed
                and official.get("status") == "passed"
                and runtime_smoke["status"] == "passed"
                and font["status"] == "passed"
                and output_before_validator == output_after_validator
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
    "renpy_sdk_validator",
    "run_official_validator",
    "tree_sha256",
    "validate_font_coverage",
]
