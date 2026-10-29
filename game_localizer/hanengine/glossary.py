"""Glossary matching for prompt injection and post-translation verification.

Two design decisions come straight from the projects reviewed in
``_research/UPSTREAMS.md``:

1. **Only inject the terms this batch actually contains.**  A game glossary can
   hold hundreds of entries; sending all of them burns context and dilutes the
   instruction.  AiNiee's ``GlossaryHelper.collect_matched_rows`` does this.
2. **Match longest first and consume what matched.**  When a glossary holds both
   ``Alice`` and ``Alice-chan``, a naive substring pass reports both for the
   same span.  GalTransl sorts by descending length and removes each match from
   the working text so a short term cannot re-match inside a longer one.

The same matcher is used for verification, so injection and checking can never
disagree about what "contains the term" means.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryTerm:
    """One source->target pair, with an optional translator note."""

    source: str
    target: str
    note: str = ""

    def __post_init__(self) -> None:
        for name in ("source", "target"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value:
                raise ValueError(f"{name} must not be empty")
        if not isinstance(self.note, str):
            raise TypeError("note must be a string")

    def to_prompt_row(self) -> str:
        note = self.note or " "
        return f"{self.source}|{self.target}|{note}"


# Terms shorter than this are not enforced.  A mined glossary legitimately
# contains unit labels like "m" / "s" / "h", and as bare substrings they match
# inside unrelated words ("Steam" contains "m"), which would reject correct
# translations.  Four characters is the shortest length at which a term is
# specific enough to be a real constraint for Latin sources; CJK terms are
# exempt because a single character there is often a whole word.
MIN_ENFORCED_TERM_LENGTH = 4


def _is_enforceable(term: GlossaryTerm) -> bool:
    """Whether a term is specific enough to gate a translation."""

    if len(term.source) >= MIN_ENFORCED_TERM_LENGTH:
        return True
    # A short CJK source is a real word, not a substring hazard.
    return any("\u3400" <= ch <= "\u9fff" for ch in term.source)


class Glossary:
    """A source->target table that matches by longest term first.

    ``case_sensitive`` defaults to False because game strings vary in casing
    (``Health`` / ``health``) while glossary entries are usually written once.
    Whole-word matching is intentionally *not* supported: CJK sources have no
    word boundaries, and a partial match is still a useful translation hint.
    """

    def __init__(
        self,
        entries: Mapping[str, str] | Iterable[GlossaryTerm],
        *,
        case_sensitive: bool = False,
    ) -> None:
        if isinstance(entries, Mapping):
            terms = [
                GlossaryTerm(source=key, target=value)
                for key, value in entries.items()
                if isinstance(key, str) and isinstance(value, str) and key and value
            ]
        else:
            terms = [term for term in entries if isinstance(term, GlossaryTerm)]
        if any(not isinstance(term, GlossaryTerm) for term in terms):
            raise TypeError("entries must contain GlossaryTerm values")
        # Longest source first: a short term must never win the span that a
        # longer term also covers.
        terms.sort(key=lambda term: (-len(term.source), term.source))
        self._terms = tuple(terms)
        self._case_sensitive = bool(case_sensitive)

    def __bool__(self) -> bool:
        return bool(self._terms)

    def __len__(self) -> int:
        return len(self._terms)

    @property
    def terms(self) -> tuple[GlossaryTerm, ...]:
        return self._terms

    def _fold(self, value: str) -> str:
        return value if self._case_sensitive else value.casefold()

    def match(self, text: str) -> tuple[GlossaryTerm, ...]:
        """Return the terms present in ``text``, longest first, no overlaps.

        Matched spans are blanked out of the working copy so that a shorter term
        contained in a longer one does not match twice.  Terms too short to be
        specific are skipped for *injection* only; see ``violations``.
        """

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text or not self._terms:
            return ()
        working = self._fold(text)
        matched: list[GlossaryTerm] = []
        for term in self._terms:
            if not _is_enforceable(term):
                continue
            needle = self._fold(term.source)
            if needle and needle in working:
                matched.append(term)
                working = working.replace(needle, "\0")
        return tuple(matched)

    def prompt_block(self, text: str, *, header: str = "###术语表") -> str:
        """Render the matched terms as a prompt section, or ``""`` when empty."""

        matched = self.match(text)
        if not matched:
            return ""
        lines = [header, "原文|译文|备注"]
        lines.extend(term.to_prompt_row() for term in matched)
        return "\n".join(lines)

    def violations(self, source: str, target: str) -> tuple[GlossaryTerm, ...]:
        """Terms whose pinned rendering must appear in ``target``.

        Only terms that make up the *whole* source string are enforced.  A term
        that merely appears inside a longer sentence is a translation *hint*,
        not a contract: the mined glossary contains 56 entries that are
        substrings of other entries ("Save" inside "Delete Save?"), and the
        official Chinese itself renders them differently in context
        ("保存" alone, "存档" in the sentence).  Enforcing those would reject
        correct translations.

        The whole-string rule is also what keeps injection and verification
        consistent: both agree that a hint inside a sentence is not binding.
        """

        if not isinstance(source, str) or not isinstance(target, str):
            raise TypeError("source and target must be strings")
        if not target.strip():
            return ()
        missing = []
        for term in self.enforceable_terms(source):
            if self._fold(term.target) not in self._fold(target):
                missing.append(term)
        return tuple(missing)

    def enforceable_terms(self, source: str) -> tuple[GlossaryTerm, ...]:
        """Terms that bind this source string, i.e. it *is* the term."""

        if not isinstance(source, str):
            raise TypeError("source must be a string")
        folded = self._fold(source.strip())
        if not folded:
            return ()
        return tuple(
            term
            for term in self._terms
            if _is_enforceable(term) and self._fold(term.source.strip()) == folded
        )


__all__ = ["Glossary", "GlossaryTerm"]
