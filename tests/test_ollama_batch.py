"""The bridge's batch endpoint: `n|text` in, `n|translation` out.

The protocol is deliberately line-oriented instead of JSON: a JSON envelope paid
about 30 tokens per segment for the id alone, which ate the entire saving from
packing.  What is tested here is the part that keeps that shortcut safe --
alignment by integer, and routing anything fragile back to the single path.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.ollama_translation_server import (
    MAX_BATCH_SEGMENTS,
    _batch_notes,
    _batch_request_payload,
    _batch_system_prompt,
    _parse_batch_answer,
    _translate_batch_with_ollama,
)


def _item(segment_id: str, text: str, **extra) -> dict:
    item = {
        "segment_id": segment_id,
        "text": text,
        "source_language": "en",
        "target_language": "zh-CN",
        "context": [],
        "protected_tokens": [],
        "reference_translation": None,
        "retry_instruction": "",
    }
    item.update(extra)
    return item


def _payload(*items: dict) -> dict:
    return {"segments": list(items)}


class BatchPayloadValidationTests(unittest.TestCase):
    def test_valid_batch_is_normalized_into_items(self):
        items, model = _batch_request_payload(
            {"segments": [{"segment_id": "a", "text": "Start", "source_language": "en", "target_language": "zh-CN"}], "model": "qwen2.5:3b"}
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["segment_id"], "a")
        self.assertEqual(items[0]["retry_instruction"], "")
        self.assertEqual(model, "qwen2.5:3b")

    def test_missing_segments_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "segments must be a non-empty list"):
            _batch_request_payload({})

    def test_empty_segments_list_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            _batch_request_payload({"segments": []})

    def test_duplicate_segment_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate segment_id"):
            _batch_request_payload(
                _payload(_item("a", "Start"), _item("a", "Quit"))
            )

    def test_oversized_batch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, f"at most {MAX_BATCH_SEGMENTS}"):
            _batch_request_payload(
                _payload(*(_item(f"s{index}", "Start") for index in range(MAX_BATCH_SEGMENTS + 1)))
            )

    def test_non_object_item_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"segments\[0\] must be a JSON object"):
            _batch_request_payload({"segments": ["Start"]})

    def test_per_segment_validation_still_applies(self):
        with self.assertRaisesRegex(ValueError, "segment_id must be a non-empty string"):
            _batch_request_payload(
                _payload({"text": "Start", "source_language": "en", "target_language": "zh-CN"})
            )


class BatchAnswerParsingTests(unittest.TestCase):
    def test_numbered_lines_are_parsed_in_order(self):
        parsed, broken = _parse_batch_answer("0|开始\n1|退出", (0, 1))
        self.assertEqual(parsed, {0: "开始", 1: "退出"})
        self.assertEqual(broken, [])

    def test_code_fences_and_blank_lines_are_ignored(self):
        parsed, broken = _parse_batch_answer("```\n0|开始\n\n```", (0,))
        self.assertEqual(parsed, {0: "开始"})
        self.assertEqual(broken, [])

    def test_missing_line_is_reported_as_broken(self):
        parsed, broken = _parse_batch_answer("0|开始", (0, 1))
        self.assertEqual(parsed, {0: "开始"})
        self.assertEqual(broken, [1])

    def test_out_of_range_index_is_dropped(self):
        parsed, broken = _parse_batch_answer("0|开始\n7|凭空", (0,))
        self.assertEqual(parsed, {0: "开始"})
        self.assertEqual(broken, [])

    def test_duplicate_index_keeps_the_first_and_flags_the_line(self):
        parsed, broken = _parse_batch_answer("0|开始\n0|又是开始", (0,))
        self.assertEqual(parsed, {0: "开始"})
        self.assertIn(0, broken)

    def test_full_width_separator_is_accepted(self):
        parsed, _ = _parse_batch_answer("0｜开始", (0,))
        self.assertEqual(parsed, {0: "开始"})

    def test_colon_separator_is_accepted(self):
        parsed, _ = _parse_batch_answer("0:开始", (0,))
        self.assertEqual(parsed, {0: "开始"})

    def test_empty_translation_is_broken(self):
        parsed, broken = _parse_batch_answer("0|   ", (0,))
        self.assertEqual(parsed, {})
        self.assertEqual(broken, [0])


class BatchPromptTests(unittest.TestCase):
    def test_prompt_names_the_line_format_and_the_order_rule(self):
        prompt = _batch_system_prompt("Simplified Chinese")
        self.assertIn("n|text", prompt)
        self.assertIn("n|translation", prompt)
        self.assertIn("Never merge, split, drop, or reorder", prompt)
        self.assertIn("Simplified Chinese", prompt)

    def test_notes_only_appear_when_there_is_something_to_say(self):
        self.assertEqual(_batch_notes(_item("a", "Start"), 0), "")

    def test_reference_context_and_correction_become_notes(self):
        notes = _batch_notes(
            _item(
                "a",
                "Start",
                reference_translation="开始",
                retry_instruction="be shorter",
                context=("上一句", "下一句"),
            ),
            3,
        )
        self.assertIn("# 3 reference wording", notes)
        self.assertIn("be shorter", notes)
        self.assertIn("上一句 / 下一句", notes)


class BatchTranslationTests(unittest.TestCase):
    def _run(self, items, answer):
        with patch(
            "tools.ollama_translation_server._ollama_chat_raw",
            return_value=answer,
        ) as chat:
            translations, failures = _translate_batch_with_ollama(
                ollama_url="http://127.0.0.1:11434",
                model="qwen2.5:3b",
                target_language="zh-CN",
                timeout=30.0,
                items=tuple(items),
            )
        return translations, failures, chat

    def test_aligned_answer_is_accepted(self):
        translations, failures, _ = self._run(
            [_item("a", "Start"), _item("b", "Quit")],
            "0|开始\n1|退出",
        )
        self.assertEqual(translations, {"a": "开始", "b": "退出"})
        self.assertEqual(failures, {})

    def test_segments_with_rich_text_tags_are_sent_back_to_the_single_path(self):
        translations, failures, chat = self._run(
            [_item("a", "Start"), _item("b", "<b>Quit</b>")],
            "0|开始",
        )
        self.assertEqual(failures["b"], "needs_single_request")
        # Only the eligible segment reached the model: notes and one data line.
        message = chat.call_args.kwargs["user_message"]
        self.assertEqual(message.count("\n"), 0)
        self.assertNotIn("<b>", message)

    def test_physical_newlines_are_sent_back_to_the_single_path(self):
        _, failures, _ = self._run([_item("a", "Line one\nLine two")], "0|第一行")
        self.assertEqual(failures["a"], "needs_single_request")

    def test_all_ineligible_segments_never_call_the_model(self):
        translations, failures, chat = self._run([_item("a", "<b>x</b>")], "")
        self.assertEqual(translations, {})
        self.assertEqual(failures, {"a": "needs_single_request"})
        self.assertFalse(chat.called)

    def test_missing_line_is_a_failure_not_a_guess(self):
        _, failures, _ = self._run([_item("a", "Start"), _item("b", "Quit")], "0|开始")
        self.assertEqual(failures, {"b": "batch_line_missing"})

    def test_protected_token_that_disappears_is_a_failure(self):
        _, failures, _ = self._run(
            [_item("a", "Hold {0}", protected_tokens=("{0}",))],
            "0|按住",
        )
        self.assertEqual(failures["a"], "placeholder_mismatch")

    def test_residual_english_is_a_failure(self):
        _, failures, _ = self._run([_item("a", "Quit")], "0|Quit")
        self.assertEqual(failures["a"], "residual_english")

    def test_segment_ids_are_mapped_back_from_line_numbers(self):
        translations, _, _ = self._run(
            [_item("unity:7", "Start"), _item("unity:9", "Quit")],
            "0|开始\n1|退出",
        )
        self.assertEqual(sorted(translations), ["unity:7", "unity:9"])


if __name__ == "__main__":
    unittest.main()
