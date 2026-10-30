import tempfile
import unittest
from pathlib import Path
from unittest import mock

from game_localizer.hanengine import memory as memory_module
from game_localizer.hanengine.memory import (
    PROMPT_VERSION,
    MemoryTranslationProvider,
    TranslationMemory,
    with_memory,
)
from game_localizer.hanengine.pipeline import _finish
from game_localizer.hanengine.translation import TranslationRequest, TranslationResult


class _InnerProvider:
    """A provider that answers with a fixed text and counts its calls."""

    def __init__(self, answer="开始游戏"):
        self.answer = answer
        self.calls = []

    def translate(self, request):
        self.calls.append(request.segment_id)
        return TranslationResult(self.answer, "local-model", "qwen2.5:3b", 1.0)


class _InnerBatchProvider(_InnerProvider):
    def translate_batch(self, requests):
        self.calls.extend(request.segment_id for request in requests)
        return {
            request.segment_id: TranslationResult(
                self.answer, "local-model", "qwen2.5:3b", 1.0
            )
            for request in requests
        }


def _request(text="Start Game", segment_id="seg-1", target_language="zh-CN"):
    return TranslationRequest(segment_id, text, "en", target_language)


class TranslationMemoryTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.path = Path(self._directory.name) / "memory.sqlite3"
        self.memory = TranslationMemory(self.path)
        self.addCleanup(self.memory.close)

    def test_store_then_lookup_round_trips(self):
        self.memory.store(
            source_text="Start Game",
            target_text="开始游戏",
            source_language="en",
            target_language="zh-CN",
        )
        entry = self.memory.lookup(
            source_text="Start Game",
            source_language="en",
            target_language="zh-CN",
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.target_text, "开始游戏")
        self.assertEqual(self.memory.count(), 1)

    def test_unknown_source_is_a_miss(self):
        self.assertIsNone(
            self.memory.lookup(
                source_text="Quit", source_language="en", target_language="zh-CN"
            )
        )

    def test_a_hash_collision_is_treated_as_a_miss(self):
        self.memory.store(
            source_text="Start Game",
            target_text="开始游戏",
            source_language="en",
            target_language="zh-CN",
        )
        with mock.patch.object(memory_module, "_hash_text", return_value="same"):
            self.memory.store(
                source_text="Quit",
                target_text="退出",
                source_language="en",
                target_language="zh-CN",
            )
            entry = self.memory.lookup(
                source_text="Start Game",
                source_language="en",
                target_language="zh-CN",
            )
        # The row that survives is the second one, and asking for the first text
        # must not hand back its translation just because the hashes matched.
        self.assertIsNone(entry)

    def test_the_model_and_prompt_version_are_part_of_the_key(self):
        self.memory.store(
            source_text="Start Game",
            target_text="开始游戏",
            source_language="en",
            target_language="zh-CN",
            model="qwen2.5:3b",
        )
        self.assertIsNotNone(
            self.memory.lookup(
                source_text="Start Game",
                source_language="en",
                target_language="zh-CN",
                model="qwen2.5:3b",
            )
        )
        self.assertIsNone(
            self.memory.lookup(
                source_text="Start Game",
                source_language="en",
                target_language="zh-CN",
                model="qwen2.5:7b",
            )
        )
        self.assertIsNone(
            self.memory.lookup(
                source_text="Start Game",
                source_language="en",
                target_language="zh-CN",
                model="qwen2.5:3b",
                prompt_version="older",
            )
        )

    def test_the_same_file_is_shared_by_two_sessions(self):
        self.memory.store(
            source_text="Start Game",
            target_text="开始游戏",
            source_language="en",
            target_language="zh-CN",
        )
        with TranslationMemory(self.path) as reopened:
            entry = reopened.lookup(
                source_text="Start Game",
                source_language="en",
                target_language="zh-CN",
            )
        self.assertEqual(entry.target_text, "开始游戏")


class MemoryProviderTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.memory = TranslationMemory(Path(self._directory.name) / "memory.sqlite3")
        self.addCleanup(self.memory.close)

    def test_a_hit_skips_the_wrapped_provider(self):
        self.memory.store(
            source_text="Start Game",
            target_text="开始游戏",
            source_language="en",
            target_language="zh-CN",
        )
        inner = _InnerProvider()
        provider = MemoryTranslationProvider(inner, self.memory)
        result = provider.translate(_request())
        self.assertEqual(result.text, "开始游戏")
        self.assertEqual(result.provider, "translation-memory")
        self.assertTrue(result.cached)
        self.assertEqual(inner.calls, [])
        self.assertEqual((provider.hits, provider.misses), (1, 0))

    def test_a_miss_delegates_and_reports_its_own_provider(self):
        inner = _InnerProvider()
        provider = MemoryTranslationProvider(inner, self.memory)
        result = provider.translate(_request())
        self.assertEqual(result.provider, "local-model")
        self.assertEqual(inner.calls, ["seg-1"])
        self.assertEqual((provider.hits, provider.misses), (0, 1))

    def test_remember_ignores_a_memory_result(self):
        inner = _InnerProvider()
        provider = MemoryTranslationProvider(inner, self.memory)
        cached = TranslationResult("开始游戏", "translation-memory", "memory", 1.0, True)
        provider.remember(_request(), cached)
        self.assertEqual(self.memory.count(), 0)

    def test_remember_stores_an_accepted_answer(self):
        inner = _InnerProvider()
        provider = MemoryTranslationProvider(inner, self.memory)
        provider.remember(_request(), TranslationResult("开始游戏", "local-model", "m", 1.0))
        entry = self.memory.lookup(
            source_text="Start Game", source_language="en", target_language="zh-CN"
        )
        self.assertEqual(entry.target_text, "开始游戏")

    def test_batch_only_exists_when_the_inner_provider_has_one(self):
        self.assertFalse(hasattr(MemoryTranslationProvider(_InnerProvider(), self.memory), "translate_batch"))
        self.assertTrue(
            hasattr(MemoryTranslationProvider(_InnerBatchProvider(), self.memory), "translate_batch")
        )

    def test_batch_serves_hits_and_delegates_only_the_rest(self):
        self.memory.store(
            source_text="Start Game",
            target_text="开始游戏",
            source_language="en",
            target_language="zh-CN",
        )
        inner = _InnerBatchProvider(answer="退出")
        provider = MemoryTranslationProvider(inner, self.memory)
        results = provider.translate_batch([_request(), _request("Quit", "seg-2")])
        self.assertEqual(results["seg-1"].provider, "translation-memory")
        self.assertEqual(results["seg-2"].text, "退出")
        self.assertEqual(inner.calls, ["seg-2"])

    def test_with_memory_returns_the_provider_untouched_without_a_memory(self):
        inner = _InnerProvider()
        self.assertIs(with_memory(inner, None), inner)


class MemoryAdoptionTests(unittest.TestCase):
    """The pipeline is the only place that knows an answer was accepted."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.memory = TranslationMemory(Path(self._directory.name) / "memory.sqlite3")
        self.addCleanup(self.memory.close)
        self.provider = MemoryTranslationProvider(_InnerProvider(), self.memory)

    def test_an_accepted_answer_is_remembered(self):
        _finish(
            _request(),
            TranslationResult("开始游戏", "local-model", "m", 1.0),
            provider=self.provider,
        )
        self.assertEqual(self.memory.count(), 1)

    def test_a_rejected_answer_is_not_remembered(self):
        outcome = _finish(
            _request(),
            TranslationResult("查看浮動", "local-model", "m", 1.0),
            provider=self.provider,
        )
        self.assertIsNotNone(outcome.error)
        self.assertEqual(getattr(outcome.error, "code", None), "traditional_chinese")
        self.assertEqual(self.memory.count(), 0)

    def test_a_run_without_a_memory_still_finishes(self):
        outcome = _finish(_request(), TranslationResult("开始游戏", "local-model", "m", 1.0))
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.translation.text, "开始游戏")


class PromptVersionTests(unittest.TestCase):
    def test_prompt_version_is_a_non_empty_string(self):
        self.assertIsInstance(PROMPT_VERSION, str)
        self.assertTrue(PROMPT_VERSION)


if __name__ == "__main__":
    unittest.main()
