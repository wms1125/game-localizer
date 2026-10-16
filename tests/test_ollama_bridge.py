from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools.ollama_translation_server import (
    TranslationBridgeError,
    _loopback_url,
    _ollama_health,
    _preserves_placeholders,
    _request_payload,
    _translate_with_retries,
    _translate_with_ollama,
)


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class OllamaBridgeTests(unittest.TestCase):
    def test_ollama_health_reports_upstream_transport_failure(self):
        def fake_urlopen(request, timeout):
            raise TimeoutError("timed out")

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            result = _ollama_health("http://127.0.0.1:11434", 2.0)

        self.assertEqual(result, {"status": "error", "error": "TimeoutError"})

    def test_ollama_health_reports_ready_upstream(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch(
            "tools.ollama_translation_server.urllib.request.urlopen",
            return_value=Response(),
        ):
            result = _ollama_health("http://127.0.0.1:11434", 2.0)

        self.assertEqual(result, {"status": "ok"})

    def test_only_loopback_ollama_urls_are_allowed(self):
        self.assertEqual(_loopback_url("http://127.0.0.1:11434/"), "http://127.0.0.1:11434")
        with self.assertRaisesRegex(ValueError, "loopback"):
            _loopback_url("https://example.invalid")
        with self.assertRaisesRegex(ValueError, "loopback"):
            _loopback_url("http://127.0.0.1:11434?redirect=https://example.invalid")

    def test_request_contract_requires_string_context_and_tokens(self):
        values = _request_payload(
            {
                "segment_id": "unity:1",
                "text": "Use [move]",
                "source_language": "en",
                "target_language": "zh-CN",
                "context": ["HUD"],
                "protected_tokens": ["[move]"],
            }
        )
        self.assertEqual(values[0], "unity:1")
        self.assertEqual(values[4], ("HUD",))
        with self.assertRaisesRegex(ValueError, "context"):
            _request_payload({"segment_id": "x", "text": "x", "source_language": "en", "target_language": "zh-CN", "context": "HUD"})

    def test_translation_request_and_response_preserve_placeholder(self):
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data)
            return _Response(
                json.dumps(
                    {"message": {"content": "使用 [HANENGINE_TOKEN_0] 移动。"}},
                    ensure_ascii=False,
                ).encode("utf-8")
            )

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            result = _translate_with_ollama(
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:1",
                text="Use [move] to move.",
                source_language="en",
                target_language="zh-CN",
                context=("HUD",),
                protected_tokens=("[move]",),
                timeout=30.0,
            )
        self.assertEqual(result, "使用 [move] 移动。")
        self.assertEqual(captured["timeout"], 30.0)
        self.assertEqual(captured["payload"]["model"], "qwen2.5:3b")
        self.assertIn("[HANENGINE_TOKEN_0]", captured["payload"]["messages"][1]["content"])

    def test_brace_placeholder_keeps_surrounding_parentheses_in_context(self):
        def fake_urlopen(request, timeout):
            payload = json.loads(request.data)
            self.assertIn("Revive (Hold [HANENGINE_TOKEN_0])", payload["messages"][1]["content"])
            return _Response(
                json.dumps(
                    {"message": {"content": "复活(按住 [HANENGINE_TOKEN_0])"}},
                    ensure_ascii=False,
                ).encode("utf-8")
            )

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            result = _translate_with_ollama(
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:brace-placeholder",
                text="Revive (Hold {0})",
                source_language="en",
                target_language="zh-CN",
                context=(),
                protected_tokens=("{0}",),
                timeout=30.0,
            )

        self.assertEqual(result, "复活(按住 {0})")

    def test_translation_request_and_response_preserve_rich_text_tags(self):
        responses = [
            _Response(json.dumps({"message": {"content": "提取"}}, ensure_ascii=False).encode("utf-8")),
            _Response(json.dumps({"message": {"content": "装扮箱"}}, ensure_ascii=False).encode("utf-8")),
            _Response(json.dumps({"message": {"content": "。"}}, ensure_ascii=False).encode("utf-8")),
        ]

        def fake_urlopen(request, timeout):
            return responses.pop(0)

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            result = _translate_with_ollama(
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:rich-text",
                text="Extract <b><u>COSMETIC BOX</u></b>.",
                source_language="en",
                target_language="zh-CN",
                context=("HUD",),
                protected_tokens=("<b>", "<u>", "</u>", "</b>"),
                timeout=30.0,
            )
        self.assertEqual(result, "提取 <b><u>装扮箱</u></b>。")

    def test_rich_text_tags_are_kept_in_place_by_fragmented_translation(self):
        responses = [
            _Response(json.dumps({"message": {"content": "这个"}}, ensure_ascii=False).encode("utf-8")),
            _Response(json.dumps({"message": {"content": "长腿生物"}}, ensure_ascii=False).encode("utf-8")),
            _Response(json.dumps({"message": {"content": "在我睡觉时偷我的啤酒"}}, ensure_ascii=False).encode("utf-8")),
        ]

        def fake_urlopen(request, timeout):
            return responses.pop(0)

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            result = _translate_with_ollama(
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:rich-text-fragments",
                text="this <color=#FFEF4D><b>long-legged creature</color></b> has been stealing my beer while I sleep",
                source_language="en",
                target_language="zh-CN",
                context=(),
                protected_tokens=("<color=#FFEF4D>", "<b>", "</color>", "</b>"),
                timeout=30.0,
            )

        self.assertEqual(
            result,
            "这个 <color=#FFEF4D><b>长腿生物</color></b> 在我睡觉时偷我的啤酒",
        )

    def test_translation_reads_multiline_phrases_as_one_layout_segment(self):
        def fake_urlopen(request, timeout):
            payload = json.loads(request.data)
            self.assertIn("Physical line breaks are forced visual layout breaks", payload["messages"][0]["content"])
            self.assertEqual(payload["messages"][1]["content"], "How to\nFish")
            return _Response(
                json.dumps(
                    {"message": {"content": "如何\n钓鱼"}},
                    ensure_ascii=False,
                ).encode("utf-8")
            )

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            result = _translate_with_ollama(
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:multiline-title",
                text="How to\nFish",
                source_language="en",
                target_language="zh-CN",
                context=(),
                protected_tokens=(),
                timeout=30.0,
            )

        self.assertEqual(result, "如何\n钓鱼")

    def test_missing_marker_is_rejected_instead_of_repaired(self):
        def fake_urlopen(request, timeout):
            return _Response(
                b'{"message":{"content":"\xe4\xbd\xbf\xe7\x94\xa8"}}'
            )

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            with self.assertRaisesRegex(RuntimeError, "marker"):
                _translate_with_ollama(
                    ollama_url="http://127.0.0.1:11434",
                    model="qwen2.5:3b",
                    segment_id="unity:1",
                    text="Use [move] to move.",
                    source_language="en",
                    target_language="zh-CN",
                    context=(),
                    protected_tokens=("[move]",),
                    timeout=30.0,
                )

    def test_physical_newline_in_single_fragment_is_rejected(self):
        def fake_urlopen(request, timeout):
            return _Response(json.dumps({"message": {"content": "译文\n额外说明"}}).encode("utf-8"))

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            with self.assertRaisesRegex(RuntimeError, "physical newline"):
                _translate_with_ollama(
                    ollama_url="http://127.0.0.1:11434",
                    model="qwen2.5:3b",
                    segment_id="unity:1",
                    text="Not me... :'(",
                    source_language="en",
                    target_language="zh-CN",
                    context=(),
                    protected_tokens=(),
                    timeout=30.0,
                )

    def test_existing_physical_newline_count_is_allowed(self):
        def fake_urlopen(request, timeout):
            return _Response(json.dumps({"message": {"content": "第一行\n第二行"}}).encode("utf-8"))

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            result = _translate_with_ollama(
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:1",
                text="First line\nSecond line",
                source_language="en",
                target_language="zh-CN",
                context=(),
                protected_tokens=(),
                timeout=30.0,
            )
        self.assertEqual(result, "第一行\n第二行")

    def test_literal_newline_tokens_are_translated_as_separate_fragments(self):
        responses = [
            _Response(b'{"message":{"content":"Best computer"}}'),
            _Response(b'{"message":{"content":"should host."}}'),
            _Response(b'{"message":{"content":"Are you this friend?"}}'),
        ]

        def fake_urlopen(request, timeout):
            return responses.pop(0)

        with patch("tools.ollama_translation_server.urllib.request.urlopen", fake_urlopen):
            result = _translate_with_ollama(
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:2",
                text=r"Best computer\nshould host.\n\nAre you this friend?",
                source_language="en",
                target_language="zh-CN",
                context=("Menu",),
                protected_tokens=(r"\n", r"\n", r"\n"),
                timeout=30.0,
            )
        self.assertEqual(result, r"Best computer\nshould host.\n\nAre you this friend?")
        self.assertEqual(responses, [])

    def test_translation_retries_transient_runtime_errors(self):
        calls = []

        def fake_translate(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("temporary marker failure")
            return "译文"

        with patch("tools.ollama_translation_server._translate_with_ollama", fake_translate):
            result = _translate_with_retries(
                attempts=3,
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:3",
                text="Start",
                source_language="en",
                target_language="zh-CN",
                context=(),
                protected_tokens=(),
                timeout=30.0,
            )
        self.assertEqual(result, "译文")
        self.assertEqual(len(calls), 2)

    def test_translation_retries_unchanged_short_english_slang(self):
        calls = []

        def fake_translate(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return "yum yummy"
            self.assertIn("short slang", kwargs["retry_instruction"])
            return "真好吃"

        with patch("tools.ollama_translation_server._translate_with_ollama", fake_translate):
            result = _translate_with_retries(
                attempts=3,
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:yum-yummy",
                text="yum yummy",
                source_language="en",
                target_language="zh-CN",
                context=(),
                protected_tokens=(),
                timeout=30.0,
            )

        self.assertEqual(result, "真好吃")
        self.assertEqual(len(calls), 2)

    def test_translation_retries_single_word_source_when_model_echoes_it(self):
        calls = []

        def fake_translate(**kwargs):
            calls.append(kwargs)
            return "yums" if len(calls) == 1 else "好吃"

        with patch("tools.ollama_translation_server._translate_with_ollama", fake_translate):
            result = _translate_with_retries(
                attempts=2,
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:yums",
                text="yums",
                source_language="en",
                target_language="zh-CN",
                context=(),
                protected_tokens=(),
                timeout=30.0,
            )

        self.assertEqual(result, "好吃")
        self.assertEqual(len(calls), 2)

    def test_translation_retries_english_echo_with_punctuation(self):
        calls = []

        def fake_translate(**kwargs):
            calls.append(kwargs)
            return "yum yummy!" if len(calls) == 1 else "真好吃！"

        with patch("tools.ollama_translation_server._translate_with_ollama", fake_translate):
            result = _translate_with_retries(
                attempts=2,
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:yum-yummy-punctuation",
                text="yum yummy",
                source_language="en",
                target_language="zh-CN",
                context=(),
                protected_tokens=(),
                timeout=30.0,
            )

        self.assertEqual(result, "真好吃！")
        self.assertEqual(len(calls), 2)

    def test_translation_fails_with_residual_english_after_retry_budget(self):
        calls = []

        def fake_translate(**kwargs):
            calls.append(kwargs)
            return "yum yummy"

        with patch("tools.ollama_translation_server._translate_with_ollama", fake_translate):
            with self.assertRaises(TranslationBridgeError) as raised:
                _translate_with_retries(
                    attempts=3,
                    ollama_url="http://127.0.0.1:11434",
                    model="qwen2.5:3b",
                    segment_id="unity:yum-yummy",
                    text="yum yummy",
                    source_language="en",
                    target_language="zh-CN",
                    context=(),
                    protected_tokens=(),
                    timeout=30.0,
                )

        self.assertEqual(raised.exception.code, "residual_english")
        self.assertEqual(raised.exception.retry_count, 2)
        self.assertEqual(len(calls), 3)

    def test_preserved_kg_unit_does_not_trigger_residual_english_retry(self):
        calls = []

        def fake_translate(**kwargs):
            calls.append(kwargs)
            return "kg"

        with patch("tools.ollama_translation_server._translate_with_ollama", fake_translate):
            result = _translate_with_retries(
                attempts=3,
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                segment_id="unity:unit-kg",
                text="kg",
                source_language="en",
                target_language="zh-CN",
                context=(),
                protected_tokens=(),
                timeout=30.0,
            )

        self.assertEqual(result, "kg")
        self.assertEqual(len(calls), 1)

    def test_placeholder_comparison_is_multiset_based(self):
        self.assertTrue(_preserves_placeholders("%1 %1 {name}", "{name} %1 %1"))
        self.assertFalse(_preserves_placeholders("Use [move]", "使用"))


if __name__ == "__main__":
    unittest.main()
