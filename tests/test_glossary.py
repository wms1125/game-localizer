from __future__ import annotations

import unittest

from game_localizer.hanengine.glossary import Glossary, GlossaryTerm


class GlossaryMatchingTests(unittest.TestCase):
    def test_only_present_terms_match(self):
        glossary = Glossary({"Boss Left": "怪物已离开", "Coconut": "椰子"})
        matched = glossary.match("the boss left the arena")
        self.assertEqual([t.source for t in matched], ["Boss Left"])

    def test_matching_is_case_insensitive_by_default(self):
        glossary = Glossary({"Steam Relay": "Steam 中继"})
        self.assertEqual(len(glossary.match("steam relay ready")), 1)

    def test_case_sensitive_mode_respects_casing(self):
        glossary = Glossary({"Steam": "Steam"}, case_sensitive=True)
        self.assertEqual(glossary.match("steam"), ())
        self.assertEqual(len(glossary.match("Steam")), 1)

    def test_longest_term_wins_over_its_own_prefix(self):
        # A naive substring pass reports both terms for one span.
        glossary = Glossary({"Alice": "爱丽丝", "Alice-chan": "爱丽丝酱"})
        matched = glossary.match("hello Alice-chan")
        self.assertEqual([t.source for t in matched], ["Alice-chan"])

    def test_shorter_term_still_matches_elsewhere(self):
        glossary = Glossary({"Alice": "爱丽丝", "Alice-chan": "爱丽丝酱"})
        matched = glossary.match("Alice met Alice-chan")
        self.assertEqual(
            sorted(t.source for t in matched), ["Alice", "Alice-chan"]
        )

    def test_no_match_returns_empty(self):
        glossary = Glossary({"Coconut": "椰子"})
        self.assertEqual(glossary.match("nothing here"), ())

    def test_empty_glossary_is_falsy(self):
        glossary = Glossary({})
        self.assertFalse(glossary)
        self.assertEqual(len(glossary), 0)

    def test_non_string_entries_are_dropped(self):
        glossary = Glossary({"Keep": "保留", "": "x", "Bad": 1})
        self.assertEqual([t.source for t in glossary.terms], ["Keep"])


class GlossaryPromptTests(unittest.TestCase):
    def test_prompt_block_lists_only_matched_terms(self):
        glossary = Glossary({"Coconut": "椰子", "Boss Left": "怪物已离开"})
        block = glossary.prompt_block("grab the coconut")
        self.assertIn("###术语表", block)
        self.assertIn("原文|译文|备注", block)
        self.assertIn("Coconut|椰子", block)
        self.assertNotIn("Boss Left", block)

    def test_prompt_block_is_empty_without_matches(self):
        glossary = Glossary({"Coconut": "椰子"})
        self.assertEqual(glossary.prompt_block("nothing"), "")

    def test_missing_note_renders_a_placeholder(self):
        glossary = Glossary({"Coconut": "椰子"})
        self.assertIn("Coconut|椰子|", glossary.prompt_block("coconut"))


class GlossaryVerificationTests(unittest.TestCase):
    def test_used_term_is_not_a_violation(self):
        glossary = Glossary({"Coconut": "椰子"})
        self.assertEqual(glossary.violations("Coconut", "椰子"), ())

    def test_ignored_term_is_a_violation(self):
        glossary = Glossary({"Coconut": "椰子"})
        missing = glossary.violations("Coconut", "坚果")
        self.assertEqual([t.source for t in missing], ["Coconut"])

    def test_violations_are_limited_to_terms_in_the_source(self):
        glossary = Glossary({"Coconut": "椰子", "Boss Left": "怪物已离开"})
        missing = glossary.violations("Coconut", "坚果")
        self.assertEqual([t.source for t in missing], ["Coconut"])

    def test_a_term_inside_a_sentence_is_only_a_hint(self):
        # The mined glossary contains 56 entries that are substrings of other
        # entries, and the game's own Chinese renders them differently in
        # context: "Save" alone is 保存, but "Delete Save?" is 删除存档吗？
        # Enforcing the in-sentence form would reject the official translation.
        glossary = Glossary({"Save": "保存"})
        self.assertEqual(glossary.violations("Delete Save?", "删除存档吗？"), ())
        self.assertEqual(len(glossary.match("Delete Save?")), 1)

    def test_whole_string_match_is_enforced(self):
        glossary = Glossary({"Save": "保存"})
        self.assertEqual(
            [t.source for t in glossary.violations("Save", "存档")], ["Save"]
        )

    def test_enforceable_terms_requires_the_whole_string(self):
        glossary = Glossary({"Save": "保存", "Coconut": "椰子"})
        self.assertEqual(
            [t.source for t in glossary.enforceable_terms("Coconut")], ["Coconut"]
        )
        self.assertEqual(glossary.enforceable_terms("a coconut"), ())

    def test_enforceable_terms_ignores_surrounding_whitespace(self):
        glossary = Glossary({"Coconut": "椰子"})
        self.assertEqual(len(glossary.enforceable_terms("  Coconut  ")), 1)

    def test_empty_target_is_not_judged(self):
        glossary = Glossary({"Coconut": "椰子"})
        self.assertEqual(glossary.violations("Coconut", "  "), ())

    def test_verification_uses_the_same_matcher_as_injection(self):
        # The overlap rule must not make injection and verification disagree.
        glossary = Glossary({"Alice": "爱丽丝", "Alice-chan": "爱丽丝酱"})
        self.assertEqual(glossary.match("Alice-chan"), (glossary.terms[0],))
        self.assertEqual(glossary.violations("Alice-chan", "爱丽丝酱"), ())

    def test_short_terms_are_not_enforced(self):
        # "m" / "s" / "h" are unit labels in the mined glossary and match inside
        # unrelated words; they must never gate a translation.
        glossary = Glossary({"m": "分", "s": "秒"})
        self.assertEqual(glossary.match("Waiting for Steam..."), ())
        self.assertEqual(glossary.violations("m", "分"), ())

    def test_short_cjk_terms_are_still_enforced(self):
        glossary = Glossary({"鱼": "鱼"})
        self.assertEqual(len(glossary.enforceable_terms("鱼")), 1)


class GlossaryTermTests(unittest.TestCase):
    def test_empty_source_is_rejected(self):
        with self.assertRaises(ValueError):
            GlossaryTerm(source="", target="x")

    def test_empty_target_is_rejected(self):
        with self.assertRaises(ValueError):
            GlossaryTerm(source="x", target="")

    def test_prompt_row_has_three_columns(self):
        self.assertEqual(
            GlossaryTerm("Coconut", "椰子", "fish bait").to_prompt_row(),
            "Coconut|椰子|fish bait",
        )


if __name__ == "__main__":
    unittest.main()
