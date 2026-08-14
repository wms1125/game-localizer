from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import shutil
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
_UNHANDLED_FIELDS = ("relative_path", "line", "expression", "reason")
_CATALOG_FIELDS = (
    "language",
    "project_fingerprint",
    "entries",
    "unhandled_items",
)
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
_FONT_CONFIG_PATH = PurePosixPath("game/hanengine_fonts.rpy")
_FONT_DIRECTORY = PurePosixPath("game/hanengine_fonts")
_LANGUAGE_ACTIVATION_RE = re.compile(r"^define config\.default_language = (.+)$")
_LANGUAGE_OVERRIDE_HEADER = "init 1 python:"
_LANGUAGE_OVERRIDE_LINES = (
    "    import os as _hanengine_os",
    "    _hanengine_requested_language = _hanengine_os.environ.get(\"HANENGINE_GAME_LANGUAGE\")",
    "    if _hanengine_requested_language == \"source\":",
    "        config.default_language = None",
    "        config.language = None",
    "        _preferences.language = None",
    "    elif _hanengine_requested_language:",
    "        config.language = _hanengine_requested_language",
)
_FONT_CONFIG_HEADER_RE = re.compile(
    r"^translate ([A-Za-z_][A-Za-z0-9_]*) python:$"
)
_FONT_GROUP_INIT = "    _hanengine_font_group = FontGroup()"
_FONT_GROUP_ADD_RE = re.compile(
    r'^    _hanengine_font_group\.add\("([A-Za-z0-9._/-]+)", '
    r"(None|0x[0-9a-f]+), (None|0x[0-9a-f]+)\)$"
)
_FONT_GROUP_ASSIGNMENT = (
    "    gui.system_font = gui.main_font = gui.text_font = "
    "gui.name_text_font = gui.interface_text_font = "
    "gui.button_text_font = gui.choice_button_text_font = "
    "_hanengine_font_group"
)
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
class RenPyUnhandledItem:
    relative_path: str
    line: int
    expression: str
    reason: str

    def __post_init__(self) -> None:
        for name in ("relative_path", "expression", "reason"):
            object.__setattr__(self, name, _string(getattr(self, name), name))
        if not isinstance(self.line, int) or isinstance(self.line, bool) or self.line < 1:
            raise ValueError("line must be a positive integer")
        if self.reason not in {
            "dynamic_translation_argument",
            "concatenated_translation_expression",
        }:
            raise ValueError("unsupported Ren'Py unhandled-item reason")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "relative_path": self.relative_path,
            "line": self.line,
            "expression": self.expression,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> "RenPyUnhandledItem":
        values = _require_mapping(payload, cls.__name__)
        _require_exact(values, _UNHANDLED_FIELDS, cls.__name__)
        return cls(
            relative_path=values["relative_path"],
            line=values["line"],
            expression=values["expression"],
            reason=values["reason"],
        )


@dataclass(frozen=True)
class RenPyCatalog:
    language: str
    project_fingerprint: str
    entries: tuple[RenPySegment, ...]
    unhandled_items: tuple[RenPyUnhandledItem, ...] = ()

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
        if isinstance(self.unhandled_items, (str, bytes)) or not isinstance(
            self.unhandled_items, Iterable
        ):
            raise TypeError("unhandled_items must be an iterable")
        unhandled_items = tuple(self.unhandled_items)
        if any(not isinstance(item, RenPyUnhandledItem) for item in unhandled_items):
            raise TypeError("unhandled_items must contain RenPyUnhandledItem values")
        object.__setattr__(self, "unhandled_items", unhandled_items)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "language": self.language,
            "project_fingerprint": self.project_fingerprint,
            "entries": [entry.to_dict() for entry in self.entries],
            "unhandled_items": [item.to_dict() for item in self.unhandled_items],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> RenPyCatalog:
        values = _require_mapping(payload, cls.__name__)
        _require_exact(values, _CATALOG_FIELDS, cls.__name__)
        entries = values["entries"]
        if isinstance(entries, (str, bytes)) or not isinstance(entries, Iterable):
            raise TypeError("entries must be an iterable")
        unhandled_items = values["unhandled_items"]
        if isinstance(unhandled_items, (str, bytes)) or not isinstance(
            unhandled_items, Iterable
        ):
            raise TypeError("unhandled_items must be an iterable")
        return cls(
            language=values["language"],
            project_fingerprint=values["project_fingerprint"],
            entries=tuple(RenPySegment.from_dict(item) for item in entries),
            unhandled_items=tuple(
                RenPyUnhandledItem.from_dict(item) for item in unhandled_items
            ),
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
            and path.relative_to(root).as_posix()
            not in {
                _LANGUAGE_ACTIVATION_PATH.as_posix(),
                _FONT_CONFIG_PATH.as_posix(),
            }
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
    statements = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not statements:
        raise RenPyValidationError("language activation file must contain one default language declaration")
    declaration = _LANGUAGE_ACTIVATION_RE.fullmatch(statements[0])
    if declaration is None:
        raise RenPyValidationError("invalid language activation statement at line 1")
    try:
        language = ast.literal_eval(declaration.group(1))
    except (SyntaxError, ValueError) as exc:
        raise RenPyValidationError("invalid language identifier at line 1") from exc
    if not isinstance(language, str) or language != renpy_language_identifier(language):
        raise RenPyValidationError("invalid language identifier at line 1")
    declarations.append(language)
    remainder = statements[1:]
    if remainder:
        expected_override = [_LANGUAGE_OVERRIDE_HEADER, *_LANGUAGE_OVERRIDE_LINES]
        if remainder != expected_override:
            raise RenPyValidationError("invalid language override statements")
    if len(declarations) != 1:
        raise RenPyValidationError(
            "language activation file must contain one default language declaration"
        )
    language = declarations[0]
    if expected_language is not None and language != renpy_language_identifier(expected_language):
        raise RenPyValidationError("language activation target does not match the catalog")
    return language


def _font_unicode_coverage(path: Path) -> set[int]:
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise ValueError("fontTools is required when shipping Ren'Py fonts") from exc
    try:
        font = TTFont(str(path), lazy=True)
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError(f"font could not be read: {path.name}") from exc
    try:
        coverage: set[int] = set()
        for table in font["cmap"].tables:
            if table.isUnicode():
                coverage.update(table.cmap)
        return coverage
    except (KeyError, AttributeError) as exc:
        raise ValueError(f"font has no Unicode cmap: {path.name}") from exc
    finally:
        font.close()


def _codepoint_ranges(codepoints: Iterable[int]) -> tuple[tuple[int, int], ...]:
    ordered = sorted(set(codepoints))
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    previous: int | None = None
    for codepoint in ordered:
        if start is None:
            start = previous = codepoint
        elif codepoint == previous + 1:
            previous = codepoint
        else:
            ranges.append((start, previous))
            start = previous = codepoint
    if start is not None and previous is not None:
        ranges.append((start, previous))
    return tuple(ranges)


def validate_renpy_font_config_text(
    text: str,
    *,
    expected_language: str | None = None,
) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if len(lines) < 4:
        raise RenPyValidationError("font configuration is incomplete")
    header = _FONT_CONFIG_HEADER_RE.fullmatch(lines[0])
    if header is None:
        raise RenPyValidationError("invalid font configuration header")
    language = header.group(1)
    if language != renpy_language_identifier(language):
        raise RenPyValidationError("invalid font configuration language")
    if expected_language is not None and language != renpy_language_identifier(expected_language):
        raise RenPyValidationError("font configuration target does not match the catalog")
    if lines[1] != _FONT_GROUP_INIT or lines[-1] != _FONT_GROUP_ASSIGNMENT:
        raise RenPyValidationError("font configuration has invalid FontGroup statements")
    additions = lines[2:-1]
    if not additions or any(_FONT_GROUP_ADD_RE.fullmatch(line) is None for line in additions):
        raise RenPyValidationError("font configuration has invalid font ranges")
    if not any(line.endswith(", None, None)") for line in additions):
        raise RenPyValidationError("font configuration has no fallback font")
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


def _significant_tokens(line: str) -> tuple[tokenize.TokenInfo, ...]:
    ignored = {
        tokenize.ENCODING,
        tokenize.NEWLINE,
        tokenize.NL,
        tokenize.ENDMARKER,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.COMMENT,
    }
    return tuple(token for token in _tokens_for_line(line) if token.type not in ignored)


def _extract_translation_calls(
    line: str,
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    tokens = _significant_tokens(line)
    values: list[str] = []
    unhandled: list[tuple[str, str]] = []
    for index in range(len(tokens) - 1):
        if not (
            tokens[index].type == tokenize.NAME
            and tokens[index].string == "_"
            and tokens[index + 1].type == tokenize.OP
            and tokens[index + 1].string == "("
        ):
            continue
        depth = 0
        closing_index: int | None = None
        for cursor in range(index + 1, len(tokens)):
            token = tokens[cursor]
            if token.type != tokenize.OP:
                continue
            if token.string in {"(", "[", "{"}:
                depth += 1
            elif token.string in {")", "]", "}"}:
                depth -= 1
                if depth == 0:
                    closing_index = cursor
                    break
        if closing_index is None:
            expression = line[tokens[index].start[1] :].strip()
            if expression:
                unhandled.append((expression, "dynamic_translation_argument"))
            continue
        argument_tokens = tokens[index + 2 : closing_index]
        expression = line[
            tokens[index].start[1] : tokens[closing_index].end[1]
        ]
        if len(argument_tokens) != 1 or argument_tokens[0].type != tokenize.STRING:
            reason = (
                "concatenated_translation_expression"
                if any(
                    token.type == tokenize.OP and token.string == "+"
                    for token in argument_tokens
                )
                and any(token.type == tokenize.STRING for token in argument_tokens)
                else "dynamic_translation_argument"
            )
            unhandled.append((expression, reason))
            continue
        try:
            value = ast.literal_eval(argument_tokens[0].string)
        except (SyntaxError, ValueError):
            unhandled.append((expression, "dynamic_translation_argument"))
            continue
        if isinstance(value, str):
            if value:
                values.append(value)
        else:
            unhandled.append((expression, "dynamic_translation_argument"))
    return tuple(values), tuple(unhandled)


def _extract_line(line: str) -> tuple[str, str | None, str] | None:
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    tokens = list(_significant_tokens(line))
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


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


class RenPyExtractor:
    def extract(self, project_root: Path, *, language: str = "zh_cn") -> RenPyCatalog:
        if not isinstance(project_root, Path):
            raise TypeError("project_root must be a Path")
        root = project_root.resolve(strict=True)
        files = renpy_project_files(root)
        entries: list[RenPySegment] = []
        unhandled_items: list[RenPyUnhandledItem] = []
        duplicate_counts: dict[str, int] = {}
        for path in files:
            relative = path.relative_to(root).as_posix()
            menu_indent: int | None = None
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                indentation = _indent_width(line)
                if stripped == "menu:":
                    menu_indent = indentation
                    continue
                if menu_indent is not None and stripped and indentation <= menu_indent:
                    menu_indent = None
                parsed_entries: list[tuple[str, str | None, str]] = []
                parsed = _extract_line(line)
                if parsed is not None:
                    parsed_entries.append(parsed)
                wrapped_literals, unhandled_calls = _extract_translation_calls(line)
                unhandled_items.extend(
                    RenPyUnhandledItem(
                        relative_path=relative,
                        line=line_number,
                        expression=expression,
                        reason=reason,
                    )
                    for expression, reason in unhandled_calls
                )
                wrapped_sources = list(wrapped_literals)
                if parsed is not None and parsed[2] in wrapped_sources:
                    wrapped_sources.remove(parsed[2])
                parsed_entries.extend(
                    ("narration", None, source) for source in wrapped_sources
                )
                if not parsed_entries:
                    continue
                for kind, speaker, source in parsed_entries:
                    if menu_indent is not None and speaker is None and indentation > menu_indent:
                        kind = "menu"
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
        return RenPyCatalog(
            language,
            _project_fingerprint(root, files),
            tuple(entries),
            tuple(unhandled_items),
        )


@dataclass(frozen=True)
class RenPyBuildResult:
    path: Path
    sha256: str
    activation_path: Path
    activation_sha256: str
    entries_written: int
    generated_paths: tuple[Path, ...] = ()


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


class RenPyWriter:
    def build(
        self,
        catalog: RenPyCatalog,
        output_root: Path,
        *,
        source_root: Path | None = None,
        font_paths: Iterable[Path] = (),
        font_probe_texts: Iterable[str] = (),
    ) -> RenPyBuildResult:
        if not isinstance(catalog, RenPyCatalog):
            raise TypeError("catalog must be a RenPyCatalog")
        paths = tuple(font_paths)
        if isinstance(font_probe_texts, (str, bytes)):
            raise TypeError("font_probe_texts must be an iterable of strings")
        probes = tuple(font_probe_texts)
        if any(not isinstance(text, str) or not text for text in probes):
            raise ValueError("font_probe_texts must contain non-empty strings")
        if probes and not paths:
            raise ValueError("font probe texts require configured font_paths")
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
            source_font_config = source / Path(*_FONT_CONFIG_PATH.parts)
            source_font_directory = source / Path(*_FONT_DIRECTORY.parts)
            if source_font_config.exists() or source_font_directory.exists():
                raise ValueError(
                    "source project already contains the reserved HanEngine font paths"
                )
            current = RenPyExtractor().extract(source, language=catalog.language)
            if current.project_fingerprint != catalog.project_fingerprint:
                raise ValueError("source project changed since extraction")
        translated = tuple(item for item in catalog.entries if item.target_text is not None)
        if not translated:
            raise ValueError("catalog contains no translated entries")
        for item in translated:
            _validate_placeholders(item.source_text, item.target_text or "")
        unique_translated: list[RenPySegment] = []
        first_by_source: dict[str, RenPySegment] = {}
        for item in translated:
            previous = first_by_source.get(item.source_text)
            if previous is None:
                first_by_source[item.source_text] = item
                unique_translated.append(item)
                continue
            if previous.target_text != item.target_text:
                raise RenPyValidationError(
                    f"conflicting translations for source {item.source_text!r}: "
                    f"{previous.relative_path}:{previous.line} "
                    f"[{previous.segment_id}] -> {previous.target_text!r}; "
                    f"{item.relative_path}:{item.line} "
                    f"[{item.segment_id}] -> {item.target_text!r}"
                )
        language = renpy_language_identifier(catalog.language)
        path = output / "game" / "tl" / language / "hanengine_translations.rpy"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Generated by HanEngine; source project remains unchanged.", ""]
        # Ren'Py indexes string translations by the old text globally. Repeating
        # an old value in separate blocks causes a runtime duplicate-translation
        # error. Identical targets are deduplicated; conflicts fail above.
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
            "# HanEngine desktop controls the language at launch; no in-game menu is added.",
            _LANGUAGE_OVERRIDE_HEADER,
            *_LANGUAGE_OVERRIDE_LINES,
            "",
        ]
        activation_text = "\n".join(activation_lines)
        validate_renpy_language_activation_text(
            activation_text,
            expected_language=language,
        )
        activation_path.write_text(activation_text, encoding="utf-8", newline="\n")
        activation_content = activation_path.read_bytes()
        copied_fonts, font_config_path = self._write_fonts(
            output,
            language,
            translated,
            paths,
            probes,
        )
        generated_paths = (path, activation_path)
        if font_config_path is not None:
            generated_paths += (font_config_path,)
        generated_paths += copied_fonts
        return RenPyBuildResult(
            path,
            hashlib.sha256(content).hexdigest(),
            activation_path,
            hashlib.sha256(activation_content).hexdigest(),
            len(unique_translated),
            generated_paths,
        )

    @staticmethod
    def _write_fonts(
        output: Path,
        language: str,
        translated: Iterable[RenPySegment],
        font_paths: Iterable[Path],
        font_probe_texts: Iterable[str],
    ) -> tuple[tuple[Path, ...], Path | None]:
        paths = tuple(font_paths)
        if not paths:
            return (), None
        resolved_paths: list[Path] = []
        names: set[str] = set()
        for path in paths:
            if not isinstance(path, Path):
                raise TypeError("font_paths must contain Path values")
            candidate = path.expanduser()
            if candidate.is_symlink():
                raise ValueError("font must not be a symbolic link")
            resolved = candidate.resolve(strict=True)
            if (
                not resolved.is_file()
                or resolved.suffix.casefold() not in {".ttf", ".otf"}
            ):
                raise ValueError("font must be an existing non-symlink .ttf or .otf file")
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", resolved.name)
            if not name or name in {".", ".."}:
                raise ValueError("font filename cannot be sanitized safely")
            folded = name.casefold()
            if folded in names:
                raise ValueError("font filenames collide after sanitization")
            names.add(folded)
            resolved_paths.append(resolved)

        required_texts = tuple(item.target_text or "" for item in translated) + tuple(
            font_probe_texts
        )
        required = {
            ord(character)
            for text in required_texts
            for character in text
            if not character.isspace() and ord(character) >= 0x20
        }
        coverage = tuple(_font_unicode_coverage(path) for path in resolved_paths)
        missing = sorted(
            codepoint
            for codepoint in required
            if not any(codepoint in table for table in coverage)
        )
        if missing:
            preview = ", ".join(f"U+{codepoint:04X}" for codepoint in missing[:8])
            scope = (
                "translated text and runtime probes"
                if font_probe_texts
                else "translated text"
            )
            raise ValueError(
                f"configured fonts do not cover {scope}: {preview}"
            )

        font_directory = output / Path(*_FONT_DIRECTORY.parts)
        font_directory.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        references: list[str] = []
        for resolved in resolved_paths:
            destination = font_directory / re.sub(r"[^A-Za-z0-9._-]+", "_", resolved.name)
            shutil.copy2(resolved, destination)
            copied.append(destination)
            references.append(f"{_FONT_DIRECTORY.name}/{destination.name}")

        assigned: set[int] = set()
        config_lines = [
            "# Generated by HanEngine; source project remains unchanged.",
            f"translate {language} python:",
            _FONT_GROUP_INIT,
        ]
        for reference, table in zip(references, coverage):
            available = (required & table) - assigned
            ranges = _codepoint_ranges(available)
            assigned.update(available)
            for start, end in ranges:
                config_lines.append(
                    f"    _hanengine_font_group.add({_quote(reference)}, {hex(start)}, {hex(end)})"
                )
        fallback = references[-1]
        config_lines.append(f"    _hanengine_font_group.add({_quote(fallback)}, None, None)")
        config_lines.extend([_FONT_GROUP_ASSIGNMENT, ""])
        config_text = "\n".join(config_lines)
        validate_renpy_font_config_text(config_text, expected_language=language)
        font_config_path = output / Path(*_FONT_CONFIG_PATH.parts)
        font_config_path.write_text(config_text, encoding="utf-8", newline="\n")
        return tuple(copied), font_config_path


__all__ = [
    "RenPyBuildResult",
    "RenPyCatalog",
    "RenPyExtractor",
    "RenPySegment",
    "RenPyUnhandledItem",
    "RenPyValidationError",
    "RenPyWriter",
    "renpy_language_identifier",
    "renpy_project_files",
    "validate_renpy_placeholders",
    "validate_renpy_language_activation_text",
    "validate_renpy_font_config_text",
    "validate_renpy_translation_text",
]
