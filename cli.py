from __future__ import annotations

import argparse
import json
import sys

from translator import ProcessingResult, TranslationError, process_resource


ETHICS = (
    "\u4ec5\u7528\u4e8e\u5408\u6cd5\u62e5\u6709\u6216\u5df2\u83b7\u6388\u6743\u7684\u6e38\u620f\u8d44\u6e90\uff1b"
    "\u4e0d\u652f\u6301\u7834\u89e3\u3001\u89e3\u5bc6\u6216\u7ed5\u8fc7\u4fdd\u62a4\u3002"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"\u8f7b\u91cf\u7ea7\u672c\u5730\u6e38\u620f\u6c49\u5316\u8f85\u52a9\u5de5\u5177\u3002\n{ETHICS}"
    )
    parser.add_argument(
        "resource", help="\u660e\u6587\u8d44\u6e90\u6587\u4ef6\uff08TXT/KS/RPY/SCRIPT/CSV/JSON\uff09"
    )
    parser.add_argument("dictionary", help="UTF-8 JSON \u7ffb\u8bd1\u5b57\u5178")
    parser.add_argument("--output", help="\u6c49\u5316\u8d44\u6e90\u8f93\u51fa\u8def\u5f84")
    parser.add_argument("--untranslated", help="\u672a\u7ffb\u8bd1 JSON \u6e05\u5355\u8f93\u51fa\u8def\u5f84")
    return parser


def format_result(result: ProcessingResult, preview_limit: int = 50) -> str:
    preview_limit = max(0, preview_limit)
    lines: list[str] = []
    for item in result.matches[:preview_limit]:
        lines.append(
            f"[\u5339\u914d] {item.location}: {json.dumps(item.original, ensure_ascii=False)} -> "
            f"{json.dumps(item.translated, ensure_ascii=False)}"
        )
    if len(result.matches) > preview_limit:
        lines.append(f"[\u5339\u914d] \u53e6\u6709 {len(result.matches) - preview_limit} \u9879\u5df2\u7701\u7565")
    for item in result.unmatched[:preview_limit]:
        lines.append(
            f"[\u672a\u5339\u914d] {item.location}: {json.dumps(item.original, ensure_ascii=False)}"
        )
    if len(result.unmatched) > preview_limit:
        lines.append(
            f"[\u672a\u5339\u914d] \u53e6\u6709 {len(result.unmatched) - preview_limit} \u9879\u5df2\u7701\u7565"
        )
    for warning in result.warnings:
        lines.append(
            f"[\u5360\u4f4d\u7b26\u8b66\u544a] {warning.location}: \u7f3a\u5c11 {', '.join(warning.missing)}"
        )
    for path in result.overwritten_paths:
        lines.append(f"[\u8986\u76d6] \u5df2\u8986\u76d6\u73b0\u6709\u6587\u4ef6: {path}")
    lines.extend(
        [
            f"\u8f93\u5165\u7f16\u7801: {result.input_encoding}",
            f"\u8f93\u51fa\u7f16\u7801: {result.output_encoding}",
            f"\u5339\u914d\u6761\u76ee: {len(result.matched_keys)}",
            f"\u5b9e\u9645\u66ff\u6362: {result.replacement_count}",
            f"\u672a\u7ffb\u8bd1\u6761\u76ee: {len(result.untranslated)}",
            f"\u5360\u4f4d\u7b26\u8b66\u544a: {len(result.warnings)}",
            f"\u6c49\u5316\u6587\u4ef6: {result.output_path}",
            f"\u5f85\u7ffb\u8bd1\u6e05\u5355: {result.untranslated_path}",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        result = process_resource(
            args.resource,
            args.dictionary,
            output_path=args.output,
            untranslated_path=args.untranslated,
        )
    except TranslationError as exc:
        print(f"\u9519\u8bef: {exc}", file=sys.stderr)
        return 1
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
