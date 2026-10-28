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


if __name__ == "__main__":
    unittest.main()
