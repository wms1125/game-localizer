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


class RichTextBodyDuplicationTests(unittest.TestCase):
    """A shipped candidate carried 14 self-repeating rich-text segments past a
    'passed' quality gate because only tag order was compared."""

    # Real defect text taken from
    # experiments/reference-l3-v3/candidate-final (How to Fish, zh-CN table).
    SHIPPED_DEFECTS = (
        (
            "take this <color=#FFEF4D><b>empty beer can</color></b> and attach it to your rod",
            "拿上这个空酒罐，把它挂在钓竿上。 <color=#FFEF4D><b>拿上这个空酒罐，把它挂在钓竿上。</color></b> 并将它挂在钓竿上。",
        ),
        (
            "it really likes <color=#FFEF4D><b>leeches</color></b>. if you get me some, I can make them into bait for you",
            "它特别喜欢蚂蝗，要是你能弄来一些，我就能替你做出合适的饵料。 <color=#FFEF4D><b>它特别喜欢蚂蝗，要是你能弄来一些，我就能替你做出合适的饵料。</color></b>. 如果你弄来一些，我可以做成饵料给你。",
        ),
        (
            "there's a <color=#FFEF4D><b>scary fish</color></b> in the ocean. I'm too afraid to step in",
            "海里有一条可怕的鱼，我可不敢下水。 <color=#FFEF4D><b>可怕的鱼吓我了，我可不敢下水。</color></b> 海里有一条可怕的鱼，我可不敢下水。",
        ),
    )

    def test_shipped_defects_are_now_rejected(self):
        for source, target in self.SHIPPED_DEFECTS:
            with self.subTest(target=target[:24]):
                issues = translation_quality_issues(_request(source), _result(target))
                self.assertIn(
                    "rich_text_body_duplication",
                    {issue.code for issue in issues},
                )

    def test_defect_is_an_error_not_a_warning(self):
        source, target = self.SHIPPED_DEFECTS[0]
        codes = {
            issue.code: issue.severity
            for issue in translation_quality_issues(_request(source), _result(target))
        }
        self.assertEqual(codes.get("rich_text_body_duplication"), "error")

    def test_defect_is_in_the_pipeline_fallback_set(self):
        from game_localizer.hanengine.pipeline import FALLBACK_ERROR_CODES

        self.assertIn("rich_text_body_duplication", FALLBACK_ERROR_CODES)

    def test_correct_rich_text_translation_still_passes(self):
        issues = translation_quality_issues(
            _request("take this <color=#FFEF4D><b>empty beer can</color></b> and attach it to your rod"),
            _result("拿上这个<color=#FFEF4D><b>空酒罐</color></b>，把它挂在钓竿上。"),
        )
        self.assertNotIn(
            "rich_text_body_duplication",
            {issue.code for issue in issues},
        )

    def test_legitimate_repetition_is_not_flagged(self):
        # Deliberate onomatopoeia is shorter than the run threshold.
        issues = translation_quality_issues(
            _request("yum yum yum <color=#FFEF4D><b>tasty</color></b>"),
            _result("好吃好吃好吃，<color=#FFEF4D><b>真香</color></b>"),
        )
        self.assertNotIn(
            "rich_text_body_duplication",
            {issue.code for issue in issues},
        )

    def test_untagged_segments_are_not_scanned(self):
        # Without inline tags the duplication pattern does not occur, and the
        # check must not fire on ordinary repeated dialogue.
        issues = translation_quality_issues(
            _request("go go go go"),
            _result("走啊走啊走啊走啊"),
        )
        self.assertNotIn(
            "rich_text_body_duplication",
            {issue.code for issue in issues},
        )


class GarbledCharacterTests(unittest.TestCase):
    """U+FFFD is unrecoverable and must never reach a candidate."""

    def test_replacement_character_is_an_error(self):
        issues = translation_quality_issues(_request("Hello"), _result("你好\ufffd\ufffd"))
        codes = {issue.code: issue.severity for issue in issues}
        self.assertEqual(codes.get("garbled_replacement_character"), "error")

    def test_single_replacement_character_is_enough(self):
        issues = translation_quality_issues(_request("Hello"), _result("你\ufffd好"))
        self.assertIn("garbled_replacement_character", {i.code for i in issues})

    def test_clean_translation_is_not_flagged(self):
        issues = translation_quality_issues(_request("Hello"), _result("你好"))
        self.assertNotIn("garbled_replacement_character", {i.code for i in issues})

    def test_it_is_in_the_pipeline_fallback_set(self):
        from game_localizer.hanengine.pipeline import FALLBACK_ERROR_CODES

        self.assertIn("garbled_replacement_character", FALLBACK_ERROR_CODES)


class GlossaryViolationTests(unittest.TestCase):
    """A pinned term is a deterministic contract, not a suggestion.

    Only a segment that *is* the term is enforced.  A term inside a longer
    sentence is a hint, because the game's own Chinese renders those differently
    in context.
    """

    def _request_with_glossary(self, text, terms):
        from game_localizer.hanengine.glossary import Glossary

        glossary = Glossary(terms)
        return TranslationRequest(
            "unity:1",
            text,
            "en",
            "zh-CN",
            glossary=glossary.match(text),
            enforced_terms=glossary.enforceable_terms(text),
        )

    def test_ignored_term_is_an_error(self):
        request = self._request_with_glossary("Coconut", {"Coconut": "椰子"})
        issues = translation_quality_issues(request, _result("坚果"))
        codes = {i.code: i.severity for i in issues}
        self.assertEqual(codes.get("glossary_violation"), "error")

    def test_used_term_passes(self):
        request = self._request_with_glossary("Coconut", {"Coconut": "椰子"})
        issues = translation_quality_issues(request, _result("椰子"))
        self.assertNotIn("glossary_violation", {i.code for i in issues})

    def test_request_without_glossary_is_not_checked(self):
        issues = translation_quality_issues(_request("Coconut"), _result("坚果"))
        self.assertNotIn("glossary_violation", {i.code for i in issues})

    def test_term_inside_a_sentence_is_not_enforced(self):
        # "Delete Save?" is officially 删除存档吗？, not 保存.
        request = self._request_with_glossary("Delete Save?", {"Save": "保存"})
        issues = translation_quality_issues(request, _result("删除存档吗？"))
        self.assertNotIn("glossary_violation", {i.code for i in issues})

    def test_only_terms_present_in_source_are_enforced(self):
        request = self._request_with_glossary(
            "Coconut", {"Coconut": "椰子", "Boss": "首领"}
        )
        issues = translation_quality_issues(request, _result("椰子"))
        self.assertNotIn("glossary_violation", {i.code for i in issues})

    def test_it_is_in_the_pipeline_fallback_set(self):
        from game_localizer.hanengine.pipeline import FALLBACK_ERROR_CODES

        self.assertIn("glossary_violation", FALLBACK_ERROR_CODES)

    def test_payload_carries_only_matched_terms(self):
        from game_localizer.hanengine.glossary import Glossary

        glossary = Glossary({"Coconut": "椰子", "Boss Left": "怪物已离开"})
        matched = glossary.match("grab the coconut")
        self.assertEqual([t.source for t in matched], ["Coconut"])


if __name__ == "__main__":
    unittest.main()
