"""Prove placeholder masking actually rescues segments that would otherwise fall back.

The point is not that masking exists, but that a model which mangles a raw
``{0}`` produces a *usable* translation once the token was masked.  Each case
below fails a strict comparison on the raw text and passes after masking.
"""
from __future__ import annotations

import json
import unittest

from game_localizer.hanengine.translation import (
    HttpResponse,
    LocalModelTranslationProvider,
    TranslationRequest,
    translation_quality_issues,
)
from game_localizer.hanengine.placeholders import mask_placeholders, restore_placeholders


class _FakeModel:
    """A model that rewrites the token however ``transform`` says."""

    def __init__(self, transform) -> None:
        self._transform = transform
        self.seen_text: list[str] = []

    def __call__(self, url, headers, body, timeout):
        payload = json.loads(body.decode("utf-8"))
        self.seen_text.append(payload["text"])
        translated = "按住" + self._transform(payload["text"])
        return HttpResponse(
            200,
            "application/json",
            json.dumps(
                {"translation": translated, "provider": "fake", "model": "fake", "confidence": 0.9},
                ensure_ascii=False,
            ).encode("utf-8"),
        )


def _provider(transform):
    fake = _FakeModel(transform)
    return LocalModelTranslationProvider(
        "http://127.0.0.1:9/translate", transport=fake
    ), fake


class MaskingRescuesMangledTokensTests(unittest.TestCase):
    SOURCE = "Revive (Hold {0})"

    def test_raw_token_would_fail_strict_comparison(self):
        # Baseline: a model that turns {0} into （0） breaks the contract.
        from game_localizer.hanengine.translation import _preserves_placeholders

        self.assertFalse(_preserves_placeholders(self.SOURCE, "按住（0）"))

    def test_model_never_sees_the_raw_token(self):
        provider, fake = _provider(lambda text: text.replace("Zq", "（").replace("Zx", "）"))
        request = TranslationRequest("s1", self.SOURCE, "en", "zh-CN")
        provider.translate(request)
        self.assertNotIn("{0}", fake.seen_text[0])

    def test_spaced_sentinel_is_restored(self):
        # Model pads the sentinel with spaces; restoration still finds it.
        def pad(text):
            marker = text[text.index("Zq") : text.index("Zx") + 2]
            return text.replace(marker, " " + marker + " ")

        provider, _ = _provider(pad)
        request = TranslationRequest("s1", self.SOURCE, "en", "zh-CN")
        result = provider.translate(request)
        self.assertIn("{0}", result.text)
        self.assertEqual(
            [i.code for i in translation_quality_issues(request, result)],
            [],
        )

    def test_case_flipped_sentinel_is_restored(self):
        def lower(text):
            marker = text[text.index("Zq") : text.index("Zx") + 2]
            return text.replace(marker, marker.lower())

        provider, _ = _provider(lower)
        request = TranslationRequest("s1", self.SOURCE, "en", "zh-CN")
        result = provider.translate(request)
        self.assertIn("{0}", result.text)

    def test_untouched_sentinel_round_trips(self):
        provider, _ = _provider(lambda text: text)
        request = TranslationRequest("s1", self.SOURCE, "en", "zh-CN")
        result = provider.translate(request)
        self.assertIn("{0}", result.text)
        self.assertEqual(
            [i.code for i in translation_quality_issues(request, result)],
            [],
        )

    def test_dropped_sentinel_still_fails_the_gate(self):
        # Masking must not let a genuinely lost placeholder through.
        def drop(text):
            marker = text[text.index("Zq") : text.index("Zx") + 2]
            return text.replace(marker, "")

        provider, _ = _provider(drop)
        request = TranslationRequest("s1", self.SOURCE, "en", "zh-CN")
        result = provider.translate(request)
        self.assertNotIn("{0}", result.text)
        codes = {i.code for i in translation_quality_issues(request, result)}
        self.assertIn("placeholder_mismatch", codes)


class MaskRoundTripTests(unittest.TestCase):
    def test_multiple_tokens_survive_one_round_trip(self):
        source = "{name} wants [item] now"
        masked = mask_placeholders(source, ("{name}", "[item]"))
        self.assertEqual(restore_placeholders(masked, masked.text), source)

    def test_percent_placeholder_round_trips(self):
        source = "Dealt %s damage"
        masked = mask_placeholders(source, ("%s",))
        self.assertEqual(restore_placeholders(masked, masked.text), source)


if __name__ == "__main__":
    unittest.main()
