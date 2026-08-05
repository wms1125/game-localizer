from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, TypeVar

from game_localizer.hanengine.routing import RiskLevel, RouteOperation, RoutePlan
from game_localizer.hanengine.segments import (
    JsonValue,
    Segment,
    SegmentDraft,
    SourceLocation,
    normalize_relative_path,
)
from game_localizer.hanengine.tasks import (
    Artifact,
    ArtifactKind,
    TaskContext,
    _copy_json_object,
)


CONTRACT_VERSION = "hanengine.adapter/v1"

EnumType = TypeVar("EnumType", bound=Enum)

_ADAPTER_ID_PATTERN = re.compile(
    r"[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+\Z"
)
_SEMVER_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_CAUSE_TYPE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?:api_key|authorization|secret|token|request_body|screenshot)\s*[:=]",
    re.IGNORECASE,
)
_DIAGNOSTIC_TEXT_MARKERS = ("chain_of_thought", "reasoning_trace", "traceback")


class AdapterMaturity(str, Enum):
    DETECT_ONLY = "detect_only"
    EXTRACT_READY = "extract_ready"
    BUILD_READY = "build_ready"
    VERIFIED = "verified"


class AdapterCapability(str, Enum):
    DETECT = "detect"
    EXTRACT = "extract"
    VALIDATE = "validate"
    BUILD = "build"
    VERIFY = "verify"
    ROLLBACK = "rollback"


class Operation(str, Enum):
    DETECT = "detect"
    EXTRACT = "extract"
    VALIDATE = "validate"
    BUILD = "build"
    VERIFY = "verify"
    ROLLBACK = "rollback"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EvidenceSource(str, Enum):
    FILESYSTEM = "filesystem"
    PROJECT_MANIFEST = "project_manifest"
    ENGINE_MARKER = "engine_marker"
    USER_DECLARATION = "user_declaration"
    HANGUARD_SIGNAL = "hanguard_signal"


class DeclaredMode(str, Enum):
    PLAYER = "player"
    STUDIO = "studio"


class AdapterErrorCode(str, Enum):
    UNSUPPORTED_INPUT = "UNSUPPORTED_INPUT"
    ENGINE_NOT_DETECTED = "ENGINE_NOT_DETECTED"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    RISK_POLICY_BLOCKED = "RISK_POLICY_BLOCKED"
    READ_FAILED = "READ_FAILED"
    DECODE_FAILED = "DECODE_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    EXTRACT_PARTIAL = "EXTRACT_PARTIAL"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    STAGING_ESCAPE_BLOCKED = "STAGING_ESCAPE_BLOCKED"
    BUILD_FAILED = "BUILD_FAILED"
    VERIFY_FAILED = "VERIFY_FAILED"
    BACKUP_FAILED = "BACKUP_FAILED"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_ROUTE_TO_ADAPTER_OPERATION = {
    RouteOperation.DETECT: Operation.DETECT,
    RouteOperation.EXTRACT: Operation.EXTRACT,
    RouteOperation.VALIDATE: Operation.VALIDATE,
    RouteOperation.BUILD: Operation.BUILD,
    RouteOperation.VERIFY: Operation.VERIFY,
    RouteOperation.ROLLBACK: Operation.ROLLBACK,
}

_OPERATION_CAPABILITY = {
    Operation.DETECT: AdapterCapability.DETECT,
    Operation.EXTRACT: AdapterCapability.EXTRACT,
    Operation.VALIDATE: AdapterCapability.VALIDATE,
    Operation.BUILD: AdapterCapability.BUILD,
    Operation.VERIFY: AdapterCapability.VERIFY,
    Operation.ROLLBACK: AdapterCapability.ROLLBACK,
}

_MATURITY_CAPABILITIES = {
    AdapterMaturity.DETECT_ONLY: frozenset({AdapterCapability.DETECT}),
    AdapterMaturity.EXTRACT_READY: frozenset(
        {AdapterCapability.DETECT, AdapterCapability.EXTRACT}
    ),
    AdapterMaturity.BUILD_READY: frozenset(
        {
            AdapterCapability.DETECT,
            AdapterCapability.EXTRACT,
            AdapterCapability.VALIDATE,
            AdapterCapability.BUILD,
            AdapterCapability.VERIFY,
        }
    ),
    AdapterMaturity.VERIFIED: frozenset(AdapterCapability),
}


def adapter_operations_for_route(route: RoutePlan) -> frozenset[Operation]:
    if not isinstance(route, RoutePlan):
        raise TypeError("route must be a RoutePlan")
    return frozenset(
        _ROUTE_TO_ADAPTER_OPERATION[item]
        for item in route.allowed_operations
        if item in _ROUTE_TO_ADAPTER_OPERATION
    )


def _require_enum(value: object, enum_type: type[EnumType], field_name: str) -> EnumType:
    if not isinstance(value, enum_type):
        raise TypeError(f"{field_name} must be a {enum_type.__name__}")
    return value


def _plain_string(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    canonical = _copy_json_object({"value": value}, field_name)["value"]
    if type(canonical) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not allow_empty and not canonical:
        raise ValueError(f"{field_name} must not be empty")
    return canonical


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _plain_string(value, field_name)


def _sanitized_message(value: object) -> str:
    message = _plain_string(value, "message")
    folded = str.casefold(message)
    if _SENSITIVE_ASSIGNMENT_PATTERN.search(message) or any(
        marker in folded for marker in _DIAGNOSTIC_TEXT_MARKERS
    ):
        raise ValueError("message contains sensitive or diagnostic content")
    if any(ord(character) < 32 and character not in "\t" for character in message):
        raise ValueError("message contains control characters")
    return message


def _cause_type(value: object) -> str | None:
    if value is None:
        return None
    cause_type = _plain_string(value, "cause_type")
    if _CAUSE_TYPE_PATTERN.fullmatch(cause_type) is None:
        raise ValueError("cause_type must contain only an exception type name")
    return cause_type


def _require_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool")
    return value


def _require_integer(value: object, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return value


def _confidence(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be within [0.0, 1.0]")
    return number


def _ordered_items(value: object, field_name: str) -> tuple[object, ...]:
    if (
        isinstance(value, (str, bytes, Mapping, set, frozenset))
        or not isinstance(value, Iterable)
    ):
        raise TypeError(f"{field_name} must be an ordered iterable collection")
    return tuple(value)


def _typed_tuple(value: object, item_type: type, field_name: str) -> tuple:
    items = _ordered_items(value, field_name)
    if any(not isinstance(item, item_type) for item in items):
        raise TypeError(f"{field_name} must contain only {item_type.__name__} values")
    return items


def _string_tuple(
    value: object,
    field_name: str,
    *,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    items = _ordered_items(value, field_name)
    strings = tuple(_plain_string(item, field_name) for item in items)
    if require_nonempty and not strings:
        raise ValueError(f"{field_name} must not be empty")
    return strings


def _enum_frozenset(
    value: object,
    enum_type: type[EnumType],
    field_name: str,
) -> frozenset[EnumType]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        raise TypeError(f"{field_name} must be an iterable collection")
    items = tuple(value)
    if any(not isinstance(item, enum_type) for item in items):
        raise TypeError(f"{field_name} must contain only {enum_type.__name__} values")
    return frozenset(items)


def _path_tuple(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(
        normalize_relative_path(item)
        for item in _string_tuple(value, field_name)
    )


def _statistics(value: object, field_name: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a dictionary")
    snapshot: dict[str, int] = {}
    for key, item in value.items():
        canonical_key = _plain_string(key, field_name)
        if canonical_key in snapshot:
            raise ValueError(f"{field_name} contains duplicate keys")
        snapshot[canonical_key] = _require_integer(item, field_name)
    return snapshot


def _path_string_mapping(value: object, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a dictionary")
    snapshot: dict[str, str] = {}
    for key, item in value.items():
        normalized = normalize_relative_path(_plain_string(key, field_name))
        if normalized in snapshot:
            raise ValueError(f"{field_name} contains duplicate normalized paths")
        snapshot[normalized] = _plain_string(item, field_name)
    return snapshot


def _resolved_identity(path: Path) -> Path:
    return path.resolve(strict=False)


def _root_path(value: object, field_name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{field_name} must be a Path")
    if not value.is_absolute():
        raise ValueError(f"{field_name} must be absolute")
    resolved = _resolved_identity(value)
    if not isinstance(resolved, Path) or not resolved.is_absolute():
        raise ValueError(f"{field_name} has an invalid resolved identity")
    if value != resolved:
        raise ValueError(f"{field_name} must equal its resolved identity")
    return value


def _ensure_separate_roots(first: Path, second: Path, field_names: str) -> None:
    if first == second or first in second.parents or second in first.parents:
        raise ValueError(f"{field_names} must be distinct and non-containing")


def _ensure_child_within(root: Path, relative_path: str, field_name: str) -> None:
    child = _resolved_identity(root / relative_path)
    if not isinstance(child, Path):
        raise ValueError(f"{field_name} has an invalid resolved identity")
    try:
        child.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field_name} resolves to an escape outside its root") from exc


def _require_context(value: object) -> TaskContext:
    if not isinstance(value, TaskContext):
        raise TypeError("context must be a TaskContext")
    return value


def _validate_capability_gate(
    maturity: AdapterMaturity,
    capabilities: frozenset[AdapterCapability],
) -> None:
    missing = _MATURITY_CAPABILITIES[maturity] - capabilities
    if missing:
        raise ValueError("capabilities do not satisfy the declared maturity")


@dataclass(frozen=True)
class AdapterMetadata:
    adapter_id: str
    contract_version: str
    adapter_version: str
    engine_name: str
    supported_engine_versions: tuple[str, ...]
    capabilities: frozenset[AdapterCapability]
    maturity: AdapterMaturity
    platforms: tuple[str, ...]
    known_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        adapter_id = _plain_string(self.adapter_id, "adapter_id")
        if _ADAPTER_ID_PATTERN.fullmatch(adapter_id) is None:
            raise ValueError("adapter_id must be a lower-case reverse-domain identifier")
        object.__setattr__(self, "adapter_id", adapter_id)
        contract_version = _plain_string(self.contract_version, "contract_version")
        if contract_version != CONTRACT_VERSION:
            raise ValueError(f"contract_version must equal {CONTRACT_VERSION}")
        object.__setattr__(self, "contract_version", contract_version)
        adapter_version = _plain_string(self.adapter_version, "adapter_version")
        if _SEMVER_PATTERN.fullmatch(adapter_version) is None:
            raise ValueError("adapter_version must be a strict MAJOR.MINOR.PATCH version")
        object.__setattr__(self, "adapter_version", adapter_version)
        object.__setattr__(self, "engine_name", _plain_string(self.engine_name, "engine_name"))
        object.__setattr__(
            self,
            "supported_engine_versions",
            _string_tuple(
                self.supported_engine_versions,
                "supported_engine_versions",
                require_nonempty=True,
            ),
        )
        capabilities = _enum_frozenset(
            self.capabilities,
            AdapterCapability,
            "capabilities",
        )
        object.__setattr__(self, "capabilities", capabilities)
        maturity = _require_enum(self.maturity, AdapterMaturity, "maturity")
        _validate_capability_gate(maturity, capabilities)
        object.__setattr__(
            self,
            "platforms",
            _string_tuple(self.platforms, "platforms", require_nonempty=True),
        )
        object.__setattr__(
            self,
            "known_limitations",
            _string_tuple(self.known_limitations, "known_limitations"),
        )


@dataclass(frozen=True)
class Evidence:
    code: str
    source: EvidenceSource
    value: str
    weight: float
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _plain_string(self.code, "code"))
        _require_enum(self.source, EvidenceSource, "source")
        object.__setattr__(self, "value", _plain_string(self.value, "value"))
        object.__setattr__(self, "weight", _confidence(self.weight, "weight"))
        object.__setattr__(
            self,
            "description",
            _plain_string(self.description, "description"),
        )


@dataclass(frozen=True)
class AdapterError:
    code: AdapterErrorCode
    operation: Operation
    message: str
    recoverable: bool
    segment_id: str | None = None
    relative_path: str | None = None
    evidence: tuple[Evidence, ...] = ()
    details: dict[str, JsonValue] = field(default_factory=dict)
    cause_type: str | None = None

    def __post_init__(self) -> None:
        _require_enum(self.code, AdapterErrorCode, "code")
        _require_enum(self.operation, Operation, "operation")
        object.__setattr__(self, "message", _sanitized_message(self.message))
        _require_bool(self.recoverable, "recoverable")
        object.__setattr__(self, "segment_id", _optional_string(self.segment_id, "segment_id"))
        if self.relative_path is not None:
            object.__setattr__(
                self,
                "relative_path",
                normalize_relative_path(self.relative_path),
            )
        object.__setattr__(self, "evidence", _typed_tuple(self.evidence, Evidence, "evidence"))
        object.__setattr__(self, "details", _copy_json_object(self.details, "details"))
        object.__setattr__(self, "cause_type", _cause_type(self.cause_type))


@dataclass(frozen=True)
class DetectionRequest:
    input_root: Path
    declared_mode: DeclaredMode
    project_id: str
    risk_level: RiskLevel
    allowed_operations: frozenset[Operation]
    context: TaskContext

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_root", _root_path(self.input_root, "input_root"))
        _require_enum(self.declared_mode, DeclaredMode, "declared_mode")
        object.__setattr__(self, "project_id", _plain_string(self.project_id, "project_id"))
        _require_enum(self.risk_level, RiskLevel, "risk_level")
        operations = _enum_frozenset(self.allowed_operations, Operation, "allowed_operations")
        if operations != frozenset({Operation.DETECT}):
            raise ValueError("allowed_operations must equal exactly {Operation.DETECT}")
        object.__setattr__(self, "allowed_operations", operations)
        _require_context(self.context)


@dataclass(frozen=True)
class DetectionResult:
    matched: bool
    engine_name: str | None
    engine_version: str | None
    confidence: float
    evidence: tuple[Evidence, ...]
    maturity: AdapterMaturity
    capabilities: frozenset[AdapterCapability]
    limitations: tuple[str, ...]
    recommended_operation: Operation

    def __post_init__(self) -> None:
        _require_bool(self.matched, "matched")
        object.__setattr__(self, "engine_name", _optional_string(self.engine_name, "engine_name"))
        object.__setattr__(
            self,
            "engine_version",
            _optional_string(self.engine_version, "engine_version"),
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence, "confidence"))
        evidence = _typed_tuple(self.evidence, Evidence, "evidence")
        object.__setattr__(self, "evidence", evidence)
        maturity = _require_enum(self.maturity, AdapterMaturity, "maturity")
        capabilities = _enum_frozenset(
            self.capabilities,
            AdapterCapability,
            "capabilities",
        )
        _validate_capability_gate(maturity, capabilities)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "limitations", _string_tuple(self.limitations, "limitations"))
        operation = _require_enum(
            self.recommended_operation,
            Operation,
            "recommended_operation",
        )
        if _OPERATION_CAPABILITY[operation] not in capabilities:
            raise ValueError("recommended_operation requires the matching capability")
        if operation is not Operation.DETECT:
            raise ValueError(
                "recommended_operation must satisfy the detect request oracle"
            )
        if self.matched:
            if not evidence or self.engine_name is None or self.engine_version is None:
                raise ValueError("matched detection requires evidence and engine identity")
        elif evidence or self.engine_name is not None or self.engine_version is not None:
            raise ValueError("unmatched detection must not report evidence or engine identity")


@dataclass(frozen=True)
class ExtractRequest:
    source_root: Path
    working_root: Path
    candidate_encodings: tuple[str, ...]
    filters: tuple[str, ...]
    project_id: str
    context: TaskContext

    def __post_init__(self) -> None:
        source = _root_path(self.source_root, "source_root")
        working = _root_path(self.working_root, "working_root")
        _ensure_separate_roots(source, working, "source_root and working_root")
        object.__setattr__(self, "source_root", source)
        object.__setattr__(self, "working_root", working)
        object.__setattr__(
            self,
            "candidate_encodings",
            _string_tuple(self.candidate_encodings, "candidate_encodings"),
        )
        object.__setattr__(self, "filters", _string_tuple(self.filters, "filters"))
        object.__setattr__(self, "project_id", _plain_string(self.project_id, "project_id"))
        _require_context(self.context)


@dataclass(frozen=True)
class ExtractResult:
    segments: tuple[SegmentDraft, ...]
    source_tree_fingerprint: str
    read_files: tuple[str, ...]
    skipped_files: tuple[str, ...]
    warnings: tuple[str, ...]
    statistics: dict[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "segments", _typed_tuple(self.segments, SegmentDraft, "segments"))
        object.__setattr__(
            self,
            "source_tree_fingerprint",
            _plain_string(self.source_tree_fingerprint, "source_tree_fingerprint"),
        )
        object.__setattr__(self, "read_files", _path_tuple(self.read_files, "read_files"))
        object.__setattr__(self, "skipped_files", _path_tuple(self.skipped_files, "skipped_files"))
        object.__setattr__(self, "warnings", _string_tuple(self.warnings, "warnings"))
        object.__setattr__(self, "statistics", _statistics(self.statistics, "statistics"))


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: IssueSeverity
    segment_id: str | None
    source_location: SourceLocation | None
    message: str
    automatically_recoverable: bool
    suggested_action: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _plain_string(self.code, "code"))
        _require_enum(self.severity, IssueSeverity, "severity")
        object.__setattr__(self, "segment_id", _optional_string(self.segment_id, "segment_id"))
        if self.source_location is not None and not isinstance(self.source_location, SourceLocation):
            raise TypeError("source_location must be a SourceLocation or None")
        object.__setattr__(self, "message", _plain_string(self.message, "message"))
        _require_bool(self.automatically_recoverable, "automatically_recoverable")
        object.__setattr__(
            self,
            "suggested_action",
            _plain_string(self.suggested_action, "suggested_action"),
        )


@dataclass(frozen=True)
class ValidationRequest:
    source_tree_fingerprint: str
    original_segments: tuple[Segment, ...]
    translated_segments: tuple[Segment, ...]
    target_encoding: str
    project_rules: dict[str, JsonValue]
    context: TaskContext

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_tree_fingerprint",
            _plain_string(self.source_tree_fingerprint, "source_tree_fingerprint"),
        )
        object.__setattr__(
            self,
            "original_segments",
            _typed_tuple(self.original_segments, Segment, "original_segments"),
        )
        object.__setattr__(
            self,
            "translated_segments",
            _typed_tuple(self.translated_segments, Segment, "translated_segments"),
        )
        object.__setattr__(self, "target_encoding", _plain_string(self.target_encoding, "target_encoding"))
        object.__setattr__(self, "project_rules", _copy_json_object(self.project_rules, "project_rules"))
        _require_context(self.context)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    automatic_fixes: tuple[str, ...]
    blocking_issue_count: int
    warning_count: int

    def __post_init__(self) -> None:
        _require_bool(self.valid, "valid")
        object.__setattr__(self, "issues", _typed_tuple(self.issues, ValidationIssue, "issues"))
        object.__setattr__(
            self,
            "automatic_fixes",
            _string_tuple(self.automatic_fixes, "automatic_fixes"),
        )
        object.__setattr__(
            self,
            "blocking_issue_count",
            _require_integer(self.blocking_issue_count, "blocking_issue_count"),
        )
        object.__setattr__(
            self,
            "warning_count",
            _require_integer(self.warning_count, "warning_count"),
        )


@dataclass(frozen=True)
class BuildRequest:
    source_root: Path
    staging_root: Path
    validated_segments: tuple[Segment, ...]
    source_tree_fingerprint: str
    output_options: dict[str, JsonValue]
    context: TaskContext

    def __post_init__(self) -> None:
        source = _root_path(self.source_root, "source_root")
        staging = _root_path(self.staging_root, "staging_root")
        _ensure_separate_roots(source, staging, "source_root and staging_root")
        segments = _typed_tuple(self.validated_segments, Segment, "validated_segments")
        for segment in segments:
            relative_path = segment.source_location.relative_path
            if relative_path is not None:
                _ensure_child_within(source, relative_path, "validated segment path")
        object.__setattr__(self, "source_root", source)
        object.__setattr__(self, "staging_root", staging)
        object.__setattr__(self, "validated_segments", segments)
        object.__setattr__(
            self,
            "source_tree_fingerprint",
            _plain_string(self.source_tree_fingerprint, "source_tree_fingerprint"),
        )
        object.__setattr__(self, "output_options", _copy_json_object(self.output_options, "output_options"))
        _require_context(self.context)


@dataclass(frozen=True)
class BuildManifestEntry:
    relative_path: str
    change_kind: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_path", normalize_relative_path(self.relative_path))
        object.__setattr__(self, "change_kind", _plain_string(self.change_kind, "change_kind"))
        object.__setattr__(self, "sha256", _plain_string(self.sha256, "sha256"))


@dataclass(frozen=True)
class BuildResult:
    generated_files: tuple[str, ...]
    added_files: tuple[str, ...]
    modified_files: tuple[str, ...]
    deleted_files: tuple[str, ...]
    manifest: tuple[BuildManifestEntry, ...]
    artifacts: tuple[Artifact, ...]
    candidate_fingerprint: str
    warnings: tuple[str, ...]
    statistics: dict[str, int]

    def __post_init__(self) -> None:
        for field_name in ("generated_files", "added_files", "modified_files", "deleted_files"):
            object.__setattr__(self, field_name, _path_tuple(getattr(self, field_name), field_name))
        object.__setattr__(self, "manifest", _typed_tuple(self.manifest, BuildManifestEntry, "manifest"))
        object.__setattr__(self, "artifacts", _typed_tuple(self.artifacts, Artifact, "artifacts"))
        object.__setattr__(
            self,
            "candidate_fingerprint",
            _plain_string(self.candidate_fingerprint, "candidate_fingerprint"),
        )
        object.__setattr__(self, "warnings", _string_tuple(self.warnings, "warnings"))
        object.__setattr__(self, "statistics", _statistics(self.statistics, "statistics"))


@dataclass(frozen=True)
class VerifyRequest:
    source_tree_fingerprint: str
    staging_root: Path
    manifest: tuple[BuildManifestEntry, ...]
    verification_level: str
    context: TaskContext

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_tree_fingerprint",
            _plain_string(self.source_tree_fingerprint, "source_tree_fingerprint"),
        )
        staging = _root_path(self.staging_root, "staging_root")
        manifest = _typed_tuple(self.manifest, BuildManifestEntry, "manifest")
        for entry in manifest:
            _ensure_child_within(staging, entry.relative_path, "manifest relative_path")
        object.__setattr__(self, "staging_root", staging)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(
            self,
            "verification_level",
            _plain_string(self.verification_level, "verification_level"),
        )
        _require_context(self.context)


@dataclass(frozen=True)
class VerificationCheck:
    code: str
    passed: bool
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _plain_string(self.code, "code"))
        _require_bool(self.passed, "passed")
        object.__setattr__(self, "message", _plain_string(self.message, "message"))


@dataclass(frozen=True)
class VerifyResult:
    passed: bool
    checks: tuple[VerificationCheck, ...]
    syntax_passed: bool
    encoding_passed: bool
    artifact_hashes: dict[str, str]
    smoke_test_passed: bool | None
    issues: tuple[ValidationIssue, ...]

    def __post_init__(self) -> None:
        _require_bool(self.passed, "passed")
        object.__setattr__(self, "checks", _typed_tuple(self.checks, VerificationCheck, "checks"))
        _require_bool(self.syntax_passed, "syntax_passed")
        _require_bool(self.encoding_passed, "encoding_passed")
        object.__setattr__(self, "artifact_hashes", _path_string_mapping(self.artifact_hashes, "artifact_hashes"))
        if self.smoke_test_passed is not None:
            _require_bool(self.smoke_test_passed, "smoke_test_passed")
        object.__setattr__(self, "issues", _typed_tuple(self.issues, ValidationIssue, "issues"))


@dataclass(frozen=True)
class RollbackRequest:
    project_id: str
    install_manifest: tuple[BuildManifestEntry, ...]
    backup_manifest: tuple[BuildManifestEntry, ...]
    target_root: Path
    expected_original_hashes: dict[str, str]
    context: TaskContext

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _plain_string(self.project_id, "project_id"))
        install = _typed_tuple(self.install_manifest, BuildManifestEntry, "install_manifest")
        backup = _typed_tuple(self.backup_manifest, BuildManifestEntry, "backup_manifest")
        target = _root_path(self.target_root, "target_root")
        hashes = _path_string_mapping(self.expected_original_hashes, "expected_original_hashes")
        for entry in (*install, *backup):
            _ensure_child_within(target, entry.relative_path, "rollback manifest relative_path")
        for relative_path in hashes:
            _ensure_child_within(target, relative_path, "expected_original_hashes path")
        object.__setattr__(self, "install_manifest", install)
        object.__setattr__(self, "backup_manifest", backup)
        object.__setattr__(self, "target_root", target)
        object.__setattr__(self, "expected_original_hashes", hashes)
        _require_context(self.context)


@dataclass(frozen=True)
class RollbackResult:
    restored_files: tuple[str, ...]
    unchanged_files: tuple[str, ...]
    failed_files: tuple[str, ...]
    hash_verification_passed: bool
    issues: tuple[ValidationIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "restored_files", _path_tuple(self.restored_files, "restored_files"))
        object.__setattr__(self, "unchanged_files", _path_tuple(self.unchanged_files, "unchanged_files"))
        object.__setattr__(self, "failed_files", _path_tuple(self.failed_files, "failed_files"))
        _require_bool(self.hash_verification_passed, "hash_verification_passed")
        object.__setattr__(self, "issues", _typed_tuple(self.issues, ValidationIssue, "issues"))


class AdapterV1(Protocol):
    metadata: AdapterMetadata

    def detect(self, request: DetectionRequest) -> DetectionResult | AdapterError: ...
    def extract(self, request: ExtractRequest) -> ExtractResult | AdapterError: ...
    def validate(self, request: ValidationRequest) -> ValidationResult | AdapterError: ...
    def build(self, request: BuildRequest) -> BuildResult | AdapterError: ...
    def verify(self, request: VerifyRequest) -> VerifyResult | AdapterError: ...
    def rollback(self, request: RollbackRequest) -> RollbackResult | AdapterError: ...


__all__ = [
    "AdapterCapability",
    "AdapterError",
    "AdapterErrorCode",
    "AdapterMaturity",
    "AdapterMetadata",
    "AdapterV1",
    "ArtifactKind",
    "BuildManifestEntry",
    "BuildRequest",
    "BuildResult",
    "DeclaredMode",
    "DetectionRequest",
    "DetectionResult",
    "Evidence",
    "EvidenceSource",
    "ExtractRequest",
    "ExtractResult",
    "IssueSeverity",
    "Operation",
    "RollbackRequest",
    "RollbackResult",
    "ValidationIssue",
    "ValidationRequest",
    "ValidationResult",
    "VerificationCheck",
    "VerifyRequest",
    "VerifyResult",
    "adapter_operations_for_route",
]
