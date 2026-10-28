from __future__ import annotations

import unittest

from game_localizer.hanengine.translation import (
    TranslationRequest,
    TranslationResult,
    translation_quality_issues,
    with_terminal_punctuation,
)


def _request(text: str, reference: str | None = None) -> TranslationRequest:
    return TranslationRequest(
        "unity:1",
        text,
        "en",
        "zh-CN",
        reference_translation=reference,
    )


def _result(text: str) -> TranslationResult:
    return TranslationResult(text, "local-model", "qwen2.5:3b", 0.9)


class MixedLanguageDetectionTests(unittest.TestCase):
    def test_single_leftover_english_word_is_an_error(self):
        issues = translation_quality_issues(_request("take the lighter"), _result("拿 lighter"))
        codes = {issue.code: issue.severity for issue in issues}
        self.assertEqual(codes.get("residual_english"), "error")

    def test_allowlisted_tokens_do_not_trigger(self):
        for text in ("去找NPC角色", "重 5 kg 的物品", "正在连接 Steam..."):
            with self.subTest(text=text):
                issues = translation_quality_issues(_request("source"), _result(text))
                self.assertNotIn("residual_english", {issue.code for issue in issues})

    def test_placeholders_and_rich_text_are_ignored(self):
        issues = translation_quality_issues(
            _request("Insert <color=#FFEF4D><b>drip creature</color></b> to play"),
            _result("投入<color=#FFEF4D><b>极品动物</color></b>后摇奖{0}"),
        )
        self.assertNotIn("residual_english", {issue.code for issue in issues})

    def test_pure_english_result_is_still_an_error(self):
        issues = translation_quality_issues(_request("yum yummy"), _result("yum yummy"))
        self.assertIn("residual_english", {issue.code for issue in issues})

    def test_short_changed_english_output_without_cjk_is_an_error(self):
        # Cod→Code previously slipped through the >=3-word threshold.
        issues = translation_quality_issues(_request("Cod"), _result("Code"))
        self.assertIn("residual_english", {issue.code for issue in issues})

    def test_digit_only_output_is_allowed(self):
        issues = translation_quality_issues(_request("360"), _result("360"))
        self.assertNotIn("residual_english", {issue.code for issue in issues})


class TerminalPunctuationTests(unittest.TestCase):
    def test_appends_punctuation_matching_reference(self):
        fixed = with_terminal_punctuation(
            _request("Creature Caught!", reference="捕获动物！"),
            _result("捕获生物"),
        )
        self.assertEqual(fixed.text, "捕获生物！")

    def test_maps_half_width_reference_punctuation(self):
        fixed = with_terminal_punctuation(
            _request("Hello, {name}!", reference=None),
            _result("你好，{name}"),
        )
        self.assertEqual(fixed.text, "你好，{name}！")

    def test_noop_when_target_already_punctuated(self):
        result = _result("捕获动物！")
        self.assertIs(with_terminal_punctuation(_request("Creature Caught!"), result), result)

    def test_noop_without_cjk_or_reference_punctuation(self):
        result = _result("plain text")
        self.assertIs(with_terminal_punctuation(_request("Creature Caught!"), result), result)
        latin = _result("捕获生物")
        self.assertIs(with_terminal_punctuation(_request("no punctuation"), latin), latin)

    def test_placeholder_tail_still_gets_punctuation(self):
        fixed = with_terminal_punctuation(
            _request("Hello, {name}!", reference=None),
            _result("你好，{name}"),
        )
        self.assertEqual(fixed.text, "你好，{name}！")

    def test_markup_tail_gets_punctuation_outside_the_markup(self):
        fixed = with_terminal_punctuation(
            _request("Creature Caught!", reference="捕获动物！"),
            _result("捕获<color=#FFEF4D><b>动物</color></b>"),
        )
        self.assertEqual(fixed.text, "捕获<color=#FFEF4D><b>动物</color></b>！")


if __name__ == "__main__":
    unittest.main()
