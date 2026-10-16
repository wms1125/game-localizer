from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from game_localizer.adapters import RenPyAdapterV1
from game_localizer.adapters.contract import (
    BuildRequest,
    BuildResult,
    ExtractRequest,
    ExtractResult,
    ValidationRequest,
    ValidationResult,
    VerifyRequest,
    VerifyResult,
)
from game_localizer.hanengine.segments import Segment
from game_localizer.hanengine.tasks import TaskContext, TaskControl


CORPUS_ROOT = Path(__file__).parent / "golden" / "renpy"


def make_context(step_id: str) -> TaskContext:
    return TaskContext("task-renpy-golden", step_id, TaskControl(), lambda *args: None)


class RenPyGoldenCorpusTests(unittest.TestCase):
    def test_manifest_cases_extract_and_build_without_source_mutation(self):
        manifest = json.loads((CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["engine"], "renpy")
        self.assertEqual(manifest["authority"]["tier"], "synthetic")

        adapter = RenPyAdapterV1()
        for case in manifest["cases"]:
            with self.subTest(case=case["id"]):
                project = self._safe_path(case["project"])
                expected = json.loads(self._safe_path(case["expected"]).read_text(encoding="utf-8"))
                with tempfile.TemporaryDirectory() as directory:
                    workspace = Path(directory)
                    source = workspace / "source"
                    shutil.copytree(project, source)
                    before = self._snapshot(source)
                    working = workspace / "working"
                    working.mkdir()
                    extracted = adapter.extract(
                        ExtractRequest(
                            source,
                            working,
                            ("utf-8",),
                            (),
                            f"golden-{case['id']}",
                            make_context("extract"),
                        )
                    )
                    self.assertIsInstance(extracted, ExtractResult)
                    self.assertEqual(
                        extracted.source_tree_fingerprint,
                        case["source_tree_sha256"],
                    )
                    self.assertEqual(self._entries(extracted), expected["entries"])
                    self.assertEqual(self._snapshot(source), before)

                    originals = tuple(
                        Segment.from_draft(f"golden-{case['id']}", "zh-CN", draft)
                        for draft in extracted.segments
                    )
                    translated = tuple(
                        replace(
                            segment,
                            target_text="T: " + segment.source_text,
                            translation_source="golden-fixture",
                        )
                        for segment in originals
                    )
                    validation = adapter.validate(
                        ValidationRequest(
                            extracted.source_tree_fingerprint,
                            originals,
                            translated,
                            "utf-8",
                            {},
                            make_context("validate"),
                        )
                    )
                    self.assertIsInstance(validation, ValidationResult)
                    self.assertTrue(validation.valid)

                    output = workspace / "output"
                    built = adapter.build(
                        BuildRequest(
                            source,
                            output,
                            translated,
                            extracted.source_tree_fingerprint,
                            {},
                            make_context("build"),
                        )
                    )
                    self.assertIsInstance(built, BuildResult)
                    self.assertEqual(self._snapshot(source), before)
                    verified = adapter.verify(
                        VerifyRequest(
                            extracted.source_tree_fingerprint,
                            output,
                            built.manifest,
                            "full",
                            make_context("verify"),
                        )
                    )
                    self.assertIsInstance(verified, VerifyResult)
                    self.assertTrue(verified.passed)

    @staticmethod
    def _entries(result: ExtractResult) -> list[dict[str, object]]:
        entries = []
        for draft in result.segments:
            contract = draft.metadata["segment_v2"]
            context = contract["context"]
            entries.append(
                {
                    "line": draft.source_location.line,
                    "kind": context["kind"],
                    "speaker": context["speaker"],
                    "source_text": draft.source_text,
                    "placeholders": list(draft.placeholders),
                    "text_context": context["text_context"],
                }
            )
        return entries

    @staticmethod
    def _safe_path(relative: str) -> Path:
        root = CORPUS_ROOT.resolve()
        path = (root / Path(*relative.split("/"))).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise AssertionError(f"golden corpus path escapes corpus root: {relative}") from exc
        return path

    @staticmethod
    def _snapshot(root: Path) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (
                    path.relative_to(root).as_posix(),
                    path.read_bytes().hex(),
                )
                for path in root.rglob("*")
                if path.is_file()
            )
        )


if __name__ == "__main__":
    unittest.main()
