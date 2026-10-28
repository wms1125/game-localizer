# Engine Detection Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only Phase 1 foundation that detects Ren'Py, RPG Maker MV/MZ, Godot, Unity, and Unreal projects with explainable confidence scores while preserving the existing single-file CLI.

**Architecture:** Add a small `game_localizer` package containing immutable detection models, one read-only project snapshot scanner, an adapter interface, an explicit adapter registry, and isolated engine detectors. Route new `detect` and `engines` CLI commands before the legacy positional command so existing users and tests remain compatible.

**Tech Stack:** Python 3.11 standard library, `dataclasses`, `enum`, `pathlib`, `os.scandir`, `argparse`, `json`, and standard-library `unittest`.

## Global Constraints

- Core detection must use only the Python standard library and must not install packages at runtime.
- Phase 1 is read-only: it may print reports but must not modify the selected project directory.
- Do not follow symbolic links, Windows directory junctions, or other filesystem reparse points.
- Do not parse, unpack, decrypt, reverse engineer, or execute project binaries, archives, plugins, or scripts.
- High confidence is 80–100, medium confidence is 50–79, and scores below 50 do not select an engine.
- Multiple high-confidence candidates, or a top-two score difference of 10 or less, must stop automatic selection.
- Every nonzero detection score must include human-readable evidence.
- All Phase 1 adapters report `detect_only` capability and `experimental` maturity until their extraction/write adapters are implemented and tested.
- Preserve `python cli.py <resource> <dictionary>` behavior, exit codes, default outputs, and all current tests.
- Continue using `unittest`; do not introduce pytest.
- Keep processing fully offline and limited to legally owned or explicitly authorized resources.

## Scope Boundary

This plan implements only specification Phase 1: models, read-only scanning, explainable detection, adapter registration, CLI reporting, documentation, and regression coverage. Translation catalogs, automated validation decisions, resource extraction, writeback, backup, rollback, engine SDK invocation, and GUI project mode each require a later implementation plan after this foundation passes review.

## File Map

- Create `game_localizer/__init__.py`: public package exports for detection types and functions.
- Create `game_localizer/models.py`: enums and immutable detection report data classes.
- Create `game_localizer/scanner.py`: read-only directory snapshot with generated-directory filtering and no symlink/reparse traversal.
- Create `game_localizer/detector.py`: candidate ordering and automatic selection policy.
- Create `game_localizer/reporting.py`: human-readable detection formatting.
- Create `game_localizer/adapters/base.py`: adapter protocol and result builder.
- Create `game_localizer/adapters/__init__.py`: explicit built-in adapter registry.
- Create `game_localizer/adapters/renpy.py`: Ren'Py signature scoring.
- Create `game_localizer/adapters/rpgmaker.py`: separate MV and MZ signature scoring.
- Create `game_localizer/adapters/godot.py`: Godot source and PCK signature scoring.
- Create `game_localizer/adapters/unity.py`: Unity source and Windows build signature scoring.
- Create `game_localizer/adapters/unreal.py`: Unreal source and packaged container signature scoring.
- Modify `cli.py`: route `detect` and `engines` commands without changing legacy parsing.
- Modify `README.md`: document detection commands, evidence, maturity, and Phase 1 limitations.
- Create `tests/test_detection_models.py`: model validation and JSON serialization.
- Create `tests/test_project_scanner.py`: safe snapshot behavior.
- Create `tests/test_detector.py`: threshold and conflict resolution.
- Create `tests/test_renpy_adapter.py`: Ren'Py positive and archive-only cases.
- Create `tests/test_rpgmaker_adapter.py`: MV/MZ distinction and false-positive cases.
- Create `tests/test_godot_adapter.py`: source and PCK cases.
- Create `tests/test_unity_adapter.py`: source, packaged, and weak-signal cases.
- Create `tests/test_unreal_adapter.py`: source and packaged cases.
- Create `tests/test_detection_cli.py`: subprocess coverage for new commands and exit codes.

---

### Task 1: Immutable Detection Models

**Files:**
- Create: `game_localizer/__init__.py`
- Create: `game_localizer/models.py`
- Create: `tests/test_detection_models.py`

**Interfaces:**
- Produces: `CapabilityLevel`, `MaturityLevel`, `DetectionStatus`, `DetectionEvidence`, `DetectionResult`, and `DetectionReport`.
- `DetectionResult.to_dict()` and `DetectionReport.to_dict()` return JSON-serializable dictionaries used by Task 5.
- No filesystem or adapter dependencies are allowed in this task.

- [ ] **Step 1: Write failing model tests**

Create `tests/test_detection_models.py` with these tests:

```python
import unittest
from pathlib import Path

from game_localizer.models import (
    CapabilityLevel,
    DetectionEvidence,
    DetectionReport,
    DetectionResult,
    DetectionStatus,
    MaturityLevel,
)


class DetectionModelTests(unittest.TestCase):
    def make_result(self, score: int = 90) -> DetectionResult:
        return DetectionResult(
            engine_id="renpy",
            display_name="Ren'Py",
            score=score,
            capability=CapabilityLevel.DETECT_ONLY,
            maturity=MaturityLevel.EXPERIMENTAL,
            evidence=(
                DetectionEvidence(
                    code="renpy_scripts",
                    path="game/script.rpy",
                    description="发现 Ren'Py 源脚本",
                    weight=65,
                ),
            ),
            warnings=("阶段一仅提供只读检测",),
        )

    def test_detection_result_rejects_score_outside_range(self):
        with self.assertRaisesRegex(ValueError, "0 到 100"):
            self.make_result(101)

    def test_detection_result_requires_evidence_for_positive_score(self):
        with self.assertRaisesRegex(ValueError, "检测证据"):
            DetectionResult(
                engine_id="unknown",
                display_name="Unknown",
                score=1,
                capability=CapabilityLevel.DETECT_ONLY,
                maturity=MaturityLevel.EXPERIMENTAL,
                evidence=(),
            )

    def test_report_serializes_enums_paths_and_nested_results(self):
        report = DetectionReport(
            root=Path("C:/games/example"),
            status=DetectionStatus.AUTO_SELECTED,
            selected_engine="renpy",
            candidates=(self.make_result(),),
        )

        payload = report.to_dict()

        self.assertEqual(payload["status"], "auto_selected")
        self.assertEqual(payload["selected_engine"], "renpy")
        self.assertEqual(payload["candidates"][0]["capability"], "detect_only")
        self.assertEqual(payload["candidates"][0]["evidence"][0]["weight"], 65)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the model tests and verify the import failure**

Run:

```powershell
python -m unittest tests.test_detection_models -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'game_localizer'`.

- [ ] **Step 3: Implement the model module**

Create `game_localizer/models.py` with this complete API:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class CapabilityLevel(str, Enum):
    FULL = "full"
    ASSISTED = "assisted"
    DETECT_ONLY = "detect_only"
    UNSUPPORTED = "unsupported"


class MaturityLevel(str, Enum):
    EXPERIMENTAL = "experimental"
    BETA = "beta"
    STABLE = "stable"


class DetectionStatus(str, Enum):
    AUTO_SELECTED = "auto_selected"
    STOPPED_UNCERTAIN = "stopped_uncertain"
    STOPPED_CONFLICT = "stopped_conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DetectionEvidence:
    code: str
    path: str
    description: str
    weight: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "description": self.description,
            "weight": self.weight,
        }


@dataclass(frozen=True)
class DetectionResult:
    engine_id: str
    display_name: str
    score: int
    capability: CapabilityLevel
    maturity: MaturityLevel
    evidence: tuple[DetectionEvidence, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("检测分数必须位于 0 到 100")
        if self.score > 0 and not self.evidence:
            raise ValueError("非零检测分数必须包含检测证据")

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "display_name": self.display_name,
            "score": self.score,
            "capability": self.capability.value,
            "maturity": self.maturity.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class DetectionReport:
    root: Path
    status: DetectionStatus
    selected_engine: str | None
    candidates: tuple[DetectionResult, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "status": self.status.value,
            "selected_engine": self.selected_engine,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "warnings": list(self.warnings),
        }
```

Create `game_localizer/__init__.py`:

```python
from .models import (
    CapabilityLevel,
    DetectionEvidence,
    DetectionReport,
    DetectionResult,
    DetectionStatus,
    MaturityLevel,
)

__all__ = [
    "CapabilityLevel",
    "DetectionEvidence",
    "DetectionReport",
    "DetectionResult",
    "DetectionStatus",
    "MaturityLevel",
]
```

- [ ] **Step 4: Run the model tests**

Run:

```powershell
python -m unittest tests.test_detection_models -v
```

Expected: 3 tests pass and the command exits with code 0.

- [ ] **Step 5: Commit Task 1**

```powershell
git add game_localizer/__init__.py game_localizer/models.py tests/test_detection_models.py
git commit -m "feat: add engine detection models"
```

---

### Task 2: Safe Project Snapshot and Detection Resolution

**Files:**
- Create: `game_localizer/scanner.py`
- Create: `game_localizer/detector.py`
- Create: `game_localizer/adapters/base.py`
- Create: `game_localizer/adapters/__init__.py`
- Create: `tests/test_project_scanner.py`
- Create: `tests/test_detector.py`

**Interfaces:**
- Consumes: Task 1 model classes.
- Produces: `ProjectSnapshot`, `ProjectScanError`, `scan_project(root)`, `EngineAdapter`, `resolve_detection(root, candidates)`, and `detect_project(root, adapters=None)`.
- Later adapters consume `ProjectSnapshot.has_file`, `has_dir`, `files_named`, `files_with_suffix`, `root_files_with_suffix`, and `root_dirs_with_suffix`.
- `detect_project` lazily imports the registry only when `adapters` is omitted, preventing import cycles.

- [ ] **Step 1: Write failing scanner tests**

Create `tests/test_project_scanner.py`:

```python
import os
import tempfile
import unittest
from pathlib import Path

from game_localizer.scanner import ProjectScanError, scan_project


class ProjectScannerTests(unittest.TestCase):
    def test_snapshot_normalizes_paths_and_skips_generated_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Game").mkdir()
            (root / "Game" / "Script.RPY").write_text("label start:", encoding="utf-8")
            (root / "Library").mkdir()
            (root / "Library" / "secret.asset").write_bytes(b"binary")

            snapshot = scan_project(root)

            self.assertTrue(snapshot.has_dir("game"))
            self.assertTrue(snapshot.has_file("game/script.rpy"))
            self.assertFalse(snapshot.has_file("library/secret.asset"))
            self.assertIn("library", snapshot.ignored_directories)

    def test_snapshot_does_not_follow_directory_symlinks(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            target = Path(outside)
            (target / "outside.rpy").write_text("label outside:", encoding="utf-8")
            link = root / "linked"
            try:
                os.symlink(target, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("当前环境不允许创建目录符号链接")

            snapshot = scan_project(root)

            self.assertFalse(snapshot.has_file("linked/outside.rpy"))
            self.assertIn("linked", snapshot.ignored_directories)

    def test_scan_rejects_non_directory_input(self):
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "game.exe"
            file_path.write_bytes(b"not a directory")

            with self.assertRaisesRegex(ProjectScanError, "项目目录"):
                scan_project(file_path)
```

- [ ] **Step 2: Write failing detection policy tests**

Create `tests/test_detector.py`:

```python
import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.base import EngineAdapter
from game_localizer.detector import detect_project, resolve_detection
from game_localizer.models import (
    CapabilityLevel,
    DetectionEvidence,
    DetectionResult,
    DetectionStatus,
    MaturityLevel,
)
from game_localizer.scanner import ProjectSnapshot


class FixedAdapter(EngineAdapter):
    display_name = "Fixed"
    maturity = MaturityLevel.EXPERIMENTAL

    def __init__(self, engine_id: str, score: int):
        self.engine_id = engine_id
        self.score = score

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        if self.score == 0:
            return None
        return self.build_result(
            evidence=(
                DetectionEvidence(
                    code=f"{self.engine_id}_signal",
                    path="signal.file",
                    description=f"{self.engine_id} signal",
                    weight=self.score,
                ),
            )
        )


class DetectorTests(unittest.TestCase):
    def test_auto_selects_single_high_confidence_candidate(self):
        report = resolve_detection(
            Path("C:/game"),
            (FixedAdapter("first", 91).detect(self.empty_snapshot()),),
        )
        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "first")

    def test_stops_when_top_candidates_are_within_ten_points(self):
        candidates = tuple(
            adapter.detect(self.empty_snapshot())
            for adapter in (FixedAdapter("first", 90), FixedAdapter("second", 82))
        )
        report = resolve_detection(Path("C:/game"), candidates)
        self.assertEqual(report.status, DetectionStatus.STOPPED_CONFLICT)
        self.assertIsNone(report.selected_engine)

    def test_stops_on_medium_confidence_and_marks_low_confidence_unknown(self):
        medium = resolve_detection(
            Path("C:/game"),
            (FixedAdapter("medium", 70).detect(self.empty_snapshot()),),
        )
        low = resolve_detection(
            Path("C:/game"),
            (FixedAdapter("low", 40).detect(self.empty_snapshot()),),
        )
        self.assertEqual(medium.status, DetectionStatus.STOPPED_UNCERTAIN)
        self.assertEqual(low.status, DetectionStatus.UNKNOWN)

    def test_detect_project_scans_once_and_uses_injected_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            report = detect_project(directory, adapters=(FixedAdapter("fixed", 90),))
        self.assertEqual(report.selected_engine, "fixed")

    def test_detect_project_does_not_modify_project_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signal = root / "signal.file"
            signal.write_bytes(b"unchanged")
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            detect_project(root, adapters=(FixedAdapter("fixed", 90),))

            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
        self.assertEqual(after, before)

    @staticmethod
    def empty_snapshot() -> ProjectSnapshot:
        return ProjectSnapshot(
            root=Path("C:/game"),
            files=frozenset(),
            directories=frozenset(),
            ignored_directories=frozenset(),
        )
```

- [ ] **Step 3: Run the new tests and verify missing-module failures**

Run:

```powershell
python -m unittest tests.test_project_scanner tests.test_detector -v
```

Expected: FAIL because `game_localizer.scanner`, `game_localizer.detector`, and `game_localizer.adapters.base` do not exist.

- [ ] **Step 4: Implement the read-only scanner**

Create `game_localizer/scanner.py` with these exact public methods and safety rules:

```python
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat


DEFAULT_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "binaries",
        "deriveddatacache",
        "intermediate",
        "library",
        "localized-output",
        "obj",
        "temp",
    }
)


class ProjectScanError(ValueError):
    pass


def _normalize(relative_path: Path | str) -> str:
    return Path(relative_path).as_posix().strip("/").casefold()


def _is_reparse_point(entry: os.DirEntry[str]) -> bool:
    try:
        metadata = entry.stat(follow_symlinks=False)
    except OSError as exc:
        raise ProjectScanError(f"无法检查项目路径: {entry.path}: {exc}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return entry.is_symlink() or bool(reparse_flag and attributes & reparse_flag)


@dataclass(frozen=True)
class ProjectSnapshot:
    root: Path
    files: frozenset[str]
    directories: frozenset[str]
    ignored_directories: frozenset[str]

    def has_file(self, relative_path: str) -> bool:
        return _normalize(relative_path) in self.files

    def has_dir(self, relative_path: str) -> bool:
        return _normalize(relative_path) in self.directories

    def files_named(self, name: str) -> tuple[str, ...]:
        expected = name.casefold()
        return tuple(path for path in sorted(self.files) if Path(path).name.casefold() == expected)

    def files_with_suffix(self, suffix: str) -> tuple[str, ...]:
        expected = suffix.casefold()
        return tuple(path for path in sorted(self.files) if path.endswith(expected))

    def root_files_with_suffix(self, suffix: str) -> tuple[str, ...]:
        return tuple(path for path in self.files_with_suffix(suffix) if "/" not in path)

    def root_dirs_with_suffix(self, suffix: str) -> tuple[str, ...]:
        expected = suffix.casefold()
        return tuple(
            path
            for path in sorted(self.directories)
            if "/" not in path and path.endswith(expected)
        )


def scan_project(root: str | Path) -> ProjectSnapshot:
    project_root = Path(root).resolve()
    if not project_root.is_dir():
        raise ProjectScanError(f"项目目录不存在或不是目录: {project_root}")

    files: set[str] = set()
    directories: set[str] = set()
    ignored: set[str] = set()
    pending = [project_root]

    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise ProjectScanError(f"无法扫描项目目录: {current}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = _normalize(path.relative_to(project_root))
            if _is_reparse_point(entry):
                ignored.add(relative)
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    directories.add(relative)
                    if entry.name.casefold() in DEFAULT_IGNORED_DIRS:
                        ignored.add(relative)
                    else:
                        pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.add(relative)
            except OSError as exc:
                raise ProjectScanError(f"无法检查项目路径: {path}: {exc}") from exc

    return ProjectSnapshot(
        root=project_root,
        files=frozenset(files),
        directories=frozenset(directories),
        ignored_directories=frozenset(ignored),
    )
```

- [ ] **Step 5: Implement the adapter base and empty registry**

Create `game_localizer/adapters/base.py`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from game_localizer.models import (
    CapabilityLevel,
    DetectionEvidence,
    DetectionResult,
    MaturityLevel,
)
from game_localizer.scanner import ProjectSnapshot


class EngineAdapter(ABC):
    engine_id: str
    display_name: str
    maturity: MaturityLevel

    @abstractmethod
    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        raise NotImplementedError

    def build_result(
        self,
        evidence: Iterable[DetectionEvidence],
        warnings: Iterable[str] = (),
    ) -> DetectionResult:
        evidence_tuple = tuple(evidence)
        return DetectionResult(
            engine_id=self.engine_id,
            display_name=self.display_name,
            score=min(100, sum(item.weight for item in evidence_tuple)),
            capability=CapabilityLevel.DETECT_ONLY,
            maturity=self.maturity,
            evidence=evidence_tuple,
            warnings=tuple(warnings),
        )
```

Create `game_localizer/adapters/__init__.py` as an explicit registry placeholder used before engine tasks are complete:

```python
from .base import EngineAdapter


def get_adapters() -> tuple[EngineAdapter, ...]:
    return ()


__all__ = ["EngineAdapter", "get_adapters"]
```

- [ ] **Step 6: Implement detection resolution**

Create `game_localizer/detector.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionReport, DetectionResult, DetectionStatus
from game_localizer.scanner import scan_project


def resolve_detection(
    root: Path,
    candidates: Iterable[DetectionResult | None],
) -> DetectionReport:
    ordered = tuple(
        sorted(
            (candidate for candidate in candidates if candidate is not None and candidate.score > 0),
            key=lambda item: (-item.score, item.engine_id),
        )
    )
    if not ordered or ordered[0].score < 50:
        return DetectionReport(root, DetectionStatus.UNKNOWN, None, ordered)

    highest = ordered[0]
    if highest.score < 80:
        return DetectionReport(root, DetectionStatus.STOPPED_UNCERTAIN, None, ordered)

    if len(ordered) > 1:
        second = ordered[1]
        if second.score >= 80 or highest.score - second.score <= 10:
            return DetectionReport(root, DetectionStatus.STOPPED_CONFLICT, None, ordered)

    return DetectionReport(root, DetectionStatus.AUTO_SELECTED, highest.engine_id, ordered)


def detect_project(
    root: str | Path,
    adapters: Iterable[EngineAdapter] | None = None,
) -> DetectionReport:
    snapshot = scan_project(root)
    if adapters is None:
        from game_localizer.adapters import get_adapters

        adapters = get_adapters()
    return resolve_detection(
        snapshot.root,
        (adapter.detect(snapshot) for adapter in adapters),
    )
```

- [ ] **Step 7: Run scanner and detector tests**

Run:

```powershell
python -m unittest tests.test_project_scanner tests.test_detector -v
```

Expected: all scanner and detector tests pass; the symlink test may report `skipped` on Windows systems without symlink permission.

- [ ] **Step 8: Run existing tests for regression safety**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all existing and new tests pass with `OK`.

- [ ] **Step 9: Commit Task 2**

```powershell
git add game_localizer/scanner.py game_localizer/detector.py game_localizer/adapters/base.py game_localizer/adapters/__init__.py tests/test_project_scanner.py tests/test_detector.py
git commit -m "feat: add safe project detection pipeline"
```

---

### Task 3: Ren'Py and RPG Maker Detection Adapters

**Files:**
- Create: `game_localizer/adapters/renpy.py`
- Create: `game_localizer/adapters/rpgmaker.py`
- Modify: `game_localizer/adapters/__init__.py`
- Create: `tests/test_renpy_adapter.py`
- Create: `tests/test_rpgmaker_adapter.py`

**Interfaces:**
- Consumes: `EngineAdapter`, `ProjectSnapshot`, `DetectionEvidence`, and the Task 2 registry.
- Produces registered IDs `renpy`, `rpg_maker_mz`, and `rpg_maker_mv`.
- Every adapter remains `experimental` and `detect_only` in this phase.

- [ ] **Step 1: Write failing Ren'Py adapter tests**

Create `tests/test_renpy_adapter.py`:

```python
import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.renpy import RenPyAdapter
from game_localizer.models import CapabilityLevel, DetectionStatus
from game_localizer.detector import detect_project


class RenPyAdapterTests(unittest.TestCase):
    def test_source_project_is_auto_selected_with_explainable_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "game").mkdir()
            (root / "game" / "script.rpy").write_text("label start:\n", encoding="utf-8")
            report = detect_project(root, adapters=(RenPyAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "renpy")
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)
        self.assertIn("renpy_scripts", {item.code for item in report.candidates[0].evidence})

    def test_archive_only_distribution_does_not_claim_full_support(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "game").mkdir()
            (root / "renpy").mkdir()
            (root / "game" / "archive.rpa").write_bytes(b"archive")
            report = detect_project(root, adapters=(RenPyAdapter(),))

        self.assertEqual(report.status, DetectionStatus.STOPPED_UNCERTAIN)
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)
        self.assertTrue(report.candidates[0].warnings)
```

- [ ] **Step 2: Write failing RPG Maker tests**

Create `tests/test_rpgmaker_adapter.py`:

```python
import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.rpgmaker import RpgMakerMVAdapter, RpgMakerMZAdapter
from game_localizer.models import DetectionStatus
from game_localizer.detector import detect_project


def touch(root: Path, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RpgMakerAdapterTests(unittest.TestCase):
    def test_mz_project_selects_mz_without_mv_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "game.rmmzproject")
            touch(root, "js/rmmz_core.js")
            touch(root, "data/System.json", "{}")
            report = detect_project(root, adapters=(RpgMakerMZAdapter(), RpgMakerMVAdapter()))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "rpg_maker_mz")

    def test_mv_project_selects_mv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "game.rpgproject")
            touch(root, "js/rpg_core.js")
            touch(root, "data/System.json", "{}")
            report = detect_project(root, adapters=(RpgMakerMZAdapter(), RpgMakerMVAdapter()))

        self.assertEqual(report.selected_engine, "rpg_maker_mv")

    def test_shared_system_json_alone_is_not_enough(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "data/System.json", "{}")
            report = detect_project(root, adapters=(RpgMakerMZAdapter(), RpgMakerMVAdapter()))

        self.assertEqual(report.status, DetectionStatus.UNKNOWN)
        self.assertIsNone(report.selected_engine)
```

- [ ] **Step 3: Run the adapter tests and verify import failures**

Run:

```powershell
python -m unittest tests.test_renpy_adapter tests.test_rpgmaker_adapter -v
```

Expected: FAIL because the engine adapter modules do not exist.

- [ ] **Step 4: Implement Ren'Py detection**

Create `game_localizer/adapters/renpy.py`:

```python
from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class RenPyAdapter(EngineAdapter):
    engine_id = "renpy"
    display_name = "Ren'Py"
    maturity = MaturityLevel.EXPERIMENTAL

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        if snapshot.has_dir("game"):
            evidence.append(DetectionEvidence("renpy_game_dir", "game", "发现 game 目录", 20))
        scripts = tuple(
            path for path in snapshot.files_with_suffix(".rpy") if path.startswith("game/")
        )
        if scripts:
            evidence.append(
                DetectionEvidence("renpy_scripts", scripts[0], "发现 Ren'Py 源脚本", 65)
            )
        if snapshot.has_dir("renpy"):
            evidence.append(DetectionEvidence("renpy_runtime", "renpy", "发现 Ren'Py 运行库", 15))
        compiled = snapshot.files_with_suffix(".rpyc")
        if compiled:
            evidence.append(
                DetectionEvidence("renpy_compiled", compiled[0], "发现编译脚本", 10)
            )
        archives = snapshot.files_with_suffix(".rpa")
        if archives:
            evidence.append(DetectionEvidence("renpy_archive", archives[0], "发现 RPA 归档", 25))
        if not evidence:
            return None
        warnings = ()
        if not scripts and (compiled or archives):
            warnings = ("仅发现编译脚本或归档；阶段一不会提取或修改这些资源",)
        return self.build_result(evidence, warnings)
```

- [ ] **Step 5: Implement RPG Maker MV/MZ detection**

Create `game_localizer/adapters/rpgmaker.py`:

```python
from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class _RpgMakerAdapter(EngineAdapter):
    project_file: str
    core_candidates: tuple[str, ...]

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        if snapshot.has_file(self.project_file):
            evidence.append(
                DetectionEvidence(
                    "rpgmaker_project",
                    self.project_file,
                    f"发现 {self.display_name} 项目标记",
                    60,
                )
            )
        core = next((path for path in self.core_candidates if snapshot.has_file(path)), None)
        if core:
            evidence.append(DetectionEvidence("rpgmaker_core", core, "发现引擎核心脚本", 45))
        system = next(
            (path for path in ("data/system.json", "www/data/system.json") if snapshot.has_file(path)),
            None,
        )
        if system:
            evidence.append(DetectionEvidence("rpgmaker_system", system, "发现系统数据库", 35))
        if snapshot.has_file("package.json") or snapshot.has_file("www/package.json"):
            evidence.append(DetectionEvidence("rpgmaker_package", "package.json", "发现 NW.js 配置", 10))
        if not evidence:
            return None
        return self.build_result(evidence, ("阶段一仅提供只读检测",))


class RpgMakerMZAdapter(_RpgMakerAdapter):
    engine_id = "rpg_maker_mz"
    display_name = "RPG Maker MZ"
    maturity = MaturityLevel.EXPERIMENTAL
    project_file = "game.rmmzproject"
    core_candidates = ("js/rmmz_core.js", "www/js/rmmz_core.js")


class RpgMakerMVAdapter(_RpgMakerAdapter):
    engine_id = "rpg_maker_mv"
    display_name = "RPG Maker MV"
    maturity = MaturityLevel.EXPERIMENTAL
    project_file = "game.rpgproject"
    core_candidates = ("js/rpg_core.js", "www/js/rpg_core.js")
```

- [ ] **Step 6: Register the three adapters**

Replace `game_localizer/adapters/__init__.py` with:

```python
from .base import EngineAdapter
from .renpy import RenPyAdapter
from .rpgmaker import RpgMakerMVAdapter, RpgMakerMZAdapter


_ADAPTERS: tuple[EngineAdapter, ...] = (
    RenPyAdapter(),
    RpgMakerMZAdapter(),
    RpgMakerMVAdapter(),
)


def get_adapters() -> tuple[EngineAdapter, ...]:
    return _ADAPTERS


__all__ = ["EngineAdapter", "get_adapters"]
```

- [ ] **Step 7: Run the engine-specific and detector tests**

Run:

```powershell
python -m unittest tests.test_renpy_adapter tests.test_rpgmaker_adapter tests.test_detector -v
```

Expected: all tests pass with `OK`.

- [ ] **Step 8: Commit Task 3**

```powershell
git add game_localizer/adapters/__init__.py game_localizer/adapters/renpy.py game_localizer/adapters/rpgmaker.py tests/test_renpy_adapter.py tests/test_rpgmaker_adapter.py
git commit -m "feat: detect RenPy and RPG Maker projects"
```

---

### Task 4: Godot, Unity, and Unreal Detection Adapters

**Files:**
- Create: `game_localizer/adapters/godot.py`
- Create: `game_localizer/adapters/unity.py`
- Create: `game_localizer/adapters/unreal.py`
- Modify: `game_localizer/adapters/__init__.py`
- Create: `tests/test_godot_adapter.py`
- Create: `tests/test_unity_adapter.py`
- Create: `tests/test_unreal_adapter.py`

**Interfaces:**
- Consumes: the same Task 2 adapter API and scanner query methods.
- Produces registered IDs `godot`, `unity`, and `unreal`.
- Source projects and sufficiently strong packaged signatures can be auto-detected, but capability remains `detect_only`.

- [ ] **Step 1: Write failing Godot tests**

Create `tests/test_godot_adapter.py` with one source test and one PCK test:

```python
import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.godot import GodotAdapter
from game_localizer.models import DetectionStatus
from game_localizer.detector import detect_project


class GodotAdapterTests(unittest.TestCase):
    def test_project_godot_is_a_strong_source_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "project.godot").write_text("[application]\n", encoding="utf-8")
            report = detect_project(root, adapters=(GodotAdapter(),))
        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "godot")

    def test_matching_pck_and_executable_detect_packaged_godot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.pck").write_bytes(b"pack")
            (root / "sample.exe").write_bytes(b"executable")
            report = detect_project(root, adapters=(GodotAdapter(),))
        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertTrue(report.candidates[0].warnings)
```

- [ ] **Step 2: Write failing Unity and Unreal tests**

Create `tests/test_unity_adapter.py`:

```python
import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.unity import UnityAdapter
from game_localizer.models import CapabilityLevel, DetectionStatus
from game_localizer.detector import detect_project


def touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class UnityAdapterTests(unittest.TestCase):
    def test_source_project_is_auto_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Assets").mkdir()
            touch(root, "ProjectSettings/ProjectVersion.txt")
            touch(root, "Packages/manifest.json")
            report = detect_project(root, adapters=(UnityAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "unity")
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)

    def test_packaged_windows_build_is_auto_selected_but_detect_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "UnityPlayer.dll")
            (root / "Game_Data").mkdir()
            touch(root, "Game_Data/globalgamemanagers")
            report = detect_project(root, adapters=(UnityAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)
        self.assertTrue(report.candidates[0].warnings)

    def test_assets_directory_alone_does_not_auto_select_unity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Assets").mkdir()
            report = detect_project(root, adapters=(UnityAdapter(),))

        self.assertEqual(report.status, DetectionStatus.UNKNOWN)
        self.assertIsNone(report.selected_engine)
```

Create `tests/test_unreal_adapter.py`:

```python
import tempfile
import unittest
from pathlib import Path

from game_localizer.adapters.unreal import UnrealAdapter
from game_localizer.models import CapabilityLevel, DetectionStatus
from game_localizer.detector import detect_project


def touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class UnrealAdapterTests(unittest.TestCase):
    def test_source_project_is_auto_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "Sample.uproject")
            (root / "Config").mkdir()
            (root / "Content").mkdir()
            report = detect_project(root, adapters=(UnrealAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertEqual(report.selected_engine, "unreal")
        self.assertEqual(report.candidates[0].capability, CapabilityLevel.DETECT_ONLY)

    def test_iostore_package_is_auto_selected_but_detect_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "Content/Paks/game.pak")
            touch(root, "Content/Paks/game.ucas")
            touch(root, "Content/Paks/game.utoc")
            report = detect_project(root, adapters=(UnrealAdapter(),))

        self.assertEqual(report.status, DetectionStatus.AUTO_SELECTED)
        self.assertTrue(report.candidates[0].warnings)

    def test_lone_pak_is_low_confidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            touch(root, "Content/Paks/game.pak")
            report = detect_project(root, adapters=(UnrealAdapter(),))

        self.assertEqual(report.status, DetectionStatus.UNKNOWN)
        self.assertIsNone(report.selected_engine)
```

- [ ] **Step 3: Run the tests and verify missing adapter imports**

Run:

```powershell
python -m unittest tests.test_godot_adapter tests.test_unity_adapter tests.test_unreal_adapter -v
```

Expected: FAIL because the three adapter modules do not exist.

- [ ] **Step 4: Implement Godot detection**

Create `game_localizer/adapters/godot.py`:

```python
from pathlib import Path

from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class GodotAdapter(EngineAdapter):
    engine_id = "godot"
    display_name = "Godot"
    maturity = MaturityLevel.EXPERIMENTAL

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        if snapshot.has_file("project.godot"):
            evidence.append(DetectionEvidence("godot_project", "project.godot", "发现 Godot 项目文件", 85))
        if snapshot.has_dir(".godot"):
            evidence.append(DetectionEvidence("godot_cache", ".godot", "发现 Godot 项目缓存", 10))
        scripts = snapshot.files_with_suffix(".gd") + snapshot.files_with_suffix(".tscn")
        if scripts:
            evidence.append(DetectionEvidence("godot_resources", scripts[0], "发现 Godot 项目资源", 5))

        packs = snapshot.root_files_with_suffix(".pck")
        if packs:
            evidence.append(DetectionEvidence("godot_pack", packs[0], "发现 Godot PCK", 60))
            pack_stems = {Path(path).stem for path in packs}
            executables = snapshot.root_files_with_suffix(".exe")
            matching = next((path for path in executables if Path(path).stem in pack_stems), None)
            if matching:
                evidence.append(DetectionEvidence("godot_executable", matching, "发现同名可执行文件", 25))

        if not evidence:
            return None
        warnings = ("PCK只用于检测，不会被提取或修改",) if packs else ("阶段一仅提供只读检测",)
        return self.build_result(evidence, warnings)
```

- [ ] **Step 5: Implement Unity detection**

Create `game_localizer/adapters/unity.py`:

```python
from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class UnityAdapter(EngineAdapter):
    engine_id = "unity"
    display_name = "Unity"
    maturity = MaturityLevel.EXPERIMENTAL

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        if snapshot.has_dir("assets"):
            evidence.append(DetectionEvidence("unity_assets", "Assets", "发现 Unity Assets 目录", 25))
        if snapshot.has_file("projectsettings/projectversion.txt"):
            evidence.append(DetectionEvidence("unity_version", "ProjectSettings/ProjectVersion.txt", "发现 Unity 项目版本", 45))
        if snapshot.has_file("packages/manifest.json"):
            evidence.append(DetectionEvidence("unity_packages", "Packages/manifest.json", "发现 Unity包清单", 35))
        if snapshot.has_file("unityplayer.dll"):
            evidence.append(DetectionEvidence("unity_player", "UnityPlayer.dll", "发现 Unity Player", 45))
        data_dirs = snapshot.root_dirs_with_suffix("_data")
        if data_dirs:
            evidence.append(DetectionEvidence("unity_data", data_dirs[0], "发现 Unity Data目录", 30))
            managers = tuple(
                path for path in snapshot.files_named("globalgamemanagers") if path.startswith(f"{data_dirs[0]}/")
            )
            if managers:
                evidence.append(DetectionEvidence("unity_managers", managers[0], "发现 Unity全局资源", 35))
        if not evidence:
            return None
        packaged = bool(snapshot.has_file("unityplayer.dll") or data_dirs)
        warnings = (
            "Unity成品二进制资源只用于检测，不会被提取或修改",
        ) if packaged else ("阶段一仅提供只读检测",)
        return self.build_result(evidence, warnings)
```

- [ ] **Step 6: Implement Unreal detection**

Create `game_localizer/adapters/unreal.py`:

```python
from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class UnrealAdapter(EngineAdapter):
    engine_id = "unreal"
    display_name = "Unreal Engine"
    maturity = MaturityLevel.EXPERIMENTAL

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        projects = snapshot.root_files_with_suffix(".uproject")
        if projects:
            evidence.append(DetectionEvidence("unreal_project", projects[0], "发现 Unreal 项目文件", 80))
        if snapshot.has_dir("config"):
            evidence.append(DetectionEvidence("unreal_config", "Config", "发现 Unreal 配置目录", 10))
        if snapshot.has_dir("content"):
            evidence.append(DetectionEvidence("unreal_content", "Content", "发现 Unreal Content目录", 10))
        for suffix, code, weight in (
            (".pak", "unreal_pak", 45),
            (".ucas", "unreal_ucas", 30),
            (".utoc", "unreal_utoc", 30),
        ):
            matches = snapshot.files_with_suffix(suffix)
            if matches:
                evidence.append(DetectionEvidence(code, matches[0], f"发现 Unreal {suffix} 容器", weight))
        if not evidence:
            return None
        packaged = any(item.code in {"unreal_pak", "unreal_ucas", "unreal_utoc"} for item in evidence)
        warnings = (
            "Unreal封包只用于检测，不会被提取或修改",
        ) if packaged else ("阶段一仅提供只读检测",)
        return self.build_result(evidence, warnings)
```

- [ ] **Step 7: Extend the explicit registry**

Replace `game_localizer/adapters/__init__.py` with the complete registry:

```python
from .base import EngineAdapter
from .godot import GodotAdapter
from .renpy import RenPyAdapter
from .rpgmaker import RpgMakerMVAdapter, RpgMakerMZAdapter
from .unity import UnityAdapter
from .unreal import UnrealAdapter


_ADAPTERS: tuple[EngineAdapter, ...] = (
    RenPyAdapter(),
    RpgMakerMZAdapter(),
    RpgMakerMVAdapter(),
    GodotAdapter(),
    UnityAdapter(),
    UnrealAdapter(),
)


def get_adapters() -> tuple[EngineAdapter, ...]:
    return _ADAPTERS


__all__ = ["EngineAdapter", "get_adapters"]
```

- [ ] **Step 8: Run all adapter tests**

Run:

```powershell
python -m unittest tests.test_renpy_adapter tests.test_rpgmaker_adapter tests.test_godot_adapter tests.test_unity_adapter tests.test_unreal_adapter -v
```

Expected: all adapter tests pass with `OK` and no high-confidence result is produced by the weak-signal tests.

- [ ] **Step 9: Commit Task 4**

```powershell
git add game_localizer/adapters/__init__.py game_localizer/adapters/godot.py game_localizer/adapters/unity.py game_localizer/adapters/unreal.py tests/test_godot_adapter.py tests/test_unity_adapter.py tests/test_unreal_adapter.py
git commit -m "feat: detect Godot Unity and Unreal projects"
```

---

### Task 5: Detection CLI and Machine-Readable Reports

**Files:**
- Create: `game_localizer/reporting.py`
- Modify: `game_localizer/__init__.py`
- Modify: `cli.py`
- Create: `tests/test_detection_cli.py`

**Interfaces:**
- Consumes: `detect_project`, `DetectionReport`, `DetectionStatus`, and `get_adapters`.
- Produces: `format_detection_report(report) -> str`, `python cli.py detect <directory> [--json]`, and `python cli.py engines [--json]`.
- Exit code 0 means automatic selection/list success, 1 means input or scan failure, and 2 means unknown/uncertain/conflicting detection with no project modification.
- Legacy `build_parser`, `format_result`, and positional behavior remain callable by current tests.

- [ ] **Step 1: Write failing CLI subprocess tests**

Create `tests/test_detection_cli.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DetectionCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "cli.py"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_detect_outputs_json_and_zero_for_high_confidence_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "game").mkdir()
            (root / "game" / "script.rpy").write_text("label start:\n", encoding="utf-8")
            completed = self.run_cli("detect", str(root), "--json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "auto_selected")
        self.assertEqual(payload["selected_engine"], "renpy")

    def test_detect_returns_two_for_unknown_project(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli("detect", directory)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("无法确定", completed.stdout)

    def test_detect_returns_one_for_missing_directory_without_traceback(self):
        completed = self.run_cli("detect", "missing-project")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("错误:", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_engines_lists_all_registered_engine_ids(self):
        completed = self.run_cli("engines", "--json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        ids = {item["engine_id"] for item in json.loads(completed.stdout)}
        self.assertEqual(
            ids,
            {"renpy", "rpg_maker_mz", "rpg_maker_mv", "godot", "unity", "unreal"},
        )
```

- [ ] **Step 2: Run the CLI tests and verify command-routing failures**

Run:

```powershell
python -m unittest tests.test_detection_cli -v
```

Expected: FAIL because the legacy parser treats `detect` and `engines` as resource paths.

- [ ] **Step 3: Implement human-readable report formatting**

Create `game_localizer/reporting.py`:

```python
from game_localizer.models import DetectionReport, DetectionStatus


_STATUS_LABELS = {
    DetectionStatus.AUTO_SELECTED: "自动选择",
    DetectionStatus.STOPPED_UNCERTAIN: "置信度不足，已停止",
    DetectionStatus.STOPPED_CONFLICT: "候选冲突，已停止",
    DetectionStatus.UNKNOWN: "无法确定",
}


def format_detection_report(report: DetectionReport) -> str:
    lines = [f"项目目录: {report.root}", f"检测状态: {_STATUS_LABELS[report.status]}"]
    for candidate in report.candidates:
        lines.append(
            f"候选引擎: {candidate.display_name} ({candidate.engine_id}) "
            f"置信度 {candidate.score}% / {candidate.capability.value} / {candidate.maturity.value}"
        )
        for evidence in candidate.evidence:
            lines.append(f"  - [{evidence.weight:+d}] {evidence.description}: {evidence.path}")
        for warning in candidate.warnings:
            lines.append(f"  - 警告: {warning}")
    if report.selected_engine:
        lines.append(f"选定引擎: {report.selected_engine}")
    else:
        lines.append("未选定引擎；项目未修改。")
    return "\n".join(lines)
```

Replace `game_localizer/__init__.py` with:

```python
from .detector import detect_project
from .models import (
    CapabilityLevel,
    DetectionEvidence,
    DetectionReport,
    DetectionResult,
    DetectionStatus,
    MaturityLevel,
)
from .reporting import format_detection_report

__all__ = [
    "CapabilityLevel",
    "DetectionEvidence",
    "DetectionReport",
    "DetectionResult",
    "DetectionStatus",
    "MaturityLevel",
    "detect_project",
    "format_detection_report",
]
```

- [ ] **Step 4: Add non-breaking command routing to `cli.py`**

Keep the existing `build_parser()` and `format_result()` unchanged. Add these imports:

```python
from game_localizer.adapters import get_adapters
from game_localizer.detector import detect_project
from game_localizer.models import DetectionStatus
from game_localizer.reporting import format_detection_report
from game_localizer.scanner import ProjectScanError
```

Add these functions above `main`:

```python
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
    args = build_detect_parser().parse_args(argv)
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
    args = build_engines_parser().parse_args(argv)
    payload = [
        {
            "engine_id": adapter.engine_id,
            "display_name": adapter.display_name,
            "maturity": adapter.maturity.value,
            "capability": "detect_only",
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
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(format_result(result))
    return 0
```

Replace only the body of `main` with:

```python
def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "detect":
        return run_detect(arguments[1:])
    if arguments and arguments[0] == "engines":
        return run_engines(arguments[1:])
    return run_legacy(arguments)
```

- [ ] **Step 5: Run new and legacy CLI tests**

Run:

```powershell
python -m unittest tests.test_detection_cli tests.test_cli -v
```

Expected: new detection tests and all pre-existing CLI tests pass with `OK`.

- [ ] **Step 6: Run full regression suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass with `OK`; no existing test is deleted or weakened.

- [ ] **Step 7: Commit Task 5**

```powershell
git add game_localizer/__init__.py game_localizer/reporting.py cli.py tests/test_detection_cli.py
git commit -m "feat: add engine detection CLI"
```

---

### Task 6: Phase 1 Documentation and Final Verification

**Files:**
- Modify: `README.md`
- Verify only: all files changed in Tasks 1–5

**Interfaces:**
- Documents the exact commands and limitations already implemented.
- Does not introduce extraction, writeback, GUI project mode, SDK execution, or binary parsing claims.

- [ ] **Step 1: Add a concise project-detection section to README**

Add commands:

```powershell
python cli.py engines
python cli.py detect "C:\Games\AuthorizedProject"
python cli.py detect "C:\Games\AuthorizedProject" --json
```

Document these exact semantics:

- Phase 1 scans file names and directory structure only.
- It recognizes Ren'Py, RPG Maker MV/MZ, Godot, Unity, and Unreal evidence.
- Exit code 0 means one high-confidence engine was auto-selected.
- Exit code 2 means unknown, uncertain, or conflicting evidence and the project was not modified.
- All adapters are `experimental` and `detect_only` in this release.
- Unity/Unreal/Godot packaged containers and Ren'Py archives are never unpacked or modified.
- The original single-file commands remain available.

- [ ] **Step 2: Verify source formatting and importability**

Run:

```powershell
git diff --check
python -m compileall -q cli.py translator.py game_localizer tests
```

Expected: both commands exit with code 0 and print no errors.

- [ ] **Step 3: Run the complete automated suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: every legacy and detection test passes with final output `OK`.

- [ ] **Step 4: Perform CLI smoke checks**

Run:

```powershell
python cli.py engines --json
python cli.py --help
```

Expected: the first command returns six engine IDs with `detect_only` capability; the second still describes the legacy resource and dictionary positional arguments.

- [ ] **Step 5: Verify repository scope**

Run:

```powershell
git status --short
git log -6 --stat --oneline
```

Expected: only the files listed in this plan are changed, no downloaded games or engine binaries are tracked, and no generated `localized-output` directory is present.

- [ ] **Step 6: Commit Task 6**

```powershell
git add README.md
git commit -m "docs: explain engine detection phase"
```

## Phase 1 Completion Gate

Before starting a later extraction/writeback plan, verify all of the following:

- `python -m unittest discover -s tests -v` exits 0.
- `git diff --check` exits 0.
- A Ren'Py source fixture auto-selects `renpy` with evidence.
- RPG Maker MV and MZ fixtures select distinct engine IDs.
- Godot, Unity, and Unreal official-structure fixtures auto-select the expected engine.
- Weak or conflicting evidence returns exit code 2 and never selects an engine.
- Scanning ignores generated directories and does not follow symlinks/reparse points.
- `python cli.py <resource> <dictionary>` remains behaviorally compatible.
- Every built-in adapter reports `detect_only` and `experimental`.
- No project resource is created, modified, unpacked, executed, or deleted by detection.
