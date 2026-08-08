from __future__ import annotations

import os
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from game_localizer.adapters.structured import (
    GodotAdapterV1,
    RenPyAdapterV1,
    RpgMakerMVAdapterV1,
    RpgMakerMZAdapterV1,
    UnityAdapterV1,
    UnrealAdapterV1,
)
from game_localizer.adapters.contract import (
    BuildRequest,
    BuildResult,
    DeclaredMode,
    ExtractRequest,
    ExtractResult,
    Operation,
    ValidationRequest,
    ValidationResult,
    VerifyRequest,
    VerifyResult,
)
from game_localizer.hanengine.adapter_runtime import (
    AdapterRuntimeV1,
    AdapterSelection,
    AdapterTaskExecution,
)
from game_localizer.hanengine.core import HanCore
from game_localizer.hanengine.multiengine import (
    LocalizationCatalog,
    LocalizationEntry,
)
from game_localizer.hanengine.pipeline import (
    HanPipelineV1,
    PipelineTranslationOutcome,
    catalog_segments,
)
from game_localizer.hanengine.routing import HanGuard, RiskLevel, RoutePlan
from game_localizer.hanengine.store import (
    HanStore,
    ProjectStore,
    TaskRetrySpec,
    default_data_root,
)
from game_localizer.hanengine.tasks import EventSink, TaskEvent
from game_localizer.hanengine.translation import TranslationProvider


STRUCTURED_ENGINE_IDS = (
    "renpy",
    "rpg_maker_mv",
    "rpg_maker_mz",
    "godot",
    "unity",
    "unreal",
)
_ADAPTER_TYPES = {
    "renpy": RenPyAdapterV1,
    "rpg_maker_mv": RpgMakerMVAdapterV1,
    "rpg_maker_mz": RpgMakerMZAdapterV1,
    "godot": GodotAdapterV1,
    "unity": UnityAdapterV1,
    "unreal": UnrealAdapterV1,
}


class StructuredWorkflowError(RuntimeError):
    pass


class StructuredValidationFailed(StructuredWorkflowError):
    def __init__(self, execution: AdapterTaskExecution):
        super().__init__("Structured localization validation failed")
        self.execution = execution


class StructuredVerificationFailed(StructuredWorkflowError):
    def __init__(self, execution: AdapterTaskExecution):
        super().__init__("Structured localization verification failed")
        self.execution = execution


@dataclass(frozen=True)
class StructuredExtractOutcome:
    selection: AdapterSelection
    execution: AdapterTaskExecution
    catalog: LocalizationCatalog
    state_root: Path


@dataclass(frozen=True)
class StructuredBuildOutcome:
    selection: AdapterSelection
    validation: AdapterTaskExecution
    build: AdapterTaskExecution
    verification: AdapterTaskExecution
    state_root: Path

    @property
    def build_result(self) -> BuildResult:
        result = self.build.result
        if not isinstance(result, BuildResult):
            raise TypeError("build execution does not contain BuildResult")
        return result

    @property
    def verify_result(self) -> VerifyResult:
        result = self.verification.result
        if not isinstance(result, VerifyResult):
            raise TypeError("verification execution does not contain VerifyResult")
        return result


def default_workflow_state_root() -> Path:
    try:
        return default_data_root().resolve(strict=False)
    except RuntimeError:
        return (Path.home() / ".hanengine").resolve(strict=False)


def project_id_for_root(project_root: Path) -> str:
    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a Path")
    resolved = project_root.resolve(strict=False)
    identity = os.path.normcase(str(resolved))
    raw = bytearray(hashlib.sha256(identity.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def format_guard_decision(route: RoutePlan) -> str:
    allowed = ",".join(sorted(item.value for item in route.allowed_operations)) or "none"
    reasons = ",".join(route.decision_reasons) or "policy_and_capability_intersection"
    return (
        f"[HanGuard] phase={route.phase.value} "
        f"risk={route.risk_before.name}->{route.risk_after.name} "
        f"allowed={allowed} reasons={reasons}"
    )


def format_persisted_task_event(event: TaskEvent) -> str:
    prefix = f"[HanTask persisted] {event.task_id} #{event.sequence}"
    if event.progress is not None:
        total = "?" if event.progress.total is None else str(event.progress.total)
        item = "" if event.progress.current_item is None else f" item={event.progress.current_item}"
        return f"{prefix} {event.event_type.value} {event.progress.completed}/{total}{item}"
    step = "" if event.step_id is None else f" step={event.step_id}"
    return f"{prefix} {event.event_type.value}{step} {event.summary}"


def _catalog_from_extract(
    engine_id: str,
    target_language: str,
    source_language: str,
    result: ExtractResult,
) -> LocalizationCatalog:
    entries = []
    for draft in result.segments:
        kind = draft.metadata.get("kind")
        locator = draft.metadata.get("locator")
        relative_path = draft.source_location.relative_path
        if not isinstance(kind, str) or not kind or not isinstance(locator, dict):
            raise StructuredWorkflowError("Extracted segment has invalid engine metadata")
        if relative_path is None:
            raise StructuredWorkflowError("Extracted segment has no resource path")
        entries.append(
            LocalizationEntry(
                segment_id=draft.segment_id,
                relative_path=relative_path,
                source_text=draft.source_text,
                source_hash=draft.source_fingerprint,
                kind=kind,
                locator=locator,
            )
        )
    return LocalizationCatalog(
        engine_id=engine_id,
        language=target_language,
        source_language=source_language,
        project_fingerprint=result.source_tree_fingerprint,
        files=result.read_files,
        entries=tuple(entries),
    )


class StructuredWorkflowSession:
    def __init__(
        self,
        project_root: Path,
        *,
        engine_id: str = "auto",
        target_language: str = "zh-CN",
        source_language: str = "en",
        state_root: Path | None = None,
        declared_mode: DeclaredMode = DeclaredMode.STUDIO,
        user_baseline: RiskLevel = RiskLevel.H0_PROJECT,
        adapter_baseline: RiskLevel = RiskLevel.H0_PROJECT,
        guard: HanGuard | None = None,
        event_listener: EventSink | None = None,
        retry_spec: TaskRetrySpec | None = None,
    ) -> None:
        if not isinstance(project_root, Path):
            raise TypeError("project_root must be a Path")
        self.project_root = project_root.resolve(strict=True)
        if not self.project_root.is_dir():
            raise ValueError("project_root must be a directory")
        if engine_id != "auto" and engine_id not in STRUCTURED_ENGINE_IDS:
            raise ValueError("engine_id is not supported by the structured workflow")
        if not isinstance(target_language, str) or not target_language:
            raise ValueError("target_language must not be empty")
        if not isinstance(source_language, str) or not source_language:
            raise ValueError("source_language must not be empty")
        if not isinstance(declared_mode, DeclaredMode):
            raise TypeError("declared_mode must be a DeclaredMode")
        if not isinstance(user_baseline, RiskLevel):
            raise TypeError("user_baseline must be a RiskLevel")
        if not isinstance(adapter_baseline, RiskLevel):
            raise TypeError("adapter_baseline must be a RiskLevel")
        if guard is not None and not isinstance(guard, HanGuard):
            raise TypeError("guard must be a HanGuard or None")
        if event_listener is not None and not callable(event_listener):
            raise TypeError("event_listener must be callable or None")
        if state_root is not None and not isinstance(state_root, Path):
            raise TypeError("state_root must be a Path or None")
        if retry_spec is not None and not isinstance(retry_spec, TaskRetrySpec):
            raise TypeError("retry_spec must be a TaskRetrySpec or None")

        self.engine_id = engine_id
        self.target_language = target_language
        self.source_language = source_language
        self.declared_mode = declared_mode
        self.user_baseline = user_baseline
        self.adapter_baseline = adapter_baseline
        self.retry_spec = retry_spec
        self.state_root = (
            default_workflow_state_root()
            if state_root is None
            else state_root.expanduser().resolve(strict=False)
        )
        if self.state_root == self.project_root or self.project_root in self.state_root.parents:
            raise ValueError("state_root must be outside the source project")
        self.project_id = project_id_for_root(self.project_root)
        self.store = HanStore(self.state_root)
        self.project_store: ProjectStore | None = None
        try:
            record = self.store.get_project(self.project_id)
            if record is None:
                self.store.create_project(
                    self.project_root.name or "Game project",
                    source_root=self.project_root,
                    project_id=self.project_id,
                )
            elif record.source_root != str(self.project_root):
                raise ValueError("persisted project source root does not match")
            self.project_store = self.store.open_project(self.project_id)
            adapters = tuple(
                adapter_type(
                    target_language=self.target_language,
                    source_language=self.source_language,
                )
                for name, adapter_type in _ADAPTER_TYPES.items()
                if self.engine_id == "auto" or name == self.engine_id
            )
            self.runtime = AdapterRuntimeV1(
                HanCore(self.project_store),
                HanGuard(()) if guard is None else guard,
                adapters,
                event_listener=event_listener,
                retry_spec=retry_spec,
            )
        except Exception:
            if self.project_store is not None:
                self.project_store.close()
            self.store.close()
            raise
        self._selection: AdapterSelection | None = None

    def detect(self) -> AdapterSelection:
        if self._selection is None:
            self._selection = self.runtime.detect(
                self.project_root,
                self.declared_mode,
                user_baseline=self.user_baseline,
                adapter_baseline=self.adapter_baseline,
                declared_adapter_id=(
                    None
                    if self.engine_id == "auto"
                    else self.runtime.registry.adapters[0].metadata.adapter_id
                ),
            )
        return self._selection

    def extract(self) -> StructuredExtractOutcome:
        selection = self.detect()
        working_root = self.state_root / "work" / self.project_id
        working_root.mkdir(parents=True, exist_ok=True)
        execution = self.runtime.run_operation(
            selection,
            Operation.EXTRACT,
            lambda context: ExtractRequest(
                source_root=self.project_root,
                working_root=working_root.resolve(strict=False),
                candidate_encodings=("utf-8", "cp932", "utf-16"),
                filters=(),
                project_id=self.project_id,
                context=context,
            ),
            target_language=self.target_language,
        )
        result = execution.result
        if not isinstance(result, ExtractResult):
            raise TypeError("extract execution does not contain ExtractResult")
        adapter = self.runtime.registry.get(selection.adapter_id)
        selected_engine = getattr(adapter, "engine_id", None)
        if not isinstance(selected_engine, str) or not selected_engine:
            raise StructuredWorkflowError("Selected adapter has no engine ID")
        catalog = _catalog_from_extract(
            selected_engine,
            self.target_language,
            self.source_language,
            result,
        )
        return StructuredExtractOutcome(selection, execution, catalog, self.state_root)

    def build(
        self,
        catalog: LocalizationCatalog,
        output_root: Path,
    ) -> StructuredBuildOutcome:
        if not isinstance(catalog, LocalizationCatalog):
            raise TypeError("catalog must be a LocalizationCatalog")
        if not isinstance(output_root, Path):
            raise TypeError("output_root must be a Path")
        if self.project_store is None:
            raise RuntimeError("workflow session is closed")
        with self.project_store.acquire_project_lock():
            return self._build_unlocked(catalog, output_root)

    def _build_unlocked(
        self,
        catalog: LocalizationCatalog,
        output_root: Path,
    ) -> StructuredBuildOutcome:
        selection = self.detect()
        adapter = self.runtime.registry.get(selection.adapter_id)
        selected_engine = getattr(adapter, "engine_id", None)
        if catalog.engine_id != selected_engine:
            raise ValueError("catalog engine does not match the detected engine")
        originals, translated = catalog_segments(self.project_id, catalog)
        validation = self.runtime.run_operation(
            selection,
            Operation.VALIDATE,
            lambda context: ValidationRequest(
                source_tree_fingerprint=catalog.project_fingerprint,
                original_segments=originals,
                translated_segments=translated,
                target_encoding="utf-8",
                project_rules={},
                context=context,
            ),
        )
        validation_result = validation.result
        if not isinstance(validation_result, ValidationResult):
            raise TypeError("validation execution does not contain ValidationResult")
        if not validation_result.valid:
            raise StructuredValidationFailed(validation)

        staging_root = output_root.expanduser().resolve(strict=False)
        build = self.runtime.run_operation(
            selection,
            Operation.BUILD,
            lambda context: BuildRequest(
                source_root=self.project_root,
                staging_root=staging_root,
                validated_segments=translated,
                source_tree_fingerprint=catalog.project_fingerprint,
                output_options={},
                context=context,
            ),
        )
        build_result = build.result
        if not isinstance(build_result, BuildResult):
            raise TypeError("build execution does not contain BuildResult")
        verification = self.runtime.run_operation(
            selection,
            Operation.VERIFY,
            lambda context: VerifyRequest(
                source_tree_fingerprint=catalog.project_fingerprint,
                staging_root=staging_root,
                manifest=build_result.manifest,
                verification_level="full",
                context=context,
            ),
        )
        verify_result = verification.result
        if not isinstance(verify_result, VerifyResult):
            raise TypeError("verification execution does not contain VerifyResult")
        if not verify_result.passed:
            raise StructuredVerificationFailed(verification)
        return StructuredBuildOutcome(
            selection,
            validation,
            build,
            verification,
            self.state_root,
        )

    def translate(
        self,
        catalog: LocalizationCatalog,
        provider: TranslationProvider,
        *,
        resume: bool = True,
        task_id: str | None = None,
        retry_spec: TaskRetrySpec | None = None,
    ) -> PipelineTranslationOutcome:
        if not isinstance(catalog, LocalizationCatalog):
            raise TypeError("catalog must be a LocalizationCatalog")
        selection = self.detect()
        adapter = self.runtime.registry.get(selection.adapter_id)
        selected_engine = getattr(adapter, "engine_id", None)
        if catalog.engine_id != selected_engine:
            raise ValueError("catalog engine does not match the detected engine")
        pipeline = HanPipelineV1(
            self.runtime.core,
            event_listener=self.runtime.event_listener,
        )
        return pipeline.translate(
            catalog,
            selection.final_route,
            provider,
            resume=resume,
            task_id=task_id,
            retry_spec=self.retry_spec if retry_spec is None else retry_spec,
        )

    def persisted_events(self, task_id: str) -> tuple[TaskEvent, ...]:
        if self.project_store is None:
            raise RuntimeError("workflow session is closed")
        return self.project_store.list_events(task_id)

    def close(self) -> None:
        if self.project_store is not None:
            self.project_store.close()
            self.project_store = None
        self.store.close()

    def __enter__(self) -> StructuredWorkflowSession:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = [
    "STRUCTURED_ENGINE_IDS",
    "StructuredBuildOutcome",
    "StructuredExtractOutcome",
    "StructuredValidationFailed",
    "StructuredVerificationFailed",
    "StructuredWorkflowError",
    "StructuredWorkflowSession",
    "default_workflow_state_root",
    "format_guard_decision",
    "format_persisted_task_event",
    "project_id_for_root",
]
