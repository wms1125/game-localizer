from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol


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
        return HttpResponse(exc.code, exc.headers.get("Content-Type", ""), b"")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TranslationProviderError(f"translation transport failed: {type(exc).__name__}") from exc


@dataclass(frozen=True)
class TranslationRequest:
    segment_id: str
    text: str
    source_language: str
    target_language: str
    context: tuple[str, ...] = ()

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
    pass


class TranslationNotFoundError(TranslationProviderError):
    pass


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
        payload = {
            "text": request.text,
            "source_language": request.source_language,
            "target_language": request.target_language,
            "context": list(request.context),
        }
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        response = self._transport(self._endpoint, headers, body, self._timeout)
        if response.status < 200 or response.status >= 300:
            raise TranslationProviderError(f"cloud translation returned HTTP {response.status}")
        try:
            decoded = json.loads(response.body)
            if not isinstance(decoded, Mapping):
                raise ValueError
            text = decoded["translation"]
            provider = decoded.get("provider", "cloud")
            model = decoded.get("model", "unknown")
            confidence = decoded.get("confidence", 0.0)
            result = TranslationResult(text, provider, model, confidence)
        except (KeyError, TypeError, ValueError) as exc:
            raise TranslationProviderError("cloud translation returned an invalid response") from exc
        return result


_PLACEHOLDER_RE = re.compile(r"\[[^\]\n]+\]|\{[^{}\n]+\}|%\d+|%[a-zA-Z]")


def _preserves_placeholders(source: str, target: str) -> bool:
    return sorted(_PLACEHOLDER_RE.findall(source)) == sorted(_PLACEHOLDER_RE.findall(target))


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
        key = (request.segment_id, request.text, request.source_language, request.target_language, request.context)
        cached = self._cache.get(key)
        if cached is not None:
            return TranslationResult(cached.text, cached.provider, cached.model, cached.confidence, True)
        failures: list[str] = []
        misses = 0
        for provider in self._providers:
            try:
                result = provider.translate(request)
                if not _preserves_placeholders(request.text, result.text):
                    raise TranslationProviderError("provider changed placeholders")
                self._cache[key] = result
                return result
            except TranslationNotFoundError:
                misses += 1
            except TranslationProviderError as exc:
                failures.append(type(exc).__name__)
            except Exception as exc:
                failures.append(type(exc).__name__)
        if misses == len(self._providers):
            raise TranslationNotFoundError("no provider has a translation")
        raise TranslationProviderError("all translation providers failed: " + ",".join(failures))

    def translate_many(self, requests: Iterable[TranslationRequest]) -> tuple[TranslationResult, ...]:
        return tuple(self.translate(request) for request in requests)


__all__ = [
    "CloudTranslationProvider",
    "DictionaryTranslationProvider",
    "HttpResponse",
    "TranslationProvider",
    "TranslationNotFoundError",
    "TranslationProviderError",
    "TranslationRequest",
    "TranslationResult",
    "TranslationRouter",
]
