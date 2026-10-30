"""Reuse a finished translation across runs, projects, and re-extractions.

Every run of HanEngine already resumes from the segment checkpoints in the
project store, so a second run of the *same* project is nearly free.  What is not
free, and what this module fixes, is everything else:

* a second game, whose "Resume", "Settings", and "Quit" were already translated
  in the first one - and should not be worded differently this time;
* a re-extraction that renumbers segments, which invalidates every checkpoint
  even though the source strings did not change;
* a run that died after 600 of 646 segments, where the last 46 should not pay for
  the first 600 a second time.

The key is the *source text*, never the segment id, which is exactly what makes
the reuse survive renumbering.  The model and a prompt version are part of the
key so that changing either one cannot silently serve stale wording - the same
lesson LunaTranslator encodes in ``result_cache_key``.

A hit is stored only after the quality gate accepted the answer, so the memory
never accumulates the rejected attempts that the repair round was called in to
fix.
"""

import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from game_localizer.hanengine.translation import (
    TranslationRequest,
    TranslationResult,
)

# Bump whenever anything that shapes the wording changes: the bridge system
# prompt, the repair instructions, the glossary rendering, or the punctuation
# rule.  A stale memory would otherwise survive a prompt rewrite and quietly
# pin the old style.
PROMPT_VERSION = "2026-10-30"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    source_hash     TEXT NOT NULL,
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    source_text     TEXT NOT NULL,
    target_text     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (source_hash, source_language, target_language, model, prompt_version)
)
"""


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MemoryEntry:
    target_text: str
    source_text: str


class TranslationMemory:
    """A SQLite-backed source-to-target store shared by every project.

    Every operation opens and closes its own connection.  Keeping one connection
    alive for the length of a run looks cheaper, but on Windows the open handle
    keeps the file locked, which breaks the ordinary case of a run whose state
    directory is a temporary folder that is deleted afterwards.
    """

    def __init__(self, path: Path):
        if not isinstance(path, Path):
            raise TypeError("path must be a Path")
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._session() as connection:
            connection.execute(_SCHEMA)

    @contextmanager
    def _session(self):
        """Yield a connection that commits on success and always closes."""

        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def close(self) -> None:
        """Kept so callers can use a uniform teardown; no handle is held."""

    def __enter__(self) -> "TranslationMemory":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def lookup(
        self,
        *,
        source_text: str,
        source_language: str,
        target_language: str,
        model: str = "",
        prompt_version: str = PROMPT_VERSION,
    ) -> MemoryEntry | None:
        with self._session() as connection:
            row = connection.execute(
                "SELECT source_text, target_text FROM translations "
                "WHERE source_hash=? AND source_language=? AND target_language=? "
                "AND model=? AND prompt_version=?",
                (
                    _hash_text(source_text),
                    source_language,
                    target_language,
                    model,
                    prompt_version,
                ),
            ).fetchone()
        if row is None:
            return None
        # A hash match with different text would mean a collision; treat the entry
        # as a miss rather than serving a translation for the wrong sentence.
        if row[0] != source_text:
            return None
        return MemoryEntry(target_text=row[1], source_text=row[0])

    def store(
        self,
        *,
        source_text: str,
        target_text: str,
        source_language: str,
        target_language: str,
        model: str = "",
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        with self._session() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO translations("
                "source_hash,source_language,target_language,model,prompt_version,"
                "source_text,target_text,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    _hash_text(source_text),
                    source_language,
                    target_language,
                    model,
                    prompt_version,
                    source_text,
                    target_text,
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                ),
            )

    def count(self) -> int:
        with self._session() as connection:
            return int(
                connection.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
            )


class MemoryTranslationProvider:
    """Serve accepted translations from memory, delegating the rest.

    ``remember`` is called by the pipeline only after the quality gate accepted an
    answer, so a rejected attempt never reaches the memory.  The wrapper is
    transparent: ``translate_batch`` exists only when the wrapped provider has
    one, and the router therefore keeps batching where it can.
    """

    def __init__(
        self,
        inner: object,
        memory: TranslationMemory,
        *,
        model: str = "",
        prompt_version: str = PROMPT_VERSION,
    ):
        if not hasattr(inner, "translate"):
            raise TypeError("inner provider must have a translate method")
        if model == "":
            model = str(getattr(inner, "model", "") or "")
        self._inner = inner
        self._memory = memory
        self._model = model
        self._prompt_version = prompt_version
        self.hits = 0
        self.misses = 0
        if hasattr(inner, "translate_batch"):

            def translate_batch(requests):
                return self._translate_batch(requests)

            self.translate_batch = translate_batch

    @property
    def model(self) -> str:
        return self._model

    def _lookup(self, request: TranslationRequest) -> TranslationResult | None:
        hit = self._memory.lookup(
            source_text=request.text,
            source_language=request.source_language,
            target_language=request.target_language,
            model=self._model,
            prompt_version=self._prompt_version,
        )
        if hit is None:
            return None
        return TranslationResult(hit.target_text, "translation-memory", self._model or "memory", 1.0, True)

    def translate(self, request: TranslationRequest) -> TranslationResult:
        cached = self._lookup(request)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        return self._inner.translate(request)

    def _translate_batch(
        self, requests: list[TranslationRequest]
    ) -> dict[str, TranslationResult]:
        results: dict[str, TranslationResult] = {}
        remaining: list[TranslationRequest] = []
        for request in requests:
            cached = self._lookup(request)
            if cached is None:
                remaining.append(request)
            else:
                self.hits += 1
                results[request.segment_id] = cached
        if remaining:
            self.misses += len(remaining)
            results.update(dict(self._inner.translate_batch(remaining)))
        return results

    def remember(self, request: TranslationRequest, result: TranslationResult) -> None:
        """Record an accepted answer. Called by the pipeline, not by the router."""

        if result.provider == "translation-memory":
            return
        self._memory.store(
            source_text=request.text,
            target_text=result.text,
            source_language=request.source_language,
            target_language=request.target_language,
            model=self._model,
            prompt_version=self._prompt_version,
        )


def with_memory(
    provider: object, memory: TranslationMemory | None, *, prompt_version: str = PROMPT_VERSION
) -> object:
    """Wrap a provider (or a router) in the memory layer when one was configured."""

    if memory is None:
        return provider
    return MemoryTranslationProvider(provider, memory, prompt_version=prompt_version)


def _unused_router_reference() -> type:  # pragma: no cover - keeps the import honest
    return TranslationRouter
