from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import TypeAlias


JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


def normalize_relative_path(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("relative path must be a string")
    if not value:
        raise ValueError("relative path must not be empty")
    if "/" in value and "\\" in value:
        raise ValueError("relative path must not contain mixed path separators")

    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
    ):
        raise ValueError("relative path must not be absolute or rooted")

    path = windows_path if "\\" in value else posix_path
    if ".." in path.parts:
        raise ValueError("relative path must not contain parent traversal")

    normalized = PurePosixPath(*path.parts).as_posix()
    if not normalized or normalized == ".":
        raise ValueError("relative path must identify a path")
    return normalized


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


def _require_string(value: object, field_name: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence of strings")
    copied = tuple(value)
    if any(not isinstance(item, str) for item in copied):
        raise TypeError(f"{field_name} must contain only strings")
    return copied


def _optional_integer(
    value: object,
    field_name: str,
    *,
    minimum: int,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer or None")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return value


def _confidence(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number or None")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be within [0.0, 1.0]")
    return number


def _require_string_json_keys(value: object) -> None:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        for nested in value.values():
            _require_string_json_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _require_string_json_keys(nested)


def _copy_metadata(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise TypeError("metadata must be a JSON object")
    try:
        _require_string_json_keys(value)
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        copied = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must contain only finite JSON values") from exc
    return copied


@dataclass(frozen=True)
class ScreenRegion:
    x: int
    y: int
    width: int
    height: int

    _FIELDS = ("x", "y", "width", "height")

    def __post_init__(self) -> None:
        for name in self._FIELDS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if self.x < 0 or self.y < 0:
            raise ValueError("x and y must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> ScreenRegion:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        return cls(
            x=values["x"],
            y=values["y"],
            width=values["width"],
            height=values["height"],
        )


@dataclass(frozen=True)
class SourceLocation:
    relative_path: str | None = None
    logical_path: str | None = None
    line: int | None = None
    column: int | None = None
    byte_offset: int | None = None
    screen_region: ScreenRegion | None = None

    _FIELDS = (
        "relative_path",
        "logical_path",
        "line",
        "column",
        "byte_offset",
        "screen_region",
    )

    def __post_init__(self) -> None:
        if self.relative_path is not None:
            object.__setattr__(self, "relative_path", normalize_relative_path(self.relative_path))
        if self.logical_path is not None:
            logical_path = _require_string(self.logical_path, "logical_path", allow_empty=False)
            object.__setattr__(self, "logical_path", logical_path)
        object.__setattr__(self, "line", _optional_integer(self.line, "line", minimum=1))
        object.__setattr__(self, "column", _optional_integer(self.column, "column", minimum=1))
        object.__setattr__(
            self,
            "byte_offset",
            _optional_integer(self.byte_offset, "byte_offset", minimum=0),
        )
        if self.screen_region is not None and not isinstance(self.screen_region, ScreenRegion):
            raise TypeError("screen_region must be a ScreenRegion or None")
        if all(getattr(self, field_name) is None for field_name in self._FIELDS):
            raise ValueError("source location requires at least one locator")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "relative_path": self.relative_path,
            "logical_path": self.logical_path,
            "line": self.line,
            "column": self.column,
            "byte_offset": self.byte_offset,
            "screen_region": (
                None if self.screen_region is None else self.screen_region.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> SourceLocation:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        region_payload = values["screen_region"]
        if region_payload is None:
            region = None
        elif isinstance(region_payload, Mapping):
            region = ScreenRegion.from_dict(region_payload)
        else:
            raise TypeError("screen_region must be a mapping or None")
        return cls(
            relative_path=values["relative_path"],
            logical_path=values["logical_path"],
            line=values["line"],
            column=values["column"],
            byte_offset=values["byte_offset"],
            screen_region=region,
        )


@dataclass(frozen=True)
class SegmentDraft:
    segment_id: str
    source_text: str
    source_language: str
    speaker: str | None
    context_before: tuple[str, ...]
    context_after: tuple[str, ...]
    placeholders: tuple[str, ...]
    tags: tuple[str, ...]
    constraints: tuple[str, ...]
    source_location: SourceLocation
    source_fingerprint: str
    ocr_confidence: float | None
    region_confidence: float | None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    _FIELDS = (
        "segment_id",
        "source_text",
        "source_language",
        "speaker",
        "context_before",
        "context_after",
        "placeholders",
        "tags",
        "constraints",
        "source_location",
        "source_fingerprint",
        "ocr_confidence",
        "region_confidence",
        "metadata",
    )
    _SEQUENCE_FIELDS = (
        "context_before",
        "context_after",
        "placeholders",
        "tags",
        "constraints",
    )

    def __post_init__(self) -> None:
        for field_name in ("segment_id", "source_language", "source_fingerprint"):
            object.__setattr__(
                self,
                field_name,
                _require_string(getattr(self, field_name), field_name, allow_empty=False),
            )
        object.__setattr__(self, "source_text", _require_string(self.source_text, "source_text"))
        object.__setattr__(self, "speaker", _optional_string(self.speaker, "speaker"))
        for field_name in self._SEQUENCE_FIELDS:
            object.__setattr__(
                self,
                field_name,
                _string_tuple(getattr(self, field_name), field_name),
            )
        if not isinstance(self.source_location, SourceLocation):
            raise TypeError("source_location must be a SourceLocation")
        object.__setattr__(
            self,
            "ocr_confidence",
            _confidence(self.ocr_confidence, "ocr_confidence"),
        )
        object.__setattr__(
            self,
            "region_confidence",
            _confidence(self.region_confidence, "region_confidence"),
        )
        object.__setattr__(self, "metadata", _copy_metadata(self.metadata))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "segment_id": self.segment_id,
            "source_text": self.source_text,
            "source_language": self.source_language,
            "speaker": self.speaker,
            "context_before": list(self.context_before),
            "context_after": list(self.context_after),
            "placeholders": list(self.placeholders),
            "tags": list(self.tags),
            "constraints": list(self.constraints),
            "source_location": self.source_location.to_dict(),
            "source_fingerprint": self.source_fingerprint,
            "ocr_confidence": self.ocr_confidence,
            "region_confidence": self.region_confidence,
            "metadata": _copy_metadata(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> SegmentDraft:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        location_payload = values["source_location"]
        if not isinstance(location_payload, Mapping):
            raise TypeError("source_location must be a mapping")
        return cls(
            segment_id=values["segment_id"],
            source_text=values["source_text"],
            source_language=values["source_language"],
            speaker=values["speaker"],
            context_before=values["context_before"],
            context_after=values["context_after"],
            placeholders=values["placeholders"],
            tags=values["tags"],
            constraints=values["constraints"],
            source_location=SourceLocation.from_dict(location_payload),
            source_fingerprint=values["source_fingerprint"],
            ocr_confidence=values["ocr_confidence"],
            region_confidence=values["region_confidence"],
            metadata=values["metadata"],
        )


@dataclass(frozen=True)
class Segment:
    project_id: str
    target_language: str
    segment_id: str
    source_text: str
    source_language: str
    speaker: str | None
    context_before: tuple[str, ...]
    context_after: tuple[str, ...]
    placeholders: tuple[str, ...]
    tags: tuple[str, ...]
    constraints: tuple[str, ...]
    source_location: SourceLocation
    source_fingerprint: str
    context_fingerprint: str
    target_text: str | None
    translation_source: str | None
    ocr_confidence: float | None
    region_confidence: float | None
    metadata: dict[str, JsonValue]

    _FIELDS = (
        "project_id",
        "target_language",
        "segment_id",
        "source_text",
        "source_language",
        "speaker",
        "context_before",
        "context_after",
        "placeholders",
        "tags",
        "constraints",
        "source_location",
        "source_fingerprint",
        "context_fingerprint",
        "target_text",
        "translation_source",
        "ocr_confidence",
        "region_confidence",
        "metadata",
    )
    _SEQUENCE_FIELDS = SegmentDraft._SEQUENCE_FIELDS

    def __post_init__(self) -> None:
        for field_name in (
            "project_id",
            "target_language",
            "segment_id",
            "source_language",
            "source_fingerprint",
            "context_fingerprint",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_string(getattr(self, field_name), field_name, allow_empty=False),
            )
        object.__setattr__(self, "source_text", _require_string(self.source_text, "source_text"))
        for field_name in ("speaker", "target_text", "translation_source"):
            object.__setattr__(
                self,
                field_name,
                _optional_string(getattr(self, field_name), field_name),
            )
        for field_name in self._SEQUENCE_FIELDS:
            object.__setattr__(
                self,
                field_name,
                _string_tuple(getattr(self, field_name), field_name),
            )
        if not isinstance(self.source_location, SourceLocation):
            raise TypeError("source_location must be a SourceLocation")
        object.__setattr__(
            self,
            "ocr_confidence",
            _confidence(self.ocr_confidence, "ocr_confidence"),
        )
        object.__setattr__(
            self,
            "region_confidence",
            _confidence(self.region_confidence, "region_confidence"),
        )
        object.__setattr__(self, "metadata", _copy_metadata(self.metadata))

    @classmethod
    def from_draft(
        cls,
        project_id: str,
        target_language: str,
        draft: SegmentDraft,
    ) -> Segment:
        if not isinstance(draft, SegmentDraft):
            raise TypeError("draft must be a SegmentDraft")
        fingerprint_payload = {
            "project_id": project_id,
            "target_language": target_language,
            "speaker": draft.speaker,
            "context_before": list(draft.context_before),
            "context_after": list(draft.context_after),
            "constraints": list(draft.constraints),
            "source_location": draft.source_location.to_dict(),
        }
        canonical = json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            project_id=project_id,
            target_language=target_language,
            segment_id=draft.segment_id,
            source_text=draft.source_text,
            source_language=draft.source_language,
            speaker=draft.speaker,
            context_before=draft.context_before,
            context_after=draft.context_after,
            placeholders=draft.placeholders,
            tags=draft.tags,
            constraints=draft.constraints,
            source_location=draft.source_location,
            source_fingerprint=draft.source_fingerprint,
            context_fingerprint=hashlib.sha256(canonical).hexdigest(),
            target_text=None,
            translation_source=None,
            ocr_confidence=draft.ocr_confidence,
            region_confidence=draft.region_confidence,
            metadata=draft.metadata,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "project_id": self.project_id,
            "target_language": self.target_language,
            "segment_id": self.segment_id,
            "source_text": self.source_text,
            "source_language": self.source_language,
            "speaker": self.speaker,
            "context_before": list(self.context_before),
            "context_after": list(self.context_after),
            "placeholders": list(self.placeholders),
            "tags": list(self.tags),
            "constraints": list(self.constraints),
            "source_location": self.source_location.to_dict(),
            "source_fingerprint": self.source_fingerprint,
            "context_fingerprint": self.context_fingerprint,
            "target_text": self.target_text,
            "translation_source": self.translation_source,
            "ocr_confidence": self.ocr_confidence,
            "region_confidence": self.region_confidence,
            "metadata": _copy_metadata(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> Segment:
        values = _require_mapping(payload, cls.__name__)
        _require_exact_keys(values, cls._FIELDS, cls.__name__)
        location_payload = values["source_location"]
        if not isinstance(location_payload, Mapping):
            raise TypeError("source_location must be a mapping")
        return cls(
            project_id=values["project_id"],
            target_language=values["target_language"],
            segment_id=values["segment_id"],
            source_text=values["source_text"],
            source_language=values["source_language"],
            speaker=values["speaker"],
            context_before=values["context_before"],
            context_after=values["context_after"],
            placeholders=values["placeholders"],
            tags=values["tags"],
            constraints=values["constraints"],
            source_location=SourceLocation.from_dict(location_payload),
            source_fingerprint=values["source_fingerprint"],
            context_fingerprint=values["context_fingerprint"],
            target_text=values["target_text"],
            translation_source=values["translation_source"],
            ocr_confidence=values["ocr_confidence"],
            region_confidence=values["region_confidence"],
            metadata=values["metadata"],
        )
