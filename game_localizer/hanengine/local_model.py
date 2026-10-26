from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .multiengine import LocalizationCatalog, LocalizationEntry
from .translation import (
    LocalModelTranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationRouter,
)


LOCAL_MODEL_BENCHMARK_SCHEMA_VERSION = "hanengine.local-model-benchmark/v1"


@dataclass(frozen=True)
class LocalModelBenchmarkItem:
    segment_id: str
    relative_path: str
    source_text: str
    target_text: str | None
    provider: str | None
    model: str | None
    confidence: float | None
    latency_ms: float
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "relative_path": self.relative_path,
            "source_text": self.source_text,
            "target_text": self.target_text,
            "provider": self.provider,
            "model": self.model,
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(frozen=True)
class LocalModelBenchmarkReport:
    engine_id: str
    model_name: str
    endpoint: str
    sample_count: int
    translated_count: int
    failed_count: int
    elapsed_ms: float
    average_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    items: tuple[LocalModelBenchmarkItem, ...]

    @property
    def passed(self) -> bool:
        return self.sample_count > 0 and self.failed_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": LOCAL_MODEL_BENCHMARK_SCHEMA_VERSION,
            "status": "passed" if self.passed else "failed",
            "engine_id": self.engine_id,
            "model_name": self.model_name,
            "endpoint": self.endpoint,
            "recommended_profile": {
                "parameter_range": "3B-4B",
                "quantization": "Q4_K_M",
                "context_length": 8192,
            },
            "summary": {
                "sample_count": self.sample_count,
                "translated_count": self.translated_count,
                "failed_count": self.failed_count,
                "elapsed_ms": self.elapsed_ms,
                "average_latency_ms": self.average_latency_ms,
                "p50_latency_ms": self.p50_latency_ms,
                "p95_latency_ms": self.p95_latency_ms,
            },
            "items": [item.to_dict() for item in self.items],
        }


def _percentile(values: tuple[float, ...], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def select_local_model_samples(
    entries: Iterable[LocalizationEntry],
    sample_count: int = 100,
) -> tuple[LocalizationEntry, ...]:
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count <= 0:
        raise ValueError("sample_count must be a positive integer")
    grouped: dict[str, list[LocalizationEntry]] = defaultdict(list)
    for entry in entries:
        if not isinstance(entry, LocalizationEntry):
            raise TypeError("entries must contain LocalizationEntry values")
        grouped[entry.relative_path].append(entry)
    queues = [grouped[key] for key in sorted(grouped)]
    selected: list[LocalizationEntry] = []
    while queues and len(selected) < sample_count:
        next_queues: list[list[LocalizationEntry]] = []
        for queue in queues:
            selected.append(queue.pop(0))
            if len(selected) >= sample_count:
                break
            if queue:
                next_queues.append(queue)
        queues = next_queues
    return tuple(selected)


def benchmark_local_model(
    catalog: LocalizationCatalog,
    endpoint: str,
    *,
    model_name: str = "unknown",
    timeout: float = 120.0,
    sample_count: int = 100,
) -> LocalModelBenchmarkReport:
    if not isinstance(catalog, LocalizationCatalog):
        raise TypeError("catalog must be a LocalizationCatalog")
    samples = select_local_model_samples(catalog.entries, sample_count)
    provider = LocalModelTranslationProvider(
        endpoint,
        timeout=timeout,
        model_name=model_name,
    )
    router = TranslationRouter((provider,))
    items: list[LocalModelBenchmarkItem] = []
    latencies: list[float] = []
    started = time.perf_counter()
    for entry in samples:
        request = TranslationRequest(
            entry.segment_id,
            entry.source_text,
            catalog.source_language,
            catalog.language,
            context=(entry.relative_path, entry.kind),
        )
        item_started = time.perf_counter()
        try:
            result = router.translate(request)
            latency_ms = (time.perf_counter() - item_started) * 1000
            latencies.append(latency_ms)
            items.append(
                LocalModelBenchmarkItem(
                    entry.segment_id,
                    entry.relative_path,
                    entry.source_text,
                    result.text,
                    result.provider,
                    result.model,
                    result.confidence,
                    latency_ms,
                )
            )
        except (TranslationProviderError, ValueError, TypeError) as exc:
            latency_ms = (time.perf_counter() - item_started) * 1000
            latencies.append(latency_ms)
            items.append(
                LocalModelBenchmarkItem(
                    entry.segment_id,
                    entry.relative_path,
                    entry.source_text,
                    None,
                    None,
                    None,
                    None,
                    latency_ms,
                    f"{type(exc).__name__}: {exc}",
                )
            )
    elapsed_ms = (time.perf_counter() - started) * 1000
    latency_values = tuple(latencies)
    translated_count = sum(item.target_text is not None for item in items)
    return LocalModelBenchmarkReport(
        engine_id=catalog.engine_id,
        model_name=model_name,
        endpoint=endpoint,
        sample_count=len(samples),
        translated_count=translated_count,
        failed_count=len(samples) - translated_count,
        elapsed_ms=elapsed_ms,
        average_latency_ms=(sum(latency_values) / len(latency_values) if latency_values else 0.0),
        p50_latency_ms=_percentile(latency_values, 0.50),
        p95_latency_ms=_percentile(latency_values, 0.95),
        items=tuple(items),
    )


def write_local_model_benchmark(report: LocalModelBenchmarkReport, output: Path) -> Path:
    if not isinstance(report, LocalModelBenchmarkReport):
        raise TypeError("report must be a LocalModelBenchmarkReport")
    if not isinstance(output, Path):
        raise TypeError("output must be a Path")
    output = output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output


__all__ = [
    "LOCAL_MODEL_BENCHMARK_SCHEMA_VERSION",
    "LocalModelBenchmarkItem",
    "LocalModelBenchmarkReport",
    "benchmark_local_model",
    "select_local_model_samples",
    "write_local_model_benchmark",
]
