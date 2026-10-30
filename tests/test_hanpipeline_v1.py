from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from game_localizer.hanengine import (
    DictionaryTranslationProvider,
    HanPipelineV1,
    PipelineTranslationFailed,
    TranslationProviderError,
    TranslationResult,
    TranslationRouter,
    build_translation_review_queue,
)
from game_localizer.structured_workflow import StructuredWorkflowSession


class _FailAfterOneProvider:
    def __init__(self) -> None:
        self.calls = []

    def translate(self, request):
        self.calls.append(request.segment_id)
        if len(self.calls) == 2:
            raise TranslationProviderError("temporary outage")
        return TranslationResult(
            f"ZH:{request.text}",
            "cloud",
            "test-model",
            0.9,
        )


class _PrefixProvider:
    def __init__(self) -> None:
        self.calls = []

    def translate(self, request):
        self.calls.append(request.segment_id)
        return TranslationResult(
            f"ZH:{request.text}",
            "cloud",
            "test-model",
            0.9,
        )


class _ResidualEnglishProvider:
    TRANSLATIONS = {"Hello, {name}!": "你好，{name}！"}

    def __init__(self) -> None:
        self.calls = []

    def translate(self, request):
        self.calls.append(request.segment_id)
        if request.text == "Hero":
            raise TranslationProviderError(
                "model echoed English",
                code="residual_english",
                failure_codes=("residual_english",),
                retry_count=2,
            )
        return TranslationResult(
            self.TRANSLATIONS.get(request.text, "中文"),
            "local-model",
            "test-model",
            0.9,
        )


class HanPipelineV1Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / "data").mkdir(parents=True)
        (self.project / "game.rpgproject").write_text(
            "RPG Maker MV",
            encoding="utf-8",
        )
        (self.project / "data" / "Actors.json").write_text(
            json.dumps(
                [None, {"name": "Hero", "nickname": "", "profile": ""}]
            ),
            encoding="utf-8",
        )
        (self.project / "data" / "Map001.json").write_text(
            json.dumps(
                {
                    "displayName": "",
                    "events": [
                        {"list": [{"code": 401, "parameters": ["Hello, {name}!"]}]}
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.state_root = self.root / "state"

    def test_failed_translation_resumes_from_persisted_segments(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            extracted = workflow.extract()
            self.assertEqual(len(extracted.catalog.entries), 2)
            first = _FailAfterOneProvider()

            with self.assertRaises(PipelineTranslationFailed) as raised:
                workflow.translate(
                    extracted.catalog,
                    TranslationRouter((first,)),
                )

            failed = raised.exception
            self.assertEqual(failed.translated_count, 1)
            self.assertEqual(failed.resumed_count, 0)
            persisted = workflow.project_store.list_segments()
            self.assertEqual(
                sum(segment.target_text is not None for segment in persisted),
                1,
            )
            self.assertEqual(
                len(workflow.project_store.list_checkpoints(failed.task.task_id)),
                1,
            )

            second = _PrefixProvider()
            resumed = workflow.translate(
                extracted.catalog,
                TranslationRouter((second,)),
            )

            self.assertEqual(resumed.resumed_count, 1)
            self.assertEqual(resumed.translated_count, 1)
            self.assertEqual(len(second.calls), 1)
            self.assertTrue(
                all(entry.target_text is not None for entry in resumed.catalog.entries)
            )
            checkpoints = workflow.project_store.list_checkpoints(
                resumed.task.task_id,
                "pipeline-translate",
            )
            self.assertEqual([item.sequence for item in checkpoints], [1, 2])
            self.assertEqual(
                [item.payload["disposition"] for item in checkpoints],
                ["resumed", "translated"],
            )

            built = workflow.build(resumed.catalog, self.root / "output")
            self.assertTrue(built.verify_result.passed)

    def test_quality_gate_failure_falls_back_and_batch_continues(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            catalog = workflow.extract().catalog

            class _NewlineMismatchProvider:
                TRANSLATIONS = {"Hello, {name}!": "你好，{name}！"}

                def __init__(self) -> None:
                    self.calls = []

                def translate(self, request):
                    self.calls.append(request.text)
                    if request.text == "Hero":
                        raise TranslationProviderError(
                            "model moved the line break",
                            code="physical_newline_mismatch",
                            failure_codes=("physical_newline_mismatch",),
                            retry_count=2,
                        )
                    return TranslationResult(
                        self.TRANSLATIONS.get(request.text, "中文"),
                        "local-model",
                        "test-model",
                        0.9,
                    )

            provider = _NewlineMismatchProvider()
            outcome = workflow.translate(catalog, TranslationRouter((provider,)))

            self.assertEqual(outcome.translated_count, 1)
            self.assertEqual(outcome.untranslated_count, 1)
            failed_segment = next(
                segment
                for segment in outcome.segments
                if segment.source_text == "Hero"
            )
            self.assertIsNone(failed_segment.target_text)
            self.assertEqual(
                failed_segment.metadata["translation_failure"]["code"],
                "physical_newline_mismatch",
            )
            queue = build_translation_review_queue(
                outcome.catalog,
                translation=outcome,
            )
            queued = next(
                item for item in queue["items"] if item["source_text"] == "Hero"
            )
            self.assertIn("missing_translation", queued["reasons"])

    def test_residual_english_is_queued_and_translation_continues(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            catalog = workflow.extract().catalog
            provider = _ResidualEnglishProvider()

            outcome = workflow.translate(catalog, TranslationRouter((provider,)))

            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(outcome.translated_count, 1)
            self.assertEqual(outcome.untranslated_count, 1)
            failed_segment = next(
                segment for segment in outcome.segments if segment.source_text == "Hero"
            )
            self.assertIsNone(failed_segment.target_text)
            self.assertEqual(
                failed_segment.metadata["translation_failure"]["code"],
                "residual_english",
            )
            queue = build_translation_review_queue(
                outcome.catalog,
                translation=outcome,
            )
            queued_failure = next(
                item for item in queue["items"] if item["source_text"] == "Hero"
            )
            self.assertIn("translation_failed", queued_failure["reasons"])
            self.assertEqual(
                queued_failure["failure"]["retry_count"],
                2,
            )

            resumed_provider = _PrefixProvider()
            resumed = workflow.translate(
                catalog,
                TranslationRouter((resumed_provider,)),
            )

            self.assertEqual(resumed.translated_count, 1)
            self.assertEqual(resumed.resumed_count, 1)
            self.assertEqual(resumed.untranslated_count, 0)
            retried_segment = next(
                segment for segment in resumed.segments if segment.source_text == "Hero"
            )
            self.assertNotIn("translation_failure", retried_segment.metadata)

    def test_dictionary_precedes_cloud_and_cloud_only_handles_misses(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            catalog = workflow.extract().catalog
            cloud = _PrefixProvider()
            outcome = workflow.translate(
                catalog,
                TranslationRouter(
                    (
                        DictionaryTranslationProvider({"Hero": "英雄"}),
                        cloud,
                    )
                ),
            )

            targets = {
                entry.source_text: entry.target_text for entry in outcome.catalog.entries
            }
            self.assertEqual(targets["Hero"], "英雄")
            self.assertEqual(targets["Hello, {name}!"], "ZH:Hello, {name}!")
            self.assertEqual(len(cloud.calls), 1)
            self.assertEqual(outcome.untranslated_count, 0)

    def test_no_resume_retranslates_every_segment(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            catalog = workflow.extract().catalog
            first = _PrefixProvider()
            workflow.translate(catalog, TranslationRouter((first,)))

            second = _PrefixProvider()
            outcome = workflow.translate(
                catalog,
                TranslationRouter((second,)),
                resume=False,
            )

            self.assertEqual(outcome.resumed_count, 0)
            self.assertEqual(outcome.translated_count, 2)
            self.assertEqual(len(second.calls), 2)

    def test_target_language_change_does_not_resume_previous_language(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            target_language="zh-CN",
            state_root=self.state_root,
        ) as workflow:
            catalog = workflow.extract().catalog
            workflow.translate(catalog, TranslationRouter((_PrefixProvider(),)))

        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            target_language="ja",
            state_root=self.state_root,
        ) as workflow:
            catalog = workflow.extract().catalog
            provider = _PrefixProvider()
            outcome = workflow.translate(
                catalog,
                TranslationRouter((provider,)),
            )

            self.assertEqual(outcome.resumed_count, 0)
            self.assertEqual(outcome.translated_count, 2)
            self.assertEqual(len(provider.calls), 2)

    def test_foreign_route_is_rejected_before_segments_are_ingested(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            selection = workflow.detect()
            catalog = workflow.extract().catalog
            workflow.project_store.connection.execute("DELETE FROM segments")
            workflow.project_store.connection.commit()
            foreign_route = replace(
                selection.final_route,
                project_id="99999999-9999-4999-8999-999999999999",
            )

            with self.assertRaisesRegex(ValueError, "belong"):
                HanPipelineV1(workflow.runtime.core).translate(
                    catalog,
                    foreign_route,
                    TranslationRouter((_PrefixProvider(),)),
                )

            self.assertEqual(workflow.project_store.list_segments(), ())


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._lock = None

    def translate(self, request):
        if self._lock is None:
            import threading

            self._lock = threading.Lock()
        with self._lock:
            self.calls.append(request.segment_id)
        return TranslationResult(f"ZH:{request.text}", "cloud", "test-model", 0.9)


class _AlwaysFailProvider:
    def translate(self, request):
        raise TranslationProviderError("temporary outage")


class PipelineConcurrencyTests(unittest.TestCase):
    """Concurrency must not change outcomes, ordering, or checkpoint semantics."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / "data").mkdir(parents=True)
        (self.project / "game.rpgproject").write_text("RPG Maker MV", encoding="utf-8")
        (self.project / "data" / "Actors.json").write_text(
            json.dumps(
                [
                    None,
                    {"name": "Hero", "nickname": "Brave", "profile": "A quiet one"},
                    {"name": "Mage", "nickname": "Sage", "profile": "Reads a lot"},
                ]
            ),
            encoding="utf-8",
        )
        (self.project / "data" / "Map001.json").write_text(
            json.dumps(
                {
                    "displayName": "Beach",
                    "events": [
                        {"list": [{"code": 401, "parameters": ["Hello, {name}!"]}]},
                        {"list": [{"code": 401, "parameters": ["Good morning"]}]},
                        {"list": [{"code": 401, "parameters": ["See you soon"]}]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.state_root = self.root / "state"

    def _run(self, workers: int):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            extracted = workflow.extract()
            provider = _RecordingProvider()
            outcome = workflow.translate(
                extracted.catalog,
                TranslationRouter((provider,)),
                workers=workers,
            )
            checkpoints = workflow.project_store.list_checkpoints(
                outcome.task.task_id, "pipeline-translate"
            )
            return outcome, provider, checkpoints

    def test_parallel_matches_serial_outcome(self):
        import shutil

        serial, serial_provider, _ = self._run(1)
        shutil.rmtree(self.state_root, ignore_errors=True)
        parallel, parallel_provider, _ = self._run(4)

        self.assertEqual(serial.translated_count, parallel.translated_count)
        self.assertEqual(serial.untranslated_count, parallel.untranslated_count)
        self.assertEqual(serial.catalog_count, parallel.catalog_count)
        self.assertEqual(
            [e.target_text for e in serial.catalog.entries],
            [e.target_text for e in parallel.catalog.entries],
        )
        self.assertEqual(sorted(serial_provider.calls), sorted(parallel_provider.calls))

    def test_checkpoint_order_is_sequential(self):
        _, _, checkpoints = self._run(4)
        self.assertEqual(
            [item.sequence for item in checkpoints],
            list(range(1, len(checkpoints) + 1)),
        )
        self.assertEqual(
            [item.payload["completed"] for item in checkpoints],
            list(range(1, len(checkpoints) + 1)),
        )

    def test_each_segment_translated_exactly_once(self):
        _, provider, _ = self._run(4)
        self.assertEqual(len(provider.calls), len(set(provider.calls)))

    def test_provider_failure_still_aborts_under_concurrency(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            extracted = workflow.extract()
            with self.assertRaises(PipelineTranslationFailed):
                workflow.translate(
                    extracted.catalog,
                    TranslationRouter((_AlwaysFailProvider(),)),
                    workers=4,
                )

    def test_content_rejection_falls_back_without_aborting(self):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            extracted = workflow.extract()
            outcome = workflow.translate(
                extracted.catalog,
                TranslationRouter((_ResidualEnglishProvider(),)),
                workers=4,
            )
            self.assertGreater(outcome.untranslated_count, 0)
            self.assertGreater(outcome.translated_count, 0)


class _GlossaryAwareProvider:
    """Translates by concatenating the pinned target for every matched term.

    Lets a test prove that the glossary reached the provider rather than
    trusting the pipeline to have wired it.
    """

    def __init__(self) -> None:
        self.seen: list[tuple[str, ...]] = []

    def translate(self, request):
        self.seen.append(tuple(t.source for t in request.glossary))
        if request.glossary:
            joined = "".join(t.target for t in request.glossary)
            return TranslationResult(joined, "glossary-aware", "test", 0.9)
        return TranslationResult(f"ZH:{request.text}", "glossary-aware", "test", 0.9)


class _IgnoresGlossaryProvider:
    def __init__(self) -> None:
        self.seen: list[tuple[str, ...]] = []

    def translate(self, request):
        self.seen.append(tuple(t.source for t in request.glossary))
        return TranslationResult(f"ZH:{request.text}", "ignores-glossary", "test", 0.9)


class PipelineGlossaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / "data").mkdir(parents=True)
        (self.project / "game.rpgproject").write_text("RPG Maker MV", encoding="utf-8")
        (self.project / "data" / "Actors.json").write_text(
            json.dumps([None, {"name": "Hero", "nickname": "", "profile": ""}]),
            encoding="utf-8",
        )
        (self.project / "data" / "Map001.json").write_text(
            json.dumps(
                {
                    "displayName": "Beach",
                    "events": [
                        {"list": [{"code": 401, "parameters": ["grab the coconut"]}]},
                        {"list": [{"code": 401, "parameters": ["the boss left"]}]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.state_root = self.root / "state"

    def test_glossary_reaches_the_provider_per_segment(self):
        from game_localizer.hanengine.glossary import Glossary

        with StructuredWorkflowSession(
            self.project, engine_id="rpg_maker_mv", state_root=self.state_root
        ) as workflow:
            catalog = workflow.extract().catalog
            provider = _GlossaryAwareProvider()
            workflow.translate(
                catalog,
                TranslationRouter((provider,)),
                glossary=Glossary({"Coconut": "椰子", "Unrelated Term": "无关"}),
            )
        seen = {source for batch in provider.seen for source in batch}
        self.assertIn("Coconut", seen)
        # A term absent from every segment must never be injected.
        self.assertNotIn("Unrelated Term", seen)

    def test_matching_is_case_insensitive_across_segments(self):
        from game_localizer.hanengine.glossary import Glossary

        with StructuredWorkflowSession(
            self.project, engine_id="rpg_maker_mv", state_root=self.state_root
        ) as workflow:
            catalog = workflow.extract().catalog
            provider = _GlossaryAwareProvider()
            workflow.translate(
                catalog,
                TranslationRouter((provider,)),
                glossary=Glossary({"Boss": "首领"}),
            )
        # The source says "the boss left"; the glossary entry is capitalised.
        seen = {source for batch in provider.seen for source in batch}
        self.assertIn("Boss", seen)

    def test_pinned_term_that_is_ignored_falls_back(self):
        from game_localizer.hanengine.glossary import Glossary

        # The segment must *be* the term for the gate to bind.
        (self.project / "data" / "Map001.json").write_text(
            json.dumps(
                {
                    "displayName": "Beach",
                    "events": [
                        {"list": [{"code": 401, "parameters": ["Coconut"]}]},
                        {"list": [{"code": 401, "parameters": ["the boss left"]}]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        with StructuredWorkflowSession(
            self.project, engine_id="rpg_maker_mv", state_root=self.state_root
        ) as workflow:
            catalog = workflow.extract().catalog
            outcome = workflow.translate(
                catalog,
                TranslationRouter((_IgnoresGlossaryProvider(),)),
                glossary=Glossary({"Coconut": "椰子"}),
            )
        # The Coconut segment must not ship: the provider ignored the term.
        self.assertGreater(outcome.untranslated_count, 0)
        self.assertGreater(outcome.translated_count, 0)

    def test_in_sentence_term_does_not_block_shipping(self):
        from game_localizer.hanengine.glossary import Glossary

        with StructuredWorkflowSession(
            self.project, engine_id="rpg_maker_mv", state_root=self.state_root
        ) as workflow:
            catalog = workflow.extract().catalog
            outcome = workflow.translate(
                catalog,
                TranslationRouter((_IgnoresGlossaryProvider(),)),
                glossary=Glossary({"Coconut": "椰子"}),
            )
        # "grab the coconut" only *contains* the term; that is a hint, so the
        # segment ships even though the provider ignored it.
        self.assertEqual(outcome.untranslated_count, 0)

    def test_without_glossary_nothing_is_injected(self):
        with StructuredWorkflowSession(
            self.project, engine_id="rpg_maker_mv", state_root=self.state_root
        ) as workflow:
            catalog = workflow.extract().catalog
            provider = _GlossaryAwareProvider()
            workflow.translate(catalog, TranslationRouter((provider,)))
        self.assertTrue(all(batch == () for batch in provider.seen))


class _BudgetRepairProvider:
    """Too wide on the first attempt, on budget when re-asked with an instruction."""

    WIDE = "360度转体击杀"
    COMPACT = "转体击杀"

    def __init__(self, *, wide_for: str = "360") -> None:
        self.attempts: list[tuple[str, str]] = []
        self._wide_for = wide_for

    def translate(self, request):
        self.attempts.append((request.text, request.retry_instruction))
        if request.text != self._wide_for:
            return TranslationResult("早上好。", "cloud", "test-model", 0.9)
        if request.retry_instruction:
            return TranslationResult(self.COMPACT, "cloud", "test-model", 0.9)
        return TranslationResult(self.WIDE, "cloud", "test-model", 0.9)

    def attempts_for(self, text: str) -> list[str]:
        return [i for t, i in self.attempts if t == text]


class _StubbornProvider:
    """Always too wide, no matter how often it is asked."""

    def __init__(self) -> None:
        self.attempts: list[tuple[str, str]] = []

    def translate(self, request):
        self.attempts.append((request.text, request.retry_instruction))
        if request.text != "360":
            return TranslationResult("早上好。", "cloud", "test-model", 0.9)
        return TranslationResult("360度转体击杀外加空中翻滚", "cloud", "test-model", 0.9)

    def attempts_for(self, text: str) -> list[str]:
        return [i for t, i in self.attempts if t == text]


class PipelineRepairRoundTests(unittest.TestCase):
    """A repairable warning must trigger exactly one targeted re-ask."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / "data").mkdir(parents=True)
        (self.project / "game.rpgproject").write_text("RPG Maker MV", encoding="utf-8")
        (self.project / "data" / "Actors.json").write_text(
            json.dumps([None, {"name": "Hero", "nickname": "", "profile": ""}]),
            encoding="utf-8",
        )
        (self.project / "data" / "Map001.json").write_text(
            json.dumps(
                {
                    "displayName": "360",
                    "events": [{"list": [{"code": 401, "parameters": ["Good morning"]}]}],
                }
            ),
            encoding="utf-8",
        )
        self.state_root = self.root / "state"

    def _translate(self, provider, **kwargs):
        with StructuredWorkflowSession(
            self.project,
            engine_id="rpg_maker_mv",
            state_root=self.state_root,
        ) as workflow:
            catalog = workflow.extract().catalog
            outcome = workflow.translate(
                catalog,
                TranslationRouter((provider,)),
                **kwargs,
            )
            return outcome, workflow.project_store.list_segments()

    def test_overwide_label_is_reasked_once_and_replaced(self):
        provider = _BudgetRepairProvider()
        outcome, segments = self._translate(provider)
        # First attempt plus exactly one repair attempt for the wide label.
        attempts = provider.attempts_for("360")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], "")
        self.assertIn("shorter", attempts[1])
        # The compact repair is what ships, and it carries no warning.
        shipped = [s for s in segments if s.source_text == "360"]
        self.assertEqual(len(shipped), 1)
        self.assertIn(_BudgetRepairProvider.COMPACT, shipped[0].target_text)
        quality = shipped[0].metadata.get("translation_quality", [])
        self.assertEqual([q["code"] for q in quality], [])
        self.assertEqual(outcome.untranslated_count, 0)

    def test_other_segments_are_not_reasked(self):
        provider = _BudgetRepairProvider()
        self._translate(provider)
        self.assertEqual(len(provider.attempts_for("Good morning")), 1)
        self.assertEqual(len(provider.attempts_for("Hero")), 1)

    def test_stubborn_provider_keeps_first_attempt(self):
        provider = _StubbornProvider()
        _, segments = self._translate(provider)
        self.assertEqual(len(provider.attempts_for("360")), 2)
        shipped = [s for s in segments if s.source_text == "360"]
        # Still over budget, so the repair is rejected and the original stands.
        # No terminal punctuation: the source ("360") has none to copy.
        self.assertEqual(shipped[0].target_text.strip(), "360度转体击杀外加空中翻滚")
        codes = [q["code"] for q in shipped[0].metadata["translation_quality"]]
        self.assertEqual(codes, ["length_budget_exceeded"])

    def test_repair_rounds_zero_disables_the_reask(self):
        provider = _BudgetRepairProvider()
        _, segments = self._translate(provider, repair_rounds=0)
        self.assertEqual(len(provider.attempts_for("360")), 1)
        codes = [
            q["code"]
            for s in segments
            if s.source_text == "360"
            for q in s.metadata.get("translation_quality", [])
        ]
        self.assertEqual(codes, ["length_budget_exceeded"])

    def test_clean_segments_are_never_reasked(self):
        class _CleanProvider:
            def __init__(self) -> None:
                self.texts: list[str] = []

            def translate(self, request):
                self.texts.append(request.text)
                return TranslationResult("早上好。", "cloud", "test-model", 0.9)

        provider = _CleanProvider()
        self._translate(provider)
        # Every segment is asked exactly once: no repair round for clean output.
        self.assertEqual(sorted(provider.texts), sorted({"Hero", "360", "Good morning"}))

    def test_negative_repair_rounds_is_rejected(self):
        with self.assertRaises(ValueError):
            self._translate(_BudgetRepairProvider(), repair_rounds=-1)


if __name__ == "__main__":
    unittest.main()
