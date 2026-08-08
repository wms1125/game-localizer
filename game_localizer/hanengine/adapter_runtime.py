from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from game_localizer.adapters.contract import (
    AdapterError,
    AdapterErrorCode,
    AdapterMetadata,
    AdapterV1,
    BuildRequest,
    BuildResult,
    DeclaredMode,
    DetectionRequest,
    DetectionResult,
    Evidence,
    EvidenceSource,
    ExtractRequest,
    ExtractResult,
    Operation,
    RollbackRequest,
    RollbackResult,
    ValidationRequest,
    ValidationResult,
    VerifyRequest,
    VerifyResult,
    adapter_operations_for_route,
    route_operations_for_capabilities,
)

from .core import HanCore
from .routing import (
    EvaluationStatus,
    HanGuard,
    RiskLevel,
    RiskSignal,
    RouteOperation,
    RoutePhase,
    RoutePlan,
)
from .segments import JsonValue, Segment
from .store import TaskRetrySpec
from .tasks import (
    StepResult,
    TaskCancelled,
    TaskContext,
    TaskPlan,
    TaskState,
    TaskStep,
    EventSink,
)


AdapterRequest: TypeAlias = (
    DetectionRequest
    | ExtractRequest
    | ValidationRequest
    | BuildRequest
    | VerifyRequest
    | RollbackRequest
)
AdapterResult: TypeAlias = (
    DetectionResult
    | ExtractResult
    | ValidationResult
    | BuildResult
    | VerifyResult
    | RollbackResult
)
AdapterRequestFactory: TypeAlias = Callable[[TaskContext], AdapterRequest]

_REQUEST_TYPES = {
    Operation.DETECT: DetectionRequest,
    Operation.EXTRACT: ExtractRequest,
    Operation.VALIDATE: ValidationRequest,
    Operation.BUILD: BuildRequest,
    Operation.VERIFY: VerifyRequest,
    Operation.ROLLBACK: RollbackRequest,
}
_RESULT_TYPES = {
    Operation.DETECT: DetectionResult,
    Operation.EXTRACT: ExtractResult,
    Operation.VALIDATE: ValidationResult,
    Operation.BUILD: BuildResult,
    Operation.VERIFY: VerifyResult,
    Operation.ROLLBACK: RollbackResult,
}
_OPERATION_TITLES = {
    Operation.DETECT: "Detect engine",
    Operation.EXTRACT: "Extract localization resources",
    Operation.VALIDATE: "Validate translations",
    Operation.BUILD: "Build localization candidate",
    Operation.VERIFY: "Verify localization candidate",
    Operation.ROLLBACK: "Rollback localization changes",
}


class AdapterRuntimeError(RuntimeError):
    pass


class AdapterNotDetectedError(AdapterRuntimeError):
    def __init__(self, task: TaskPlan, provisional_route: RoutePlan):
        super().__init__("No AdapterV1 implementation matched the project")
        self.task = task
        self.provisional_route = provisional_route


class AdapterAmbiguityError(AdapterRuntimeError):
    def __init__(
        self,
        task: TaskPlan,
        provisional_route: RoutePlan,
        adapter_ids: tuple[str, ...],
    ):
        super().__init__("Multiple AdapterV1 implementations matched with similar confidence")
        self.task = task
        self.provisional_route = provisional_route
        self.adapter_ids = adapter_ids


class AdapterTaskFailedError(AdapterRuntimeError):
    def __init__(
        self,
        task: TaskPlan,
        operation: Operation,
        adapter_error: AdapterError | None = None,
    ):
        super().__init__(f"AdapterV1 {operation.value} task did not complete")
        self.task = task
        self.operation = operation
        self.adapter_error = adapter_error


class _AdapterInvocationFailed(RuntimeError):
    pass


class AdapterRegistryV1:
    def __init__(self, adapters: Iterable[AdapterV1]):
        if isinstance(adapters, (str, bytes, set, frozenset)):
            raise TypeError("adapters must be an ordered iterable")
        items = tuple(adapters)
        by_id: dict[str, AdapterV1] = {}
        for adapter in items:
            metadata = getattr(adapter, "metadata", None)
            if not isinstance(metadata, AdapterMetadata):
                raise TypeError("every adapter must expose AdapterMetadata")
            for method_name in ("detect", "extract", "validate", "build", "verify", "rollback"):
                if not callable(getattr(adapter, method_name, None)):
                    raise TypeError("every adapter must implement the AdapterV1 operations")
            if metadata.adapter_id in by_id:
                raise ValueError("adapter IDs must be unique")
            by_id[metadata.adapter_id] = adapter
        if not by_id:
            raise ValueError("at least one AdapterV1 implementation is required")
        self._adapters = tuple(by_id[key] for key in sorted(by_id))
        self._by_id = dict(by_id)

    @property
    def adapters(self) -> tuple[AdapterV1, ...]:
        return self._adapters

    def get(self, adapter_id: str) -> AdapterV1:
        if not isinstance(adapter_id, str) or not adapter_id:
            raise ValueError("adapter_id must not be empty")
        try:
            return self._by_id[adapter_id]
        except KeyError as exc:
            raise KeyError(f"AdapterV1 implementation is not registered: {adapter_id}") from exc


@dataclass(frozen=True)
class AdapterSelection:
    adapter_id: str
    detection: DetectionResult
    provisional_route: RoutePlan
    final_route: RoutePlan
    detection_task: TaskPlan

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_id, str) or not self.adapter_id:
            raise ValueError("adapter_id must not be empty")
        if not isinstance(self.detection, DetectionResult) or not self.detection.matched:
            raise ValueError("detection must be a matched DetectionResult")
        if not isinstance(self.provisional_route, RoutePlan):
            raise TypeError("provisional_route must be a RoutePlan")
        if self.provisional_route.phase is not RoutePhase.PROVISIONAL:
            raise ValueError("provisional_route must be provisional")
        if not isinstance(self.final_route, RoutePlan):
            raise TypeError("final_route must be a RoutePlan")
        if self.final_route.phase is not RoutePhase.FINAL:
            raise ValueError("final_route must be final")
        if not isinstance(self.detection_task, TaskPlan):
            raise TypeError("detection_task must be a TaskPlan")
        if self.detection_task.state is not TaskState.COMPLETED:
            raise ValueError("detection_task must be completed")
        project_ids = {
            self.provisional_route.project_id,
            self.final_route.project_id,
            self.detection_task.project_id,
        }
        if len(project_ids) != 1:
            raise ValueError("selection records must belong to one project")
        available = route_operations_for_capabilities(self.detection.capabilities)
        if not self.final_route.allowed_operations <= available:
            raise ValueError("final route exceeds detected adapter capabilities")


@dataclass(frozen=True)
class AdapterTaskExecution:
    adapter_id: str
    operation: Operation
    task: TaskPlan
    result: AdapterResult
    ingested_segments: tuple[Segment, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_id, str) or not self.adapter_id:
            raise ValueError("adapter_id must not be empty")
        if not isinstance(self.operation, Operation):
            raise TypeError("operation must be an Operation")
        if not isinstance(self.task, TaskPlan) or self.task.state is not TaskState.COMPLETED:
            raise ValueError("task must be a completed TaskPlan")
        if not isinstance(self.result, _RESULT_TYPES[self.operation]):
            raise TypeError("result does not match operation")
        segments = tuple(self.ingested_segments)
        if any(not isinstance(segment, Segment) for segment in segments):
            raise TypeError("ingested_segments must contain Segment values")
        if self.operation is not Operation.EXTRACT and segments:
            raise ValueError("only extract operations may ingest segments")
        object.__setattr__(self, "ingested_segments", segments)


def _result_summary(result: AdapterResult) -> dict[str, JsonValue]:
    if isinstance(result, DetectionResult):
        return {
            "matched": result.matched,
            "engine_name": result.engine_name,
            "engine_version": result.engine_version,
            "confidence": result.confidence,
            "maturity": result.maturity.value,
            "capabilities": sorted(item.value for item in result.capabilities),
        }
    if isinstance(result, ExtractResult):
        return {
            "source_tree_fingerprint": result.source_tree_fingerprint,
            "read_files": list(result.read_files),
            "skipped_files": list(result.skipped_files),
            "statistics": dict(result.statistics),
        }
    if isinstance(result, ValidationResult):
        return {
            "valid": result.valid,
            "blocking_issue_count": result.blocking_issue_count,
            "warning_count": result.warning_count,
            "issue_codes": [issue.code for issue in result.issues],
        }
    if isinstance(result, BuildResult):
        return {
            "generated_files": list(result.generated_files),
            "manifest": [
                {
                    "relative_path": entry.relative_path,
                    "change_kind": entry.change_kind,
                    "sha256": entry.sha256,
                }
                for entry in result.manifest
            ],
            "candidate_fingerprint": result.candidate_fingerprint,
            "statistics": dict(result.statistics),
        }
    if isinstance(result, VerifyResult):
        return {
            "passed": result.passed,
            "syntax_passed": result.syntax_passed,
            "encoding_passed": result.encoding_passed,
            "artifact_hashes": dict(result.artifact_hashes),
            "check_codes": [check.code for check in result.checks],
        }
    return {
        "restored_files": list(result.restored_files),
        "unchanged_files": list(result.unchanged_files),
        "failed_files": list(result.failed_files),
        "hash_verification_passed": result.hash_verification_passed,
    }


class AdapterRuntimeV1:
    def __init__(
        self,
        core: HanCore,
        guard: HanGuard,
        adapters: Iterable[AdapterV1] | None = None,
        *,
        ambiguity_threshold: float = 0.10,
        event_listener: EventSink | None = None,
        retry_spec: TaskRetrySpec | None = None,
    ):
        if not isinstance(core, HanCore):
            raise TypeError("core must be a HanCore")
        if not isinstance(guard, HanGuard):
            raise TypeError("guard must be a HanGuard")
        if (
            isinstance(ambiguity_threshold, bool)
            or not isinstance(ambiguity_threshold, (int, float))
            or not 0.0 <= float(ambiguity_threshold) <= 1.0
        ):
            raise ValueError("ambiguity_threshold must be within [0.0, 1.0]")
        self.core = core
        self.guard = guard
        if event_listener is not None and not callable(event_listener):
            raise TypeError("event_listener must be callable or None")
        if retry_spec is not None and not isinstance(retry_spec, TaskRetrySpec):
            raise TypeError("retry_spec must be a TaskRetrySpec or None")
        self.event_listener = event_listener
        self.retry_spec = retry_spec
        if adapters is None:
            from game_localizer.adapters import get_adapters_v1

            adapters = get_adapters_v1()
        self.registry = AdapterRegistryV1(adapters)
        self.ambiguity_threshold = float(ambiguity_threshold)

    def _check_source_root(self, source_root: Path) -> None:
        if not isinstance(source_root, Path):
            raise TypeError("source root must be a Path")
        if not source_root.is_absolute() or source_root != source_root.resolve(strict=False):
            raise ValueError("source root must equal its resolved absolute identity")
        configured = self.core.store.source_root
        if configured is not None and source_root != configured:
            raise ValueError("request source root does not match the project source root")

    def detect(
        self,
        input_root: Path,
        declared_mode: DeclaredMode,
        *,
        user_baseline: RiskLevel | None,
        adapter_baseline: RiskLevel | None,
        signals: Iterable[RiskSignal] = (),
        final_signals: Iterable[RiskSignal] = (),
        provisional_evaluation_status: EvaluationStatus = EvaluationStatus.COMPLETE,
        final_evaluation_status: EvaluationStatus = EvaluationStatus.COMPLETE,
        task_id: str | None = None,
        declared_adapter_id: str | None = None,
    ) -> AdapterSelection:
        self._check_source_root(input_root)
        if not isinstance(declared_mode, DeclaredMode):
            raise TypeError("declared_mode must be a DeclaredMode")
        signal_items = tuple(signals)
        final_signal_items = tuple(final_signals)
        if declared_adapter_id is not None:
            self.registry.get(declared_adapter_id)
        provisional = self.guard.evaluate_provisional(
            self.core.store.project_id,
            user_baseline,
            signal_items,
            evaluation_status=provisional_evaluation_status,
        )
        self.core.store.delete_route(RoutePhase.FINAL)
        task = self.core.create_task(
            kind="adapter-detect",
            route=provisional,
            task_id=task_id,
            steps=(TaskStep("adapter-detect", "Detect AdapterV1 engine", RouteOperation.DETECT),),
        )
        if self.retry_spec is not None:
            self.core.store.save_task_retry_spec(task.task_id, self.retry_spec)
        selected: list[tuple[AdapterV1, DetectionResult]] = []
        adapter_errors: list[AdapterError] = []
        ambiguous_ids: list[tuple[str, ...]] = []

        def handler(context: TaskContext) -> StepResult:
            candidates: list[tuple[AdapterV1, DetectionResult]] = []
            for adapter in self.registry.adapters:
                context.checkpoint()
                request = DetectionRequest(
                    input_root=input_root,
                    declared_mode=declared_mode,
                    project_id=self.core.store.project_id,
                    risk_level=provisional.risk_after,
                    allowed_operations=adapter_operations_for_route(provisional),
                    context=context,
                )
                result = adapter.detect(request)
                if isinstance(result, AdapterError):
                    adapter_errors.append(result)
                    context.warning(
                        "AdapterV1 detection returned an error",
                        {
                            "adapter_id": adapter.metadata.adapter_id,
                            "code": result.code.value,
                        },
                    )
                    if result.code is AdapterErrorCode.CANCELLED:
                        raise TaskCancelled("adapter detection cancelled")
                    continue
                if not isinstance(result, DetectionResult):
                    raise TypeError("adapter detect returned an invalid result")
                if (
                    not result.matched
                    and declared_adapter_id == adapter.metadata.adapter_id
                ):
                    result = DetectionResult(
                        matched=True,
                        engine_name=adapter.metadata.engine_name,
                        engine_version="user-declared",
                        confidence=0.55,
                        evidence=(
                            Evidence(
                                code="explicit_adapter_declaration",
                                source=EvidenceSource.USER_DECLARATION,
                                value=adapter.metadata.adapter_id,
                                weight=0.55,
                                description="Adapter selected explicitly by the user",
                            ),
                        ),
                        maturity=adapter.metadata.maturity,
                        capabilities=adapter.metadata.capabilities,
                        limitations=adapter.metadata.known_limitations,
                        recommended_operation=Operation.DETECT,
                    )
                if not result.capabilities <= adapter.metadata.capabilities:
                    raise ValueError("detection capabilities exceed adapter metadata")
                if result.matched:
                    candidates.append((adapter, result))

            candidates.sort(
                key=lambda item: (-item[1].confidence, item[0].metadata.adapter_id)
            )
            ambiguous = (
                len(candidates) > 1
                and candidates[0][1].confidence - candidates[1][1].confidence
                <= self.ambiguity_threshold
            )
            if ambiguous:
                top_confidence = candidates[0][1].confidence
                ids = tuple(
                    adapter.metadata.adapter_id
                    for adapter, result in candidates
                    if top_confidence - result.confidence <= self.ambiguity_threshold
                )
                ambiguous_ids.append(ids)
            elif candidates:
                selected.append(candidates[0])
            if not candidates and len(adapter_errors) == len(self.registry.adapters):
                raise _AdapterInvocationFailed("all adapter detections failed")
            return StepResult(
                data={
                    "matched": bool(candidates),
                    "ambiguous": ambiguous,
                    "candidate_count": len(candidates),
                    "candidate_adapter_ids": [
                        adapter.metadata.adapter_id for adapter, _ in candidates
                    ],
                    "adapter_error_count": len(adapter_errors),
                    "adapter_id": (
                        None if ambiguous or not candidates else candidates[0][0].metadata.adapter_id
                    ),
                    "confidence": (
                        None if ambiguous or not candidates else candidates[0][1].confidence
                    ),
                    "evidence_codes": (
                        []
                        if ambiguous or not candidates
                        else [item.code for item in candidates[0][1].evidence]
                    ),
                }
            )

        completed = self.core.run_task(
            task,
            route=provisional,
            handlers={"adapter-detect": handler},
            event_listener=self.event_listener,
        )
        if completed.state is not TaskState.COMPLETED:
            error = adapter_errors[-1] if adapter_errors else None
            raise AdapterTaskFailedError(completed, Operation.DETECT, error)
        if ambiguous_ids:
            raise AdapterAmbiguityError(completed, provisional, ambiguous_ids[0])
        if not selected:
            raise AdapterNotDetectedError(completed, provisional)

        adapter, detection = selected[0]
        final_route = self.guard.evaluate_final(
            provisional,
            adapter_baseline,
            final_signal_items,
            available_operations=route_operations_for_capabilities(detection.capabilities),
            evaluation_status=final_evaluation_status,
        )
        self.core.store.save_route(final_route)
        return AdapterSelection(
            adapter_id=adapter.metadata.adapter_id,
            detection=detection,
            provisional_route=provisional,
            final_route=final_route,
            detection_task=completed,
        )

    def run_operation(
        self,
        selection: AdapterSelection,
        operation: Operation,
        request_factory: AdapterRequestFactory,
        *,
        target_language: str | None = None,
        task_id: str | None = None,
    ) -> AdapterTaskExecution:
        if not isinstance(selection, AdapterSelection):
            raise TypeError("selection must be an AdapterSelection")
        if not isinstance(operation, Operation):
            raise TypeError("operation must be an Operation")
        if not callable(request_factory):
            raise TypeError("request_factory must be callable")
        self._check_selection_provenance(selection)
        if operation is Operation.EXTRACT:
            if not isinstance(target_language, str) or not target_language:
                raise ValueError("target_language is required for extract operations")
        elif target_language is not None:
            raise ValueError("target_language is only valid for extract operations")

        adapter = self.registry.get(selection.adapter_id)
        route_operation = RouteOperation(operation.value)
        task = self.core.create_task(
            kind=f"adapter-{operation.value}",
            route=selection.final_route,
            task_id=task_id,
            steps=(
                TaskStep(
                    f"adapter-{operation.value}",
                    _OPERATION_TITLES[operation],
                    route_operation,
                ),
            ),
        )
        if self.retry_spec is not None:
            self.core.store.save_task_retry_spec(task.task_id, self.retry_spec)
        results: list[AdapterResult] = []
        ingested: list[tuple[Segment, ...]] = []
        adapter_errors: list[AdapterError] = []

        def handler(context: TaskContext) -> StepResult:
            request = request_factory(context)
            if not isinstance(request, _REQUEST_TYPES[operation]):
                raise TypeError("request factory returned the wrong request type")
            if request.context is not context:
                raise ValueError("adapter request must use the active HanTask context")
            self._check_request_ownership(request)
            result = getattr(adapter, operation.value)(request)
            if isinstance(result, AdapterError):
                adapter_errors.append(result)
                context.warning(
                    "AdapterV1 operation returned an error",
                    {"adapter_id": selection.adapter_id, "code": result.code.value},
                )
                if result.code is AdapterErrorCode.CANCELLED:
                    raise TaskCancelled("adapter operation cancelled")
                raise _AdapterInvocationFailed("adapter operation failed")
            if not isinstance(result, _RESULT_TYPES[operation]):
                raise TypeError("adapter returned the wrong result type")
            segment_items: tuple[Segment, ...] = ()
            if isinstance(result, ExtractResult):
                segment_items = self.core.ingest_segments(
                    result.segments,
                    target_language=target_language,
                )
                ingested.append(segment_items)
            results.append(result)
            summary = _result_summary(result)
            summary["adapter_id"] = selection.adapter_id
            if segment_items:
                summary["ingested_segments"] = len(segment_items)
            return StepResult(data=summary)

        completed = self.core.run_task(
            task,
            route=selection.final_route,
            handlers={f"adapter-{operation.value}": handler},
            event_listener=self.event_listener,
        )
        if completed.state is not TaskState.COMPLETED or not results:
            error = adapter_errors[-1] if adapter_errors else None
            raise AdapterTaskFailedError(completed, operation, error)
        return AdapterTaskExecution(
            adapter_id=selection.adapter_id,
            operation=operation,
            task=completed,
            result=results[0],
            ingested_segments=ingested[0] if ingested else (),
        )

    def _check_request_ownership(self, request: AdapterRequest) -> None:
        project_id = self.core.store.project_id
        if isinstance(request, DetectionRequest):
            if request.project_id != project_id:
                raise ValueError("detection request belongs to another project")
            self._check_source_root(request.input_root)
        elif isinstance(request, ExtractRequest):
            if request.project_id != project_id:
                raise ValueError("extract request belongs to another project")
            self._check_source_root(request.source_root)
        elif isinstance(request, ValidationRequest):
            if any(
                segment.project_id != project_id
                for segment in (*request.original_segments, *request.translated_segments)
            ):
                raise ValueError("validation segments belong to another project")
        elif isinstance(request, BuildRequest):
            self._check_source_root(request.source_root)
            if any(segment.project_id != project_id for segment in request.validated_segments):
                raise ValueError("build segments belong to another project")
        elif isinstance(request, RollbackRequest) and request.project_id != project_id:
            raise ValueError("rollback request belongs to another project")

    def _check_selection_provenance(self, selection: AdapterSelection) -> None:
        project_id = self.core.store.project_id
        if selection.final_route.project_id != project_id:
            raise ValueError("adapter selection belongs to another project")
        if self.core.store.get_route(RoutePhase.PROVISIONAL) != selection.provisional_route:
            raise ValueError("adapter selection provisional route is not current")
        if self.core.store.get_route(RoutePhase.FINAL) != selection.final_route:
            raise ValueError("adapter selection final route is not current")
        if self.core.store.get_task(selection.detection_task.task_id) != selection.detection_task:
            raise ValueError("adapter selection detection task is not persisted")


__all__ = [
    "AdapterAmbiguityError",
    "AdapterNotDetectedError",
    "AdapterRegistryV1",
    "AdapterRequest",
    "AdapterRequestFactory",
    "AdapterResult",
    "AdapterRuntimeError",
    "AdapterRuntimeV1",
    "AdapterSelection",
    "AdapterTaskExecution",
    "AdapterTaskFailedError",
]
