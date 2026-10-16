import json
import tempfile
import unittest
from pathlib import Path

from game_localizer.hanengine.translation import (
    CloudTranslationProvider,
    DictionaryTranslationProvider,
    HttpResponse,
    TranslationProviderError,
    TranslationRequest,
    TranslationRouter,
)
from game_localizer.hanengine.tts import CloudTtsProvider, TtsRequest, WindowsSapiTts


class CloudTranslationTests(unittest.TestCase):
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
