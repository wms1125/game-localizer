from __future__ import annotations

import argparse
import json
from pathlib import Path


CONTRACT = "hanengine.benchmark/v1"
RENPY_PROJECTS = (
    ("rp_core_dialogue", 160),
    ("rp_screen_language", 120),
    ("rp_branching_context", 120),
    ("rp_packaged_smoke", 100),
)
RESOLUTIONS = ("1280x720", "1920x1080", "2560x1440", "3840x2160")
BACKGROUNDS = ("solid", "translucent", "textured", "static_scene", "low_contrast")
LAYOUTS = ("single_line", "multi_line", "menu")
FONT_ROTATIONS = ("sans_serif", "serif_sans")
DYNAMIC_KINDS = ("typewriter", "fade_slide", "animated_background", "camera_motion")
ROUTE_OPERATIONS = (
    "detect",
    "extract",
    "validate",
    "build",
    "verify",
    "rollback",
    "install_patch",
    "capture",
    "ocr",
    "visual_replace",
)
EVALUATION_STATUSES = (
    "complete",
    "missing_evidence",
    "unknown_rule",
    "evaluation_failed",
)

_EXTERNAL_OPERATIONS = ("detect", "capture", "ocr", "visual_replace")


def _source_language(index: int) -> str:
    return "ja" if index % 5 == 0 else "en"


def _static_cases() -> list[dict[str, object]]:
    cases = []
    index = 0
    for resolution in RESOLUTIONS:
        for background in BACKGROUNDS:
            for layout in LAYOUTS:
                for font_rotation in FONT_ROTATIONS:
                    index += 1
                    cases.append(
                        {
                            "case_id": f"static-{index:03d}",
                            "resolution": resolution,
                            "background": background,
                            "layout": layout,
                            "font_rotation": font_rotation,
                            "source_language": _source_language(index),
                        }
                    )
    return cases


def _dynamic_cases() -> list[dict[str, object]]:
    cases = []
    index = 0
    for kind in DYNAMIC_KINDS:
        for _ in range(15):
            index += 1
            cases.append(
                {
                    "case_id": f"dynamic-{index:03d}",
                    "kind": kind,
                    "frame_count": 30,
                    "source_language": _source_language(index),
                }
            )
    return cases


def _translation_slots() -> list[dict[str, str]]:
    slots = []
    for index in range(1, 301):
        if index <= 180:
            category = "dialogue"
        elif index <= 240:
            category = "menu_ui"
        else:
            category = "system"
        slots.append(
            {
                "slot_id": f"gold-{index:03d}",
                "category": category,
                "source_language": _source_language(index),
            }
        )
    return slots


def _signal(value: str) -> dict[str, str]:
    return {
        "signal_type": "capture_result",
        "value": value,
        "source": "synthetic_benchmark",
        "evidence": f"synthetic signal: {value}",
    }


def _rule(
    rule_id: str,
    match_value: str,
    minimum_risk: str,
    blocked_operations: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "rule_version": "1.0.0",
        "signal_type": "capture_result",
        "match_value": match_value,
        "minimum_risk": minimum_risk,
        "blocked_operations": sorted(blocked_operations),
        "reason": f"synthetic {rule_id} benchmark rule",
        "evidence_source": "repository-owned synthetic benchmark",
        "last_verified_date": "2026-08-05",
    }


def _allowed_for(risk: str, blocked_operations: tuple[str, ...] = ()) -> list[str]:
    base = ROUTE_OPERATIONS if risk in ("H0_PROJECT", "H1_OFFLINE") else _EXTERNAL_OPERATIONS
    blocked = frozenset(blocked_operations)
    return [operation for operation in base if operation not in blocked]


def _guard_case(
    *,
    case_id: str,
    stratum: str,
    user_baseline: str | None,
    adapter_baseline: str | None,
    expected_risk: str,
    rules: list[dict[str, object]] | None = None,
    signals: list[dict[str, str]] | None = None,
    final_status: str = "complete",
    blocked_operations: tuple[str, ...] = (),
) -> dict[str, object]:
    allowed = _allowed_for(expected_risk, blocked_operations)
    return {
        "case_id": case_id,
        "stratum": stratum,
        "project_id": f"benchmark-{case_id}",
        "user_baseline": user_baseline,
        "adapter_baseline": adapter_baseline,
        "available_operations": list(ROUTE_OPERATIONS),
        "rules": rules or [],
        "signals": signals or [],
        "provisional_evaluation_status": "complete",
        "final_evaluation_status": final_status,
        "expected_risk": expected_risk,
        "expected_allowed_operations": allowed,
        "expected_blocked_operations": [
            operation for operation in ROUTE_OPERATIONS if operation not in allowed
        ],
    }


def _fixed_guard_cases() -> list[dict[str, object]]:
    cases = []
    fixed = (
        ("h0", "H0", "H0_PROJECT"),
        ("h1", "H1", "H1_OFFLINE"),
        ("h2", "H2", "H2_RESTRICTED"),
    )
    for prefix, stratum, risk in fixed:
        for index in range(1, 17):
            cases.append(
                _guard_case(
                    case_id=f"guard-{prefix}-{index:02d}",
                    stratum=stratum,
                    user_baseline=risk,
                    adapter_baseline=risk,
                    expected_risk=risk,
                )
            )

    for index in range(1, 17):
        rules = []
        signals = []
        blocked_operations: tuple[str, ...] = ()
        if index > 8:
            value = "overlay_forbidden" if index <= 12 else "capture_black_frame"
            blocked_operations = ("capture", "ocr", "visual_replace")
            rules = [
                _rule(
                    f"synthetic-{value}",
                    value,
                    "H3_PROTECTED",
                    blocked_operations,
                )
            ]
            signals = [_signal(value)]
        cases.append(
            _guard_case(
                case_id=f"guard-h3-{index:02d}",
                stratum="H3",
                user_baseline="H3_PROTECTED",
                adapter_baseline="H3_PROTECTED",
                expected_risk="H3_PROTECTED",
                rules=rules,
                signals=signals,
                blocked_operations=blocked_operations,
            )
        )
    return cases


def _edge_guard_cases() -> list[dict[str, object]]:
    conflict_specs = (
        ("H0_PROJECT", "H1_OFFLINE", "H2_RESTRICTED"),
        ("H1_OFFLINE", "H0_PROJECT", "H3_PROTECTED"),
        ("H3_PROTECTED", "H0_PROJECT", "H1_OFFLINE"),
        ("H2_RESTRICTED", "H1_OFFLINE", "H0_PROJECT"),
    )
    cases = []
    for index, (user_risk, adapter_risk, rule_risk) in enumerate(conflict_specs, 1):
        value = f"risk_conflict_{index}"
        expected_risk = max(
            (user_risk, adapter_risk, rule_risk),
            key=("H0_PROJECT", "H1_OFFLINE", "H2_RESTRICTED", "H3_PROTECTED").index,
        )
        cases.append(
            _guard_case(
                case_id=f"guard-edge-{index:02d}",
                stratum="edge",
                user_baseline=user_risk,
                adapter_baseline=adapter_risk,
                expected_risk=expected_risk,
                rules=[_rule(f"synthetic-conflict-{index}", value, rule_risk)],
                signals=[_signal(value)],
            )
        )

    for index, status in enumerate(EVALUATION_STATUSES[1:], 1):
        for offset in range(4):
            case_number = 5 + (index - 1) * 4 + offset
            cases.append(
                _guard_case(
                    case_id=f"guard-edge-{case_number:02d}",
                    stratum="edge",
                    user_baseline="H0_PROJECT",
                    adapter_baseline="H0_PROJECT",
                    expected_risk="H2_RESTRICTED",
                    final_status=status,
                )
            )
    return cases


def build_payloads() -> dict[str, object]:
    guard_cases = _fixed_guard_cases() + _edge_guard_cases()
    return {
        "manifest.json": {
            "contract": CONTRACT,
            "counts": {
                "renpy_projects": 4,
                "renpy_segments": 500,
                "player_static_cases": 120,
                "player_dynamic_cases": 60,
                "translation_gold_slots": 300,
                "guard_risk_cases": 80,
            },
        },
        "guard_risk_cases.json": {
            "contract": CONTRACT,
            "cases": guard_cases,
        },
        "renpy_projects.json": {
            "contract": CONTRACT,
            "renpy_versions": ["8.5.3", "8.4.1"],
            "projects": [
                {"project_id": project_id, "expected_segments": count}
                for project_id, count in RENPY_PROJECTS
            ],
        },
        "player_cases.json": {
            "contract": CONTRACT,
            "static_cases": _static_cases(),
            "dynamic_cases": _dynamic_cases(),
        },
        "translation_gold_manifest.json": {
            "contract": CONTRACT,
            "slots": _translation_slots(),
        },
    }


def _render(payload: object) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    return text.encode("utf-8")


def write_payloads(root: Path) -> tuple[Path, ...]:
    benchmark_root = root / "benchmarks"
    benchmark_root.mkdir(parents=True, exist_ok=True)
    written = []
    for name, payload in build_payloads().items():
        path = benchmark_root / name
        path.write_text(
            _render(payload).decode("utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        written.append(path)
    return tuple(written)


def check_payloads(root: Path) -> int:
    benchmark_root = root / "benchmarks"
    mismatches = []
    for name, payload in build_payloads().items():
        path = benchmark_root / name
        if not path.is_file() or path.read_bytes() != _render(payload):
            mismatches.append(name)
    if mismatches:
        print("Benchmark manifests differ: " + ", ".join(mismatches))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if args.check:
        return check_payloads(root)
    write_payloads(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
