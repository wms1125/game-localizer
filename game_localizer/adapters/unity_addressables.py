from __future__ import annotations

import gc
import hashlib
import re
import shutil
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from game_localizer.hanengine.multiengine import (
    LocalizationCatalog,
    LocalizationEntry,
)
from game_localizer.hanengine.tasks import TaskCancelled

from .contract import (
    AdapterError,
    AdapterErrorCode,
    AdapterMaturity,
    AdapterMetadata,
    BuildManifestEntry,
    BuildRequest,
    BuildResult,
    DetectionRequest,
    DetectionResult,
    Evidence,
    EvidenceSource,
    ExtractRequest,
    ExtractResult,
    IssueSeverity,
    Operation,
    ValidationIssue,
    VerificationCheck,
    VerifyRequest,
    VerifyResult,
)
from .structured import (
    _BUILD_CAPABILITIES,
    _candidate_fingerprint,
    _copy_project_tree,
    _safe_candidate_path,
    _sha256_file,
    UnityAdapterV1 as PlainUnityAdapterV1,
)


_ENGLISH_BUNDLE = re.compile(r"^localization-string-tables-english.*\.bundle$", re.IGNORECASE)
_SIMPLIFIED_CHINESE_BUNDLE = re.compile(
    r"^localization-string-tables-chinese\(simplified\).*\.bundle$",
    re.IGNORECASE,
)
_ENGLISH_SUFFIX = "_en"
_SIMPLIFIED_CHINESE_SUFFIX = "_zh-cn"


class UnityAddressablesError(ValueError):
    pass


@dataclass(frozen=True)
class _TableRecord:
    table_name: str
    entry_id: int
    text: str
    object_path_id: int
    table_index: int


@dataclass(frozen=True)
class _AddressablesLayout:
    root: Path
    english_bundle: Path
    chinese_bundle: Path
    catalog: Path

    def files(self, project_root: Path) -> tuple[str, ...]:
        return tuple(
            path.relative_to(project_root.resolve(strict=True)).as_posix()
            for path in (self.english_bundle, self.chinese_bundle, self.catalog)
        )

    def localized_files(self, project_root: Path) -> tuple[str, ...]:
        return tuple(
            path.relative_to(project_root.resolve(strict=True)).as_posix()
            for path in (self.chinese_bundle, self.catalog)
        )


@dataclass(frozen=True)
class _AddressablesProfile:
    layout: _AddressablesLayout
    files: tuple[str, ...]
    english_records: tuple[_TableRecord, ...]
    chinese_records: tuple[_TableRecord, ...]
    project_fingerprint: str


def _unitypy_load(path: Path):
    try:
        import UnityPy
    except ImportError as exc:  # pragma: no cover - depends on the local runtime
        raise UnityAddressablesError("UnityPy is required for Unity Localization bundles") from exc
    return UnityPy.load(str(path))


def _is_safe_path(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def _find_layout(project_root: Path) -> _AddressablesLayout | None:
    root = project_root.resolve(strict=True)
    if not (root / "UnityPlayer.dll").is_file() and not any(
        (data_dir / "globalgamemanagers").is_file()
        for data_dir in root.glob("*_Data")
        if data_dir.is_dir() and not data_dir.is_symlink()
    ):
        return None
    layouts: list[_AddressablesLayout] = []
    data_dirs = sorted(
        (path for path in root.glob("*_Data") if path.is_dir() and not path.is_symlink()),
        key=lambda path: path.name.casefold(),
    )
    for data_dir in data_dirs:
        aa_root = data_dir / "StreamingAssets" / "aa"
        catalog = aa_root / "catalog.bin"
        if not aa_root.is_dir() or aa_root.is_symlink() or not catalog.is_file() or catalog.is_symlink():
            continue
        for platform_dir in sorted(aa_root.iterdir(), key=lambda path: path.name.casefold()):
            if not platform_dir.is_dir() or platform_dir.is_symlink():
                continue
            bundles = tuple(
                path
                for path in platform_dir.iterdir()
                if path.is_file() and not path.is_symlink() and path.suffix.casefold() == ".bundle"
            )
            english = tuple(path for path in bundles if _ENGLISH_BUNDLE.fullmatch(path.name))
            chinese = tuple(path for path in bundles if _SIMPLIFIED_CHINESE_BUNDLE.fullmatch(path.name))
            if len(english) == 1 and len(chinese) == 1:
                layout = _AddressablesLayout(aa_root, english[0], chinese[0], catalog)
                if all(
                    _is_safe_path(root, path)
                    for path in (
                        layout.root,
                        layout.english_bundle,
                        layout.chinese_bundle,
                        layout.catalog,
                    )
                ):
                    layouts.append(layout)
    if len(layouts) > 1:
        raise UnityAddressablesError("multiple Unity Localization Addressables profiles were found")
    return layouts[0] if layouts else None


def _table_base(name: str, suffix: str) -> str | None:
    if name.casefold().endswith(suffix):
        return name[: -len(suffix)]
    return None


def _read_tables(bundle: Path, suffix: str) -> tuple[_TableRecord, ...]:
    try:
        environment = _unitypy_load(bundle)
    except UnityAddressablesError:
        raise
    except Exception as exc:
        raise UnityAddressablesError(f"UnityPy could not open {bundle.name}") from exc
    records: list[_TableRecord] = []
    seen: set[tuple[str, int]] = set()
    for obj in environment.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            data = obj.read()
        except Exception as exc:
            raise UnityAddressablesError(f"UnityPy could not read a table in {bundle.name}") from exc
        table = getattr(data, "m_TableData", None)
        name = getattr(data, "m_Name", None)
        if not isinstance(name, str) or not isinstance(table, list):
            continue
        table_name = _table_base(name, suffix)
        if table_name is None:
            continue
        for table_index, item in enumerate(table):
            entry_id = getattr(item, "m_Id", None)
            localized = getattr(item, "m_Localized", None)
            if not isinstance(entry_id, int) or not isinstance(localized, str):
                continue
            identity = (table_name, entry_id)
            if identity in seen:
                raise UnityAddressablesError("a string table contains duplicate entry IDs")
            seen.add(identity)
            records.append(
                _TableRecord(table_name, entry_id, localized, int(obj.path_id), table_index)
            )
    del environment
    gc.collect()
    if not records:
        raise UnityAddressablesError(f"no supported Unity Localization tables found in {bundle.name}")
    return tuple(records)


def _bundle_crc(bundle: Path) -> int:
    raw_file = bundle.read_bytes()
    try:
        position = raw_file.index(b"\0") + 1
        struct.unpack_from(">I", raw_file, position)
        position += 4
        for _ in range(2):
            position = raw_file.index(b"\0", position) + 1
        _bundle_size, compressed_info_size, uncompressed_info_size, flags = struct.unpack_from(
            ">QIII", raw_file, position
        )
    except (ValueError, struct.error) as exc:
        raise UnityAddressablesError(f"invalid UnityFS bundle header: {bundle.name}") from exc
    info_start = (position + 20 + 15) // 16 * 16
    try:
        environment = _unitypy_load(bundle)
    except UnityAddressablesError:
        raise
    except Exception as exc:
        raise UnityAddressablesError(f"UnityPy could not open {bundle.name}") from exc
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
    except Exception as exc:
        raise UnityAddressablesError(f"invalid UnityFS bundle block table: {bundle.name}") from exc
    finally:
        del environment
        gc.collect()


def _fingerprint(root: Path, files: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        path = root / Path(*relative.split("/"))
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def _profile(project_root: Path) -> _AddressablesProfile | None:
    project_root = project_root.resolve(strict=True)
    layout = _find_layout(project_root)
    if layout is None:
        return None
    files = layout.files(project_root)
    english_records = _read_tables(layout.english_bundle, _ENGLISH_SUFFIX)
    chinese_records = _read_tables(layout.chinese_bundle, _SIMPLIFIED_CHINESE_SUFFIX)
    english_keys = {(item.table_name, item.entry_id) for item in english_records}
    chinese_keys = {(item.table_name, item.entry_id) for item in chinese_records}
    if english_keys != chinese_keys:
        raise UnityAddressablesError("English and Simplified Chinese tables have different entry IDs")
    catalog_data = layout.catalog.read_bytes()
    if not catalog_data:
        raise UnityAddressablesError("Addressables catalog.bin is empty")
    for bundle in (layout.english_bundle, layout.chinese_bundle):
        crc = struct.pack("<I", _bundle_crc(bundle))
        if catalog_data.count(crc) != 1:
            raise UnityAddressablesError(
                f"catalog.bin does not contain one unambiguous CRC reference for {bundle.name}"
            )
    return _AddressablesProfile(
        layout,
        files,
        english_records,
        chinese_records,
        _fingerprint(project_root, files),
    )


def _replace_bundle(
    bundle: Path,
    suffix: str,
    translations: dict[tuple[str, int], str],
    context,
    *,
    progress_offset: int,
    progress_total: int,
) -> int:
    temporary = Path(tempfile.mkdtemp(prefix="hanengine-unity-bundle-"))
    try:
        try:
            environment = _unitypy_load(bundle)
        except UnityAddressablesError:
            raise
        except Exception as exc:
            raise UnityAddressablesError(f"UnityPy could not open {bundle.name}") from exc
        changed = 0
        seen: set[tuple[str, int]] = set()
        for obj in environment.objects:
            context.checkpoint()
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                data = obj.read()
            except Exception as exc:
                raise UnityAddressablesError(f"UnityPy could not read a table in {bundle.name}") from exc
            table = getattr(data, "m_TableData", None)
            name = getattr(data, "m_Name", None)
            if not isinstance(name, str) or not isinstance(table, list):
                continue
            table_name = _table_base(name, suffix)
            if table_name is None:
                continue
            object_changed = False
            for item in table:
                context.checkpoint()
                entry_id = getattr(item, "m_Id", None)
                identity = (table_name, entry_id)
                if identity not in translations:
                    continue
                item.m_Localized = translations[identity]
                seen.add(identity)
                changed += 1
                object_changed = True
                context.progress(
                    progress_offset + changed,
                    progress_total,
                    current_item=f"{bundle.name}:{table_name}:{entry_id}",
                )
            if object_changed:
                obj.save_typetree(data)
        environment.save(out_path=str(temporary))
        del environment
        gc.collect()
        written = temporary / bundle.name
        if not written.is_file():
            raise UnityAddressablesError(f"UnityPy did not write modified bundle: {bundle.name}")
        if seen != set(translations):
            raise UnityAddressablesError(f"bundle {bundle.name} is missing translated entries")
        written.replace(bundle)
        return changed
    except (TaskCancelled, UnityAddressablesError):
        raise
    except Exception as exc:
        raise UnityAddressablesError(f"UnityPy could not rebuild {bundle.name}") from exc
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _update_catalog(
    source_catalog: Path,
    candidate_catalog: Path,
    source_bundles: tuple[Path, ...],
    candidate_bundles: tuple[Path, ...],
) -> None:
    if candidate_catalog.read_bytes() != source_catalog.read_bytes():
        raise UnityAddressablesError("candidate catalog changed before its bundle CRCs were updated")
    if len(source_bundles) != len(candidate_bundles):
        raise UnityAddressablesError("source and candidate bundle lists do not match")
    original = candidate_catalog.read_bytes()
    replacements: list[tuple[int, bytes]] = []
    for source_bundle, candidate_bundle in zip(source_bundles, candidate_bundles):
        old_crc = struct.pack("<I", _bundle_crc(source_bundle))
        new_crc = struct.pack("<I", _bundle_crc(candidate_bundle))
        if original.count(old_crc) != 1:
            raise UnityAddressablesError(
                f"catalog.bin does not contain one unambiguous CRC reference for {source_bundle.name}"
            )
        replacements.append((original.index(old_crc), new_crc))
    offsets = [offset for offset, _ in replacements]
    if len(offsets) != len(set(offsets)):
        raise UnityAddressablesError("Addressables bundles share one catalog CRC reference")
    data = bytearray(original)
    for offset, new_crc in replacements:
        data[offset : offset + 4] = new_crc
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{candidate_catalog.name}.hanengine.",
        suffix=".tmp",
        dir=str(candidate_catalog.parent),
    )
    temporary = Path(temporary_name)
    try:
        with open(descriptor, "wb", closefd=True) as stream:
            stream.write(data)
        temporary.replace(candidate_catalog)
    finally:
        temporary.unlink(missing_ok=True)


class UnityAddressablesAdapterV1(PlainUnityAdapterV1):
    """Unity adapter with a narrow Unity Localization Addressables profile."""

    metadata = AdapterMetadata(
        adapter_id=PlainUnityAdapterV1.metadata.adapter_id,
        contract_version=PlainUnityAdapterV1.metadata.contract_version,
        adapter_version=PlainUnityAdapterV1.metadata.adapter_version,
        engine_name=PlainUnityAdapterV1.metadata.engine_name,
        supported_engine_versions=PlainUnityAdapterV1.metadata.supported_engine_versions,
        capabilities=_BUILD_CAPABILITIES,
        maturity=AdapterMaturity.BUILD_READY,
        platforms=PlainUnityAdapterV1.metadata.platforms,
        known_limitations=(
            "Packaged Unity support is limited to matching English and Simplified Chinese Unity Localization string tables",
            "Builds write the translated values to the Simplified Chinese bundle and preserve the English bundle",
            "Unity Player, other binary assets, and unrecognized Addressables layouts remain detection-only",
            "Candidate verification checks table structure and catalog CRC references but does not launch the game",
            "Rollback is managed by HanEngine BackupManager",
        ),
    )

    def _supported_profile(self, root: Path) -> _AddressablesProfile | None:
        if self.target_language.casefold() != "zh-cn" or self.source_language.casefold() != "en":
            return None
        try:
            return _profile(root)
        except Exception:
            return None

    def detect(self, request: DetectionRequest) -> DetectionResult | AdapterError:
        if not isinstance(request, DetectionRequest):
            raise TypeError("request must be a DetectionRequest")
        try:
            request.context.checkpoint()
            profile = self._supported_profile(request.input_root)
            if profile is None:
                return super().detect(request)
            source_evidence = self._source_evidence(request.input_root)
            packaged_evidence = self._packaged_evidence(request.input_root)
            relative = profile.layout.root.relative_to(request.input_root.resolve(strict=True)).as_posix()
            evidence = source_evidence + packaged_evidence + (
                Evidence(
                    "unity_localization_addressables",
                    EvidenceSource.FILESYSTEM,
                    relative,
                    0.95,
                    "Matching English and Simplified Chinese Unity Localization tables and catalog CRCs found",
                ),
            )
            request.context.progress(1, 1, current_item=self.engine_id)
            request.context.log(
                "supported Unity Localization Addressables profile detected",
                {"engine_id": self.engine_id, "segments": len(profile.english_records)},
            )
            return DetectionResult(
                matched=True,
                engine_name=self.metadata.engine_name,
                engine_version=self._engine_version(request.input_root, evidence),
                confidence=min(0.99, sum(item.weight for item in evidence)),
                evidence=evidence,
                maturity=AdapterMaturity.BUILD_READY,
                capabilities=self.metadata.capabilities,
                limitations=self.metadata.known_limitations,
                recommended_operation=Operation.DETECT,
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.DETECT,
                AdapterErrorCode.CANCELLED,
                "Engine detection was cancelled",
                recoverable=True,
                cause=exc,
            )
        except OSError as exc:
            return self._error(
                Operation.DETECT,
                AdapterErrorCode.READ_FAILED,
                "Unity Addressables resources could not be inspected",
                recoverable=True,
                cause=exc,
            )

    def extract(self, request: ExtractRequest) -> ExtractResult | AdapterError:
        if not isinstance(request, ExtractRequest):
            raise TypeError("request must be an ExtractRequest")
        profile = self._supported_profile(request.source_root)
        if profile is None:
            return super().extract(request)
        try:
            request.context.checkpoint()
            entries = []
            relative_bundle = profile.layout.english_bundle.relative_to(
                request.source_root.resolve(strict=True)
            ).as_posix()
            for index, record in enumerate(profile.english_records, 1):
                request.context.checkpoint()
                identity = f"unity-addressables\0{relative_bundle}\0{record.table_name}\0{record.entry_id}".encode("utf-8")
                segment_id = f"unity-addressables:{hashlib.sha256(identity).hexdigest()[:24]}"
                entry = LocalizationEntry(
                    segment_id=segment_id,
                    relative_path=relative_bundle,
                    source_text=record.text,
                    source_hash=hashlib.sha256(record.text.encode("utf-8")).hexdigest(),
                    kind="unity_addressables_string",
                    locator={
                        "type": "unity_addressables_string",
                        "table_name": record.table_name,
                        "entry_id": record.entry_id,
                        "object_path_id": record.object_path_id,
                        "table_index": record.table_index,
                    },
                )
                entries.append(entry)
                request.context.progress(
                    index,
                    len(profile.english_records),
                    current_item=f"{record.table_name}:{record.entry_id}",
                )
            catalog = LocalizationCatalog(
                engine_id=self.engine_id,
                language=self.target_language,
                source_language=self.source_language,
                project_fingerprint=profile.project_fingerprint,
                files=profile.files,
                entries=tuple(entries),
            )
            drafts = tuple(self._entry_to_draft(entry, catalog) for entry in catalog.entries)
            request.context.progress(len(drafts), len(drafts), current_item=self.engine_id)
            request.context.log(
                "Unity Localization Addressables resources extracted",
                {"engine_id": self.engine_id, "files": len(profile.files), "segments": len(drafts)},
            )
            return ExtractResult(
                segments=drafts,
                source_tree_fingerprint=profile.project_fingerprint,
                read_files=profile.files,
                skipped_files=(),
                warnings=("Only Unity Localization English and Simplified Chinese string-table bundles are supported",),
                statistics={"files": len(profile.files), "segments": len(drafts)},
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.EXTRACT,
                AdapterErrorCode.CANCELLED,
                "Unity Addressables extraction was cancelled",
                recoverable=True,
                cause=exc,
            )
        except (OSError, UnityAddressablesError, ValueError, TypeError) as exc:
            return self._error(
                Operation.EXTRACT,
                AdapterErrorCode.UNSUPPORTED_INPUT,
                "Supported Unity Localization tables could not be extracted",
                recoverable=False,
                cause=exc,
            )

    @staticmethod
    def _addressables_segments(request: BuildRequest) -> bool:
        return any(
            segment.metadata.get("kind") == "unity_addressables_string"
            for segment in request.validated_segments
        )

    def build(self, request: BuildRequest) -> BuildResult | AdapterError:
        if not isinstance(request, BuildRequest):
            raise TypeError("request must be a BuildRequest")
        if not self._addressables_segments(request):
            return super().build(request)
        temporary: Path | None = None
        removed_placeholder = False
        try:
            request.context.checkpoint()
            catalog = self._catalog_from_segments(request)
            if catalog.language.casefold() != "zh-cn" or catalog.source_language.casefold() != "en":
                raise UnityAddressablesError("this Addressables profile supports only en to zh-CN")
            profile = _profile(request.source_root)
            if profile is None or profile.project_fingerprint != request.source_tree_fingerprint:
                raise UnityAddressablesError("source Addressables resources changed since extraction")
            translations: dict[tuple[str, int], str] = {}
            for entry in catalog.entries:
                request.context.checkpoint()
                if entry.kind != "unity_addressables_string" or entry.target_text is None:
                    raise UnityAddressablesError("Addressables catalog contains an unsupported entry")
                table_name = entry.locator.get("table_name")
                entry_id = entry.locator.get("entry_id")
                if not isinstance(table_name, str) or not isinstance(entry_id, int):
                    raise UnityAddressablesError("Addressables entry locator is invalid")
                if (table_name, entry_id) in translations:
                    raise UnityAddressablesError("Addressables catalog contains duplicate entry IDs")
                translations[(table_name, entry_id)] = entry.target_text
            if set(translations) != {(item.table_name, item.entry_id) for item in profile.english_records}:
                raise UnityAddressablesError("translated catalog does not match extracted string-table entries")

            output = request.staging_root
            if output.exists():
                if output.is_symlink() or not output.is_dir() or next(output.iterdir(), None) is not None:
                    raise UnityAddressablesError("output root already exists and is not empty")
                removed_placeholder = True
            output.parent.mkdir(parents=True, exist_ok=True)
            # Keep the copied tree under the system temp directory.  A Unity
            # Addressables path plus a user-chosen candidate name can exceed
            # Windows' legacy MAX_PATH limit when the staging tree sits next
            # to the output directory.
            temporary = Path(tempfile.mkdtemp(prefix="hnu-addr-"))
            _copy_project_tree(request.source_root.resolve(strict=True), temporary, request.context)
            candidate_profile = _profile(temporary)
            if candidate_profile is None:
                raise UnityAddressablesError("copied candidate lost its supported Addressables profile")
            if candidate_profile.project_fingerprint != profile.project_fingerprint:
                raise UnityAddressablesError("source Addressables resources changed while the candidate was copied")
            progress_total = len(translations)
            request.context.progress(0, progress_total, current_item="Unity Localization tables")
            changed_chinese = _replace_bundle(
                candidate_profile.layout.chinese_bundle,
                _SIMPLIFIED_CHINESE_SUFFIX,
                translations,
                request.context,
                progress_offset=0,
                progress_total=progress_total,
            )
            _update_catalog(
                profile.layout.catalog,
                candidate_profile.layout.catalog,
                (profile.layout.chinese_bundle,),
                (candidate_profile.layout.chinese_bundle,),
            )
            checked_candidate = _profile(temporary)
            if checked_candidate is None or not self._tables_match_translations(
                checked_candidate,
                translations,
                profile.english_records,
            ):
                raise UnityAddressablesError(
                    "rebuilt Simplified Chinese table failed read-back or English table changed"
                )
            relative_paths = tuple(sorted(checked_candidate.layout.localized_files(temporary)))
            manifest = tuple(
                BuildManifestEntry(
                    relative_path=relative,
                    change_kind="modified",
                    sha256=_sha256_file(temporary / Path(*relative.split("/"))),
                )
                for relative in relative_paths
            )
            if removed_placeholder:
                output.rmdir()
            temporary.replace(output)
            temporary = None
            request.context.progress(progress_total, progress_total, current_item=self.engine_id)
            request.context.log(
                "Unity Localization Addressables candidate built",
                {
                    "engine_id": self.engine_id,
                    "files": len(relative_paths),
                    "segments": len(translations),
                    "english_entries_preserved": len(profile.english_records),
                    "chinese_entries": changed_chinese,
                },
            )
            return BuildResult(
                generated_files=relative_paths,
                added_files=(),
                modified_files=relative_paths,
                deleted_files=(),
                manifest=manifest,
                artifacts=(),
                candidate_fingerprint=_candidate_fingerprint(manifest),
                warnings=(),
                statistics={
                    "files": len(relative_paths),
                    "segments": len(translations),
                    "english_entries_preserved": len(profile.english_records),
                    "chinese_entries": changed_chinese,
                },
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.BUILD,
                AdapterErrorCode.CANCELLED,
                "Unity Addressables candidate build was cancelled",
                recoverable=True,
                cause=exc,
            )
        except (OSError, UnityAddressablesError, TypeError, ValueError, KeyError) as exc:
            return self._error(
                Operation.BUILD,
                AdapterErrorCode.BUILD_FAILED,
                "Unity Addressables candidate could not be built",
                recoverable=False,
                cause=exc,
            )
        finally:
            if temporary is not None:
                shutil.rmtree(temporary, ignore_errors=True)
            if removed_placeholder and not request.staging_root.exists():
                request.staging_root.mkdir()

    @staticmethod
    def _tables_have_matching_entry_ids(profile: _AddressablesProfile) -> bool:
        english = {(item.table_name, item.entry_id) for item in profile.english_records}
        chinese = {(item.table_name, item.entry_id) for item in profile.chinese_records}
        return bool(english) and english == chinese

    @staticmethod
    def _tables_match_translations(
        profile: _AddressablesProfile,
        translations: dict[tuple[str, int], str],
        original_english_records: tuple[_TableRecord, ...],
    ) -> bool:
        expected_english = {
            (item.table_name, item.entry_id): item.text for item in original_english_records
        }
        actual_english = {
            (item.table_name, item.entry_id): item.text for item in profile.english_records
        }
        actual_chinese = {
            (item.table_name, item.entry_id): item.text for item in profile.chinese_records
        }
        return actual_english == expected_english and actual_chinese == translations

    def verify(self, request: VerifyRequest) -> VerifyResult | AdapterError:
        if not isinstance(request, VerifyRequest):
            raise TypeError("request must be a VerifyRequest")
        try:
            request.context.checkpoint()
            profile = _profile(request.staging_root)
            if profile is None:
                return super().verify(request)
            checks: list[VerificationCheck] = []
            hashes: dict[str, str] = {}
            issues: list[ValidationIssue] = []
            manifest_paths = tuple(sorted(entry.relative_path for entry in request.manifest))
            profile_paths = tuple(sorted(profile.layout.localized_files(request.staging_root)))
            profile_matches = manifest_paths == profile_paths and len(manifest_paths) == len(set(manifest_paths))
            checks.append(
                VerificationCheck(
                    "unity_addressables_manifest",
                    profile_matches,
                    "Manifest covers both localization bundles and catalog.bin" if profile_matches else "Manifest does not match the supported Addressables files",
                )
            )
            passed = profile_matches and bool(request.manifest)
            if not profile_matches:
                issues.append(
                    ValidationIssue(
                        "unity_addressables_manifest_mismatch",
                        IssueSeverity.ERROR,
                        None,
                        None,
                        "The build manifest does not cover the supported Addressables files",
                        False,
                        "Rebuild the candidate with the HanEngine Unity Addressables adapter",
                    )
                )
            for index, entry in enumerate(request.manifest, 1):
                request.context.checkpoint()
                path = _safe_candidate_path(request.staging_root, entry.relative_path)
                exists = path is not None and path.is_file()
                checks.append(
                    VerificationCheck(
                        f"file_exists:{entry.relative_path}",
                        exists,
                        "Candidate file exists" if exists else "Candidate file is missing or unsafe",
                    )
                )
                if not exists:
                    passed = False
                    issues.append(
                        ValidationIssue(
                            "candidate_file_missing",
                            IssueSeverity.ERROR,
                            None,
                            None,
                            "A manifest file is missing or resolves through an unsafe link",
                            False,
                            "Rebuild the candidate in a clean staging directory",
                        )
                    )
                    request.context.progress(index, len(request.manifest), current_item=entry.relative_path)
                    continue
                actual_hash = _sha256_file(path)
                hashes[entry.relative_path] = actual_hash
                matches = actual_hash.casefold() == entry.sha256.casefold()
                checks.append(
                    VerificationCheck(
                        f"sha256:{entry.relative_path}",
                        matches,
                        "Candidate hash matches the manifest" if matches else "Candidate hash differs from the manifest",
                    )
                )
                passed = passed and matches
                if not matches:
                    issues.append(
                        ValidationIssue(
                            "candidate_hash_mismatch",
                            IssueSeverity.ERROR,
                            None,
                            None,
                            "A candidate file hash differs from the build manifest",
                            False,
                            "Discard and rebuild the candidate",
                        )
                    )
                request.context.progress(index, len(request.manifest), current_item=entry.relative_path)
            tables_match = self._tables_have_matching_entry_ids(profile)
            checks.append(
                VerificationCheck(
                    "unity_addressables_table_readback",
                    tables_match,
                    "Both locale tables were read back with matching entry IDs"
                    if tables_match
                    else "Locale table entry IDs differ after build",
                )
            )
            passed = passed and tables_match
            if not tables_match:
                issues.append(
                    ValidationIssue(
                        "unity_addressables_entry_ids_mismatch",
                        IssueSeverity.ERROR,
                        None,
                        None,
                        "English and Simplified Chinese entry IDs differ after build",
                        False,
                        "Rebuild the candidate with matching string-table entries",
                    )
                )
            request.context.log(
                "Unity Localization Addressables candidate verified",
                {"engine_id": self.engine_id, "passed": passed, "files": len(request.manifest)},
            )
            return VerifyResult(
                passed=passed,
                checks=tuple(checks),
                syntax_passed=passed,
                encoding_passed=True,
                artifact_hashes=hashes,
                smoke_test_passed=None,
                issues=tuple(issues),
            )
        except TaskCancelled as exc:
            return self._error(
                Operation.VERIFY,
                AdapterErrorCode.CANCELLED,
                "Unity Addressables candidate verification was cancelled",
                recoverable=True,
                cause=exc,
            )
        except (OSError, UnityAddressablesError, TypeError, ValueError, IndexError, struct.error, RuntimeError) as exc:
            return self._error(
                Operation.VERIFY,
                AdapterErrorCode.VERIFY_FAILED,
                "Unity Addressables candidate could not be verified",
                recoverable=False,
                cause=exc,
            )
