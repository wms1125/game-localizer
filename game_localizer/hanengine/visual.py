from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import math
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .translation import TranslationProvider, TranslationRequest


DEFAULT_OCR_RESIDUAL_ALLOWLIST = ("english", "ren'py")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_PATHLIKE_RE = re.compile(r"^[A-Za-z0-9_.:/\\-]+$")


@dataclass(frozen=True)
class OcrBox:
    x: int
    y: int
    width: int
    height: int
    text: str
    confidence: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("OCR box dimensions must be positive")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("OCR text must not be empty")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("OCR confidence must be in [0.0, 1.0]")


@dataclass(frozen=True)
class OcrFrame:
    boxes: tuple[OcrBox, ...]
    background_fingerprint: str

    def __post_init__(self) -> None:
        if isinstance(self.boxes, (str, bytes)):
            raise TypeError("boxes must be ordered")
        boxes = tuple(self.boxes)
        if any(not isinstance(box, OcrBox) for box in boxes):
            raise TypeError("boxes must contain OcrBox values")
        if not isinstance(self.background_fingerprint, str) or not self.background_fingerprint:
            raise ValueError("background_fingerprint must not be empty")
        object.__setattr__(self, "boxes", boxes)


def detect_english_residuals(
    frame: OcrFrame,
    *,
    allowlist: Iterable[str] = (),
    minimum_confidence: float = 0.80,
) -> tuple[OcrBox, ...]:
    """Return OCR boxes that look like untranslated natural-language English."""

    if not isinstance(frame, OcrFrame):
        raise TypeError("frame must be an OcrFrame")
    if (
        isinstance(minimum_confidence, bool)
        or not isinstance(minimum_confidence, (int, float))
        or not 0.0 <= minimum_confidence <= 1.0
    ):
        raise ValueError("minimum_confidence must be in [0.0, 1.0]")
    if isinstance(allowlist, (str, bytes)):
        raise TypeError("allowlist must be an iterable of strings")
    normalized_allowlist = set(DEFAULT_OCR_RESIDUAL_ALLOWLIST)
    for value in allowlist:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("allowlist must contain non-empty strings")
        normalized_allowlist.add(" ".join(value.split()).casefold())

    residuals: list[OcrBox] = []
    for box in frame.boxes:
        if box.confidence < minimum_confidence:
            continue
        normalized = " ".join(box.text.split()).casefold()
        residual_candidate = normalized
        for allowed in sorted(normalized_allowlist, key=len, reverse=True):
            residual_candidate = residual_candidate.replace(allowed, " ")
        words = _LATIN_WORD_RE.findall(residual_candidate)
        original_words = _LATIN_WORD_RE.findall(box.text)
        if not words or normalized in normalized_allowlist:
            continue
        if _PATHLIKE_RE.fullmatch(box.text.strip()) and any(
            marker in box.text for marker in "_./:\\"
        ):
            continue
        if all(word.isupper() for word in original_words) and len(
            "".join(original_words)
        ) <= 5:
            continue
        residuals.append(box)
    return tuple(residuals)


@dataclass(frozen=True)
class OverlayText:
    x: int
    y: int
    width: int
    height: int
    text: str
    confidence: float


def _iou(first: OcrBox, second: OcrBox) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    intersection = max(0, right - left) * max(0, bottom - top)
    union = first.width * first.height + second.width * second.height - intersection
    return intersection / union if union else 0.0


class VisualReplacementEngine:
    """Frame-stability gate for same-position replacement.

    It intentionally stores OCR geometry/text and hashes only; raw screenshots never
    enter the session state.
    """

    def __init__(self, *, stable_threshold: float = 0.85, confidence_threshold: float = 0.80, stable_frames: int = 3):
        if not 0.0 <= confidence_threshold <= 1.0 or not 0.0 <= stable_threshold <= 1.0:
            raise ValueError("stability thresholds must be in [0.0, 1.0]")
        if stable_frames < 1:
            raise ValueError("stable_frames must be positive")
        self._stable_threshold = stable_threshold
        self._confidence_threshold = confidence_threshold
        self._stable_frames = stable_frames
        self._previous: OcrFrame | None = None
        self._counts: list[int] = []

    def process(self, frame: OcrFrame, translations: Mapping[str, str]) -> tuple[OverlayText, ...]:
        if not isinstance(frame, OcrFrame):
            raise TypeError("frame must be an OcrFrame")
        if not isinstance(translations, Mapping):
            raise TypeError("translations must be a mapping")
        previous = self._previous
        next_counts: list[int] = []
        overlays: list[OverlayText] = []
        for index, box in enumerate(frame.boxes):
            old = previous.boxes[index] if previous is not None and index < len(previous.boxes) else None
            if old is None:
                score = 1.0
            else:
                geometry = _iou(old, box)
                text_stability = 1.0 if old.text == box.text else 0.0
                background = 1.0 if previous and previous.background_fingerprint == frame.background_fingerprint else 0.0
                score = 0.4 * geometry + 0.3 * text_stability + 0.3 * background
            prior_count = self._counts[index] if index < len(self._counts) else 0
            count = (prior_count + 1) if score >= self._stable_threshold else (1 if score >= 0.65 else 0)
            next_counts.append(count)
            translated = translations.get(box.text)
            if count >= self._stable_frames and box.confidence >= self._confidence_threshold and translated:
                overlays.append(OverlayText(box.x, box.y, box.width, box.height, translated, box.confidence))
        self._previous = frame
        self._counts = next_counts
        return tuple(overlays)

    def clear(self) -> None:
        self._previous = None
        self._counts = []


class OcrProvider(Protocol):
    def recognize(self, image: object, *, language: str) -> OcrFrame: ...


def _image_fingerprint(image: object) -> str:
    digest = hashlib.sha256()
    digest.update(repr(getattr(image, "mode", None)).encode("utf-8"))
    digest.update(b"|")
    digest.update(repr(getattr(image, "size", None)).encode("utf-8"))
    tobytes = getattr(image, "tobytes", None)
    if callable(tobytes):
        try:
            digest.update(b"|")
            digest.update(tobytes())
        except Exception:
            pass
    return digest.hexdigest()


class PytesseractOcrProvider:
    provider_name = "pytesseract"

    def __init__(self, *, config: str = ""):
        self._config = config
        self._loaded: tuple[object, object] | None = None

    def _load(self):
        if self._loaded is None:
            import pytesseract
            from pytesseract import Output

            self._loaded = (pytesseract, Output)
        return self._loaded

    def available(self) -> bool:
        try:
            pytesseract, _ = self._load()
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    @property
    def provider_version(self) -> str:
        try:
            pytesseract, _ = self._load()
            return str(pytesseract.get_tesseract_version())
        except Exception:
            return "unavailable"

    def recognize(self, image: object, *, language: str) -> OcrFrame:
        try:
            pytesseract, output = self._load()
            data = pytesseract.image_to_data(image, lang=language, config=self._config, output_type=output.DICT)
        except Exception as exc:
            raise RuntimeError("local OCR provider is unavailable") from exc
        boxes: list[OcrBox] = []
        for index, text in enumerate(data.get("text", ())):
            text = str(text).strip()
            if not text:
                continue
            try:
                confidence = max(0.0, min(1.0, float(data["conf"][index]) / 100.0))
                boxes.append(OcrBox(int(data["left"][index]), int(data["top"][index]), int(data["width"][index]), int(data["height"][index]), text, confidence))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        return OcrFrame(tuple(boxes), _image_fingerprint(image))


class RapidOcrProvider:
    """Optional Chinese/English OCR provider backed by RapidOCR ONNX Runtime."""

    provider_name = "rapidocr-onnxruntime"

    def __init__(self):
        self._engine: object | None = None
        self._version: str | None = None

    def _load(self):
        if self._engine is None:
            import rapidocr_onnxruntime

            self._engine = rapidocr_onnxruntime.RapidOCR()
            try:
                self._version = importlib.metadata.version(
                    "rapidocr-onnxruntime"
                )
            except importlib.metadata.PackageNotFoundError:
                self._version = "unknown"
        return self._engine

    def available(self) -> bool:
        try:
            self._load()
            return True
        except Exception:
            return False

    @property
    def provider_version(self) -> str:
        try:
            self._load()
        except Exception:
            return "unavailable"
        return self._version or "unknown"

    def recognize(self, image: object, *, language: str) -> OcrFrame:
        if not isinstance(language, str) or not language.strip():
            raise ValueError("language must not be empty")
        try:
            result, _ = self._load()(image)
        except Exception as exc:
            raise RuntimeError("local RapidOCR provider is unavailable") from exc
        boxes: list[OcrBox] = []
        for item in result or ():
            try:
                points, text, confidence = item
                text = str(text).strip()
                xs = [float(point[0]) for point in points]
                ys = [float(point[1]) for point in points]
                left = math.floor(min(xs))
                top = math.floor(min(ys))
                right = math.ceil(max(xs))
                bottom = math.ceil(max(ys))
                confidence = max(0.0, min(1.0, float(confidence)))
                if text and right > left and bottom > top:
                    boxes.append(
                        OcrBox(
                            left,
                            top,
                            right - left,
                            bottom - top,
                            text,
                            confidence,
                        )
                    )
            except (IndexError, TypeError, ValueError):
                continue
        return OcrFrame(tuple(boxes), _image_fingerprint(image))


class PillowScreenCapture:
    def capture(self, bbox: tuple[int, int, int, int]):
        try:
            from PIL import ImageGrab

            return ImageGrab.grab(bbox=bbox, all_screens=True)
        except Exception as exc:
            raise RuntimeError("screen capture is unavailable") from exc


class VisualReplacementSession:
    def __init__(self, ocr: OcrProvider, translator: TranslationProvider, source_language: str, target_language: str, *, engine: VisualReplacementEngine | None = None):
        self._ocr = ocr
        self._translator = translator
        self._source_language = source_language
        self._target_language = target_language
        self._engine = engine or VisualReplacementEngine()

    def process_image(self, image: object) -> tuple[OverlayText, ...]:
        frame = self._ocr.recognize(image, language=self._source_language)
        translations: dict[str, str] = {}
        for box in frame.boxes:
            try:
                request = TranslationRequest(
                    "ocr:" + hashlib.sha256(box.text.encode("utf-8")).hexdigest()[:24],
                    box.text,
                    self._source_language,
                    self._target_language,
                )
                translations[box.text] = self._translator.translate(request).text
            except Exception:
                continue
        return self._engine.process(frame, translations)

    def clear(self) -> None:
        self._engine.clear()


class TkOverlayWindow:
    def __init__(self, root: object):
        import tkinter as tk

        self._window = tk.Toplevel(root)
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        self._window.configure(bg="#010101")
        self._window.attributes("-transparentcolor", "#010101")
        self._canvas = tk.Canvas(self._window, bg="#010101", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self.hide()
        self._make_click_through()

    def _make_click_through(self) -> None:
        if os.name != "nt":
            return
        hwnd = self._window.winfo_id()
        user32 = ctypes.windll.user32
        get_long = user32.GetWindowLongW
        set_long = user32.SetWindowLongW
        style = get_long(hwnd, -20)
        set_long(hwnd, -20, style | 0x00000020 | 0x00080000 | 0x00000080)

    def update(self, overlays: Iterable[OverlayText], *, origin: tuple[int, int], size: tuple[int, int]) -> None:
        overlays = tuple(overlays)
        self._window.geometry(f"{size[0]}x{size[1]}+{origin[0]}+{origin[1]}")
        self._canvas.delete("all")
        for overlay in overlays:
            self._canvas.create_rectangle(overlay.x, overlay.y, overlay.x + overlay.width, overlay.y + overlay.height, fill="#f7f3ec", outline="")
            self._canvas.create_text(overlay.x + 4, overlay.y + overlay.height // 2, anchor="w", text=overlay.text, fill="#242321", font=("Microsoft YaHei UI", max(10, min(28, overlay.height // 2))))
        self._window.deiconify() if overlays else self.hide()

    def hide(self) -> None:
        self._window.withdraw()

    def destroy(self) -> None:
        self._window.destroy()


__all__ = [
    "DEFAULT_OCR_RESIDUAL_ALLOWLIST",
    "OcrBox",
    "OcrFrame",
    "OverlayText",
    "PillowScreenCapture",
    "PytesseractOcrProvider",
    "RapidOcrProvider",
    "TkOverlayWindow",
    "VisualReplacementEngine",
    "VisualReplacementSession",
    "detect_english_residuals",
]
