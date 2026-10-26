from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Keep the documented ``python tools/...`` invocation independent of the
# caller's current working directory and Python path configuration.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from game_localizer.hanengine import (
    MultiEngineError,
    MultiEngineExtractor,
    benchmark_local_model,
    write_local_model_benchmark,
)


ENGINE_IDS = ("godot", "rpg_maker_mv", "rpg_maker_mz", "unity", "unreal")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="抽样调用本地模型，并生成 HanEngine 翻译基准报告。"
    )
    parser.add_argument("project", help="游戏项目目录")
    parser.add_argument("--engine", required=True, choices=ENGINE_IDS)
    parser.add_argument("--endpoint", required=True, help="本机 HTTP 翻译端点")
    parser.add_argument("--model-name", default="unknown")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--sample-count", type=int, default=100)
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--source-language", default="en")
    parser.add_argument("--output", required=True, help="JSON 报告路径")
    return parser


def _report_is_outside_project(project: Path, output: Path) -> bool:
    return output != project and project not in output.parents


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        project = Path(args.project).expanduser().resolve(strict=True)
        if not project.is_dir():
            raise ValueError("project must be a directory")
        output = Path(args.output).expanduser().resolve(strict=False)
        if not _report_is_outside_project(project, output):
            raise ValueError("benchmark report must be outside the source project")
        catalog = MultiEngineExtractor().extract(
            args.engine,
            project,
            language=args.language,
            source_language=args.source_language,
        )
        print(f"Extracted {len(catalog.entries)} entries from {len(catalog.files)} files")
        report = benchmark_local_model(
            catalog,
            args.endpoint,
            model_name=args.model_name,
            timeout=args.timeout,
            sample_count=args.sample_count,
        )
        report_path = write_local_model_benchmark(report, output)
        print(
            f"Benchmark: {report.translated_count}/{report.sample_count} translated; "
            f"failed={report.failed_count}; report={report_path}"
        )
        return 0 if report.passed else 1
    except (OSError, ValueError, MultiEngineError, json.JSONDecodeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
