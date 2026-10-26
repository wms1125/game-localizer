import json
import tempfile
import unittest
from pathlib import Path

from game_localizer.hanengine.translation import (
    CloudTranslationProvider,
    DictionaryTranslationProvider,
    HttpResponse,
    LocalModelTranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationResult,
    TranslationRouter,
    translation_quality_issues,
)
from game_localizer.hanengine.tts import CloudTtsProvider, TtsRequest, WindowsSapiTts


class CloudTranslationTests(unittest.TestCase):
    def test_local_model_uses_loopback_endpoint_and_structured_request(self):
        calls = []

        def transport(url, headers, body, timeout):
            calls.append((url, headers, json.loads(body), timeout))
            return HttpResponse(
                200,
                "application/json",
                json.dumps(
                    {
                        "translation": "使用 [move] 移动。",
                        "provider": "local-runtime",
                        "model": "test-q4",
                        "confidence": 0.88,
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )

        provider = LocalModelTranslationProvider(
            "http://127.0.0.1:8080/translate",
            transport=transport,
            model_name="test-q4",
        )
        result = provider.translate(
            TranslationRequest(
                "line-1",
                "Use [move] to move.",
                "en",
                "zh-CN",
                context=("tutorial",),
            )
        )

        self.assertEqual(result.text, "使用 [move] 移动。")
        self.assertEqual(calls[0][0], "http://127.0.0.1:8080/translate")
        self.assertEqual(calls[0][2]["segment_id"], "line-1")
        self.assertEqual(calls[0][2]["context"], ["tutorial"])
        self.assertEqual(calls[0][2]["protected_tokens"], ["[move]"])
        self.assertNotIn("Authorization", calls[0][1])

    def test_local_model_protects_rich_text_tags(self):
        calls = []

        def transport(url, headers, body, timeout):
            calls.append(json.loads(body))
            return HttpResponse(
                200,
                "application/json",
                json.dumps(
                    {
                        "translation": "提取 <b><u>装扮箱</u></b>。",
                        "provider": "local-runtime",
                        "model": "test-q4",
                        "confidence": 0.88,
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )

        provider = LocalModelTranslationProvider(
            "http://127.0.0.1:8080/translate",
            transport=transport,
            model_name="test-q4",
        )
        result = provider.translate(
            TranslationRequest(
                "line-rich-text",
                "Extract <b><u>COSMETIC BOX</u></b>.",
                "en",
                "zh-CN",
            )
        )
        self.assertEqual(result.text, "提取 <b><u>装扮箱</u></b>。")
        self.assertEqual(
            calls[0]["protected_tokens"],
            ["</b>", "</u>", "<b>", "<u>"],
        )

    def test_local_model_sends_physical_line_breaks_unchanged(self):
        calls = []

        def transport(url, headers, body, timeout):
            calls.append(json.loads(body))
            return HttpResponse(
                200,
                "application/json",
                json.dumps({"translation": "如何\n捕鱼"}, ensure_ascii=False).encode("utf-8"),
            )

        provider = LocalModelTranslationProvider(
            "http://127.0.0.1:8080/translate",
            transport=transport,
            model_name="test-q4",
        )
        result = provider.translate(
            TranslationRequest("line-break", "How to\nFish", "en", "zh-CN")
        )

        self.assertEqual(result.text, "如何\n捕鱼")
        self.assertEqual(calls[0]["text"], "How to\nFish")
        self.assertEqual(calls[0]["protected_tokens"], [])

    def test_local_model_leaves_physical_line_break_validation_to_the_router(self):
        provider = LocalModelTranslationProvider(
            "http://127.0.0.1:8080/translate",
            transport=lambda *args: HttpResponse(
                200,
                "application/json",
                json.dumps({"translation": "如何"}, ensure_ascii=False).encode("utf-8"),
            ),
            model_name="test-q4",
        )

        result = provider.translate(
            TranslationRequest("line-break", "How to\nFish", "en", "zh-CN")
        )
        self.assertEqual(result.text, "如何")

    def test_local_model_rejects_non_loopback_endpoint(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            LocalModelTranslationProvider("https://translate.example.test")

    def test_cloud_request_uses_runtime_bearer_token_and_structured_context(self):
        calls = []

        def transport(url, headers, body, timeout):
            calls.append((url, headers, json.loads(body), timeout))
            return HttpResponse(
                200,
                "application/json",
                json.dumps(
                    {
                        "translation": "你好，[name]！",
                        "provider": "test-cloud",
                        "model": "translator-v1",
                        "confidence": 0.93,
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )

        provider = CloudTranslationProvider(
            "https://api.example.test/translate",
            token_provider=lambda: "runtime-secret",
            transport=transport,
        )
        request = TranslationRequest(
            segment_id="line-1",
            text="Hello, [name]!",
            source_language="en",
            target_language="zh-CN",
            context=("Speaker: Alice",),
        )
        result = provider.translate(request)
        self.assertEqual(result.text, "你好，[name]！")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer runtime-secret")
        self.assertEqual(calls[0][2]["context"], ["Speaker: Alice"])
        self.assertNotIn("screenshot", calls[0][2])
        self.assertNotIn("runtime-secret", repr(provider.__dict__))

    def test_router_falls_back_and_rejects_placeholder_loss(self):
        bad = CloudTranslationProvider(
            "https://api.example.test/translate",
            transport=lambda *args: HttpResponse(
                200,
                "application/json",
                b'{"translation":"bad","provider":"bad","model":"v1","confidence":0.8}',
            ),
        )
        fallback = DictionaryTranslationProvider({"Hello [name]": "你好 [name]"})
        router = TranslationRouter((bad, fallback))
        request = TranslationRequest("line-1", "Hello [name]", "en", "zh-CN")
        self.assertEqual(router.translate(request).provider, "dictionary")
        self.assertTrue(router.translate(request).cached)

    def test_router_rejects_literal_newline_marker_loss(self):
        provider = DictionaryTranslationProvider({"First\\nSecond": "第一行"})
        router = TranslationRouter((provider,))
        with self.assertRaisesRegex(TranslationProviderError, "all translation providers failed"):
            router.translate(TranslationRequest("line-1", "First\\nSecond", "en", "zh-CN"))

    def test_residual_english_gate_allows_the_preserved_kg_unit_only(self):
        unit_request = TranslationRequest("unit-kg", "kg", "en", "zh-CN")
        unit_result = TranslationResult("kg", "ollama", "qwen2.5:3b", 0.3)
        self.assertNotIn(
            "residual_english",
            {issue.code for issue in translation_quality_issues(unit_request, unit_result)},
        )

        phrase_request = TranslationRequest("phrase", "Host Game", "en", "zh-CN")
        phrase_result = TranslationResult("Host Game", "ollama", "qwen2.5:3b", 0.3)
        self.assertIn(
            "residual_english",
            {issue.code for issue in translation_quality_issues(phrase_request, phrase_result)},
        )

    def test_cloud_errors_are_sanitized(self):
        provider = CloudTranslationProvider(
            "https://api.example.test/translate",
            transport=lambda *args: HttpResponse(503, "text/plain", b"upstream body"),
        )
        with self.assertRaisesRegex(TranslationProviderError, "503") as caught:
            provider.translate(TranslationRequest("1", "Hello", "en", "zh-CN"))
        self.assertNotIn("upstream body", str(caught.exception))


class TtsTests(unittest.TestCase):
    def test_cloud_tts_writes_verified_wav_without_persisting_token(self):
        wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"0" * 28
        provider = CloudTtsProvider(
            "https://api.example.test/tts",
            token_provider=lambda: "runtime-tts-secret",
            transport=lambda url, headers, body, timeout: HttpResponse(200, "audio/wav", wav),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = provider.synthesize(
                TtsRequest("你好", "zh-CN", voice="default", rate=1.0),
                Path(directory) / "speech.wav",
            )
            self.assertEqual(result.path.read_bytes(), wav)
        self.assertNotIn("runtime-tts-secret", repr(provider.__dict__))

    def test_windows_sapi_runner_receives_no_unescaped_text(self):
        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            output = Path(kwargs["output_path"])
            output.write_bytes(b"RIFF" + b"0" * 40)
            return type("Completed", (), {"returncode": 0, "stderr": ""})()

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "speech.wav"
            result = WindowsSapiTts(command_runner=runner).synthesize(
                TtsRequest("你好'; Remove-Item C:\\*", "zh-CN"),
                output,
            )
        flattened = " ".join(commands[0])
        self.assertNotIn("Remove-Item", flattened)
        self.assertEqual(result.provider, "windows-sapi")


if __name__ == "__main__":
    unittest.main()
