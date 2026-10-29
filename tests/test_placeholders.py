from __future__ import annotations

import unittest

from game_localizer.hanengine.placeholders import (
    mask_placeholders,
    restore_placeholders,
    sentinel_count,
)


class MaskingTests(unittest.TestCase):
    def test_token_is_replaced_and_restored(self):
        masked = mask_placeholders("Revive (Hold {0})", ("{0}",))
        self.assertNotIn("{0}", masked.text)
        self.assertIn("Zq", masked.text)
        self.assertEqual(restore_placeholders(masked, masked.text), "Revive (Hold {0})")

    def test_no_tokens_is_a_noop(self):
        masked = mask_placeholders("plain text", ())
        self.assertEqual(masked.text, "plain text")
        self.assertEqual(masked.tokens, ())

    def test_repeated_tokens_get_distinct_sentinels(self):
        masked = mask_placeholders("{0} and {0}", ("{0}",))
        self.assertEqual(len(masked.tokens), 2)
        self.assertEqual(sentinel_count(masked.text), 2)
        self.assertEqual(restore_placeholders(masked, masked.text), "{0} and {0}")

    def test_longest_token_is_masked_first(self):
        # "{{0}}" must not be consumed by the "{0}" pass.
        masked = mask_placeholders("a {{0}} b {0}", ("{0}", "{{0}}"))
        self.assertEqual(masked.tokens, ("{{0}}", "{0}"))
        self.assertEqual(restore_placeholders(masked, masked.text), "a {{0}} b {0}")

    def test_multiple_distinct_tokens(self):
        masked = mask_placeholders("{name} has %s and [item]", ("{name}", "%s", "[item]"))
        self.assertEqual(len(masked.tokens), 3)
        self.assertEqual(
            restore_placeholders(masked, masked.text), "{name} has %s and [item]"
        )


class RestorationToleranceTests(unittest.TestCase):
    """The model may add spaces, change case, or reorder sentinels."""

    def test_exact_sentinel_restores(self):
        masked = mask_placeholders("Hold {0}", ("{0}",))
        self.assertEqual(restore_placeholders(masked, "按住 " + masked.text.split()[-1]), "按住 {0}")

    def test_spaces_inserted_inside_sentinel_still_restore(self):
        masked = mask_placeholders("Hold {0}", ("{0}",))
        sentinel = masked.text.split()[-1]
        noisy = " ".join(sentinel)  # "Z q B Z x"
        self.assertEqual(restore_placeholders(masked, f"按住 {noisy}"), "按住 {0}")

    def test_case_change_still_restores(self):
        masked = mask_placeholders("Hold {0}", ("{0}",))
        sentinel = masked.text.split()[-1]
        self.assertEqual(restore_placeholders(masked, sentinel.lower()), "{0}")

    def test_punctuation_between_letters_still_restores(self):
        masked = mask_placeholders("Hold {0}", ("{0}",))
        sentinel = masked.text.split()[-1]
        noisy = sentinel[0] + "-" + sentinel[1] + "." + sentinel[2:]
        self.assertEqual(restore_placeholders(masked, noisy), "{0}")

    def test_missing_sentinel_leaves_text_untouched(self):
        masked = mask_placeholders("Hold {0}", ("{0}",))
        self.assertEqual(restore_placeholders(masked, "按住"), "按住")

    def test_two_sentinels_restore_independently(self):
        masked = mask_placeholders("{a} and {b}", ("{a}", "{b}"))
        first, second = masked.text.split(" and ")
        # Reverse the order to prove each sentinel maps to its own token.
        self.assertEqual(
            restore_placeholders(masked, f"{second} and {first}"), "{b} and {a}"
        )


class SentinelShapeTests(unittest.TestCase):
    def test_sentinel_has_no_cjk_and_no_vowels(self):
        masked = mask_placeholders("x {0}", ("{0}",))
        sentinel = masked.text.split()[-1]
        self.assertFalse(any("\u3400" <= ch <= "\u9fff" for ch in sentinel))
        self.assertNotIn("A", sentinel.upper()[2:3])  # no vowel inside

    def test_many_tokens_do_not_collide(self):
        tokens = tuple(f"{{{i}}}" for i in range(30))
        text = " ".join(tokens)
        masked = mask_placeholders(text, tokens)
        self.assertEqual(len(set(masked.tokens)), 30)
        self.assertEqual(sentinel_count(masked.text), 30)
        self.assertEqual(restore_placeholders(masked, masked.text), text)


if __name__ == "__main__":
    unittest.main()
