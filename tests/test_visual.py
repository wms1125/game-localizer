import unittest
from unittest.mock import patch

from game_localizer.hanengine.translation import TranslationResult, TranslationRequest
from game_localizer.hanengine.visual import (
    OcrBox,
    OcrFrame,
    VisualReplacementEngine,
    VisualReplacementSession,
)


class FakeOcr:
    def __init__(self, frame):
        self.frame = frame

    def recognize(self, image, *, language):
        return self.frame


class FakeTranslator:
    def translate(self, request: TranslationRequest):
        return TranslationResult("你好", "fake", "test", 0.99)


class VisualTests(unittest.TestCase):
    def box(self, text="Hello"):
        return OcrBox(10, 20, 100, 30, text, 0.98)

    def test_stability_requires_three_frames_and_clears_on_motion(self):
        engine = VisualReplacementEngine()
        frame = OcrFrame((self.box(),), "background-a")
        self.assertEqual(engine.process(frame, {"Hello": "你好"}), ())
        self.assertEqual(engine.process(frame, {"Hello": "你好"}), ())
        visible = engine.process(frame, {"Hello": "你好"})
        self.assertEqual(visible[0].text, "你好")
        moved = OcrFrame((OcrBox(400, 400, 100, 30, "Hello", 0.98),), "background-b")
        self.assertEqual(engine.process(moved, {"Hello": "你好"}), ())

    def test_low_confidence_and_missing_translation_never_draw(self):
        engine = VisualReplacementEngine()
        frame = OcrFrame((OcrBox(0, 0, 10, 10, "Hello", 0.2),), "bg")
        for _ in range(5):
            self.assertEqual(engine.process(frame, {}), ())

    def test_session_does_not_persist_raw_image(self):
        frame = OcrFrame((self.box(),), "bg")
        session = VisualReplacementSession(FakeOcr(frame), FakeTranslator(), "en", "zh-CN")
        outputs = [session.process_image(object()) for _ in range(3)]
        self.assertEqual(outputs[-1][0].text, "你好")
        self.assertFalse(any(isinstance(value, (bytes, bytearray)) for value in session.__dict__.values()))

    def test_ocr_provider_reports_missing_binary_cleanly(self):
        from game_localizer.hanengine.visual import PytesseractOcrProvider

        provider = PytesseractOcrProvider()
        with patch.object(provider, "_load", side_effect=RuntimeError("not installed")):
            self.assertFalse(provider.available())


if __name__ == "__main__":
    unittest.main()
