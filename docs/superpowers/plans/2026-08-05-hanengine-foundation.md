# HanEngine Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 HanEngine 首个实施周期：先锁定基准资产清单、HanGuard 风险样本与适配器契约测试骨架，再建立无 GUI 的 `HanCore`、`Segment`、`RoutePlan`、`HanTask` 和 `HanStore`，同时保证 Phase 0 后冻结的 146 项基线测试（含原有 99 项应用测试）不退化。

**Architecture:** 在现有 `game_localizer` 包旁新增独立的 `game_localizer.hanengine` 基础层。适配器契约继续位于 `game_localizer.adapters`，但不改动当前只读检测适配器；`HanGuard` 先以纯函数式规则评估生成路线，`HanTask` 以同步可协作取消的运行器产生结构化事件，`HanStore` 以全局索引数据库加每项目独立 SQLite 数据库持久化，`HanCore` 只负责校验项目边界、规范化文本段、执行路线授权和编排任务。

**Tech Stack:** Python 3.11 标准库，`dataclasses`、`enum`、`hashlib`、`json`、`pathlib`、`sqlite3`、`threading`、`uuid`、`unittest`；不增加第三方依赖。

## Global Constraints

- 首个实施周期只覆盖主规格第 12 节的第 1、2 步。
- 不实现 OCR、屏幕捕获、覆盖层、窗口跟踪或动态场景替换。
- 不实现 Ren'Py 文本提取、资源写回、补丁安装、备份或回滚。
- 不接入在线机器翻译、LLM、TTS、HanCloud 或任何网络请求。
- 不修改当前 `translator.py`、`cli.py`、`gui.py`、现有检测器和现有引擎适配器的行为。
- 新基础层只使用 Python 标准库；不得在运行时安装依赖。
- HanGuard 只收集调用者传入的非侵入式信号；本周期不枚举系统进程、服务或模块。
- `H3_PROTECTED` 不得被配置或调用者降级；证据缺失、规则未知或评估失败一律回退到 `H2_RESTRICTED`。
- 适配器的 `detect`、`extract`、`validate`、`verify` 保持只读；`build` 的写入边界仍是独立暂存目录。本周期仅定义和测试契约，不实现具体写入适配器。
- 所有数据库测试必须使用临时目录，不得写入真实 `%LOCALAPPDATA%`。
- 用户可见路径只保存相对路径；绝对源路径只允许存在于本地项目记录中。
- API 密钥、完整在线请求、完整截图和模型内部推理不得进入事件、SQLite、JSON 基准资产或日志。
- 继续使用 `unittest`；不引入 pytest。
- 每个任务严格执行红灯测试、最小实现、绿灯验证和独立提交。
- 所有操作仅面向用户合法拥有或明确获授权的项目和仓库自有合成测试资产。
- 仓库根许可证在本周期仍未决；`benchmarks/LICENSE` 的 CC0-1.0 放弃声明只覆盖 `benchmarks/` 下仓库自有的合成资产与元数据，不覆盖生产代码、测试代码、文档或仓库其他内容。
- 不复制、改编、生成或提交任何第三方代码、商业游戏内容、截图、译文或其他第三方资产；Task 1 只提交仓库自有合成元数据和对应许可载体。

## Scope Boundary

本计划交付“可测试、可持久化、可编排但还不能真正修改游戏”的 HanEngine 基础层。完成后能够：验证固定基准清单；根据合成信号生成两阶段风险路线；表达并运行可取消、可重试的后台任务；按项目隔离保存文本段、路线、任务、事件和产物；由 `HanCore` 拒绝未经路线授权的步骤。真正的明文能力迁移、Ren'Py 适配、视觉替换、翻译路由和 GUI 分别由后续计划实现。

## File Map

- Create `.gitattributes`: 固定根目录下 `benchmarks/*.json` 的 Git checkout 行尾为 LF，避免 Windows `core.autocrlf` 改写已提交基准字节。
- Create `benchmarks/README.md`: 基准资产来源、生成方式、许可边界和本周期仅提交清单的说明。
- Create `benchmarks/LICENSE`: 仅适用于 `benchmarks/` 仓库自有合成资产与元数据的 CC0-1.0 法律文本；仓库根许可证仍未决。
- Create `benchmarks/manifest.json`: 全部固定基准集的版本和数量总清单。
- Create `benchmarks/guard_risk_cases.json`: 80 个合成 HanGuard 风险快照。
- Create `benchmarks/renpy_projects.json`: 4 个 Ren'Py 基准项目、500 个预期文本段和固定 SDK 版本清单。
- Create `benchmarks/player_cases.json`: 120 个静态截图案例和 60 个动态序列的生成清单。
- Create `benchmarks/translation_gold_manifest.json`: 300 条翻译黄金集的分层槽位清单；本周期不填入人工参考译文。
- Create `tools/generate_benchmark_manifests.py`: 确定性生成上述 JSON 清单和风险样本。
- Create `tests/test_benchmark_manifests.py`: 校验版本、数量、ID 唯一性、风险分层和生成确定性。
- Create `tests/adapter_contract_v1.py`: 可被每个未来适配器继承的 v1 契约测试混入类；文件名不以 `test_` 开头，避免在没有具体适配器时被单独发现。
- Create `game_localizer/hanengine/__init__.py`: HanEngine 基础层的稳定公开导出。
- Create `game_localizer/hanengine/segments.py`: `SourceLocation`、`ScreenRegion`、`SegmentDraft` 和 `Segment`。
- Create `game_localizer/hanengine/routing.py`: HanGuard 风险枚举、规则、证据、两阶段 `RoutePlan` 和评估器。
- Create `game_localizer/hanengine/tasks.py`: 任务、步骤、事件、产物、协作控制和同步运行器。
- Create `game_localizer/hanengine/store.py`: 数据根路径、全局项目索引、每项目 SQLite 存储和 schema v1。
- Create `game_localizer/hanengine/core.py`: `HanCore` 无 GUI 编排门面。
- Create `game_localizer/adapters/contract.py`: `hanengine.adapter/v1` 完整类型、错误模型和 `Protocol`。
- Modify `docs/superpowers/specs/2026-08-05-hanengine-adapter-contract.md`: 同步 v1 书面契约，使每个操作请求只携带 runner 创建的 `TaskContext`，并禁止适配器直接使用事件接收器或自行构造任务事件。
- Create `tests/test_hanengine_segments.py`: 文本段、来源位置、JSON 元数据和稳定指纹测试。
- Create `tests/test_hanguard_routing.py`: 两阶段风险、从严合并、权限交集和 80 个风险样本测试。
- Create `tests/test_hantask_models.py`: 状态、事件序列、进度和序列化测试。
- Create `tests/test_hantask_runner.py`: 实时事件、重试、暂停检查点和取消测试。
- Create `tests/test_adapter_contract.py`: 用内存假适配器实际运行 v1 契约测试骨架。
- Create `tests/test_hanstore.py`: 数据路径、schema、事务和多项目隔离测试。
- Create `tests/test_hancore.py`: 文本段接收、路线拦截、任务执行和持久化端到端测试。
- Modify `README.md`: 增加 HanEngine 基础层状态、测试命令和明确的未支持能力。

---

### Task 1: Freeze Benchmark Manifests and the Adapter Contract Harness

**Files:**
- Create: `.gitattributes`
- Create: `benchmarks/README.md`
- Create: `benchmarks/LICENSE`
- Create: `benchmarks/manifest.json`
- Create: `benchmarks/guard_risk_cases.json`
- Create: `benchmarks/renpy_projects.json`
- Create: `benchmarks/player_cases.json`
- Create: `benchmarks/translation_gold_manifest.json`
- Create: `tools/generate_benchmark_manifests.py`
- Create: `tests/test_benchmark_manifests.py`
- Create: `tests/adapter_contract_v1.py`

**Interfaces:**
- `tools.generate_benchmark_manifests.build_payloads() -> dict[str, object]` 返回以目标文件名为键的确定性对象。
- `tools.generate_benchmark_manifests.write_payloads(root: Path) -> tuple[Path, ...]` 使用 UTF-8、`ensure_ascii=False`、`indent=2` 和末尾换行写入清单。
- 所有清单的 `contract` 固定为 `hanengine.benchmark/v1`。
- `tests.adapter_contract_v1.AdapterV1ContractMixin` 要求子类实现 `make_adapter()` 和 `make_detection_request()`；本任务只建立可复用测试骨架，不实现具体适配器。
- `tests.adapter_contract_v1.AdapterV1ContractMixin` 还要求 `make_unmatched_detection_request()`；匹配与未匹配请求必须走无条件、互不替代的断言路径。

- [ ] **Step 0: Freeze the post-Phase 0 regression baseline**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: exactly 146 tests run and pass with no skipped tests: the original 99 application tests, 37 compliance tests, and 10 SBOM tests. Record this post-Phase 0 count as the immutable regression baseline for every later task; the original 99 application tests remain individually protected from regression.

- [ ] **Step 1: Write failing benchmark manifest tests**

Create `tests/test_benchmark_manifests.py` with these assertions:

```python
import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"


def load(name: str) -> dict[str, object]:
    return json.loads((BENCHMARKS / name).read_text(encoding="utf-8"))


class BenchmarkManifestTests(unittest.TestCase):
    def test_master_manifest_locks_every_dataset(self):
        payload = load("manifest.json")
        self.assertEqual(payload["contract"], "hanengine.benchmark/v1")
        self.assertEqual(
            payload["counts"],
            {
                "renpy_projects": 4,
                "renpy_segments": 500,
                "player_static_cases": 120,
                "player_dynamic_cases": 60,
                "translation_gold_slots": 300,
                "guard_risk_cases": 80,
            },
        )

    def test_benchmark_license_carrier_and_scope_are_separate(self):
        license_text = (BENCHMARKS / "LICENSE").read_text(encoding="utf-8")
        readme_text = (BENCHMARKS / "README.md").read_text(encoding="utf-8")
        self.assertIn("CC0 1.0", license_text)
        self.assertNotIn("root license remains undecided", license_text)
        self.assertIn("benchmarks/", readme_text)
        self.assertIn("root license remains undecided", readme_text)
        self.assertIn("no third-party code or assets", readme_text.lower())

    def test_git_attributes_pin_benchmark_json_to_lf(self):
        completed = subprocess.run(
            ["git", "check-attr", "text", "eol", "--", "benchmarks/manifest.json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("benchmarks/manifest.json: text: set", completed.stdout)
        self.assertIn("benchmarks/manifest.json: eol: lf", completed.stdout)

    def test_renpy_manifest_locks_versions_and_segment_counts(self):
        payload = load("renpy_projects.json")
        projects = payload["projects"]
        self.assertEqual(payload["renpy_versions"], ["8.5.3", "8.4.1"])
        self.assertEqual(
            {item["project_id"]: item["expected_segments"] for item in projects},
            {
                "rp_core_dialogue": 160,
                "rp_screen_language": 120,
                "rp_branching_context": 120,
                "rp_packaged_smoke": 100,
            },
        )
        self.assertEqual(sum(item["expected_segments"] for item in projects), 500)

    def test_player_and_translation_case_ids_are_unique(self):
        player = load("player_cases.json")
        translation = load("translation_gold_manifest.json")
        static_ids = [item["case_id"] for item in player["static_cases"]]
        dynamic_ids = [item["case_id"] for item in player["dynamic_cases"]]
        slot_ids = [item["slot_id"] for item in translation["slots"]]
        self.assertEqual((len(static_ids), len(dynamic_ids), len(slot_ids)), (120, 60, 300))
        self.assertEqual(len(set(static_ids + dynamic_ids)), 180)
        self.assertEqual(len(set(slot_ids)), 300)
        self.assertEqual(
            Counter(item["category"] for item in translation["slots"]),
            Counter({"dialogue": 180, "menu_ui": 60, "system": 60}),
        )
        self.assertEqual(
            Counter(item["source_language"] for item in translation["slots"]),
            Counter({"en": 240, "ja": 60}),
        )

    def test_guard_cases_have_required_strata_and_expected_routes(self):
        payload = load("guard_risk_cases.json")
        cases = payload["cases"]
        self.assertEqual(len(cases), 80)
        self.assertEqual(len({item["case_id"] for item in cases}), 80)
        self.assertEqual(
            Counter(item["stratum"] for item in cases),
            Counter({"H0": 16, "H1": 16, "H2": 16, "H3": 16, "edge": 16}),
        )
        for case in cases:
            self.assertIn("signals", case)
            self.assertIn("expected_risk", case)
            self.assertIn("expected_allowed_operations", case)
            self.assertIn("expected_blocked_operations", case)
        edge_cases = [item for item in cases if item["stratum"] == "edge"]
        self.assertEqual(
            Counter(item["final_evaluation_status"] for item in edge_cases),
            Counter(
                {
                    "complete": 4,
                    "missing_evidence": 4,
                    "unknown_rule": 4,
                    "evaluation_failed": 4,
                }
            ),
        )

    def test_generator_is_deterministic_and_check_mode_is_clean(self):
        completed = subprocess.run(
            [sys.executable, "tools/generate_benchmark_manifests.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_committed_json_is_canonical_utf8_lf_without_bom(self):
        for name in (
            "manifest.json",
            "guard_risk_cases.json",
            "renpy_projects.json",
            "player_cases.json",
            "translation_gold_manifest.json",
        ):
            raw = (BENCHMARKS / name).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), name)
            self.assertTrue(raw.endswith(b"\n"), name)
            self.assertFalse(raw.endswith(b"\n\n"), name)
            self.assertNotIn(b"\r\n", raw, name)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the benchmark tests and verify missing-file failures**

Run:

```powershell
python -m unittest tests.test_benchmark_manifests -v
```

Expected: FAIL with `FileNotFoundError` for one or more files under `benchmarks/`.

- [ ] **Step 3: Implement the deterministic manifest generator**

Create `tools/generate_benchmark_manifests.py`. Use fixed tuples for every axis and stable nested-loop order. The generated data must obey this exact matrix:

```python
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
    "detect", "extract", "validate", "build", "verify", "rollback",
    "install_patch", "capture", "ocr", "visual_replace",
)
EVALUATION_STATUSES = (
    "complete",
    "missing_evidence",
    "unknown_rule",
    "evaluation_failed",
)
```

Generation rules:

- Static cases are the full `4 × 5 × 3 × 2 = 120` Cartesian product. IDs are `static-001` through `static-120`.
- Dynamic cases are 15 cases for each `DYNAMIC_KINDS` value, each with `frame_count: 30`. IDs are `dynamic-001` through `dynamic-060`.
- Player source language uses a deterministic 80/20 split: the first four cases in each block of five are `en`, the fifth is `ja`.
- Translation slots are `gold-001` through `gold-300`: first 180 `dialogue`, next 60 `menu_ui`, last 60 `system`; within each block, four of every five are `en` and the fifth is `ja`.
- Guard cases are `guard-h0-01..16`, `guard-h1-01..16`, `guard-h2-01..16`, `guard-h3-01..16`, and `guard-edge-01..16`.
- Every guard case contains `project_id`, `user_baseline`, `adapter_baseline`, `available_operations`, `rules`, `signals`, `provisional_evaluation_status`, and `final_evaluation_status`. Status values are from `EVALUATION_STATUSES`; every rule uses the exact `HanGuardRule.to_dict()` shape and every signal contains `signal_type`, `value`, `source`, and `evidence`.
- H0 expected operations are all `ROUTE_OPERATIONS`; H1 excludes no read/build/install/visual operation in this foundation; H2 allows only `detect`, `capture`, `ocr`, and `visual_replace`; H3 allows those four unless a case contains `overlay_forbidden` or `capture_black_frame`, in which case only `detect` is allowed.
- Every fixed case uses `provisional_evaluation_status: "complete"`; the 16 edge cases use final statuses of four `complete` conflicts, four `missing_evidence`, four `unknown_rule`, and four `evaluation_failed` cases. The latter three statuses expect `H2_RESTRICTED`; complete conflicts expect the highest matched level. These are distinct serialized inputs and must exercise distinct `decision_reasons` in Task 3.
- Render canonical JSON as `json.dumps(..., ensure_ascii=False, indent=2, allow_nan=False) + "\n"`. Write with UTF-8, no BOM, and `newline="\n"`; `--check` compares `Path.read_bytes()` with `rendered.encode("utf-8")` without writing, so `core.autocrlf` or universal-newline reads cannot hide byte differences.

The command-line entry point must be:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if args.check:
        return check_payloads(root)
    write_payloads(root)
    return 0
```

- [ ] **Step 4: Generate and document the benchmark manifests**

Run:

```powershell
python tools/generate_benchmark_manifests.py
```

Create `benchmarks/README.md` stating:

- `benchmarks/LICENSE` contains the CC0-1.0 legal text and applies only to repository-owned synthetic assets and metadata under `benchmarks/`;
- the repository root license remains undecided, so this benchmark-scoped CC0 declaration does not license production code, tests, documentation, or any other repository path;
- no commercial game files, screenshots or translated text are included;
- no third-party code or assets are copied, adapted, generated, or committed;
- this cycle commits only manifests and risk snapshots;
- future Ren'Py, screenshot, dynamic and human-reference assets must match the committed IDs;
- regeneration and verification commands are `python tools/generate_benchmark_manifests.py` and `python tools/generate_benchmark_manifests.py --check`.

Create `benchmarks/LICENSE` from the unmodified standard CC0-1.0 legal text. Do not prepend, append, or edit that legal text. Keep the benchmark-only scope notice exclusively in `benchmarks/README.md`; do not add or imply a root repository license.

Create root `.gitattributes` with this exact rule:

```gitattributes
/benchmarks/*.json text eol=lf
```

- [ ] **Step 5: Add the reusable adapter contract test harness**

Create `tests/adapter_contract_v1.py` with a non-discovered mixin exposing these exact hooks:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


def snapshot_tree(root: Path) -> tuple[tuple[str, str, bytes | None], ...]:
    items = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        items.append((relative, "dir" if path.is_dir() else "file", None if path.is_dir() else path.read_bytes()))
    return tuple(items)


class AdapterV1ContractMixin(ABC):
    @abstractmethod
    def make_adapter(self):
        raise NotImplementedError

    @abstractmethod
    def make_detection_request(self):
        raise NotImplementedError

    @abstractmethod
    def make_unmatched_detection_request(self):
        raise NotImplementedError

    def test_contract_metadata_is_valid(self):
        adapter = self.make_adapter()
        self.assertEqual(adapter.metadata.contract_version, "hanengine.adapter/v1")
        self.assertTrue(adapter.metadata.adapter_id)
        self.assertTrue(adapter.metadata.capabilities)

    def test_detect_is_deterministic(self):
        adapter = self.make_adapter()
        request = self.make_detection_request()
        first = adapter.detect(request)
        second = adapter.detect(request)
        self.assertTrue(first.matched)
        self.assertEqual(first, second)

    def test_unmatched_detection_has_no_evidence(self):
        result = self.make_adapter().detect(self.make_unmatched_detection_request())
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence, ())
        self.assertIsNone(result.engine_name)
        self.assertIsNone(result.engine_version)

    def test_detect_does_not_modify_input_root(self):
        adapter = self.make_adapter()
        request = self.make_detection_request()
        before = snapshot_tree(request.input_root)
        adapter.detect(request)
        self.assertEqual(snapshot_tree(request.input_root), before)

    def test_recommended_operation_is_allowed_by_request(self):
        request = self.make_detection_request()
        result = self.make_adapter().detect(request)
        self.assertIn(result.recommended_operation, request.allowed_operations)
```

The harness file name does not begin with `test_` and contains no `unittest.TestCase` subclass, so discovery cannot create an abstract or skipped test. The concrete Task 6 test subclasses the mixin and `unittest.TestCase` directly.

- [ ] **Step 6: Run the benchmark checks**

Run:

```powershell
python -m unittest tests.test_benchmark_manifests -v
python tools/generate_benchmark_manifests.py --check
git check-attr text eol -- benchmarks/manifest.json
```

Expected: all benchmark tests pass; `--check` exits 0 and writes nothing; `git check-attr` reports `text: set` and `eol: lf` for `benchmarks/manifest.json`.

- [ ] **Step 7: Commit Task 1**

Immediately before staging, run the complete regression gate:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus all Task 1 tests pass, and no existing or new test is skipped.

```powershell
git add .gitattributes benchmarks/README.md benchmarks/LICENSE benchmarks/*.json tools/generate_benchmark_manifests.py tests/test_benchmark_manifests.py tests/adapter_contract_v1.py
git commit -m "test: lock HanEngine benchmark manifests"
```

---

### Task 2: Add Stable Segment and Source Location Models

**Files:**
- Create: `game_localizer/hanengine/__init__.py`
- Create: `game_localizer/hanengine/segments.py`
- Create: `tests/test_hanengine_segments.py`

**Interfaces:**
- `normalize_relative_path(value: str) -> str` is the one shared, cross-platform validator used by source locations, artifacts, adapter path lists, and manifests.
- `ScreenRegion(x: int, y: int, width: int, height: int)` rejects negative coordinates and non-positive dimensions.
- `SourceLocation(relative_path, logical_path, line, column, byte_offset, screen_region)` requires at least one real locator; absent values are `None`, never fabricated zeroes.
- `SegmentDraft` mirrors adapter-contract fields and validates metadata as JSON serializable.
- `Segment.from_draft(project_id: str, target_language: str, draft: SegmentDraft) -> Segment` calculates a deterministic context fingerprint.

- [ ] **Step 1: Write failing segment model tests**

Create `tests/test_hanengine_segments.py` covering:

```python
import unittest

from game_localizer.hanengine.segments import (
    ScreenRegion,
    Segment,
    SegmentDraft,
    SourceLocation,
    normalize_relative_path,
)


class SegmentModelTests(unittest.TestCase):
    def make_draft(self) -> SegmentDraft:
        return SegmentDraft(
            segment_id="script.rpy:line:12",
            source_text="Start Game",
            source_language="en",
            speaker=None,
            context_before=("Main Menu",),
            context_after=("Load Game",),
            placeholders=(),
            tags=(),
            constraints=("menu",),
            source_location=SourceLocation(relative_path="game/script.rpy", line=12),
            source_fingerprint="sha256:source",
            ocr_confidence=None,
            region_confidence=None,
            metadata={"engine": "renpy"},
        )

    def test_file_location_uses_none_for_inapplicable_fields(self):
        location = self.make_draft().source_location
        self.assertEqual(location.relative_path, "game/script.rpy")
        self.assertIsNone(location.screen_region)
        self.assertIsNone(location.byte_offset)

    def test_screen_region_rejects_non_positive_dimensions(self):
        with self.assertRaisesRegex(ValueError, "width and height"):
            ScreenRegion(x=0, y=0, width=0, height=20)

    def test_location_rejects_absolute_or_parent_traversal_paths(self):
        for path in (
            "/game/script.rpy",
            "C:/game/script.rpy",
            "C:\\game\\script.rpy",
            "C:game\\script.rpy",
            "\\game\\script.rpy",
            "\\\\server\\share\\script.rpy",
            "\\\\?\\C:\\game\\script.rpy",
            "../script.rpy",
            "..\\script.rpy",
            "safe/..\\script.rpy",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                SourceLocation(relative_path=path)

    def test_relative_path_normalization_is_platform_independent(self):
        self.assertEqual(
            normalize_relative_path("game\\scripts\\script.rpy"),
            "game/scripts/script.rpy",
        )

    def test_relative_path_rejects_mixed_separators_without_traversal(self):
        with self.assertRaisesRegex(ValueError, "mixed path separators"):
            normalize_relative_path("game\\scripts/file.rpy")

    def test_segment_rejects_non_json_metadata(self):
        with self.assertRaisesRegex(ValueError, "JSON"):
            SegmentDraft(**{**self.make_draft().__dict__, "metadata": {"bad": object()}})

    def test_from_draft_is_deterministic_and_project_scoped(self):
        first = Segment.from_draft("project-a", "zh-Hans", self.make_draft())
        second = Segment.from_draft("project-a", "zh-Hans", self.make_draft())
        other = Segment.from_draft("project-b", "zh-Hans", self.make_draft())
        self.assertEqual(first, second)
        self.assertNotEqual(first.context_fingerprint, other.context_fingerprint)
        self.assertIsNone(first.target_text)
        self.assertIsNone(first.translation_source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the segment tests and verify the import failure**

Run:

```powershell
python -m unittest tests.test_hanengine_segments -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'game_localizer.hanengine'`.

- [ ] **Step 3: Implement `segments.py` with the exact public fields**

Use these signatures:

```python
def normalize_relative_path(value: str) -> str: ...


@dataclass(frozen=True)
class ScreenRegion:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class SourceLocation:
    relative_path: str | None = None
    logical_path: str | None = None
    line: int | None = None
    column: int | None = None
    byte_offset: int | None = None
    screen_region: ScreenRegion | None = None


@dataclass(frozen=True)
class SegmentDraft:
    segment_id: str
    source_text: str
    source_language: str
    speaker: str | None
    context_before: tuple[str, ...]
    context_after: tuple[str, ...]
    placeholders: tuple[str, ...]
    tags: tuple[str, ...]
    constraints: tuple[str, ...]
    source_location: SourceLocation
    source_fingerprint: str
    ocr_confidence: float | None
    region_confidence: float | None
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Segment:
    project_id: str
    target_language: str
    segment_id: str
    source_text: str
    source_language: str
    speaker: str | None
    context_before: tuple[str, ...]
    context_after: tuple[str, ...]
    placeholders: tuple[str, ...]
    tags: tuple[str, ...]
    constraints: tuple[str, ...]
    source_location: SourceLocation
    source_fingerprint: str
    context_fingerprint: str
    target_text: str | None
    translation_source: str | None
    ocr_confidence: float | None
    region_confidence: float | None
    metadata: dict[str, JsonValue]

    @classmethod
    def from_draft(
        cls,
        project_id: str,
        target_language: str,
        draft: SegmentDraft,
    ) -> "Segment": ...
```

Implementation requirements:

- Implement `normalize_relative_path()` with both `PurePosixPath` and `PureWindowsPath`, independent of the host OS. Before any normalization, reject every input that contains both `/` and `\`, even when it has no `..` component (for example `game\scripts/file.rpy`). Continue to accept a pure-backslash relative path such as `game\scripts\script.rpy` and normalize it to forward slashes. Also reject empty paths, POSIX absolute paths, Windows drives (including `C:relative`), rooted paths, UNC shares, device paths, and any `..` component before returning a forward-slash relative path.
- All later relative-path models import this function from `segments.py`; do not copy slightly different path checks into `tasks.py` or `adapters/contract.py`.
- `line` and `column` are `None` or at least 1; `byte_offset` is `None` or at least 0.
- Confidence values are `None` or within `[0.0, 1.0]`.
- Validate metadata with `json.dumps(metadata, allow_nan=False)` and copy the dictionary so caller mutation cannot change the instance immediately after construction.
- Calculate `context_fingerprint` as `sha256` over UTF-8 canonical JSON containing `project_id`, `target_language`, `speaker`, `context_before`, `context_after`, `constraints`, and `source_location.to_dict()`.
- `from_draft()` sets `target_text` and `translation_source` to `None`; later translation providers may create a replaced immutable instance, allowing `ValidationRequest` and `BuildRequest` to carry candidate text without introducing a second incompatible segment identity.
- Add `to_dict()` and `from_dict()` to all four models; emitted dictionaries must be JSON serializable and deterministic.
- Export these four models from `game_localizer/hanengine/__init__.py`.

- [ ] **Step 4: Run the segment tests**

Run:

```powershell
python -m unittest tests.test_hanengine_segments -v
```

Expected: all segment tests pass.

- [ ] **Step 5: Commit Task 2**

Immediately before staging, run:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus all tests added through Task 2 pass, with no skipped tests.

```powershell
git add game_localizer/hanengine tests/test_hanengine_segments.py
git commit -m "feat: add HanEngine segment models"
```

---

### Task 3: Implement Two-Phase HanGuard Routing

**Files:**
- Create: `game_localizer/hanengine/routing.py`
- Modify: `game_localizer/hanengine/__init__.py`
- Create: `tests/test_hanguard_routing.py`

**Interfaces:**
- `RiskLevel`: `H0_PROJECT`, `H1_OFFLINE`, `H2_RESTRICTED`, `H3_PROTECTED` in increasing numeric order.
- `EvaluationStatus`: `COMPLETE`, `MISSING_EVIDENCE`, `UNKNOWN_RULE`, `EVALUATION_FAILED`; every non-complete status fails closed to at least H2 with a distinct decision reason.
- `RouteOperation`: `DETECT`, `EXTRACT`, `VALIDATE`, `BUILD`, `VERIFY`, `ROLLBACK`, `INSTALL_PATCH`, `CAPTURE`, `OCR`, `VISUAL_REPLACE`.
- `HanGuard.evaluate_provisional(...) -> RoutePlan` only permits `DETECT`.
- `HanGuard.evaluate_final(...) -> RoutePlan` may add operations only from the caller-supplied available-capability set and can never reduce risk below the provisional plan.

- [ ] **Step 1: Write failing routing tests**

Create `tests/test_hanguard_routing.py` covering the following core cases:

```python
import json
import unittest
from pathlib import Path

from game_localizer.hanengine.routing import (
    HanGuard,
    HanGuardRule,
    RiskLevel,
    RiskSignal,
    EvaluationStatus,
    RouteOperation,
    RoutePhase,
    SignalType,
)


ROOT = Path(__file__).resolve().parents[1]


class HanGuardRoutingTests(unittest.TestCase):
    def setUp(self):
        self.rules = (
            HanGuardRule(
                rule_id="known-anticheat",
                rule_version="1.0.0",
                signal_type=SignalType.PATH,
                match_value="knownac.exe",
                minimum_risk=RiskLevel.H3_PROTECTED,
                blocked_operations=frozenset(
                    {RouteOperation.INSTALL_PATCH, RouteOperation.EXTRACT}
                ),
                reason="protected environment",
                evidence_source="synthetic test rule",
                last_verified_date="2026-08-05",
            ),
        )
        self.guard = HanGuard(self.rules)

    def test_provisional_route_only_allows_detect(self):
        plan = self.guard.evaluate_provisional(
            project_id="project-a",
            user_baseline=RiskLevel.H0_PROJECT,
            signals=(),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(plan.phase, RoutePhase.PROVISIONAL)
        self.assertEqual(plan.allowed_operations, frozenset({RouteOperation.DETECT}))

    def test_final_route_never_lowers_provisional_risk(self):
        provisional = self.guard.evaluate_provisional(
            "project-a",
            RiskLevel.H2_RESTRICTED,
            (),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        final = self.guard.evaluate_final(
            provisional,
            adapter_baseline=RiskLevel.H0_PROJECT,
            signals=(),
            available_operations=frozenset(RouteOperation),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(final.risk_after, RiskLevel.H2_RESTRICTED)

    def test_rule_match_records_actual_signal_and_raises_risk(self):
        signal = RiskSignal(
            signal_type=SignalType.PATH,
            value="KnownAC.EXE",
            source="install_root",
            evidence="public file name",
        )
        provisional = self.guard.evaluate_provisional(
            "project-a",
            RiskLevel.H1_OFFLINE,
            (signal,),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(provisional.risk_after, RiskLevel.H3_PROTECTED)
        self.assertEqual(provisional.matches[0].actual_signal, "KnownAC.EXE")

    def test_final_route_intersects_actual_available_capabilities(self):
        provisional = self.guard.evaluate_provisional(
            "project-a",
            RiskLevel.H0_PROJECT,
            (),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        final = self.guard.evaluate_final(
            provisional,
            adapter_baseline=RiskLevel.H0_PROJECT,
            signals=(),
            available_operations=frozenset(
                {RouteOperation.DETECT, RouteOperation.EXTRACT}
            ),
            evaluation_status=EvaluationStatus.COMPLETE,
        )
        self.assertEqual(
            final.allowed_operations,
            frozenset({RouteOperation.DETECT, RouteOperation.EXTRACT}),
        )

    def test_non_complete_evaluation_statuses_default_to_h2_with_distinct_reason(self):
        for status in (
            EvaluationStatus.MISSING_EVIDENCE,
            EvaluationStatus.UNKNOWN_RULE,
            EvaluationStatus.EVALUATION_FAILED,
        ):
            plan = self.guard.evaluate_provisional(
                "project-a",
                RiskLevel.H0_PROJECT,
                (),
                evaluation_status=status,
            )
            self.assertEqual(plan.risk_after, RiskLevel.H2_RESTRICTED)
            self.assertTrue(plan.unknown_evidence)
            self.assertEqual(plan.evaluation_status, status)
            self.assertIn(status.value, plan.decision_reasons)

    def test_all_fixed_guard_cases_match_expected_route(self):
        payload = json.loads(
            (ROOT / "benchmarks/guard_risk_cases.json").read_text(encoding="utf-8")
        )
        for case in payload["cases"]:
            with self.subTest(case_id=case["case_id"]):
                rules = tuple(HanGuardRule.from_dict(item) for item in case["rules"])
                signals = tuple(RiskSignal.from_dict(item) for item in case["signals"])
                guard = HanGuard(rules)
                provisional = guard.evaluate_provisional(
                    case["project_id"],
                    RiskLevel[case["user_baseline"]] if case["user_baseline"] else None,
                    signals,
                    evaluation_status=EvaluationStatus(
                        case["provisional_evaluation_status"]
                    ),
                )
                plan = guard.evaluate_final(
                    provisional,
                    adapter_baseline=(
                        RiskLevel[case["adapter_baseline"]]
                        if case["adapter_baseline"]
                        else None
                    ),
                    signals=signals,
                    available_operations=frozenset(
                        RouteOperation(item) for item in case["available_operations"]
                    ),
                    evaluation_status=EvaluationStatus(
                        case["final_evaluation_status"]
                    ),
                )
                self.assertEqual(plan.risk_after.name, case["expected_risk"])
                self.assertEqual(
                    plan.evaluation_status.value,
                    case["final_evaluation_status"],
                )
                if plan.evaluation_status is not EvaluationStatus.COMPLETE:
                    self.assertIn(
                        plan.evaluation_status.value,
                        plan.decision_reasons,
                    )
                self.assertEqual(
                    sorted(item.value for item in plan.allowed_operations),
                    sorted(case["expected_allowed_operations"]),
                )
                self.assertEqual(
                    sorted(item.value for item in plan.blocked_operations),
                    sorted(case["expected_blocked_operations"]),
                )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the routing tests and verify the import failure**

Run:

```powershell
python -m unittest tests.test_hanguard_routing -v
```

Expected: FAIL because `game_localizer.hanengine.routing` does not exist.

- [ ] **Step 3: Implement routing types and deterministic serialization**

Create these exact models in `routing.py`:

```python
class RiskLevel(IntEnum):
    H0_PROJECT = 0
    H1_OFFLINE = 1
    H2_RESTRICTED = 2
    H3_PROTECTED = 3


class RoutePhase(str, Enum):
    PROVISIONAL = "provisional"
    FINAL = "final"


class EvaluationStatus(str, Enum):
    COMPLETE = "complete"
    MISSING_EVIDENCE = "missing_evidence"
    UNKNOWN_RULE = "unknown_rule"
    EVALUATION_FAILED = "evaluation_failed"


class SignalType(str, Enum):
    USER_DECLARATION = "user_declaration"
    PATH = "path"
    MANIFEST_KEY = "manifest_key"
    PROCESS_NAME = "process_name"
    SERVICE_NAME = "service_name"
    CAPTURE_RESULT = "capture_result"


class RouteOperation(str, Enum):
    DETECT = "detect"
    EXTRACT = "extract"
    VALIDATE = "validate"
    BUILD = "build"
    VERIFY = "verify"
    ROLLBACK = "rollback"
    INSTALL_PATCH = "install_patch"
    CAPTURE = "capture"
    OCR = "ocr"
    VISUAL_REPLACE = "visual_replace"


@dataclass(frozen=True)
class RiskSignal:
    signal_type: SignalType
    value: str
    source: str
    evidence: str


@dataclass(frozen=True)
class HanGuardRule:
    rule_id: str
    rule_version: str
    signal_type: SignalType
    match_value: str
    minimum_risk: RiskLevel
    blocked_operations: frozenset[RouteOperation]
    reason: str
    evidence_source: str
    last_verified_date: str


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    rule_version: str
    actual_signal: str
    source: str
    risk_before: RiskLevel
    risk_after: RiskLevel
    blocked_operations: frozenset[RouteOperation]
    reason: str


@dataclass(frozen=True)
class RoutePlan:
    project_id: str
    phase: RoutePhase
    risk_before: RiskLevel
    risk_after: RiskLevel
    allowed_operations: frozenset[RouteOperation]
    blocked_operations: frozenset[RouteOperation]
    matches: tuple[RuleMatch, ...]
    evaluation_status: EvaluationStatus
    unknown_evidence: bool
    decision_reasons: tuple[str, ...]
```

Add `to_dict()` and `from_dict()` for each evidence/rule/plan model. Sort enum sets by `.value` so persisted JSON is deterministic.

- [ ] **Step 4: Implement the two-phase evaluator**

Use this exact public API:

```python
class HanGuard:
    def __init__(self, rules: Iterable[HanGuardRule]): ...

    def evaluate_provisional(
        self,
        project_id: str,
        user_baseline: RiskLevel | None,
        signals: Iterable[RiskSignal],
        *,
        evaluation_status: EvaluationStatus,
    ) -> RoutePlan: ...

    def evaluate_final(
        self,
        provisional: RoutePlan,
        adapter_baseline: RiskLevel | None,
        signals: Iterable[RiskSignal],
        *,
        available_operations: frozenset[RouteOperation],
        evaluation_status: EvaluationStatus,
    ) -> RoutePlan: ...
```

Policy implementation:

- Case-fold both rule `match_value` and signal `value`; require exact normalized equality and matching `SignalType`.
- Risk equals the maximum of the incoming baseline and every rule minimum. A missing baseline or any `EvaluationStatus` other than `COMPLETE` also contributes `H2_RESTRICTED`; preserve the exact status on `RoutePlan`, set `unknown_evidence=True`, and append its exact `.value` to `decision_reasons` so missing evidence, unknown rules, and evaluation failures are auditable distinct paths.
- Final permissions are `risk_base_operations ∩ available_operations`, followed by rule-block subtraction. The available-capability set may remove capabilities but can never add an operation forbidden by risk policy.
- Provisional routes always have only `DETECT` allowed, even for H0/H1.
- Final H0 and H1 base sets contain all operations; final H2 contains `DETECT`, `CAPTURE`, `OCR`, `VISUAL_REPLACE`; final H3 uses the same safe external set but capture-black-frame or overlay-forbidden rules block `CAPTURE`, `OCR`, and `VISUAL_REPLACE`, leaving only `DETECT`.
- `blocked_operations` is always the exact complement of `allowed_operations` within the complete `RouteOperation` enum.
- `evaluate_final` rejects a non-provisional input and preserves `max(provisional.risk_after, adapter_baseline, matched risks)`.
- For the final plan, `evaluation_status` equals the final argument when it is non-complete; otherwise it preserves a non-complete provisional status; otherwise it is `COMPLETE`. Preserve distinct decision reasons from both phases. Fixed benchmarks place edge statuses in the final phase, while direct unit tests exercise each non-complete provisional path.
- `H3_PROTECTED` is terminal for the current evaluation; no configuration parameter exists to force a lower result.

- [ ] **Step 5: Run routing and benchmark tests**

Run:

```powershell
python -m unittest tests.test_hanguard_routing tests.test_benchmark_manifests -v
```

Expected: all tests pass, including all 80 risk cases.

- [ ] **Step 6: Commit Task 3**

Immediately before staging, run:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus all tests added through Task 3 pass, with no skipped tests.

```powershell
git add game_localizer/hanengine/routing.py game_localizer/hanengine/__init__.py tests/test_hanguard_routing.py
git commit -m "feat: add two-phase HanGuard routing"
```

---

### Task 4: Add HanTask State, Event, and Artifact Models

**Files:**
- Create: `game_localizer/hanengine/tasks.py`
- Modify: `game_localizer/hanengine/__init__.py`
- Create: `tests/test_hantask_models.py`

**Interfaces:**
- Task event types are exactly `queued`, `started`, `progress`, `log`, `warning`, `retrying`, `artifact`, `completed`, `failed`, and `cancelled`.
- `ArtifactKind` is defined once in `tasks.py` with `PATCH`, `MANIFEST`, `BACKUP`, `REPORT`, and `UNTRANSLATED_LIST`; adapter contracts import and re-export this same enum instead of defining another one.
- `TaskEvent.sequence` is positive and monotonically increasing per task.
- `TaskProgress` validates `0 <= completed <= total` and allows `total=None` for indeterminate work.
- All model dictionaries are JSON serializable and contain no callable or exception object.

- [ ] **Step 1: Write failing task model tests**

Create `tests/test_hantask_models.py` with tests for enum values, invalid progress, event sequence, round-trip serialization, and artifact relative-path validation. The core construction test is:

```python
def test_task_plan_round_trips_with_steps(self):
    plan = TaskPlan(
        task_id="task-1",
        project_id="project-a",
        kind="extract",
        state=TaskState.QUEUED,
        steps=(
            TaskStep(
                step_id="detect",
                title="Detect engine",
                operation=RouteOperation.DETECT,
                state=StepState.QUEUED,
                max_retries=0,
            ),
        ),
    )
    self.assertEqual(TaskPlan.from_dict(plan.to_dict()), plan)
```

Also assert that `Artifact(relative_path="../escape.json", ...)`, Windows drive-relative/rooted/UNC/device paths, and backslash traversal raise `ValueError`; that `Artifact.kind` rejects plain strings or unknown enum values; and that sequence `0` is rejected.

- [ ] **Step 2: Run the task model tests and verify the import failure**

Run:

```powershell
python -m unittest tests.test_hantask_models -v
```

Expected: FAIL because `game_localizer.hanengine.tasks` does not exist.

- [ ] **Step 3: Implement the task models**

Use these exact public types:

```python
class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    QUEUED = "queued"
    STARTED = "started"
    PROGRESS = "progress"
    LOG = "log"
    WARNING = "warning"
    RETRYING = "retrying"
    ARTIFACT = "artifact"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(str, Enum):
    PATCH = "patch"
    MANIFEST = "manifest"
    BACKUP = "backup"
    REPORT = "report"
    UNTRANSLATED_LIST = "untranslated_list"


@dataclass(frozen=True)
class TaskProgress:
    completed: int
    total: int | None
    current_item: str | None = None


@dataclass
class TaskStep:
    step_id: str
    title: str
    operation: RouteOperation
    state: StepState = StepState.QUEUED
    attempt: int = 0
    max_retries: int = 0


@dataclass
class TaskPlan:
    task_id: str
    project_id: str
    kind: str
    state: TaskState
    steps: tuple[TaskStep, ...]


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    step_id: str | None
    sequence: int
    event_type: EventType
    timestamp: str
    summary: str
    progress: TaskProgress | None = None
    data: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    task_id: str
    step_id: str
    kind: ArtifactKind
    relative_path: str
    sha256: str | None
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    artifacts: tuple[Artifact, ...] = ()
    data: dict[str, JsonValue] = field(default_factory=dict)
```

Implementation requirements:

- Use UTC ISO 8601 timestamps ending in `Z`; timestamps are created by the runner, not accepted from handler dictionaries.
- Require `Artifact.kind` to be an `ArtifactKind` instance; do not coerce arbitrary strings. Serialize it by `.value` and reconstruct it through `ArtifactKind(...)`.
- Normalize and validate artifact relative paths only through `segments.normalize_relative_path()` so Windows and POSIX path behavior is identical.
- Validate event and artifact metadata with `json.dumps(..., allow_nan=False)`.
- Reject reserved/sensitive keys case-insensitively: `api_key`, `authorization`, `secret`, `token`, `request_body`, `screenshot`, `chain_of_thought`, and `reasoning_trace`.
- Add deterministic `to_dict()` and `from_dict()` to every persisted model.

- [ ] **Step 4: Run the task model tests**

Run:

```powershell
python -m unittest tests.test_hantask_models -v
```

Expected: all task model tests pass.

- [ ] **Step 5: Commit Task 4**

Immediately before staging, run:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus all tests added through Task 4 pass, with no skipped tests.

```powershell
git add game_localizer/hanengine/tasks.py game_localizer/hanengine/__init__.py tests/test_hantask_models.py
git commit -m "feat: add HanTask event models"
```

---

### Task 5: Implement the Headless HanTask Runner

**Files:**
- Modify: `game_localizer/hanengine/tasks.py`
- Modify: `game_localizer/hanengine/__init__.py`
- Create: `tests/test_hantask_runner.py`

**Interfaces:**
- `TaskControl.pause()`, `resume()`, `cancel()`, and `checkpoint()` provide cooperative control.
- `TaskContext.progress()`, `log()`, `warning()`, `artifact()`, and `checkpoint()` are the only handler-facing event APIs.
- Adapter requests reuse the active `TaskContext`; adapters never construct `TaskEvent`, timestamps, or sequence numbers themselves.
- `TaskRunner.run(plan, handlers, control=None) -> TaskPlan` is synchronous and deterministic apart from timestamps.
- GUI threading and scheduling remain out of scope; a future caller may run this synchronous runner on a worker thread.

- [ ] **Step 1: Write failing runner tests**

Create `tests/test_hantask_runner.py` covering:

- queued → started → progress/artifact → completed event order;
- strictly increasing sequences beginning at 1;
- one recoverable handler failure emits `retrying`, increments attempt, and succeeds within `max_retries`;
- exhausted retries mark the step and task failed and emit a sanitized `failed` event;
- a cancellation requested before the second step marks remaining work cancelled and confirms within the next checkpoint;
- a paused control blocks at `checkpoint()` until `resume()` is called, using a test thread with a one-second safety timeout;
- no event includes exception objects or sensitive keys.

Import `ArtifactKind` with the other task models. The handler API used in tests must be:

```python
def handler(context: TaskContext) -> StepResult:
    context.progress(1, 2, current_item="game/script.rpy")
    artifact = Artifact(
        artifact_id="artifact-1",
        task_id=context.task_id,
        step_id=context.step_id,
        kind=ArtifactKind.REPORT,
        relative_path="reports/extract.json",
        sha256=None,
    )
    context.artifact(artifact)
    return StepResult(artifacts=(artifact,), data={"processed": 1})
```

- [ ] **Step 2: Run the runner tests and verify missing symbols**

Run:

```powershell
python -m unittest tests.test_hantask_runner -v
```

Expected: FAIL importing `TaskControl`, `TaskContext`, or `TaskRunner`.

- [ ] **Step 3: Implement cooperative control and context**

Add:

```python
class TaskCancelled(RuntimeError):
    pass


class TaskControl:
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def cancel(self) -> None: ...
    def is_cancelled(self) -> bool: ...
    def checkpoint(self) -> None: ...


EventSink = Callable[[TaskEvent], None]
ContextEventEmitter = Callable[
    [str, str, EventType, str, TaskProgress | None, dict[str, JsonValue]],
    TaskEvent,
]


class TaskContext:
    def __init__(
        self,
        task_id: str,
        step_id: str,
        control: TaskControl,
        emit_event: ContextEventEmitter,
    ): ...

    @property
    def task_id(self) -> str: ...

    @property
    def step_id(self) -> str: ...

    def progress(
        self,
        completed: int,
        total: int | None,
        *,
        current_item: str | None = None,
        data: dict[str, JsonValue] | None = None,
    ) -> None: ...

    def log(self, summary: str, data: dict[str, JsonValue] | None = None) -> None: ...
    def warning(self, summary: str, data: dict[str, JsonValue] | None = None) -> None: ...
    def artifact(self, artifact: Artifact) -> None: ...
    def checkpoint(self) -> None: ...
```

Use `threading.Condition` inside `TaskControl`; `pause()` only changes the flag, `checkpoint()` waits while paused, and `cancel()` wakes all waiters and raises `TaskCancelled` at the next checkpoint.

`TaskContext` is also the adapter execution context. Only `TaskRunner` and tests construct it; the runner-supplied `ContextEventEmitter` owns UTC timestamps, the task-wide next sequence, `TaskEvent` construction, and delivery to `EventSink`. Adapters receive only the context's safe event/checkpoint methods and never receive `ContextEventEmitter` or `EventSink` directly. `TaskContext.artifact()` must validate `artifact.task_id == context.task_id` and `artifact.step_id == context.step_id`, then emit exactly one `ARTIFACT` event with this fixed payload:

```python
data={"artifact": artifact.to_dict()}
```

No flattened alternative or second artifact event shape is allowed.

- [ ] **Step 4: Implement state transitions, retries, and event sequencing**

Add:

```python
StepHandler = Callable[[TaskContext], StepResult]


class TaskRunner:
    def __init__(self, event_sink: EventSink): ...

    def run(
        self,
        plan: TaskPlan,
        handlers: Mapping[str, StepHandler],
        control: TaskControl | None = None,
    ) -> TaskPlan: ...
```

Rules:

- Reject duplicate step IDs, a non-queued plan, or a missing handler before emitting `started`.
- Emit task-level `queued` sequence 1, then task-level `started`.
- Before each attempt call `control.checkpoint()` and increment `step.attempt`.
- A handler exception emits only its exception type plus the fixed text `step failed`; do not serialize `str(exc)`, traceback or exception objects because an arbitrary exception message may contain credentials or request content. A handler that needs a user-facing explanation must emit an already-sanitized warning before raising.
- Retry while `attempt <= max_retries`; emit `retrying` and update task/step states.
- `TaskCancelled` emits one terminal `cancelled` event and marks the active and remaining queued steps cancelled.
- On success emit step `completed` events and one task-level `completed` event.
- Event sequence is owned by one runner invocation and strictly increments for every event sent to the sink.
- A handler returning an artifact must have already emitted it through `context.artifact()`; deduplicate by `artifact_id` when producing the final step data.
- Tests must assert the exact nested artifact event payload, that the payload round-trips with `Artifact.from_dict()`, and that every event produced inside an adapter/handler shares the runner's single monotonically increasing sequence.

- [ ] **Step 5: Run task tests**

Run:

```powershell
python -m unittest tests.test_hantask_models tests.test_hantask_runner -v
```

Expected: all HanTask tests pass without a thread left alive.

- [ ] **Step 6: Commit Task 5**

Immediately before staging, run:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus all tests added through Task 5 pass, with no skipped tests.

```powershell
git add game_localizer/hanengine/tasks.py game_localizer/hanengine/__init__.py tests/test_hantask_runner.py
git commit -m "feat: add headless HanTask runner"
```

---

### Task 6: Materialize the Adapter v1 Contract

**Files:**
- Create: `game_localizer/adapters/contract.py`
- Create: `tests/test_adapter_contract.py`
- Modify: `docs/superpowers/specs/2026-08-05-hanengine-adapter-contract.md`

**Interfaces:**
- Contract identifier: `hanengine.adapter/v1`.
- `AdapterV1` is a `typing.Protocol`; this task does not replace the existing `EngineAdapter` ABC.
- All failures are returned as `AdapterError`; concrete methods do not expose raw exceptions across the adapter boundary.
- Contract `Operation` remains the six adapter operations and is intentionally separate from the larger HanGuard `RouteOperation` set.
- `adapter_operations_for_route(route: RoutePlan) -> frozenset[Operation]` is the only bridge between the enums and uses an explicit six-entry mapping; string-based or constructor-based implicit conversion is forbidden.
- Each request carries the active `TaskContext` rather than a raw `TaskControl` plus full-event sink, so adapter progress joins the runner-owned event sequence.

- [ ] **Step 0: Synchronize the written adapter v1 contract**

Modify `docs/superpowers/specs/2026-08-05-hanengine-adapter-contract.md` before materializing its types:

- In section 3, require every one of `DetectionRequest`, `ExtractRequest`, `ValidationRequest`, `BuildRequest`, `VerifyRequest`, and `RollbackRequest` to carry the active `TaskContext` created by `TaskRunner`; remove all separate `cancellation_token` and `event_sink` request fields.
- In section 5, state that adapters report progress, logs, warnings, artifacts and cooperative cancellation only through the request's `TaskContext` methods.
- State that `TaskRunner` alone owns the task-wide event sequence, UTC timestamps, `TaskEvent` construction and delivery to `EventSink`; adapters must not receive a raw `EventSink`, construct `TaskEvent`, or choose sequence numbers/timestamps.
- Keep the contract identifier `hanengine.adapter/v1`; this is a pre-implementation correction of the reviewed v1 design, not a shipped breaking change.

- [ ] **Step 1: Write failing contract model and harness tests**

Create `tests/test_adapter_contract.py` with:

- metadata version, semantic adapter version, nonempty version/platform declarations, and maturity/capability consistency tests;
- `Evidence.weight` range and matched-result evidence requirements;
- `EvidenceSource` accepts only approved non-invasive source categories;
- `AdapterError` code/operation/recoverability and JSON-details tests;
- `DetectionRequest.allowed_operations` must equal exactly `{Operation.DETECT}`; request path, distinct-root, symlink, Windows junction, and project ID validation;
- exact `adapter_operations_for_route()` mapping for all six shared operations, with policy-only route operations omitted and no implicit enum conversion;
- a minimal structurally complete `FakeAdapter` implementing all six `AdapterV1` methods; `detect` returns deterministic matched/unmatched results by request root, while the five unavailable detect-only operations return the corresponding sanitized `AdapterError` without side effects;
- a concrete `AdapterContractTests(AdapterV1ContractMixin, unittest.TestCase)` that implements `make_adapter()`, a guaranteed matched `make_detection_request()`, and a guaranteed unmatched `make_unmatched_detection_request()`, then runs all five shared detect-only tests from Task 1 without conditional assertions.
- request-field tests using `dataclasses.fields()` that unconditionally prove all six request records contain exactly one runner-facing execution field named `context` and contain neither `event_sink` nor `cancellation_token`;
- an adapter/runner integration test in which a `TaskRunner` handler constructs a `DetectionRequest` with that handler's current `TaskContext`, then calls `FakeAdapter.detect()`; `FakeAdapter.detect()` must call `request.context.progress()` and `request.context.log()` and must never receive/import `EventSink` or construct `TaskEvent`.

The adapter/runner integration test must make these unconditional assertions (no `if result.matched`, filtering fallback, or optional branch):

Import the `dataclasses` module; import `DetectionResult` and all six request dataclasses from `game_localizer.adapters.contract`; and import `EventType`, `StepResult`, `TaskContext`, `TaskPlan`, `TaskRunner`, `TaskState`, and `TaskStep` from `game_localizer.hanengine.tasks` plus `RouteOperation` from `game_localizer.hanengine.routing`. The request-field test iterates over the explicit six-request tuple rather than discovering subclasses dynamically.

```python
def test_requests_only_expose_runner_created_task_context(self):
    request_types = (
        DetectionRequest,
        ExtractRequest,
        ValidationRequest,
        BuildRequest,
        VerifyRequest,
        RollbackRequest,
    )
    for request_type in request_types:
        with self.subTest(request_type=request_type.__name__):
            names = {field.name for field in dataclasses.fields(request_type)}
            self.assertIn("context", names)
            self.assertTrue({"event_sink", "cancellation_token"}.isdisjoint(names))
```

```python
def test_adapter_events_share_the_runner_owned_sequence(self):
    events = []
    adapter = self.make_adapter()
    plan = TaskPlan(
        task_id="task-adapter-detect",
        project_id="project-a",
        kind="detect",
        state=TaskState.QUEUED,
        steps=(
            TaskStep(
                step_id="detect",
                title="Detect engine",
                operation=RouteOperation.DETECT,
            ),
        ),
    )

    def handler(context: TaskContext) -> StepResult:
        request = dataclasses.replace(
            self.make_detection_request(),
            context=context,
        )
        result = adapter.detect(request)
        self.assertIsInstance(result, DetectionResult)
        self.assertTrue(result.matched)
        return StepResult(data={"matched": result.matched})

    completed = TaskRunner(events.append).run(plan, {"detect": handler})

    self.assertEqual(completed.state, TaskState.COMPLETED)
    self.assertEqual(
        [event.event_type for event in events],
        [
            EventType.QUEUED,
            EventType.STARTED,
            EventType.PROGRESS,
            EventType.LOG,
            EventType.COMPLETED,
            EventType.COMPLETED,
        ],
    )
    self.assertEqual(
        [event.sequence for event in events],
        list(range(1, len(events) + 1)),
    )
```

The `FakeAdapter.detect()` implementation used by both the mixin and integration test emits exactly one progress and one log event through `request.context`; tests may construct a context fixture for direct contract calls, but production adapter code never constructs a context or receives the runner's emitter/sink.

Run:

```powershell
python -m unittest tests.test_adapter_contract -v
```

Expected: FAIL because `game_localizer.adapters.contract` does not exist.

- [ ] **Step 2: Implement contract enums and common models**

Create these enums exactly:

```python
class AdapterMaturity(str, Enum):
    DETECT_ONLY = "detect_only"
    EXTRACT_READY = "extract_ready"
    BUILD_READY = "build_ready"
    VERIFIED = "verified"


class AdapterCapability(str, Enum):
    DETECT = "detect"
    EXTRACT = "extract"
    VALIDATE = "validate"
    BUILD = "build"
    VERIFY = "verify"
    ROLLBACK = "rollback"


class Operation(str, Enum):
    DETECT = "detect"
    EXTRACT = "extract"
    VALIDATE = "validate"
    BUILD = "build"
    VERIFY = "verify"
    ROLLBACK = "rollback"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EvidenceSource(str, Enum):
    FILESYSTEM = "filesystem"
    PROJECT_MANIFEST = "project_manifest"
    ENGINE_MARKER = "engine_marker"
    USER_DECLARATION = "user_declaration"
    HANGUARD_SIGNAL = "hanguard_signal"


class DeclaredMode(str, Enum):
    PLAYER = "player"
    STUDIO = "studio"
```

Add `AdapterErrorCode` with all 16 codes from the approved contract: `UNSUPPORTED_INPUT`, `ENGINE_NOT_DETECTED`, `UNSUPPORTED_VERSION`, `RISK_POLICY_BLOCKED`, `READ_FAILED`, `DECODE_FAILED`, `PARSE_FAILED`, `EXTRACT_PARTIAL`, `VALIDATION_FAILED`, `STAGING_ESCAPE_BLOCKED`, `BUILD_FAILED`, `VERIFY_FAILED`, `BACKUP_FAILED`, `ROLLBACK_FAILED`, `CANCELLED`, `INTERNAL_ERROR`.

Implement exact common models:

```python
@dataclass(frozen=True)
class AdapterMetadata:
    adapter_id: str
    contract_version: str
    adapter_version: str
    engine_name: str
    supported_engine_versions: tuple[str, ...]
    capabilities: frozenset[AdapterCapability]
    maturity: AdapterMaturity
    platforms: tuple[str, ...]
    known_limitations: tuple[str, ...]


@dataclass(frozen=True)
class Evidence:
    code: str
    source: EvidenceSource
    value: str
    weight: float
    description: str


@dataclass(frozen=True)
class AdapterError:
    code: AdapterErrorCode
    operation: Operation
    message: str
    recoverable: bool
    segment_id: str | None = None
    relative_path: str | None = None
    evidence: tuple[Evidence, ...] = ()
    details: dict[str, JsonValue] = field(default_factory=dict)
    cause_type: str | None = None
```

Validation rules:

- `contract_version` must equal `hanengine.adapter/v1`.
- `adapter_id` uses lower-case reverse-domain components; `adapter_version` is `MAJOR.MINOR.PATCH` with nonnegative integers.
- Capability maturity gates are cumulative: `DETECT_ONLY` needs `DETECT`; `EXTRACT_READY` also needs `EXTRACT`; `BUILD_READY` also needs `VALIDATE`, `BUILD`, and `VERIFY`; `VERIFIED` additionally needs `ROLLBACK`.
- Evidence weights are `[0.0, 1.0]`.
- `Evidence.source` must be an `EvidenceSource`; plain strings and unapproved categories are rejected. Re-export the single `ArtifactKind` imported from `game_localizer.hanengine.tasks`; do not declare an adapter-local duplicate.
- Error details use the same JSON/sensitive-key validation as task events.

Add the explicit route bridge beside the enums:

```python
_ROUTE_TO_ADAPTER_OPERATION = {
    RouteOperation.DETECT: Operation.DETECT,
    RouteOperation.EXTRACT: Operation.EXTRACT,
    RouteOperation.VALIDATE: Operation.VALIDATE,
    RouteOperation.BUILD: Operation.BUILD,
    RouteOperation.VERIFY: Operation.VERIFY,
    RouteOperation.ROLLBACK: Operation.ROLLBACK,
}


def adapter_operations_for_route(route: RoutePlan) -> frozenset[Operation]:
    return frozenset(
        _ROUTE_TO_ADAPTER_OPERATION[item]
        for item in route.allowed_operations
        if item in _ROUTE_TO_ADAPTER_OPERATION
    )
```

Tests must prove the mapping has exactly six entries, every key/value is the declared enum instance (not a string conversion), policy-only `INSTALL_PATCH`, `CAPTURE`, `OCR`, and `VISUAL_REPLACE` never appear, and a provisional route maps to `{Operation.DETECT}`.

- [ ] **Step 3: Implement all operation request/result records**

Use immutable dataclasses with these exact fields:

```python
@dataclass(frozen=True)
class DetectionRequest:
    input_root: Path
    declared_mode: DeclaredMode
    project_id: str
    risk_level: RiskLevel
    allowed_operations: frozenset[Operation]
    context: TaskContext

@dataclass(frozen=True)
class DetectionResult:
    matched: bool
    engine_name: str | None
    engine_version: str | None
    confidence: float
    evidence: tuple[Evidence, ...]
    maturity: AdapterMaturity
    capabilities: frozenset[AdapterCapability]
    limitations: tuple[str, ...]
    recommended_operation: Operation

@dataclass(frozen=True)
class ExtractRequest:
    source_root: Path
    working_root: Path
    candidate_encodings: tuple[str, ...]
    filters: tuple[str, ...]
    project_id: str
    context: TaskContext

@dataclass(frozen=True)
class ExtractResult:
    segments: tuple[SegmentDraft, ...]
    source_tree_fingerprint: str
    read_files: tuple[str, ...]
    skipped_files: tuple[str, ...]
    warnings: tuple[str, ...]
    statistics: dict[str, int]

@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: IssueSeverity
    segment_id: str | None
    source_location: SourceLocation | None
    message: str
    automatically_recoverable: bool
    suggested_action: str

@dataclass(frozen=True)
class ValidationRequest:
    source_tree_fingerprint: str
    original_segments: tuple[Segment, ...]
    translated_segments: tuple[Segment, ...]
    target_encoding: str
    project_rules: dict[str, JsonValue]
    context: TaskContext

@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    automatic_fixes: tuple[str, ...]
    blocking_issue_count: int
    warning_count: int

@dataclass(frozen=True)
class BuildRequest:
    source_root: Path
    staging_root: Path
    validated_segments: tuple[Segment, ...]
    source_tree_fingerprint: str
    output_options: dict[str, JsonValue]
    context: TaskContext

@dataclass(frozen=True)
class BuildManifestEntry:
    relative_path: str
    change_kind: str
    sha256: str

@dataclass(frozen=True)
class BuildResult:
    generated_files: tuple[str, ...]
    added_files: tuple[str, ...]
    modified_files: tuple[str, ...]
    deleted_files: tuple[str, ...]
    manifest: tuple[BuildManifestEntry, ...]
    artifacts: tuple[Artifact, ...]
    candidate_fingerprint: str
    warnings: tuple[str, ...]
    statistics: dict[str, int]

@dataclass(frozen=True)
class VerifyRequest:
    source_tree_fingerprint: str
    staging_root: Path
    manifest: tuple[BuildManifestEntry, ...]
    verification_level: str
    context: TaskContext

@dataclass(frozen=True)
class VerificationCheck:
    code: str
    passed: bool
    message: str

@dataclass(frozen=True)
class VerifyResult:
    passed: bool
    checks: tuple[VerificationCheck, ...]
    syntax_passed: bool
    encoding_passed: bool
    artifact_hashes: dict[str, str]
    smoke_test_passed: bool | None
    issues: tuple[ValidationIssue, ...]

@dataclass(frozen=True)
class RollbackRequest:
    project_id: str
    install_manifest: tuple[BuildManifestEntry, ...]
    backup_manifest: tuple[BuildManifestEntry, ...]
    target_root: Path
    expected_original_hashes: dict[str, str]
    context: TaskContext

@dataclass(frozen=True)
class RollbackResult:
    restored_files: tuple[str, ...]
    unchanged_files: tuple[str, ...]
    failed_files: tuple[str, ...]
    hash_verification_passed: bool
    issues: tuple[ValidationIssue, ...]
```

Use `Artifact`, `ArtifactKind`, and `TaskContext` from `game_localizer.hanengine.tasks`, `Segment`/`SegmentDraft`/`SourceLocation`/`normalize_relative_path` from `segments.py`, and `RiskLevel`/`RouteOperation`/`RoutePlan` from `routing.py`. `DetectionRequest.__post_init__` requires `allowed_operations == frozenset({Operation.DETECT})`; any extra operation is rejected before adapter invocation. Every path list is normalized only with `normalize_relative_path()`.

All request roots must already be absolute and resolved. For every pair that must be distinct (`source_root`/`working_root`, `source_root`/`staging_root`), compare resolved targets and reject equality or containment that violates the operation boundary. Tests must cover ordinary symlink and Windows directory-junction aliases without adding skips: use injected/mock-resolved path identities for the platform-neutral unit cases, plus a real junction case on the Windows release host. Build/verify path tests must also reject a staging child whose resolved symlink/junction target is outside the staging root.

- [ ] **Step 4: Add the `AdapterV1` protocol**

```python
class AdapterV1(Protocol):
    metadata: AdapterMetadata

    def detect(self, request: DetectionRequest) -> DetectionResult | AdapterError: ...
    def extract(self, request: ExtractRequest) -> ExtractResult | AdapterError: ...
    def validate(self, request: ValidationRequest) -> ValidationResult | AdapterError: ...
    def build(self, request: BuildRequest) -> BuildResult | AdapterError: ...
    def verify(self, request: VerifyRequest) -> VerifyResult | AdapterError: ...
    def rollback(self, request: RollbackRequest) -> RollbackResult | AdapterError: ...
```

Do not make this protocol inherit or modify the legacy `EngineAdapter`. The later migration plan will provide an explicit compatibility adapter.

- [ ] **Step 5: Run adapter contract and foundation tests**

Run:

```powershell
python -m unittest tests.test_adapter_contract tests.test_hanengine_segments tests.test_hanguard_routing tests.test_hantask_models tests.test_hantask_runner -v
```

Expected: all tests pass; the concrete fake adapter executes the shared contract mixin, and the adapter/runner integration test proves adapter events share the runner-owned strictly increasing sequence.

- [ ] **Step 6: Commit Task 6**

Immediately before staging, run:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus all tests added through Task 6 pass, with no skipped tests.

```powershell
git add game_localizer/adapters/contract.py tests/test_adapter_contract.py docs/superpowers/specs/2026-08-05-hanengine-adapter-contract.md
git commit -m "feat: define HanEngine adapter v1 contract"
```

---

### Task 7: Add Project-Isolated HanStore Persistence

**Files:**
- Create: `game_localizer/hanengine/store.py`
- Modify: `game_localizer/hanengine/__init__.py`
- Create: `tests/test_hanstore.py`

**Interfaces:**
- `default_data_root(local_app_data: Path | None = None) -> Path` returns `<LOCALAPPDATA>/HanEngine` and fails clearly when no base is available.
- `HanStore(data_root: Path)` owns `config.db` and the `projects/` directory.
- `HanStore.create_project(name, source_root=None, project_id=None) -> ProjectRecord` uses a UUID and creates a dedicated `hanengine.db`.
- `HanStore.open_project(project_id) -> ProjectStore` never searches another project database.
- This task implements isolation and persistence only; destructive project deletion and Credential Manager integration remain later work.

- [ ] **Step 1: Write failing HanStore tests**

Create `tests/test_hanstore.py` covering:

- default path resolution with an injected local-app-data directory;
- UUID validation and rejection of path separators/traversal in project IDs;
- `config.db` plus exact project database path `projects/<project_id>/hanengine.db`;
- schema version `1` and foreign keys enabled;
- two projects persist same `segment_id` without collision and cannot read each other's rows;
- route, task, step, event, artifact, and checkpoint round trips; the checkpoint case must save, close the project database, reopen it through `HanStore`, read through the public API, and compare the reconstructed `Checkpoint` for exact equality;
- `ProjectRecord` and `Checkpoint` exact `to_dict()`/`from_dict()` round trips with canonical JSON;
- duplicate event sequence for one task is rejected transactionally;
- failed batch insertion rolls back the whole batch;
- SQLite/JSON contains no API-key field.

The isolation test must resemble:

```python
with tempfile.TemporaryDirectory() as directory:
    store = HanStore(Path(directory))
    first = store.create_project("First", project_id="11111111-1111-4111-8111-111111111111")
    second = store.create_project("Second", project_id="22222222-2222-4222-8222-222222222222")
    with store.open_project(first.project_id) as first_db, store.open_project(second.project_id) as second_db:
        first_db.save_segments((make_segment(first.project_id),))
        second_db.save_segments((make_segment(second.project_id),))
        self.assertEqual(len(first_db.list_segments()), 1)
        self.assertEqual(len(second_db.list_segments()), 1)
        self.assertNotEqual(first_db.path, second_db.path)
```

The persisted checkpoint round-trip must use only public APIs and resemble:

```python
with tempfile.TemporaryDirectory() as directory:
    store = HanStore(Path(directory))
    project = store.create_project(
        "Checkpoint Project",
        project_id="33333333-3333-4333-8333-333333333333",
    )
    task = TaskPlan(
        task_id="task-1",
        project_id=project.project_id,
        kind="detect",
        state=TaskState.QUEUED,
        steps=(
            TaskStep(
                step_id="detect",
                title="Detect engine",
                operation=RouteOperation.DETECT,
            ),
        ),
    )
    checkpoint = Checkpoint(
        checkpoint_id="checkpoint-1",
        task_id=task.task_id,
        step_id="detect",
        sequence=1,
        payload={"cursor": 7, "paths": ["game/script.rpy"]},
    )
    with store.open_project(project.project_id) as project_db:
        project_db.save_task(task)
        project_db.save_checkpoint(checkpoint)

    with store.open_project(project.project_id) as reopened:
        restored = reopened.get_checkpoint(checkpoint.checkpoint_id)

    self.assertEqual(restored, checkpoint)
```

- [ ] **Step 2: Run HanStore tests and verify the import failure**

Run:

```powershell
python -m unittest tests.test_hanstore -v
```

Expected: FAIL because `game_localizer.hanengine.store` does not exist.

- [ ] **Step 3: Implement paths, project index, and schema migration**

Use these public types:

```python
@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    name: str
    source_root: str | None
    created_at: str

    def to_dict(self) -> dict[str, JsonValue]: ...

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> "ProjectRecord": ...


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    task_id: str
    step_id: str
    sequence: int
    payload: dict[str, JsonValue]

    def to_dict(self) -> dict[str, JsonValue]: ...

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonValue]) -> "Checkpoint": ...


class HanStore:
    def __init__(self, data_root: Path): ...
    def create_project(
        self,
        name: str,
        source_root: Path | None = None,
        project_id: str | None = None,
    ) -> ProjectRecord: ...
    def get_project(self, project_id: str) -> ProjectRecord | None: ...
    def list_projects(self) -> tuple[ProjectRecord, ...]: ...
    def open_project(self, project_id: str) -> "ProjectStore": ...
```

`config.db` schema v1:

```sql
CREATE TABLE schema_info (version INTEGER NOT NULL);
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_root TEXT,
    created_at TEXT NOT NULL
);
```

Per-project schema v1 tables:

- `schema_info(version)`
- `project_meta(project_id PRIMARY KEY, name, created_at)`
- `segments(project_id, segment_id, payload_json, PRIMARY KEY(project_id, segment_id))`
- `route_plans(project_id, phase, payload_json, PRIMARY KEY(project_id, phase))`
- `tasks(project_id, task_id PRIMARY KEY, payload_json)`
- `task_steps(project_id, task_id, step_id, payload_json, PRIMARY KEY(task_id, step_id), FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE)`
- `task_events(project_id, task_id, sequence, payload_json, PRIMARY KEY(task_id, sequence), FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE)`
- `artifacts(project_id, artifact_id PRIMARY KEY, task_id, step_id, payload_json, FOREIGN KEY(task_id, step_id) REFERENCES task_steps(task_id, step_id) ON DELETE CASCADE)`
- `checkpoints(project_id, checkpoint_id PRIMARY KEY, task_id, step_id, sequence, payload_json, FOREIGN KEY(task_id, step_id) REFERENCES task_steps(task_id, step_id) ON DELETE CASCADE)`

Enable `PRAGMA foreign_keys = ON`, use explicit transactions, and store canonical JSON with `ensure_ascii=False`, `allow_nan=False`, `sort_keys=True`, compact separators.

Every persisted model, including `ProjectRecord` and `Checkpoint`, must implement symmetric deterministic `to_dict()`/`from_dict()`. Validate and copy checkpoint payloads with the same recursive JSON and sensitive-key rules as task-event data; no SQLite row is reconstructed by ad-hoc field indexing when a model deserializer exists.

- [ ] **Step 4: Implement the project database API**

```python
class ProjectStore:
    @property
    def project_id(self) -> str: ...

    @property
    def path(self) -> Path: ...

    def save_segments(self, segments: Iterable[Segment]) -> None: ...
    def list_segments(self) -> tuple[Segment, ...]: ...
    def save_route(self, route: RoutePlan) -> None: ...
    def get_route(self, phase: RoutePhase) -> RoutePlan | None: ...
    def save_task(self, task: TaskPlan) -> None: ...
    def get_task(self, task_id: str) -> TaskPlan | None: ...
    def append_event(self, event: TaskEvent) -> None: ...
    def list_events(self, task_id: str, after_sequence: int = 0) -> tuple[TaskEvent, ...]: ...
    def save_artifact(self, artifact: Artifact) -> None: ...
    def list_artifacts(self, task_id: str) -> tuple[Artifact, ...]: ...
    def save_checkpoint(self, checkpoint: Checkpoint) -> None: ...
    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None: ...
    def close(self) -> None: ...
    def __enter__(self) -> "ProjectStore": ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...
```

Every write validates that model `project_id` or owning task belongs to `self.project_id`. A mismatch raises `ValueError` before starting a transaction. `get_checkpoint()` reads the canonical `payload_json`, parses it as JSON, and returns `Checkpoint.from_dict(...)`; it returns `None` only when that checkpoint ID does not exist in the current project database. The close/reopen test above must not inspect a SQLite row or call a private helper. Do not add project deletion, backup retention, global translation memory, terms, or secret storage in this cycle.

- [ ] **Step 5: Run storage and model tests**

Run:

```powershell
python -m unittest tests.test_hanstore tests.test_hanengine_segments tests.test_hanguard_routing tests.test_hantask_models -v
```

Expected: all tests pass and temporary databases are removed when the test context exits.

- [ ] **Step 6: Commit Task 7**

Immediately before staging, run:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus all tests added through Task 7 pass, with no skipped tests.

```powershell
git add game_localizer/hanengine/store.py game_localizer/hanengine/__init__.py tests/test_hanstore.py
git commit -m "feat: add project-isolated HanStore"
```

---

### Task 8: Wire the Headless HanCore Orchestrator

**Files:**
- Create: `game_localizer/hanengine/core.py`
- Modify: `game_localizer/hanengine/__init__.py`
- Create: `tests/test_hancore.py`

**Interfaces:**
- `HanCore` owns one open `ProjectStore` and never crosses its project boundary.
- `ingest_segments` deduplicates identical IDs only when source fingerprints agree.
- `create_task` validates every step against one final route before persistence.
- `run_task` persists every event and artifact while returning the final task state.

- [ ] **Step 1: Write failing HanCore tests**

Create `tests/test_hancore.py` covering:

- ingesting drafts produces deterministic, project-scoped segments and saves them;
- duplicate `segment_id` plus equal source fingerprint deduplicates;
- duplicate `segment_id` plus different source fingerprint raises before any row is written;
- provisional route rejects an `EXTRACT` task;
- final H0 route permits `DETECT` and `EXTRACT` steps;
- a task/route/store project mismatch is rejected;
- successful execution persists task states, ordered events and artifacts;
- failed and cancelled execution persist terminal states;
- a blocked step is rejected before runner construction: its handler is never called and no task event or artifact is emitted or persisted.

The route enforcement test must call:

```python
with self.assertRaisesRegex(RouteBlockedError, "extract"):
    core.create_task(
        kind="extract",
        route=provisional_route,
        steps=(TaskStep("extract", "Extract text", RouteOperation.EXTRACT),),
    )
```

For the handler non-invocation test, construct an otherwise valid queued `TaskPlan` in memory with one route-blocked step, install a spy in the `handlers` mapping, snapshot persisted events/artifacts, and call `run_task`. `run_task` must raise `RouteBlockedError` during route validation before constructing `TaskRunner`; assert the spy call count is zero and both persisted collections are unchanged. This foundation does not infer an operation from artifact kind.

- [ ] **Step 2: Run HanCore tests and verify the import failure**

Run:

```powershell
python -m unittest tests.test_hancore -v
```

Expected: FAIL because `game_localizer.hanengine.core` does not exist.

- [ ] **Step 3: Implement route enforcement and segment ingestion**

Use this API:

```python
class RouteBlockedError(PermissionError):
    pass


class SegmentConflictError(ValueError):
    pass


class HanCore:
    def __init__(self, store: ProjectStore): ...

    def ingest_segments(
        self,
        drafts: Iterable[SegmentDraft],
        *,
        target_language: str,
    ) -> tuple[Segment, ...]: ...

    def create_task(
        self,
        *,
        kind: str,
        route: RoutePlan,
        steps: Iterable[TaskStep],
        task_id: str | None = None,
    ) -> TaskPlan: ...

    def run_task(
        self,
        task: TaskPlan,
        *,
        route: RoutePlan,
        handlers: Mapping[str, StepHandler],
        control: TaskControl | None = None,
    ) -> TaskPlan: ...
```

Rules:

- Require `route.phase is FINAL` for every operation except a task containing only `DETECT`; a detect-only task may use a provisional route.
- Require all `TaskStep.operation` values in `route.allowed_operations` before persisting the task or emitting events.
- `run_task` repeats project, phase, and operation authorization checks on the supplied in-memory task before constructing `TaskRunner`, so callers cannot bypass `create_task` with a manually built plan.
- Generate UUIDv4 task IDs when absent.
- Ingest drafts into memory first, detect conflicts, then call one transactional `save_segments`; never partially persist a conflicting batch.
- Deduplicate by `(project_id, segment_id)` only when `source_fingerprint` is identical.

- [ ] **Step 4: Persist runner events and artifacts**

In `run_task`, construct the runner with a sink that:

1. appends the event to `ProjectStore`;
2. when `event_type is ARTIFACT`, reconstructs the referenced artifact from structured event data and saves it;
3. updates the task row after every terminal step event and after the terminal task event.

Do not catch `KeyboardInterrupt` or `SystemExit`. Convert ordinary unexpected orchestration errors into a failed task event only after route and project-boundary validation has passed.

For item 2, accept only the exact Task 5 payload `event.data == {"artifact": <Artifact.to_dict()>}`. Reconstruct with `Artifact.from_dict(event.data["artifact"])`, validate task/step ownership again, and reject malformed or additional payload keys before any artifact write.

- [ ] **Step 5: Run the HanCore end-to-end tests**

Run:

```powershell
python -m unittest tests.test_hancore tests.test_hanstore tests.test_hantask_runner -v
```

Expected: all headless orchestration, storage and runner tests pass.

- [ ] **Step 6: Commit Task 8**

Immediately before staging, run:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus all tests added through Task 8 pass, with no skipped tests.

```powershell
git add game_localizer/hanengine/core.py game_localizer/hanengine/__init__.py tests/test_hancore.py
git commit -m "feat: wire headless HanCore foundation"
```

---

### Task 9: Document the Foundation and Run the Full Release Gate

**Files:**
- Modify: `README.md`

**Interfaces:**
- README clearly distinguishes the existing usable local file translator from the new internal HanEngine foundation.
- No command is advertised as modifying packaged games.

- [ ] **Step 1: Add the HanEngine foundation status to README**

Add a concise section containing:

- implemented: benchmark manifests, adapter v1 types/harness, two-phase HanGuard, headless task events/runner, project-isolated SQLite storage, and HanCore route enforcement;
- not implemented in this cycle: Ren'Py extraction/writeback, OCR/original-position visual replacement, cloud translation, TTS, packaged-game patching, backup/rollback, and the new dual-mode GUI;
- tests:

```powershell
python tools/generate_benchmark_manifests.py --check
python -m unittest discover -s tests -v
```

- ethics: only process legally owned or explicitly authorized resources; no cracking, decryption, DRM bypass, injection, memory hooks or protocol interception.
- licensing: `benchmarks/LICENSE` applies CC0-1.0 only to repository-owned synthetic benchmark content; the repository root license remains undecided, and no third-party code or assets are included.

- [ ] **Step 2: Compile all Python modules**

Run:

```powershell
python -m compileall -q game_localizer tests tools
```

Expected: command exits 0 with no syntax errors.

- [ ] **Step 3: Verify benchmark determinism**

Run:

```powershell
python tools/generate_benchmark_manifests.py --check
git check-attr text eol -- benchmarks/manifest.json
```

Expected: the generator exits 0 and `git status --short` remains unchanged; `git check-attr` reports `text: set` and `eol: lf` for `benchmarks/manifest.json`.

- [ ] **Step 4: Run the complete regression suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus every new foundation test pass; no existing or new test is skipped or removed to obtain a green run.

- [ ] **Step 5: Inspect the diff for accidental scope expansion**

Run:

```powershell
git diff --check
git status --short
git diff --stat
```

Expected:

- no whitespace errors;
- changes are limited to the File Map in this plan;
- `translator.py`, `cli.py`, `gui.py`, existing detector modules, and current adapter implementations are unchanged;
- no generated database, credential, screenshot, game asset, `__pycache__`, or temporary file is staged.

- [ ] **Step 6: Review public type consistency**

Manually verify:

- adapter `Operation` contains exactly six contract operations;
- HanGuard `RouteOperation` is the larger policy set; `adapter_operations_for_route()` is the only explicit six-entry bridge and no implicit enum conversion exists;
- every non-complete `EvaluationStatus` has a distinct serialized value and decision reason while failing closed to at least H2;
- every persisted model has matching `to_dict()`/`from_dict()` behavior;
- every project-owned row rejects a different project ID;
- provisional routes cannot authorize extraction or write-related work;
- final H2/H3 routes never authorize build, install or rollback;
- contract models use `SegmentDraft` for extraction and `Segment` for core/persisted work;
- event data rejects sensitive keys and never exposes exception objects or tracebacks.
- artifact events use exactly `data={"artifact": artifact.to_dict()}` and round-trip through `Artifact.from_dict()`.

- [ ] **Step 7: Commit Task 9**

Immediately before staging, rerun:

```powershell
python -m unittest discover -s tests -v
```

Expected: the frozen 146-test post-Phase 0 baseline plus every foundation test pass, with no skipped tests.

```powershell
git add README.md
git commit -m "docs: describe HanEngine foundation status"
```

---

## Completion Gate

The first implementation cycle is complete only when all of the following are true:

- deterministic benchmark manifests exist for all fixed datasets;
- all 80 HanGuard risk cases pass;
- the adapter v1 contract harness runs against a concrete fake adapter;
- `Segment`, `RoutePlan`, `HanTask`, `HanStore`, and `HanCore` have executable tests and stable serialization;
- HanCore blocks every step not authorized by the supplied route;
- two project databases cannot read or overwrite each other's records;
- task events are ordered, live-consumable, cancellable, retryable, and free of restricted data;
- adapter-emitted progress uses the same TaskContext and monotonic task-wide event sequence as runner events;
- Python compilation succeeds;
- the frozen 146-test post-Phase 0 baseline and all added foundation tests pass together, and the original 99 application tests within that baseline do not regress;
- no existing or new test is skipped to obtain a green run;
- benchmark JSON is canonical UTF-8 without BOM, uses LF bytes on every host, `git check-attr` reports `text: set` and `eol: lf`, and `--check` compares bytes without writing;
- no OCR, Ren'Py writeback, cloud translation, backup/rollback, packaged-game modification or GUI code has entered this cycle.

The next plan may begin with the approved implementation sequence step 3: migrate the existing plaintext translator, encoding support, scanner and detection adapters behind these new contracts while preserving behavior.
