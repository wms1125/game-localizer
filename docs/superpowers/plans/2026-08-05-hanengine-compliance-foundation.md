# HanEngine Compliance Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不替项目选择根许可证、不引入第三方依赖的前提下，建立 HanEngine 的来源台账、洁净室边界、恢复材料禁入检查、第三方组件清单和确定性 SPDX SBOM 基础。

**Architecture:** 使用 Python 3.11 标准库实现只读合规检查器和确定性 SBOM 生成器。机器可读 JSON 是唯一结构化事实源，Markdown 只解释政策；普通审计允许项目许可证保持 `UNDECIDED`，发布审计必须阻断，第三方组件缺少来源、哈希或许可证时任何模式都阻断。

**Tech Stack:** Python 3.11 标准库、`dataclasses`、`argparse`、`json`、`pathlib`、`re`、`unittest`、GitHub Actions。

## Global Constraints

- 不创建或选择根 `LICENSE`；`license_status` 固定为 `UNDECIDED`，`license_spdx` 固定为 `NOASSERTION`，直到用户另行书面选择。
- 普通审计在没有根许可证时返回警告并成功；`--release` 审计必须返回错误并以非零状态退出。
- 不复制、导入、执行或提交 RenpyThief 恢复包的伪代码、脚本、二进制、模型、UI 资源或安装树。
- 恢复包只作为仓库外的受限静态研究材料登记；实现代码只能依据 HanEngine 规格、官方公开文档和仓库自有合成夹具。
- 不增加第三方 Python 依赖，不发起网络请求，不扫描或修改仓库外路径。
- 检查器只读；除了显式 SBOM 生成命令，任何检查不得创建、修改或删除文件。
- JSON 使用 UTF-8、`ensure_ascii=False`、`allow_nan=False`、`sort_keys=True`、`indent=2` 和末尾换行。
- 所有生产行为先写失败测试并观察正确失败，再写最小实现。
- 现有 99 项测试不得删除、跳过或修改来获得绿灯。
- 本计划只建立合规基础，不实现 HanEngine Foundation、OCR、注入、Hook、Ren'Py 写回、在线翻译或 GUI。

---

## File Map

- Create `compliance/provenance.json`: 项目、许可证状态、受限研究材料和允许实现来源的机器台账。
- Create `compliance/third_party_components.json`: 第三方组件清单；初始为空数组。
- Create `docs/compliance/CLEAN_ROOM_POLICY.md`: 分析与实现隔离、禁止复制项和 PR 来源声明。
- Create `PROVENANCE.md`: 人类可读来源摘要和维护流程。
- Create `THIRD_PARTY_NOTICES.md`: 当前第三方再分发状态与未来条目模板。
- Create `tools/check_compliance.py`: 只读审计、恢复材料禁入和发布许可证门禁。
- Create `tests/test_compliance.py`: 合规检查器 TDD 覆盖。
- Create `tools/generate_sbom.py`: 从机器台账确定性生成 SPDX 2.3 JSON。
- Create `compliance/sbom.spdx.json`: 提交的当前 SBOM 快照。
- Create `tests/test_sbom.py`: SBOM schema、确定性和 `--check` 测试。
- Create `.github/workflows/compliance.yml`: 在 Windows/Python 3.11 上运行普通合规审计、SBOM 漂移检查和测试。

---

### Task 1: Add Provenance, Clean-Room Policy, and Compliance Gate

**Files:**
- Create: `compliance/provenance.json`
- Create: `compliance/third_party_components.json`
- Create: `docs/compliance/CLEAN_ROOM_POLICY.md`
- Create: `PROVENANCE.md`
- Create: `THIRD_PARTY_NOTICES.md`
- Create: `tools/check_compliance.py`
- Create: `tests/test_compliance.py`

**Interfaces:**
- `tools.check_compliance.check_repository(root: Path, *, release: bool = False) -> ComplianceReport`
- `ComplianceFinding(code: str, severity: str, message: str, path: str | None = None)`
- `ComplianceReport(findings: tuple[ComplianceFinding, ...])` exposes `ok`, `errors`, `warnings`, and `to_dict()`.
- CLI: `python tools/check_compliance.py [--root PATH] [--release] [--json]`; exit `0` only when `report.ok` is true.
- Machine contracts: `hanengine.provenance/v1` and `hanengine.third-party/v1`.

- [ ] **Step 1: Write the failing compliance tests**

Create `tests/test_compliance.py` with a temporary-repository helper that writes the five required policy/manifest files. Cover these behaviors with real files:

```python
class ComplianceTests(unittest.TestCase):
    def test_repository_audit_is_clean_except_for_undecided_license(self):
        report = check_repository(ROOT)
        self.assertTrue(report.ok)
        self.assertEqual([item.code for item in report.warnings], ["PROJECT_LICENSE_UNDECIDED"])

    def test_release_mode_blocks_missing_root_license(self):
        root = self.make_repository()
        report = check_repository(root, release=True)
        self.assertFalse(report.ok)
        self.assertIn("PROJECT_LICENSE_REQUIRED", [item.code for item in report.errors])

    def test_forbidden_recovery_tree_is_blocked(self):
        root = self.make_repository()
        forbidden = root / "recovered-source" / "embedded-scripts" / "renpythief.rpy"
        forbidden.parent.mkdir(parents=True)
        forbidden.write_text("restricted", encoding="utf-8")
        report = check_repository(root)
        self.assertIn("RESTRICTED_MATERIAL_TRACKED", [item.code for item in report.errors])

    def test_third_party_component_requires_locked_source_hash_and_license(self):
        root = self.make_repository(components=[{"name": "Example"}])
        report = check_repository(root)
        self.assertIn("THIRD_PARTY_METADATA_INVALID", [item.code for item in report.errors])
```

Also test missing/invalid JSON, wrong contracts, exact finding serialization, CLI JSON output, audit exit `0`, release exit `1`, and that checks leave the tree byte-for-byte unchanged.

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run:

```powershell
python -m unittest tests.test_compliance -v
```

Expected: FAIL because `tools.check_compliance` does not exist.

- [ ] **Step 3: Add the machine-readable manifests**

Create `compliance/provenance.json` with these exact top-level fields:

```json
{
  "contract": "hanengine.provenance/v1",
  "project": {
    "license_spdx": "NOASSERTION",
    "license_status": "UNDECIDED",
    "name": "HanEngine",
    "repository": "https://github.com/wms1125/game-localizer",
    "version": "0.0.0-foundation"
  },
  "restricted_reference_material": [
    {
      "name": "RenpyThief 6.7.7 authorized recovery package",
      "purpose": "static architecture analysis only",
      "repository_inclusion": "FORBIDDEN",
      "sha256": "2DF39E113C8CA2401749A2F985E00EB96F1FA2BC5FB82F47F77A3747EF67767A"
    }
  ],
  "implementation_sources": [
    {
      "kind": "project_owned",
      "scope": "game_localizer/** and repository-owned synthetic fixtures"
    },
    {
      "kind": "official_documentation",
      "scope": "documented per implementation change"
    }
  ]
}
```

Create `compliance/third_party_components.json`:

```json
{
  "components": [],
  "contract": "hanengine.third-party/v1"
}
```

- [ ] **Step 4: Implement the minimal read-only checker**

Create `tools/check_compliance.py` with frozen dataclasses and these constants:

```python
PROVENANCE_CONTRACT = "hanengine.provenance/v1"
THIRD_PARTY_CONTRACT = "hanengine.third-party/v1"
LICENSE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "COPYING.txt", "COPYING.md")
FORBIDDEN_PATH_SEGMENTS = frozenset({
    "decompiled-native", "decompiled-dotnet", "runtime-dump-raw",
    "embedded-scripts", "unpacked", "injector-source", "ghidra-scripts",
})
SKIPPED_PATH_SEGMENTS = frozenset({".git", ".superpowers", "__pycache__"})
COMPONENT_FIELDS = frozenset({
    "name", "version", "source_url", "sha256", "license_spdx", "usage", "redistributed",
})
```

Implementation rules:

- Validate required files, JSON object roots, exact contracts and exact `UNDECIDED`/`NOASSERTION` pairing while no root license exists.
- Walk only `root`; skip directories whose path contains a skipped segment. A file whose relative path contains any forbidden segment yields one `RESTRICTED_MATERIAL_TRACKED` error.
- Every third-party component must be an object containing all `COMPONENT_FIELDS`; `sha256` must be exactly 64 hexadecimal characters; other required string fields must be non-empty; `redistributed` must be boolean.
- A missing root license yields `PROJECT_LICENSE_UNDECIDED` warning in audit mode and `PROJECT_LICENSE_REQUIRED` error in release mode.
- Findings are sorted by `(severity, code, path or "", message)` for deterministic output. Severity values are only `ERROR` and `WARNING`.
- Do not infer a project license from `THIRD_PARTY_NOTICES.md`, benchmark CC0 metadata, dependency licenses or GitHub visibility.

- [ ] **Step 5: Add the human-readable policy documents**

`docs/compliance/CLEAN_ROOM_POLICY.md` must state:

- recovery material is outside the repository and only available to designated observers;
- observers may publish behavior, interface, risk and test requirements, but not recovered identifiers, control flow, strings, UI assets or code;
- implementers use HanEngine specs, official documentation and synthetic fixtures, not recovered files;
- every implementation PR records sources and confirms no restricted material was copied;
- injection, Hook, process-memory and protected-resource routes remain outside the current product boundary.

`PROVENANCE.md` must explain the two JSON contracts, the archive hash as evidence only, audit/release commands and the unresolved root-license gate. `THIRD_PARTY_NOTICES.md` must say no third-party component is currently redistributed by the Python foundation and include a future-entry template with name, version, source, hash, license, copyright, modifications and distribution mode.

- [ ] **Step 6: Run compliance and regression tests**

Run:

```powershell
python -m unittest tests.test_compliance -v
python tools/check_compliance.py --json
python tools/check_compliance.py --release --json
python -m unittest discover -s tests -v
```

Expected: compliance tests and full suite pass; audit exits `0` with one `PROJECT_LICENSE_UNDECIDED` warning; release command exits `1` with `PROJECT_LICENSE_REQUIRED` and is recorded as the expected negative gate.

- [ ] **Step 7: Commit Task 1**

```powershell
git add compliance/provenance.json compliance/third_party_components.json docs/compliance/CLEAN_ROOM_POLICY.md PROVENANCE.md THIRD_PARTY_NOTICES.md tools/check_compliance.py tests/test_compliance.py
git commit -m "feat: add HanEngine compliance gate"
```

---

### Task 2: Generate a Deterministic SPDX SBOM and Add CI Drift Checks

**Files:**
- Create: `tools/generate_sbom.py`
- Create: `compliance/sbom.spdx.json`
- Create: `tests/test_sbom.py`
- Create: `.github/workflows/compliance.yml`

**Interfaces:**
- `tools.generate_sbom.build_sbom(root: Path) -> dict[str, object]`
- `tools.generate_sbom.render_sbom(payload: dict[str, object]) -> str`
- `tools.generate_sbom.write_sbom(root: Path) -> Path`
- `tools.generate_sbom.check_sbom(root: Path) -> bool`
- CLI: `python tools/generate_sbom.py [--root PATH] [--check]`; `--check` never writes.

- [ ] **Step 1: Write the failing SBOM tests**

Create `tests/test_sbom.py` covering:

```python
class SbomTests(unittest.TestCase):
    def test_sbom_is_spdx_23_and_describes_hanengine(self):
        payload = build_sbom(ROOT)
        self.assertEqual(payload["spdxVersion"], "SPDX-2.3")
        self.assertEqual(payload["dataLicense"], "CC0-1.0")
        self.assertEqual(payload["SPDXID"], "SPDXRef-DOCUMENT")
        self.assertEqual(payload["packages"][0]["SPDXID"], "SPDXRef-Package-HanEngine")
        self.assertEqual(payload["packages"][0]["licenseDeclared"], "NOASSERTION")
        self.assertEqual(payload["relationships"], [{
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": "SPDXRef-Package-HanEngine",
        }])

    def test_render_is_deterministic_and_matches_committed_snapshot(self):
        self.assertEqual(render_sbom(build_sbom(ROOT)), render_sbom(build_sbom(ROOT)))
        self.assertTrue(check_sbom(ROOT))
```

Also test conversion of one synthetic third-party component, stable `SPDXRef-ThirdParty-<slug>` identifiers, invalid component rejection, missing provenance rejection, CLI `--check` exit `0`, drift exit `1`, and that `--check` does not write.

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run:

```powershell
python -m unittest tests.test_sbom -v
```

Expected: FAIL because `tools.generate_sbom` does not exist.

- [ ] **Step 3: Implement the minimal SPDX 2.3 generator**

Use the provenance project fields for package name/version/license and these exact document values:

```python
DOCUMENT_NAMESPACE = "https://github.com/wms1125/game-localizer/sbom/hanengine-foundation"
CREATED = "2026-08-05T00:00:00Z"
CREATOR = "Tool: HanEngine compliance foundation"
```

The document contains `spdxVersion`, `dataLicense`, `SPDXID`, `name`, `documentNamespace`, `creationInfo`, `packages`, and `relationships`. HanEngine is the first package with `filesAnalyzed: false`, `downloadLocation: NOASSERTION`, `copyrightText: NOASSERTION`, and the provenance license value for both declared/concluded license. Each third-party component becomes a package using the manifest source URL, version, SHA-256 external reference in `checksums`, declared/concluded SPDX license and `filesAnalyzed: false`; add a `DEPENDS_ON` relationship from HanEngine to each component.

`render_sbom` uses the plan-wide canonical JSON format. `--check` compares exact UTF-8 text with `compliance/sbom.spdx.json` and prints a concise drift message without modifying the file.

- [ ] **Step 4: Generate and verify the committed SBOM**

Run:

```powershell
python tools/generate_sbom.py
python tools/generate_sbom.py --check
```

Expected: the first command creates `compliance/sbom.spdx.json`; the second exits `0` and does not change it.

- [ ] **Step 5: Add the CI workflow**

Create `.github/workflows/compliance.yml` using `windows-latest`, `actions/checkout@v4`, `actions/setup-python@v5` with Python `3.11`, then run exactly:

```powershell
python tools/check_compliance.py --json
python tools/generate_sbom.py --check
python -m unittest tests.test_compliance tests.test_sbom -v
```

Do not run `--release` in ordinary PR CI while the root-license decision is intentionally unresolved; release packaging must invoke it separately and remain blocked.

- [ ] **Step 6: Run Task 2 and full regression gates**

Run:

```powershell
python -m unittest tests.test_compliance tests.test_sbom -v
python tools/check_compliance.py --json
python tools/generate_sbom.py --check
python -m unittest discover -s tests -v
git diff --check
```

Expected: all commands exit `0`; the audit contains only the expected project-license warning; the original 99 tests remain and all added tests pass.

- [ ] **Step 7: Commit Task 2**

```powershell
git add tools/generate_sbom.py compliance/sbom.spdx.json tests/test_sbom.py .github/workflows/compliance.yml
git commit -m "feat: generate HanEngine SPDX SBOM"
```

---

## Completion Gate

阶段 0 的许可中立部分只有在以下条件全部成立时完成：

- 恢复材料路径禁入、第三方元数据和机器台账校验均有可执行测试；
- 普通审计只把缺少根许可证报告为警告，发布审计可靠阻断；
- 没有根 `LICENSE` 被自动创建或推断；
- SPDX 2.3 SBOM 可确定性重建且 `--check` 不写文件；
- CI 检查恢复材料、第三方元数据和 SBOM 漂移；
- Python Foundation 仍为标准库实现，第三方组件清单为空；
- 所有新增测试与原有 99 项测试一起通过；
- 下一阶段开始前，用户仍需单独选择 HanEngine 根许可证，任何第三方代码进入核心前该门禁必须关闭。
