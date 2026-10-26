"""Mine a game-specific glossary from a HanEngine translation comparison report.

The comparison report pairs each English source string with the game's official
Simplified Chinese text.  Short, repeated source strings that the official
translators rendered consistently are safe to pin as exact-match dictionary
terms: they bypass the model entirely, which removes terminology drift,
unit mistranslations, and mixed-language leftovers.

Usage:
    python tools/mine_glossary.py comparison.json --output glossary.json \
        --report glossary-report.json

The output glossary is a plain JSON object mapping source strings to official
Chinese strings, directly usable as ``--dictionary`` input.  The optional
report records per-term frequencies and conflicting official renderings so a
human can decide what to pin.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

COMPARISON_SCHEMA = "hanengine.translation-comparison/v1"

# A term is a short label-like string: no sentence punctuation, few words.
_TERM_DISQUALIFIED = re.compile(r"[.!?;:，。！？；：…]")
_CJK = re.compile(r"[\u3400-\u9fff]")
_WORD = re.compile(r"[A-Za-z]+")
_MAX_TERM_WORDS = 4
_MAX_TERM_CHARS = 40


def _is_term_like(source: str) -> bool:
    stripped = source.strip()
    if not stripped or len(stripped) > _MAX_TERM_CHARS:
        return False
    if _TERM_DISQUALIFIED.search(stripped):
        return False
    words = _WORD.findall(stripped)
    if not words or len(words) > _MAX_TERM_WORDS:
        return False
    if stripped.isdigit():
        return False
    return True


def _is_usable_reference(official: str) -> bool:
    value = official.strip()
    if not value:
        return False
    # Either real Chinese, or a deliberately kept Latin token (units, brands).
    return bool(_CJK.search(value)) or bool(_WORD.fullmatch(value))


def mine_glossary(report: dict) -> tuple[dict[str, str], dict[str, object]]:
    if not isinstance(report, dict) or report.get("schema_version") != COMPARISON_SCHEMA:
        raise ValueError("comparison report has an unsupported schema")
    entries = report.get("entries")
    if not isinstance(entries, list):
        raise ValueError("comparison report entries must be a list")

    renderings: dict[str, Counter[str]] = defaultdict(Counter)
    for item in entries:
        if not isinstance(item, dict):
            continue
        source = item.get("source_text")
        official = item.get("official_zh")
        if not isinstance(source, str) or not isinstance(official, str):
            continue
        if not _is_term_like(source) or not _is_usable_reference(official):
            continue
        renderings[source.strip()][official.strip()] += 1

    terms: dict[str, str] = {}
    conflicts: list[dict[str, object]] = []
    frequencies: dict[str, int] = {}
    for source, counter in renderings.items():
        total = sum(counter.values())
        if len(counter) == 1:
            translation = next(iter(counter))
            terms[source] = translation
            frequencies[source] = total
        else:
            conflicts.append(
                {
                    "source": source,
                    "count": total,
                    "renderings": dict(counter.most_common()),
                }
            )
    ordered_terms = {key: terms[key] for key in sorted(terms, key=str.casefold)}
    report_out = {
        "schema_version": "hanengine.glossary-mining/v1",
        "term_count": len(ordered_terms),
        "conflict_count": len(conflicts),
        "frequencies": dict(
            sorted(frequencies.items(), key=lambda item: -item[1])
        ),
        "conflicts": sorted(conflicts, key=lambda item: -item["count"]),
    }
    return ordered_terms, report_out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mine an exact-match glossary from a translation comparison report."
    )
    parser.add_argument(
        "report", help="comparison report JSON (hanengine.translation-comparison/v1)"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="glossary JSON path (plain {source: zh} object, usable as --dictionary)",
    )
    parser.add_argument(
        "--report-out",
        help="optional mining report JSON path (frequencies and conflicts)",
    )
    args = parser.parse_args(argv)

    report_path = Path(args.report).expanduser()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    terms, mining = mine_glossary(data)

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(terms, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.report_out:
        mining_path = Path(args.report_out).expanduser()
        mining_path.parent.mkdir(parents=True, exist_ok=True)
        mining_path.write_text(
            json.dumps(mining, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(
        f"Mined {mining['term_count']} terms "
        f"({mining['conflict_count']} conflicts) -> {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
