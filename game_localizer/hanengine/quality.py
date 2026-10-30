from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from collections.abc import Mapping
from typing import TYPE_CHECKING

from game_localizer.adapters.contract import ExtractResult, ValidationResult, VerifyResult
from game_localizer.hanengine.multiengine import LocalizationCatalog, extract_placeholders

if TYPE_CHECKING:
    from game_localizer.hanengine.pipeline import PipelineTranslationOutcome
    from game_localizer.structured_workflow import StructuredBuildOutcome


QUALITY_REPORT_SCHEMA_VERSION = "hanengine.quality-report/v1"
REVIEW_QUEUE_SCHEMA_VERSION = "hanengine.translation-review/v1"


def _issue_payload(issue) -> dict[str, object]:
    location = issue.source_location
    return {
        "code": issue.code,
        "severity": issue.severity.value,
        "segment_id": issue.segment_id,
        "relative_path": None if location is None else location.relative_path,
        "message": issue.message,
        "automatically_recoverable": issue.automatically_recoverable,
        "suggested_action": issue.suggested_action,
    }


def _translation_summary(
    catalog: LocalizationCatalog,
    translation: PipelineTranslationOutcome | None,
) -> dict[str, object]:
    target_count = sum(entry.target_text is not None for entry in catalog.entries)
    untranslated_count = len(catalog.entries) - target_count
    if translation is None:
        return {
            "catalog_count": len(catalog.entries),
            "translated_count": target_count,
            "resumed_count": 0,
            "catalog_target_count": target_count,
            "untranslated_count": untranslated_count,
            "complete": untranslated_count == 0,
        }
    return {
        "catalog_count": translation.catalog_count,
        "translated_count": translation.translated_count,
        "resumed_count": translation.resumed_count,
        "catalog_target_count": translation.catalog_count,
        "untranslated_count": translation.untranslated_count,
        "complete": translation.untranslated_count == 0,
    }


def _translation_quality_summary(
    translation: PipelineTranslationOutcome | None,
    partial_segments=(),
) -> dict[str, object]:
    counts = {"error": 0, "warning": 0}
    codes: dict[str, int] = {}
    segments = translation.segments if translation is not None else tuple(partial_segments)
    for segment in segments:
        quality = segment.metadata.get("translation_quality")
        if not isinstance(quality, list):
            continue
        for issue in quality:
            if not isinstance(issue, Mapping):
                continue
            severity = issue.get("severity")
            code = issue.get("code")
            if severity in counts:
                counts[severity] += 1
            if isinstance(code, str) and code:
                codes[code] = codes.get(code, 0) + 1
    return {
        "error_count": counts["error"],
        "warning_count": counts["warning"],
        "codes": dict(sorted(codes.items())),
    }


def build_translation_review_queue(
    catalog: LocalizationCatalog,
    *,
    translation: PipelineTranslationOutcome | None = None,
    partial_segments=(),
    translation_failure: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return actionable entries that should be reviewed before candidate delivery."""

    if not isinstance(catalog, LocalizationCatalog):
        raise TypeError("catalog must be a LocalizationCatalog")
    segment_by_id = {}
    if translation is not None:
        segment_by_id = {segment.segment_id: segment for segment in translation.segments}
    else:
        segment_by_id = {segment.segment_id: segment for segment in partial_segments}
    items: list[dict[str, object]] = []
    for entry in catalog.entries:
        target = entry.target_text
        reasons: list[str] = []
        if target is None:
            reasons.append("missing_translation")
        else:
            if target.strip() == entry.source_text.strip() and re.search(r"[A-Za-z]", target):
                reasons.append("source_text_unchanged")
            if extract_placeholders(entry.source_text) != extract_placeholders(target):
                reasons.append("placeholder_mismatch")
            if tuple(re.findall(r"\r\n|\r|\n", entry.source_text)) != tuple(
                re.findall(r"\r\n|\r|\n", target)
            ):
                reasons.append("physical_newline_mismatch")
            if re.search(
                r"(?i)(?:^|[\[{(\s])(?:segment_id|source_language|target_language|protected_tokens|context)\s*[:=]",
                target,
            ):
                reasons.append("metadata_contamination")
        segment = segment_by_id.get(entry.segment_id)
        if segment is not None:
            metadata = segment.metadata.get("translation")
            if isinstance(metadata, Mapping):
                confidence = metadata.get("confidence")
                if isinstance(confidence, (int, float)) and confidence < 0.45:
                    reasons.append("low_confidence")
            failure = segment.metadata.get("translation_failure")
            if isinstance(failure, Mapping):
                reasons.append("translation_failed")
            quality = segment.metadata.get("translation_quality")
            if isinstance(quality, list):
                for issue in quality:
                    if isinstance(issue, Mapping) and isinstance(issue.get("code"), str):
                        code = issue["code"]
                        if code not in reasons:
                            reasons.append(code)
        if reasons:
            item = {
                "segment_id": entry.segment_id,
                "relative_path": entry.relative_path,
                "source_text": entry.source_text,
                "target_text": target,
                "reasons": reasons,
            }
            if segment is not None:
                failure = segment.metadata.get("translation_failure")
                if isinstance(failure, Mapping):
                    item["failure"] = dict(failure)
            items.append(item)
    if translation_failure:
        failure_id = translation_failure.get("segment_id")
        if isinstance(failure_id, str):
            existing = next((item for item in items if item["segment_id"] == failure_id), None)
            if existing is not None:
                existing["failure"] = dict(translation_failure)
                if "translation_failed" not in existing["reasons"]:
                    existing["reasons"].append("translation_failed")
            else:
                entry = next((item for item in catalog.entries if item.segment_id == failure_id), None)
                if entry is not None:
                    items.append(
                        {
                            "segment_id": entry.segment_id,
                            "relative_path": entry.relative_path,
                            "source_text": entry.source_text,
                            "target_text": entry.target_text,
                            "reasons": ["translation_failed"],
                            "failure": dict(translation_failure),
                        }
                    )
    return {
        "schema_version": REVIEW_QUEUE_SCHEMA_VERSION,
        "count": len(items),
        "items": items,
    }


def build_quality_report(
    *,
    catalog: LocalizationCatalog,
    engine_id: str,
    source_language: str,
    target_language: str,
    extract_result: ExtractResult | None = None,
    translation: PipelineTranslationOutcome | None = None,
    partial_segments=(),
    build_outcome: StructuredBuildOutcome | None = None,
    validation_result: ValidationResult | None = None,
    translation_failure: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Create a portable quality summary from an existing workflow execution."""

    if not isinstance(catalog, LocalizationCatalog):
        raise TypeError("catalog must be a LocalizationCatalog")
    if not isinstance(engine_id, str) or not engine_id:
        raise ValueError("engine_id must not be empty")
    if not isinstance(source_language, str) or not source_language:
        raise ValueError("source_language must not be empty")
    if not isinstance(target_language, str) or not target_language:
        raise ValueError("target_language must not be empty")
    if extract_result is not None and not isinstance(extract_result, ExtractResult):
        raise TypeError("extract_result must be an ExtractResult or None")
    if validation_result is not None and not isinstance(validation_result, ValidationResult):
        raise TypeError("validation_result must be a ValidationResult or None")
    if build_outcome is not None and validation_result is not None:
        raise ValueError("build_outcome and validation_result cannot both be provided")
    if translation_failure is not None and not isinstance(translation_failure, Mapping):
        raise TypeError("translation_failure must be a mapping or None")

    translation_summary = _translation_summary(catalog, translation)
    translation_quality = _translation_quality_summary(translation, partial_segments)
    extraction_warnings = () if extract_result is None else extract_result.warnings
    extraction_statistics = {} if extract_result is None else dict(extract_result.statistics)
    verify_result: VerifyResult | None = None
    build_result = None
    if build_outcome is not None:
        validation_result = build_outcome.validation.result
        verify_result = build_outcome.verify_result
        build_result = build_outcome.build_result

    validation_issues = () if validation_result is None else validation_result.issues
    verification_issues = () if verify_result is None else verify_result.issues
    build_warnings = () if build_result is None else build_result.warnings
    reasons: list[str] = []
    if translation_summary["untranslated_count"]:
        reasons.append("translation_incomplete")
    if translation_failure:
        reasons.append("translation_failed")
    if translation_quality["error_count"] or translation_quality["warning_count"]:
        reasons.append("translation_quality_issues")
    if extraction_warnings:
        reasons.append("extraction_warnings")
    if validation_result is not None and validation_result.warning_count:
        reasons.append("validation_warnings")
    if build_warnings:
        reasons.append("build_warnings")
    if verification_issues:
        reasons.append("verification_issues")
    failed = bool(
        validation_result is not None
        and not validation_result.valid
    ) or bool(verify_result is not None and not verify_result.passed)
    if translation_failure:
        failed = True
    if translation_quality["error_count"]:
        failed = True
    # An incomplete translation means the candidate still contains source text.
    # The CLI already refuses to treat that run as success, so the report must
    # agree with the exit code instead of downgrading it to a review hint.
    if translation_summary["untranslated_count"]:
        failed = True
    status = "failed" if failed else "review_required" if reasons else "passed"
    review_queue = build_translation_review_queue(
        catalog,
        translation=translation,
        partial_segments=partial_segments,
        translation_failure=translation_failure,
    )

    return {
        "schema_version": QUALITY_REPORT_SCHEMA_VERSION,
        "status": status,
        "engine_id": engine_id,
        "source_language": source_language,
        "target_language": target_language,
        "project_fingerprint": catalog.project_fingerprint,
        "source_files": list(catalog.files),
        "summary": {
            "segment_count": len(catalog.entries),
            "translated_count": translation_summary["translated_count"],
            "resumed_count": translation_summary["resumed_count"],
            "untranslated_count": translation_summary["untranslated_count"],
            "quality_error_count": translation_quality["error_count"],
            "quality_warning_count": translation_quality["warning_count"],
            "unhandled_count": extraction_statistics.get("unhandled_items", 0),
            "extraction_warning_count": len(extraction_warnings),
            "validation_issue_count": len(validation_issues),
            "validation_blocking_count": (
                0 if validation_result is None else validation_result.blocking_issue_count
            ),
            "validation_warning_count": (
                0 if validation_result is None else validation_result.warning_count
            ),
            "build_warning_count": len(build_warnings),
            "verification_issue_count": len(verification_issues),
        },
        "translation": translation_summary,
        "translation_quality": translation_quality,
        "translation_failure": None if translation_failure is None else dict(translation_failure),
        "extraction": {
            "statistics": extraction_statistics,
            "warnings": list(extraction_warnings),
        },
        "validation": {
            "valid": None if validation_result is None else validation_result.valid,
            "issues": [_issue_payload(issue) for issue in validation_issues],
        },
        "build": {
            "candidate_fingerprint": None if build_result is None else build_result.candidate_fingerprint,
            "generated_files": [] if build_result is None else list(build_result.generated_files),
            "statistics": {} if build_result is None else dict(build_result.statistics),
            "warnings": list(build_warnings),
        },
        "verification": {
            "passed": None if verify_result is None else verify_result.passed,
            "issues": [_issue_payload(issue) for issue in verification_issues],
            "checks": []
            if verify_result is None
            else [
                {"code": check.code, "passed": check.passed, "message": check.message}
                for check in verify_result.checks
            ],
        },
        "review": {
            "required": bool(reasons) or bool(review_queue["count"]),
            "reasons": reasons,
            "queue": review_queue,
        },
    }


def write_quality_report(report: dict[str, object], destination: Path) -> Path:
    if not isinstance(report, dict):
        raise TypeError("report must be a dictionary")
    if not isinstance(destination, Path):
        raise TypeError("destination must be a Path")
    target = destination.expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def write_translation_review_queue(queue: dict[str, object], destination: Path) -> Path:
    if not isinstance(queue, dict):
        raise TypeError("queue must be a dictionary")
    if not isinstance(destination, Path):
        raise TypeError("destination must be a Path")
    target = destination.expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(
            json.dumps(queue, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


__all__ = [
    "QUALITY_REPORT_SCHEMA_VERSION",
    "REVIEW_QUEUE_SCHEMA_VERSION",
    "build_translation_review_queue",
    "build_quality_report",
    "write_translation_review_queue",
    "write_quality_report",
]
