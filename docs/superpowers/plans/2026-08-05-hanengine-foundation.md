# HanEngine Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 HanEngine 首个实施周期：先锁定基准资产清单、HanGuard 风险样本与适配器契约测试骨架，再建立无 GUI 的 `HanCore`、`Segment`、`RoutePlan`、`HanTask` 和 `HanStore`，同时保证现有 99 项测试不退化。

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

## Scope Boundary

本计划交付“可测试、可持久化、可编排但还不能真正修改游戏”的 HanEngine 基础层。完成后能够：验证固定基准清单；根据合成信号生成两阶段风险路线；表达并运行可取消、可重试的后台任务；按项目隔离保存文本段、路线、任务、事件和产物；由 `HanCore` 拒绝未经路线授权的步骤。真正的明文能力迁移、Ren'Py 适配、视觉替换、翻译路由和 GUI 分别由后续计划实现。

## File Map

- Create `benchmarks/README.md`: 基准资产来源、生成方式、许可边界和本周期仅提交清单的说明。
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
- Create: `benchmarks/README.md`
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

    def test_generator_is_deterministic_and_check_mode_is_clean(self):
        completed = subprocess.run(
            [sys.executable, "tools/generate_benchmark_manifests.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


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
```

Generation rules:

- Static cases are the full `4 × 5 × 3 × 2 = 120` Cartesian product. IDs are `static-001` through `static-120`.
- Dynamic cases are 15 cases for each `DYNAMIC_KINDS` value, each with `frame_count: 30`. IDs are `dynamic-001` through `dynamic-060`.
- Player source language uses a deterministic 80/20 split: the first four cases in each block of five are `en`, the fifth is `ja`.
- Translation slots are `gold-001` through `gold-300`: first 180 `dialogue`, next 60 `menu_ui`, last 60 `system`; within each block, four of every five are `en` and the fifth is `ja`.
- Guard cases are `guard-h0-01..16`, `guard-h1-01..16`, `guard-h2-01..16`, `guard-h3-01..16`, and `guard-edge-01..16`.
- Every guard case contains `project_id`, `user_baseline`, `adapter_baseline`, `available_operations`, `rules`, `signals`, `provisional_evidence_complete`, and `final_evidence_complete`. Every rule uses the exact `HanGuardRule.to_dict()` shape and every signal contains `signal_type`, `value`, `source`, and `evidence`.
- H0 expected operations are all `ROUTE_OPERATIONS`; H1 excludes no read/build/install/visual operation in this foundation; H2 allows only `detect`, `capture`, `ocr`, and `visual_replace`; H3 allows those four unless a case contains `overlay_forbidden` or `capture_black_frame`, in which case only `detect` is allowed.
- Edge cases cover four conflicts, four missing-evidence cases, four unknown-rule cases, and four evaluation-error cases. Missing, unknown, and evaluation-error cases expect `H2_RESTRICTED`; conflicts expect the highest matched level.
- `--check` renders each payload in memory and compares exact UTF-8 text with committed output without writing.

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

- all content is repository-owned synthetic metadata under CC0-1.0;
- no commercial game files, screenshots or translated text are included;
- this cycle commits only manifests and risk snapshots;
- future Ren'Py, screenshot, dynamic and human-reference assets must match the committed IDs;
- regeneration and verification commands are `python tools/generate_benchmark_manifests.py` and `python tools/generate_benchmark_manifests.py --check`.

- [ ] **Step 5: Add the reusable adapter contract test harness**

Create `tests/adapter_contract_v1.py` with a non-discovered mixin exposing these exact hooks:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
import unittest
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

    def test_contract_metadata_is_valid(self):
        adapter = self.make_adapter()
        self.assertEqual(adapter.metadata.contract_version, "hanengine.adapter/v1")
        self.assertTrue(adapter.metadata.adapter_id)
        self.assertTrue(adapter.metadata.capabilities)

    def test_detect_is_deterministic(self):
        adapter = self.make_adapter()
        request = self.make_detection_request()
        self.assertEqual(adapter.detect(request), adapter.detect(request))

    def test_unmatched_detection_has_no_evidence(self):
        result = self.make_adapter().detect(self.make_detection_request())
        if not result.matched:
            self.assertEqual(result.evidence, ())

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


class AdapterV1ContractCase(AdapterV1ContractMixin, unittest.TestCase):
    __unittest_skip__ = True
    __unittest_skip_why__ = "abstract adapter contract harness"
```

The concrete test in Task 6 will subclass the mixin directly and therefore will not inherit the skipped base class.

- [ ] **Step 6: Run the benchmark checks**

Run:

```powershell
python -m unittest tests.test_benchmark_manifests -v
python tools/generate_benchmark_manifests.py --check
```

Expected: all benchmark tests pass; `--check` exits 0 and writes nothing.

- [ ] **Step 7: Commit Task 1**

```powershell
git add benchmarks tools/generate_benchmark_manifests.py tests/test_benchmark_manifests.py tests/adapter_contract_v1.py
git commit -m "test: lock HanEngine benchmark manifests"
```

---

### Task 2: Add Stable Segment and Source Location Models

**Files:**
- Create: `game_localizer/hanengine/__init__.py`
- Create: `game_localizer/hanengine/segments.py`
- Create: `tests/test_hanengine_segments.py`

**Interfaces:**
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
        for path in ("C:/game/script.rpy", "../script.rpy"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                SourceLocation(relative_path=path)

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

- Normalize relative paths to forward slashes, reject absolute paths and any `..` component.
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
            evidence_complete=True,
        )
        self.assertEqual(plan.phase, RoutePhase.PROVISIONAL)
        self.assertEqual(plan.allowed_operations, frozenset({RouteOperation.DETECT}))

    def test_final_route_never_lowers_provisional_risk(self):
        provisional = self.guard.evaluate_provisional(
            "project-a", RiskLevel.H2_RESTRICTED, (), evidence_complete=True
        )
        final = self.guard.evaluate_final(
            provisional,
            adapter_baseline=RiskLevel.H0_PROJECT,
            signals=(),
            available_operations=frozenset(RouteOperation),
            evidence_complete=True,
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
            "project-a", RiskLevel.H1_OFFLINE, (signal,), evidence_complete=True
        )
        self.assertEqual(provisional.risk_after, RiskLevel.H3_PROTECTED)
        self.assertEqual(provisional.matches[0].actual_signal, "KnownAC.EXE")

    def test_final_route_intersects_actual_available_capabilities(self):
        provisional = self.guard.evaluate_provisional(
            "project-a", RiskLevel.H0_PROJECT, (), evidence_complete=True
        )
        final = self.guard.evaluate_final(
            provisional,
            adapter_baseline=RiskLevel.H0_PROJECT,
            signals=(),
            available_operations=frozenset(
                {RouteOperation.DETECT, RouteOperation.EXTRACT}
            ),
            evidence_complete=True,
        )
        self.assertEqual(
            final.allowed_operations,
            frozenset({RouteOperation.DETECT, RouteOperation.EXTRACT}),
        )

    def test_missing_or_failed_evidence_defaults_to_h2(self):
        for complete in (False,):
            plan = self.guard.evaluate_provisional(
                "project-a", RiskLevel.H0_PROJECT, (), evidence_complete=complete
            )
            self.assertEqual(plan.risk_after, RiskLevel.H2_RESTRICTED)
            self.assertTrue(plan.unknown_evidence)

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
                    evidence_complete=case["provisional_evidence_complete"],
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
                    evidence_complete=case["final_evidence_complete"],
                )
                self.assertEqual(plan.risk_after.name, case["expected_risk"])
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
        evidence_complete: bool,
    ) -> RoutePlan: ...

    def evaluate_final(
        self,
        provisional: RoutePlan,
        adapter_baseline: RiskLevel | None,
        signals: Iterable[RiskSignal],
        *,
        available_operations: frozenset[RouteOperation],
        evidence_complete: bool,
    ) -> RoutePlan: ...
```

Policy implementation:

- Case-fold both rule `match_value` and signal `value`; require exact normalized equality and matching `SignalType`.
- Risk equals the maximum of the incoming baseline, every rule minimum, and `H2_RESTRICTED` when evidence is incomplete, the baseline is absent, a rule ID is unknown, or evaluation is marked failed by a benchmark case.
- Final permissions are `risk_base_operations ∩ available_operations`, followed by rule-block subtraction. The available-capability set may remove capabilities but can never add an operation forbidden by risk policy.
- Provisional routes always have only `DETECT` allowed, even for H0/H1.
- Final H0 and H1 base sets contain all operations; final H2 contains `DETECT`, `CAPTURE`, `OCR`, `VISUAL_REPLACE`; final H3 uses the same safe external set but capture-black-frame or overlay-forbidden rules block `CAPTURE`, `OCR`, and `VISUAL_REPLACE`, leaving only `DETECT`.
- `blocked_operations` is always the exact complement of `allowed_operations` within the complete `RouteOperation` enum.
- `evaluate_final` rejects a non-provisional input and preserves `max(provisional.risk_after, adapter_baseline, matched risks)`.
- `H3_PROTECTED` is terminal for the current evaluation; no configuration parameter exists to force a lower result.

- [ ] **Step 5: Run routing and benchmark tests**

Run:

```powershell
python -m unittest tests.test_hanguard_routing tests.test_benchmark_manifests -v
```

Expected: all tests pass, including all 80 risk cases.

- [ ] **Step 6: Commit Task 3**

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

Also assert that `Artifact(relative_path="../escape.json", ...)` raises `ValueError`, and that sequence `0` is rejected.

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
    kind: str
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
- Normalize and validate artifact relative paths using the same no-absolute/no-`..` rule as `SourceLocation`.
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

The handler API used in tests must be:

```python
def handler(context: TaskContext) -> StepResult:
    context.progress(1, 2, current_item="game/script.rpy")
    artifact = Artifact(
        artifact_id="artifact-1",
        task_id=context.task_id,
        step_id=context.step_id,
        kind="report",
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


class TaskContext:
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

- [ ] **Step 5: Run task tests**

Run:

```powershell
python -m unittest tests.test_hantask_models tests.test_hantask_runner -v
```

Expected: all HanTask tests pass without a thread left alive.

- [ ] **Step 6: Commit Task 5**

```powershell
git add game_localizer/hanengine/tasks.py game_localizer/hanengine/__init__.py tests/test_hantask_runner.py
git commit -m "feat: add headless HanTask runner"
```

---

### Task 6: Materialize the Adapter v1 Contract

**Files:**
- Create: `game_localizer/adapters/contract.py`
- Create: `tests/test_adapter_contract.py`

**Interfaces:**
- Contract identifier: `hanengine.adapter/v1`.
- `AdapterV1` is a `typing.Protocol`; this task does not replace the existing `EngineAdapter` ABC.
- All failures are returned as `AdapterError`; concrete methods do not expose raw exceptions across the adapter boundary.
- Contract `Operation` remains the six adapter operations and is intentionally separate from the larger HanGuard `RouteOperation` set.

- [ ] **Step 1: Write failing contract model and harness tests**

Create `tests/test_adapter_contract.py` with:

- metadata version, semantic adapter version, nonempty version/platform declarations, and maturity/capability consistency tests;
- `Evidence.weight` range and matched-result evidence requirements;
- `AdapterError` code/operation/recoverability and JSON-details tests;
- request path and project ID validation;
- a minimal `FakeAdapter` implementing `AdapterV1.detect`;
- a concrete `AdapterContractTests(AdapterV1ContractMixin, unittest.TestCase)` that implements `make_adapter()` and `make_detection_request()` and runs all five shared detect-only tests from Task 1.

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


class ArtifactKind(str, Enum):
    PATCH = "patch"
    MANIFEST = "manifest"
    BACKUP = "backup"
    REPORT = "report"
    UNTRANSLATED_LIST = "untranslated_list"


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
    source: str
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
- Error details use the same JSON/sensitive-key validation as task events.

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
    cancellation_token: TaskControl
    event_sink: EventSink

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
    cancellation_token: TaskControl
    event_sink: EventSink

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
    cancellation_token: TaskControl
    event_sink: EventSink

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
    cancellation_token: TaskControl
    event_sink: EventSink

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
    cancellation_token: TaskControl
    event_sink: EventSink

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
    cancellation_token: TaskControl
    event_sink: EventSink

@dataclass(frozen=True)
class RollbackResult:
    restored_files: tuple[str, ...]
    unchanged_files: tuple[str, ...]
    failed_files: tuple[str, ...]
    hash_verification_passed: bool
    issues: tuple[ValidationIssue, ...]
```

Use `Artifact` from `game_localizer.hanengine.tasks`, `Segment`/`SegmentDraft`/`SourceLocation` from `segments.py`, and routing risk from `routing.py`. Every path list is relative and normalized; request roots are resolved absolute paths and must be distinct where the contract requires it.

- [ ] **Step 4: Add the `AdapterV1` protocol**

```python
AdapterOutcome = TypeVar("AdapterOutcome")


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
python -m unittest tests.test_adapter_contract tests.test_hanengine_segments tests.test_hanguard_routing tests.test_hantask_models -v
```

Expected: all tests pass; the concrete fake adapter executes the shared contract mixin.

- [ ] **Step 6: Commit Task 6**

```powershell
git add game_localizer/adapters/contract.py tests/test_adapter_contract.py
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
- route, task, step, event, artifact, and checkpoint round trips;
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


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    task_id: str
    step_id: str
    sequence: int
    payload: dict[str, JsonValue]


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
    def close(self) -> None: ...
    def __enter__(self) -> "ProjectStore": ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...
```

Every write validates that model `project_id` or owning task belongs to `self.project_id`. A mismatch raises `ValueError` before starting a transaction. Do not add project deletion, backup retention, global translation memory, terms, or secret storage in this cycle.

- [ ] **Step 5: Run storage and model tests**

Run:

```powershell
python -m unittest tests.test_hanstore tests.test_hanengine_segments tests.test_hanguard_routing tests.test_hantask_models -v
```

Expected: all tests pass and temporary databases are removed when the test context exits.

- [ ] **Step 6: Commit Task 7**

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
- handlers cannot bypass HanGuard by emitting an artifact for a blocked operation.

The route enforcement test must call:

```python
with self.assertRaisesRegex(RouteBlockedError, "extract"):
    core.create_task(
        kind="extract",
        route=provisional_route,
        steps=(TaskStep("extract", "Extract text", RouteOperation.EXTRACT),),
    )
```

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
- Generate UUIDv4 task IDs when absent.
- Ingest drafts into memory first, detect conflicts, then call one transactional `save_segments`; never partially persist a conflicting batch.
- Deduplicate by `(project_id, segment_id)` only when `source_fingerprint` is identical.

- [ ] **Step 4: Persist runner events and artifacts**

In `run_task`, construct the runner with a sink that:

1. appends the event to `ProjectStore`;
2. when `event_type is ARTIFACT`, reconstructs the referenced artifact from structured event data and saves it;
3. updates the task row after every terminal step event and after the terminal task event.

Do not catch `KeyboardInterrupt` or `SystemExit`. Convert ordinary unexpected orchestration errors into a failed task event only after route and project-boundary validation has passed.

- [ ] **Step 5: Run the HanCore end-to-end tests**

Run:

```powershell
python -m unittest tests.test_hancore tests.test_hanstore tests.test_hantask_runner -v
```

Expected: all headless orchestration, storage and runner tests pass.

- [ ] **Step 6: Commit Task 8**

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
```

Expected: command exits 0 and `git status --short` remains unchanged.

- [ ] **Step 4: Run the complete regression suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: the original 99 tests plus every new foundation test pass; no existing test is skipped or removed to obtain a green run.

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
- HanGuard `RouteOperation` is the larger policy set and no implicit enum conversion exists;
- every persisted model has matching `to_dict()`/`from_dict()` behavior;
- every project-owned row rejects a different project ID;
- provisional routes cannot authorize extraction or write-related work;
- final H2/H3 routes never authorize build, install or rollback;
- contract models use `SegmentDraft` for extraction and `Segment` for core/persisted work;
- event data rejects sensitive keys and never exposes exception objects or tracebacks.

- [ ] **Step 7: Commit Task 9**

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
- Python compilation succeeds;
- the original 99 tests and all added tests pass together;
- no OCR, Ren'Py writeback, cloud translation, backup/rollback, packaged-game modification or GUI code has entered this cycle.

The next plan may begin with the approved implementation sequence step 3: migrate the existing plaintext translator, encoding support, scanner and detection adapters behind these new contracts while preserving behavior.
