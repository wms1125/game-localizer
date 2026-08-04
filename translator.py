from __future__ import annotations

from collections import Counter
import codecs
from dataclasses import dataclass, field
import json
from pathlib import Path
import re


SUPPORTED_EXTENSIONS = {".txt", ".ks", ".rpy", ".script", ".csv", ".json"}
OUTPUT_ENCODING = "utf-8"
PLACEHOLDER_RE = re.compile(
    r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\{(?:[A-Za-z_][A-Za-z0-9_]*|\d+)\}|"
    r"%(?:\d+|[sdif])|\\r\\n|\\n"
)


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
