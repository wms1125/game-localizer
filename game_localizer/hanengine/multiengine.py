from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .segments import JsonValue, normalize_relative_path


_PLACEHOLDER_RE = re.compile(
    r"\{[^{}\r\n]+\}|\[[^\]\r\n]+\]|%(?:\d+\$)?[A-Za-z]|\$\{[^}\r\n]+\}"
)
_RPG_TEXT_KEYS = frozenset(
    {
        "name",
        "nickname",
        "profile",
        "description",
        "message",
        "text",
        "help",
        "title",
        "gametitle",
        "currencyunit",
        "locationname",
        "mapname",
        "command",
    }
)
_RPG_EVENT_CODES = frozenset({101, 102, 401, 405, 408})
_CSV_KEY_NAMES = frozenset({"key", "keys", "id", "key id", "entry", "entry id"})


class MultiEngineError(ValueError):
    """Raised when an engine resource is unsupported or fails closed."""


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    return value


def extract_placeholders(value: str) -> tuple[str, ...]:
    _require_text(value, "value", allow_empty=True)
    return tuple(_PLACEHOLDER_RE.findall(value))


def _validate_placeholders(source: str, target: str) -> None:
    if Counter(extract_placeholders(source)) != Counter(extract_placeholders(target)):
        raise MultiEngineError("translation changes placeholders")


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise MultiEngineError(f"unable to decode text resource: {path.name}")


def _relative(path: Path, root: Path) -> str:
    try:
        return normalize_relative_path(path.relative_to(root).as_posix())
    except ValueError as exc:
        raise MultiEngineError("resource path is outside project root") from exc


def _fingerprint(root: Path, files: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        normalized = normalize_relative_path(relative)
        path = root / Path(*normalized.split("/"))
        if not path.is_file() or path.is_symlink():
            raise MultiEngineError(f"resource file is unavailable: {normalized}")
        digest.update(normalized.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def _copy_tree(source: Path, output: Path) -> None:
    source = source.resolve(strict=True)
    output = output.resolve(strict=False)
    if source == output or source in output.parents:
        raise MultiEngineError("output root must be separate from source root")
    output.mkdir(parents=True, exist_ok=True)
    for current, directories, files in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        safe_directories: list[str] = []
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                raise MultiEngineError("project contains a symbolic link")
            safe_directories.append(name)
            (output / path.relative_to(source)).mkdir(parents=True, exist_ok=True)
        directories[:] = safe_directories
        for name in files:
            path = current_path / name
            if path.is_symlink():
                raise MultiEngineError("project contains a symbolic link")
            destination = output / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def _json_pointer(path: tuple[str | int, ...]) -> str:
    parts = []
    for item in path:
        text = str(item).replace("~", "~0").replace("/", "~1")
        parts.append(text)
    return "/" + "/".join(parts)


def _json_parts(pointer: str) -> tuple[str, ...]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise MultiEngineError("invalid JSON pointer")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/"))


def _json_get(value: object, parts: tuple[str, ...]) -> object:
    current = value
    for part in parts:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise MultiEngineError("JSON pointer does not identify a value") from exc
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise MultiEngineError("JSON pointer does not identify a value")
    return current


def _json_set(value: object, parts: tuple[str, ...], replacement: str) -> None:
    if not parts:
        raise MultiEngineError("JSON pointer cannot replace the document root")
    current = value
    for part in parts[:-1]:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise MultiEngineError("JSON pointer does not identify a value") from exc
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise MultiEngineError("JSON pointer does not identify a value")
    last = parts[-1]
    if isinstance(current, list):
        try:
            current[int(last)] = replacement
        except (ValueError, IndexError) as exc:
            raise MultiEngineError("JSON pointer does not identify a value") from exc
    elif isinstance(current, dict) and last in current:
        current[last] = replacement
    else:
        raise MultiEngineError("JSON pointer does not identify a value")


@dataclass(frozen=True)
class LocalizationEntry:
    segment_id: str
    relative_path: str
    source_text: str
    source_hash: str
    kind: str
    locator: dict[str, JsonValue]
    target_text: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("segment_id", "source_text", "source_hash", "kind"):
            _require_text(getattr(self, field_name), field_name)
        object.__setattr__(self, "relative_path", normalize_relative_path(self.relative_path))
        if not isinstance(self.locator, dict):
            raise TypeError("locator must be a JSON object")
        json.dumps(self.locator, ensure_ascii=False, allow_nan=False)
        if self.target_text is not None:
            _require_text(self.target_text, "target_text", allow_empty=True)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "segment_id": self.segment_id,
            "relative_path": self.relative_path,
            "source_text": self.source_text,
            "source_hash": self.source_hash,
            "kind": self.kind,
            "locator": json.loads(json.dumps(self.locator, ensure_ascii=False, sort_keys=True)),
            "target_text": self.target_text,
        }


@dataclass(frozen=True)
class LocalizationCatalog:
    engine_id: str
    language: str
    source_language: str
    project_fingerprint: str
    files: tuple[str, ...]
    entries: tuple[LocalizationEntry, ...]

    def __post_init__(self) -> None:
        for field_name in ("engine_id", "language", "source_language", "project_fingerprint"):
            _require_text(getattr(self, field_name), field_name)
        files = tuple(normalize_relative_path(item) for item in self.files)
        entries = tuple(self.entries)
        if any(not isinstance(item, LocalizationEntry) for item in entries):
            raise TypeError("entries must contain LocalizationEntry values")
        if len({item.segment_id for item in entries}) != len(entries):
            raise ValueError("entries must have unique segment IDs")
        if any(item.relative_path not in files for item in entries):
            raise ValueError("entry path is not present in catalog files")
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "entries", entries)

    def translate(self, translations: Mapping[str, str]) -> LocalizationCatalog:
        if not isinstance(translations, Mapping):
            raise TypeError("translations must be a mapping")
        result: list[LocalizationEntry] = []
        for entry in self.entries:
            target = translations.get(entry.source_text, entry.target_text)
            if target is not None:
                _require_text(target, "translation", allow_empty=True)
                _validate_placeholders(entry.source_text, target)
            result.append(replace(entry, target_text=target))
        return replace(self, entries=tuple(result))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "engine_id": self.engine_id,
            "language": self.language,
            "source_language": self.source_language,
            "project_fingerprint": self.project_fingerprint,
            "files": list(self.files),
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> LocalizationCatalog:
        if not isinstance(payload, Mapping):
            raise TypeError("catalog payload must be a mapping")
        expected = {"engine_id", "language", "source_language", "project_fingerprint", "files", "entries"}
        if set(payload) != expected:
            raise ValueError("catalog payload fields do not match schema")
        raw_entries = payload["entries"]
        if not isinstance(raw_entries, list):
            raise TypeError("entries must be a list")
        entries: list[LocalizationEntry] = []
        for raw in raw_entries:
            if not isinstance(raw, Mapping):
                raise TypeError("entry must be an object")
            entries.append(LocalizationEntry(**raw))
        return cls(
            engine_id=payload["engine_id"],
            language=payload["language"],
            source_language=payload["source_language"],
            project_fingerprint=payload["project_fingerprint"],
            files=payload["files"],
            entries=tuple(entries),
        )


def _entry(engine_id: str, relative: str, text: str, kind: str, locator: dict[str, JsonValue]) -> LocalizationEntry:
    identity = f"{engine_id}\0{relative}\0{kind}\0{json.dumps(locator, sort_keys=True)}\0{text}".encode("utf-8")
    return LocalizationEntry(
        segment_id=f"{engine_id}:{hashlib.sha256(identity).hexdigest()[:24]}",
        relative_path=relative,
        source_text=text,
        source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        kind=kind,
        locator=locator,
    )


def _catalog(engine_id: str, root: Path, language: str, source_language: str, files: tuple[str, ...], entries: list[LocalizationEntry]) -> LocalizationCatalog:
    return LocalizationCatalog(engine_id, language, source_language, _fingerprint(root, files), files, tuple(entries))


def _rpg_data_files(root: Path) -> tuple[Path, ...]:
    base = root / "www" if (root / "www" / "data").is_dir() else root
    data = base / "data"
    if not data.is_dir():
        raise MultiEngineError("RPG Maker project has no data directory")
    return tuple(sorted(path for path in data.glob("*.json") if path.is_file() and not path.is_symlink()))


def _walk_rpg(value: object, pointer: tuple[str | int, ...], emit) -> None:
    if isinstance(value, dict):
        code = value.get("code")
        parameters = value.get("parameters")
        if isinstance(code, int) and code in _RPG_EVENT_CODES and isinstance(parameters, list):
            if code == 101 and len(parameters) > 4 and isinstance(parameters[4], str):
                emit(parameters[4], pointer + ("parameters", 4), "event")
            elif code in {401, 405, 408} and parameters and isinstance(parameters[0], str):
                emit(parameters[0], pointer + ("parameters", 0), "event")
            elif code == 102 and parameters and isinstance(parameters[0], list):
                for index, choice in enumerate(parameters[0]):
                    if isinstance(choice, str):
                        emit(choice, pointer + ("parameters", 0, index), "choice")
        for key, child in value.items():
            if isinstance(child, str) and key.casefold() in _RPG_TEXT_KEYS and child:
                emit(child, pointer + (key,), "field")
            elif isinstance(child, (dict, list)):
                _walk_rpg(child, pointer + (key,), emit)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                _walk_rpg(child, pointer + (index,), emit)


class RpgMakerExtractor:
    def __init__(self, engine_id: str):
        if engine_id not in {"rpg_maker_mv", "rpg_maker_mz"}:
            raise ValueError("engine_id must be rpg_maker_mv or rpg_maker_mz")
        self.engine_id = engine_id

    def extract(self, project_root: Path, *, language: str = "zh-CN", source_language: str = "en") -> LocalizationCatalog:
        root = project_root.resolve(strict=True)
        entries: list[LocalizationEntry] = []
        files = tuple(_relative(path, root) for path in _rpg_data_files(root))
        for path, relative in zip(_rpg_data_files(root), files):
            try:
                document = json.loads(_read_text(path))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise MultiEngineError(f"invalid RPG Maker JSON: {relative}") from exc
            _walk_rpg(
                document,
                (),
                lambda text, pointer, kind: entries.append(
                    _entry(self.engine_id, relative, text, kind, {"type": "json", "pointer": _json_pointer(pointer)})
                ),
            )
        return _catalog(self.engine_id, root, language, source_language, files, entries)


def _csv_dialect(text: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _language_column(header: list[str], language: str, excluded: set[int]) -> int | None:
    normalized = language.casefold().replace("_", "-")
    for index, value in enumerate(header):
        if index in excluded:
            continue
        folded = value.strip().casefold().replace("_", "-")
        if folded == normalized or folded.endswith(f"({normalized})"):
            return index
    return None


def _extract_csv(engine_id: str, root: Path, language: str, source_language: str) -> LocalizationCatalog:
    candidates = tuple(
        sorted(path for path in root.rglob("*.csv") if path.is_file() and not path.is_symlink())
    )
    entries: list[LocalizationEntry] = []
    files: list[str] = []
    for path in candidates:
        text = _read_text(path)
        dialect = _csv_dialect(text)
        rows = list(csv.reader(io.StringIO(text), dialect))
        if len(rows) < 2 or not rows[0]:
            continue
        header = [item.strip() for item in rows[0]]
        key_columns = {index for index, value in enumerate(header) if value.casefold() in _CSV_KEY_NAMES}
        source_col = _language_column(header, source_language, key_columns)
        if source_col is None:
            non_key = [index for index in range(len(header)) if index not in key_columns]
            source_col = non_key[0] if non_key else None
        if source_col is None:
            continue
        target_col = _language_column(header, language, key_columns)
        relative = _relative(path, root)
        files.append(relative)
        for row_index, row in enumerate(rows[1:], 1):
            if source_col >= len(row) or not row[source_col]:
                continue
            target_index = target_col if target_col is not None else len(header)
            entries.append(
                _entry(
                    engine_id,
                    relative,
                    row[source_col],
                    "csv",
                    {
                        "type": "csv",
                        "row": row_index,
                        "source_column": source_col,
                        "target_column": target_index,
                        "target_header": language,
                        "key_column": min(key_columns) if key_columns else None,
                        "delimiter": dialect.delimiter,
                    },
                )
            )
    if not files:
        raise MultiEngineError(f"no supported {engine_id} CSV resources found")
    return _catalog(engine_id, root, language, source_language, tuple(files), entries)


@dataclass(frozen=True)
class _PoRecord:
    prefix: tuple[str, ...]
    context: str | None
    msgid: str
    msgstr: str


def _po_value(line: str) -> str:
    try:
        value = ast.literal_eval(line[line.index('"'):])
    except (ValueError, SyntaxError):
        raise MultiEngineError("invalid PO quoted value")
    if not isinstance(value, str):
        raise MultiEngineError("PO value must be a string")
    return value


def _parse_po(text: str) -> list[_PoRecord]:
    records: list[_PoRecord] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.splitlines()
        if not lines:
            continue
        prefix: list[str] = []
        context: str | None = None
        msgid: str | None = None
        msgstr: str | None = None
        current: str | None = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                prefix.append(line)
            elif stripped.startswith("msgctxt "):
                context = _po_value(stripped)
                current = "context"
            elif stripped.startswith("msgid "):
                msgid = _po_value(stripped)
                current = "msgid"
            elif stripped.startswith("msgstr "):
                msgstr = _po_value(stripped)
                current = "msgstr"
            elif stripped.startswith('"') and stripped.endswith('"') and current:
                value = _po_value(stripped)
                if current == "context":
                    context = (context or "") + value
                elif current == "msgid":
                    msgid = (msgid or "") + value
                else:
                    msgstr = (msgstr or "") + value
            elif stripped:
                prefix.append(line)
        if msgid is not None and msgstr is not None:
            records.append(_PoRecord(tuple(prefix), context, msgid, msgstr))
    return records


def _po_quote(value: str) -> list[str]:
    encoded = json.dumps(value, ensure_ascii=False)
    if "\n" not in value:
        return [encoded]
    chunks = value.splitlines(keepends=True)
    lines = ['""']
    for chunk in chunks:
        lines.append(json.dumps(chunk, ensure_ascii=False))
    if value and not value.endswith("\n") and len(lines) == 1:
        lines.append(json.dumps(value, ensure_ascii=False))
    return lines


def _render_po(records: Iterable[_PoRecord]) -> str:
    output: list[str] = []
    for record in records:
        output.extend(record.prefix)
        if record.context is not None:
            context_lines = _po_quote(record.context)
            output.append("msgctxt " + context_lines[0])
            output.extend(context_lines[1:])
        msgid_lines = _po_quote(record.msgid)
        output.append("msgid " + msgid_lines[0])
        output.extend(msgid_lines[1:])
        msgstr_lines = _po_quote(record.msgstr)
        output.append("msgstr " + msgstr_lines[0])
        output.extend(msgstr_lines[1:])
        output.append("")
    return "\n".join(output)


def validate_resource_syntax(relative_path: str, text: str) -> None:
    """Parse a supported plaintext localization resource without modifying it."""
    normalized = normalize_relative_path(relative_path)
    _require_text(text, "text", allow_empty=True)
    suffix = Path(normalized).suffix.casefold()
    try:
        if suffix == ".json":
            json.loads(text)
        elif suffix == ".csv":
            list(csv.reader(io.StringIO(text), _csv_dialect(text), strict=True))
        elif suffix == ".po":
            for line in text.splitlines():
                stripped = line.strip()
                if stripped and not (
                    stripped.startswith("#")
                    or stripped.startswith("msgctxt ")
                    or stripped.startswith("msgid ")
                    or stripped.startswith("msgstr ")
                    or (stripped.startswith('"') and stripped.endswith('"'))
                ):
                    raise MultiEngineError("PO resource uses unsupported syntax")
            records = _parse_po(text)
            declared_records = sum(
                line.strip().startswith("msgid ") for line in text.splitlines()
            )
            if text.strip() and (not records or len(records) != declared_records):
                raise MultiEngineError("PO resource contains no parseable records")
        elif suffix in {".xlf", ".xliff"}:
            ET.fromstring(text)
        else:
            raise MultiEngineError(f"unsupported localization resource: {normalized}")
    except (csv.Error, json.JSONDecodeError, ET.ParseError) as exc:
        raise MultiEngineError(f"invalid localization resource: {normalized}") from exc


def _extract_po(engine_id: str, root: Path, language: str, source_language: str) -> LocalizationCatalog:
    candidates = tuple(
        sorted(path for path in root.rglob("*.po") if path.is_file() and not path.is_symlink())
    )
    files: list[str] = []
    entries: list[LocalizationEntry] = []
    for path in candidates:
        relative = _relative(path, root)
        text = _read_text(path)
        validate_resource_syntax(relative, text)
        records = _parse_po(text)
        usable = [record for record in records if record.msgid]
        if not usable:
            continue
        files.append(relative)
        for index, record in enumerate(records):
            if not record.msgid:
                continue
            entries.append(
                _entry(
                    engine_id,
                    relative,
                    record.msgid,
                    "po",
                    {"type": "po", "record": index},
                )
            )
    if not files:
        raise MultiEngineError(f"no supported {engine_id} PO resources found")
    return _catalog(engine_id, root, language, source_language, tuple(files), entries)


def _extract_xliff(engine_id: str, root: Path, language: str, source_language: str) -> LocalizationCatalog:
    candidates = tuple(
        sorted(
            path for path in (*root.rglob("*.xlf"), *root.rglob("*.xliff"))
            if path.is_file() and not path.is_symlink()
        )
    )
    files: list[str] = []
    entries: list[LocalizationEntry] = []
    for path in candidates:
        try:
            document = ET.fromstring(_read_text(path))
        except ET.ParseError as exc:
            raise MultiEngineError(f"invalid XLIFF resource: {_relative(path, root)}") from exc
        units = [node for node in document.iter() if node.tag.rsplit("}", 1)[-1] == "trans-unit"]
        usable = []
        for index, unit in enumerate(units):
            source = next((child for child in unit if child.tag.rsplit("}", 1)[-1] == "source"), None)
            if source is not None and "".join(source.itertext()):
                if list(source):
                    raise MultiEngineError("XLIFF inline markup is not supported yet")
                usable.append((index, unit, source))
        if not usable:
            continue
        relative = _relative(path, root)
        files.append(relative)
        for index, unit, source in usable:
            entries.append(
                _entry(
                    engine_id,
                    relative,
                    "".join(source.itertext()),
                    "xliff",
                    {"type": "xliff", "unit": index, "id": unit.attrib.get("id", str(index))},
                )
            )
    if not files:
        raise MultiEngineError("no supported Unity XLIFF resources found")
    return _catalog(engine_id, root, language, source_language, tuple(files), entries)


class GodotExtractor:
    def extract(self, project_root: Path, *, language: str = "zh-CN", source_language: str = "en") -> LocalizationCatalog:
        root = project_root.resolve(strict=True)
        po_candidates = tuple(root.rglob("*.po"))
        if po_candidates:
            return _extract_po("godot", root, language, source_language)
        return _extract_csv("godot", root, language, source_language)


class UnityExtractor:
    def extract(self, project_root: Path, *, language: str = "zh-CN", source_language: str = "en") -> LocalizationCatalog:
        root = project_root.resolve(strict=True)
        try:
            return _extract_xliff("unity", root, language, source_language)
        except MultiEngineError:
            return _extract_csv("unity", root, language, source_language)


class UnrealExtractor:
    def extract(self, project_root: Path, *, language: str = "zh-CN", source_language: str = "en") -> LocalizationCatalog:
        return _extract_po("unreal", project_root.resolve(strict=True), language, source_language)


class MultiEngineExtractor:
    def extract(self, engine_id: str, project_root: Path, *, language: str = "zh-CN", source_language: str = "en") -> LocalizationCatalog:
        if engine_id in {"rpg_maker_mv", "rpg_maker_mz"}:
            return RpgMakerExtractor(engine_id).extract(project_root, language=language, source_language=source_language)
        if engine_id == "godot":
            return GodotExtractor().extract(project_root, language=language, source_language=source_language)
        if engine_id == "unity":
            return UnityExtractor().extract(project_root, language=language, source_language=source_language)
        if engine_id == "unreal":
            return UnrealExtractor().extract(project_root, language=language, source_language=source_language)
        raise MultiEngineError(f"no structured extractor for engine: {engine_id}")


@dataclass(frozen=True)
class MultiEngineBuildResult:
    output_root: Path
    files_written: tuple[str, ...]
    entries_written: int


class MultiEngineWriter:
    def build(
        self,
        catalog: LocalizationCatalog,
        source_root: Path,
        output_root: Path,
        *,
        allow_existing_empty: bool = False,
    ) -> MultiEngineBuildResult:
        if not isinstance(catalog, LocalizationCatalog):
            raise TypeError("catalog must be a LocalizationCatalog")
        if type(allow_existing_empty) is not bool:
            raise TypeError("allow_existing_empty must be a bool")
        source = source_root.resolve(strict=True)
        if _fingerprint(source, catalog.files) != catalog.project_fingerprint:
            raise MultiEngineError("source project changed since extraction")
        grouped: dict[str, list[LocalizationEntry]] = {}
        for entry in catalog.entries:
            if entry.target_text is not None:
                grouped.setdefault(entry.relative_path, []).append(entry)
        if not grouped:
            raise MultiEngineError("catalog contains no translated entries")
        requested_output = output_root.absolute()
        output = output_root.resolve(strict=False)
        if output_root.is_symlink() or requested_output != output:
            raise MultiEngineError("output root must not resolve through a symbolic link")
        existing_empty = False
        if output.exists():
            if (
                not allow_existing_empty
                or output.is_symlink()
                or not output.is_dir()
                or next(output.iterdir(), None) is not None
            ):
                raise MultiEngineError("output root already exists; choose a new output directory")
            existing_empty = True
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent))).resolve()
        try:
            _copy_tree(source, staging)
            files_written: list[str] = []
            count = 0
            for relative, entries in grouped.items():
                path = staging / Path(*relative.split("/"))
                formats = {str(entry.locator.get("type")) for entry in entries}
                if formats == {"json"}:
                    document = json.loads(_read_text(path))
                    for entry in entries:
                        target = entry.target_text or ""
                        pointer = _json_parts(str(entry.locator["pointer"]))
                        if _json_get(document, pointer) != entry.source_text:
                            raise MultiEngineError(f"source text changed: {relative}")
                        _json_set(document, pointer, target)
                    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
                elif formats == {"csv"}:
                    text = _read_text(path)
                    dialect = _csv_dialect(text)
                    rows = list(csv.reader(io.StringIO(text), dialect))
                    header = rows[0]
                    for entry in entries:
                        locator = entry.locator
                        row_index = int(locator["row"])
                        source_col = int(locator["source_column"])
                        target_col = int(locator["target_column"])
                        if row_index >= len(rows):
                            raise MultiEngineError(f"source text changed: {relative}")
                        while len(rows[row_index]) <= target_col:
                            rows[row_index].append("")
                        if source_col >= len(rows[row_index]) or rows[row_index][source_col] != entry.source_text:
                            raise MultiEngineError(f"source text changed: {relative}")
                        while len(header) <= target_col:
                            header.append(str(locator.get("target_header", catalog.language)))
                        rows[row_index][target_col] = entry.target_text or ""
                    buffer = io.StringIO(newline="")
                    csv.writer(buffer, dialect).writerows(rows)
                    path.write_text(buffer.getvalue(), encoding="utf-8", newline="")
                elif formats == {"po"}:
                    records = _parse_po(_read_text(path))
                    for entry in entries:
                        index = int(entry.locator["record"])
                        if index >= len(records) or records[index].msgid != entry.source_text:
                            raise MultiEngineError(f"source text changed: {relative}")
                        records[index] = replace(records[index], msgstr=entry.target_text or "")
                    path.write_text(_render_po(records), encoding="utf-8", newline="\n")
                elif formats == {"xliff"}:
                    document = ET.fromstring(_read_text(path))
                    units = [node for node in document.iter() if node.tag.rsplit("}", 1)[-1] == "trans-unit"]
                    for entry in entries:
                        index = int(entry.locator["unit"])
                        if index >= len(units):
                            raise MultiEngineError(f"source text changed: {relative}")
                        unit = units[index]
                        source_node = next((child for child in unit if child.tag.rsplit("}", 1)[-1] == "source"), None)
                        if source_node is None or "".join(source_node.itertext()) != entry.source_text:
                            raise MultiEngineError(f"source text changed: {relative}")
                        target_node = next((child for child in unit if child.tag.rsplit("}", 1)[-1] == "target"), None)
                        if target_node is None:
                            namespace = unit.tag.split("}", 1)[0][1:] if unit.tag.startswith("{") else ""
                            target_tag = f"{{{namespace}}}target" if namespace else "target"
                            target_node = ET.SubElement(unit, target_tag)
                        target_node.text = entry.target_text or ""
                    ET.ElementTree(document).write(path, encoding="utf-8", xml_declaration=True)
                else:
                    raise MultiEngineError(f"mixed or unsupported resource format: {relative}")
                files_written.append(relative)
                count += len(entries)
            removed_placeholder = False
            try:
                if existing_empty:
                    output.rmdir()
                    removed_placeholder = True
                staging.replace(output)
            except Exception:
                if removed_placeholder and not output.exists():
                    output.mkdir()
                raise
            return MultiEngineBuildResult(output, tuple(sorted(files_written)), count)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


__all__ = [
    "extract_placeholders",
    "GodotExtractor",
    "LocalizationCatalog",
    "LocalizationEntry",
    "MultiEngineBuildResult",
    "MultiEngineError",
    "MultiEngineExtractor",
    "MultiEngineWriter",
    "RpgMakerExtractor",
    "UnityExtractor",
    "UnrealExtractor",
    "validate_resource_syntax",
]
