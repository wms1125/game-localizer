from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace

from .core import HanCore, RouteBlockedError
from .multiengine import LocalizationCatalog, LocalizationEntry, extract_placeholders
from .routing import RouteOperation, RoutePlan
from .segments import Segment, SegmentDraft, SourceLocation
from .store import Checkpoint, TaskRetrySpec
from .tasks import EventSink, StepResult, TaskPlan, TaskState, TaskStep
from .translation import (
    TranslationNotFoundError,
    TranslationProvider,
    TranslationRequest,
)


PIPELINE_TRANSLATE_STEP = "pipeline-translate"


class PipelineTranslationError(RuntimeError):
    pass


class PipelineTranslationFailed(PipelineTranslationError):
    def __init__(
        self,
        task: TaskPlan,
        *,
        translated_count: int,
        resumed_count: int,
    ) -> None:
        super().__init__("HanPipelineV1 translation task did not complete")
        self.task = task
        self.translated_count = translated_count
        self.resumed_count = resumed_count


@dataclass(frozen=True)
class PipelineTranslationOutcome:
    task: TaskPlan
    catalog: LocalizationCatalog
    segments: tuple[Segment, ...]
    translated_count: int
    resumed_count: int
    catalog_count: int
    untranslated_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.task, TaskPlan) or self.task.state is not TaskState.COMPLETED:
            raise ValueError("task must be a completed TaskPlan")
        if not isinstance(self.catalog, LocalizationCatalog):
            raise TypeError("catalog must be a LocalizationCatalog")
        segments = tuple(self.segments)
        if any(not isinstance(segment, Segment) for segment in segments):
            raise TypeError("segments must contain Segment values")
        if tuple(segment.segment_id for segment in segments) != tuple(
            entry.segment_id for entry in self.catalog.entries
        ):
            raise ValueError("segments must match catalog entry order")
        for field_name in (
            "translated_count",
            "resumed_count",
            "catalog_count",
            "untranslated_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if (
            self.translated_count
            + self.resumed_count
            + self.catalog_count
            + self.untranslated_count
            != len(self.catalog.entries)
        ):
            raise ValueError("translation counts must cover every catalog entry")
        object.__setattr__(self, "segments", segments)


def catalog_drafts(catalog: LocalizationCatalog) -> tuple[SegmentDraft, ...]:
    if not isinstance(catalog, LocalizationCatalog):
        raise TypeError("catalog must be a LocalizationCatalog")
    return tuple(_draft_from_entry(catalog, entry) for entry in catalog.entries)


def catalog_segments(
    project_id: str,
    catalog: LocalizationCatalog,
) -> tuple[tuple[Segment, ...], tuple[Segment, ...]]:
    originals = tuple(
        Segment.from_draft(project_id, catalog.language, draft)
        for draft in catalog_drafts(catalog)
    )
    translated = tuple(
        replace(
            segment,
            target_text=entry.target_text,
            translation_source=(None if entry.target_text is None else "catalog"),
        )
        for segment, entry in zip(originals, catalog.entries)
    )
    return originals, translated


def _draft_from_entry(
    catalog: LocalizationCatalog,
    entry: LocalizationEntry,
) -> SegmentDraft:
    return SegmentDraft(
        segment_id=entry.segment_id,
        source_text=entry.source_text,
        source_language=catalog.source_language,
        speaker=None,
        context_before=(),
        context_after=(),
        placeholders=extract_placeholders(entry.source_text),
        tags=(catalog.engine_id, entry.kind),
        constraints=("preserve_placeholders",),
        source_location=SourceLocation(
            relative_path=entry.relative_path,
            logical_path=json.dumps(
                entry.locator,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
        source_fingerprint=entry.source_hash,
        ocr_confidence=None,
        region_confidence=None,
        metadata={
            "engine_id": catalog.engine_id,
            "kind": entry.kind,
            "locator": entry.locator,
            "catalog_language": catalog.language,
            "catalog_files": list(catalog.files),
        },
    )


def _catalog_with_segments(
    catalog: LocalizationCatalog,
    segments: tuple[Segment, ...],
) -> LocalizationCatalog:
    by_id = {segment.segment_id: segment for segment in segments}
    entries = tuple(
        replace(entry, target_text=by_id[entry.segment_id].target_text)
        for entry in catalog.entries
    )
    return replace(catalog, entries=entries)


def _translation_context(segment: Segment) -> tuple[str, ...]:
    items = list(segment.context_before)
    if segment.speaker:
        items.append(f"speaker: {segment.speaker}")
    items.extend(segment.context_after)
    return tuple(items)


class HanPipelineV1:
    def __init__(self, core: HanCore, *, event_listener: EventSink | None = None) -> None:
        if not isinstance(core, HanCore):
            raise TypeError("core must be a HanCore")
        if event_listener is not None and not callable(event_listener):
            raise TypeError("event_listener must be callable or None")
        self.core = core
        self.event_listener = event_listener

    def translate(
        self,
        catalog: LocalizationCatalog,
        route: RoutePlan,
        provider: TranslationProvider,
        *,
        resume: bool = True,
        task_id: str | None = None,
        retry_spec: TaskRetrySpec | None = None,
    ) -> PipelineTranslationOutcome:
        if not isinstance(catalog, LocalizationCatalog):
            raise TypeError("catalog must be a LocalizationCatalog")
        if not isinstance(route, RoutePlan):
            raise TypeError("route must be a RoutePlan")
        if not callable(getattr(provider, "translate", None)):
            raise TypeError("provider must implement translate")
        if not isinstance(resume, bool):
            raise TypeError("resume must be a bool")
        if retry_spec is not None and not isinstance(retry_spec, TaskRetrySpec):
            raise TypeError("retry_spec must be a TaskRetrySpec or None")
        required_operations = frozenset(
            {RouteOperation.EXTRACT, RouteOperation.VALIDATE}
        )
        if not required_operations <= route.allowed_operations:
            missing = sorted(
                item.value for item in required_operations - route.allowed_operations
            )
            raise RouteBlockedError(
                "route does not authorize pipeline translation: " + ",".join(missing)
            )

        lease = self.core.store.acquire_project_lock()
        try:
            task = self.core.create_task(
                kind="pipeline-translate",
                route=route,
                task_id=task_id,
                steps=(
                    TaskStep(
                        PIPELINE_TRANSLATE_STEP,
                        "Translate localization segments",
                        RouteOperation.VALIDATE,
                    ),
                ),
            )
            lease.bind_task(task.task_id)
            if retry_spec is not None:
                self.core.store.save_task_retry_spec(task.task_id, retry_spec)
        except Exception:
            lease.close()
            raise
        completed_segments: list[Segment] = []
        counts = {
            "translated": 0,
            "resumed": 0,
            "catalog": 0,
            "untranslated": 0,
        }

        def handler(context) -> StepResult:
            segments = self.core.ingest_segments(
                catalog_drafts(catalog),
                target_language=catalog.language,
            )
            by_id = {segment.segment_id: segment for segment in segments}
            ordered = tuple(by_id[entry.segment_id] for entry in catalog.entries)
            total = len(catalog.entries)
            context.progress(0, total)
            for index, (entry, persisted) in enumerate(
                zip(catalog.entries, ordered),
                start=1,
            ):
                context.checkpoint()
                result_provider: str | None = None
                result_model: str | None = None
                result_confidence: float | None = None
                if entry.target_text is not None:
                    current = replace(
                        persisted,
                        target_text=entry.target_text,
                        translation_source="catalog",
                    )
                    disposition = "catalog"
                    counts["catalog"] += 1
                elif resume and persisted.target_text is not None:
                    current = persisted
                    disposition = "resumed"
                    counts["resumed"] += 1
                else:
                    request = TranslationRequest(
                        segment_id=persisted.segment_id,
                        text=persisted.source_text,
                        source_language=persisted.source_language,
                        target_language=persisted.target_language,
                        context=_translation_context(persisted),
                    )
                    try:
                        translation = provider.translate(request)
                    except TranslationNotFoundError:
                        metadata = dict(persisted.metadata)
                        metadata.pop("translation", None)
                        current = replace(
                            persisted,
                            target_text=None,
                            translation_source=None,
                            metadata=metadata,
                        )
                        disposition = "untranslated"
                        counts["untranslated"] += 1
                    else:
                        metadata = dict(persisted.metadata)
                        metadata["translation"] = {
                            "provider": translation.provider,
                            "model": translation.model,
                            "confidence": translation.confidence,
                            "cached": translation.cached,
                        }
                        current = replace(
                            persisted,
                            target_text=translation.text,
                            translation_source=(
                                f"{translation.provider}:{translation.model}"
                            ),
                            metadata=metadata,
                        )
                        disposition = "translated"
                        result_provider = translation.provider
                        result_model = translation.model
                        result_confidence = translation.confidence
                        counts["translated"] += 1

                checkpoint = Checkpoint(
                    checkpoint_id=str(uuid.uuid4()),
                    task_id=context.task_id,
                    step_id=context.step_id,
                    sequence=index,
                    payload={
                        "segment_id": current.segment_id,
                        "source_fingerprint": current.source_fingerprint,
                        "completed": index,
                        "total": total,
                        "disposition": disposition,
                        "provider": result_provider,
                        "model": result_model,
                        "confidence": result_confidence,
                    },
                )
                self.core.store.save_segment_checkpoint(current, checkpoint)
                completed_segments.append(current)
                if disposition == "untranslated":
                    context.warning(
                        "No translation was available for segment",
                        {"segment_id": current.segment_id},
                    )
                context.progress(
                    index,
                    total,
                    current_item=entry.relative_path,
                    data={
                        "segment_id": current.segment_id,
                        "disposition": disposition,
                    },
                )
            return StepResult(
                data={
                    "translated": counts["translated"],
                    "resumed": counts["resumed"],
                    "catalog": counts["catalog"],
                    "untranslated": counts["untranslated"],
                    "segments": total,
                }
            )

        try:
            completed = self.core.run_task(
                task,
                route=route,
                handlers={PIPELINE_TRANSLATE_STEP: handler},
                event_listener=self.event_listener,
            )
        finally:
            lease.close()
        if completed.state is not TaskState.COMPLETED:
            raise PipelineTranslationFailed(
                completed,
                translated_count=counts["translated"],
                resumed_count=counts["resumed"],
            )
        segment_items = tuple(completed_segments)
        return PipelineTranslationOutcome(
            task=completed,
            catalog=_catalog_with_segments(catalog, segment_items),
            segments=segment_items,
            translated_count=counts["translated"],
            resumed_count=counts["resumed"],
            catalog_count=counts["catalog"],
            untranslated_count=counts["untranslated"],
        )


__all__ = [
    "HanPipelineV1",
    "PIPELINE_TRANSLATE_STEP",
    "PipelineTranslationError",
    "PipelineTranslationFailed",
    "PipelineTranslationOutcome",
    "catalog_drafts",
    "catalog_segments",
]
