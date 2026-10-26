from __future__ import annotations

import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Mapping

from game_localizer.hanengine.multiengine import LocalizationCatalog, extract_placeholders


COMPARISON_SCHEMA_VERSION = "hanengine.translation-comparison/v1"


def _contains_replacement_character(value: str) -> bool:
    return "\ufffd" in value


def _contains_english(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value))


def _issue(
    *,
    entry: Mapping[str, object],
    official_text: str | None,
    category: str,
    severity: str,
    reasons: list[str],
) -> dict[str, object]:
    return {
        "segment_id": entry["segment_id"],
        "relative_path": entry["relative_path"],
        "table_name": entry["locator"].get("table_name"),
        "entry_id": entry["locator"].get("entry_id"),
        "source_text": entry["source_text"],
        "official_zh": official_text,
        "candidate_zh": entry.get("target_text"),
        "category": category,
        "severity": severity,
        "reasons": reasons,
        "decision": "pending" if category != "match" else "accepted",
        "recommended_text": official_text if official_text is not None else entry.get("target_text"),
    }


def compare_unity_catalog(
    project_root: Path,
    catalog: LocalizationCatalog,
    *,
    official_bundle: Path | None = None,
) -> dict[str, object]:
    """Compare English source, packaged Simplified Chinese, and candidate text.

    The packaged Chinese value is evidence for review, not an automatic source of
    truth. Differences are therefore reported as pending instead of silently
    replacing the candidate translation.
    """

    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a Path")
    if not isinstance(catalog, LocalizationCatalog):
        raise TypeError("catalog must be a LocalizationCatalog")
    if catalog.engine_id != "unity":
        raise ValueError("Unity comparison requires a unity catalog")
    from game_localizer.adapters.unity_addressables import _profile, _read_tables

    profile = _profile(project_root)
    if profile is None:
        raise ValueError("project does not contain a supported Unity Localization Addressables profile")

    if official_bundle is None:
        official_records = profile.chinese_records
    else:
        official_bundle = official_bundle.expanduser().resolve(strict=True)
        official_records = _read_tables(official_bundle, "_zh-cn")
    official = {(record.table_name, record.entry_id): record.text for record in official_records}
    source = {
        (record.table_name, record.entry_id): record.text
        for record in profile.english_records
    }
    rows: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    for entry in catalog.entries:
        table_name = entry.locator.get("table_name")
        entry_id = entry.locator.get("entry_id")
        key = (table_name, entry_id)
        official_text = official.get(key)
        source_text = source.get(key)
        target = entry.target_text
        reasons: list[str] = []
        source_mismatch = source_text is None or source_text != entry.source_text
        if source_mismatch:
            reasons.append("source_mismatch")
        if official_text is None:
            reasons.append("official_entry_missing")
        if source_mismatch:
            category, severity = "source_mismatch", "error"
        elif target is None or not target.strip():
            category, severity = "missing_target", "error"
            reasons.append("missing_target_text")
        elif _contains_replacement_character(target):
            category, severity = "corrupt_output", "error"
            reasons.append("replacement_character")
        elif Counter(extract_placeholders(entry.source_text)) != Counter(extract_placeholders(target)):
            category, severity = "format_error", "error"
            reasons.append("placeholder_mismatch")
        elif official_text is not None and target == official_text:
            # Official text kept identical to the source (units, brands): the
            # candidate matches the official choice even though the source is
            # unchanged, so this is a match rather than an untranslated entry.
            category, severity = "match", "none"
        elif target.strip() == entry.source_text.strip() and _contains_english(target):
            category, severity = "untranslated", "warning"
            reasons.append("source_text_unchanged")
        elif official_text is None:
            category, severity = "candidate_only", "warning"
        else:
            category, severity = "difference", "review"
            reasons.append("candidate_differs_from_official")
            if _contains_english(target) and not _contains_english(official_text):
                reasons.append("residual_english")
        row = _issue(
            entry=entry.to_dict(),
            official_text=official_text,
            category=category,
            severity=severity,
            reasons=reasons,
        )
        rows.append(row)
        counts[category] += 1
        severity_counts[severity] += 1

    rows.sort(key=lambda item: (-{"error": 3, "warning": 2, "review": 1, "none": 0}[item["severity"]], str(item["segment_id"])))
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "engine_id": "unity",
        "project_fingerprint": catalog.project_fingerprint,
        "source_files": list(catalog.files),
        "summary": {
            "entry_count": len(rows),
            "match_count": counts["match"],
            "difference_count": counts["difference"],
            "error_count": severity_counts["error"],
            "warning_count": severity_counts["warning"],
            "review_count": severity_counts["review"],
            "categories": dict(sorted(counts.items())),
        },
        "entries": rows,
    }


def write_comparison_report(report: dict[str, object], output: Path) -> Path:
    if not isinstance(report, dict):
        raise TypeError("report must be a dictionary")
    output = output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _html_row(entry: Mapping[str, object]) -> str:
    def cell(value: object) -> str:
        return html.escape("" if value is None else str(value)).replace("\n", "<br>")

    return (
        f'<tr data-severity="{cell(entry["severity"])}" data-category="{cell(entry["category"])}">'
        f"<td><span class=\"badge {cell(entry['severity'])}\">{cell(entry['severity'])}</span></td>"
        f"<td>{cell(entry['category'])}</td>"
        f"<td><code>{cell(entry['table_name'])}:{cell(entry['entry_id'])}</code><br>{cell(entry['source_text'])}</td>"
        f"<td>{cell(entry['official_zh'])}</td><td>{cell(entry['candidate_zh'])}</td>"
        f"<td>{cell(', '.join(entry['reasons']))}</td></tr>"
    )


def comparison_html(report: Mapping[str, object]) -> str:
    summary = report["summary"]
    entries = report["entries"]
    rows = "\n".join(_html_row(entry) for entry in entries)
    payload = json.dumps(summary, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>HanEngine 三方翻译对比</title>
<style>body{{font:14px system-ui,sans-serif;margin:24px;color:#202124}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;vertical-align:top;text-align:left}}th{{background:#f3f4f6;position:sticky;top:0}}textarea,select{{padding:6px;margin:4px 8px 12px 0}}.badge{{padding:2px 6px;border-radius:3px}}.error{{background:#ffd8d8}}.warning{{background:#fff0c2}}.review{{background:#dcecff}}.none{{background:#e7e7e7}}code{{white-space:nowrap}}</style></head>
<body><h1>Unity 三方翻译对比</h1><p id="summary"></p>
<label>筛选严重度 <select id="severity"><option value="">全部</option><option>error</option><option>warning</option><option>review</option><option>none</option></select></label>
<label>搜索 <input id="search" type="search" placeholder="英文、中文、表名"></label>
<table><thead><tr><th>严重度</th><th>类别</th><th>英文原文</th><th>游戏原中文</th><th>当前译文</th><th>原因</th></tr></thead><tbody>{rows}</tbody></table>
<script>const summary={payload};document.querySelector('#summary').textContent=`共 ${{summary.entry_count}} 条：匹配 ${{summary.match_count}}，差异 ${{summary.difference_count}}，错误 ${{summary.error_count}}，待复核 ${{summary.review_count}}`;
const filter=()=>{{const severity=document.querySelector('#severity').value.toLowerCase(),query=document.querySelector('#search').value.toLowerCase();document.querySelectorAll('tbody tr').forEach(row=>{{row.hidden=Boolean((severity&&row.dataset.severity!==severity)|| (query&&!row.textContent.toLowerCase().includes(query)));}})}};document.querySelector('#severity').onchange=filter;document.querySelector('#search').oninput=filter;</script></body></html>
"""


def write_comparison_html(report: Mapping[str, object], output: Path) -> Path:
    output = output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(comparison_html(report), encoding="utf-8")
    return output


__all__ = [
    "COMPARISON_SCHEMA_VERSION",
    "compare_unity_catalog",
    "comparison_html",
    "write_comparison_html",
    "write_comparison_report",
]
