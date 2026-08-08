from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import tokenize
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from .multiengine import extract_placeholders as _extract_generic_placeholders
from .segments import JsonValue


_FIELDS = (
    "segment_id",
    "relative_path",
    "line",
    "kind",
    "source_text",
    "source_hash",
    "placeholders",
    "speaker",
    "target_text",
)
_CATALOG_FIELDS = ("language", "project_fingerprint", "entries")
_COMMANDS = frozenset(
    {
        "label",
        "jump",
        "call",
        "scene",
        "show",
        "hide",
        "with",
        "play",
        "queue",
        "stop",
        "pause",
        "window",
        "voice",
        "image",
        "transform",
        "define",
        "default",
        "python",
        "init",
        "translate",
        "old",
        "new",
    }
)
# These screen-language properties carry identifiers, styles, or asset paths,
# not user-facing text. A text statement without one of these properties is
# still extracted so screen labels remain localizable.
_SCREEN_NON_TEXT_NAMES = frozenset(
    {
        "add",
        "action",
        "activate_sound",
        "alternate",
        "at",
        "background",
        "color",
        "hover_sound",
        "font",
        "foreground",
        "id",
        "insensitive",
        "key",
        "layout",
        "mouse",
        "scrollbars",
        "selected",
        "selected_hover",
        "selected_idle",
        "sound",
        "size_group",
        "style",
        "style_prefix",
        "thumb",
        "unselected",
        "variant",
        "xalign",
        "yalign",
    }
)
_SCREEN_TEXT_STATEMENTS = frozenset({"label", "text", "textbutton"})
_ID_RE = re.compile(r"[^A-Za-z0-9_]+")
_LANGUAGE_ID_RE = re.compile(r"[^A-Za-z0-9_]+")
_LANGUAGE_ACTIVATION_PATH = PurePosixPath("game/hanengine_language.rpy")
_LANGUAGE_ACTIVATION_RE = re.compile(r"^define config\.default_language = (.+)$")
_TRANSLATE_HEADER_RE = re.compile(
    r"^translate ([A-Za-z_][A-Za-z0-9_]*) "
    r"(strings|[A-Za-z_][A-Za-z0-9_]*):$"
)
_TRANSLATE_VALUE_RE = re.compile(r"^    (old|new) (.+)$")


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} payload must be a mapping")
    return value


def _require_exact(payload: Mapping[str, object], fields: tuple[str, ...], name: str) -> None:
    if set(payload) != set(fields):
        raise ValueError(f"{name} payload fields do not match schema")


def _string(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be an iterable of strings")
    values = tuple(value)
    if any(not isinstance(item, str) for item in values):
        raise TypeError(f"{name} must contain only strings")
    return values


class RenPyValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RenPySegment:
    segment_id: str
    relative_path: str
    line: int
    kind: str
    source_text: str
    source_hash: str
    placeholders: tuple[str, ...]
    speaker: str | None = None
    target_text: str | None = None

    def __post_init__(self) -> None:
        for name in ("segment_id", "relative_path", "kind", "source_text", "source_hash"):
            object.__setattr__(self, name, _string(getattr(self, name), name))
        if not isinstance(self.line, int) or isinstance(self.line, bool) or self.line < 1:
            raise ValueError("line must be a positive integer")
        if self.kind not in {"dialogue", "menu", "narration"}:
            raise ValueError("kind must be dialogue, menu or narration")
        object.__setattr__(self, "placeholders", _string_tuple(self.placeholders, "placeholders"))
        if self.speaker is not None:
            object.__setattr__(self, "speaker", _string(self.speaker, "speaker"))
        if self.target_text is not None:
            object.__setattr__(self, "target_text", _string(self.target_text, "target_text", allow_empty=True))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "segment_id": self.segment_id,
            "relative_path": self.relative_path,
            "line": self.line,
            "kind": self.kind,
            "source_text": self.source_text,
            "source_hash": self.source_hash,
            "placeholders": list(self.placeholders),
            "speaker": self.speaker,
            "target_text": self.target_text,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> RenPySegment:
        values = _require_mapping(payload, cls.__name__)
        _require_exact(values, _FIELDS, cls.__name__)
        return cls(
            segment_id=values["segment_id"],
            relative_path=values["relative_path"],
            line=values["line"],
            kind=values["kind"],
            source_text=values["source_text"],
            source_hash=values["source_hash"],
            placeholders=values["placeholders"],
            speaker=values["speaker"],
            target_text=values["target_text"],
        )


@dataclass(frozen=True)
class RenPyCatalog:
    language: str
    project_fingerprint: str
    entries: tuple[RenPySegment, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _string(self.language, "language"))
        object.__setattr__(self, "project_fingerprint", _string(self.project_fingerprint, "project_fingerprint"))
        if isinstance(self.entries, (str, bytes)) or not isinstance(self.entries, Iterable):
            raise TypeError("entries must be an iterable")
        entries = tuple(self.entries)
        if any(not isinstance(item, RenPySegment) for item in entries):
            raise TypeError("entries must contain RenPySegment values")
        if len({item.segment_id for item in entries}) != len(entries):
            raise ValueError("entries must have unique segment IDs")
        object.__setattr__(self, "entries", entries)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "language": self.language,
            "project_fingerprint": self.project_fingerprint,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> RenPyCatalog:
        values = _require_mapping(payload, cls.__name__)
        _require_exact(values, _CATALOG_FIELDS, cls.__name__)
        entries = values["entries"]
        if isinstance(entries, (str, bytes)) or not isinstance(entries, Iterable):
            raise TypeError("entries must be an iterable")
        return cls(
            language=values["language"],
            project_fingerprint=values["project_fingerprint"],
            entries=tuple(RenPySegment.from_dict(item) for item in entries),
        )

    def translate(self, translations: Mapping[str, str]) -> RenPyCatalog:
        if not isinstance(translations, Mapping):
            raise TypeError("translations must be a mapping")
        translated: list[RenPySegment] = []
        for entry in self.entries:
            target = translations.get(entry.source_text, entry.target_text)
            if target is not None:
                _validate_placeholders(entry.source_text, target)
            translated.append(replace(entry, target_text=target))
        return replace(self, entries=tuple(translated))


def _validate_placeholders(source: str, target: str) -> None:
    source_tokens = _extract_placeholders(source)
    target_tokens = _extract_placeholders(target)
    source_variables = tuple(token for token in source_tokens if token.startswith("["))
    target_variables = tuple(token for token in target_tokens if token.startswith("["))
    if sorted(source_variables) != sorted(target_variables):
        raise RenPyValidationError("placeholder set changed during translation")
    source_tags = tuple(token for token in source_tokens if token.startswith("{"))
    target_tags = tuple(token for token in target_tokens if token.startswith("{"))
    if source_tags != target_tags:
        raise RenPyValidationError("rich text tags changed during translation")


def validate_renpy_placeholders(source: str, target: str) -> None:
    """Validate Ren'Py interpolation expressions and rich text tags."""
    _string(source, "source", allow_empty=True)
    _string(target, "target", allow_empty=True)
    _validate_placeholders(source, target)


def _extract_placeholders(text: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _extract_generic_placeholders(text)
        if token.startswith("[") or token.startswith("{")
    )


def renpy_language_identifier(language: str) -> str:
    value = _string(language, "language").replace("-", "_")
    value = _LANGUAGE_ID_RE.sub("_", value).strip("_").casefold()
    if not value:
        raise ValueError("language does not contain a valid Ren'Py identifier")
    if value[0].isdigit():
        value = f"lang_{value}"
    return value


def renpy_project_files(root: Path) -> tuple[Path, ...]:
    if not isinstance(root, Path):
        raise TypeError("root must be a Path")
    game = root / "game"
    if not game.is_dir():
        raise ValueError("Ren'Py project must contain a game directory")
    return tuple(
        sorted(
            path
            for path in game.rglob("*.rpy")
            if path.is_file()
            and "tl" not in path.relative_to(root).parts
            and path.relative_to(root).as_posix() != _LANGUAGE_ACTIVATION_PATH.as_posix()
        )
    )


def validate_renpy_translation_text(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    current_block: str | None = None
    expected = "old"
    block_pairs = 0
    total_pairs = 0
    languages: set[str] = set()

    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            if current_block is not None and (expected != "old" or block_pairs == 0):
                raise RenPyValidationError(
                    f"incomplete translation block before line {line_number}"
                )
            header = _TRANSLATE_HEADER_RE.fullmatch(line)
            if header is None:
                raise RenPyValidationError(
                    f"invalid translation block header at line {line_number}"
                )
            languages.add(header.group(1))
            current_block = header.group(2)
            expected = "old"
            block_pairs = 0
            continue

        if current_block is None:
            raise RenPyValidationError(
                f"translation statement has no block at line {line_number}"
            )
        statement = _TRANSLATE_VALUE_RE.fullmatch(line)
        if statement is None or statement.group(1) != expected:
            raise RenPyValidationError(
                f"invalid translation statement at line {line_number}"
            )
        try:
            value = ast.literal_eval(statement.group(2))
        except (SyntaxError, ValueError) as exc:
            raise RenPyValidationError(
                f"invalid string literal at line {line_number}"
            ) from exc
        if not isinstance(value, str):
            raise RenPyValidationError(
                f"translation value is not a string at line {line_number}"
            )
        if expected == "old":
            expected = "new"
        else:
            expected = "old"
            block_pairs += 1
            total_pairs += 1

    if current_block is None or expected != "old" or block_pairs == 0:
        raise RenPyValidationError("translation file contains no complete translation block")
    if len(languages) != 1:
        raise RenPyValidationError("translation file mixes language identifiers")
    return total_pairs


def validate_renpy_language_activation_text(
    text: str,
    *,
    expected_language: str | None = None,
) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    declarations: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        declaration = _LANGUAGE_ACTIVATION_RE.fullmatch(line)
        if declaration is None:
            raise RenPyValidationError(
                f"invalid language activation statement at line {line_number}"
            )
        try:
            language = ast.literal_eval(declaration.group(1))
        except (SyntaxError, ValueError) as exc:
            raise RenPyValidationError(
                f"invalid language identifier at line {line_number}"
            ) from exc
        if not isinstance(language, str) or language != renpy_language_identifier(language):
            raise RenPyValidationError(
                f"invalid language identifier at line {line_number}"
            )
        declarations.append(language)
    if len(declarations) != 1:
        raise RenPyValidationError(
            "language activation file must contain one default language declaration"
        )
    language = declarations[0]
    if expected_language is not None and language != renpy_language_identifier(expected_language):
        raise RenPyValidationError("language activation target does not match the catalog")
    return language


def _project_fingerprint(root: Path, files: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def _tokens_for_line(line: str) -> tuple[tokenize.TokenInfo, ...]:
    try:
        return tuple(tokenize.generate_tokens(io.StringIO(line).readline))
    except (tokenize.TokenError, IndentationError):
        return ()


def _extract_line(line: str) -> tuple[str, str | None, str] | None:
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    tokens = [token for token in _tokens_for_line(line) if token.type not in {tokenize.ENCODING, tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT}]
    string_index = next((index for index, token in enumerate(tokens) if token.type == tokenize.STRING), None)
    if string_index is None:
        return None
    before = tokens[:string_index]
    after = tokens[string_index + 1 :]
    wrapped = (
        len(before) >= 2
        and before[-2].type == tokenize.NAME
        and before[-2].string == "_"
        and before[-1].type == tokenize.OP
        and before[-1].string == "("
        and bool(after)
        and after[0].type == tokenize.OP
        and after[0].string == ")"
    )
    if wrapped:
        before = before[:-2]
        after = after[1:]
    prefix_names = [token.string for token in before if token.type == tokenize.NAME]
    if any(token.type not in {tokenize.NAME, tokenize.OP} for token in before):
        return None
    if any(token.string not in {";", ":"} for token in after) and (
        not prefix_names or prefix_names[0] not in _SCREEN_TEXT_STATEMENTS
    ):
        return None
    if prefix_names and prefix_names[0] in _COMMANDS and prefix_names[0] not in _SCREEN_TEXT_STATEMENTS:
        return None
    if any(name in _SCREEN_NON_TEXT_NAMES for name in prefix_names):
        return None
    if any(name in {"old", "new"} for name in prefix_names):
        return None
    try:
        source = ast.literal_eval(tokens[string_index].string)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(source, str) or not source:
        return None
    if any(token.type == tokenize.OP and token.string not in {"-", "+"} for token in before):
        return None
    is_screen_text = bool(prefix_names and prefix_names[0] in _SCREEN_TEXT_STATEMENTS)
    kind = (
        "narration"
        if is_screen_text
        else (
            "menu"
            if any(token.type == tokenize.OP and token.string in {"-", "+"} for token in before)
            else ("dialogue" if prefix_names else "narration")
        )
    )
    speaker = None if is_screen_text else (prefix_names[-1] if prefix_names else None)
    return kind, speaker, source


class RenPyExtractor:
    def extract(self, project_root: Path, *, language: str = "zh_cn") -> RenPyCatalog:
        if not isinstance(project_root, Path):
            raise TypeError("project_root must be a Path")
        root = project_root.resolve(strict=True)
        files = renpy_project_files(root)
        entries: list[RenPySegment] = []
        duplicate_counts: dict[str, int] = {}
        for path in files:
            relative = path.relative_to(root).as_posix()
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                parsed = _extract_line(line)
                if parsed is None:
                    continue
                kind, speaker, source = parsed
                identity = f"{relative}\0{kind}\0{speaker or ''}\0{source}".encode("utf-8")
                base_segment_id = "renpy:" + hashlib.sha256(identity).hexdigest()[:24]
                occurrence = duplicate_counts.get(base_segment_id, 0)
                duplicate_counts[base_segment_id] = occurrence + 1
                if occurrence:
                    identity += f"\0{occurrence}".encode("ascii")
                    segment_id = "renpy:" + hashlib.sha256(identity).hexdigest()[:24]
                else:
                    segment_id = base_segment_id
                entries.append(
                    RenPySegment(
                        segment_id=segment_id,
                        relative_path=relative,
                        line=line_number,
                        kind=kind,
                        source_text=source,
                        source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                        placeholders=_extract_placeholders(source),
                        speaker=speaker,
                    )
                )
        return RenPyCatalog(language, _project_fingerprint(root, files), tuple(entries))


@dataclass(frozen=True)
class RenPyBuildResult:
    path: Path
    sha256: str
    activation_path: Path
    activation_sha256: str
    entries_written: int


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


class RenPyWriter:
    def build(
        self,
        catalog: RenPyCatalog,
        output_root: Path,
        *,
        source_root: Path | None = None,
    ) -> RenPyBuildResult:
        if not isinstance(catalog, RenPyCatalog):
            raise TypeError("catalog must be a RenPyCatalog")
        output = output_root.resolve(strict=False)
        if source_root is not None:
            source = source_root.resolve(strict=True)
            if output == source:
                raise ValueError("output root must be separate from source root")
            source_activation = source / Path(*_LANGUAGE_ACTIVATION_PATH.parts)
            if source_activation.exists():
                raise ValueError(
                    "source project already contains the reserved HanEngine language activation path"
                )
            current = RenPyExtractor().extract(source, language=catalog.language)
            if current.project_fingerprint != catalog.project_fingerprint:
                raise ValueError("source project changed since extraction")
        translated = tuple(item for item in catalog.entries if item.target_text is not None)
        if not translated:
            raise ValueError("catalog contains no translated entries")
        for item in translated:
            _validate_placeholders(item.source_text, item.target_text or "")
        language = renpy_language_identifier(catalog.language)
        path = output / "game" / "tl" / language / "hanengine_translations.rpy"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Generated by HanEngine; source project remains unchanged.", ""]
        # Ren'Py indexes string translations by the old text globally. Repeating
        # an old value in separate blocks causes a runtime duplicate-translation
        # error, so retain the first translated occurrence deterministically.
        unique_translated: list[RenPySegment] = []
        seen_sources: set[str] = set()
        for item in translated:
            if item.source_text in seen_sources:
                continue
            seen_sources.add(item.source_text)
            unique_translated.append(item)
        dialogue = [item for item in unique_translated if item.kind == "dialogue"]
        strings = [item for item in unique_translated if item.kind != "dialogue"]
        for item in dialogue:
            block_id = "hanengine_" + _ID_RE.sub("_", item.segment_id)
            lines.extend(
                [
                    f"translate {language} {block_id}:",
                    f"    old {_quote(item.source_text)}",
                    f"    new {_quote(item.target_text or '')}",
                    "",
                ]
            )
        if strings:
            lines.extend([f"translate {language} strings:"])
            for item in strings:
                lines.extend([f"    old {_quote(item.source_text)}", f"    new {_quote(item.target_text or '')}"])
            lines.append("")
        rendered = "\n".join(lines)
        validate_renpy_translation_text(rendered)
        path.write_text(rendered, encoding="utf-8", newline="\n")
        content = path.read_bytes()
        activation_path = output / Path(*_LANGUAGE_ACTIVATION_PATH.parts)
        activation_lines = [
            "# Generated by HanEngine; source project remains unchanged.",
            "# Later Language(...) choices are persisted by Ren'Py preferences.",
            f"define config.default_language = {_quote(language)}",
            "",
        ]
        activation_text = "\n".join(activation_lines)
        validate_renpy_language_activation_text(
            activation_text,
            expected_language=language,
        )
        activation_path.write_text(activation_text, encoding="utf-8", newline="\n")
        activation_content = activation_path.read_bytes()
        return RenPyBuildResult(
            path,
            hashlib.sha256(content).hexdigest(),
            activation_path,
            hashlib.sha256(activation_content).hexdigest(),
            len(translated),
        )


__all__ = [
    "RenPyBuildResult",
    "RenPyCatalog",
    "RenPyExtractor",
    "RenPySegment",
    "RenPyValidationError",
    "RenPyWriter",
    "renpy_language_identifier",
    "renpy_project_files",
    "validate_renpy_language_activation_text",
    "validate_renpy_translation_text",
]
