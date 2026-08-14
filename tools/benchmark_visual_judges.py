from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "hanengine.visual-judge-benchmark/v1"
DECISIONS = {"pass", "escalate", "fail"}
PROMPT = """\
你是游戏本地化发布前的视觉判官。你会收到同一场景的两张截图：第一张是原文参考图，第二张是简体中文候选图。

先独立观察候选图，再逐个文本区域与参考图对照。必须逐项检查以下会阻断发布的问题：
1. 本应翻译但仍保留的原文自然语言，包括页面标签、存档标签、日期和游戏内容中的标题；
2. 文字被截断、溢出、相互遮挡或明显越界；只要两行文字的字形相互穿插、压住或无法分别阅读，就算 overlap；
3. 缺字、方框字、乱码或字体无法显示；
4. 明显破坏可读性的错误换行、布局或视觉风格；把正常词语拆成孤立单字行算 bad_wrapping，正文相对参考图或同页标题明显过小、过淡、低对比度算 style_readability。

不要报告窗口系统标题栏、Ren'Py 等引擎/品牌名、人物名，也不要把语言选择器中的 English、Español、日本語等语言名称当成漏翻。不要猜测截图之外的问题。

只输出一个 JSON 对象，不要使用 Markdown 或代码围栏。字段必须且只能是：
{
  "decision": "pass|escalate|fail",
  "style_score": 0到1之间的数字,
  "confidence": 0到1之间的数字,
  "model": "实际模型名称",
  "issues": ["问题代码: 可从截图核验的简短证据"]
}

没有问题时 decision 必须为 pass 且 issues 为空；确认存在问题时为 fail；无法确定时为 escalate。问题代码只使用 residual_untranslated_text、clipped、overflow、overlap、missing_glyphs、garbled_text、bad_wrapping、style_readability。
"""


class BenchmarkError(RuntimeError):
    pass


class RequestError(BenchmarkError):
    def __init__(self, message: str, attempt_count: int) -> None:
        super().__init__(message)
        self.attempt_count = attempt_count


@dataclass(frozen=True)
class Sample:
    sample_id: str
    reference_image: Path
    candidate_image: Path
    expected_defect: bool
    expected_issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class Provider:
    provider_id: str
    model: str
    key_env: str
    endpoint: str


PROVIDERS = (
    Provider(
        provider_id="glm-flashx",
        model="glm-4.6v-flashx",
        key_env="ZHIPU_API_KEY",
        endpoint="https://open.bigmodel.cn/api/paas/v4/chat/completions",
    ),
    Provider(
        provider_id="glm-pro",
        model="glm-4.6v",
        key_env="ZHIPU_API_KEY",
        endpoint="https://open.bigmodel.cn/api/paas/v4/chat/completions",
    ),
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"cannot read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkError(f"JSON root must be an object: {path}")
    return payload


def load_dataset(path: Path) -> tuple[Sample, ...]:
    payload = _read_json(path)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise BenchmarkError(f"dataset schema_version must be {SCHEMA_VERSION}")
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise BenchmarkError("dataset samples must be a non-empty array")
    samples: list[Sample] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_samples):
        if not isinstance(item, dict):
            raise BenchmarkError(f"samples[{index}] must be an object")
        if set(item) != {
            "sample_id",
            "reference_image",
            "candidate_image",
            "expected_defect",
            "expected_issue_codes",
        }:
            raise BenchmarkError(f"samples[{index}] fields do not match the benchmark schema")
        sample_id = item["sample_id"]
        expected = item["expected_defect"]
        codes = item["expected_issue_codes"]
        if not isinstance(sample_id, str) or not sample_id or sample_id in seen:
            raise BenchmarkError(f"samples[{index}].sample_id must be unique and non-empty")
        if not isinstance(expected, bool):
            raise BenchmarkError(f"samples[{index}].expected_defect must be boolean")
        if not isinstance(codes, list) or any(not isinstance(code, str) or not code for code in codes):
            raise BenchmarkError(f"samples[{index}].expected_issue_codes must contain strings")
        if expected != bool(codes):
            raise BenchmarkError(f"samples[{index}] expected_defect and expected_issue_codes disagree")
        reference = (path.parent / item["reference_image"]).resolve()
        candidate = (path.parent / item["candidate_image"]).resolve()
        for image in (reference, candidate):
            if not image.is_file():
                raise BenchmarkError(f"benchmark image does not exist: {image}")
            if image.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise BenchmarkError(f"unsupported benchmark image type: {image}")
        seen.add(sample_id)
        samples.append(Sample(sample_id, reference, candidate, expected, tuple(codes)))
    if not any(sample.expected_defect for sample in samples):
        raise BenchmarkError("dataset needs at least one positive sample to measure missed defects")
    if all(sample.expected_defect for sample in samples):
        raise BenchmarkError("dataset needs at least one negative sample to measure false positives")
    return tuple(samples)


def _data_url(path: Path) -> str:
    # Preserve source pixels for deterministic gates; only the remote-model copy
    # is compressed to avoid multi-megabyte PNG uploads failing on Windows TLS.
    try:
        from PIL import Image

        encoded = io.BytesIO()
        with Image.open(path) as image:
            image.convert("RGB").save(encoded, format="JPEG", quality=90, optimize=True)
    except (ImportError, OSError) as exc:
        raise BenchmarkError(f"cannot prepare benchmark image {path}: {exc}") from exc
    return f"data:image/jpeg;base64,{base64.b64encode(encoded.getvalue()).decode('ascii')}"


def _sample_prompt(sample_id: str) -> str:
    return f"{PROMPT}\n第一张图是原文参考，第二张图是简体中文候选。"


def _response_usage(payload: dict[str, Any]) -> dict[str, int] | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    normalized: dict[str, int] = {}
    for field in fields:
        value = usage.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        normalized[field] = value
    return normalized


def _request(
    provider: Provider,
    sample: Sample,
    api_key: str,
) -> tuple[str, float, int, dict[str, int] | None]:
    prompt = _sample_prompt(sample.sample_id)
    body = {
        "model": provider.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _data_url(sample.reference_image)}},
                    {"type": "image_url", "image_url": {"url": _data_url(sample.candidate_image)}},
                ],
            }
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    endpoint = provider.endpoint
    headers = {"Authorization": f"Bearer {api_key}"}
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=encoded,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    started = time.perf_counter()
    retry_delays = (5, 15, 30) if provider.provider_id.startswith("glm") else ()
    attempt_count = 0
    while True:
        attempt_count += 1
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                response_body = response.read()
            break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:2000]
            overloaded = exc.code == 429 and '"code":"1305"' in error_body.replace(" ", "")
            if overloaded and attempt_count <= len(retry_delays):
                time.sleep(retry_delays[attempt_count - 1])
                continue
            raise RequestError(f"HTTP {exc.code}: {error_body}", attempt_count) from exc
        except (OSError, TimeoutError) as exc:
            raise RequestError(
                f"request failed: {type(exc).__name__}: {exc}",
                attempt_count,
            ) from exc
    elapsed_ms = (time.perf_counter() - started) * 1000
    try:
        payload = json.loads(response_body.decode("utf-8"))
        text = payload["choices"][0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise RequestError(
            f"provider response shape is invalid: {type(exc).__name__}",
            attempt_count,
        ) from exc
    if not isinstance(text, str) or not text:
        raise RequestError("provider returned empty model text", attempt_count)
    return text, elapsed_ms, attempt_count, _response_usage(payload)


def validate_judge_json(raw_text: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc.msg}"
    if not isinstance(payload, dict):
        return None, "invalid_schema: root must be an object"
    expected_fields = {"decision", "style_score", "confidence", "model", "issues"}
    if set(payload) != expected_fields:
        return None, "invalid_schema: fields do not match the visual judge contract"
    if payload["decision"] not in DECISIONS:
        return None, "invalid_schema: decision is invalid"
    for field in ("style_score", "confidence"):
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"invalid_schema: {field} must be numeric"
        if not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
            return None, f"invalid_schema: {field} must be within [0, 1]"
    if not isinstance(payload["model"], str) or not payload["model"]:
        return None, "invalid_schema: model must be a non-empty string"
    issues = payload["issues"]
    if not isinstance(issues, list) or any(not isinstance(issue, str) or not issue for issue in issues):
        return None, "invalid_schema: issues must contain non-empty strings"
    return payload, None


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def summarize(
    provider: Provider,
    records: list[dict[str, Any]],
    expected_sample_count: int | None = None,
) -> dict[str, Any]:
    expected_sample_count = len(records) if expected_sample_count is None else expected_sample_count
    positives = [record for record in records if record["expected_defect"]]
    negatives = [record for record in records if not record["expected_defect"]]
    successful = [record for record in records if record["request_success"]]
    evaluated_positives = [record for record in positives if record["judge_result"] is not None]
    evaluated_negatives = [record for record in negatives if record["judge_result"] is not None]
    missed = sum(
        record["judge_result"]["decision"] == "pass"
        and not record["judge_result"]["issues"]
        for record in evaluated_positives
    )
    false_positives = sum(
        (
            record["judge_result"]["decision"] != "pass"
            or bool(record["judge_result"]["issues"])
        )
        for record in evaluated_negatives
    )
    compliant = sum(record["judge_result"] is not None for record in records)
    model_identity_matches = sum(
        record["judge_result"] is not None
        and record["judge_result"]["model"].casefold() == provider.model.casefold()
        for record in records
    )
    latencies = [record["latency_ms"] for record in records if record["latency_ms"] is not None]
    token_usages = [record["token_usage"] for record in records if record.get("token_usage") is not None]
    issue_code_summaries: dict[str, dict[str, Any]] = {}
    expected_issue_codes = sorted(
        {
            code
            for record in records
            for code in record.get("expected_issue_codes", ())
        }
    )
    for code in expected_issue_codes:
        category_records = [
            record for record in records if code in record.get("expected_issue_codes", ())
        ]
        evaluated = [record for record in category_records if record["judge_result"] is not None]
        detected = sum(
            record["judge_result"]["decision"] != "pass"
            or bool(record["judge_result"]["issues"])
            for record in evaluated
        )
        correctly_classified = sum(
            code
            in {
                issue.split(":", 1)[0].strip()
                for issue in record["judge_result"]["issues"]
            }
            for record in evaluated
        )
        complete = len(evaluated) == len(category_records)
        issue_code_summaries[code] = {
            "sample_count": len(category_records),
            "evaluated_count": len(evaluated),
            "detected_count": detected,
            "observed_detection_recall": None if not evaluated else detected / len(evaluated),
            "detection_recall": detected / len(evaluated) if complete and evaluated else None,
            "correctly_classified_count": correctly_classified,
            "observed_classification_recall": (
                None if not evaluated else correctly_classified / len(evaluated)
            ),
            "classification_recall": (
                correctly_classified / len(evaluated) if complete and evaluated else None
            ),
        }
    positive_complete = len(evaluated_positives) == len(positives)
    negative_complete = len(evaluated_negatives) == len(negatives)
    request_success_rate = len(successful) / len(records)
    json_compliance_rate = None if not successful else compliant / len(successful)
    observed_miss_rate = None if not evaluated_positives else missed / len(evaluated_positives)
    observed_false_positive_rate = (
        None if not evaluated_negatives else false_positives / len(evaluated_negatives)
    )
    dataset_complete = len(records) == expected_sample_count
    benchmark_complete = dataset_complete and positive_complete and negative_complete
    model_identity_match_rate = None if not successful else model_identity_matches / len(successful)
    default_eligible = (
        benchmark_complete
        and request_success_rate == 1.0
        and json_compliance_rate == 1.0
        and observed_miss_rate == 0.0
    )
    return {
        "provider": provider.provider_id,
        "model": provider.model,
        "sample_count": len(records),
        "expected_sample_count": expected_sample_count,
        "dataset_complete": dataset_complete,
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "request_success_count": len(successful),
        "request_success_rate": request_success_rate,
        "positive_evaluated_count": len(evaluated_positives),
        "negative_evaluated_count": len(evaluated_negatives),
        "missed_defect_count": missed,
        "observed_miss_rate": observed_miss_rate,
        "miss_rate": observed_miss_rate if positive_complete else None,
        "false_positive_count": false_positives,
        "observed_false_positive_rate": observed_false_positive_rate,
        "false_positive_rate": observed_false_positive_rate if negative_complete else None,
        "json_compliant_count": compliant,
        "json_compliance_rate": json_compliance_rate,
        "end_to_end_json_coverage_rate": compliant / len(records),
        "model_identity_match_count": model_identity_matches,
        "model_identity_match_rate": model_identity_match_rate,
        "issue_code_summaries": issue_code_summaries,
        "benchmark_complete": benchmark_complete,
        "default_eligible": default_eligible,
        "token_usage": None
        if not token_usages
        else {
            field: sum(usage[field] for usage in token_usages)
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "latency_ms": None
        if not latencies
        else {
            "mean": statistics.fmean(latencies),
            "median": statistics.median(latencies),
            "p95": _percentile_95(latencies),
            "minimum": min(latencies),
            "maximum": max(latencies),
        },
    }


def choose_default(summaries: list[dict[str, Any]]) -> str | None:
    eligible = [summary for summary in summaries if summary["default_eligible"]]
    if not eligible:
        return None
    ranked = sorted(
        eligible,
        key=lambda item: (
            item["miss_rate"],
            -item["json_compliance_rate"],
            item["false_positive_rate"],
            item["latency_ms"]["median"],
        ),
    )
    return ranked[0]["model"]


def run(
    dataset_path: Path,
    output_path: Path,
    providers: tuple[Provider, ...] = PROVIDERS,
    sample_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    all_samples = load_dataset(dataset_path)
    expected_sample_count = len(all_samples)
    samples = all_samples
    if sample_ids is not None:
        selected = set(sample_ids)
        unknown = selected - {sample.sample_id for sample in samples}
        if unknown:
            raise BenchmarkError(f"unknown sample IDs: {', '.join(sorted(unknown))}")
        samples = tuple(sample for sample in samples if sample.sample_id in selected)
        if not samples:
            raise BenchmarkError("sample selection cannot be empty")
    keys = {provider.provider_id: os.environ.get(provider.key_env, "") for provider in providers}
    missing = [provider.key_env for provider in providers if not keys[provider.provider_id]]
    if missing:
        raise BenchmarkError(f"missing API key environment variables: {', '.join(missing)}")
    records_by_provider: dict[str, list[dict[str, Any]]] = {
        provider.provider_id: [] for provider in providers
    }
    for sample_index, sample in enumerate(samples):
        provider_order = providers if sample_index % 2 == 0 else tuple(reversed(providers))
        for provider in provider_order:
            record: dict[str, Any] = {
                "provider": provider.provider_id,
                "model": provider.model,
                "sample_id": sample.sample_id,
                "expected_defect": sample.expected_defect,
                "expected_issue_codes": list(sample.expected_issue_codes),
                "attempt_count": 0,
                "request_success": False,
                "latency_ms": None,
                "json_compliant": False,
                "error": None,
                "token_usage": None,
                "raw_model_text": None,
                "judge_result": None,
            }
            try:
                raw_text, elapsed_ms, attempt_count, token_usage = _request(
                    provider,
                    sample,
                    keys[provider.provider_id],
                )
                record["attempt_count"] = attempt_count
                record["request_success"] = True
                record["latency_ms"] = round(elapsed_ms, 3)
                record["token_usage"] = token_usage
                record["raw_model_text"] = raw_text
                result, error = validate_judge_json(raw_text)
                record["judge_result"] = result
                record["json_compliant"] = result is not None
                record["error"] = error
            except RequestError as exc:
                record["attempt_count"] = exc.attempt_count
                record["error"] = str(exc)
            records_by_provider[provider.provider_id].append(record)
            print(
                f"{provider.model} {sample.sample_id}: "
                f"json={'ok' if record['json_compliant'] else 'invalid'} "
                f"latency_ms={record['latency_ms']}",
                file=sys.stderr,
                flush=True,
            )
    summaries = [
        summarize(
            provider,
            records_by_provider[provider.provider_id],
            expected_sample_count,
        )
        for provider in providers
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "dataset": str(dataset_path.resolve()),
        "prompt": PROMPT,
        "metric_definition": {
            "unit": "scene",
            "request_success_rate": "successful API responses / attempted scenes",
            "miss_rate": "positive scenes with a valid pass and no issue / evaluated positive scenes; null until all positive scenes are evaluated",
            "false_positive_rate": "evaluated negative scenes with a non-pass result or issue / evaluated negative scenes; null until all negative scenes are evaluated",
            "json_compliance_rate": "responses matching the exact five-field judge contract / successful API responses",
            "end_to_end_json_coverage_rate": "responses matching the exact five-field judge contract / attempted scenes",
            "model_identity_match_rate": "successful responses whose model field exactly matches the configured model / successful responses",
            "issue_code_detection_recall": "positive scenes for one expected issue code with a non-pass result or any issue / evaluated scenes for that code",
            "issue_code_classification_recall": "positive scenes whose issues include the expected issue code / evaluated scenes for that code",
            "latency_ms": "end-to-end request time including overload backoff and remote inference; local base64 preparation excluded",
            "token_usage": "provider-reported prompt, completion and total token counts; monetary charge is not inferred",
        },
        "records": [
            record
            for provider in providers
            for record in records_by_provider[provider.provider_id]
        ],
        "summaries": summaries,
        "recommended_default_model": choose_default(summaries),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Blind benchmark for HanEngine image visual judges")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(".tmp/visual-judge-benchmark-report.json"))
    parser.add_argument(
        "--provider",
        action="append",
        choices=tuple(provider.provider_id for provider in PROVIDERS),
        help="provider to benchmark; repeat to select multiple (default: all)",
    )
    parser.add_argument(
        "--sample-id",
        action="append",
        help="sample to benchmark; repeat to select a subset (default: all)",
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    selected_ids = set(args.provider or ())
    providers = tuple(
        provider for provider in PROVIDERS if not selected_ids or provider.provider_id in selected_ids
    )
    try:
        samples = load_dataset(args.dataset)
        if args.validate_only:
            positives = sum(sample.expected_defect for sample in samples)
            print(f"dataset valid: {len(samples)} scenes, {positives} positive, {len(samples) - positives} negative")
            return 0
        report = run(args.dataset, args.output, providers, tuple(args.sample_id) if args.sample_id else None)
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report["summaries"], ensure_ascii=False, indent=2))
    print(f"recommended_default_model={report['recommended_default_model']}")
    print(f"report={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
