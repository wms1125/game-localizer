from __future__ import annotations

import codecs
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from game_localizer.hanengine.multiengine import (
    LocalizationCatalog,
    LocalizationEntry,
    MultiEngineError,
    MultiEngineExtractor,
    MultiEngineWriter,
    extract_placeholders,
    validate_resource_syntax,
)
from game_localizer.hanengine.segments import (
    Segment,
    SegmentDraft,
    SourceLocation,
    segment_v2_metadata,
)
from game_localizer.hanengine.renpy import (
    RenPyCatalog,
    RenPyExtractor,
    RenPySegment,
    RenPyValidationError,
    RenPyWriter,
    renpy_language_identifier,
    renpy_project_files,
    validate_renpy_font_config_text,
    validate_renpy_placeholders,
    validate_renpy_language_activation_text,
    validate_renpy_translation_text,
)
from game_localizer.hanengine.tasks import TaskCancelled

from .contract import (
    CONTRACT_VERSION,
    AdapterCapability,
    AdapterError,
    AdapterErrorCode,
    AdapterMaturity,
    AdapterMetadata,
    BuildManifestEntry,
    BuildRequest,
    BuildResult,
    DetectionRequest,
    DetectionResult,
    Evidence,
    EvidenceSource,
    ExtractRequest,
    ExtractResult,
    IssueSeverity,
    Operation,
    RollbackRequest,
    RollbackResult,
    ValidationIssue,
    ValidationRequest,
    ValidationResult,
    VerificationCheck,
    VerifyRequest,
    VerifyResult,
)


_BUILD_CAPABILITIES = frozenset(
    {
        AdapterCapability.DETECT,
        AdapterCapability.EXTRACT,
        AdapterCapability.VALIDATE,
        AdapterCapability.BUILD,
        AdapterCapability.VERIFY,
    }
)
_DETECT_CAPABILITIES = frozenset({AdapterCapability.DETECT})
_COMMON_LIMITATIONS = (
    "Only authorized plaintext structured localization resources are supported",
    "Encrypted and packaged binary assets are detection-only",
    "Rollback is managed by HanEngine BackupManager",
)


def _is_untranslated_natural_language(source: str, target: str, language: str) -> bool:
    if not language.casefold().startswith("zh") or not target.strip():
        return False
    if source.strip() != target.strip() or re.search(r"[\u3400-\u9fff]", source):
        return False
    text = source.strip()
    if not re.search(r"[A-Za-z]{2}", text) or not re.search(r"\s", text):
        return False
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./:+-]*", text):
        return False
    return len(text) >= 8


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _candidate_fingerprint(manifest: tuple[BuildManifestEntry, ...]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(manifest, key=lambda item: item.relative_path):
        digest.update(entry.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _marker_text(path: Path) -> str:
    with path.open("rb") as stream:
        return stream.read(128 * 1024).decode("utf-8-sig", errors="replace")


def _safe_candidate_path(root: Path, relative_path: str) -> Path | None:
    path = root / Path(*relative_path.split("/"))
    try:
        path.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return None
    current = root
    for part in relative_path.split("/"):
        current = current / part
        if current.is_symlink():
            return None
    return path


def _copy_project_tree(source: Path, output: Path, context) -> None:
    for current, directories, files in os.walk(source, topdown=True, followlinks=False):
        context.checkpoint()
        current_path = Path(current)
        safe_directories = []
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                raise ValueError("project contains a symbolic link")
            safe_directories.append(name)
            (output / path.relative_to(source)).mkdir(parents=True, exist_ok=True)
        directories[:] = safe_directories
        for name in files:
            context.checkpoint()
            path = current_path / name
            if path.is_symlink():
                raise ValueError("project contains a symbolic link")
            destination = output / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


class StructuredAdapterV1:
    """AdapterV1 implementation shared by plaintext structured game resources."""

    engine_id = ""
    source_markers: tuple[tuple[str, str, float, str], ...] = ()
    metadata: AdapterMetadata

    def __init__(
        self,
        *,
        target_language: str = "zh-CN",
        source_language: str = "en",
    ) -> None:
        if not isinstance(target_language, str) or not target_language:
            raise ValueError("target_language must not be empty")
        if not isinstance(source_language, str) or not source_language:
            raise ValueError("source_language must not be empty")
        self.target_language = target_language
        self.source_language = source_language

    def _error(
        self,
        operation: Operation,
        code: AdapterErrorCode,
        message: str,
        *,
        recoverable: bool,
        cause: BaseException | None = None,
        relative_path: str | None = None,
    ) -> AdapterError:
        return AdapterError(
            code=code,
            operation=operation,
            message=message,
            recoverable=recoverable,
            relative_path=relative_path,
            details={"engine_id": self.engine_id},
            cause_type=None if cause is None else type(cause).__name__,
        )

    def _source_evidence(self, root: Path) -> tuple[Evidence, ...]:
        evidence = []
        for code, relative, weight, description in self.source_markers:
            path = root / Path(*relative.split("/"))
            if path.is_file() and not path.is_symlink():
                evidence.append(
                    Evidence(
                        code=code,
                        source=EvidenceSource.ENGINE_MARKER,
                        value=relative,
                        weight=weight,
                        description=description,
                    )
                )
        return tuple(evidence)

    def _packaged_evidence(self, root: Path) -> tuple[Evidence, ...]:
        return ()

    def _engine_version(self, root: Path, evidence: tuple[Evidence, ...]) -> str:
        return "unknown"

    def detect(self, request: DetectionRequest) -> DetectionResult | AdapterError:
        if not isinstance(request, DetectionRequest):
            raise TypeError("request must be a DetectionRequest")
        try:
            request.context.checkpoint()
            source_evidence = self._source_evidence(request.input_root)
            packaged_evidence = self._packaged_evidence(request.input_root)
            evidence = source_evidence + packaged_evidence
            request.context.progress(1, 1, current_item=self.engine_id)
            request.context.log(
                "structured engine detection completed",
                {"engine_id": self.engine_id, "matched": bool(evidence)},
            )
            if not evidence:
                return DetectionResult(
                    matched=False,
                    engine_name=None,
                    engine_version=None,
                    confidence=0.0,
                    evidence=(),
                    maturity=self.metadata.maturity,
                    capabilities=self.metadata.capabilities,
                    limitations=self.metadata.known_limitations,
                    recommended_operation=Operation.DETECT,
                )

            source_ready = bool(source_evidence)
            confidence = min(0.99, sum(item.weight for item in evidence))
            limitations = self.metadata.known_limitations
            if not source_ready:
                limitations = limitations + (
                    "This packaged build can only be identified; extraction and modification are disabled",
                )
            return DetectionResult(
                matched=True,
                engine_name=self.metadata.engine_name,
                engine_version=self._engine_version(request.input_root, evidence),
                confidence=confidence,
                evidence=evidence,
                maturity=(self.metadata.maturity if source_ready else AdapterMaturity.DETECT_ONLY),
                capabilities=(self.metadata.capabilities if source_ready else _DETECT_CAPABILITIES),
                limitations=limitations,
                recommended_operation=Operation.DETECT,
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.DETECT,
                AdapterErrorCode.CANCELLED,
                "Engine detection was cancelled",
                recoverable=True,
                cause=exc,
            )
        except OSError as exc:
            return self._error(
                Operation.DETECT,
                AdapterErrorCode.READ_FAILED,
                "Engine markers could not be read",
                recoverable=True,
                cause=exc,
            )

    def extract(self, request: ExtractRequest) -> ExtractResult | AdapterError:
        if not isinstance(request, ExtractRequest):
            raise TypeError("request must be an ExtractRequest")
        try:
            request.context.checkpoint()
            request.context.progress(0, None, current_item=self.engine_id)
            catalog = MultiEngineExtractor().extract(
                self.engine_id,
                request.source_root,
                language=self.target_language,
                source_language=self.source_language,
            )
            drafts = tuple(self._entry_to_draft(entry, catalog) for entry in catalog.entries)
            request.context.progress(len(drafts), len(drafts), current_item=self.engine_id)
            request.context.log(
                "structured resources extracted",
                {"engine_id": self.engine_id, "files": len(catalog.files), "segments": len(drafts)},
            )
            warnings = ()
            if request.filters:
                warnings = ("Extraction filters are not applied by this adapter version",)
                request.context.warning(warnings[0], {"engine_id": self.engine_id})
            return ExtractResult(
                segments=drafts,
                source_tree_fingerprint=catalog.project_fingerprint,
                read_files=catalog.files,
                skipped_files=(),
                warnings=warnings,
                statistics={"files": len(catalog.files), "segments": len(drafts)},
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.EXTRACT,
                AdapterErrorCode.CANCELLED,
                "Resource extraction was cancelled",
                recoverable=True,
                cause=exc,
            )
        except MultiEngineError as exc:
            message = str(exc).casefold()
            if "decode" in message:
                code = AdapterErrorCode.DECODE_FAILED
            elif "invalid" in message or "parse" in message or "markup" in message:
                code = AdapterErrorCode.PARSE_FAILED
            else:
                code = AdapterErrorCode.UNSUPPORTED_INPUT
            return self._error(
                Operation.EXTRACT,
                code,
                "No supported plaintext localization resources could be extracted",
                recoverable=False,
                cause=exc,
            )
        except (OSError, UnicodeError) as exc:
            return self._error(
                Operation.EXTRACT,
                AdapterErrorCode.READ_FAILED,
                "Plaintext localization resources could not be read",
                recoverable=True,
                cause=exc,
            )
        except (TypeError, ValueError) as exc:
            return self._error(
                Operation.EXTRACT,
                AdapterErrorCode.PARSE_FAILED,
                "Extracted localization metadata was invalid",
                recoverable=False,
                cause=exc,
            )

    def _entry_to_draft(
        self,
        entry: LocalizationEntry,
        catalog: LocalizationCatalog,
    ) -> SegmentDraft:
        placeholders = extract_placeholders(entry.source_text)
        metadata = {
            "engine_id": catalog.engine_id,
            "kind": entry.kind,
            "locator": entry.locator,
            "catalog_language": catalog.language,
            "catalog_files": list(catalog.files),
            "segment_v2": segment_v2_metadata(
                entry.source_text,
                placeholders,
                kind=entry.kind,
            ),
        }
        return SegmentDraft(
            segment_id=entry.segment_id,
            source_text=entry.source_text,
            source_language=catalog.source_language,
            speaker=None,
            context_before=(),
            context_after=(),
            placeholders=placeholders,
            tags=(catalog.engine_id, entry.kind),
            constraints=("preserve_placeholders",),
            source_location=SourceLocation(
                relative_path=entry.relative_path,
                logical_path=json.dumps(
                    entry.locator,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
            source_fingerprint=entry.source_hash,
            ocr_confidence=None,
            region_confidence=None,
            metadata=metadata,
        )

    @staticmethod
    def _issue(
        code: str,
        message: str,
        *,
        segment: Segment | None = None,
        severity: IssueSeverity = IssueSeverity.ERROR,
        suggested_action: str,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            severity=severity,
            segment_id=None if segment is None else segment.segment_id,
            source_location=None if segment is None else segment.source_location,
            message=message,
            automatically_recoverable=False,
            suggested_action=suggested_action,
        )

    def _translation_preserves_placeholders(self, source: str, target: str) -> bool:
        if self.engine_id == "renpy":
            try:
                validate_renpy_placeholders(source, target)
            except RenPyValidationError:
                return False
            return True
        return Counter(extract_placeholders(source)) == Counter(extract_placeholders(target))

    def validate(self, request: ValidationRequest) -> ValidationResult | AdapterError:
        if not isinstance(request, ValidationRequest):
            raise TypeError("request must be a ValidationRequest")
        try:
            request.context.checkpoint()
            issues: list[ValidationIssue] = []
            originals: dict[str, Segment] = {}
            translated: dict[str, Segment] = {}

            for segment in request.original_segments:
                if segment.segment_id in originals:
                    issues.append(
                        self._issue(
                            "duplicate_original_segment_id",
                            "The original catalog contains a duplicate segment ID",
                            segment=segment,
                            suggested_action="Re-extract the source catalog",
                        )
                    )
                else:
                    originals[segment.segment_id] = segment
            for segment in request.translated_segments:
                if segment.segment_id in translated:
                    issues.append(
                        self._issue(
                            "duplicate_translated_segment_id",
                            "The translated catalog contains a duplicate segment ID",
                            segment=segment,
                            suggested_action="Keep exactly one translation for this segment ID",
                        )
                    )
                else:
                    translated[segment.segment_id] = segment

            try:
                codecs.lookup(request.target_encoding)
                encoding_available = True
            except LookupError:
                encoding_available = False
                issues.append(
                    self._issue(
                        "unknown_target_encoding",
                        "The requested target encoding is not available",
                        suggested_action="Choose a supported target encoding such as UTF-8",
                    )
                )

            total = len(originals)
            for index, (segment_id, original) in enumerate(originals.items(), 1):
                request.context.checkpoint()
                candidate = translated.get(segment_id)
                if candidate is None:
                    issues.append(
                        self._issue(
                            "missing_translated_segment",
                            "A source segment has no matching translated segment",
                            segment=original,
                            suggested_action="Restore the missing translated segment",
                        )
                    )
                    request.context.progress(index, total, current_item=segment_id)
                    continue
                if candidate.source_fingerprint != original.source_fingerprint:
                    issues.append(
                        self._issue(
                            "source_fingerprint_mismatch",
                            "The translated segment does not match the extracted source fingerprint",
                            segment=candidate,
                            suggested_action="Re-extract and translate the current source segment",
                        )
                    )
                if candidate.source_text != original.source_text:
                    issues.append(
                        self._issue(
                            "source_text_changed",
                            "The translated segment changes the protected source text",
                            segment=candidate,
                            suggested_action="Restore the extracted source text",
                        )
                    )
                if candidate.source_location != original.source_location:
                    issues.append(
                        self._issue(
                            "source_location_changed",
                            "The translated segment changes its protected source location",
                            segment=candidate,
                            suggested_action="Restore the extracted source location",
                        )
                    )
                protected_metadata = ("engine_id", "kind", "locator", "catalog_files")
                if any(candidate.metadata.get(key) != original.metadata.get(key) for key in protected_metadata):
                    issues.append(
                        self._issue(
                            "source_metadata_changed",
                            "The translated segment changes protected engine metadata",
                            segment=candidate,
                            suggested_action="Restore metadata from the extracted segment",
                        )
                    )
                if candidate.target_text is None:
                    issues.append(
                        self._issue(
                            "missing_target_text",
                            "The translated segment has no target text",
                            segment=candidate,
                            suggested_action="Provide target text for this segment",
                        )
                    )
                else:
                    if not self._translation_preserves_placeholders(
                        original.source_text,
                        candidate.target_text,
                    ):
                        issues.append(
                            self._issue(
                                "placeholder_mismatch",
                                "The translation changes required placeholders",
                                segment=candidate,
                                suggested_action="Restore every source placeholder in the translation",
                            )
                        )
                    if encoding_available:
                        try:
                            candidate.target_text.encode(request.target_encoding)
                        except UnicodeEncodeError:
                            issues.append(
                                self._issue(
                                    "target_encoding_failed",
                                    "The translation cannot be represented in the target encoding",
                                    segment=candidate,
                                    suggested_action="Use UTF-8 or revise unsupported characters",
                                    )
                                )
                    if _is_untranslated_natural_language(
                        original.source_text,
                        candidate.target_text,
                        self.target_language,
                    ):
                        issues.append(
                            self._issue(
                                "untranslated_natural_language",
                                "The target text is identical to the English source and may remain untranslated",
                                segment=candidate,
                                severity=IssueSeverity.WARNING,
                                suggested_action="Review this entry and provide a natural-language translation",
                            )
                        )
                request.context.progress(index, total, current_item=segment_id)

            for segment_id in sorted(translated.keys() - originals.keys()):
                candidate = translated[segment_id]
                issues.append(
                    self._issue(
                        "unknown_translated_segment",
                        "The translated catalog contains a segment not present in the source catalog",
                        segment=candidate,
                        suggested_action="Remove the unknown translated segment",
                    )
                )

            blocking = sum(
                issue.severity in {IssueSeverity.ERROR, IssueSeverity.CRITICAL}
                for issue in issues
            )
            warnings = sum(issue.severity is IssueSeverity.WARNING for issue in issues)
            request.context.log(
                "structured translation validation completed",
                {"engine_id": self.engine_id, "issues": len(issues), "blocking": blocking},
            )
            return ValidationResult(
                valid=blocking == 0,
                issues=tuple(issues),
                automatic_fixes=(),
                blocking_issue_count=blocking,
                warning_count=warnings,
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.VALIDATE,
                AdapterErrorCode.CANCELLED,
                "Translation validation was cancelled",
                recoverable=True,
                cause=exc,
            )
        except (TypeError, ValueError) as exc:
            return self._error(
                Operation.VALIDATE,
                AdapterErrorCode.VALIDATION_FAILED,
                "Translation validation could not be completed",
                recoverable=False,
                cause=exc,
            )

    def build(self, request: BuildRequest) -> BuildResult | AdapterError:
        if not isinstance(request, BuildRequest):
            raise TypeError("request must be a BuildRequest")
        try:
            request.context.checkpoint()
            catalog = self._catalog_from_segments(request)
            request.context.progress(0, len(catalog.entries), current_item=self.engine_id)
            written = MultiEngineWriter().build(
                catalog,
                request.source_root,
                request.staging_root,
                allow_existing_empty=True,
            )
            manifest = tuple(
                BuildManifestEntry(
                    relative_path=relative,
                    change_kind="modified",
                    sha256=_sha256_file(request.staging_root / Path(*relative.split("/"))),
                )
                for relative in written.files_written
            )
            request.context.progress(
                written.entries_written,
                len(catalog.entries),
                current_item=self.engine_id,
            )
            request.context.log(
                "structured localization candidate built",
                {
                    "engine_id": self.engine_id,
                    "files": len(written.files_written),
                    "segments": written.entries_written,
                },
            )
            return BuildResult(
                generated_files=written.files_written,
                added_files=(),
                modified_files=written.files_written,
                deleted_files=(),
                manifest=manifest,
                artifacts=(),
                candidate_fingerprint=_candidate_fingerprint(manifest),
                warnings=(),
                statistics={
                    "files": len(written.files_written),
                    "segments": written.entries_written,
                },
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.BUILD,
                AdapterErrorCode.CANCELLED,
                "Candidate build was cancelled",
                recoverable=True,
                cause=exc,
            )
        except MultiEngineError as exc:
            return self._error(
                Operation.BUILD,
                AdapterErrorCode.BUILD_FAILED,
                "The plaintext localization candidate could not be built",
                recoverable=False,
                cause=exc,
            )
        except (OSError, TypeError, ValueError, KeyError) as exc:
            return self._error(
                Operation.BUILD,
                AdapterErrorCode.BUILD_FAILED,
                "The build request contains invalid or unavailable resources",
                recoverable=False,
                cause=exc,
            )

    def _catalog_from_segments(self, request: BuildRequest) -> LocalizationCatalog:
        if not request.validated_segments:
            raise MultiEngineError("no validated segments were provided")
        entries: list[LocalizationEntry] = []
        catalog_files: tuple[str, ...] | None = None
        source_languages: set[str] = set()
        target_languages: set[str] = set()

        for segment in request.validated_segments:
            request.context.checkpoint()
            if segment.metadata.get("engine_id") != self.engine_id:
                raise MultiEngineError("segment belongs to a different engine")
            relative = segment.source_location.relative_path
            kind = segment.metadata.get("kind")
            locator = segment.metadata.get("locator")
            raw_files = segment.metadata.get("catalog_files")
            if relative is None or not isinstance(kind, str) or not kind or not isinstance(locator, dict):
                raise MultiEngineError("segment has incomplete engine metadata")
            if segment.target_text is None:
                raise MultiEngineError("segment has no target text")
            if hashlib.sha256(segment.source_text.encode("utf-8")).hexdigest() != segment.source_fingerprint:
                raise MultiEngineError("segment source fingerprint is invalid")
            if Counter(extract_placeholders(segment.source_text)) != Counter(
                extract_placeholders(segment.target_text)
            ):
                raise MultiEngineError("translation changes placeholders")
            if raw_files is not None:
                if not isinstance(raw_files, list) or any(not isinstance(item, str) for item in raw_files):
                    raise MultiEngineError("catalog file metadata is invalid")
                current_files = tuple(raw_files)
                if catalog_files is None:
                    catalog_files = current_files
                elif catalog_files != current_files:
                    raise MultiEngineError("segments contain inconsistent catalog files")
            entries.append(
                LocalizationEntry(
                    segment_id=segment.segment_id,
                    relative_path=relative,
                    source_text=segment.source_text,
                    source_hash=segment.source_fingerprint,
                    kind=kind,
                    locator=locator,
                    target_text=segment.target_text,
                )
            )
            source_languages.add(segment.source_language)
            target_languages.add(segment.target_language)

        if len(source_languages) != 1 or len(target_languages) != 1:
            raise MultiEngineError("segments contain inconsistent languages")
        if catalog_files is None:
            catalog_files = tuple(sorted({entry.relative_path for entry in entries}))
        return LocalizationCatalog(
            engine_id=self.engine_id,
            language=next(iter(target_languages)),
            source_language=next(iter(source_languages)),
            project_fingerprint=request.source_tree_fingerprint,
            files=catalog_files,
            entries=tuple(entries),
        )

    def verify(self, request: VerifyRequest) -> VerifyResult | AdapterError:
        if not isinstance(request, VerifyRequest):
            raise TypeError("request must be a VerifyRequest")
        try:
            request.context.checkpoint()
            checks: list[VerificationCheck] = []
            issues: list[ValidationIssue] = []
            artifact_hashes: dict[str, str] = {}
            encoding_passed = True
            syntax_passed = True

            if not request.manifest:
                checks.append(
                    VerificationCheck("manifest_nonempty", False, "The build manifest is empty")
                )
                issues.append(
                    self._issue(
                        "empty_build_manifest",
                        "The candidate has no files to verify",
                        suggested_action="Build the localization candidate before verification",
                    )
                )

            for index, entry in enumerate(request.manifest, 1):
                request.context.checkpoint()
                path = _safe_candidate_path(request.staging_root, entry.relative_path)
                exists = path is not None and path.is_file()
                checks.append(
                    VerificationCheck(
                        f"file_exists:{entry.relative_path}",
                        exists,
                        ("Candidate file exists" if exists else "Candidate file is missing or unsafe"),
                    )
                )
                if not exists:
                    encoding_passed = False
                    syntax_passed = False
                    issues.append(
                        self._issue(
                            "candidate_file_missing",
                            "A manifest file is missing or resolves through an unsafe link",
                            segment=None,
                            suggested_action="Rebuild the candidate in a clean staging directory",
                        )
                    )
                    request.context.progress(index, len(request.manifest), current_item=entry.relative_path)
                    continue

                actual_hash = _sha256_file(path)
                artifact_hashes[entry.relative_path] = actual_hash
                hash_matches = actual_hash.casefold() == entry.sha256.casefold()
                checks.append(
                    VerificationCheck(
                        f"sha256:{entry.relative_path}",
                        hash_matches,
                        ("Candidate hash matches the manifest" if hash_matches else "Candidate hash differs from the manifest"),
                    )
                )
                if not hash_matches:
                    issues.append(
                        self._issue(
                            "candidate_hash_mismatch",
                            "A candidate file hash differs from the build manifest",
                            suggested_action="Discard and rebuild the candidate",
                        )
                    )

                try:
                    text = path.read_bytes().decode("utf-8-sig")
                    decoded = True
                except UnicodeDecodeError:
                    decoded = False
                    text = ""
                    encoding_passed = False
                    issues.append(
                        self._issue(
                            "candidate_encoding_invalid",
                            "A candidate resource is not valid UTF-8",
                            suggested_action="Rebuild the candidate using UTF-8 output",
                        )
                    )
                checks.append(
                    VerificationCheck(
                        f"utf8:{entry.relative_path}",
                        decoded,
                        ("Candidate resource is valid UTF-8" if decoded else "Candidate resource is not valid UTF-8"),
                    )
                )

                parsed = False
                if decoded:
                    try:
                        validate_resource_syntax(entry.relative_path, text)
                        parsed = True
                    except MultiEngineError:
                        syntax_passed = False
                        issues.append(
                            self._issue(
                                "candidate_syntax_invalid",
                                "A candidate resource does not parse as its declared format",
                                suggested_action="Discard and rebuild the candidate from the current source",
                            )
                        )
                else:
                    syntax_passed = False
                checks.append(
                    VerificationCheck(
                        f"syntax:{entry.relative_path}",
                        parsed,
                        ("Candidate resource syntax is valid" if parsed else "Candidate resource syntax is invalid"),
                    )
                )
                request.context.progress(index, len(request.manifest), current_item=entry.relative_path)

            passed = bool(request.manifest) and all(check.passed for check in checks)
            request.context.log(
                "structured localization candidate verified",
                {"engine_id": self.engine_id, "passed": passed, "files": len(request.manifest)},
            )
            return VerifyResult(
                passed=passed,
                checks=tuple(checks),
                syntax_passed=syntax_passed and bool(request.manifest),
                encoding_passed=encoding_passed and bool(request.manifest),
                artifact_hashes=artifact_hashes,
                smoke_test_passed=None,
                issues=tuple(issues),
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.VERIFY,
                AdapterErrorCode.CANCELLED,
                "Candidate verification was cancelled",
                recoverable=True,
                cause=exc,
            )
        except (OSError, TypeError, ValueError) as exc:
            return self._error(
                Operation.VERIFY,
                AdapterErrorCode.VERIFY_FAILED,
                "Candidate verification could not be completed",
                recoverable=False,
                cause=exc,
            )

    def rollback(self, request: RollbackRequest) -> RollbackResult | AdapterError:
        if not isinstance(request, RollbackRequest):
            raise TypeError("request must be a RollbackRequest")
        return self._error(
            Operation.ROLLBACK,
            AdapterErrorCode.UNSUPPORTED_INPUT,
            "Rollback is managed by HanEngine BackupManager",
            recoverable=False,
        )


class RenPyAdapterV1(StructuredAdapterV1):
    engine_id = "renpy"
    metadata = AdapterMetadata(
        adapter_id="hanengine.renpy",
        contract_version=CONTRACT_VERSION,
        adapter_version="1.0.0",
        engine_name="Ren'Py",
        supported_engine_versions=("7.x plaintext projects", "8.x plaintext projects"),
        capabilities=_BUILD_CAPABILITIES,
        maturity=AdapterMaturity.BUILD_READY,
        platforms=("windows", "linux", "macos"),
        known_limitations=(
            "Only authorized plaintext .rpy source projects are supported",
            ".rpa archives and .rpyc compiled scripts are detection-only",
            "Build verification does not run the Ren'Py SDK compiler or the game runtime",
            "Rollback is managed by HanEngine BackupManager",
        ),
    )

    def _source_evidence(self, root: Path) -> tuple[Evidence, ...]:
        try:
            files = renpy_project_files(root)
        except ValueError:
            return ()
        if not files:
            return ()
        relative = files[0].relative_to(root).as_posix()
        return (
            Evidence(
                "renpy_source_script",
                EvidenceSource.ENGINE_MARKER,
                relative,
                0.90,
                "Ren'Py plaintext source script found",
            ),
        )

    def _packaged_evidence(self, root: Path) -> tuple[Evidence, ...]:
        candidates = tuple(
            sorted(
                (
                    path
                    for suffix in ("*.rpa", "*.rpyc")
                    for path in root.rglob(suffix)
                    if path.is_file() and not path.is_symlink()
                ),
                key=lambda path: path.as_posix().casefold(),
            )
        )
        if not candidates:
            return ()
        relative = candidates[0].relative_to(root).as_posix()
        return (
            Evidence(
                "renpy_packaged_resource",
                EvidenceSource.FILESYSTEM,
                relative,
                0.65,
                "Ren'Py archive or compiled script found",
            ),
        )

    def extract(self, request: ExtractRequest) -> ExtractResult | AdapterError:
        if not isinstance(request, ExtractRequest):
            raise TypeError("request must be an ExtractRequest")
        try:
            request.context.checkpoint()
            files = renpy_project_files(request.source_root)
            catalog = RenPyExtractor().extract(
                request.source_root,
                language=self.target_language,
            )
            if not files or not catalog.entries:
                raise ValueError("project contains no translatable plaintext Ren'Py statements")
            relative_files = tuple(path.relative_to(request.source_root).as_posix() for path in files)
            drafts = tuple(
                self._renpy_segment_to_draft(entry, relative_files)
                for entry in catalog.entries
            )
            warnings = ()
            if request.filters:
                warnings = ("Extraction filters are not applied by this adapter version",)
                request.context.warning(warnings[0], {"engine_id": self.engine_id})
            request.context.progress(len(drafts), len(drafts), current_item=self.engine_id)
            request.context.log(
                "Ren'Py plaintext resources extracted",
                {"engine_id": self.engine_id, "files": len(files), "segments": len(drafts)},
            )
            return ExtractResult(
                segments=drafts,
                source_tree_fingerprint=catalog.project_fingerprint,
                read_files=relative_files,
                skipped_files=(),
                warnings=warnings,
                statistics={"files": len(files), "segments": len(drafts)},
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.EXTRACT,
                AdapterErrorCode.CANCELLED,
                "Ren'Py extraction was cancelled",
                recoverable=True,
                cause=exc,
            )
        except UnicodeError as exc:
            return self._error(
                Operation.EXTRACT,
                AdapterErrorCode.DECODE_FAILED,
                "Ren'Py source scripts are not valid UTF-8",
                recoverable=False,
                cause=exc,
            )
        except OSError as exc:
            return self._error(
                Operation.EXTRACT,
                AdapterErrorCode.READ_FAILED,
                "Ren'Py source scripts could not be read",
                recoverable=True,
                cause=exc,
            )
        except (TypeError, ValueError) as exc:
            return self._error(
                Operation.EXTRACT,
                AdapterErrorCode.UNSUPPORTED_INPUT,
                "No supported plaintext Ren'Py statements could be extracted",
                recoverable=False,
                cause=exc,
            )

    def _renpy_segment_to_draft(
        self,
        entry: RenPySegment,
        catalog_files: tuple[str, ...],
    ) -> SegmentDraft:
        locator = {
            "type": "renpy",
            "line": entry.line,
            "kind": entry.kind,
            "speaker": entry.speaker,
        }
        placeholders = extract_placeholders(entry.source_text)
        metadata = {
            "engine_id": self.engine_id,
            "kind": entry.kind,
            "locator": locator,
            "catalog_language": self.target_language,
            "catalog_files": list(catalog_files),
            "segment_v2": segment_v2_metadata(
                entry.source_text,
                placeholders,
                text_tags=tuple(token for token in placeholders if token.startswith("{")),
                speaker=entry.speaker,
                kind=entry.kind,
                text_context=next(
                    (
                        token[2:-1]
                        for token in placeholders
                        if token.startswith("{#") and token.endswith("}") and len(token) > 3
                    ),
                    None,
                ),
            ),
        }
        return SegmentDraft(
            segment_id=entry.segment_id,
            source_text=entry.source_text,
            source_language=self.source_language,
            speaker=entry.speaker,
            context_before=(),
            context_after=(),
            placeholders=placeholders,
            tags=(self.engine_id, entry.kind),
            constraints=("preserve_placeholders", "preserve_renpy_text_tags"),
            source_location=SourceLocation(
                relative_path=entry.relative_path,
                logical_path=json.dumps(
                    locator,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                line=entry.line,
            ),
            source_fingerprint=entry.source_hash,
            ocr_confidence=None,
            region_confidence=None,
            metadata=metadata,
        )

    def build(self, request: BuildRequest) -> BuildResult | AdapterError:
        if not isinstance(request, BuildRequest):
            raise TypeError("request must be a BuildRequest")
        try:
            request.context.checkpoint()
            catalog = self._renpy_catalog_from_segments(request)
            output = request.staging_root
            existing_empty = False
            if output.exists():
                if (
                    output.is_symlink()
                    or not output.is_dir()
                    or next(output.iterdir(), None) is not None
                ):
                    raise ValueError("output root already exists and is not empty")
                existing_empty = True
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent))
            ).resolve()
            removed_placeholder = False
            try:
                _copy_project_tree(request.source_root, temporary, request.context)
                configured_fonts = request.output_options.get("renpy_font_paths", [])
                if not isinstance(configured_fonts, list) or any(
                    not isinstance(path, str) or not path for path in configured_fonts
                ):
                    raise ValueError("renpy_font_paths must be a list of non-empty strings")
                written = RenPyWriter().build(
                    catalog,
                    temporary,
                    source_root=request.source_root,
                    font_paths=tuple(Path(path) for path in configured_fonts),
                )
                relative_paths = tuple(
                    path.relative_to(temporary).as_posix()
                    for path in written.generated_paths
                )
                change_kinds = tuple(
                    (
                        "modified"
                        if (request.source_root / Path(*relative.split("/"))).is_file()
                        else "added"
                    )
                    for relative in relative_paths
                )
                if existing_empty:
                    output.rmdir()
                    removed_placeholder = True
                temporary.replace(output)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                if removed_placeholder and not output.exists():
                    output.mkdir()
                raise

            manifest = tuple(
                BuildManifestEntry(
                    relative_path=relative,
                    change_kind=change_kind,
                    sha256=_sha256_file(output / Path(*relative.split("/"))),
                )
                for relative, change_kind in zip(relative_paths, change_kinds)
            )
            request.context.progress(
                written.entries_written,
                len(catalog.entries),
                current_item=relative_paths[0],
            )
            request.context.log(
                "Ren'Py localization candidate built",
                {
                    "engine_id": self.engine_id,
                    "files": len(relative_paths),
                    "segments": written.entries_written,
                },
            )
            return BuildResult(
                generated_files=relative_paths,
                added_files=tuple(
                    relative
                    for relative, change_kind in zip(relative_paths, change_kinds)
                    if change_kind == "added"
                ),
                modified_files=tuple(
                    relative
                    for relative, change_kind in zip(relative_paths, change_kinds)
                    if change_kind == "modified"
                ),
                deleted_files=(),
                manifest=manifest,
                artifacts=(),
                candidate_fingerprint=_candidate_fingerprint(manifest),
                warnings=(
                    "Ren'Py SDK compilation and runtime smoke testing were not performed",
                ),
                statistics={"files": len(relative_paths), "segments": written.entries_written},
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.BUILD,
                AdapterErrorCode.CANCELLED,
                "Ren'Py candidate build was cancelled",
                recoverable=True,
                cause=exc,
            )
        except (OSError, UnicodeError, TypeError, ValueError, RenPyValidationError) as exc:
            return self._error(
                Operation.BUILD,
                AdapterErrorCode.BUILD_FAILED,
                "The Ren'Py localization candidate could not be built",
                recoverable=False,
                cause=exc,
            )

    def _renpy_catalog_from_segments(self, request: BuildRequest) -> RenPyCatalog:
        if not request.validated_segments:
            raise ValueError("no validated Ren'Py segments were provided")
        entries = []
        target_languages = set()
        for segment in request.validated_segments:
            request.context.checkpoint()
            if segment.metadata.get("engine_id") != self.engine_id:
                raise ValueError("segment belongs to a different engine")
            locator = segment.metadata.get("locator")
            kind = segment.metadata.get("kind")
            relative = segment.source_location.relative_path
            if (
                not isinstance(locator, dict)
                or locator.get("type") != "renpy"
                or not isinstance(kind, str)
                or relative is None
            ):
                raise ValueError("segment has incomplete Ren'Py metadata")
            line = locator.get("line")
            speaker = locator.get("speaker")
            if isinstance(line, bool) or not isinstance(line, int) or line < 1:
                raise ValueError("segment has an invalid Ren'Py source line")
            if speaker is not None and not isinstance(speaker, str):
                raise ValueError("segment has an invalid Ren'Py speaker")
            if segment.target_text is None:
                raise ValueError("segment has no target text")
            if hashlib.sha256(segment.source_text.encode("utf-8")).hexdigest() != segment.source_fingerprint:
                raise ValueError("segment source fingerprint is invalid")
            if not self._translation_preserves_placeholders(
                segment.source_text,
                segment.target_text,
            ):
                raise ValueError("translation changes Ren'Py placeholders")
            entries.append(
                RenPySegment(
                    segment_id=segment.segment_id,
                    relative_path=relative,
                    line=line,
                    kind=kind,
                    source_text=segment.source_text,
                    source_hash=segment.source_fingerprint,
                    placeholders=extract_placeholders(segment.source_text),
                    speaker=speaker,
                    target_text=segment.target_text,
                )
            )
            target_languages.add(segment.target_language)
        if len(target_languages) != 1:
            raise ValueError("segments contain inconsistent target languages")
        return RenPyCatalog(
            language=next(iter(target_languages)),
            project_fingerprint=request.source_tree_fingerprint,
            entries=tuple(entries),
        )

    def verify(self, request: VerifyRequest) -> VerifyResult | AdapterError:
        if not isinstance(request, VerifyRequest):
            raise TypeError("request must be a VerifyRequest")
        try:
            request.context.checkpoint()
            checks = []
            issues = []
            artifact_hashes = {}
            encoding_passed = True
            syntax_passed = True

            language = renpy_language_identifier(self.target_language)
            translation_path = f"game/tl/{language}/hanengine_translations.rpy"
            activation_path = "game/hanengine_language.rpy"
            manifest_paths = [entry.relative_path for entry in request.manifest]
            font_paths = sorted(
                path
                for path in manifest_paths
                if path.startswith("game/hanengine_fonts/")
                and Path(path).suffix.casefold() in {".ttf", ".otf"}
            )
            font_config_path = "game/hanengine_fonts.rpy"
            expected_paths = {translation_path, activation_path, *font_paths}
            if font_paths:
                expected_paths.add(font_config_path)
            manifest_complete = (
                len(manifest_paths) == len(expected_paths)
                and set(manifest_paths) == expected_paths
            )
            checks.append(
                VerificationCheck(
                    "renpy_generated_manifest",
                    manifest_complete,
                    (
                        "Manifest contains the translation, language activation, and configured font files"
                        if manifest_complete
                        else "Manifest does not contain exactly the required Ren'Py generated and font files"
                    ),
                )
            )
            if not manifest_complete:
                issues.append(
                    self._issue(
                        "renpy_generated_manifest_incomplete",
                        "The candidate manifest must contain the translation, language activation, and configured font files",
                        suggested_action="Discard and rebuild the candidate",
                    )
                )

            if not request.manifest:
                checks.append(
                    VerificationCheck("manifest_nonempty", False, "The build manifest is empty")
                )
                issues.append(
                    self._issue(
                        "empty_build_manifest",
                        "The candidate has no Ren'Py translation file to verify",
                        suggested_action="Build the localization candidate before verification",
                    )
                )

            for index, entry in enumerate(request.manifest, 1):
                request.context.checkpoint()
                expected_location = entry.relative_path in expected_paths
                checks.append(
                    VerificationCheck(
                        f"renpy_output_path:{entry.relative_path}",
                        expected_location,
                        (
                            "Generated file is in its expected Ren'Py location"
                            if expected_location
                            else "Generated file is outside the expected Ren'Py locations"
                        ),
                    )
                )
                path = _safe_candidate_path(request.staging_root, entry.relative_path)
                exists = path is not None and path.is_file()
                checks.append(
                    VerificationCheck(
                        f"file_exists:{entry.relative_path}",
                        exists,
                        "Candidate file exists" if exists else "Candidate file is missing or unsafe",
                    )
                )
                if not expected_location or not exists:
                    syntax_passed = False
                    encoding_passed = encoding_passed and exists
                    issues.append(
                        self._issue(
                            "renpy_candidate_file_invalid",
                            "A Ren'Py candidate file is missing or outside the expected output locations",
                            suggested_action="Discard and rebuild the candidate in a clean output directory",
                        )
                    )
                    request.context.progress(index, len(request.manifest), current_item=entry.relative_path)
                    continue

                actual_hash = _sha256_file(path)
                artifact_hashes[entry.relative_path] = actual_hash
                hash_matches = actual_hash.casefold() == entry.sha256.casefold()
                checks.append(
                    VerificationCheck(
                        f"sha256:{entry.relative_path}",
                        hash_matches,
                        "Candidate hash matches the manifest" if hash_matches else "Candidate hash differs from the manifest",
                    )
                )
                if not hash_matches:
                    issues.append(
                        self._issue(
                            "candidate_hash_mismatch",
                            "A generated Ren'Py file hash differs from the build manifest",
                            suggested_action="Discard and rebuild the candidate",
                        )
                    )

                if entry.relative_path in font_paths:
                    supported = path.suffix.casefold() in {".ttf", ".otf"}
                    checks.append(
                        VerificationCheck(
                            f"font_binary:{entry.relative_path}",
                            supported,
                            "Shipped font has a supported extension"
                            if supported
                            else "Shipped font has an unsupported extension",
                        )
                    )
                    if not supported:
                        syntax_passed = False
                        issues.append(
                            self._issue(
                                "renpy_font_file_invalid",
                                "A shipped Ren'Py font does not have a supported font extension",
                                suggested_action="Discard and rebuild the candidate with .ttf or .otf fonts",
                            )
                        )
                    request.context.progress(index, len(request.manifest), current_item=entry.relative_path)
                    continue

                try:
                    text = path.read_bytes().decode("utf-8-sig")
                    decoded = True
                except UnicodeDecodeError:
                    text = ""
                    decoded = False
                    encoding_passed = False
                checks.append(
                    VerificationCheck(
                        f"utf8:{entry.relative_path}",
                        decoded,
                        "Candidate is valid UTF-8" if decoded else "Candidate is not valid UTF-8",
                    )
                )
                parsed = False
                if decoded:
                    try:
                        if entry.relative_path == translation_path:
                            validate_renpy_translation_text(text)
                        elif entry.relative_path == font_config_path:
                            validate_renpy_font_config_text(
                                text,
                                expected_language=language,
                            )
                        else:
                            validate_renpy_language_activation_text(
                                text,
                                expected_language=language,
                            )
                        parsed = True
                    except RenPyValidationError:
                        syntax_passed = False
                else:
                    syntax_passed = False
                checks.append(
                    VerificationCheck(
                        f"renpy_syntax:{entry.relative_path}",
                        parsed,
                        "Generated Ren'Py structure is valid" if parsed else "Generated Ren'Py structure is invalid",
                    )
                )
                if not decoded or not parsed:
                    issues.append(
                        self._issue(
                            "renpy_translation_syntax_invalid",
                            "A generated Ren'Py file failed UTF-8 or structure validation",
                            suggested_action="Discard and rebuild the candidate",
                        )
                    )
                request.context.progress(index, len(request.manifest), current_item=entry.relative_path)

            copied_fingerprint = RenPyExtractor().extract(
                request.staging_root,
                language=self.target_language,
            ).project_fingerprint
            source_matches = copied_fingerprint == request.source_tree_fingerprint
            checks.append(
                VerificationCheck(
                    "source_tree_fingerprint",
                    source_matches,
                    "Copied source scripts match extraction" if source_matches else "Copied source scripts changed after extraction",
                )
            )
            if not source_matches:
                issues.append(
                    self._issue(
                        "source_tree_fingerprint_mismatch",
                        "The copied Ren'Py source scripts do not match the extracted project",
                        suggested_action="Discard and rebuild from the current source project",
                    )
                )
                syntax_passed = False

            passed = bool(request.manifest) and all(check.passed for check in checks)
            request.context.log(
                "Ren'Py localization candidate verified",
                {"engine_id": self.engine_id, "passed": passed, "files": len(request.manifest)},
            )
            return VerifyResult(
                passed=passed,
                checks=tuple(checks),
                syntax_passed=syntax_passed and bool(request.manifest),
                encoding_passed=encoding_passed and bool(request.manifest),
                artifact_hashes=artifact_hashes,
                smoke_test_passed=None,
                issues=tuple(issues),
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.VERIFY,
                AdapterErrorCode.CANCELLED,
                "Ren'Py candidate verification was cancelled",
                recoverable=True,
                cause=exc,
            )
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            return self._error(
                Operation.VERIFY,
                AdapterErrorCode.VERIFY_FAILED,
                "The Ren'Py localization candidate could not be verified",
                recoverable=False,
                cause=exc,
            )


class RpgMakerMVAdapterV1(StructuredAdapterV1):
    engine_id = "rpg_maker_mv"
    source_markers = (
        ("rpg_maker_mv_project", "game.rpgproject", 0.70, "RPG Maker MV project marker found"),
        ("rpg_maker_mv_core", "js/rpg_core.js", 0.25, "RPG Maker MV core script found"),
        ("rpg_maker_mv_www_core", "www/js/rpg_core.js", 0.25, "RPG Maker MV deployed core script found"),
    )
    metadata = AdapterMetadata(
        adapter_id="hanengine.rpg-maker-mv",
        contract_version=CONTRACT_VERSION,
        adapter_version="1.0.0",
        engine_name="RPG Maker MV",
        supported_engine_versions=("1.x",),
        capabilities=_BUILD_CAPABILITIES,
        maturity=AdapterMaturity.BUILD_READY,
        platforms=("windows", "linux", "macos"),
        known_limitations=_COMMON_LIMITATIONS,
    )

    def _engine_version(self, root: Path, evidence: tuple[Evidence, ...]) -> str:
        for relative in ("js/rpg_core.js", "www/js/rpg_core.js"):
            path = root / Path(*relative.split("/"))
            if path.is_file() and not path.is_symlink():
                match = re.search(r"RPGMAKER_VERSION\s*=\s*['\"]([^'\"]+)", _marker_text(path))
                if match:
                    return match.group(1)
        return "MV"


class RpgMakerMZAdapterV1(StructuredAdapterV1):
    engine_id = "rpg_maker_mz"
    source_markers = (
        ("rpg_maker_mz_project", "game.rmmzproject", 0.70, "RPG Maker MZ project marker found"),
        ("rpg_maker_mz_core", "js/rmmz_core.js", 0.25, "RPG Maker MZ core script found"),
        ("rpg_maker_mz_www_core", "www/js/rmmz_core.js", 0.25, "RPG Maker MZ deployed core script found"),
    )
    metadata = AdapterMetadata(
        adapter_id="hanengine.rpg-maker-mz",
        contract_version=CONTRACT_VERSION,
        adapter_version="1.0.0",
        engine_name="RPG Maker MZ",
        supported_engine_versions=("1.x",),
        capabilities=_BUILD_CAPABILITIES,
        maturity=AdapterMaturity.BUILD_READY,
        platforms=("windows", "linux", "macos"),
        known_limitations=_COMMON_LIMITATIONS,
    )

    def _engine_version(self, root: Path, evidence: tuple[Evidence, ...]) -> str:
        for relative in ("js/rmmz_core.js", "www/js/rmmz_core.js"):
            path = root / Path(*relative.split("/"))
            if path.is_file() and not path.is_symlink():
                match = re.search(r"RPGMAKER_VERSION\s*=\s*['\"]([^'\"]+)", _marker_text(path))
                if match:
                    return match.group(1)
        return "MZ"


class GodotAdapterV1(StructuredAdapterV1):
    engine_id = "godot"
    source_markers = (
        ("godot_project", "project.godot", 0.90, "Godot project marker found"),
    )
    metadata = AdapterMetadata(
        adapter_id="hanengine.godot",
        contract_version=CONTRACT_VERSION,
        adapter_version="1.0.0",
        engine_name="Godot",
        supported_engine_versions=("3.x", "4.x"),
        capabilities=_BUILD_CAPABILITIES,
        maturity=AdapterMaturity.BUILD_READY,
        platforms=("windows", "linux", "macos"),
        known_limitations=_COMMON_LIMITATIONS,
    )

    def _packaged_evidence(self, root: Path) -> tuple[Evidence, ...]:
        packs = sorted(
            (path for path in root.glob("*.pck") if path.is_file() and not path.is_symlink()),
            key=lambda path: path.name.casefold(),
        )
        if not packs:
            return ()
        return (
            Evidence("godot_pack", EvidenceSource.FILESYSTEM, packs[0].name, 0.65, "Godot PCK package found"),
        )

    def _engine_version(self, root: Path, evidence: tuple[Evidence, ...]) -> str:
        path = root / "project.godot"
        if path.is_file() and not path.is_symlink():
            match = re.search(r"(?m)^config_version\s*=\s*(\d+)", _marker_text(path))
            if match:
                version = int(match.group(1))
                return "4.x" if version >= 5 else "3.x"
        return "unknown"


class UnityAdapterV1(StructuredAdapterV1):
    engine_id = "unity"
    source_markers = (
        ("unity_version", "ProjectSettings/ProjectVersion.txt", 0.55, "Unity project version marker found"),
        ("unity_packages", "Packages/manifest.json", 0.35, "Unity package manifest found"),
    )
    metadata = AdapterMetadata(
        adapter_id="hanengine.unity",
        contract_version=CONTRACT_VERSION,
        adapter_version="1.0.0",
        engine_name="Unity",
        supported_engine_versions=("2019.4+",),
        capabilities=_BUILD_CAPABILITIES,
        maturity=AdapterMaturity.BUILD_READY,
        platforms=("windows", "linux", "macos"),
        known_limitations=_COMMON_LIMITATIONS,
    )

    def _packaged_evidence(self, root: Path) -> tuple[Evidence, ...]:
        player = root / "UnityPlayer.dll"
        data_dirs = sorted(
            (path for path in root.glob("*_Data") if path.is_dir() and not path.is_symlink()),
            key=lambda path: path.name.casefold(),
        )
        evidence = []
        if player.is_file() and not player.is_symlink():
            evidence.append(Evidence("unity_player", EvidenceSource.FILESYSTEM, player.name, 0.55, "Unity player binary found"))
        if data_dirs:
            evidence.append(Evidence("unity_data", EvidenceSource.FILESYSTEM, data_dirs[0].name, 0.35, "Unity data directory found"))
        return tuple(evidence)

    def _engine_version(self, root: Path, evidence: tuple[Evidence, ...]) -> str:
        path = root / "ProjectSettings" / "ProjectVersion.txt"
        if path.is_file() and not path.is_symlink():
            match = re.search(r"(?m)^m_EditorVersion:\s*(\S+)", _marker_text(path))
            if match:
                return match.group(1)
        return "unknown"


class UnrealAdapterV1(StructuredAdapterV1):
    engine_id = "unreal"
    metadata = AdapterMetadata(
        adapter_id="hanengine.unreal",
        contract_version=CONTRACT_VERSION,
        adapter_version="1.0.0",
        engine_name="Unreal Engine",
        supported_engine_versions=("4.x", "5.x"),
        capabilities=_BUILD_CAPABILITIES,
        maturity=AdapterMaturity.BUILD_READY,
        platforms=("windows", "linux", "macos"),
        known_limitations=_COMMON_LIMITATIONS,
    )

    def _project_files(self, root: Path) -> tuple[Path, ...]:
        return tuple(
            sorted(
                (path for path in root.glob("*.uproject") if path.is_file() and not path.is_symlink()),
                key=lambda path: path.name.casefold(),
            )
        )

    def _source_evidence(self, root: Path) -> tuple[Evidence, ...]:
        projects = self._project_files(root)
        if not projects:
            return ()
        return (
            Evidence("unreal_project", EvidenceSource.PROJECT_MANIFEST, projects[0].name, 0.90, "Unreal project manifest found"),
        )

    def _packaged_evidence(self, root: Path) -> tuple[Evidence, ...]:
        candidates = []
        for directory in (root, root / "Content" / "Paks"):
            if directory.is_dir() and not directory.is_symlink():
                candidates.extend(
                    path
                    for suffix in ("*.pak", "*.ucas", "*.utoc")
                    for path in directory.glob(suffix)
                    if path.is_file() and not path.is_symlink()
                )
        if not candidates:
            return ()
        path = sorted(candidates, key=lambda item: item.as_posix().casefold())[0]
        relative = path.relative_to(root).as_posix()
        return (
            Evidence("unreal_container", EvidenceSource.FILESYSTEM, relative, 0.65, "Unreal packaged container found"),
        )

    def _engine_version(self, root: Path, evidence: tuple[Evidence, ...]) -> str:
        projects = self._project_files(root)
        if projects:
            try:
                payload = json.loads(_marker_text(projects[0]))
            except json.JSONDecodeError:
                return "unknown"
            association = payload.get("EngineAssociation") if isinstance(payload, dict) else None
            if isinstance(association, str) and association:
                return association
        return "unknown"


__all__ = [
    "GodotAdapterV1",
    "RenPyAdapterV1",
    "RpgMakerMVAdapterV1",
    "RpgMakerMZAdapterV1",
    "StructuredAdapterV1",
    "UnityAdapterV1",
    "UnrealAdapterV1",
]
