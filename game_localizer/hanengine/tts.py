from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .translation import HttpResponse, HttpTransport


@dataclass(frozen=True)
class TtsRequest:
    text: str
    language: str
    voice: str | None = None
    rate: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("text must be a non-empty string")
        if not isinstance(self.language, str) or not self.language:
            raise ValueError("language must be a non-empty string")
        if self.voice is not None and (not isinstance(self.voice, str) or not self.voice):
            raise ValueError("voice must be a non-empty string or None")
        if isinstance(self.rate, bool) or not isinstance(self.rate, (int, float)) or not 0.25 <= self.rate <= 4.0:
            raise ValueError("rate must be between 0.25 and 4.0")


@dataclass(frozen=True)
class TtsResult:
    path: Path
    provider: str
    sha256: str


class TtsProviderError(RuntimeError):
    pass


def _write_wav(path: Path, data: bytes) -> TtsResult:
    if not data.startswith(b"RIFF") or b"WAVE" not in data[:16]:
        raise TtsProviderError("TTS provider did not return a WAV file")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".hanengine-tts-", suffix=".wav", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return TtsResult(path, "cloud", hashlib.sha256(data).hexdigest())


class CloudTtsProvider:
    def __init__(
        self,
        endpoint: str,
        *,
        token_provider: Callable[[], str | None] | None = None,
        transport: HttpTransport,
        timeout: float = 60.0,
    ):
        if not isinstance(endpoint, str) or not endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("cloud endpoint must use HTTPS or an explicit local HTTP endpoint")
        self._endpoint = endpoint
        self._token_provider = token_provider
        self._transport = transport
        self._timeout = timeout

    def synthesize(self, request: TtsRequest, output_path: Path) -> TtsResult:
        if not isinstance(request, TtsRequest):
            raise TypeError("request must be a TtsRequest")
        if not isinstance(output_path, Path) or output_path.suffix.casefold() != ".wav":
            raise ValueError("output_path must be a WAV path")
        headers = {"Content-Type": "application/json", "Accept": "audio/wav"}
        if self._token_provider is not None:
            token = self._token_provider()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        body = json.dumps(
            {"text": request.text, "language": request.language, "voice": request.voice, "rate": request.rate},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._transport(self._endpoint, headers, body, self._timeout)
        if response.status < 200 or response.status >= 300:
            raise TtsProviderError(f"cloud TTS returned HTTP {response.status}")
        result = _write_wav(output_path.resolve(strict=False), response.body)
        return TtsResult(result.path, "cloud-tts", result.sha256)


CommandRunner = Callable[..., object]


class WindowsSapiTts:
    def __init__(self, *, command_runner: CommandRunner | None = None, timeout: float = 60.0):
        self._command_runner = command_runner or self._run_command
        self._timeout = timeout

    def synthesize(self, request: TtsRequest, output_path: Path) -> TtsResult:
        if os.name != "nt":
            raise TtsProviderError("Windows SAPI is only available on Windows")
        if not isinstance(request, TtsRequest):
            raise TypeError("request must be a TtsRequest")
        output = output_path.resolve(strict=False)
        if output.suffix.casefold() != ".wav":
            raise ValueError("output_path must be a WAV path")
        powershell = shutil.which("powershell") or shutil.which("powershell.exe")
        if not powershell:
            raise TtsProviderError("Windows PowerShell is not available")
        encode = lambda value: base64.b64encode(value.encode("utf-8")).decode("ascii")
        script = (
            "$ErrorActionPreference='Stop';"
            "$text=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($args[0]));"
            "$voice=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($args[1]));"
            "$path=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($args[2]));"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "if($voice){$s.SelectVoice($voice)};"
            "$s.Rate=[Math]::Max(-10,[Math]::Min(10,[int](($args[3]-1)*5)));"
            "$s.SetOutputToWaveFile($path);$s.Speak($text);$s.Dispose();"
        )
        command = [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
            encode(request.text),
            encode(request.voice or ""),
            encode(str(output)),
            str(request.rate),
        ]
        completed = self._command_runner(command, output_path=output, timeout=self._timeout)
        if getattr(completed, "returncode", 1) != 0 or not output.is_file():
            raise TtsProviderError("Windows SAPI did not produce a WAV file")
        data = output.read_bytes()
        if not data.startswith(b"RIFF"):
            raise TtsProviderError("Windows SAPI produced an invalid WAV file")
        return TtsResult(output, "windows-sapi", hashlib.sha256(data).hexdigest())

    @staticmethod
    def _run_command(command: list[str], *, output_path: Path, timeout: float):
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


__all__ = ["CloudTtsProvider", "TtsProviderError", "TtsRequest", "TtsResult", "WindowsSapiTts"]
