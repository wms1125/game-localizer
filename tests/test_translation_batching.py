"""Batch transport: many segments, one round trip, per-segment safety.

The batch endpoint exists to amortise the system prompt, not to relax the
quality gate.  Every test below pins that distinction: a batch may only ever
*remove* work from the single-segment path, never *change* how a segment is
judged.
"""
from __future__ import annotations

import json
import unittest
from dataclasses import dataclass, field

from game_localizer.hanengine.pipeline import (
    DEFAULT_BATCH_SIZE,
    _SegmentTranslation,
    _translate_batch,
)
from game_localizer.hanengine.translation import (
    HttpResponse,
    LocalModelTranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationResult,
)


class _RecordingTransport:
    """Fake HTTP transport that records the URL and payload of every call."""

    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers, body, timeout):
        payload = json.loads(body.decode("utf-8"))
        self.calls.append((url, payload))
        return self._handler(url, payload)


def _ok(translations: dict[str, str]) -> HttpResponse:
    return HttpResponse(
        200,
        "application/json",
        json.dumps(
            {
                "translations": translations,
                "provider": "fake",
                "model": "fake",
                "confidence": 0.9,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
    )


def _request(segment_id: str, text: str, target_language: str = "zh-CN") -> TranslationRequest:
    return TranslationRequest(segment_id, text, "en", target_language)


def _provider(handler):
    transport = _RecordingTransport(handler)
    provider = LocalModelTranslationProvider(
        "http://127.0.0.1:9/translate",
        transport=transport,
    )
    return provider, transport


class BatchEndpointTests(unittest.TestCase):
    def test_batch_path_is_derived_from_the_translate_path(self):
        provider, transport = _provider(lambda url, payload: _ok({}))
        provider.translate_batch([_request("a", "Start")])
        self.assertEqual(transport.calls[0][0], "http://127.0.0.1:9/translate-batch")

    def test_endpoint_without_the_translate_suffix_still_gets_a_batch_path(self):
        transport = _RecordingTransport(lambda url, payload: _ok({}))
        provider = LocalModelTranslationProvider(
            "http://127.0.0.1:9/api",
            transport=transport,
        )
        provider.translate_batch([_request("a", "Start")])
        self.assertEqual(transport.calls[0][0], "http://127.0.0.1:9/api/translate-batch")

    def test_one_request_carries_every_segment(self):
        provider, transport = _provider(
            lambda url, payload: _ok({item["segment_id"]: f"译{item['text']}" for item in payload["segments"]})
        )
        provider.translate_batch([_request("a", "Start"), _request("b", "Quit")])
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(transport.calls[0][1]["segments"]), 2)


class BatchAnswerParsingTests(unittest.TestCase):
    def test_answered_segments_come_back_keyed_by_segment_id(self):
        provider, _ = _provider(
            lambda url, payload: _ok({"a": "开始", "b": "退出"})
        )
        results = provider.translate_batch([_request("a", "Start"), _request("b", "Quit")])
        self.assertEqual(sorted(results), ["a", "b"])
        self.assertEqual(results["a"].text, "开始")
        self.assertEqual(results["a"].provider, "fake")

    def test_unknown_segment_ids_are_dropped(self):
        # A model that invents an id must never be able to inject a segment.
        provider, _ = _provider(lambda url, payload: _ok({"a": "开始", "zzz": "凭空"}))
        results = provider.translate_batch([_request("a", "Start")])
        self.assertEqual(list(results), ["a"])

    def test_placeholders_are_masked_before_the_model_sees_them(self):
        provider, transport = _provider(lambda url, payload: _ok({"a": "按住{0}"}))
        provider.translate_batch([_request("a", "Hold {0}")])
        sent = transport.calls[0][1]["segments"][0]["text"]
        self.assertNotIn("{0}", sent)
        self.assertIn("Zq", sent)

    def test_masked_placeholder_is_restored_in_the_answer(self):
        provider, transport = _provider(lambda url, payload: _ok({"a": "按住 ZqB Zx"}))
        results = provider.translate_batch([_request("a", "Hold {0}")])
        self.assertIn("{0}", results["a"].text)

    def test_segment_whose_sentinel_was_truncated_is_left_out(self):
        # The model cut "ZqBZx" down to "ZqB"; there is no way to restore that, so
        # the answer must not reach the caller as if it were usable.
        provider, _ = _provider(lambda url, payload: _ok({"a": "按ZqB键冲刺"}))
        results = provider.translate_batch([_request("a", "Press {0} to sprint")])
        self.assertEqual(results, {})

    def test_truncated_sentinel_fails_the_single_path_loudly(self):
        provider, _ = _provider(
            lambda url, payload: HttpResponse(
                200,
                "application/json",
                json.dumps({"translation": "按ZqB键冲刺"}, ensure_ascii=False).encode("utf-8"),
            )
        )
        with self.assertRaises(TranslationProviderError) as caught:
            provider.translate(_request("a", "Press {0} to sprint"))
        self.assertEqual(caught.exception.code, "placeholder_mismatch")

    def test_http_error_raises_provider_error(self):
        provider, _ = _provider(
            lambda url, payload: HttpResponse(503, "application/json", b"{}")
        )
        with self.assertRaisesRegex(TranslationProviderError, "HTTP 503"):
            provider.translate_batch([_request("a", "Start")])

    def test_missing_translations_key_is_an_invalid_response(self):
        provider, _ = _provider(
            lambda url, payload: HttpResponse(
                200, "application/json", b'{"provider":"fake"}'
            )
        )
        with self.assertRaisesRegex(TranslationProviderError, "invalid batch response"):
            provider.translate_batch([_request("a", "Start")])

    def test_empty_request_list_short_circuits_without_a_call(self):
        provider, transport = _provider(lambda url, payload: _ok({}))
        self.assertEqual(provider.translate_batch([]), {})
        self.assertEqual(transport.calls, [])


@dataclass
class _StubContext:
    checkpoints: int = field(default=0)

    def checkpoint(self) -> None:
        self.checkpoints += 1


class _BatchProvider:
    """Batch-capable provider that answers only the segments it is told to."""

    def __init__(self, *, answer=None, fail_batches: bool = False) -> None:
        self._answer = answer or (lambda request: "已翻译")
        self._fail_batches = fail_batches
        self.batch_calls: list[list[str]] = []
        self.single_calls: list[str] = []

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.single_calls.append(request.segment_id)
        return TranslationResult(self._answer(request), "local-model", "stub", 1.0)

    def translate_batch(self, requests):
        self.batch_calls.append([request.segment_id for request in requests])
        if self._fail_batches:
            raise TranslationProviderError("batch endpoint is down", code="http_error")
        return {
            request.segment_id: TranslationResult(
                self._answer(request), "local-model", "stub", 1.0
            )
            for request in requests
        }


class PipelineBatchTests(unittest.TestCase):
    def test_segments_are_packed_and_finished_individually(self):
        provider = _BatchProvider()
        requests = [_request(f"s{index}", f"Label {index}") for index in range(8)]
        results = _translate_batch(
            provider,
            requests,
            batch_size=4,
            workers=1,
            context=_StubContext(),
        )
        self.assertEqual(provider.batch_calls, [["s0", "s1", "s2", "s3"], ["s4", "s5", "s6", "s7"]])
        self.assertEqual(sorted(results), [f"s{index}" for index in range(8)])
        self.assertEqual(provider.single_calls, [])

    def test_a_failed_batch_falls_back_to_one_request_per_segment(self):
        provider = _BatchProvider(fail_batches=True)
        requests = [_request("a", "Start"), _request("b", "Quit")]
        results = _translate_batch(
            provider,
            requests,
            batch_size=8,
            workers=1,
            context=_StubContext(),
        )
        self.assertEqual(sorted(provider.single_calls), ["a", "b"])
        self.assertEqual(results["a"].translation.text, "已翻译")

    def test_segments_the_batch_did_not_answer_are_re_asked_one_at_a_time(self):
        class Partial(_BatchProvider):
            def translate_batch(self, requests):
                self.batch_calls.append([request.segment_id for request in requests])
                return {
                    requests[0].segment_id: TranslationResult("只回答第一段", "stub", "stub", 1.0)
                }

        provider = Partial()
        results = _translate_batch(
            provider,
            [_request("a", "Start"), _request("b", "Quit")],
            batch_size=8,
            workers=1,
            context=_StubContext(),
        )
        self.assertEqual(provider.single_calls, ["b"])
        self.assertEqual(results["a"].translation.text, "只回答第一段")

    def test_the_quality_gate_still_runs_per_segment(self):
        # "Quit" comes back in English: that segment must be rejected even though
        # its neighbour in the same batch was fine.
        def answer(request: TranslationRequest) -> str:
            if request.segment_id == "b":
                return "Quit"
            return "开始"

        provider = _BatchProvider(answer=answer)
        results = _translate_batch(
            provider,
            [_request("a", "Start"), _request("b", "Quit")],
            batch_size=8,
            workers=1,
            context=_StubContext(),
        )
        self.assertIsNone(results["a"].error)
        self.assertIsNotNone(results["b"].error)
        self.assertEqual(results["b"].error.code, "residual_english")

    def test_batch_size_one_never_calls_the_batch_endpoint(self):
        provider = _BatchProvider()
        _translate_batch(
            provider,
            [_request("a", "Start")],
            batch_size=1,
            workers=1,
            context=_StubContext(),
        )
        self.assertEqual(provider.batch_calls, [])
        self.assertEqual(provider.single_calls, ["a"])

    def test_provider_without_batch_support_uses_the_single_path(self):
        class Single:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def translate(self, request):
                self.calls.append(request.segment_id)
                return TranslationResult("开始", "single", "single", 1.0)

        provider = Single()
        results = _translate_batch(
            provider,
            [_request("a", "Start"), _request("b", "Quit")],
            batch_size=8,
            workers=1,
            context=_StubContext(),
        )
        self.assertEqual(provider.calls, ["a", "b"])
        self.assertEqual(results["a"].translation.text, "开始")

    def test_batch_requests_are_packed_with_the_documented_default(self):
        provider = _BatchProvider()
        requests = [_request(f"s{index}", f"Label {index}") for index in range(DEFAULT_BATCH_SIZE * 2)]
        _translate_batch(
            provider,
            requests,
            batch_size=DEFAULT_BATCH_SIZE,
            workers=1,
            context=_StubContext(),
        )
        self.assertEqual(len(provider.batch_calls), 2)
        self.assertTrue(all(len(group) == DEFAULT_BATCH_SIZE for group in provider.batch_calls))

    def test_batches_run_concurrently_but_checkpoints_stay_per_group(self):
        provider = _BatchProvider()
        context = _StubContext()
        requests = [_request(f"s{index}", f"Label {index}") for index in range(6)]
        _translate_batch(
            provider,
            requests,
            batch_size=2,
            workers=3,
            context=context,
        )
        self.assertEqual(len(provider.batch_calls), 3)
        self.assertEqual(context.checkpoints, 3)


class UnreportedConfidenceTests(unittest.TestCase):
    """A provider that never scores itself must not be reported as unsure."""

    def test_batch_answer_without_confidence_is_not_low_confidence(self):
        transport = _RecordingTransport(
            lambda url, payload: HttpResponse(
                200,
                "application/json",
                json.dumps(
                    {"translations": {"a": "开始游戏"}, "provider": "fake", "model": "fake"},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        )
        provider = LocalModelTranslationProvider(
            "http://127.0.0.1:9/translate", transport=transport
        )
        results = provider.translate_batch([_request("a", "Start Game")])
        self.assertEqual(results["a"].confidence, 1.0)

    def test_single_answer_without_confidence_is_not_low_confidence(self):
        transport = _RecordingTransport(
            lambda url, payload: HttpResponse(
                200,
                "application/json",
                json.dumps(
                    {"translation": "开始游戏", "provider": "fake", "model": "fake"},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        )
        provider = LocalModelTranslationProvider(
            "http://127.0.0.1:9/translate", transport=transport
        )
        result = provider.translate(_request("a", "Start Game"))
        self.assertEqual(result.confidence, 1.0)

    def test_reported_low_confidence_is_still_reported(self):
        transport = _RecordingTransport(
            lambda url, payload: HttpResponse(
                200,
                "application/json",
                json.dumps(
                    {"translation": "开始游戏", "provider": "fake", "model": "fake", "confidence": 0.2},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        )
        provider = LocalModelTranslationProvider(
            "http://127.0.0.1:9/translate", transport=transport
        )
        result = provider.translate(_request("a", "Start Game"))
        self.assertEqual(result.confidence, 0.2)


if __name__ == "__main__":
    unittest.main()
