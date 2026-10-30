"""Placeholder masking: swap tokens for sentinel text the model will not touch.

The problem this solves: a model asked to translate ``Revive (Hold {0})`` often
returns ``复活(按住{0})`` (fine) but also ``复活（长按 {0} ）`` with the brace
moved, or ``复活(按住0)`` with the braces dropped.  A strict multiset comparison
then rejects a translation that is actually correct.

XUnity.AutoTranslator takes a different route: replace each token with a short
alphanumeric sentinel (``ZMxZ``), translate, then restore the original token with
an *approximate* match that tolerates spaces, case changes and characters the
model inserted between the sentinel letters.

HanEngine keeps the strict check as the final authority - the candidate still has
to carry exactly the right tokens - but masking makes the model's job easier, so
far fewer segments need to fall back.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# Sentinels are three letters around a digit-free marker.  The pattern is chosen
# so a model treats it as an opaque identifier rather than as words to translate:
# no vowels, no dictionary word, and no CJK.
_SENTINEL_PREFIX = "Zq"
_SENTINEL_SUFFIX = "Zx"
_SENTINEL_RE = re.compile(r"Zq[A-Za-z]\d*Zx")

# Letters used inside sentinels.  Ambiguous glyphs are avoided so an OCR-ish or
# lossy round trip does not turn one sentinel into another.
_SENTINEL_ALPHABET = "BCDFGHJKLMNPQRSTVWX"

# A truncated or otherwise mangled sentinel: the prefix, plus at most one letter.
_SENTINEL_FRAGMENT_RE = re.compile(r"Zq[A-Za-z]?")


@dataclass(frozen=True)
class MaskedText:
    """A source string with its protected tokens replaced by sentinels."""

    text: str
    tokens: tuple[str, ...]

    def restore(self, translated: str) -> str:
        """Put the original tokens back, tolerating model noise.

        Falls back to the masked form when a sentinel cannot be located, so the
        caller can still see what the model produced and let the strict quality
        gate decide.
        """

        if not isinstance(translated, str):
            raise TypeError("translated must be a string")
        restored = translated
        for index, token in enumerate(self.tokens):
            sentinel = _sentinel_for(index)
            restored = _restore_one(restored, sentinel, token)
        return restored


def _sentinel_for(index: int) -> str:
    letter = _SENTINEL_ALPHABET[index % len(_SENTINEL_ALPHABET)]
    cycle = index // len(_SENTINEL_ALPHABET)
    if cycle == 0:
        return f"{_SENTINEL_PREFIX}{letter}{_SENTINEL_SUFFIX}"
    return f"{_SENTINEL_PREFIX}{letter}{cycle}{_SENTINEL_SUFFIX}"


def _restore_one(text: str, sentinel: str, token: str) -> str:
    """Replace ``sentinel`` with ``token``, allowing separators inside it."""

    if sentinel in text:
        return text.replace(sentinel, token)
    # The model may have inserted spaces or punctuation between the sentinel
    # letters, or changed their case.  Match the letters in order, ignoring
    # anything that is not a letter between them.
    letters = [ch for ch in sentinel if ch.isalpha()]
    pattern = (
        r"(?i)"
        + r"[\s\-_.·]*".join(re.escape(ch) for ch in letters)
    )
    match = re.search(pattern, text)
    if match is None:
        return text
    return text[: match.start()] + token + text[match.end() :]


def mask_placeholders(text: str, tokens: tuple[str, ...]) -> MaskedText:
    """Replace each occurrence of each token with a unique sentinel.

    Repeated tokens get distinct sentinels so that a translation which reorders
    or duplicates them is still recoverable one occurrence at a time.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if any(not isinstance(token, str) or not token for token in tokens):
        raise ValueError("tokens must be non-empty strings")
    if not tokens:
        return MaskedText(text, ())

    # Longest first: "{0}" must not be consumed inside "{{0}}".
    ordered = sorted(set(tokens), key=lambda item: (-len(item), item))
    occurrences: list[str] = []
    masked = text
    for token in ordered:
        while token in masked:
            index = len(occurrences)
            sentinel = _sentinel_for(index)
            masked = masked.replace(token, sentinel, 1)
            occurrences.append(token)
    return MaskedText(masked, tuple(occurrences))


def restore_placeholders(masked: MaskedText, translated: str) -> str:
    """Inverse of :func:`mask_placeholders`."""

    return masked.restore(translated)


def sentinel_count(value: str) -> int:
    """How many sentinels a string still contains."""

    return len(_SENTINEL_RE.findall(value))


def sentinel_fragment_count(value: str) -> int:
    """How many sentinel *fragments* a string contains.

    A model that truncates ``ZqBZx`` into ``ZqB`` leaves a marker that cannot be
    restored, and the strict token check would not notice because the original
    token is simply gone.  Counting the bare prefix catches that case before the
    text is shipped.  Case sensitive on purpose: ``Zq`` does not occur in English.
    """

    leftover = _SENTINEL_RE.sub("", value)
    return len(_SENTINEL_FRAGMENT_RE.findall(leftover))


__all__ = [
    "MaskedText",
    "mask_placeholders",
    "restore_placeholders",
    "sentinel_count",
    "sentinel_fragment_count",
]
