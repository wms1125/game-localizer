from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from .core import HanCore, RouteBlockedError
from .glossary import Glossary
from .multiengine import LocalizationCatalog, LocalizationEntry, extract_placeholders
from .routing import RouteOperation, RoutePlan
from .segments import Segment, SegmentDraft, SourceLocation
from .store import Checkpoint, TaskRetrySpec
from .tasks import EventSink, StepResult, TaskPlan, TaskState, TaskStep
from .translation import (
    TranslationNotFoundError,
    TranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationResult,
    enforce_translation_quality,
    with_terminal_punctuation,
)


PIPELINE_TRANSLATE_STEP = "pipeline-translate"

# How many segments to pack into one provider request.  Measured on the shipped
# 646-segment corpus with qwen2.5:3b: single requests took 0.33s/segment on short
# UI labels, 8-segment batches took 0.09s and 16-segment batches 0.07s.  Longer
# dialogue gains less (1.55x) because output tokens dominate, and batches beyond
# 16 stopped improving.  Anything the batch cannot answer falls back to a single
# request, so this is a speed knob and never a correctness one.
DEFAULT_BATCH_SIZE = 8
MAX_BATCH_SIZE = 32


@dataclass(frozen=True)
class _SegmentTranslation:
    """Outcome of translating one segment, before it is persisted.

    Computed off the main thread so that persistence stays strictly ordered and
    checkpoints keep their original meaning.
    """

    request: TranslationRequest
    translation: object | None = None
    quality_issues: tuple = ()
    error: BaseException | None = None

# Quality-gate rejections that describe a problem with one segment's model
# output.  They fall back to the source text and a review entry instead of
# aborting the whole translation task.  Anything else (provider outages,
# authentication, unexpected errors) still fails the task.
FALLBACK_ERROR_CODES = frozenset(
    {
        "residual_english",
        "physical_newline_mismatch",
        "metadata_contamination",
        "control_character",
        "empty_translation",
        "placeholder_mismatch",
        "rich_text_tag_order_mismatch",
        "rich_text_body_duplication",
        "garbled_replacement_character",
        "glossary_violation",
    }
)

# Failures a targeted re-ask can plausibly fix.  A repair round re-sends only
# these segments with a code-specific instruction, and adopts the new rendering
# only when it clears the gate that rejected the first attempt.  Provider
# outages are deliberately absent: re-asking does not fix a dead endpoint.
REPAIRABLE_ERROR_CODES = frozenset(
    {
        "residual_english",
        "rich_text_body_duplication",
        "rich_text_tag_order_mismatch",
        "placeholder_mismatch",
        "glossary_violation",
        "metadata_contamination",
    }
)

# Warnings that are worth one repair attempt even though they may ship as-is.
REPAIRABLE_WARNING_CODES = frozenset({"length_budget_exceeded"})

_REPAIR_INSTRUCTIONS = {
    "residual_english": (
        "The previous attempt left English words untranslated. Translate every word "
        "into natural Simplified Chinese, including slang, onomatopoeia and UI labels."
    ),
    "rich_text_body_duplication": (
        "The previous attempt repeated the sentence inside or around a markup tag. "
        "Translate the sentence exactly once and keep each tag around its own phrase."
    ),
    "rich_text_tag_order_mismatch": (
        "The previous attempt changed the order of markup tags. Keep every tag in the "
        "same order and position as the source."
    ),
    "placeholder_mismatch": (
        "The previous attempt changed or dropped a placeholder or markup tag. Reproduce "
        "every protected token exactly, in the same order."
    ),
    "glossary_violation": (
        "The previous attempt ignored a pinned glossary term. Use the glossary rendering "
        "exactly for the terms it covers."
    ),
    "metadata_contamination": (
        "The previous attempt echoed request metadata. Return only the translated game "
        "text, with no labels, field names or explanations."
    ),
    "length_budget_exceeded": (
        "The previous attempt is too wide for its UI label. Render it shorter while "
        "keeping the meaning: this string sits in a small button or caption."
    ),
}


class PipelineTranslationError(RuntimeError):
    pass

class PipelineTranslationFailed(PipelineTranslationError):
    def __init__(
        self,
        task: TaskPlan,
        *,
        translated_count: int,
        resumed_count: int,
        partial_catalog: LocalizationCatalog | None = None,
        partial_segments: tuple[Segment, ...] = (),
        failure_code: str | None = None,
        failure_message: str | None = None,
        failure_segment_id: str | None = None,
        failure_retry_count: int = 0,
    ) -> None:
        super().__init__("HanPipelineV1 translation task did not complete")
        self.task = task
        self.translated_count = translated_count
        self.resumed_count = resumed_count
        self.partial_catalog = partial_catalog
        self.partial_segments = tuple(partial_segments)
        self.failure_code = failure_code
        self.failure_message = failure_message
        self.failure_segment_id = failure_segment_id
        self.failure_retry_count = failure_retry_count


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
        replace(
            entry,
            target_text=(
                by_id[entry.segment_id].target_text
                if entry.segment_id in by_id
                else entry.target_text
            ),
        )
        for entry in catalog.entries
    )
    return replace(catalog, entries=entries)


def _translation_context(segment: Segment) -> tuple[str, ...]:
    items = list(segment.context_before)
    if segment.speaker:
        items.append(f"speaker: {segment.speaker}")
    items.extend(segment.context_after)
    return tuple(items)


def _pending_requests(
    catalog: LocalizationCatalog,
    ordered: tuple[Segment, ...],
    *,
    resume: bool,
    reference_translations: Mapping[str, str] | None,
    glossary: Glossary | None = None,
) -> dict[str, TranslationRequest]:
    """Build the requests that actually need a provider call.

    Segments already carrying a catalog or resumed translation are skipped so
    that concurrency is spent only on real work.

    The glossary is split by role.  ``glossary`` on the request carries the terms
    found anywhere in the segment, which is a translation *hint* the model should
    follow when it fits.  ``enforced_terms`` carries only the terms the segment
    *is*, which the quality gate treats as binding.
    """

    pending: dict[str, TranslationRequest] = {}
    for entry, persisted in zip(catalog.entries, ordered):
        if entry.target_text is not None:
            continue
        if resume and persisted.target_text is not None:
            continue
        pending[persisted.segment_id] = TranslationRequest(
            segment_id=persisted.segment_id,
            text=persisted.source_text,
            source_language=persisted.source_language,
            target_language=persisted.target_language,
            context=_translation_context(persisted),
            reference_translation=(
                None
                if reference_translations is None
                else reference_translations.get(persisted.segment_id)
            ),
            glossary=(
                ()
                if glossary is None
                else glossary.match(persisted.source_text)
            ),
            enforced_terms=(
                ()
                if glossary is None
                else glossary.enforceable_terms(persisted.source_text)
            ),
        )
    return pending


def _finish(
    request: TranslationRequest,
    translation: TranslationResult,
) -> _SegmentTranslation:
    """Apply the punctuation rule and the quality gate to one provider answer."""

    try:
        translation = with_terminal_punctuation(request, translation)
        issues = enforce_translation_quality(request, translation)
    except BaseException as exc:  # re-raised in order on the main thread
        return _SegmentTranslation(request=request, error=exc)
    return _SegmentTranslation(
        request=request,
        translation=translation,
        quality_issues=issues,
    )


def _translate_one(
    provider: TranslationProvider,
    request: TranslationRequest,
) -> _SegmentTranslation:
    """Translate one segment.

    Placeholder masking is applied by the provider adapter, not here, so the
    request keeps its real text.  This function only restores sentinels if the
    provider chose to mask, which it signals via ``MaskedTranslation``.
    """

    try:
        translation = provider.translate(request)
    except BaseException as exc:  # re-raised in order on the main thread
        return _SegmentTranslation(request=request, error=exc)
    return _finish(request, translation)


def _translate_batch(
    provider: TranslationProvider,
    requests: list[TranslationRequest],
    *,
    batch_size: int,
    workers: int,
    context,
) -> dict[str, _SegmentTranslation]:
    """Translate pending requests in groups, then finish each one alone.

    Packing many segments into one request amortises the system prompt, which is
    what makes a local model slow on short UI labels.  The quality gate is still
    applied per segment: a batch is only a transport optimisation, and one bad
    line must never decide the fate of its neighbours.
    """

    if not requests:
        return {}
    translate_batch = getattr(provider, "translate_batch", None)
    if translate_batch is None or batch_size <= 1:
        return _translate_pending(
            {request.segment_id: request for request in requests},
            provider,
            workers=workers,
            context=context,
        )

    groups = [
        requests[index : index + batch_size]
        for index in range(0, len(requests), batch_size)
    ]

    def run_group(group: list[TranslationRequest]) -> dict[str, TranslationResult]:
        try:
            return dict(translate_batch(group))
        except BaseException:
            # A failed group is not a failed run: fall back to single requests for
            # exactly those segments, which is what the pre-batch code would do.
            return {}

    answers: dict[str, TranslationResult] = {}
    if workers == 1 or len(groups) == 1:
        for group in groups:
            context.checkpoint()
            answers.update(run_group(group))
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(groups))) as pool:
            futures = [pool.submit(run_group, group) for group in groups]
            for future in futures:
                context.checkpoint()
                answers.update(future.result())

    results: dict[str, _SegmentTranslation] = {}
    leftovers: list[TranslationRequest] = []
    for request in requests:
        answer = answers.get(request.segment_id)
        if answer is None:
            leftovers.append(request)
            continue
        results[request.segment_id] = _finish(request, answer)
    if leftovers:
        results.update(
            _translate_pending(
                {request.segment_id: request for request in leftovers},
                provider,
                workers=workers,
                context=context,
            )
        )
    return results


def _translate_pending(
    pending: dict[str, TranslationRequest],
    provider: TranslationProvider,
    *,
    workers: int,
    context,
) -> dict[str, _SegmentTranslation]:
    """Translate every pending segment, preserving per-segment error identity.

    Provider calls are independent, so they run concurrently; nothing is
    persisted here, which keeps checkpoint ordering and the store single-threaded.
    """

    if not pending:
        return {}
    if workers == 1 or len(pending) == 1:
        results = {}
        for segment_id, request in pending.items():
            context.checkpoint()
            results[segment_id] = _translate_one(provider, request)
        return results

    results: dict[str, _SegmentTranslation] = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as pool:
        futures = {
            segment_id: pool.submit(_translate_one, provider, request)
            for segment_id, request in pending.items()
        }
        for segment_id, future in futures.items():
            context.checkpoint()
            results[segment_id] = future.result()
    return results


def _repair_instruction(item: _SegmentTranslation) -> str | None:
    """Return a targeted re-ask instruction for a repairable outcome."""

    error_code = getattr(item.error, "code", None)
    if isinstance(error_code, str) and error_code in REPAIRABLE_ERROR_CODES:
        return _REPAIR_INSTRUCTIONS[error_code]
    for issue in item.quality_issues:
        if issue.severity == "warning" and issue.code in REPAIRABLE_WARNING_CODES:
            return _REPAIR_INSTRUCTIONS[issue.code]
    return None


def _adopts_repair(candidate: _SegmentTranslation, original: _SegmentTranslation) -> bool:
    """Adopt a repair only when it is strictly better than what it replaces."""

    if candidate.error is not None:
        return False
    if original.error is not None:
        return True
    return len(candidate.quality_issues) < len(original.quality_issues)


def _repair_pending(
    results: dict[str, _SegmentTranslation],
    provider: TranslationProvider,
    *,
    workers: int,
    context,
    repair_rounds: int,
) -> dict[str, _SegmentTranslation]:
    """Re-ask segments that failed, or tripped a repairable warning.

    This replaces AiNiee's "halve the batch and retry the failures" strategy:
    HanEngine sends one segment per request, so there is no batch to shrink, and
    the useful knob is a failure-specific instruction instead.  Nothing here is
    persisted; the caller keeps its ordered write loop.
    """

    for _round in range(repair_rounds):
        repairs = {
            segment_id: replace(item.request, retry_instruction=instruction)
            for segment_id, item in results.items()
            if (instruction := _repair_instruction(item)) is not None
        }
        if not repairs:
            break
        retried = _translate_pending(
            repairs,
            provider,
            workers=workers,
            context=context,
        )
        for segment_id, candidate in retried.items():
            if _adopts_repair(candidate, results[segment_id]):
                results[segment_id] = candidate
    return results


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
        reference_translations: Mapping[str, str] | None = None,
        workers: int = 1,
        glossary: Glossary | None = None,
        repair_rounds: int = 1,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> PipelineTranslationOutcome:
        if not isinstance(catalog, LocalizationCatalog):
            raise TypeError("catalog must be a LocalizationCatalog")
        if not isinstance(route, RoutePlan):
            raise TypeError("route must be a RoutePlan")
        if not callable(getattr(provider, "translate", None)):
            raise TypeError("provider must implement translate")
        if not isinstance(resume, bool):
            raise TypeError("resume must be a bool")
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise ValueError("workers must be a positive integer")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if batch_size > MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must not exceed {MAX_BATCH_SIZE}")
        if glossary is not None and not isinstance(glossary, Glossary):
            raise TypeError("glossary must be a Glossary or None")
        if (
            isinstance(repair_rounds, bool)
            or not isinstance(repair_rounds, int)
            or repair_rounds < 0
        ):
            raise ValueError("repair_rounds must be a non-negative integer")
        if retry_spec is not None and not isinstance(retry_spec, TaskRetrySpec):
            raise TypeError("retry_spec must be a TaskRetrySpec or None")
        if reference_translations is not None:
            if not isinstance(reference_translations, Mapping):
                raise TypeError("reference_translations must be a mapping or None")
            if any(
                not isinstance(segment_id, str)
                or not segment_id
                or not isinstance(text, str)
                or not text
                for segment_id, text in reference_translations.items()
            ):
                raise ValueError("reference_translations must map segment IDs to non-empty text")
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
        failure: dict[str, object] = {
            "code": None,
            "message": None,
            "segment_id": None,
            "retry_count": 0,
        }
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

            pending = _pending_requests(
                catalog,
                ordered,
                resume=resume,
                reference_translations=reference_translations,
                glossary=glossary,
            )
            precomputed = _translate_batch(
                provider,
                list(pending.values()),
                batch_size=batch_size,
                workers=workers,
                context=context,
            )
            precomputed = _repair_pending(
                precomputed,
                provider,
                workers=workers,
                context=context,
                repair_rounds=repair_rounds,
            )

            for index, (entry, persisted) in enumerate(
                zip(catalog.entries, ordered),
                start=1,
            ):
                context.checkpoint()
                result_provider: str | None = None
                result_model: str | None = None
                result_confidence: float | None = None
                if entry.target_text is not None:
                    metadata = dict(persisted.metadata)
                    metadata.pop("translation_failure", None)
                    current = replace(
                        persisted,
                        target_text=entry.target_text,
                        translation_source="catalog",
                        metadata=metadata,
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
                        reference_translation=(
                            None
                            if reference_translations is None
                            else reference_translations.get(persisted.segment_id)
                        ),
                    )
                    try:
                        prepared = precomputed[persisted.segment_id]
                        if prepared.error is not None:
                            raise prepared.error
                        translation = prepared.translation
                        quality_issues = prepared.quality_issues
                    except TranslationNotFoundError:
                        metadata = dict(persisted.metadata)
                        metadata.pop("translation", None)
                        metadata.pop("translation_failure", None)
                        current = replace(
                            persisted,
                            target_text=None,
                            translation_source=None,
                            metadata=metadata,
                        )
                        disposition = "untranslated"
                        counts["untranslated"] += 1
                    except TranslationProviderError as exc:
                        provider_codes = getattr(exc, "failure_codes", ())
                        error_codes = tuple(provider_codes)
                        if not error_codes:
                            error_codes = (
                                getattr(exc, "code", type(exc).__name__),
                            )
                        error_code = ",".join(error_codes)
                        retry_count = getattr(exc, "retry_count", 0)
                        error_message = str(exc)
                        context.warning(
                            "Translation failed for segment",
                            {
                                "segment_id": persisted.segment_id,
                                "error_code": error_code,
                                "error_message": error_message,
                                "retry_count": retry_count,
                            },
                        )
                        if error_codes and set(error_codes) <= FALLBACK_ERROR_CODES:
                            # Content-quality rejection for this segment only:
                            # keep the source text, queue the entry for human
                            # review, and let the rest of the batch continue.
                            # Infrastructural provider failures still abort.
                            metadata = dict(persisted.metadata)
                            metadata.pop("translation", None)
                            metadata.pop("translation_quality", None)
                            metadata["translation_failure"] = {
                                "code": error_code,
                                "message": error_message,
                                "retry_count": retry_count,
                            }
                            current = replace(
                                persisted,
                                target_text=None,
                                translation_source=None,
                                metadata=metadata,
                            )
                            disposition = "untranslated"
                            counts["untranslated"] += 1
                        else:
                            failure["code"] = error_code
                            failure["message"] = error_message
                            failure["segment_id"] = persisted.segment_id
                            failure["retry_count"] = retry_count
                            raise
                    else:
                        metadata = dict(persisted.metadata)
                        metadata.pop("translation_failure", None)
                        metadata["translation"] = {
                            "provider": translation.provider,
                            "model": translation.model,
                            "confidence": translation.confidence,
                            "cached": translation.cached,
                        }
                        if quality_issues:
                            metadata["translation_quality"] = [
                                issue.to_dict() for issue in quality_issues
                            ]
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
                partial_catalog=_catalog_with_segments(catalog, tuple(completed_segments)),
                partial_segments=tuple(completed_segments),
                failure_code=failure["code"],
                failure_message=failure["message"],
                failure_segment_id=failure["segment_id"],
                failure_retry_count=int(failure["retry_count"] or 0),
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
