from __future__ import annotations

import argparse
import sys

from translator import ProcessingResult, TranslationError, process_resource


ETHICS = "浠呯敤浜庡悎娉曟嫢鏈夋垨宸茶幏鎺堟潈鐨勬父鎴忚祫婧愶紱涓嶆敮鎸佺牬瑙ｃ€佽В瀵嗘垨缁曡繃淇濇姢銆?"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"杞婚噺绾ф湰鍦版父鎴忔眽鍖栬緟鍔╁伐鍏枫€倇{ETHICS}")
    parser.add_argument("resource", help="鏄庢枃璧勬簮鏂囦欢锛圱XT/KS/RPY/SCRIPT/CSV/JSON锛? ")
    parser.add_argument("dictionary", help="UTF-8 JSON 缈昏瘧瀛楀吀")
    parser.add_argument("--output", help="姹夊寲璧勬簮杈撳嚭璺緞")
    parser.add_argument("--untranslated", help="鏈炕璇?JSON 娓呭崟杈撳嚭璺緞")
    return parser


def format_result(result: ProcessingResult, preview_limit: int = 50) -> str:
    lines: list[str] = []
    for item in result.matches[:preview_limit]:
        lines.append(f'[鍖归厤] {item.location}: "{item.original}" -> "{item.translated}"')
    if len(result.matches) > preview_limit:
        lines.append(f"[鍖归厤] 鍙︽湁 {len(result.matches) - preview_limit} 椤瑰凡鐪佺暐")
    for item in result.unmatched[:preview_limit]:
        lines.append(f'[鏈尮閰峕 {item.location}: "{item.original}"')
    if len(result.unmatched) > preview_limit:
        lines.append(f"[鏈尮閰峕 鍙︽湁 {len(result.unmatched) - preview_limit} 椤瑰凡鐪佺暐")
    for warning in result.warnings:
        lines.append(f"[鍗犱綅绗﹁鍛奭 {warning.location}: 缂哄皯 {', '.join(warning.missing)}")
    lines.extend(
        [
            f"杈撳叆缂栫爜: {result.input_encoding}",
            f"杈撳嚭缂栫爜: {result.output_encoding}",
            f"鍖归厤鏉＄洰: {len(result.matched_keys)}",
            f"瀹為檯鏇挎崲: {result.replacement_count}",
            f"鏈炕璇戞潯鐩? {len(result.untranslated)}",
            f"鍗犱綅绗﹁鍛? {len(result.warnings)}",
            f"姹夊寲鏂囦欢: {result.output_path}",
            f"寰呯炕璇戞竻鍗? {result.untranslated_path}",
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
        print(f"閿欒: {exc}", file=sys.stderr)
        return 1
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
