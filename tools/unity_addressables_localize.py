"""Localize Unity Addressables string-table bundles into a separate candidate.

This tool is intentionally limited to Unity Localization string-table bundles.
It does not unpack arbitrary assets, patch managed assemblies, or modify the
source project. UnityPy is required because these tables are binary bundles.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import re
import shutil
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import UnityPy
except ImportError as exc:  # pragma: no cover - depends on the local runtime
    raise SystemExit("UnityPy is required: pip install UnityPy") from exc

from game_localizer.hanengine.multiengine import LocalizationCatalog, LocalizationEntry
from game_localizer.hanengine.translation import (
    LocalModelTranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationRouter,
)


ENGLISH_GLOB = "localization-string-tables-english*.bundle"
SIMPLIFIED_CHINESE_GLOB = "localization-string-tables-chinese(simplified)*.bundle"
SUPPORTED_SUFFIX = "/How to Fish_Data/StreamingAssets/aa/StandaloneWindows64"
INLINE_SPLIT_RE = re.compile(r"(\r\n|\r|\n|</?[A-Za-z][^<>\r\n]*>)")


@dataclass(frozen=True)
class TableRecord:
    table_name: str
    entry_id: int
    source_text: str
    object_path_id: int
    table_index: int


def _relative(root: Path, path: Path) -> str:
    return path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix()


def _bundle_directory(project: Path) -> Path:
    path = project / "How to Fish_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64"
    if not path.is_dir():
        raise ValueError("How to Fish Unity Addressables directory was not found")
    return path


def _one_bundle(directory: Path, pattern: str) -> Path:
    matches = tuple(sorted(directory.glob(pattern), key=lambda item: item.name.casefold()))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one bundle matching {pattern!r}, found {len(matches)}")
    return matches[0]


def _table_base(name: str) -> str:
    if name.endswith("_en"):
        return name[:-3]
    if name.endswith("_zh-CN"):
        return name[:-6]
    return name


def _read_tables(bundle: Path) -> tuple[TableRecord, ...]:
    environment = UnityPy.load(str(bundle))
    records: list[TableRecord] = []
    for obj in environment.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        data = obj.read()
        table = getattr(data, "m_TableData", None)
        name = getattr(data, "m_Name", None)
        if not isinstance(name, str) or not isinstance(table, list):
            continue
        table_name = _table_base(name)
        for table_index, item in enumerate(table):
            entry_id = getattr(item, "m_Id", None)
            localized = getattr(item, "m_Localized", None)
            if isinstance(entry_id, int) and isinstance(localized, str):
                records.append(
                    TableRecord(
                        table_name,
                        entry_id,
                        localized,
                        int(obj.path_id),
                        table_index,
                    )
                )
    if not records:
        raise ValueError(f"no Unity Localization string-table records found in {bundle.name}")
    return tuple(records)


def _project_fingerprint(files: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.name.casefold()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def extract_catalog(project: Path) -> LocalizationCatalog:
    project = project.resolve(strict=True)
    directory = _bundle_directory(project)
    english = _one_bundle(directory, ENGLISH_GLOB)
    records = _read_tables(english)
    relative = _relative(project, english)
    entries: list[LocalizationEntry] = []
    for record in records:
        identity = f"unity-addressables\0{relative}\0{record.table_name}\0{record.entry_id}".encode("utf-8")
        entries.append(
            LocalizationEntry(
                segment_id=f"unity-addressables:{hashlib.sha256(identity).hexdigest()[:24]}",
                relative_path=relative,
                source_text=record.source_text,
                source_hash=hashlib.sha256(record.source_text.encode("utf-8")).hexdigest(),
                kind="unity_addressables_string",
                locator={
                    "type": "unity_addressables_string",
                    "table_name": record.table_name,
                    "entry_id": record.entry_id,
                    "object_path_id": record.object_path_id,
                    "table_index": record.table_index,
                },
            )
        )
    return LocalizationCatalog(
        engine_id="unity_addressables",
        language="zh-CN",
        source_language="en",
        project_fingerprint=_project_fingerprint((english,)),
        files=(relative,),
        entries=tuple(entries),
    )


def _translate_catalog(
    catalog: LocalizationCatalog,
    endpoint: str,
    model: str,
    timeout: float,
    context_prefix: tuple[str, ...] = ("How to Fish",),
) -> LocalizationCatalog:
    router = TranslationRouter(
        (
            LocalModelTranslationProvider(
                endpoint,
                timeout=timeout,
                model_name=model,
            ),
        )
    )
    translations: dict[str, str] = {}
    for index, entry in enumerate(catalog.entries, start=1):
        def translate_part(text: str, part_index: int) -> str:
            leading = text[: len(text) - len(text.lstrip())]
            trailing = text[len(text.rstrip()) :]
            core_end = len(text) - len(trailing) if trailing else len(text)
            core = text[len(leading) : core_end]
            if not core:
                return text
            request = TranslationRequest(
                f"{entry.segment_id}:line:{part_index}",
                core,
                catalog.source_language,
                catalog.language,
                context=(*context_prefix, entry.locator["table_name"])
                if context_prefix
                else (),
            )
            last_error: Exception | None = None
            for _attempt in range(3):
                try:
                    translated = router.translate(request).text
                    return leading + translated + trailing
                except (TranslationProviderError, ValueError, TypeError) as exc:
                    last_error = exc
            assert last_error is not None
            raise RuntimeError(
                f"translation failed at {index}/{len(catalog.entries)} "
                f"({entry.locator['table_name']}:{entry.locator['entry_id']}, line {part_index}): {last_error}"
            ) from last_error

        parts = INLINE_SPLIT_RE.split(entry.source_text)
        translated_parts: list[str] = []
        part_index = 0
        for part in parts:
            if part in {"\r\n", "\r", "\n", ""} or INLINE_SPLIT_RE.fullmatch(part):
                translated_parts.append(part)
                continue
            translated_parts.append(translate_part(part, part_index))
            part_index += 1
        translations[entry.segment_id] = "".join(translated_parts)
    return LocalizationCatalog(
        engine_id=catalog.engine_id,
        language=catalog.language,
        source_language=catalog.source_language,
        project_fingerprint=catalog.project_fingerprint,
        files=catalog.files,
        entries=tuple(
            entry.__class__(
                segment_id=entry.segment_id,
                relative_path=entry.relative_path,
                source_text=entry.source_text,
                source_hash=entry.source_hash,
                kind=entry.kind,
                locator=entry.locator,
                target_text=translations[entry.segment_id],
            )
            for entry in catalog.entries
        ),
    )


def _copy_project(source: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("output candidate already exists; choose a new directory")
    shutil.copytree(source, output, symlinks=False)


def _replace_bundle(bundle: Path, translations: dict[tuple[str, int], str]) -> int:
    # Keep UnityPy's transient output under the short system temp path. On
    # Windows, placing the generated directory beside a deeply nested bundle
    # can exceed the legacy MAX_PATH limit before the final replacement.
    temporary = Path(tempfile.mkdtemp(prefix="hanengine-unity-bundle-"))
    try:
        environment = UnityPy.load(str(bundle))
        changed = 0
        seen: set[tuple[str, int]] = set()
        for obj in environment.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            data = obj.read()
            table = getattr(data, "m_TableData", None)
            name = getattr(data, "m_Name", None)
            if not isinstance(name, str) or not isinstance(table, list):
                continue
            table_name = _table_base(name)
            for item in table:
                entry_id = getattr(item, "m_Id", None)
                key = (table_name, entry_id)
                if key not in translations:
                    continue
                item.m_Localized = translations[key]
                seen.add(key)
                changed += 1
            if any((table_name, getattr(item, "m_Id", None)) in translations for item in table):
                obj.save_typetree(data)
        environment.save(out_path=str(temporary))
        del environment
        gc.collect()
        written = temporary / bundle.name
        if not written.is_file():
            raise RuntimeError(f"UnityPy did not write modified bundle: {bundle.name}")
        if seen != set(translations):
            missing = sorted(set(translations) - seen)
            raise RuntimeError(f"bundle {bundle.name} is missing {len(missing)} translated entries")
        bundle.unlink()
        written.replace(bundle)
        return changed
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _bundle_crc(bundle: Path) -> int:
    """Return the UnityFS CRC used by Addressables catalog entries."""
    raw_file = bundle.read_bytes()
    position = raw_file.index(b"\0") + 1
    _format_version = struct.unpack_from(">I", raw_file, position)[0]
    position += 4
    for _ in range(2):
        position = raw_file.index(b"\0", position) + 1
    _bundle_size, compressed_info_size, uncompressed_info_size, flags = struct.unpack_from(
        ">QIII", raw_file, position
    )
    info_start = (position + 20 + 15) // 16 * 16
    environment = UnityPy.load(str(bundle))
    try:
        bundle_file = environment.file
        info = bundle_file.decompress_data(
            raw_file[info_start : info_start + compressed_info_size],
            uncompressed_info_size,
            flags,
        )
        block_count = struct.unpack_from(">I", info, 16)[0]
        cursor = 20
        blocks: list[tuple[int, int, int]] = []
        for _ in range(block_count):
            uncompressed_size, compressed_size, block_flags = struct.unpack_from(">IIH", info, cursor)
            cursor += 10
            blocks.append((uncompressed_size, compressed_size, block_flags))
        node_count = struct.unpack_from(">I", info, cursor)[0]
        cursor += 4
        for _ in range(node_count):
            cursor += 20
            cursor = info.index(b"\0", cursor) + 1
        data_start = info_start + compressed_info_size
        if flags & 0x200:
            data_start = (data_start + 15) // 16 * 16
        data = bytearray()
        for uncompressed_size, compressed_size, block_flags in blocks:
            data.extend(
                bundle_file.decompress_data(
                    raw_file[data_start : data_start + compressed_size],
                    uncompressed_size,
                    block_flags,
                )
            )
            data_start += compressed_size
        return zlib.crc32(data) & 0xFFFFFFFF
    finally:
        del environment
        gc.collect()


def _update_catalog_crcs(
    project: Path,
    output: Path,
    bundles: tuple[tuple[Path, Path], ...],
) -> dict[str, object]:
    catalog = output / "How to Fish_Data" / "StreamingAssets" / "aa" / "catalog.bin"
    if not catalog.is_file():
        raise RuntimeError("How to Fish Addressables catalog.bin was not found")
    data = bytearray(catalog.read_bytes())
    updates: list[dict[str, object]] = []
    for source_bundle, candidate_bundle in bundles:
        old_crc = _bundle_crc(source_bundle)
        new_crc = _bundle_crc(candidate_bundle)
        old_bytes = struct.pack("<I", old_crc)
        new_bytes = struct.pack("<I", new_crc)
        occurrences = data.count(old_bytes)
        if occurrences == 0:
            raise RuntimeError(f"catalog.bin does not contain CRC for {source_bundle.name}")
        if old_crc != new_crc:
            data = bytearray(data.replace(old_bytes, new_bytes))
        updates.append(
            {
                "bundle": candidate_bundle.name,
                "old_crc": f"{old_crc:08x}",
                "new_crc": f"{new_crc:08x}",
                "occurrences": occurrences,
            }
        )
    catalog.write_bytes(data)
    return {"catalog": _relative(output, catalog), "updates": updates}


def build_candidate(project: Path, output: Path, catalog: LocalizationCatalog) -> dict[str, object]:
    _copy_project(project, output)
    directory = _bundle_directory(output)
    source_directory = _bundle_directory(project)
    _one_bundle(directory, ENGLISH_GLOB)
    chinese = _one_bundle(directory, SIMPLIFIED_CHINESE_GLOB)
    _one_bundle(source_directory, ENGLISH_GLOB)
    source_chinese = _one_bundle(source_directory, SIMPLIFIED_CHINESE_GLOB)
    translations = {
        (str(entry.locator["table_name"]), int(entry.locator["entry_id"])): entry.target_text or ""
        for entry in catalog.entries
    }
    changed_chinese = _replace_bundle(chinese, translations)
    catalog_crcs = _update_catalog_crcs(
        project,
        output,
        ((source_chinese, chinese),),
    )
    return {
        "engine_id": catalog.engine_id,
        "source_bundle": _relative(project, project / Path(catalog.files[0])),
        "candidate": str(output),
        "translated_entries": len(catalog.entries),
        "changed_bundles": [chinese.name],
        "changed_entries": {chinese.name: changed_chinese},
        "catalog_crcs": catalog_crcs,
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Localize How to Fish Unity Addressables string tables with a local HanEngine model")
    parser.add_argument("project")
    parser.add_argument("--output", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/translate")
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve(strict=True)
    output = Path(args.output).expanduser().resolve(strict=False)
    if output == project or project in output.parents:
        raise SystemExit("output candidate must be outside the source project")
    catalog = extract_catalog(project)
    translated = _translate_catalog(catalog, args.endpoint, args.model, args.timeout)
    _write_json(Path(args.catalog).expanduser().resolve(strict=False), translated.to_dict())
    build = build_candidate(project, output, translated)
    report = {
        "schema_version": "hanengine.unity-addressables-report/v1",
        "status": "review_required",
        "project": str(project),
        "model": args.model,
        "endpoint": args.endpoint,
        "quality_notes": {
            "human_review_required": True,
            "reason": "Translation output has not passed a human language-quality review",
        },
        "summary": {
            "segment_count": len(translated.entries),
            "translated_count": sum(entry.target_text is not None for entry in translated.entries),
            "untranslated_count": sum(entry.target_text is None for entry in translated.entries),
        },
        "build": build,
    }
    _write_json(Path(args.report).expanduser().resolve(strict=False), report)
    print(f"Extracted {len(catalog.entries)} Unity Localization entries")
    print(f"Translated {len(translated.entries)} entries with {args.model}")
    print(f"Built candidate: {output}")
    print(f"Catalog: {Path(args.catalog).expanduser().resolve(strict=False)}")
    print(f"Report: {Path(args.report).expanduser().resolve(strict=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
