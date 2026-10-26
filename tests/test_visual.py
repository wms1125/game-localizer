import unittest
from unittest.mock import patch

from game_localizer.hanengine.translation import TranslationResult, TranslationRequest
from game_localizer.hanengine.visual import (
    DEFAULT_OCR_RESIDUAL_ALLOWLIST,
    OcrBox,
    OcrFrame,
    VisualReplacementEngine,
    VisualReplacementSession,
    detect_english_residuals,
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

    def test_ocr_residual_detection_skips_allowlisted_brands_and_paths(self):
        frame = OcrFrame(
            (
                self.box("Start game"),
                self.box(DEFAULT_OCR_RESIDUAL_ALLOWLIST[0]),
                self.box("Ren'Py"),
                self.box("save/file.json"),
                self.box("HP"),
            ),
            "bg",
        )

        residuals = detect_english_residuals(frame)

        self.assertEqual([box.text for box in residuals], ["Start game"])

    def test_ocr_residual_detection_accepts_explicit_language_allowlist(self):
        frame = OcrFrame((self.box("Español"),), "bg")

        self.assertEqual(
            detect_english_residuals(frame, allowlist=("Español",)),
            (),
        )

    def test_ocr_residual_detection_allows_brand_joined_to_chinese(self):
        frame = OcrFrame((self.box("Ren'Py7+版本"),), "bg")

        self.assertEqual(detect_english_residuals(frame), ())

    def test_ocr_residual_detection_still_flags_text_after_allowlisted_brand(self):
        frame = OcrFrame((self.box("Ren'Py Start game"),), "bg")

        self.assertEqual(
            [box.text for box in detect_english_residuals(frame)],
            ["Ren'Py Start game"],
        )

    def test_rapidocr_provider_maps_quadrilateral_to_box(self):
        from game_localizer.hanengine.visual import RapidOcrProvider

        provider = RapidOcrProvider()
        provider._engine = lambda image: (
            [([[10.2, 20.8], [30.9, 20.1], [31.1, 40.2], [10.0, 40.9]], "你好", 0.96)],
            [0.1, 0.2, 0.3],
        )

        frame = provider.recognize(object(), language="chi_sim+eng")

        self.assertEqual(frame.boxes, (OcrBox(10, 20, 22, 21, "你好", 0.96),))

    def test_ocr_residual_detection_ignores_low_confidence_text(self):
        frame = OcrFrame((OcrBox(10, 20, 100, 30, "Start game", 0.79),), "bg")

        self.assertEqual(detect_english_residuals(frame), ())

    def test_ocr_residual_detection_rejects_invalid_minimum_confidence(self):
        frame = OcrFrame((self.box("Start game"),), "bg")

        for value in (-0.01, 1.01, True, "0.80"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "minimum_confidence"):
                    detect_english_residuals(frame, minimum_confidence=value)


if __name__ == "__main__":
    unittest.main()
