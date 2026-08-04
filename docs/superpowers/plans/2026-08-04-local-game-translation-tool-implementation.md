# Local Game Translation Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dependency-free Python utility that safely applies a local JSON translation dictionary to plaintext, CSV, and JSON game resources through both a CLI and a minimal tkinter GUI.

**Architecture:** `translator.py` owns all decoding, format-aware transformations, previews, placeholder warnings, and atomic output. `cli.py` and `gui.py` are thin adapters over the same `process_resource()` function. Tests use only `unittest`, temporary directories, and real filesystem/subprocess behavior.

**Tech Stack:** Python 3.10+, standard library (`argparse`, `csv`, `dataclasses`, `json`, `pathlib`, `re`, `tempfile`, `tkinter`, `unittest`).

## Global Constraints

- No runtime third-party dependencies and no network calls.
- Only `.txt`, `.ks`, `.rpy`, `.script`, `.csv`, and `.json` plaintext resources are supported.
- Read UTF-8 BOM, UTF-8, CP932, and Shift-JIS; write UTF-8 without BOM.
- Never overwrite the source resource; generated outputs use atomic replacement.
- JSON object keys are never translated; CSV cells use exact matching; plaintext uses one-pass longest-key-first inline matching.
- The GUI follows `docs/design-assets/tkinter-gui-option-2.png`: warm off-white surface, dark ink text, thin separators, muted red primary action, and a large log area.
- The ethical-use notice appears in CLI help, GUI, and README.

---

## File Map

- Create `translator.py`: reusable domain model and translation pipeline.
- Create `cli.py`: argument parsing, previews, summary, and exit codes.
- Create `gui.py`: selected tkinter/ttk visual direction and file-driven workflow.
- Create `tests/test_translator.py`: unit and filesystem integration coverage.
- Create `tests/test_cli.py`: subprocess CLI coverage.
- Create `tests/test_gui.py`: import and non-window helper coverage.
- Create `examples/dictionary.json`: editable translation template.
- Create `examples/game.json`: offline end-to-end sample resource.
- Create `README.md`: scope, dictionary preparation, commands, outputs, limitations, and ethics.
- Modify `.gitignore`: retain `.worktrees/` and ignore Python caches and generated example outputs.

---

### Task 1: Core Models, Encoding, Dictionary Validation, and Placeholders

**Files:**
- Create: `translator.py`
- Create: `tests/__init__.py`
- Create: `tests/test_translator.py`

**Interfaces:**
- Produces: `TranslationError`, `MatchPreview`, `UnmatchedPreview`, `PlaceholderWarning`, `TransformResult`, `ProcessingResult` dataclasses.
- Produces: `decode_bytes(data: bytes) -> tuple[str, str]`.
- Produces: `load_translation_dictionary(path: str | Path) -> dict[str, str]`.
- Produces: `missing_placeholders(source: str, translated: str) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing encoding and validation tests**

```python
import json
import tempfile
import unittest
from pathlib import Path

from translator import TranslationError, decode_bytes, load_translation_dictionary, missing_placeholders


class EncodingAndDictionaryTests(unittest.TestCase):
    def test_decode_bytes_supports_utf8_bom_and_cp932(self):
        self.assertEqual(decode_bytes("開始".encode("utf-8-sig")), ("開始", "utf-8-sig"))
        self.assertEqual(decode_bytes("ゲーム開始".encode("cp932")), ("ゲーム開始", "cp932"))

    def test_dictionary_requires_nonempty_string_keys_and_string_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "dictionary.json")
            path.write_text(json.dumps({"": "空"}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(TranslationError, "不能为空"):
                load_translation_dictionary(path)

            path.write_text(json.dumps({"Start": 1}), encoding="utf-8")
            with self.assertRaisesRegex(TranslationError, "字符串"):
                load_translation_dictionary(path)

    def test_placeholder_check_reports_only_missing_occurrences(self):
        self.assertEqual(
            missing_placeholders("Hello {name}, %1\\n", "你好 %1，{name}\\n"),
            (),
        )
        self.assertEqual(
            missing_placeholders("HP %1 / %1", "生命值 %1"),
            ("%1",),
        )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_translator.EncodingAndDictionaryTests -v`

Expected: import failure because `translator.py` does not exist.

- [ ] **Step 3: Implement the minimal public models and helpers**

```python
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
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m unittest tests.test_translator.EncodingAndDictionaryTests -v`

Expected: 3 tests pass.

- [ ] **Step 5: Commit the core foundation**

```powershell
git add translator.py tests/__init__.py tests/test_translator.py
git commit -m "feat: add translation core models and encoding"
```

---

### Task 2: JSON, CSV, and Plaintext Transformations

**Files:**
- Modify: `translator.py`
- Modify: `tests/test_translator.py`

**Interfaces:**
- Consumes: Task 1 dataclasses and `missing_placeholders()`.
- Produces: `transform_json(text: str, dictionary: dict[str, str]) -> TransformResult`.
- Produces: `transform_csv(text: str, dictionary: dict[str, str]) -> TransformResult`.
- Produces: `transform_plaintext(text: str, dictionary: dict[str, str], label: str = "TXT") -> TransformResult`.

- [ ] **Step 1: Add failing format-aware transformation tests**

```python
from translator import transform_csv, transform_json, transform_plaintext


class TransformationTests(unittest.TestCase):
    def test_json_changes_only_string_values_and_reports_json_paths(self):
        source = '{"New Game": "New Game", "menu": [{"label": "Options"}]}'
        result = transform_json(source, {"New Game": "新游戏"})
        parsed = json.loads(result.content)
        self.assertEqual(parsed["New Game"], "新游戏")
        self.assertEqual(parsed["menu"][0]["label"], "Options")
        self.assertIn("New Game", parsed)
        self.assertEqual(result.matches[0].location, "JSON $['New Game']")
        self.assertEqual(result.unmatched[0].location, "JSON $.menu[0].label")

    def test_csv_sniffs_semicolon_and_matches_complete_cells(self):
        result = transform_csv("id;text\n1;New Game\n2;Options\n", {"New Game": "新游戏"})
        self.assertIn("1;新游戏", result.content)
        self.assertEqual(result.replacement_count, 1)
        self.assertIn("CSV 第 3 行第 2 列", [item.location for item in result.unmatched])

    def test_plaintext_uses_single_pass_longest_first_matching(self):
        result = transform_plaintext(
            "Start New Game, {name}!\nOptions\n",
            {"Start": "开始", "New Game": "新游戏", "Start New Game, {name}!": "开始新游戏，{name}！"},
        )
        self.assertEqual(result.content.splitlines()[0], "开始新游戏，{name}！")
        self.assertEqual(result.replacement_count, 1)
        self.assertEqual(result.matches[0].location, "TXT 第 1 行")
        self.assertEqual(result.untranslated, {"Options": ""})
```

- [ ] **Step 2: Run transformation tests and verify RED**

Run: `python -m unittest tests.test_translator.TransformationTests -v`

Expected: import failure for the three transformation functions.

- [ ] **Step 3: Implement common recording and candidate filtering**

```python
import csv
import io
from typing import Any


CANDIDATE_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]")
URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|\.{1,2}[\\/])")


def is_translation_candidate(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped and CANDIDATE_RE.search(stripped) and not URL_RE.match(stripped) and not PATH_RE.match(stripped))


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
```

- [ ] **Step 4: Implement JSON, CSV, and plaintext functions**

```python
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

        def replace(match: re.Match[str]) -> str:
            original = match.group(0)
            translated = dictionary[original]
            result.matched_keys.add(original)
            result.replacement_count += 1
            result.matches.append(MatchPreview(location, original, translated))
            missing = missing_placeholders(original, translated)
            if missing:
                result.warnings.append(PlaceholderWarning(location, original, translated, missing))
            return translated

        translated_line = pattern.sub(replace, line) if pattern else line
        output_lines.append(translated_line)
        candidate = translated_line.strip()
        if candidate not in dictionary.values() and is_translation_candidate(candidate):
            if not result.matches or result.matches[-1].location != location or re.search(r"[A-Za-z\u3040-\u30ff]", candidate):
                result.untranslated.setdefault(candidate, "")
                result.unmatched.append(UnmatchedPreview(location, candidate))
    result.content = "".join(output_lines)
    return result
```

- [ ] **Step 5: Run all transformer tests and verify GREEN**

Run: `python -m unittest tests.test_translator -v`

Expected: 6 tests pass.

- [ ] **Step 6: Commit format-aware transformations**

```powershell
git add translator.py tests/test_translator.py
git commit -m "feat: transform json csv and text resources"
```

---

### Task 3: Safe End-to-End File Processing

**Files:**
- Modify: `translator.py`
- Modify: `tests/test_translator.py`

**Interfaces:**
- Consumes: Task 1 dictionary loader and Task 2 transformers.
- Produces: `default_output_paths(resource_path: str | Path) -> tuple[Path, Path]`.
- Produces: `atomic_write_text(path: Path, content: str) -> None`.
- Produces: `process_resource(resource_path, dictionary_path, output_path=None, untranslated_path=None) -> ProcessingResult`.

- [ ] **Step 1: Add failing filesystem integration tests**

```python
from translator import default_output_paths, process_resource


class ProcessingTests(unittest.TestCase):
    def test_default_paths_and_json_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.json"
            dictionary = root / "dictionary.json"
            resource.write_text('{"title":"New Game","missing":"Options"}', encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")
            result = process_resource(resource, dictionary)
            self.assertEqual(result.output_path, root / "game.zh.json")
            self.assertEqual(result.untranslated_path, root / "game.untranslated.json")
            self.assertEqual(json.loads(result.output_path.read_text(encoding="utf-8"))["title"], "新游戏")
            self.assertEqual(json.loads(result.untranslated_path.read_text(encoding="utf-8")), {"Options": ""})

    def test_process_resource_rejects_source_as_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text('{"New Game":"新游戏"}', encoding="utf-8")
            with self.assertRaisesRegex(TranslationError, "不能覆盖源文件"):
                process_resource(resource, dictionary, output_path=resource)

    def test_unsupported_extension_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.exe"
            dictionary = root / "dictionary.json"
            resource.write_bytes(b"not a resource")
            dictionary.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(TranslationError, "不支持"):
                process_resource(resource, dictionary)
            self.assertFalse((root / "game.zh.exe").exists())
```

- [ ] **Step 2: Run processing tests and verify RED**

Run: `python -m unittest tests.test_translator.ProcessingTests -v`

Expected: import failure for `default_output_paths` and `process_resource`.

- [ ] **Step 3: Implement path resolution, atomic writes, and dispatch**

```python
import os
import tempfile


def default_output_paths(resource_path: str | Path) -> tuple[Path, Path]:
    resource = Path(resource_path)
    return (
        resource.with_name(f"{resource.stem}.zh{resource.suffix}"),
        resource.with_name(f"{resource.stem}.untranslated.json"),
    )


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
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
    output = Path(output_path) if output_path else default_output
    untranslated_output = Path(untranslated_path) if untranslated_path else default_untranslated
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
```

- [ ] **Step 4: Run all core tests and verify GREEN**

Run: `python -m unittest tests.test_translator -v`

Expected: 9 tests pass and no temporary files remain.

- [ ] **Step 5: Commit the safe processing pipeline**

```powershell
git add translator.py tests/test_translator.py
git commit -m "feat: add safe resource processing pipeline"
```

---

### Task 4: Command-Line Interface and Preview Formatting

**Files:**
- Create: `cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `translator.process_resource()` and Task 1 result dataclasses.
- Produces: `format_result(result: ProcessingResult, preview_limit: int = 50) -> str`.
- Produces: `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write failing CLI tests**

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_cli_processes_resource_and_prints_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.json"
            dictionary = root / "dictionary.json"
            resource.write_text('{"title":"New Game","other":"Options"}', encoding="utf-8")
            dictionary.write_text(json.dumps({"New Game": "新游戏"}, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), str(resource), str(dictionary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("[匹配]", completed.stdout)
            self.assertIn("实际替换: 1", completed.stdout)
            self.assertIn("未翻译条目: 1", completed.stdout)

    def test_cli_returns_nonzero_for_invalid_dictionary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "game.txt"
            dictionary = root / "dictionary.json"
            resource.write_text("New Game", encoding="utf-8")
            dictionary.write_text("[]", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), str(resource), str(dictionary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("错误:", completed.stderr)
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `python -m unittest tests.test_cli -v`

Expected: both tests fail because `cli.py` does not exist.

- [ ] **Step 3: Implement argparse, previews, summary, and ethical help text**

```python
from __future__ import annotations

import argparse
import sys

from translator import ProcessingResult, TranslationError, process_resource


ETHICS = "仅用于合法拥有或已获授权的游戏资源；不支持破解、解密或绕过保护。"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"轻量级本地游戏汉化辅助工具。{ETHICS}")
    parser.add_argument("resource", help="明文资源文件（TXT/KS/RPY/SCRIPT/CSV/JSON）")
    parser.add_argument("dictionary", help="UTF-8 JSON 翻译字典")
    parser.add_argument("--output", help="汉化资源输出路径")
    parser.add_argument("--untranslated", help="未翻译 JSON 清单输出路径")
    return parser


def format_result(result: ProcessingResult, preview_limit: int = 50) -> str:
    lines: list[str] = []
    for item in result.matches[:preview_limit]:
        lines.append(f'[匹配] {item.location}: "{item.original}" -> "{item.translated}"')
    if len(result.matches) > preview_limit:
        lines.append(f"[匹配] 另有 {len(result.matches) - preview_limit} 项已省略")
    for item in result.unmatched[:preview_limit]:
        lines.append(f'[未匹配] {item.location}: "{item.original}"')
    if len(result.unmatched) > preview_limit:
        lines.append(f"[未匹配] 另有 {len(result.unmatched) - preview_limit} 项已省略")
    for warning in result.warnings:
        lines.append(f"[占位符警告] {warning.location}: 缺少 {', '.join(warning.missing)}")
    lines.extend(
        [
            f"输入编码: {result.input_encoding}",
            f"输出编码: {result.output_encoding}",
            f"匹配条目: {len(result.matched_keys)}",
            f"实际替换: {result.replacement_count}",
            f"未翻译条目: {len(result.untranslated)}",
            f"占位符警告: {len(result.warnings)}",
            f"汉化文件: {result.output_path}",
            f"待翻译清单: {result.untranslated_path}",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = process_resource(
            args.resource,
            args.dictionary,
            output_path=args.output,
            untranslated_path=args.untranslated,
        )
    except TranslationError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests and help check**

Run: `python -m unittest tests.test_cli -v`

Expected: 2 tests pass.

Run: `python cli.py --help`

Expected: exit 0; help lists positional arguments, both optional output arguments, supported formats, and the legal-use notice.

- [ ] **Step 5: Commit the CLI**

```powershell
git add cli.py tests/test_cli.py
git commit -m "feat: add command line interface"
```

---

### Task 5: Minimal tkinter GUI in the Selected Visual Direction

**Files:**
- Create: `gui.py`
- Create: `tests/test_gui.py`
- Reference: `docs/design-assets/tkinter-gui-option-2.png`

**Interfaces:**
- Consumes: `translator.process_resource()` and `cli.format_result()`.
- Produces: `GameTranslatorApp(tk.Tk)` with `choose_resource()`, `choose_dictionary()`, `run_translation()`, and `_append_log()`.
- Produces: `main() -> None`.

- [ ] **Step 1: Write a failing import and theme-contract test**

```python
import unittest

import gui


class GuiTests(unittest.TestCase):
    def test_gui_exports_app_entrypoint_and_selected_palette(self):
        self.assertTrue(callable(gui.main))
        self.assertEqual(gui.PALETTE["background"], "#f7f3ec")
        self.assertEqual(gui.PALETTE["primary"], "#c83b2b")
        self.assertEqual(gui.PALETTE["text"], "#242321")
```

- [ ] **Step 2: Run the GUI test and verify RED**

Run: `python -m unittest tests.test_gui -v`

Expected: import failure because `gui.py` does not exist.

- [ ] **Step 3: Implement the selected warm editorial tkinter interface**

Implement these exact visible characteristics from the selected reference:

```python
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from cli import format_result
from translator import TranslationError, process_resource


PALETTE = {
    "background": "#f7f3ec",
    "surface": "#fffdf8",
    "text": "#242321",
    "muted": "#6d6861",
    "border": "#cfc8bd",
    "primary": "#c83b2b",
    "primary_active": "#a92f23",
}
ETHICS = "仅用于合法拥有或已获授权的游戏资源"


class GameTranslatorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.resource_path = tk.StringVar()
        self.dictionary_path = tk.StringVar()
        self._configure_window()
        self._build_layout()

    def _configure_window(self) -> None:
        self.root.title("本地游戏汉化工具")
        self.root.geometry("900x620")
        self.root.minsize(760, 520)
        self.root.configure(bg=PALETTE["background"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TFrame", background=PALETTE["background"])
        style.configure("App.TLabel", background=PALETTE["background"], foreground=PALETTE["text"], font=("Microsoft YaHei UI", 11))
        style.configure("Title.TLabel", background=PALETTE["background"], foreground=PALETTE["text"], font=("Microsoft YaHei UI", 24, "bold"))
        style.configure("Muted.TLabel", background=PALETTE["background"], foreground=PALETTE["muted"], font=("Microsoft YaHei UI", 10))
        style.configure("Primary.TButton", background=PALETTE["primary"], foreground="white", font=("Microsoft YaHei UI", 12, "bold"), padding=(24, 10), borderwidth=0)
        style.map("Primary.TButton", background=[("active", PALETTE["primary_active"]), ("pressed", PALETTE["primary_active"])])

    def _build_layout(self) -> None:
        frame = ttk.Frame(self.root, style="App.TFrame", padding=(32, 22, 32, 18))
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)

        ttk.Label(frame, text="本地游戏汉化工具", style="Title.TLabel").grid(row=0, column=0, columnspan=3, pady=(0, 2))
        ttk.Label(frame, text=ETHICS, style="Muted.TLabel").grid(row=1, column=0, columnspan=3, pady=(0, 20))
        ttk.Separator(frame).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 18))

        ttk.Label(frame, text="选择资源文件", style="App.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 14), pady=6)
        ttk.Entry(frame, textvariable=self.resource_path).grid(row=3, column=1, sticky="ew", pady=6)
        ttk.Button(frame, text="浏览…", command=self.choose_resource).grid(row=3, column=2, padx=(10, 0), pady=6)
        ttk.Label(frame, text="加载翻译字典", style="App.TLabel").grid(row=4, column=0, sticky="w", padx=(0, 14), pady=6)
        ttk.Entry(frame, textvariable=self.dictionary_path).grid(row=4, column=1, sticky="ew", pady=6)
        ttk.Button(frame, text="浏览…", command=self.choose_dictionary).grid(row=4, column=2, padx=(10, 0), pady=6)

        ttk.Button(frame, text="执行汉化", style="Primary.TButton", command=self.run_translation).grid(row=5, column=0, columnspan=3, pady=(20, 18))
        ttk.Label(frame, text="处理日志", style="App.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.log = scrolledtext.ScrolledText(frame, wrap="word", state="disabled", bg=PALETTE["surface"], fg=PALETTE["text"], relief="solid", borderwidth=1, font=("Consolas", 10))
        self.log.grid(row=7, column=0, columnspan=3, sticky="nsew")

    def choose_resource(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("支持的资源", "*.txt *.ks *.rpy *.script *.csv *.json"), ("所有文件", "*.*")])
        if selected:
            self.resource_path.set(selected)

    def choose_dictionary(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("JSON 字典", "*.json"), ("所有文件", "*.*")])
        if selected:
            self.dictionary_path.set(selected)

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def run_translation(self) -> None:
        if not self.resource_path.get() or not self.dictionary_path.get():
            messagebox.showwarning("缺少文件", "请先选择资源文件并加载翻译字典。")
            return
        self._append_log("开始汉化处理…")
        try:
            result = process_resource(self.resource_path.get(), self.dictionary_path.get())
        except TranslationError as exc:
            self._append_log(f"错误: {exc}")
            messagebox.showerror("汉化失败", str(exc))
            return
        self._append_log(format_result(result))
        messagebox.showinfo("汉化完成", f"汉化文件已输出到：\n{result.output_path}")


def main() -> None:
    root = tk.Tk()
    GameTranslatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run GUI import tests and a bounded launch smoke check**

Run: `python -m unittest tests.test_gui -v`

Expected: 1 test passes without creating a window.

Run: `python -c "import tkinter as tk; import gui; r=tk.Tk(); gui.GameTranslatorApp(r); r.update_idletasks(); print(r.geometry()); r.destroy()"`

Expected: exit 0 and a geometry at least `760x520`.

- [ ] **Step 5: Visually compare the live window with the selected reference**

Open `python gui.py` and verify: warm off-white base, centered title and ethical subtitle, two aligned selector rows, one muted-red primary button, thin separators, large white log area, readable Chinese labels, and no extra controls. Record the check in the final verification notes; keep native tkinter differences instead of adding UI dependencies.

- [ ] **Step 6: Commit the GUI**

```powershell
git add gui.py tests/test_gui.py docs/design-assets/tkinter-gui-option-2.png
git commit -m "feat: add minimal tkinter interface"
```

---

### Task 6: Examples, README, and Full Verification

**Files:**
- Create: `examples/dictionary.json`
- Create: `examples/game.json`
- Create: `README.md`
- Create: `.gitignore`

**Interfaces:**
- Consumes: final CLI and GUI commands.
- Produces: copy-ready offline examples and user documentation.

- [ ] **Step 1: Create an example dictionary and resource**

`examples/dictionary.json`:

```json
{
  "New Game": "新游戏",
  "Continue": "继续游戏",
  "Hello, {name}!": "你好，{name}！",
  "こんにちは": "你好"
}
```

`examples/game.json`:

```json
{
  "menu": {
    "start": "New Game",
    "continue": "Continue",
    "options": "Options"
  },
  "dialogue": [
    "Hello, {name}!",
    "こんにちは"
  ]
}
```

- [ ] **Step 2: Write README commands that match the implemented interfaces**

Document exactly:

```powershell
python cli.py examples/game.json examples/dictionary.json
python cli.py game.csv dictionary.json --output translated.csv
python cli.py game.txt dictionary.json --untranslated todo.json
python gui.py
python -m unittest discover -s tests -v
```

Also document the `{原文: 中文}` dictionary format, supported extensions and input encodings, UTF-8 output rule, `.zh` and `.untranslated.json` naming, placeholder warnings, no-network behavior, plaintext-only limits, and the authorization/anti-piracy statement.

- [ ] **Step 3: Add generated-output ignores**

Append the following entries to the existing `.gitignore`, retaining its `.worktrees/` entry:

```gitignore
.worktrees/
__pycache__/
*.py[cod]
examples/*.zh.json
examples/*.untranslated.json
```

- [ ] **Step 4: Run the complete automated suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass with zero failures and zero errors.

- [ ] **Step 5: Run the example end to end and inspect outputs**

Run: `python cli.py examples/game.json examples/dictionary.json`

Expected: exit 0; four dictionary keys match; `Options` is reported as unmatched; `examples/game.zh.json` and `examples/game.untranslated.json` are valid UTF-8 JSON.

Run: `python -m json.tool examples/game.zh.json > $null; python -m json.tool examples/game.untranslated.json > $null`

Expected: both commands exit 0.

- [ ] **Step 6: Verify source-tree cleanliness and CLI documentation**

Run: `python cli.py --help; git diff --check; git status --short`

Expected: help text matches README, `git diff --check` exits 0, and status lists only intended project files before commit.

- [ ] **Step 7: Commit documentation and examples**

```powershell
git add .gitignore README.md examples/dictionary.json examples/game.json
git commit -m "docs: add usage guide and offline examples"
```

- [ ] **Step 8: Run fresh final verification after the last commit**

Run: `python -m unittest discover -s tests -v; python cli.py examples/game.json examples/dictionary.json; git status --short`

Expected: all tests pass, the example succeeds with the documented statistics, and only ignored generated example outputs remain outside Git tracking.
