from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PERCENT_PLACEHOLDER_RE = re.compile(r"%(?:\d+\$)?[A-Za-z]|%\d+")
MARKUP_TAG_RE = re.compile(r"</?[A-Za-z][^<>\r\n]*>")
DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
TRANSLATION_ATTEMPTS = 3
_ASCII_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_PRESERVED_ENGLISH_UNITS = frozenset({"kg"})
_SHORT_EXPRESSION_FALLBACKS = {
    "bing bong": "叮咚",
    "yum": "好吃",
    "yum yum": "好吃好吃",
    "yum yum yum": "好吃好吃好吃",
    "hmm mhm": "嗯嗯",
    "thanks": "谢谢",
    "yums": "好吃",
    "yummers": "真好吃",
}
_KNOWN_CREATURE_TRANSLATIONS = {
    "pike": "狗鱼",
    "piranha": "食人鱼",
    "red snapper": "红鲷鱼",
    "salmon": "三文鱼",
    "sea urchin": "海胆",
    "seagull": "海鸥",
    "seahorse": "海马",
    "sengarat": "森加拉特",
    "shrimp": "虾",
    "stonefish": "石鱼",
    "superdwarf fish": "超矮鱼",
    "tigerfish": "虎鱼",
    "triggerfish": "扳机鱼",
    "voxelfish": "体素鱼",
    "yellow boxfish": "黄箱鲀",
    "albatross": "信天翁",
    "blue shark": "蓝鲨",
    "bowhead whale": "弓头鲸",
    "the old pike": "老狗鱼",
    "giant piranha": "巨型食人鱼",
    "goblin shark": "哥布林鲨",
    "mutated bowhead whale": "变异弓头鲸",
    "pufferfish": "河豚",
    "spider crab": "蜘蛛蟹",
    "sunfish": "翻车鱼",
    "tuna": "金枪鱼",
    "albatross head": "信天翁头",
    "giant piranha skeleton": "巨型食人鱼骨架",
    "pufferfish fin": "河豚鳍",
    "spider crab shell": "蜘蛛蟹壳",
    "whale fin": "鲸鱼鳍",
    "starfish": "海星",
    "sponge": "海绵",
    "squid": "鱿鱼",
    "manta": "鳐鱼",
    "hammerhead shark": "双髻鲨",
    "narwhal": "独角鲸",
    "isopod": "等足类",
    "hermit crab": "寄居蟹",
    "sailfish": "剑鱼",
    "oyster": "牡蛎",
    "tripod fish": "三脚鱼",
    "carp": "鲤鱼",
    "koi fish": "锦鲤",
    "dogfish": "狗鲨",
    "mahi-mahi": "鬼头刀",
    "char": "红点鲑",
    "amberjack": "琥珀鱼",
    "bristlemouth": "刺口鱼",
    "alaska pollock": "阿拉斯加狭鳕",
    "tench": "丁鱥",
    "fry": "鱼苗",
    "rock crab": "岩蟹",
    "crab carcass": "螃蟹尸体",
}
_KNOWN_UI_TRANSLATIONS = {
    "suppressor": "消音器",
    "compensator": "枪口补偿器",
    "extended mag": "扩容弹匣",
    "iron sight": "机械瞄具",
    "laser sight": "激光瞄准器",
    "red dot sight": "红点瞄准镜",
    "sniper scope": "狙击镜",
    "no scope": "无瞄准镜",
    "quick scope": "快速瞄准",
    "longshot": "远距离击杀",
    "headshot": "爆头",
    "damage": "伤害",
    "ammo": "弹药",
    "attachments": "配件",
    "quest item": "任务物品",
    "value": "价值",
    "cooking": "烹饪",
    "sharpen": "磨利",
    "radar": "雷达",
    "boat": "船",
    "drive": "驾驶",
    "can't drive": "无法驾驶",
    "no keys": "没有钥匙",
    "creatures": "生物",
    "hot dog": "热狗",
    "carrot": "胡萝卜",
    "ham": "火腿",
}


class TranslationBridgeError(RuntimeError):
    def __init__(self, code: str, message: str, *, retry_count: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.retry_count = retry_count


def _loopback_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError("Ollama URL must be an unauthenticated HTTP loopback URL")
    return value.rstrip("/")


def _json_error(message: str) -> bytes:
    return json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")


def _ollama_health(ollama_url: str, timeout: float) -> dict[str, str]:
    request = urllib.request.Request(
        f"{ollama_url}/api/tags",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status < 200 or response.status >= 300:
                return {"status": "error", "error": f"http_{response.status}"}
    except urllib.error.HTTPError as exc:
        return {"status": "error", "error": f"http_{exc.code}"}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"status": "error", "error": type(exc).__name__}
    return {"status": "ok"}


def _request_payload(payload: Any) -> tuple[str, str, str, str, tuple[str, ...], tuple[str, ...]]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    required = ("segment_id", "text", "source_language", "target_language")
    for name in required:
        if not isinstance(payload.get(name), str) or not payload[name]:
            raise ValueError(f"{name} must be a non-empty string")
    context = payload.get("context", [])
    protected_tokens = payload.get("protected_tokens", [])
    if not isinstance(context, list) or any(not isinstance(item, str) for item in context):
        raise ValueError("context must be a list of strings")
    if not isinstance(protected_tokens, list) or any(
        not isinstance(item, str) for item in protected_tokens
    ):
        raise ValueError("protected_tokens must be a list of strings")
    return (
        payload["segment_id"],
        payload["text"],
        payload["source_language"],
        payload["target_language"],
        tuple(context),
        tuple(protected_tokens),
    )


def _balanced_placeholder(value: str, start: int) -> tuple[str, int] | None:
    opener = value[start]
    if opener not in "[{":
        return None
    closer = "]" if opener == "[" else "}"
    depth = 1
    quote: str | None = None
    escaped = False
    index = start + 1
    while index < len(value):
        character = value[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif opener == "[" and character in {"'", '"'}:
            quote = character
        elif character == opener:
            depth += 1
        elif character == closer:
            depth -= 1
            if depth == 0:
                return value[start : index + 1], index + 1
        index += 1
    return None


def _placeholder_spans(value: str) -> tuple[tuple[int, int, str], ...]:
    spans: list[tuple[int, int, str]] = []
    index = 0
    while index < len(value):
        markup = MARKUP_TAG_RE.match(value, index)
        if markup is not None:
            spans.append((index, markup.end(), markup.group(0)))
            index = markup.end()
            continue
        if value.startswith("\\n", index):
            spans.append((index, index + 2, "\\n"))
            index += 2
            continue
        if value.startswith("${", index):
            balanced = _balanced_placeholder(value, index + 1)
            if balanced is not None:
                token, end = balanced
                spans.append((index, end, "$" + token))
                index = end
                continue
        if value[index] in "[{":
            balanced = _balanced_placeholder(value, index)
            if balanced is not None:
                token, end = balanced
                spans.append((index, end, token))
                index = end
                continue
        match = PERCENT_PLACEHOLDER_RE.match(value, index)
        if match is not None:
            spans.append((index, match.end(), match.group(0)))
            index = match.end()
            continue
        index += 1
    return tuple(spans)


def _placeholder_tokens(value: str) -> tuple[str, ...]:
    return tuple(item[2] for item in _placeholder_spans(value))


def _preserves_placeholders(source: str, target: str) -> bool:
    return sorted(_placeholder_tokens(source)) == sorted(_placeholder_tokens(target))


def _mask_protected_tokens(
    text: str,
    protected_tokens: tuple[str, ...],
) -> tuple[str, tuple[str, ...], dict[str, str]]:
    source_tokens = _placeholder_tokens(text)
    if sorted(source_tokens) != sorted(protected_tokens):
        raise TranslationBridgeError(
            "invalid_request",
            "request protected_tokens do not match source placeholders",
        )
    masked = text
    markers: list[str] = []
    marker_by_token: dict[str, str] = {}
    token_by_marker: dict[str, str] = {}
    for token in source_tokens:
        marker = marker_by_token.get(token)
        if marker is None:
            index = len(marker_by_token)
            marker = f"[HANENGINE_TOKEN_{index}]"
            while marker in text or marker in token_by_marker:
                index += 1
                marker = f"[HANENGINE_TOKEN_{index}]"
            marker_by_token[token] = marker
            token_by_marker[marker] = token
        masked = masked.replace(token, marker, 1)
        markers.append(marker)
    return masked, tuple(markers), token_by_marker


def _restore_protected_tokens(
    translation: str,
    markers: tuple[str, ...],
    token_by_marker: dict[str, str],
) -> str:
    expected_counts = {marker: markers.count(marker) for marker in set(markers)}
    if any(translation.count(marker) != count for marker, count in expected_counts.items()):
        raise TranslationBridgeError(
            "placeholder_mismatch",
            "Ollama translation changed protected token markers",
        )
    restored = translation
    for marker, token in token_by_marker.items():
        restored = restored.replace(marker, token)
    return restored


def _ollama_chat(
    *,
    ollama_url: str,
    model: str,
    segment_id: str,
    text: str,
    source_language: str,
    target_language: str,
    context: tuple[str, ...],
    protected_tokens: tuple[str, ...],
    timeout: float,
    instructions: str,
    retry_instruction: str = "",
) -> str:
    if retry_instruction:
        instructions = f"{instructions} {retry_instruction}"
    has_physical_line_breaks = bool(re.search(r"\r|\n", text))
    if has_physical_line_breaks:
        system_prompt = (
            "You are a professional video game localization translator. "
            f"Translate the complete text into concise natural {target_language} suitable for a game. "
            "Physical line breaks are forced visual layout breaks, not sentence boundaries: "
            "read text across lines as one complete phrase to choose the correct meaning, "
            "then return the translation with exactly the same line break at the corresponding "
            "phrase boundary. Do not drop, add, or move line breaks. "
            f"{instructions} Return only the translated text."
        )
    else:
        system_prompt = (
            "You are a professional video game localization translator. "
            f"Translate from {source_language} to {target_language}. "
            "Return only the translated text, with no explanation, quotation marks, or labels. "
            "Do not add physical line breaks unless they already exist in the input. "
            "Never append notes, warnings, or translator commentary. "
            "The JSON context, segment_id, and protected_tokens are metadata only; "
            "translate only the text field and never include metadata in the answer. "
            "Use concise, natural Simplified Chinese suitable for in-game UI and dialogue. "
            f"{instructions}"
        )
    user_payload = {
        "segment_id": segment_id,
        "context": list(context),
        "protected_tokens": list(protected_tokens),
        "text": text,
    }
    request_payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    text
                    if has_physical_line_breaks
                    else json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
                ),
            },
        ],
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }
    body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{ollama_url}/api/chat",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="replace")
        raise TranslationBridgeError(
            "ollama_http_error",
            f"Ollama returned HTTP {exc.code}: {detail}",
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TranslationBridgeError(
            "transport_error",
            f"Ollama request failed: {type(exc).__name__}",
        ) from exc
    try:
        decoded = json.loads(response_body)
        translation = decoded["message"]["content"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise TranslationBridgeError("invalid_response", "Ollama returned an invalid chat response") from exc
    if not isinstance(translation, str) or not translation.strip():
        raise TranslationBridgeError("empty_translation", "Ollama returned an empty translation")
    translation = translation.strip()
    source_line_breaks = len(re.findall(r"\r\n|\r|\n", text))
    translation_line_breaks = len(re.findall(r"\r\n|\r|\n", translation))
    if translation_line_breaks != source_line_breaks:
        raise TranslationBridgeError(
            "physical_newline_mismatch",
            "Ollama translation changed physical newline count",
        )
    return translation


def _translate_fragmented(
    *,
    ollama_url: str,
    model: str,
    segment_id: str,
    text: str,
    source_language: str,
    target_language: str,
    context: tuple[str, ...],
    protected_tokens: tuple[str, ...],
    timeout: float,
    retry_instruction: str = "",
) -> str:
    source_tokens = _placeholder_tokens(text)
    if sorted(source_tokens) != sorted(protected_tokens):
        raise TranslationBridgeError(
            "invalid_request",
            "request protected_tokens do not match source placeholders",
        )
    pieces: list[str] = []
    cursor = 0
    for start, end, token in _placeholder_spans(text):
        fragment = text[cursor:start]
        if fragment:
            leading = fragment[: len(fragment) - len(fragment.lstrip())]
            trailing = fragment[len(fragment.rstrip()) :]
            core_end = len(fragment) - len(trailing) if trailing else len(fragment)
            core = fragment[len(leading) : core_end]
            if core:
                translated = _ollama_chat(
                    ollama_url=ollama_url,
                    model=model,
                    segment_id=segment_id,
                    text=core,
                    source_language=source_language,
                    target_language=target_language,
                    context=(*context, "fragment"),
                    protected_tokens=(),
                    timeout=timeout,
                    retry_instruction=retry_instruction,
                    instructions=(
                        "Translate only this text fragment. Preserve its meaning; "
                        "do not add a subject, explanation, or punctuation that is not needed."
                    ),
                )
                pieces.append(leading + translated + trailing)
            else:
                pieces.append(fragment)
        pieces.append(token)
        cursor = end
    tail = text[cursor:]
    if tail:
        leading = tail[: len(tail) - len(tail.lstrip())]
        trailing = tail[len(tail.rstrip()) :]
        core_end = len(tail) - len(trailing) if trailing else len(tail)
        core = tail[len(leading) : core_end]
        if core:
            translated = _ollama_chat(
                ollama_url=ollama_url,
                model=model,
                segment_id=segment_id,
                text=core,
                source_language=source_language,
                target_language=target_language,
                context=(*context, "fragment"),
                protected_tokens=(),
                timeout=timeout,
                retry_instruction=retry_instruction,
                instructions=(
                    "Translate only this text fragment. Preserve its meaning; "
                    "do not add a subject, explanation, or punctuation that is not needed."
                ),
            )
            pieces.append(leading + translated + trailing)
        else:
            pieces.append(tail)
    translation = "".join(pieces)
    if not _preserves_placeholders(text, translation):
        raise TranslationBridgeError(
            "placeholder_mismatch",
            "Ollama translation changed protected placeholders",
        )
    return translation


def _translate_with_ollama(
    *,
    ollama_url: str,
    model: str,
    segment_id: str,
    text: str,
    source_language: str,
    target_language: str,
    context: tuple[str, ...],
    protected_tokens: tuple[str, ...],
    timeout: float,
    retry_instruction: str = "",
) -> str:
    source_tokens = _placeholder_tokens(text)
    if any(token == r"\n" or token.startswith("<") for token in source_tokens):
        return _translate_fragmented(
            ollama_url=ollama_url,
            model=model,
            segment_id=segment_id,
            text=text,
            source_language=source_language,
            target_language=target_language,
            context=context,
            protected_tokens=protected_tokens,
            timeout=timeout,
            retry_instruction=retry_instruction,
        )
    masked_text, markers, token_by_marker = _mask_protected_tokens(text, protected_tokens)
    translation = _ollama_chat(
        ollama_url=ollama_url,
        model=model,
        segment_id=segment_id,
        text=masked_text,
        source_language=source_language,
        target_language=target_language,
        context=context,
        protected_tokens=markers,
        timeout=timeout,
        retry_instruction=retry_instruction,
        instructions=(
            "Preserve every ASCII marker exactly, including its spelling and count. "
            "Do not translate, remove, or add marker text."
        ),
    )
    translation = _restore_protected_tokens(translation, markers, token_by_marker)
    if not _preserves_placeholders(text, translation):
        raise TranslationBridgeError(
            "placeholder_mismatch",
            "Ollama translation changed protected placeholders",
        )
    return translation


def _needs_residual_english_retry(source: str, translation: str) -> bool:
    """Detect model output that the quality gate would reject as English."""

    source_text = source.strip()
    target_text = translation.strip()
    source_words = tuple(word.casefold() for word in _ASCII_WORD_RE.findall(source_text))
    ascii_words = _ASCII_WORD_RE.findall(target_text)
    if not ascii_words or source_text.casefold() in _PRESERVED_ENGLISH_UNITS:
        return False
    if target_text.casefold() == source_text.casefold():
        return True
    if source_words and sorted(word.casefold() for word in ascii_words) == sorted(source_words):
        return True
    return len(ascii_words) >= 3 and not _CJK_RE.search(target_text)


def _short_expression_fallback(source: str) -> str | None:
    normalized = re.sub(r"\s+", " ", source.strip().casefold())
    return _SHORT_EXPRESSION_FALLBACKS.get(normalized)


def _known_creature_fallback(source: str) -> str | None:
    normalized = re.sub(r"\s+", " ", source.strip().casefold())
    return _KNOWN_CREATURE_TRANSLATIONS.get(normalized)


def _known_ui_fallback(source: str) -> str | None:
    normalized = re.sub(r"\s+", " ", source.strip().casefold())
    return _KNOWN_UI_TRANSLATIONS.get(normalized)


def _translate_with_retries(
    *,
    attempts: int = TRANSLATION_ATTEMPTS,
    **kwargs: object,
) -> str:
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts <= 0:
        raise ValueError("attempts must be a positive integer")
    last_error: RuntimeError | None = None
    attempts_made = 0
    for _attempt in range(attempts):
        attempts_made += 1
        call_kwargs = dict(kwargs)
        if _attempt:
            call_kwargs["retry_instruction"] = (
                "The previous attempt left English text untranslated. Translate every word, "
                "including short slang, onomatopoeia, reactions, and repeated sounds, into "
                "natural Simplified Chinese. Translate fish species, animal names, and game "
                "creature names even when they are capitalized; translate weapon attachments "
                "and UI labels too. Do not preserve them merely because they look like proper "
                "names. Do not return the English source unchanged."
            )
        try:
            translation = _translate_with_ollama(**call_kwargs)
            if _needs_residual_english_retry(str(kwargs["text"]), translation):
                raise TranslationBridgeError(
                    "residual_english",
                    "Ollama returned residual English text",
                )
            return translation
        except RuntimeError as exc:
            last_error = exc
            if isinstance(exc, TranslationBridgeError) and exc.code == "invalid_request":
                break
    assert last_error is not None
    if isinstance(last_error, TranslationBridgeError) and last_error.code == "residual_english":
        fallback = _short_expression_fallback(str(kwargs["text"]))
        if fallback is not None:
            return fallback
        fallback = _known_creature_fallback(str(kwargs["text"]))
        if fallback is not None:
            return fallback
        fallback = _known_ui_fallback(str(kwargs["text"]))
        if fallback is not None:
            return fallback
    retry_count = max(0, attempts_made - 1)
    if isinstance(last_error, TranslationBridgeError):
        last_error.retry_count = retry_count
    else:
        last_error = TranslationBridgeError(
            "translation_error",
            str(last_error),
            retry_count=retry_count,
        )
    raise last_error


class TranslationHandler(BaseHTTPRequestHandler):
    server: "TranslationServer"

    def _write_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        if self.path == "/healthz":
            ollama = _ollama_health(self.server.ollama_url, min(self.server.timeout, 5.0))
            if ollama["status"] == "ok":
                self._write_json(
                    HTTPStatus.OK,
                    {"status": "ok", "model": self.server.model, "ollama": ollama},
                )
            else:
                self._write_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"status": "degraded", "model": self.server.model, "ollama": ollama},
                )
        else:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        if self.path != "/translate":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > self.server.max_body_bytes:
                raise ValueError("request body is too large or missing")
            payload = json.loads(self.rfile.read(length))
            values = _request_payload(payload)
            translation = _translate_with_retries(
                ollama_url=self.server.ollama_url,
                model=self.server.model,
                timeout=self.server.timeout,
                **dict(zip(
                    ("segment_id", "text", "source_language", "target_language", "context", "protected_tokens"),
                    values,
                )),
            )
            self._write_json(
                HTTPStatus.OK,
                {"translation": translation, "provider": "ollama", "model": self.server.model},
            )
        except TranslationBridgeError as exc:
            self._write_json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {
                    "error_code": exc.code,
                    "error": str(exc)[:1000],
                    "retry_count": exc.retry_count,
                },
            )
        except ValueError as exc:
            self._write_json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"error_code": "invalid_request", "error": str(exc)[:1000], "retry_count": 0},
            )
        except RuntimeError as exc:
            self._write_json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"error_code": "translation_error", "error": str(exc)[:1000], "retry_count": 0},
            )

    def log_message(self, format: str, *args: object) -> None:
        print(f"[ollama-bridge] {format % args}", file=sys.stderr)


class TranslationServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        ollama_url: str,
        model: str,
        timeout: float,
        max_body_bytes: int = 1_048_576,
    ) -> None:
        super().__init__(address, TranslationHandler)
        self.ollama_url = _loopback_url(ollama_url)
        self.model = model
        self.timeout = timeout
        self.max_body_bytes = max_body_bytes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把 Ollama 本地模型暴露为 HanEngine 翻译端点")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost", "::1"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not isinstance(args.model, str) or not args.model:
        print("错误: model must not be empty", file=sys.stderr)
        return 1
    if args.timeout <= 0 or not 1 <= args.port <= 65535:
        print("错误: timeout must be positive and port must be in 1..65535", file=sys.stderr)
        return 1
    try:
        server = TranslationServer(
            (args.host, args.port),
            ollama_url=args.ollama_url,
            model=args.model,
            timeout=args.timeout,
        )
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(
        f"HanEngine Ollama bridge listening on http://{args.host}:{args.port}/translate "
        f"(model={args.model})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
