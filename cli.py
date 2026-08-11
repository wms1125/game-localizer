from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from game_localizer.adapters import get_adapters, get_adapters_v1
from game_localizer.adapters.contract import DeclaredMode
from game_localizer.detector import detect_project
from game_localizer.models import DetectionStatus
from game_localizer.reporting import format_detection_report
from game_localizer.scanner import ProjectScanError
from translator import ProcessingResult, TranslationError, process_resource
from translator import load_translation_dictionary
from game_localizer.hanengine import (
    CloudTranslationProvider,
    CommandImageVisualJudge,
    DictionaryTranslationProvider,
    EvaluationStatus,
    HanStore,
    PipelineTranslationFailed,
    OfficialValidatorConfig,
    ProjectBusyError,
    ProjectValidationRequest,
    ProjectValidationRunner,
    RenPyCatalog,
    RenPyExtractor,
    RenPyWriter,
    RiskLevel,
    RouteOperation,
    RoutePhase,
    RoutePlan,
    TranslationRequest,
    TranslationRouter,
    TaskRetrySpec,
    TaskState,
    TtsRequest,
    WindowsSapiTts,
    ZipPackageModifier,
    prepare_visual_evidence_manifest,
    renpy_sdk_validator,
    run_renpy_capture_pair,
    run_visual_evidence,
)
from game_localizer.hanengine.multiengine import LocalizationCatalog
from game_localizer.hanengine.auth import AuthError, UserStore, auth_payload
from game_localizer.structured_workflow import (
    STRUCTURED_ENGINE_IDS,
    StructuredValidationFailed,
    StructuredVerificationFailed,
    StructuredWorkflowSession,
    default_workflow_state_root,
    format_guard_decision,
    format_persisted_task_event,
)


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


def build_detect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"自动检测游戏项目引擎。\n{ETHICS}")
    parser.add_argument("project", help="游戏项目目录")
    parser.add_argument("--json", action="store_true", help="将检测报告以 JSON 输出到标准输出")
    return parser


def build_engines_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="列出内置引擎检测适配器")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    return parser


def run_detect(argv: list[str]) -> int:
    try:
        args = build_detect_parser().parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    try:
        report = detect_project(args.project)
    except ProjectScanError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_detection_report(report))
    return 0 if report.status is DetectionStatus.AUTO_SELECTED else 2


def run_engines(argv: list[str]) -> int:
    try:
        args = build_engines_parser().parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    v1_by_engine = {
        adapter.engine_id: adapter
        for adapter in get_adapters_v1()
    }
    payload = [
        {
            "engine_id": adapter.engine_id,
            "display_name": adapter.display_name,
            "maturity": (
                v1_by_engine[adapter.engine_id].metadata.maturity.value
                if adapter.engine_id in v1_by_engine
                else adapter.maturity.value
            ),
            "capability": (
                ",".join(
                    sorted(
                        item.value
                        for item in v1_by_engine[adapter.engine_id].metadata.capabilities
                    )
                )
                if adapter.engine_id in v1_by_engine
                else "detect"
            ),
            "adapter_contract": (
                v1_by_engine[adapter.engine_id].metadata.contract_version
                if adapter.engine_id in v1_by_engine
                else None
            ),
            "structured_resource_pipeline": adapter.engine_id in v1_by_engine,
        }
        for adapter in get_adapters()
    ]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in payload:
            print(
                f"{item['engine_id']}: {item['display_name']} / "
                f"{item['capability']} / {item['maturity']}"
            )
    return 0


def _parse_args(parser: argparse.ArgumentParser, argv: list[str]):
    try:
        return parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1


def run_renpy(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=f"Ren'Py 明文项目提取与独立 tl/ 写回。\n{ETHICS}")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="提取可翻译文本目录")
    extract.add_argument("project")
    extract.add_argument("--output", required=True)
    extract.add_argument("--language", default="zh_cn")
    build = commands.add_parser("build", help="生成独立 tl/ 输出")
    build.add_argument("project")
    build.add_argument("catalog")
    build.add_argument("--output", required=True)
    build.add_argument("--dictionary")
    args = _parse_args(parser, argv)
    if isinstance(args, int):
        return args
    try:
        project = Path(args.project)
        if args.command == "extract":
            catalog = RenPyExtractor().extract(project, language=args.language)
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(catalog.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            print(f"已提取 {len(catalog.entries)} 条文本: {output}")
            return 0
        payload = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        catalog = RenPyCatalog.from_dict(payload)
        if args.dictionary:
            catalog = catalog.translate(load_translation_dictionary(args.dictionary))
        result = RenPyWriter().build(catalog, Path(args.output), source_root=project)
        print(f"已写入 {result.entries_written} 条翻译: {result.path}")
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


def _add_engine_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-root",
        help="HanStore directory for persisted routes, tasks, events and segments",
    )
    parser.add_argument(
        "--mode",
        choices=(DeclaredMode.STUDIO.value, DeclaredMode.PLAYER.value),
        default=DeclaredMode.STUDIO.value,
        help="authorization mode used as HanGuard input",
    )
    parser.add_argument(
        "--risk-level",
        choices=tuple(item.name for item in RiskLevel),
        help="explicit HanGuard baseline; defaults to H0 for studio and H1 for player",
    )
    parser.add_argument(
        "--quiet-progress",
        action="store_true",
        help="suppress persisted HanTask event lines",
    )


def _add_pipeline_translation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dictionary", help="UTF-8 JSON exact-match translation dictionary")
    parser.add_argument(
        "--cloud-endpoint",
        help="HTTPS translation endpoint used after dictionary misses",
    )
    parser.add_argument(
        "--token-env",
        default="HANENGINE_TRANSLATION_TOKEN",
        help="environment variable containing the cloud bearer token",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="ignore persisted segment translations and translate them again",
    )
    parser.add_argument(
        "--translated-catalog",
        help="optional path for the completed translated catalog JSON",
    )


def _translation_router(args) -> TranslationRouter | None:
    providers = []
    if args.dictionary:
        providers.append(
            DictionaryTranslationProvider(
                load_translation_dictionary(args.dictionary)
            )
        )
    if args.cloud_endpoint:
        providers.append(
            CloudTranslationProvider(
                args.cloud_endpoint,
                token_provider=lambda: os.environ.get(args.token_env),
            )
        )
    return None if not providers else TranslationRouter(providers)


def _write_localization_catalog(catalog: LocalizationCatalog, path: Path) -> Path:
    output = path.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output


def _engine_retry_arguments(args, project: Path, state_root: Path, risk: RiskLevel) -> tuple[str, ...]:
    arguments = [args.command, args.engine, str(project)]
    if args.command == "build":
        arguments.append(str(Path(args.catalog).expanduser().resolve(strict=True)))
    arguments.extend(
        ["--output", str(Path(args.output).expanduser().resolve(strict=False))]
    )
    if args.command in {"extract", "localize"}:
        arguments.extend(
            [
                "--language",
                args.language,
                "--source-language",
                args.source_language,
            ]
        )
    dictionary = getattr(args, "dictionary", None)
    if dictionary:
        arguments.extend(
            [
                "--dictionary",
                str(Path(dictionary).expanduser().resolve(strict=True)),
            ]
        )
    cloud_endpoint = getattr(args, "cloud_endpoint", None)
    if cloud_endpoint:
        arguments.extend(["--cloud-endpoint", cloud_endpoint])
    token_env = getattr(args, "token_env", "HANENGINE_TRANSLATION_TOKEN")
    if token_env != "HANENGINE_TRANSLATION_TOKEN":
        arguments.extend(["--token-env", token_env])
    translated_catalog = getattr(args, "translated_catalog", None)
    if translated_catalog:
        arguments.extend(
            [
                "--translated-catalog",
                str(
                    Path(translated_catalog)
                    .expanduser()
                    .resolve(strict=False)
                ),
            ]
        )
    arguments.extend(
        [
            "--state-root",
            str(state_root),
            "--mode",
            args.mode,
            "--risk-level",
            risk.name,
        ]
    )
    return tuple(arguments)


def run_engine(
    argv: list[str],
    *,
    retry_of: str | None = None,
    event_listener_override=None,
) -> int:
    parser = argparse.ArgumentParser(
        description=f"Extract and build safe, structured localization resources.\n{ETHICS}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="extract a structured engine catalog")
    extract.add_argument("engine", choices=("auto", *STRUCTURED_ENGINE_IDS))
    extract.add_argument("project")
    extract.add_argument("--output", required=True)
    extract.add_argument("--language", default="zh-CN")
    extract.add_argument("--source-language", default="en")
    _add_engine_runtime_options(extract)
    inspect = commands.add_parser(
        "inspect",
        help="inspect AdapterV1 capabilities and HanGuard decision without modifying the project",
    )
    inspect.add_argument("engine", choices=("auto", *STRUCTURED_ENGINE_IDS))
    inspect.add_argument("project")
    inspect.add_argument("--json", action="store_true")
    _add_engine_runtime_options(inspect)
    build = commands.add_parser("build", help="build a translated copy outside the source project")
    build.add_argument("engine", choices=("auto", *STRUCTURED_ENGINE_IDS))
    build.add_argument("project")
    build.add_argument("catalog")
    build.add_argument("--output", required=True)
    _add_pipeline_translation_options(build)
    _add_engine_runtime_options(build)
    localize = commands.add_parser(
        "localize",
        help="extract, translate, validate, build and verify in one resumable pipeline",
    )
    localize.add_argument("engine", choices=("auto", *STRUCTURED_ENGINE_IDS))
    localize.add_argument("project")
    localize.add_argument("--output", required=True)
    localize.add_argument("--language", default="zh-CN")
    localize.add_argument("--source-language", default="en")
    _add_pipeline_translation_options(localize)
    _add_engine_runtime_options(localize)
    args = _parse_args(parser, argv)
    if isinstance(args, int):
        return args
    try:
        project = Path(args.project).expanduser().resolve(strict=True)
        mode = DeclaredMode(args.mode)
        risk = (
            RiskLevel[args.risk_level]
            if args.risk_level
            else (RiskLevel.H0_PROJECT if mode is DeclaredMode.STUDIO else RiskLevel.H1_OFFLINE)
        )
        state_root = _task_state_root(args.state_root)
        if args.command == "inspect":
            with StructuredWorkflowSession(
                project,
                engine_id=args.engine,
                target_language="zh-CN",
                source_language="en",
                state_root=state_root,
                declared_mode=mode,
                user_baseline=risk,
                adapter_baseline=risk,
                event_listener=lambda _event: None,
            ) as workflow:
                selection = workflow.detect()
                adapter = workflow.runtime.registry.get(selection.adapter_id)
                detection = selection.detection
                capabilities = sorted(item.value for item in detection.capabilities)
                allowed = sorted(item.value for item in selection.final_route.allowed_operations)
                required = {"extract", "validate", "build", "verify"}
                localize_ready = required.issubset(set(capabilities)) and required.issubset(set(allowed))
                payload = {
                    "status": "ready" if localize_ready else "detect_only",
                    "selected_engine": getattr(adapter, "engine_id", args.engine),
                    "candidate": {
                        "engine_id": getattr(adapter, "engine_id", args.engine),
                        "display_name": getattr(adapter.metadata, "engine_name", args.engine),
                        "score": round(detection.confidence * 100),
                        "capability": capabilities,
                        "maturity": detection.maturity.value,
                        "limitations": list(detection.limitations),
                        "evidence": [
                            {
                                "code": item.code,
                                "source": item.source.value,
                                "value": item.value,
                                "weight": item.weight,
                                "description": item.description,
                            }
                            for item in detection.evidence
                        ],
                    },
                    "capabilities": capabilities,
                    "allowed_operations": allowed,
                    "hanguard": selection.final_route.to_dict(),
                    "task_id": selection.detection_task.task_id,
                    "state_root": str(state_root),
                }
                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
                else:
                    print(f"Engine: {payload['selected_engine']}")
                    print(f"Capability: {', '.join(capabilities) or '-'}")
                    print(f"HanGuard: {format_guard_decision(selection.final_route)}")
                    print(f"Status: {payload['status']}")
                return 0
        retry_spec = TaskRetrySpec.create(
            "engine",
            _engine_retry_arguments(args, project, state_root, risk),
            parent_task_id=retry_of,
        )

        def event_listener(event) -> None:
            if event_listener_override is not None:
                event_listener_override(event)
            elif not args.quiet_progress:
                print(format_persisted_task_event(event))

        if args.command in {"extract", "localize"}:
            target_language = args.language
            source_language = args.source_language
        else:
            catalog = LocalizationCatalog.from_dict(
                json.loads(Path(args.catalog).read_text(encoding="utf-8"))
            )
            target_language = catalog.language
            source_language = catalog.source_language

        with StructuredWorkflowSession(
            project,
            engine_id=args.engine,
            target_language=target_language,
            source_language=source_language,
            state_root=state_root,
            declared_mode=mode,
            user_baseline=risk,
            adapter_baseline=risk,
            event_listener=event_listener,
            retry_spec=retry_spec,
        ) as workflow:
            selection = workflow.detect()
            print(format_guard_decision(selection.final_route))
            print(f"[HanStore] project={workflow.project_id} state={workflow.state_root}")
            if args.command == "extract":
                outcome = workflow.extract()
                catalog = outcome.catalog
                output = _write_localization_catalog(catalog, Path(args.output))
                print(
                    f"Extracted {len(catalog.entries)} entries: {output} "
                    f"(task={outcome.execution.task.task_id})"
                )
                return 0

            if args.command == "localize":
                router = _translation_router(args)
                if router is None:
                    raise ValueError(
                        "localize requires --dictionary and/or --cloud-endpoint"
                    )
                extracted = workflow.extract()
                catalog = extracted.catalog
                print(
                    f"Extracted {len(catalog.entries)} entries "
                    f"(task={extracted.execution.task.task_id})"
                )
            else:
                router = _translation_router(args)

            if catalog.engine_id != args.engine and args.engine != "auto":
                raise ValueError("catalog engine does not match the requested engine")

            if router is not None:
                translation = workflow.translate(
                    catalog,
                    router,
                    resume=not args.no_resume,
                    retry_spec=retry_spec,
                )
                catalog = translation.catalog
                print(
                    "Translated "
                    f"{translation.translated_count} new, "
                    f"resumed {translation.resumed_count}, "
                    f"catalog {translation.catalog_count}, "
                    f"untranslated {translation.untranslated_count} "
                    f"(task={translation.task.task_id})"
                )
                if args.translated_catalog:
                    translated_path = _write_localization_catalog(
                        catalog,
                        Path(args.translated_catalog),
                    )
                    print(f"Translated catalog: {translated_path}")
            outcome = workflow.build(catalog, Path(args.output))
            build_result = outcome.build_result
            print(
                f"Built {build_result.statistics.get('segments', 0)} entries in {args.output} "
                f"(task={outcome.build.task.task_id})"
            )
            print(
                f"Verified {len(build_result.manifest)} files "
                f"(task={outcome.verification.task.task_id})"
            )
            return 0
    except PipelineTranslationFailed as exc:
        print(
            "Error: translation task failed after "
            f"{exc.translated_count} new and {exc.resumed_count} resumed segments "
            f"(task={exc.task.task_id}); rerun to continue",
            file=sys.stderr,
        )
        return 1
    except StructuredValidationFailed as exc:
        result = exc.execution.result
        codes = ", ".join(issue.code for issue in result.issues)
        print(f"Error: validation failed: {codes}", file=sys.stderr)
        return 1
    except StructuredVerificationFailed as exc:
        result = exc.execution.result
        codes = ", ".join(issue.code for issue in result.issues)
        print(f"Error: verification failed: {codes}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def run_project(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run an authorized AdapterV1 project validation and write a portable JSON record.\n"
            f"{ETHICS}"
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate",
        help="run detect, extract, translate, validate, build and verify",
    )
    validate.add_argument("engine", choices=("auto", *STRUCTURED_ENGINE_IDS))
    validate.add_argument("project")
    validate.add_argument("--output", required=True)
    validate.add_argument("--dictionary", required=True)
    validate.add_argument("--state-root", required=True)
    validate.add_argument("--record", required=True)
    validate.add_argument("--record-id", required=True)
    validate.add_argument("--project-label", required=True)
    validate.add_argument(
        "--authorized",
        action="store_true",
        help="assert that this project may be processed and validated",
    )
    validate.add_argument("--authorization-reference", required=True)
    validate.add_argument("--language", default="zh-CN")
    validate.add_argument("--source-language", default="en")
    validate.add_argument("--font", action="append", default=[])
    validator = validate.add_mutually_exclusive_group()
    validator.add_argument(
        "--validator",
        help="official validator executable; requires --validator-arg {output}",
    )
    validator.add_argument(
        "--renpy-sdk",
        help="Ren'Py launcher executable, invoked as <launcher> {output} compile",
    )
    validate.add_argument(
        "--validator-arg",
        action="append",
        default=[],
        help="validator argument; repeat and include one literal {output}",
    )
    validate.add_argument("--validator-timeout", type=int, default=120)
    validate.add_argument(
        "--runtime-smoke",
        choices=("not_run", "passed", "failed"),
        default="not_run",
    )
    validate.add_argument("--runtime-smoke-reference")
    args = _parse_args(parser, argv)
    if isinstance(args, int):
        return args
    try:
        if not args.authorized:
            raise ValueError("project validate requires explicit --authorized confirmation")
        if args.validator_arg and not args.validator:
            raise ValueError("--validator-arg requires --validator")
        if args.renpy_sdk:
            if args.engine not in {"auto", "renpy"}:
                raise ValueError("--renpy-sdk is only valid for a Ren'Py project")
            official_validator = renpy_sdk_validator(
                Path(args.renpy_sdk),
                timeout_seconds=args.validator_timeout,
            )
        elif args.validator:
            official_validator = OfficialValidatorConfig(
                command=Path(args.validator),
                arguments=tuple(args.validator_arg),
                timeout_seconds=args.validator_timeout,
            )
        else:
            official_validator = None
        request = ProjectValidationRequest(
            record_id=args.record_id,
            project_label=args.project_label,
            authorization_reference=args.authorization_reference,
            project_root=Path(args.project),
            engine_id=args.engine,
            output_root=Path(args.output),
            dictionary_path=Path(args.dictionary),
            state_root=Path(args.state_root),
            record_path=Path(args.record),
            target_language=args.language,
            source_language=args.source_language,
            font_paths=tuple(Path(path) for path in args.font),
            official_validator=official_validator,
            runtime_smoke=args.runtime_smoke,
            runtime_smoke_reference=args.runtime_smoke_reference,
        )
        record = ProjectValidationRunner().run(request)
        print(f"Validation conclusion: {record.conclusion}")
        print(f"Record: {request.record_path}")
        return 1 if record.conclusion == "failed" else 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def run_visual(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify paired localization screenshots with deterministic gates and an optional judge.\n"
            f"{ETHICS}"
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="verify a visual evidence manifest")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--output", required=True)
    verify.add_argument("--authorized", action="store_true")
    verify.add_argument("--authorization-reference", required=True)
    verify.add_argument("--judge-command")
    verify.add_argument("--judge-arg", action="append", default=[])
    verify.add_argument("--judge-timeout", type=int, default=120)
    verify.add_argument("--judge-provider", default="external-command")
    prepare = commands.add_parser(
        "prepare",
        help="prepare a manual visual evidence manifest from a verified Ren'Py capture report",
    )
    prepare.add_argument("--capture-report", required=True)
    prepare.add_argument("--annotations", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--authorized", action="store_true")
    capture = commands.add_parser(
        "capture-renpy",
        help="capture paired Ren'Py reference and candidate screenshots",
    )
    capture.add_argument("--renpy-sdk", required=True)
    capture.add_argument("--reference-project", required=True)
    capture.add_argument("--candidate-project", required=True)
    capture.add_argument("--plan", required=True)
    capture.add_argument("--output", required=True)
    capture.add_argument("--authorized", action="store_true")
    capture.add_argument("--authorization-reference", required=True)
    capture.add_argument("--reference-game-language", choices=("source", "zh_cn"))
    capture.add_argument("--candidate-game-language", choices=("source", "zh_cn"))
    capture.add_argument("--reference-window-title")
    capture.add_argument("--candidate-window-title")
    args = _parse_args(parser, argv)
    if isinstance(args, int):
        return args
    try:
        if not args.authorized:
            raise ValueError(f"visual {args.command} requires explicit --authorized confirmation")
        if args.command == "prepare":
            manifest = prepare_visual_evidence_manifest(
                Path(args.capture_report),
                Path(args.annotations),
                Path(args.output),
            )
            print(f"Prepared samples: {len(manifest.samples)}")
            print(f"Manifest: {Path(args.output).expanduser().absolute()}")
            return 0
        if args.command == "capture-renpy":
            report = run_renpy_capture_pair(
                Path(args.renpy_sdk),
                Path(args.reference_project),
                Path(args.candidate_project),
                Path(args.plan),
                Path(args.output),
                authorization_reference=args.authorization_reference,
                reference_game_language=args.reference_game_language,
                candidate_game_language=args.candidate_game_language,
                reference_window_title=args.reference_window_title,
                candidate_window_title=args.candidate_window_title,
            )
            print(f"Capture status: {'passed' if report.passed else 'failed'}")
            print(f"Report: {Path(args.output).expanduser().absolute() / 'capture-report.json'}")
            return 0 if report.passed else 1
        if args.judge_arg and not args.judge_command:
            raise ValueError("--judge-arg requires --judge-command")
        judge = None
        if args.judge_command:
            judge = CommandImageVisualJudge(
                (args.judge_command, *args.judge_arg),
                timeout_seconds=args.judge_timeout,
                provider_name=args.judge_provider,
            )
        report = run_visual_evidence(
            Path(args.manifest),
            Path(args.output),
            authorization_reference=args.authorization_reference,
            judge=judge,
        )
        print(f"Visual decision: {report.decision.value}")
        print(f"Report: {Path(args.output).expanduser().absolute()}")
        if report.decision.value == "pass":
            return 0
        if report.decision.value == "blocked":
            return 1
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _task_progress_text(status) -> str:
    progress = status.progress
    if progress is None:
        return "-"
    total = "?" if progress.total is None else str(progress.total)
    return f"{progress.completed}/{total}"


def _task_state_root(value: str | None) -> Path:
    return (
        default_workflow_state_root()
        if value is None
        else Path(value).expanduser().resolve(strict=False)
    )


def cancel_persisted_task(state_root: Path, task_id: str) -> str:
    with HanStore(state_root) as store:
        status = store.find_task_status(task_id)
        if status is None:
            raise ValueError(f"task not found: {task_id}")
        with store.open_project(status.project.project_id) as project:
            return project.request_task_cancel(task_id)


def retry_engine_task(
    state_root: Path,
    task_id: str,
    *,
    event_listener=None,
) -> int:
    with HanStore(state_root) as store:
        status = store.find_task_status(task_id)
        if status is None:
            raise ValueError(f"task not found: {task_id}")
        spec = status.retry_spec
        if spec is None or spec.command != "engine":
            raise ValueError("task does not have a resumable engine workflow")
        with store.open_project(status.project.project_id) as project:
            active_lock = project.active_project_lock("structured-workflow")
            if active_lock is not None:
                raise ProjectBusyError("project workflow is still running")
            if status.task.state is TaskState.COMPLETED:
                raise ValueError("completed tasks cannot be retried")
            if status.task.state in {
                TaskState.QUEUED,
                TaskState.RUNNING,
                TaskState.PAUSED,
                TaskState.RETRYING,
            }:
                project.mark_task_abandoned(task_id)
        arguments = list(spec.arguments)
    return run_engine(
        arguments,
        retry_of=task_id,
        event_listener_override=event_listener,
    )


def run_tasks(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect and control persisted HanTask workflows."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    list_command = commands.add_parser("list", help="list persisted tasks")
    list_command.add_argument("--state-root")
    list_command.add_argument("--project-id")
    list_command.add_argument("--limit", type=int, default=100)
    list_command.add_argument("--json", action="store_true")
    show = commands.add_parser("show", help="show one persisted task")
    show.add_argument("task_id")
    show.add_argument("--state-root")
    show.add_argument("--json", action="store_true")
    retry = commands.add_parser("retry", help="continue a resumable task")
    retry.add_argument("task_id")
    retry.add_argument("--state-root")
    cancel = commands.add_parser("cancel", help="request cooperative cancellation")
    cancel.add_argument("task_id")
    cancel.add_argument("--state-root")
    args = _parse_args(parser, argv)
    if isinstance(args, int):
        return args
    try:
        state_root = _task_state_root(args.state_root)
        if args.command == "retry":
            code = retry_engine_task(state_root, args.task_id)
            if code == 0:
                print(f"Retried task: {args.task_id}")
            return code
        if args.command == "cancel":
            requested_at = cancel_persisted_task(state_root, args.task_id)
            print(f"Cancellation requested: {args.task_id} at {requested_at}")
            return 0

        with HanStore(state_root) as store:
            if args.command == "list":
                statuses = store.list_task_statuses(
                    project_id=args.project_id,
                    limit=args.limit,
                )
                if args.json:
                    print(
                        json.dumps(
                            [item.to_dict() for item in statuses],
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                        )
                    )
                    return 0
                print("TASK\tSTATE\tENGINE\tSTAGE\tPROGRESS\tPROJECT\tRETRY")
                for status in statuses:
                    print(
                        "\t".join(
                            (
                                status.task.task_id,
                                status.task.state.value,
                                status.engine_id or "-",
                                status.stage,
                                _task_progress_text(status),
                                status.project.name,
                                "yes" if status.retry_spec is not None else "no",
                            )
                        )
                    )
                return 0

            status = store.find_task_status(args.task_id)
            if status is None:
                raise ValueError(f"task not found: {args.task_id}")
            payload = status.to_dict()
            if args.json:
                print(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    )
                )
                return 0
            print(f"Task: {status.task.task_id}")
            print(f"Project: {status.project.name} ({status.project.project_id})")
            print(f"State: {status.task.state.value}")
            print(f"Engine: {status.engine_id or '-'}")
            print(f"Stage: {status.stage}")
            print(f"Progress: {_task_progress_text(status)}")
            print(f"Failure: {status.failure_reason or '-'}")
            checkpoint = status.latest_checkpoint
            print(
                "Checkpoint: "
                + (
                    "-"
                    if checkpoint is None
                    else f"{checkpoint.step_id}#{checkpoint.sequence} ({checkpoint.checkpoint_id})"
                )
            )
            print(f"Cancel requested: {status.cancel_requested_at or '-'}")
            print(f"Artifacts: {len(status.artifacts)}")
            for artifact in status.artifacts:
                print(f"  {artifact.kind.value}: {artifact.relative_path}")
            print(f"Retryable: {'yes' if status.retry_spec is not None else 'no'}")
            if status.final_route is not None:
                print(format_guard_decision(status.final_route))
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _load_package_patch(path: Path) -> dict[Path, bytes]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("补丁 JSON 必须是对象")
    replacements: dict[Path, bytes] = {}
    for name, value in payload.items():
        if isinstance(value, str):
            replacements[Path(name)] = value.encode("utf-8")
        elif isinstance(value, dict) and set(value) == {"base64"} and isinstance(value["base64"], str):
            replacements[Path(name)] = base64.b64decode(value["base64"], validate=True)
        else:
            raise ValueError("补丁值必须是 UTF-8 文本或 base64 对象")
    return replacements


def run_package(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=f"修改未加密 ZIP；默认生成独立副本。\n{ETHICS}")
    parser.add_argument("archive")
    parser.add_argument("patch", help="路径到文本/base64 的 JSON 对象")
    parser.add_argument("--output")
    parser.add_argument("--apply", action="store_true", help="备份后覆盖原 ZIP")
    parser.add_argument("--backup-root")
    parser.add_argument("--authorized", action="store_true", help="确认拥有或获授权修改该资源")
    args = _parse_args(parser, argv)
    if isinstance(args, int):
        return args
    try:
        source = Path(args.archive)
        replacements = _load_package_patch(Path(args.patch))
        modifier = ZipPackageModifier()
        if args.apply:
            if not args.authorized or not args.backup_root:
                raise ValueError("应用到原包需要 --authorized 和 --backup-root")
            allowed = frozenset({RouteOperation.INSTALL_PATCH})
            route = RoutePlan(
                project_id="cli-authorized-package",
                phase=RoutePhase.FINAL,
                risk_before=RiskLevel.H0_PROJECT,
                risk_after=RiskLevel.H0_PROJECT,
                allowed_operations=allowed,
                blocked_operations=frozenset(RouteOperation) - allowed,
                matches=(),
                evaluation_status=EvaluationStatus.COMPLETE,
                unknown_evidence=False,
                decision_reasons=("explicit_authorization",),
            )
            result = modifier.apply_to_project(source, replacements, route=route, backup_root=Path(args.backup_root))
            print(f"已应用 ZIP 补丁并保留备份: {result.backup.backup_root}")
            return 0
        if not args.output:
            raise ValueError("独立输出模式需要 --output")
        result = modifier.build(source, replacements, Path(args.output))
        print(f"已生成 ZIP 副本: {result.output_path}")
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


def run_cloud_translate(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="调用兼容 HanEngine JSON 契约的云翻译服务")
    parser.add_argument("text")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--source", default="auto")
    parser.add_argument("--target", default="zh-CN")
    parser.add_argument("--token-env", default="HANENGINE_TRANSLATION_TOKEN")
    args = _parse_args(parser, argv)
    if isinstance(args, int):
        return args
    try:
        provider = CloudTranslationProvider(args.endpoint, token_provider=lambda: os.environ.get(args.token_env))
        result = provider.translate(TranslationRequest("cli", args.text, args.source, args.target))
        print(result.text)
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


def run_tts(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="使用 Windows SAPI 生成本地 WAV")
    parser.add_argument("text")
    parser.add_argument("--output", required=True)
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--voice")
    parser.add_argument("--rate", type=float, default=1.0)
    args = _parse_args(parser, argv)
    if isinstance(args, int):
        return args
    try:
        result = WindowsSapiTts().synthesize(TtsRequest(args.text, args.language, args.voice, args.rate), Path(args.output))
        print(f"已生成语音: {result.path}")
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


def run_auth(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="HanEngine local account database and session operations")
    parser.add_argument("command", choices=("status", "register", "login", "current", "logout"))
    parser.add_argument("--db", required=True, help="local authentication SQLite database")
    args = _parse_args(parser, argv)
    if isinstance(args, int):
        return args
    try:
        store = UserStore(Path(args.db))
        if args.command == "status":
            print(json.dumps(store.status(), ensure_ascii=False, sort_keys=True))
            return 0
        payload = auth_payload(json.loads(sys.stdin.read() or "{}"))
        if args.command == "register":
            session = store.create_user(
                payload.get("username", ""),
                payload.get("password", ""),
                payload.get("display_name", ""),
            )
            print(json.dumps(session.to_dict(), ensure_ascii=False, sort_keys=True))
            return 0
        token = payload.get("token", "")
        if args.command == "login":
            session = store.authenticate(
                payload.get("username", ""),
                payload.get("password", ""),
            )
            print(json.dumps(session.to_dict(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "current":
            user = store.current_user(token)
            print(
                json.dumps(
                    {"user": None if user is None else user.to_dict()},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        store.logout(token)
        print(json.dumps({"ok": True}, ensure_ascii=False, sort_keys=True))
        return 0
    except (AuthError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def run_legacy(argv: list[str]) -> int:
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


def _configure_utf8(stream: object) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _configure_utf8(sys.stdout)
    _configure_utf8(sys.stderr)
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "detect":
        return run_detect(arguments[1:])
    if arguments and arguments[0] == "engines":
        return run_engines(arguments[1:])
    if arguments and arguments[0] == "renpy":
        return run_renpy(arguments[1:])
    if arguments and arguments[0] == "engine":
        return run_engine(arguments[1:])
    if arguments and arguments[0] == "project":
        return run_project(arguments[1:])
    if arguments and arguments[0] == "visual":
        return run_visual(arguments[1:])
    if arguments and arguments[0] == "tasks":
        return run_tasks(arguments[1:])
    if arguments and arguments[0] == "package":
        return run_package(arguments[1:])
    if arguments and arguments[0] == "cloud-translate":
        return run_cloud_translate(arguments[1:])
    if arguments and arguments[0] == "tts":
        return run_tts(arguments[1:])
    if arguments and arguments[0] == "auth":
        return run_auth(arguments[1:])
    return run_legacy(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
