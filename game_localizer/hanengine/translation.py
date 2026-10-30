from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from .multiengine import extract_placeholders as extract_structured_placeholders
from .glossary import Glossary, GlossaryTerm
from .placeholders import (
    mask_placeholders,
    restore_placeholders,
    sentinel_count,
    sentinel_fragment_count,
)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str
    body: bytes


HttpTransport = Callable[[str, Mapping[str, str], bytes, float], HttpResponse]


def _default_transport(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.headers.get("Content-Type", ""), response.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, exc.headers.get("Content-Type", ""), exc.read(16_384))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TranslationProviderError(
            f"translation transport failed: {type(exc).__name__}",
            code="transport_error",
        ) from exc


@dataclass(frozen=True)
class TranslationRequest:
    segment_id: str
    text: str
    source_language: str
    target_language: str
    context: tuple[str, ...] = ()
    reference_translation: str | None = None
    glossary: tuple[GlossaryTerm, ...] = ()
    enforced_terms: tuple[GlossaryTerm, ...] = ()
    retry_instruction: str = ""

    def __post_init__(self) -> None:
        for field_name in ("segment_id", "text", "source_language", "target_language"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        if isinstance(self.context, (str, bytes)):
            raise TypeError("context must be an ordered collection")
        context = tuple(self.context)
        if any(not isinstance(item, str) for item in context):
            raise TypeError("context must contain strings")
        object.__setattr__(self, "context", context)
        reference_translation = self.reference_translation
        if reference_translation is not None and (
            not isinstance(reference_translation, str) or not reference_translation
        ):
            raise ValueError("reference_translation must be a non-empty string or None")
        if isinstance(self.glossary, (str, bytes)):
            raise TypeError("glossary must be an ordered collection of terms")
        glossary = tuple(self.glossary)
        if any(not isinstance(term, GlossaryTerm) for term in glossary):
            raise TypeError("glossary must contain GlossaryTerm values")
        object.__setattr__(self, "glossary", glossary)
        if isinstance(self.enforced_terms, (str, bytes)):
            raise TypeError("enforced_terms must be an ordered collection of terms")
        enforced = tuple(self.enforced_terms)
        if any(not isinstance(term, GlossaryTerm) for term in enforced):
            raise TypeError("enforced_terms must contain GlossaryTerm values")
        object.__setattr__(self, "enforced_terms", enforced)
        retry_instruction = self.retry_instruction
        if not isinstance(retry_instruction, str):
            raise TypeError("retry_instruction must be a string")
        object.__setattr__(self, "retry_instruction", retry_instruction.strip())


@dataclass(frozen=True)
class TranslationResult:
    text: str
    provider: str
    model: str
    confidence: float
    cached: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("translation text must be a string")
        if not self.provider or not self.model:
            raise ValueError("provider and model must not be empty")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise TypeError("confidence must be a real number")
        confidence = float(self.confidence)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")
        object.__setattr__(self, "confidence", confidence)


class TranslationProvider(Protocol):
    def translate(self, request: TranslationRequest) -> TranslationResult: ...


class TranslationProviderError(RuntimeError):
    """A sanitized provider failure with a stable machine-readable category."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_error",
        failure_codes: Iterable[str] = (),
        retry_count: int = 0,
        issue: object | None = None,
    ) -> None:
        super().__init__(message)
        if not isinstance(code, str) or not code:
            raise ValueError("code must be a non-empty string")
        self.code = code
        self.failure_codes = tuple(dict.fromkeys(failure_codes))
        if any(not isinstance(item, str) or not item for item in self.failure_codes):
            raise ValueError("failure_codes must contain non-empty strings")
        if isinstance(retry_count, bool) or not isinstance(retry_count, int) or retry_count < 0:
            raise ValueError("retry_count must be a non-negative integer")
        self.retry_count = retry_count
        # The quality issue that caused the rejection, when one exists.  The
        # router aggregates provider failures into one error, and without this
        # the repair round can no longer tell *why* the segment was rejected.
        self.issue = issue


class TranslationNotFoundError(TranslationProviderError):
    def __init__(self, message: str = "no translation found") -> None:
        super().__init__(message, code="not_found")


class TranslationQualityError(TranslationProviderError):
    def __init__(self, issue: "TranslationQualityIssue") -> None:
        if not isinstance(issue, TranslationQualityIssue):
            raise TypeError("issue must be a TranslationQualityIssue")
        super().__init__(issue.message, code=issue.code)
        self.issue = issue


@dataclass(frozen=True)
class TranslationQualityIssue:
    code: str
    severity: str
    message: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.code, self.severity, self.message)):
            raise ValueError("translation quality issue fields must be non-empty strings")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


class DictionaryTranslationProvider:
    def __init__(self, dictionary: Mapping[str, str]):
        if not isinstance(dictionary, Mapping):
            raise TypeError("dictionary must be a mapping")
        self._dictionary = {key: value for key, value in dictionary.items() if isinstance(key, str) and isinstance(value, str)}

    def translate(self, request: TranslationRequest) -> TranslationResult:
        try:
            text = self._dictionary[request.text]
        except KeyError as exc:
            raise TranslationNotFoundError("dictionary miss") from exc
        return TranslationResult(text, "dictionary", "exact", 1.0)


class CloudTranslationProvider:
    def __init__(
        self,
        endpoint: str,
        *,
        token_provider: Callable[[], str | None] | None = None,
        transport: HttpTransport | None = None,
        timeout: float = 30.0,
    ):
        if not isinstance(endpoint, str) or not endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("cloud endpoint must use HTTPS or an explicit local HTTP endpoint")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._endpoint = endpoint
        self._token_provider = token_provider
        self._transport = _default_transport if transport is None else transport
        self._timeout = float(timeout)

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if not isinstance(request, TranslationRequest):
            raise TypeError("request must be a TranslationRequest")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token_provider is not None:
            token = self._token_provider()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        # Same sentinel round-trip as the local provider: the backend never sees
        # a raw "{0}", so it cannot corrupt one.
        masked = mask_placeholders(request.text, _placeholder_tokens(request.text))
        payload = {
            "text": masked.text,
            "source_language": request.source_language,
            "target_language": request.target_language,
            "context": list(request.context),
        }
        if request.glossary:
            payload["glossary"] = [
                {"source": term.source, "target": term.target, "note": term.note}
                for term in request.glossary
            ]
        if request.retry_instruction:
            payload["retry_instruction"] = request.retry_instruction
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        response = self._transport(self._endpoint, headers, body, self._timeout)
        if response.status < 200 or response.status >= 300:
            raise TranslationProviderError(
                f"cloud translation returned HTTP {response.status}",
                code="http_error",
            )
        try:
            decoded = json.loads(response.body)
            if not isinstance(decoded, Mapping):
                raise ValueError
            text = decoded["translation"]
            provider = decoded.get("provider", "cloud")
            model = decoded.get("model", "unknown")
            confidence = decoded.get("confidence", _UNREPORTED_CONFIDENCE)
            text = restore_placeholders(masked, text)
            result = TranslationResult(text, provider, model, confidence)
        except (KeyError, TypeError, ValueError) as exc:
            raise TranslationProviderError(
                "cloud translation returned an invalid response",
                code="invalid_response",
            ) from exc
        return result


def _local_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str) or not endpoint:
        raise ValueError("local model endpoint must not be empty")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("local model endpoint must be an unauthenticated HTTP loopback URL")
    return endpoint


def _batch_endpoint(endpoint: str) -> str:
    """Derive the batch path from the single-segment endpoint.

    The bridge serves ``/translate`` and ``/translate-batch`` from one process, so
    a caller only configures the endpoint once.
    """

    parsed = urlsplit(endpoint)
    path = parsed.path.rstrip("/")
    if path.endswith("/translate"):
        path = f"{path[: -len('/translate')]}/translate-batch"
    else:
        path = f"{path}/translate-batch"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


class LocalModelTranslationProvider:
    """Call a local model runtime using HanEngine's translation JSON contract.

    The runtime receives one JSON object per request and must return an object
    containing ``translation``. It may also return ``provider``, ``model`` and
    ``confidence``. Network access is restricted to the local machine.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        transport: HttpTransport | None = None,
        timeout: float = 120.0,
        provider_name: str = "local-model",
        model_name: str = "unknown",
    ):
        self._endpoint = _local_endpoint(endpoint)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number")
        if not isinstance(provider_name, str) or not provider_name:
            raise ValueError("provider_name must not be empty")
        if not isinstance(model_name, str) or not model_name:
            raise ValueError("model_name must not be empty")
        self._transport = _default_transport if transport is None else transport
        self._timeout = float(timeout)
        self._provider_name = provider_name
        self._model_name = model_name
        self._batch_endpoint = _batch_endpoint(self._endpoint)

    def _payload(self, request: TranslationRequest, masked_text: str) -> dict[str, object]:
        tokens = sorted(_placeholder_tokens(request.text))
        payload: dict[str, object] = {
            "segment_id": request.segment_id,
            "text": masked_text,
            "source_language": request.source_language,
            "target_language": request.target_language,
            "context": list(request.context),
            "protected_tokens": tokens,
        }
        if tokens:
            # The text already carries sentinels instead of the real tokens, so a
            # bridge that masks again would find nothing to mask and reject the
            # request.  Saying so keeps one masker per request.
            payload["placeholders_masked"] = True
        if request.reference_translation is not None:
            payload["reference_translation"] = request.reference_translation
        if request.glossary:
            payload["glossary"] = [
                {"source": term.source, "target": term.target, "note": term.note}
                for term in request.glossary
            ]
        if request.retry_instruction:
            payload["retry_instruction"] = request.retry_instruction
        return payload

    def translate_batch(
        self,
        requests: Sequence[TranslationRequest],
    ) -> dict[str, TranslationResult]:
        """Translate several segments in one round trip.

        Returns only the segments the runtime answered and accepted.  Segments it
        could not align, or that came back with a broken placeholder or residual
        English, are simply absent; the caller re-asks those one at a time, where
        the tag-splitting and retry ladder live.
        """

        if not requests:
            return {}
        for request in requests:
            if not isinstance(request, TranslationRequest):
                raise TypeError("requests must contain TranslationRequest items")
        masked_by_id: dict[str, object] = {}
        segments: list[dict[str, object]] = []
        for request in requests:
            masked = mask_placeholders(request.text, _placeholder_tokens(request.text))
            masked_by_id[request.segment_id] = masked
            segments.append(self._payload(request, masked.text))
        body = json.dumps(
            {"segments": segments},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._transport(
            self._batch_endpoint,
            {"Content-Type": "application/json", "Accept": "application/json"},
            body,
            self._timeout,
        )
        if response.status < 200 or response.status >= 300:
            raise TranslationProviderError(
                f"local model returned HTTP {response.status} for a batch request",
                code="http_error",
            )
        try:
            decoded = json.loads(response.body)
            if not isinstance(decoded, Mapping):
                raise ValueError
            translations = decoded["translations"]
            if not isinstance(translations, Mapping):
                raise ValueError
            provider = decoded.get("provider", self._provider_name)
            model = decoded.get("model", self._model_name)
            confidence = decoded.get("confidence", _UNREPORTED_CONFIDENCE)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TranslationProviderError(
                "local model returned an invalid batch response",
                code="invalid_response",
            ) from exc
        results: dict[str, TranslationResult] = {}
        for segment_id, text in translations.items():
            masked = masked_by_id.get(str(segment_id))
            if masked is None or not isinstance(text, str):
                continue
            restored = restore_placeholders(masked, text)
            if sentinel_count(restored) or sentinel_fragment_count(restored):
                # Leave it out of the batch answer: the single path re-asks it and
                # fails loudly there instead of shipping a raw sentinel.
                continue
            results[str(segment_id)] = TranslationResult(
                restored,
                provider,
                model,
                confidence,
            )
        return results

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if not isinstance(request, TranslationRequest):
            raise TypeError("request must be a TranslationRequest")
        # Send sentinels instead of raw placeholders.  A model that moves
        # "{0}" around, or turns it into "（0）", cannot corrupt a token it
        # never saw; the real text is restored from the response below.
        masked = mask_placeholders(request.text, _placeholder_tokens(request.text))
        payload = self._payload(request, masked.text)
        body = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._transport(
            self._endpoint,
            {"Content-Type": "application/json", "Accept": "application/json"},
            body,
            self._timeout,
        )
        if response.status < 200 or response.status >= 300:
            code = "http_error"
            message = f"local model returned HTTP {response.status}"
            failure_codes: tuple[str, ...] = ()
            retry_count = 0
            try:
                decoded_error = json.loads(response.body)
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded_error = None
            if isinstance(decoded_error, Mapping):
                candidate_code = decoded_error.get("error_code")
                candidate_message = decoded_error.get("error")
                candidate_retries = decoded_error.get("retry_count")
                if (
                    isinstance(candidate_retries, int)
                    and not isinstance(candidate_retries, bool)
                    and 0 <= candidate_retries <= 100
                ):
                    retry_count = candidate_retries
                if isinstance(candidate_code, str) and candidate_code in {
                    "invalid_request",
                    "placeholder_mismatch",
                    "physical_newline_mismatch",
                    "invalid_response",
                    "empty_translation",
                    "transport_error",
                    "ollama_http_error",
                    "translation_error",
                    "residual_english",
                }:
                    code = candidate_code
                    failure_codes = (candidate_code,)
                if isinstance(candidate_message, str) and candidate_message:
                    message = candidate_message[:500]
            raise TranslationProviderError(
                message,
                code=code,
                failure_codes=failure_codes,
                retry_count=retry_count,
            )
        try:
            decoded = json.loads(response.body)
            if not isinstance(decoded, Mapping):
                raise ValueError
            text = decoded["translation"]
            provider = decoded.get("provider", self._provider_name)
            model = decoded.get("model", self._model_name)
            confidence = decoded.get("confidence", _UNREPORTED_CONFIDENCE)
            # Restore the original tokens before any downstream check touches them.
            text = restore_placeholders(masked, text)
            leaked = sentinel_count(text) + sentinel_fragment_count(text)
            if leaked:
                # A sentinel the model garbled cannot be restored, and leaving it
                # in the output would ship "ZqBZx" to the player.
                raise TranslationProviderError(
                    f"local model left {leaked} placeholder sentinel(s) unrestorable",
                    code="placeholder_mismatch",
                    failure_codes=("placeholder_mismatch",),
                )
            result = TranslationResult(text, provider, model, confidence)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TranslationProviderError(
                "local model returned an invalid response",
                code="invalid_response",
            ) from exc
        return result


# Providers that never score their own output must not be reported as unsure.
# The local Ollama bridge returns only {translation, provider, model}; reading the
# absent field as 0.0 made low_confidence fire on every single segment, which
# filled the review queue (4/4 in a smoke run, 189/646 on the real corpus) and
# buried the warnings that do carry information.
_UNREPORTED_CONFIDENCE = 1.0
_LOW_CONFIDENCE_THRESHOLD = 0.45


_PERCENT_PLACEHOLDER_RE = re.compile(r"%(?:\d+\$)?[A-Za-z]|%\d+")


def _placeholder_tokens(value: str) -> tuple[str, ...]:
    structured = [
        token
        for token in extract_structured_placeholders(value)
        if not token.startswith("%")
    ]
    structured.extend(match.group(0) for match in _PERCENT_PLACEHOLDER_RE.finditer(value))
    structured.extend("\\n" for _ in range(value.count("\\n")))
    return tuple(structured)


def _preserves_placeholders(source: str, target: str) -> bool:
    return sorted(_placeholder_tokens(source)) == sorted(_placeholder_tokens(target))


def _rich_text_tags(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in extract_structured_placeholders(value)
        if token.startswith("<") and token.endswith(">")
    )


def _visible_text(value: str) -> str:
    """Return the prose only: markup tags and placeholders replaced by spaces.

    ``rich_text_tag_order_mismatch`` compares tag tokens, so it cannot see a
    model that re-states the whole sentence inside an inline tag.  This helper
    exposes the prose for a repetition check.
    """

    visible = value
    for token in extract_structured_placeholders(value):
        visible = visible.replace(token, " ")
    for match in _PERCENT_PLACEHOLDER_RE.finditer(value):
        visible = visible.replace(match.group(0), " ")
    return visible


# A repeated run must be long enough that natural language does not produce it
# by accident.  Eight CJK characters is above the longest legitimate repeat in
# the shipped corpus ("好吃好吃好吃" is six) while still catching the shortest
# observed defect ("把它扔进火山口。" is eight).
_REPEATED_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff][\u3400-\u9fff，。！？、；：…]{7,}")


def _repeated_cjk_run(value: str) -> str | None:
    """Return a long CJK run that the text states more than once."""

    visible = _visible_text(value)
    for run in _REPEATED_CJK_RUN_RE.findall(visible):
        if visible.count(run) >= 2:
            return run
    return None


_EM_CJK_RANGES = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0x3000, 0x303F),
    (0xFF00, 0xFF60),
)


def em_width(value: str) -> float:
    """Estimate rendered width in em, ignoring markup and placeholders.

    Calibrated against the shipped How to Fish corpus: a CJK glyph is one em, a
    Latin glyph or digit is half an em, a space is a quarter em.  This is a
    layout heuristic, not a font measurement -- see ``visual_style`` for the
    exact path that measures a real font.
    """

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    total = 0.0
    for character in _visible_text(value):
        if character.isspace():
            total += 0.25
            continue
        point = ord(character)
        if any(low <= point <= high for low, high in _EM_CJK_RANGES):
            total += 1.0
        else:
            total += 0.5
    return total


# A short UI label is the only case where a translation can overflow its box:
# measured over the 646-segment How to Fish candidate, only segments whose source
# is under 20em ever widened, and 11% of labels under 8em widened by up to 2x.
# Longer lines always came back shorter (33-39%) because Chinese packs more
# meaning per glyph, so a budget on dialogue would only misfire.
_LENGTH_BUDGET_SOURCE_LIMIT_EM = 20.0
# 4em of slack is ~4 Chinese glyphs.  Measured hit rate at 4.0em: 1/546 short
# segments in the reference corpus and 0/492 in the no-reference corpus, and
# that single hit was a genuine over-expansion ("360" -> "360度转体击杀").
# A relative gate (target > 1.3 * source) was tested and rejected: it flagged
# 36/546 segments, every one of them a correct translation ("sir" -> "长官。".
_LENGTH_BUDGET_ALLOWANCE_EM = 4.0

_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_METADATA_ECHO_RE = re.compile(
    r"(?i)(?:^|[\[{(\s])(?:segment_id|source_language|target_language|protected_tokens|context)\s*[:=]"
)
_TRANSLATION_LABEL_RE = re.compile(r"(?i)^(?:translation|translated text|译文)\s*[:：]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_PRESERVED_ENGLISH_UNITS = frozenset({"kg"})
# Latin tokens that legitimately stay inside Chinese game text (units,
# established abbreviations).  Anything else left over in a CJK result is a
# mixed-language defect and is rejected so the segment falls back for review.
_MIXED_LANGUAGE_ALLOWLIST = frozenset({"kg", "npc", "steam"})
_TERMINAL_PUNCTUATION = frozenset(".!?。！？…")
_TRAILING_PLACEHOLDER_RE = re.compile(r"(?:\{[^{}]*\}|\[[^\[\]]*\]|%\d+(?:\$[A-Za-z])?)+\s*$")
_TRAILING_RICH_TEXT_RE = re.compile(r"</?[A-Za-z][^<>]*>\s*$")
# U+FFFD means the bytes were already lost before or during the model call.
# It is unrecoverable and must never reach a candidate: a replacement glyph in
# the string table shows up in-game as a box and cannot be fixed after build.
_REPLACEMENT_CHARACTER = "\ufffd"

# Characters whose Simplified counterpart is a different codepoint, so finding
# one in a zh-CN catalog is always wrong.  Measured on the How to Fish corpus
# (573 no-reference segments): 10 segments shipped Traditional glyphs such as
# 歡迎來到黃金鈎魚賭場 / 查看浮動 / 鯉魚游去.  A model asked for Simplified
# Chinese still emits these because the two scripts share most vocabulary.
# Kept as a guard, not a converter: it reports and triggers a re-ask.
_TRADITIONAL_ONLY = frozenset(
    "這們個時後來島歡黃隻動視檢體開關點魚貓龍語說話麼樣對學國會員場車東長門問間頭題風飛"
    "飲買賣貴錢銀鐵鋼鐘陣陽陰難雙雜雞馬鳥麗龜臺灣灣蘋葉華萬與專業絲兩嚴喪豐臨為"
    "舉義烏樂喬習鄉書爭於虧雲亞產畝親億僅從倉儀價眾優夥傘偉傳傷倫偽餘傭"
    "俠侶偵側僑儉兒兌黨蘭興舊艙艦藝節範築簡簽籃籌籠粵"
    "糞糧緊縣總績織繡繩繪繼續纏纖纜網羅罰罷羨聖聞聯聰聲職聽肅腸膚腎腫脹脅"
    "膽勝膠脈臟莖萊獲蕭薩藍藥蘇蘊處虛蟲蠻補裝裡製複褲襲見觀規覓覺覽"
    "計訂認討讓訓議訊記講論設訪證評識譯詩該詳誇誌誰課調談請諒諮諾謀謂"
    "謝謠謙譜護讀變讚艷貝負財貢貧貨販貪責貸費貼貿賀賄資賊賓賜賞賠"
    "賴購賽贈贊贏趙趕趨踐躍軀軌軍軒軟較載輔輕輛輝輪輸轉轟跡蹤顯驚髮鬥鬧"
    "鬱魯鮮鯉鯨鳳鳴鴻鵲鷹鹽麥麵黴齊齋齒齡"
)

# Target-language labels that mean "Simplified Chinese" for the check above.
_SIMPLIFIED_CHINESE_TARGETS = frozenset(
    {"zh-cn", "zh_cn", "zh-hans", "zh_hans", "zh-hans-cn", "simplified chinese"}
)


def traditional_characters(value: str) -> tuple[str, ...]:
    """Return the Traditional-only characters found in ``value``, sorted."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return tuple(sorted({character for character in value if character in _TRADITIONAL_ONLY}))


def has_terminal_punctuation(value: str) -> bool:
    """Return whether visible text ends in sentence punctuation."""

    visible = value.strip()
    while visible:
        previous = visible
        visible = _TRAILING_PLACEHOLDER_RE.sub("", visible).rstrip()
        visible = _TRAILING_RICH_TEXT_RE.sub("", visible).rstrip()
        if visible == previous:
            break
    visible = visible.rstrip("\"'”’」』）》)]}")
    return bool(visible and visible[-1] in _TERMINAL_PUNCTUATION)


_PUNCTUATION_COMPLETIONS = {
    ".": "。",
    "。": "。",
    "!": "！",
    "！": "！",
    "?": "？",
    "？": "？",
    "…": "…",
    "~": "～",
    "～": "～",
}
_APPENDABLE_TAIL_RE = re.compile(r"[\u3400-\u9fff0-9A-Za-z%)\]}]$")


def with_terminal_punctuation(
    request: TranslationRequest, result: TranslationResult
) -> TranslationResult:
    """Complete missing sentence-final punctuation on CJK results.

    The style reference is the official reference translation when present,
    otherwise the source text.  Appendability is decided on the visible tail
    (trailing rich-text markup ignored) and the punctuation is appended at
    the end of the result, so placeholders and markup are never corrupted.
    """

    target = result.text
    if not re.search(r"[\u3400-\u9fff]", target) or has_terminal_punctuation(target):
        return result
    reference = (
        request.reference_translation
        if request.reference_translation is not None
        else request.text
    )
    if not has_terminal_punctuation(reference):
        return result
    visible = reference.strip()
    while visible:
        previous = visible
        visible = _TRAILING_PLACEHOLDER_RE.sub("", visible).rstrip()
        visible = _TRAILING_RICH_TEXT_RE.sub("", visible).rstrip()
        if visible == previous:
            break
    visible = visible.rstrip("\"'”’」』）》)]}")
    if not visible:
        return result
    mapped = _PUNCTUATION_COMPLETIONS.get(visible[-1])
    if mapped is None:
        return result
    tail = target.rstrip()
    while tail:
        previous = tail
        tail = _TRAILING_RICH_TEXT_RE.sub("", tail).rstrip()
        if tail == previous:
            break
    if not _APPENDABLE_TAIL_RE.search(tail):
        return result
    return replace(result, text=target + mapped)


def _mixed_language_words(target: str) -> tuple[str, ...]:
    """Return leftover non-allowlisted Latin words inside a CJK result.

    Placeholders ({0}, {name}) and rich-text markup are stripped first so only
    real untranslated words count.
    """

    if not re.search(r"[\u3400-\u9fff]", target):
        return ()
    visible = target
    for token in extract_structured_placeholders(target):
        visible = visible.replace(token, " ")
    words = [
        word
        for word in _ASCII_WORD_RE.findall(visible)
        if word.casefold() not in _MIXED_LANGUAGE_ALLOWLIST
    ]
    return tuple(dict.fromkeys(words))


def _is_model_result(result: TranslationResult) -> bool:
    provider = result.provider.casefold()
    model = result.model.casefold()
    return (
        provider.startswith("local-")
        or provider in {"local", "ollama"}
        or any(marker in model for marker in ("qwen", "llama", "mistral"))
    )


def translation_quality_issues(
    request: TranslationRequest,
    result: TranslationResult,
) -> tuple[TranslationQualityIssue, ...]:
    """Inspect one result before it is persisted or written into a candidate."""

    if not isinstance(request, TranslationRequest):
        raise TypeError("request must be a TranslationRequest")
    if not isinstance(result, TranslationResult):
        raise TypeError("result must be a TranslationResult")
    issues: list[TranslationQualityIssue] = []
    target = result.text
    if not target.strip():
        issues.append(TranslationQualityIssue("empty_translation", "error", "translation is empty"))
    if _CONTROL_CHARACTER_RE.search(target):
        issues.append(
            TranslationQualityIssue(
                "control_character",
                "error",
                "translation contains an unsupported control character",
            )
        )
    if _REPLACEMENT_CHARACTER in target:
        issues.append(
            TranslationQualityIssue(
                "garbled_replacement_character",
                "error",
                "translation contains U+FFFD, so characters were already lost",
            )
        )
    if request.target_language.strip().casefold() in _SIMPLIFIED_CHINESE_TARGETS:
        traditional = traditional_characters(target)
        if traditional:
            issues.append(
                TranslationQualityIssue(
                    "traditional_chinese",
                    "error",
                    "translation uses Traditional characters in a Simplified Chinese target: "
                    + " ".join(traditional[:8]),
                )
            )
    source_breaks = tuple(re.findall(r"\r\n|\r|\n", request.text))
    target_breaks = tuple(re.findall(r"\r\n|\r|\n", target))
    if source_breaks != target_breaks:
        issues.append(
            TranslationQualityIssue(
                "physical_newline_mismatch",
                "error",
                "translation changed physical line breaks",
            )
        )
    if not _preserves_placeholders(request.text, target):
        issues.append(
            TranslationQualityIssue(
                "placeholder_mismatch",
                "error",
                "translation changed protected placeholders or markup tags",
            )
        )
    if _rich_text_tags(request.text) != _rich_text_tags(target):
        issues.append(
            TranslationQualityIssue(
                "rich_text_tag_order_mismatch",
                "error",
                "translation changed rich-text tag order",
            )
        )
    if _rich_text_tags(request.text):
        # Inline tags such as <color=#FFEF4D><b>phrase</color></b> invite the
        # model to restate the surrounding sentence inside the tag.  Tag order
        # is preserved by that defect, so it needs a prose-level check: a
        # shipped candidate carried 14 such segments past a "passed" gate.
        repeated = _repeated_cjk_run(target)
        if repeated is not None:
            issues.append(
                TranslationQualityIssue(
                    "rich_text_body_duplication",
                    "error",
                    "translation repeats its own text around a rich-text tag: "
                    + repeated,
                )
            )
    if request.enforced_terms:
        # Only terms the source string *is* are binding.  A term appearing inside
        # a longer sentence is a hint: the mined glossary has 56 entries that are
        # substrings of other entries, and the game's own Chinese renders them
        # differently in context ("保存" alone vs "存档" in a sentence).
        missing = [
            term for term in request.enforced_terms if term.target not in target
        ]
        if missing:
            issues.append(
                TranslationQualityIssue(
                    "glossary_violation",
                    "error",
                    "translation ignored pinned terms: "
                    + ", ".join(f"{t.source}->{t.target}" for t in missing[:3]),
                )
            )
    source_width = em_width(request.text)
    if source_width < _LENGTH_BUDGET_SOURCE_LIMIT_EM and re.search(r"[\u3400-\u9fff]", target):
        # The budget is calibrated on Chinese renderings of English labels, so it
        # only applies when the result is actually Chinese.  Comparing widths
        # against a non-CJK result would flag a translation that has not been
        # produced yet (a stub or an untranslated echo) for the wrong reason.
        target_width = em_width(target)
        allowed = source_width + _LENGTH_BUDGET_ALLOWANCE_EM
        if target_width > allowed:
            # Warning, not error: at the calibrated threshold this fires on about
            # 0.2% of short segments, and on a false positive an error would fall
            # back to the English source, which is *wider* than the Chinese that
            # tripped the gate.  The pipeline instead re-asks once for a shorter
            # rendering and keeps this text when that repair fails.
            issues.append(
                TranslationQualityIssue(
                    "length_budget_exceeded",
                    "warning",
                    f"short-label translation is {target_width:.1f}em wide, "
                    f"budget is {allowed:.1f}em (source {source_width:.1f}em)",
                )
            )
    if _METADATA_ECHO_RE.search(target) or _TRANSLATION_LABEL_RE.search(target):
        issues.append(
            TranslationQualityIssue(
                "metadata_contamination",
                "error",
                "translation contains request metadata or a translator label",
            )
        )
    if _is_model_result(result):
        ascii_words = _ASCII_WORD_RE.findall(target)
        preserved_unit = request.text.strip().casefold() in _PRESERVED_ENGLISH_UNITS
        if target.strip() == request.text.strip() and ascii_words and not preserved_unit:
            issues.append(
                TranslationQualityIssue(
                    "residual_english",
                    "error",
                    "model returned the source text unchanged",
                )
            )
        elif ascii_words and not re.search(r"[\u3400-\u9fff]", target) and not preserved_unit:
            # A zh-CN result with zero Chinese characters but Latin words is a
            # translation failure even when it differs from the source: short
            # outputs like Cod→Code previously slipped through the >=3-word
            # threshold and shipped untranslated English into the candidate.
            issues.append(
                TranslationQualityIssue(
                    "residual_english",
                    "error",
                    "model result contains no Chinese characters",
                )
            )
        else:
            mixed_words = _mixed_language_words(target)
            if mixed_words:
                issues.append(
                    TranslationQualityIssue(
                        "residual_english",
                        "error",
                        "model result mixes Chinese with untranslated English words: "
                        + ", ".join(mixed_words),
                    )
                )
        if result.confidence < _LOW_CONFIDENCE_THRESHOLD:
            issues.append(
                TranslationQualityIssue(
                    "low_confidence",
                    "warning",
                    f"model confidence {result.confidence:.2f} is below {_LOW_CONFIDENCE_THRESHOLD}",
                )
            )
        reference = request.reference_translation
        punctuation_reference = reference if reference is not None else request.text
        if (
            re.search(r"[\u3400-\u9fff]", target)
            and has_terminal_punctuation(punctuation_reference)
            and not has_terminal_punctuation(target)
        ):
            code = (
                "reference_punctuation_mismatch"
                if reference is not None
                else "missing_terminal_punctuation"
            )
            issues.append(
                TranslationQualityIssue(
                    code,
                    "warning",
                    "Chinese translation omits sentence punctuation used by its reference",
                )
            )
    return tuple(issues)


def enforce_translation_quality(
    request: TranslationRequest,
    result: TranslationResult,
) -> tuple[TranslationQualityIssue, ...]:
    issues = translation_quality_issues(request, result)
    blocking = next((issue for issue in issues if issue.severity == "error"), None)
    if blocking is not None:
        raise TranslationQualityError(blocking)
    return issues


class TranslationRouter:
    def __init__(self, providers: Iterable[TranslationProvider]):
        providers = tuple(providers)
        if not providers or any(not callable(getattr(provider, "translate", None)) for provider in providers):
            raise ValueError("at least one translation provider is required")
        self._providers = providers
        self._cache: dict[tuple[object, ...], TranslationResult] = {}

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if not isinstance(request, TranslationRequest):
            raise TypeError("request must be a TranslationRequest")
        key = (
            request.segment_id,
            request.text,
            request.source_language,
            request.target_language,
            request.context,
            request.reference_translation,
            # A repair round asks for a different rendering of the same segment,
            # so it must not be served from the cache entry of the first attempt.
            request.retry_instruction,
        )
        cached = self._cache.get(key)
        if cached is not None:
            return TranslationResult(cached.text, cached.provider, cached.model, cached.confidence, True)
        failures: list[str] = []
        failure_codes: list[str] = []
        retry_count = 0
        misses = 0
        rejected: object | None = None
        for provider in self._providers:
            try:
                result = provider.translate(request)
                enforce_translation_quality(request, result)
                self._cache[key] = result
                return result
            except TranslationNotFoundError:
                misses += 1
            except TranslationProviderError as exc:
                failures.append(f"{exc.code}:{type(exc).__name__}")
                failure_codes.extend(exc.failure_codes or (exc.code,))
                retry_count += exc.retry_count
                if getattr(exc, "issue", None) is not None:
                    rejected = exc.issue
            except Exception as exc:
                failures.append(f"provider_error:{type(exc).__name__}")
                failure_codes.append("provider_error")
        if misses == len(self._providers):
            raise TranslationNotFoundError("no provider has a translation")
        raise TranslationProviderError(
            "all translation providers failed: " + ",".join(failures),
            code="all_providers_failed",
            failure_codes=tuple(dict.fromkeys(failure_codes)),
            retry_count=retry_count,
            issue=rejected,
        )

    def translate_many(self, requests: Iterable[TranslationRequest]) -> tuple[TranslationResult, ...]:
        return tuple(self.translate(request) for request in requests)


__all__ = [
    "CloudTranslationProvider",
    "DictionaryTranslationProvider",
    "HttpResponse",
    "LocalModelTranslationProvider",
    "TranslationProvider",
    "TranslationNotFoundError",
    "TranslationProviderError",
    "TranslationQualityError",
    "TranslationQualityIssue",
    "TranslationRequest",
    "TranslationResult",
    "TranslationRouter",
    "em_width",
    "enforce_translation_quality",
    "has_terminal_punctuation",
    "traditional_characters",
    "with_terminal_punctuation",
    "translation_quality_issues",
]
