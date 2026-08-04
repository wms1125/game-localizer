from __future__ import annotations

from collections import Counter
import codecs
import csv
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


SUPPORTED_EXTENSIONS = {".txt", ".ks", ".rpy", ".script", ".csv", ".json"}
OUTPUT_ENCODING = "utf-8"
PLACEHOLDER_RE = re.compile(
    r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\{(?:[A-Za-z_][A-Za-z0-9_]*|\d+)\}|"
    r"%(?:\d+|[sdif])|\\r\\n|\\n"
)
CANDIDATE_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]")
URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|\.{1,2}[\\/])")


class TranslationError(Exception):
    pass


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
        data = json.loads(dictionary_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TranslationError(f"无法加载翻译字典: {exc}") from exc
    if not isinstance(data, dict):
        raise TranslationError("翻译字典必须是 JSON 对象")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in data.items()):
        raise TranslationError("翻译字典的键和值必须都是字符串")
    if any(key == "" for key in data):
        raise TranslationError("翻译字典的原文键不能为空")
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
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TranslationError(f"JSON 资源格式无效: {exc}") from exc
    result = TransformResult(content="")

    def walk(value: Any, path: str) -> Any:
        if isinstance(value, str):
            return _record_exact(value, f"JSON {path}", dictionary, result)
        if isinstance(value, list):
            return [walk(item, _json_path(path, index)) for index, item in enumerate(value)]
        if isinstance(value, dict):
            return {key: walk(item, _json_path(path, key)) for key, item in value.items()}
        return value

    transformed = walk(data, "$")
    result.content = json.dumps(transformed, ensure_ascii=False, indent=2) + "\n"
    return result


def transform_csv(text: str, dictionary: dict[str, str]) -> TransformResult:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
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
    writer = csv.writer(output, dialect=dialect, lineterminator="\n")
    writer.writerows(rows)
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
        original_candidate = line.strip()
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


def atomic_write_text(path: Path, content: str) -> None:
    temporary_name: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_name = handle.name
        os.replace(temporary_name, path)
    except OSError as exc:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise TranslationError(f"无法写入输出文件 {path}: {exc}") from exc


def process_resource(
    resource_path: str | Path,
    dictionary_path: str | Path,
    output_path: str | Path | None = None,
    untranslated_path: str | Path | None = None,
) -> ProcessingResult:
    resource = Path(resource_path)
    if not resource.is_file():
        raise TranslationError(f"资源文件不存在: {resource}")
    suffix = resource.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise TranslationError(f"不支持的资源扩展名: {suffix or '(无扩展名)'}")

    default_output, default_untranslated = default_output_paths(resource)
    output = Path(output_path) if output_path is not None else default_output
    untranslated_output = Path(untranslated_path) if untranslated_path is not None else default_untranslated
    if output.resolve() == resource.resolve() or untranslated_output.resolve() == resource.resolve():
        raise TranslationError("输出路径不能覆盖源文件")

    dictionary = load_translation_dictionary(dictionary_path)
    try:
        text, input_encoding = decode_bytes(resource.read_bytes())
    except OSError as exc:
        raise TranslationError(f"无法读取资源文件: {exc}") from exc

    if suffix == ".json":
        transformed = transform_json(text, dictionary)
    elif suffix == ".csv":
        transformed = transform_csv(text, dictionary)
    else:
        transformed = transform_plaintext(text, dictionary, suffix.removeprefix(".").upper())

    atomic_write_text(output, transformed.content)
    atomic_write_text(
        untranslated_output,
        json.dumps(transformed.untranslated, ensure_ascii=False, indent=2) + "\n",
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
    )
