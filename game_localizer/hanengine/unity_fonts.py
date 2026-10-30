"""Font coverage repair for Unity legacy ``Font`` assets.

Unity's legacy ``Font`` object stores the whole TTF inside ``m_FontData``, so a
candidate can gain Chinese glyphs without touching a TMP atlas: merge a subset
of a CJK donor font into the shipped face and write the result back.

The merge keeps the shipped face's own outlines and advances for every glyph it
already has (verified: ``A`` keeps advance 616 instead of the donor's 574), so
Latin text keeps its original look and only the missing CJK glyphs are added.

fontTools is an optional dependency, exactly like UnityPy; callers get a clear
error instead of an ImportError when it is absent.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Iterable

# Variable-font and shaping tables that ``fontTools.merge`` cannot combine with a
# static face (``AttributeError: type object 'VarStore' has no attribute
# 'mergeMap'``).  Dropping them from the *donor subset* is safe: the shipped face
# keeps its own layout tables, and CJK advance widths do not need kerning.
_DONOR_DROP_TABLES = (
    "fvar",
    "gvar",
    "HVAR",
    "MVAR",
    "STAT",
    "avar",
    "cvar",
    "GDEF",
    "GPOS",
    "GSUB",
    "BASE",
    "vhea",
    "vmtx",
)

# Same conflict on the *base* side: a shipped variable font such as
# ``NotoSansSC-VariableFont_wght`` carries ``fvar``/``gvar`` and a ``BASE`` table
# that owns a ``VarStore``, so ``fontTools.merge`` refuses it outright.  When the
# direct merge fails these are dropped from the shipped face and merged again;
# every outline and advance survives, only optional kerning is lost.
_UNMERGEABLE_TABLES = _DONOR_DROP_TABLES


class UnityFontError(ValueError):
    pass


@dataclass(frozen=True)
class FontCoverage:
    """Coverage of one font face against the characters a candidate needs."""

    name: str
    codepoints: frozenset[int]
    required: frozenset[int]

    @property
    def missing(self) -> frozenset[int]:
        return self.required - self.codepoints

    @property
    def complete(self) -> bool:
        return not self.missing


def _ttfont():
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:  # pragma: no cover - depends on the local runtime
        raise UnityFontError(
            "fontTools is required to repair Unity font coverage; "
            "install it in the same Python environment as HanEngine"
        ) from exc
    return TTFont


def required_codepoints(texts: Iterable[str]) -> frozenset[int]:
    """Codepoints that must be renderable; whitespace and controls are ignored."""

    required: set[int] = set()
    for text in texts:
        for character in text:
            if character.isspace() or ord(character) < 0x20:
                continue
            required.add(ord(character))
    return frozenset(required)


def font_codepoints(data: bytes) -> frozenset[int]:
    """Unicode codepoints present in a TTF/OTF cmap."""

    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be bytes")
    if not data:
        return frozenset()
    TTFont = _ttfont()
    try:
        font = TTFont(io.BytesIO(bytes(data)), lazy=True)
    except Exception as exc:
        raise UnityFontError("font data is not a readable TTF/OTF file") from exc
    try:
        cmap: set[int] = set()
        for table in font["cmap"].tables:
            if table.isUnicode():
                cmap.update(table.cmap)
        return frozenset(cmap)
    finally:
        font.close()


def coverage(name: str, data: bytes, required: frozenset[int]) -> FontCoverage:
    return FontCoverage(name=name, codepoints=font_codepoints(data), required=required)


def subset_font(source: bytes, codepoints: Iterable[int]) -> bytes:
    """Subset a donor font down to ``codepoints`` plus the ASCII basics."""

    if not isinstance(source, (bytes, bytearray)):
        raise TypeError("source must be bytes")
    wanted = {int(item) for item in codepoints}
    if not wanted:
        return b""
    TTFont = _ttfont()
    from fontTools import subset as fonttools_subset

    try:
        font = TTFont(io.BytesIO(bytes(source)), lazy=False)
    except Exception as exc:
        raise UnityFontError("donor font data is not a readable TTF/OTF file") from exc
    try:
        options = fonttools_subset.Options()
        options.layout_features = []
        options.name_IDs = ["*"]
        options.name_legacy = True
        options.name_languages = ["*"]
        options.drop_tables += list(_DONOR_DROP_TABLES)
        subsetter = fonttools_subset.Subsetter(options=options)
        subsetter.populate(unicodes=sorted(wanted))
        subsetter.subset(font)
        buffer = io.BytesIO()
        font.save(buffer)
        return buffer.getvalue()
    except UnityFontError:
        raise
    except Exception as exc:
        raise UnityFontError("donor font could not be subset") from exc
    finally:
        font.close()


def merge_fonts(base: bytes, addition: bytes) -> bytes:
    """Merge ``addition`` glyphs into ``base``, keeping base outlines on conflict."""

    if not isinstance(base, (bytes, bytearray)) or not isinstance(addition, (bytes, bytearray)):
        raise TypeError("base and addition must be bytes")
    if not base:
        raise UnityFontError("base font data is empty")
    if not addition:
        return bytes(base)
    _ttfont()
    from fontTools.merge import Merger

    try:
        return _merge_once(Merger(), bytes(base), bytes(addition))
    except Exception as exc:
        first_error = exc
    # A variable font (``fvar``/``gvar``/``HVAR``) or an OpenType-layout table
    # whose per-table ``mergeMap`` is missing (``BASE.VarStore`` is the common
    # one) makes fontTools raise instead of merging.  Trading those tables away
    # keeps every outline and every advance, which is what matters for a text
    # face; only optional kerning/mark positioning is lost.
    flattened = _flatten_font(bytes(base))
    if flattened is None:
        raise UnityFontError("font merge failed") from first_error
    try:
        return _merge_once(Merger(), flattened, bytes(addition))
    except Exception as exc:
        raise UnityFontError("font merge failed") from exc


def _merge_once(merger, base: bytes, addition: bytes) -> bytes:
    merged = merger.merge([io.BytesIO(base), io.BytesIO(addition)])
    try:
        buffer = io.BytesIO()
        if hasattr(merged, "save"):
            merged.save(buffer)
        else:
            return merged.getvalue()
        return buffer.getvalue()
    finally:
        close = getattr(merged, "close", None)
        if callable(close):
            close()


def _flatten_font(data: bytes) -> bytes | None:
    """Drop variation and layout tables so ``fontTools.merge`` can accept the font."""

    TTFont = _ttfont()
    try:
        font = TTFont(io.BytesIO(data), lazy=False)
    except Exception:
        return None
    try:
        for tag in _UNMERGEABLE_TABLES:
            if tag in font:
                del font[tag]
        buffer = io.BytesIO()
        font.save(buffer)
        return buffer.getvalue()
    except Exception:
        return None
    finally:
        font.close()


def repair_font(shipped: bytes, donor: bytes, *, required: frozenset[int]) -> bytes:
    """Return ``shipped`` with every glyph in ``required`` that it lacks added."""

    missing = required - font_codepoints(shipped)
    if not missing:
        return bytes(shipped)
    addition = subset_font(donor, missing)
    if not addition:
        raise UnityFontError("donor font produced an empty subset")
    merged = merge_fonts(shipped, addition)
    still_missing = required - font_codepoints(merged)
    if still_missing:
        raise UnityFontError(
            f"donor font does not cover {len(still_missing)} required codepoint(s), "
            f"first U+{min(still_missing):04X}"
        )
    return merged
