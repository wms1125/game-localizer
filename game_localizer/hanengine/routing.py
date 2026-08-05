from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import TypeAlias, TypeVar


JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
EnumType = TypeVar("EnumType", bound=Enum)


class RiskLevel(IntEnum):
    H0_PROJECT = 0
    H1_OFFLINE = 1
    H2_RESTRICTED = 2
    H3_PROTECTED = 3


class RoutePhase(str, Enum):
    PROVISIONAL = "provisional"
    FINAL = "final"


class EvaluationStatus(str, Enum):
    COMPLETE = "complete"
    MISSING_EVIDENCE = "missing_evidence"
    UNKNOWN_RULE = "unknown_rule"
    EVALUATION_FAILED = "evaluation_failed"


class SignalType(str, Enum):
    USER_DECLARATION = "user_declaration"
    PATH = "path"
    MANIFEST_KEY = "manifest_key"
    PROCESS_NAME = "process_name"
    SERVICE_NAME = "service_name"
    CAPTURE_RESULT = "capture_result"


class RouteOperation(str, Enum):
    DETECT = "detect"
    EXTRACT = "extract"
    VALIDATE = "validate"
    BUILD = "build"
    VERIFY = "verify"
    ROLLBACK = "rollback"
    INSTALL_PATCH = "install_patch"
    CAPTURE = "capture"
    OCR = "ocr"
    VISUAL_REPLACE = "visual_replace"


_ALL_OPERATIONS = frozenset(RouteOperation)
_SAFE_EXTERNAL_OPERATIONS = frozenset(
    {
        RouteOperation.DETECT,
        RouteOperation.CAPTURE,
        RouteOperation.OCR,
        RouteOperation.VISUAL_REPLACE,
    }
)


def _require_mapping(value: object, model_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{model_name} payload must be a mapping")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: tuple[str, ...],
    model_name: str,
) -> None:
    actual = set(payload)
    required = set(expected)
    if actual != required:
        missing = sorted(required - actual)
        unknown = sorted(actual - required)
        raise ValueError(
            f"{model_name} payload fields do not match schema; "
            f"missing={missing}, unknown={unknown}"
        )


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


def _require_enum(value: object, enum_type: type[EnumType], field_name: str) -> EnumType:
    if not isinstance(value, enum_type):
        raise TypeError(f"{field_name} must be a {enum_type.__name__}")
    return value


def _enum_from_value(
    value: object,
    enum_type: type[EnumType],
    field_name: str,
) -> EnumType:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid {enum_type.__name__}") from exc


def _risk_from_name(value: object, field_name: str) -> RiskLevel:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    try:
        return RiskLevel[value]
    except KeyError as exc:
        raise ValueError(f"{field_name} is not a valid RiskLevel") from exc


def _iterable_items(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        raise TypeError(f"{field_name} must be an iterable collection")
    return tuple(value)


def _ordered_items(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, (set, frozenset)):
        raise TypeError(f"{field_name} must be an ordered iterable collection")
    return _iterable_items(value, field_name)


def _enum_frozenset(
    value: object,
    enum_type: type[EnumType],
    field_name: str,
) -> frozenset[EnumType]:
    items = _iterable_items(value, field_name)
    if any(not isinstance(item, enum_type) for item in items):
        raise TypeError(f"{field_name} must contain only {enum_type.__name__} values")
    return frozenset(items)


def _enum_frozenset_from_values(
    value: object,
    enum_type: type[EnumType],
    field_name: str,
) -> frozenset[EnumType]:
    items = _iterable_items(value, field_name)
    return frozenset(
        _enum_from_value(item, enum_type, field_name) for item in items
    )


def _typed_tuple(value: object, item_type: type, field_name: str) -> tuple:
    items = _iterable_items(value, field_name)
    if any(not isinstance(item, item_type) for item in items):
        raise TypeError(f"{field_name} must contain only {item_type.__name__} values")
    return items


def _ordered_typed_tuple(value: object, item_type: type, field_name: str) -> tuple:
    items = _ordered_items(value, field_name)
    if any(not isinstance(item, item_type) for item in items):
        raise TypeError(f"{field_name} must contain only {item_type.__name__} values")
    return items


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    items = _ordered_items(value, field_name)
    if any(not isinstance(item, str) or not item for item in items):
        raise TypeError(f"{field_name} must contain only non-empty strings")
    return tuple(items)


def _unique_in_order(values: Iterable[EnumType]) -> tuple[EnumType, ...]:
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class RiskSignal:
    signal_type: SignalType
    value: str
    source: str
    evidence: str

    _FIELDS = ("signal_type", "value", "source", "evidence")

    def __post_init__(self) -> None:
        _require_enum(self.signal_type, SignalType, "signal_type")
        for field_name in ("value", "source", "evidence"):
            object.__setattr__(
                self, field_name, _require_string(getattr(self, field_name), field_name)
            )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "signal_type": self.signal_type.value,
            "value": self.value,
            "source": self.source,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> RiskSignal:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        return cls(
            signal_type=_enum_from_value(
                values["signal_type"], SignalType, "signal_type"
            ),
            value=values["value"],
            source=values["source"],
            evidence=values["evidence"],
        )


@dataclass(frozen=True)
class HanGuardRule:
    rule_id: str
    rule_version: str
    signal_type: SignalType
    match_value: str
    minimum_risk: RiskLevel
    blocked_operations: frozenset[RouteOperation]
    reason: str
    evidence_source: str
    last_verified_date: str

    _FIELDS = (
        "rule_id",
        "rule_version",
        "signal_type",
        "match_value",
        "minimum_risk",
        "blocked_operations",
        "reason",
        "evidence_source",
        "last_verified_date",
    )

    def __post_init__(self) -> None:
        for field_name in (
            "rule_id",
            "rule_version",
            "match_value",
            "reason",
            "evidence_source",
            "last_verified_date",
        ):
            object.__setattr__(
                self, field_name, _require_string(getattr(self, field_name), field_name)
            )
        _require_enum(self.signal_type, SignalType, "signal_type")
        _require_enum(self.minimum_risk, RiskLevel, "minimum_risk")
        object.__setattr__(
            self,
            "blocked_operations",
            _enum_frozenset(
                self.blocked_operations, RouteOperation, "blocked_operations"
            ),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "signal_type": self.signal_type.value,
            "match_value": self.match_value,
            "minimum_risk": self.minimum_risk.name,
            "blocked_operations": sorted(
                item.value for item in self.blocked_operations
            ),
            "reason": self.reason,
            "evidence_source": self.evidence_source,
            "last_verified_date": self.last_verified_date,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> HanGuardRule:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        return cls(
            rule_id=values["rule_id"],
            rule_version=values["rule_version"],
            signal_type=_enum_from_value(
                values["signal_type"], SignalType, "signal_type"
            ),
            match_value=values["match_value"],
            minimum_risk=_risk_from_name(values["minimum_risk"], "minimum_risk"),
            blocked_operations=_enum_frozenset_from_values(
                values["blocked_operations"], RouteOperation, "blocked_operations"
            ),
            reason=values["reason"],
            evidence_source=values["evidence_source"],
            last_verified_date=values["last_verified_date"],
        )


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    rule_version: str
    actual_signal: str
    source: str
    risk_before: RiskLevel
    risk_after: RiskLevel
    blocked_operations: frozenset[RouteOperation]
    reason: str

    _FIELDS = (
        "rule_id",
        "rule_version",
        "actual_signal",
        "source",
        "risk_before",
        "risk_after",
        "blocked_operations",
        "reason",
    )

    def __post_init__(self) -> None:
        for field_name in (
            "rule_id",
            "rule_version",
            "actual_signal",
            "source",
            "reason",
        ):
            object.__setattr__(
                self, field_name, _require_string(getattr(self, field_name), field_name)
            )
        _require_enum(self.risk_before, RiskLevel, "risk_before")
        _require_enum(self.risk_after, RiskLevel, "risk_after")
        if self.risk_after < self.risk_before:
            raise ValueError("risk_after must not be lower than risk_before")
        object.__setattr__(
            self,
            "blocked_operations",
            _enum_frozenset(
                self.blocked_operations, RouteOperation, "blocked_operations"
            ),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "actual_signal": self.actual_signal,
            "source": self.source,
            "risk_before": self.risk_before.name,
            "risk_after": self.risk_after.name,
            "blocked_operations": sorted(
                item.value for item in self.blocked_operations
            ),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> RuleMatch:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        return cls(
            rule_id=values["rule_id"],
            rule_version=values["rule_version"],
            actual_signal=values["actual_signal"],
            source=values["source"],
            risk_before=_risk_from_name(values["risk_before"], "risk_before"),
            risk_after=_risk_from_name(values["risk_after"], "risk_after"),
            blocked_operations=_enum_frozenset_from_values(
                values["blocked_operations"], RouteOperation, "blocked_operations"
            ),
            reason=values["reason"],
        )


@dataclass(frozen=True)
class RoutePlan:
    project_id: str
    phase: RoutePhase
    risk_before: RiskLevel
    risk_after: RiskLevel
    allowed_operations: frozenset[RouteOperation]
    blocked_operations: frozenset[RouteOperation]
    matches: tuple[RuleMatch, ...]
    evaluation_status: EvaluationStatus
    unknown_evidence: bool
    decision_reasons: tuple[str, ...]

    _FIELDS = (
        "project_id",
        "phase",
        "risk_before",
        "risk_after",
        "allowed_operations",
        "blocked_operations",
        "matches",
        "evaluation_status",
        "unknown_evidence",
        "decision_reasons",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _require_string(self.project_id, "project_id"))
        _require_enum(self.phase, RoutePhase, "phase")
        _require_enum(self.risk_before, RiskLevel, "risk_before")
        _require_enum(self.risk_after, RiskLevel, "risk_after")
        if self.risk_after < self.risk_before:
            raise ValueError("risk_after must not be lower than risk_before")
        allowed = _enum_frozenset(
            self.allowed_operations, RouteOperation, "allowed_operations"
        )
        blocked = _enum_frozenset(
            self.blocked_operations, RouteOperation, "blocked_operations"
        )
        if blocked != _ALL_OPERATIONS - allowed:
            raise ValueError(
                "blocked_operations must be the exact complement of allowed_operations"
            )
        object.__setattr__(self, "allowed_operations", allowed)
        object.__setattr__(self, "blocked_operations", blocked)
        object.__setattr__(
            self,
            "matches",
            _ordered_typed_tuple(self.matches, RuleMatch, "matches"),
        )
        _require_enum(self.evaluation_status, EvaluationStatus, "evaluation_status")
        if not isinstance(self.unknown_evidence, bool):
            raise TypeError("unknown_evidence must be a bool")
        reasons = _string_tuple(self.decision_reasons, "decision_reasons")
        object.__setattr__(self, "decision_reasons", _unique_in_order(reasons))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "project_id": self.project_id,
            "phase": self.phase.value,
            "risk_before": self.risk_before.name,
            "risk_after": self.risk_after.name,
            "allowed_operations": sorted(
                item.value for item in self.allowed_operations
            ),
            "blocked_operations": sorted(
                item.value for item in self.blocked_operations
            ),
            "matches": [item.to_dict() for item in self.matches],
            "evaluation_status": self.evaluation_status.value,
            "unknown_evidence": self.unknown_evidence,
            "decision_reasons": list(self.decision_reasons),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> RoutePlan:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        matches = _ordered_items(values["matches"], "matches")
        return cls(
            project_id=values["project_id"],
            phase=_enum_from_value(values["phase"], RoutePhase, "phase"),
            risk_before=_risk_from_name(values["risk_before"], "risk_before"),
            risk_after=_risk_from_name(values["risk_after"], "risk_after"),
            allowed_operations=_enum_frozenset_from_values(
                values["allowed_operations"], RouteOperation, "allowed_operations"
            ),
            blocked_operations=_enum_frozenset_from_values(
                values["blocked_operations"], RouteOperation, "blocked_operations"
            ),
            matches=tuple(RuleMatch.from_dict(item) for item in matches),
            evaluation_status=_enum_from_value(
                values["evaluation_status"], EvaluationStatus, "evaluation_status"
            ),
            unknown_evidence=values["unknown_evidence"],
            decision_reasons=values["decision_reasons"],
        )


class HanGuard:
    def __init__(self, rules: Iterable[HanGuardRule]):
        items = _typed_tuple(rules, HanGuardRule, "rules")
        self._rules = tuple(sorted(items, key=_rule_sort_key))

    def evaluate_provisional(
        self,
        project_id: str,
        user_baseline: RiskLevel | None,
        signals: Iterable[RiskSignal],
        *,
        evaluation_status: EvaluationStatus,
    ) -> RoutePlan:
        project_id = _require_string(project_id, "project_id")
        _require_optional_risk(user_baseline, "user_baseline")
        _require_enum(evaluation_status, EvaluationStatus, "evaluation_status")
        signal_items = _validated_signals(signals)

        risk_before = (
            RiskLevel.H2_RESTRICTED if user_baseline is None else user_baseline
        )
        unknown_evidence = user_baseline is None
        reasons: list[str] = []
        if user_baseline is None:
            reasons.append("missing_user_baseline")
        if evaluation_status is not EvaluationStatus.COMPLETE:
            risk_before = max(risk_before, RiskLevel.H2_RESTRICTED)
            unknown_evidence = True

        matches, risk_after = self._evaluate_matches(risk_before, signal_items)
        reasons = [item.reason for item in matches] + reasons
        if evaluation_status is not EvaluationStatus.COMPLETE:
            reasons.append(evaluation_status.value)
        reasons = list(_unique_in_order(reasons))

        allowed = frozenset({RouteOperation.DETECT})
        return RoutePlan(
            project_id=project_id,
            phase=RoutePhase.PROVISIONAL,
            risk_before=risk_before,
            risk_after=risk_after,
            allowed_operations=allowed,
            blocked_operations=_ALL_OPERATIONS - allowed,
            matches=matches,
            evaluation_status=evaluation_status,
            unknown_evidence=unknown_evidence,
            decision_reasons=tuple(reasons),
        )

    def evaluate_final(
        self,
        provisional: RoutePlan,
        adapter_baseline: RiskLevel | None,
        signals: Iterable[RiskSignal],
        *,
        available_operations: frozenset[RouteOperation],
        evaluation_status: EvaluationStatus,
    ) -> RoutePlan:
        if not isinstance(provisional, RoutePlan):
            raise TypeError("provisional must be a RoutePlan")
        if provisional.phase is not RoutePhase.PROVISIONAL:
            raise ValueError("evaluate_final requires a provisional RoutePlan")
        _require_optional_risk(adapter_baseline, "adapter_baseline")
        _require_enum(evaluation_status, EvaluationStatus, "evaluation_status")
        if not isinstance(available_operations, frozenset):
            raise TypeError("available_operations must be a frozenset")
        capabilities = _enum_frozenset(
            available_operations, RouteOperation, "available_operations"
        )
        signal_items = _validated_signals(signals)

        risk_before = provisional.risk_after
        risk_base = (
            RiskLevel.H2_RESTRICTED
            if adapter_baseline is None
            else adapter_baseline
        )
        risk_base = max(risk_before, risk_base)
        if evaluation_status is not EvaluationStatus.COMPLETE:
            risk_base = max(risk_base, RiskLevel.H2_RESTRICTED)

        new_matches, risk_after = self._evaluate_matches(risk_base, signal_items)
        matches = _merge_matches(provisional.matches, new_matches)

        final_status = evaluation_status
        if (
            final_status is EvaluationStatus.COMPLETE
            and provisional.evaluation_status is not EvaluationStatus.COMPLETE
        ):
            final_status = provisional.evaluation_status

        reasons = list(provisional.decision_reasons)
        reasons.extend(item.reason for item in new_matches)
        if adapter_baseline is None:
            reasons.append("missing_adapter_baseline")
        if evaluation_status is not EvaluationStatus.COMPLETE:
            reasons.append(evaluation_status.value)
        reasons = list(_unique_in_order(reasons))

        base_operations = (
            _ALL_OPERATIONS
            if risk_after in (RiskLevel.H0_PROJECT, RiskLevel.H1_OFFLINE)
            else _SAFE_EXTERNAL_OPERATIONS
        )
        rule_blocks = frozenset(
            operation
            for match in matches
            for operation in match.blocked_operations
        )
        allowed = (base_operations & capabilities) - rule_blocks
        return RoutePlan(
            project_id=provisional.project_id,
            phase=RoutePhase.FINAL,
            risk_before=risk_before,
            risk_after=risk_after,
            allowed_operations=allowed,
            blocked_operations=_ALL_OPERATIONS - allowed,
            matches=matches,
            evaluation_status=final_status,
            unknown_evidence=(
                provisional.unknown_evidence
                or adapter_baseline is None
                or evaluation_status is not EvaluationStatus.COMPLETE
            ),
            decision_reasons=tuple(reasons),
        )

    def _evaluate_matches(
        self,
        risk_before: RiskLevel,
        signals: tuple[RiskSignal, ...],
    ) -> tuple[tuple[RuleMatch, ...], RiskLevel]:
        current_risk = risk_before
        matches: list[RuleMatch] = []
        seen: set[tuple[object, ...]] = set()
        for rule in self._rules:
            for signal in signals:
                if rule.signal_type is not signal.signal_type:
                    continue
                if rule.match_value.casefold() != signal.value.casefold():
                    continue
                identity = (
                    rule.rule_id,
                    rule.rule_version,
                    signal.value,
                    signal.source,
                    rule.reason,
                    rule.blocked_operations,
                )
                if identity in seen:
                    continue
                seen.add(identity)
                next_risk = max(current_risk, rule.minimum_risk)
                matches.append(
                    RuleMatch(
                        rule_id=rule.rule_id,
                        rule_version=rule.rule_version,
                        actual_signal=signal.value,
                        source=signal.source,
                        risk_before=current_risk,
                        risk_after=next_risk,
                        blocked_operations=rule.blocked_operations,
                        reason=rule.reason,
                    )
                )
                current_risk = next_risk
        return tuple(matches), current_risk


def _require_optional_risk(value: object, field_name: str) -> None:
    if value is not None:
        _require_enum(value, RiskLevel, field_name)


def _validated_signals(signals: Iterable[RiskSignal]) -> tuple[RiskSignal, ...]:
    items = _typed_tuple(signals, RiskSignal, "signals")
    return tuple(sorted(items, key=_signal_sort_key))


def _rule_sort_key(rule: HanGuardRule) -> tuple[object, ...]:
    return (
        rule.rule_id,
        rule.rule_version,
        rule.signal_type.value,
        rule.match_value.casefold(),
        rule.match_value,
        rule.minimum_risk.value,
        tuple(sorted(item.value for item in rule.blocked_operations)),
        rule.reason,
        rule.evidence_source,
        rule.last_verified_date,
    )


def _signal_sort_key(signal: RiskSignal) -> tuple[str, str, str, str, str]:
    return (
        signal.signal_type.value,
        signal.value.casefold(),
        signal.value,
        signal.source,
        signal.evidence,
    )


def _match_identity(match: RuleMatch) -> tuple[object, ...]:
    return (
        match.rule_id,
        match.rule_version,
        match.actual_signal,
        match.source,
        match.reason,
        match.blocked_operations,
    )


def _merge_matches(
    existing: tuple[RuleMatch, ...],
    additional: tuple[RuleMatch, ...],
) -> tuple[RuleMatch, ...]:
    merged: list[RuleMatch] = []
    seen: set[tuple[object, ...]] = set()
    for match in (*existing, *additional):
        identity = _match_identity(match)
        if identity not in seen:
            seen.add(identity)
            merged.append(match)
    return tuple(merged)
