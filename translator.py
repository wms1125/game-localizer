from __future__ import annotations

from collections import Counter
import codecs
import csv
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any


SUPPORTED_EXTENSIONS = {".txt", ".ks", ".rpy", ".script", ".csv", ".json"}
OUTPUT_ENCODING = "utf-8"
PLACEHOLDER_RE = re.compile(
    r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\{(?:[A-Za-z_][A-Za-z0-9_]*|\d+)\}|"
    r"%(?:\d+|[sdif])|\\r\\n|\\n"
)
CANDIDATE_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|\.{1,2}[\\/])")


class TranslationError(Exception):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise TranslationError(f"JSON 包含重复键: {key}")
        value[key] = item
    return value


@dataclass(frozen=True)
class MatchPreview:
    location: str
    original: str
    translated: str


@dataclass(frozen=True)
class UnmatchedPreview:
    location: str
    original: str


@dataclass(frozen=True)
class PlaceholderWarning:
    location: str
    original: str
    translated: str
    missing: tuple[str, ...]


@dataclass
class TransformResult:
    content: str
    matched_keys: set[str] = field(default_factory=set)
    replacement_count: int = 0
    untranslated: dict[str, str] = field(default_factory=dict)
    matches: list[MatchPreview] = field(default_factory=list)
    unmatched: list[UnmatchedPreview] = field(default_factory=list)
    warnings: list[PlaceholderWarning] = field(default_factory=list)


@dataclass
class ProcessingResult:
    input_encoding: str
    output_encoding: str
    output_path: Path
    untranslated_path: Path
    matched_keys: set[str]
    replacement_count: int
    untranslated: dict[str, str]
    matches: list[MatchPreview]
    unmatched: list[UnmatchedPreview]
    warnings: list[PlaceholderWarning]
    overwritten_paths: tuple[Path, ...] = ()


def decode_bytes(data: bytes) -> tuple[str, str]:
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig"), "utf-8-sig"
    encodings = ("utf-8", "cp932", "shift_jis")
    for encoding in encodings:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise TranslationError("无法识别资源文件编码")


def load_translation_dictionary(path: str | Path) -> dict[str, str]:
    dictionary_path = Path(path)
    try:
        text = dictionary_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise TranslationError(f"无法加载翻译字典: {exc}") from exc
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except ValueError as exc:
        raise TranslationError(f"无法加载翻译字典: {exc}") from exc
    if not isinstance(data, dict):
        raise TranslationError("翻译字典必须是 JSON 对象")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in data.items()):
        raise TranslationError("翻译字典的键和值必须都是字符串")
    if any(key == "" for key in data):
        raise TranslationError("翻译字典的原文键不能为空")
    try:
        for key, value in data.items():
            key.encode("utf-8")
            value.encode("utf-8")
    except UnicodeError as exc:
        raise TranslationError("翻译字典的键和值必须可编码为 UTF-8") from exc
    return data


def missing_placeholders(source: str, translated: str) -> tuple[str, ...]:
    missing = Counter(PLACEHOLDER_RE.findall(source)) - Counter(PLACEHOLDER_RE.findall(translated))
    return tuple(token for token, count in sorted(missing.items()) for _ in range(count))


def is_translation_candidate(value: str) -> bool:
    stripped = value.strip()
    return bool(
        stripped
        and CANDIDATE_RE.search(stripped)
        and not URL_RE.match(stripped)
        and not PATH_RE.match(stripped)
    )


def _record_exact(value: str, location: str, dictionary: dict[str, str], result: TransformResult) -> str:
    if value in dictionary:
        translated = dictionary[value]
        result.matched_keys.add(value)
        result.replacement_count += 1
        result.matches.append(MatchPreview(location, value, translated))
        missing = missing_placeholders(value, translated)
        if missing:
            result.warnings.append(PlaceholderWarning(location, value, translated, missing))
        return translated
    if is_translation_candidate(value):
        result.untranslated.setdefault(value, "")
        result.unmatched.append(UnmatchedPreview(location, value))
    return value


def _json_path(parent: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{parent}.{key}"
    return f"{parent}[{key!r}]"


def transform_json(text: str, dictionary: dict[str, str]) -> TransformResult:
    def reject_non_finite(constant: str) -> None:
        raise TranslationError(f"JSON 资源包含非有限数值: {constant}")

    try:
        data = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=reject_non_finite,
            parse_float=Decimal,
        )
    except json.JSONDecodeError as exc:
        raise TranslationError(f"JSON 资源格式无效: {exc}") from exc
    except DecimalException as exc:
        raise TranslationError(f"JSON 数值无法安全解析: {exc}") from exc
    except ValueError as exc:
        raise TranslationError(f"JSON 资源包含无法安全解析的数值: {exc}") from exc
    result = TransformResult(content="")

    def walk(value: Any, path: str) -> Any:
        if isinstance(value, str):
            return _record_exact(value, f"JSON {path}", dictionary, result)
        if isinstance(value, list):
            return [walk(item, _json_path(path, index)) for index, item in enumerate(value)]
        if isinstance(value, dict):
            return {key: walk(item, _json_path(path, key)) for key, item in value.items()}
        if isinstance(value, Decimal):
            try:
                converted = float(value)
                equivalent = Decimal(str(converted)) == value
            except (DecimalException, OverflowError, ValueError) as exc:
                raise TranslationError(f"JSON 数值无法无损转换为 float: {value}") from exc
            if not math.isfinite(converted) or not equivalent:
                raise TranslationError(f"JSON 数值无法无损转换为 float: {value}")
            return converted
        return value

    transformed = walk(data, "$")
    result.content = json.dumps(
        transformed,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"
    return result


def transform_csv(text: str, dictionary: dict[str, str]) -> TransformResult:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), dialect, strict=True))
    except csv.Error as exc:
        raise TranslationError(f"CSV 资源解析失败: {exc}") from exc
    result = TransformResult(content="")
    for row_number, row in enumerate(rows, start=1):
        for column_number, value in enumerate(row, start=1):
            row[column_number - 1] = _record_exact(
                value,
                f"CSV 第 {row_number} 行第 {column_number} 列",
                dictionary,
                result,
            )
    output = io.StringIO(newline="")
    try:
        writer = csv.writer(
            output,
            delimiter=dialect.delimiter,
            quotechar='"',
            doublequote=True,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writerows(rows)
    except csv.Error as exc:
        raise TranslationError(f"CSV 资源写出失败: {exc}") from exc
    result.content = output.getvalue()
    return result


def transform_plaintext(text: str, dictionary: dict[str, str], label: str = "TXT") -> TransformResult:
    result = TransformResult(content="")
    pattern = (
        re.compile("|".join(re.escape(key) for key in sorted(dictionary, key=len, reverse=True)))
        if dictionary
        else None
    )
    output_lines: list[str] = []
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        location = f"{label} 第 {line_number} 行"
        matched_spans: list[tuple[int, int]] = []

        def replace(match: re.Match[str]) -> str:
            original = match.group(0)
            translated = dictionary[original]
            matched_spans.append(match.span())
            result.matched_keys.add(original)
            result.replacement_count += 1
            result.matches.append(MatchPreview(location, original, translated))
            missing = missing_placeholders(original, translated)
            if missing:
                result.warnings.append(PlaceholderWarning(location, original, translated, missing))
            return translated

        translated_line = pattern.sub(replace, line) if pattern else line
        output_lines.append(translated_line)
        original_candidate = line.removesuffix("\n").removesuffix("\r")
        remaining_parts: list[str] = []
        cursor = 0
        for start, end in matched_spans:
            remaining_parts.append(line[cursor:start])
            cursor = end
        remaining_parts.append(line[cursor:])
        if is_translation_candidate("".join(remaining_parts)):
            result.untranslated.setdefault(original_candidate, "")
            result.unmatched.append(UnmatchedPreview(location, original_candidate))
    result.content = "".join(output_lines)
    return result


def default_output_paths(resource_path: str | Path) -> tuple[Path, Path]:
    resource = Path(resource_path)
    return (
        resource.with_name(f"{resource.stem}.zh{resource.suffix}"),
        resource.with_name(f"{resource.stem}.untranslated.json"),
    )


FileIdentity = tuple[int, int]


def _identity(metadata: os.stat_result) -> FileIdentity:
    return metadata.st_dev, metadata.st_ino


def _resolve_path(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        raise TranslationError(f"无法解析路径 {path}: {exc}") from exc


def _absolute_path(path: Path) -> Path:
    try:
        return path.absolute()
    except (OSError, RuntimeError) as exc:
        raise TranslationError(f"无法检查路径 {path}: {exc}") from exc


def _metadata_for(path: Path) -> os.stat_result:
    try:
        return os.lstat(path)
    except (OSError, RuntimeError) as exc:
        raise TranslationError(f"无法检查路径 {path}: {exc}") from exc


def _optional_metadata_for(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except (OSError, RuntimeError) as exc:
        raise TranslationError(f"无法检查路径 {path}: {exc}") from exc


def _has_reparse_attribute(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or _has_reparse_attribute(metadata)


def _reject_existing_reparse_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts:
        if part == path.anchor:
            continue
        current /= part
        metadata = _optional_metadata_for(current)
        if metadata is None:
            return
        if _is_link_or_reparse(metadata):
            raise TranslationError(f"输出路径不能包含符号链接或重解析点: {current}")


def _directory_identity(path: Path) -> FileIdentity:
    _reject_existing_reparse_components(path)
    metadata = _metadata_for(path)
    if not stat.S_ISDIR(metadata.st_mode):
        raise TranslationError(f"输出父路径不是目录: {path}")
    return _identity(metadata)


def _validate_output_location(
    path: Path,
    parent_identity: FileIdentity,
    protected_identities: frozenset[FileIdentity],
) -> FileIdentity | None:
    _reject_existing_reparse_components(path)
    if _directory_identity(path.parent) != parent_identity:
        raise TranslationError(f"输出父目录在写入过程中发生变化: {path.parent}")
    metadata = _optional_metadata_for(path)
    if metadata is not None and _identity(metadata) in protected_identities:
        raise TranslationError(f"输出路径不能覆盖输入文件: {path}")
    return _identity(metadata) if metadata is not None else None


def _validate_managed_file(
    path: Path,
    expected_identity: FileIdentity,
    parent_identity: FileIdentity,
) -> None:
    _reject_existing_reparse_components(path)
    metadata = _metadata_for(path)
    if not stat.S_ISREG(metadata.st_mode) or _identity(metadata) != expected_identity:
        raise TranslationError(f"事务文件在写入过程中发生变化: {path}")
    if _directory_identity(path.parent) != parent_identity:
        raise TranslationError(f"输出父目录在写入过程中发生变化: {path.parent}")


def _cleanup_managed_file(
    path: Path,
    expected_identity: FileIdentity,
    errors: list[str],
) -> None:
    try:
        metadata = _optional_metadata_for(path)
        if metadata is None:
            return
        if _is_link_or_reparse(metadata) or _identity(metadata) != expected_identity:
            errors.append(f"未清理已变化的事务文件: {path}")
            return
        path.unlink()
    except BaseException as exc:
        errors.append(f"清理 {path} 失败: {exc}")


def atomic_write_many(
    outputs: dict[Path, str],
    *,
    protected_identities: frozenset[FileIdentity] = frozenset(),
) -> tuple[Path, ...]:
    ordered_outputs = [
        (Path(path), _absolute_path(Path(path)), content) for path, content in outputs.items()
    ]
    resolved_outputs = [_resolve_path(path) for _, path, _ in ordered_outputs]
    if len(set(resolved_outputs)) != len(resolved_outputs):
        raise TranslationError("输出路径不能相同")

    staged: dict[Path, Path] = {}
    staged_identities: dict[Path, FileIdentity] = {}
    backups: dict[Path, Path] = {}
    backup_identities: dict[Path, FileIdentity] = {}
    backup_placeholders: list[Path] = []
    parent_identities: dict[Path, FileIdentity] = {}
    commit_attempted: set[Path] = set()
    cleanup_errors: list[str] = []
    try:
        for _, path, _ in ordered_outputs:
            _reject_existing_reparse_components(path.parent)
            path.parent.mkdir(parents=True, exist_ok=True)
            parent_identities[path] = _directory_identity(path.parent)

        for _, path, content in ordered_outputs:
            _validate_output_location(path, parent_identities[path], protected_identities)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                staged[path] = temporary
                staged_identities[path] = _identity(_metadata_for(temporary))
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())

        for _, path, _ in ordered_outputs:
            target_identity = _validate_output_location(
                path,
                parent_identities[path],
                protected_identities,
            )
            if target_identity is not None:
                _validate_output_location(path, parent_identities[path], protected_identities)
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".bak",
                    delete=False,
                ) as handle:
                    backup = Path(handle.name)
                backup_placeholders.append(backup)
                backup_identities[backup] = _identity(_metadata_for(backup))
                _validate_managed_file(
                    backup,
                    backup_identities[backup],
                    parent_identities[path],
                )
                target_identity = _validate_output_location(
                    path,
                    parent_identities[path],
                    protected_identities,
                )
                if target_identity is None:
                    raise TranslationError(f"输出文件在备份前消失: {path}")
                os.replace(path, backup)
                backups[path] = backup
                backup_identities[backup] = target_identity

        for _, path, _ in ordered_outputs:
            _validate_managed_file(
                staged[path],
                staged_identities[path],
                parent_identities[path],
            )
            _validate_output_location(path, parent_identities[path], protected_identities)
            commit_attempted.add(path)
            os.replace(staged[path], path)
            staged.pop(path)
    except BaseException as exc:
        restored_backups: set[Path] = set()
        for _, path, _ in reversed(ordered_outputs):
            if path in backups:
                backup = backups[path]
                try:
                    _validate_managed_file(
                        backup,
                        backup_identities[backup],
                        parent_identities[path],
                    )
                    current_identity = _validate_output_location(
                        path,
                        parent_identities[path],
                        protected_identities,
                    )
                    if current_identity not in (None, staged_identities[path]):
                        raise TranslationError(f"输出文件在回滚前发生变化: {path}")
                    os.replace(backup, path)
                    restored_backups.add(backup)
                except BaseException as rollback_exc:
                    cleanup_errors.append(f"恢复 {path} 失败: {rollback_exc}")
            elif path in commit_attempted:
                _cleanup_managed_file(path, staged_identities[path], cleanup_errors)
        for path, temporary in staged.items():
            _cleanup_managed_file(temporary, staged_identities[path], cleanup_errors)
        for backup in backup_placeholders:
            if backup not in backups.values() or backup in restored_backups:
                _cleanup_managed_file(backup, backup_identities[backup], cleanup_errors)
        details = f"; {'; '.join(cleanup_errors)}" if cleanup_errors else ""
        if isinstance(exc, (OSError, UnicodeError)):
            raise TranslationError(f"无法以事务方式写入输出文件: {exc}{details}") from exc
        raise
    else:
        for backup in backup_placeholders:
            _cleanup_managed_file(backup, backup_identities[backup], cleanup_errors)
        if cleanup_errors:
            raise TranslationError(f"输出文件已写入，但清理备份失败: {'; '.join(cleanup_errors)}")
        return tuple(original for original, path, _ in ordered_outputs if path in backups)


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_many({Path(path): content})


def process_resource(
    resource_path: str | Path,
    dictionary_path: str | Path,
    output_path: str | Path | None = None,
    untranslated_path: str | Path | None = None,
) -> ProcessingResult:
    resource = Path(resource_path)
    dictionary_file = Path(dictionary_path)
    resource_resolved = _resolve_path(resource)
    dictionary_resolved = _resolve_path(dictionary_file)
    resource_metadata = _metadata_for(resource_resolved)
    dictionary_metadata = _metadata_for(dictionary_resolved)
    if not stat.S_ISREG(resource_metadata.st_mode):
        raise TranslationError(f"资源文件不存在: {resource}")
    suffix = resource.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise TranslationError(f"不支持的资源扩展名: {suffix or '(无扩展名)'}")

    default_output, default_untranslated = default_output_paths(resource)
    output = Path(output_path) if output_path is not None else default_output
    untranslated_output = Path(untranslated_path) if untranslated_path is not None else default_untranslated
    resolved_output = _resolve_path(output)
    resolved_untranslated = _resolve_path(untranslated_output)
    if resolved_output == resolved_untranslated:
        raise TranslationError("输出路径不能相同")
    resolved_outputs = (resolved_output, resolved_untranslated)
    if resource_resolved in resolved_outputs:
        raise TranslationError("输出路径不能覆盖源文件")
    if dictionary_resolved in resolved_outputs:
        raise TranslationError("输出路径不能覆盖翻译字典")

    dictionary = load_translation_dictionary(dictionary_resolved)
    try:
        text, input_encoding = decode_bytes(resource_resolved.read_bytes())
    except OSError as exc:
        raise TranslationError(f"无法读取资源文件: {exc}") from exc

    if suffix == ".json":
        transformed = transform_json(text, dictionary)
    elif suffix == ".csv":
        transformed = transform_csv(text, dictionary)
    else:
        transformed = transform_plaintext(text, dictionary, suffix.removeprefix(".").upper())

    overwritten_paths = atomic_write_many(
        {
            output: transformed.content,
            untranslated_output: json.dumps(transformed.untranslated, ensure_ascii=False, indent=2) + "\n",
        },
        protected_identities=frozenset(
            (_identity(resource_metadata), _identity(dictionary_metadata))
        ),
    )
    return ProcessingResult(
        input_encoding=input_encoding,
        output_encoding=OUTPUT_ENCODING,
        output_path=output,
        untranslated_path=untranslated_output,
        matched_keys=transformed.matched_keys,
        replacement_count=transformed.replacement_count,
        untranslated=transformed.untranslated,
        matches=transformed.matches,
        unmatched=transformed.unmatched,
        warnings=transformed.warnings,
        overwritten_paths=overwritten_paths,
    )
