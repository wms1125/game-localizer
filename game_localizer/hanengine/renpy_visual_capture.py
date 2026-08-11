from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from .segments import JsonValue


RENPY_CAPTURE_PLAN_SCHEMA_VERSION = "hanengine.renpy-capture-plan/v2"
RENPY_CAPTURE_REPORT_SCHEMA_VERSION = "hanengine.renpy-capture-report/v2"
_LEGACY_CAPTURE_PLAN_SCHEMA_VERSION = "hanengine.renpy-capture-plan/v1"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class RenPyVisualCaptureError(RuntimeError):
    pass


class CaptureActionKind(str, Enum):
    CLICK = "click"
    RIGHT_CLICK = "right_click"
    PRESS = "press"


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _mapping_sequence(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of objects")
    items = tuple(value)
    if any(not isinstance(item, Mapping) for item in items):
        raise TypeError(f"{name} must contain only objects")
    return items


def _exact_keys(payload: Mapping[str, object], expected: Sequence[str], name: str) -> None:
    if set(payload) != set(expected):
        raise ValueError(f"{name} payload fields do not match schema")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _number(value: object, name: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return number


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != _PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise RenPyVisualCaptureError(f"capture is not a valid PNG: {path.name}")
    width, height = struct.unpack(">II", header[16:24])
    if width < 1 or height < 1:
        raise RenPyVisualCaptureError(f"capture has invalid dimensions: {path.name}")
    return width, height


@dataclass(frozen=True)
class CaptureAction:
    kind: CaptureActionKind
    x: float | None
    y: float | None
    key: str | None
    delay_seconds: float
    repeat: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CaptureActionKind):
            raise TypeError("kind must be CaptureActionKind")
        object.__setattr__(
            self,
            "delay_seconds",
            _number(self.delay_seconds, "delay_seconds", minimum=0, maximum=30),
        )
        if isinstance(self.repeat, bool) or not isinstance(self.repeat, int) or not 1 <= self.repeat <= 100:
            raise ValueError("repeat must be between 1 and 100")
        if self.kind in {CaptureActionKind.CLICK, CaptureActionKind.RIGHT_CLICK}:
            object.__setattr__(self, "x", _number(self.x, "x", minimum=0, maximum=1))
            object.__setattr__(self, "y", _number(self.y, "y", minimum=0, maximum=1))
            if self.key is not None:
                raise ValueError("mouse actions must not define key")
        else:
            if self.x is not None or self.y is not None:
                raise ValueError("press actions must not define x or y")
            object.__setattr__(self, "key", _string(self.key, "key").casefold())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "x": self.x,
            "y": self.y,
            "key": self.key,
            "delay_seconds": self.delay_seconds,
            "repeat": self.repeat,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "CaptureAction":
        payload = _mapping(payload, "capture_action")
        _exact_keys(payload, ("kind", "x", "y", "key", "delay_seconds", "repeat"), "capture_action")
        try:
            kind = CaptureActionKind(payload["kind"])
        except (TypeError, ValueError) as exc:
            raise ValueError("capture action kind is invalid") from exc
        return cls(
            kind=kind,
            x=payload["x"],
            y=payload["y"],
            key=payload["key"],
            delay_seconds=payload["delay_seconds"],
            repeat=payload["repeat"],
        )


@dataclass(frozen=True)
class CaptureScenario:
    sample_id: str
    actions: tuple[CaptureAction, ...]
    expected_screen: str | None = None
    screen_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _string(self.sample_id, "sample_id"))
        actions = tuple(self.actions)
        if any(not isinstance(item, CaptureAction) for item in actions):
            raise TypeError("actions must contain CaptureAction values")
        object.__setattr__(self, "actions", actions)
        if self.expected_screen is not None:
            object.__setattr__(self, "expected_screen", _string(self.expected_screen, "expected_screen"))
        object.__setattr__(
            self,
            "screen_timeout_seconds",
            _number(self.screen_timeout_seconds, "screen_timeout_seconds", minimum=0.5, maximum=30),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "sample_id": self.sample_id,
            "actions": [item.to_dict() for item in self.actions],
            "expected_screen": self.expected_screen,
            "screen_timeout_seconds": self.screen_timeout_seconds,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
        *,
        require_screen_assertion: bool = True,
    ) -> "CaptureScenario":
        payload = _mapping(payload, "capture_scenario")
        expected = ("sample_id", "actions", "expected_screen", "screen_timeout_seconds")
        if not require_screen_assertion:
            expected = ("sample_id", "actions")
        _exact_keys(payload, expected, "capture_scenario")
        actions = _mapping_sequence(payload["actions"], "actions")
        return cls(
            sample_id=payload["sample_id"],
            actions=tuple(CaptureAction.from_dict(item) for item in actions),
            expected_screen=payload.get("expected_screen"),
            screen_timeout_seconds=payload.get("screen_timeout_seconds", 5.0),
        )


@dataclass(frozen=True)
class RenPyCapturePlan:
    window_title: str
    window_timeout_seconds: float
    post_focus_wait_seconds: float
    scenarios: tuple[CaptureScenario, ...]
    schema_version: str = RENPY_CAPTURE_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version not in {RENPY_CAPTURE_PLAN_SCHEMA_VERSION, _LEGACY_CAPTURE_PLAN_SCHEMA_VERSION}:
            raise ValueError(
                "schema_version must be "
                f"{RENPY_CAPTURE_PLAN_SCHEMA_VERSION} or {_LEGACY_CAPTURE_PLAN_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "window_title", _string(self.window_title, "window_title"))
        object.__setattr__(
            self,
            "window_timeout_seconds",
            _number(self.window_timeout_seconds, "window_timeout_seconds", minimum=1, maximum=120),
        )
        object.__setattr__(
            self,
            "post_focus_wait_seconds",
            _number(self.post_focus_wait_seconds, "post_focus_wait_seconds", minimum=0, maximum=10),
        )
        scenarios = tuple(self.scenarios)
        if not scenarios or any(not isinstance(item, CaptureScenario) for item in scenarios):
            raise ValueError("scenarios must contain CaptureScenario values")
        ids = [item.sample_id for item in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenarios must contain unique sample IDs")
        if self.schema_version == RENPY_CAPTURE_PLAN_SCHEMA_VERSION:
            if any(item.expected_screen is None for item in scenarios):
                raise ValueError("v2 capture scenarios must define expected_screen")
        elif any(item.expected_screen is not None for item in scenarios):
            raise ValueError("v1 capture scenarios must not define expected_screen")
        object.__setattr__(self, "scenarios", scenarios)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "window_title": self.window_title,
            "window_timeout_seconds": self.window_timeout_seconds,
            "post_focus_wait_seconds": self.post_focus_wait_seconds,
            "scenarios": [
                (
                    item.to_dict()
                    if self.schema_version == RENPY_CAPTURE_PLAN_SCHEMA_VERSION
                    else {"sample_id": item.sample_id, "actions": [action.to_dict() for action in item.actions]}
                )
                for item in self.scenarios
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RenPyCapturePlan":
        payload = _mapping(payload, "renpy_capture_plan")
        _exact_keys(
            payload,
            (
                "schema_version",
                "window_title",
                "window_timeout_seconds",
                "post_focus_wait_seconds",
                "scenarios",
            ),
            "renpy_capture_plan",
        )
        schema_version = payload["schema_version"]
        if schema_version not in {RENPY_CAPTURE_PLAN_SCHEMA_VERSION, _LEGACY_CAPTURE_PLAN_SCHEMA_VERSION}:
            raise ValueError("capture plan schema_version is unsupported")
        scenarios = _mapping_sequence(payload["scenarios"], "scenarios")
        return cls(
            schema_version=schema_version,
            window_title=payload["window_title"],
            window_timeout_seconds=payload["window_timeout_seconds"],
            post_focus_wait_seconds=payload["post_focus_wait_seconds"],
            scenarios=tuple(
                CaptureScenario.from_dict(
                    item,
                    require_screen_assertion=schema_version == RENPY_CAPTURE_PLAN_SCHEMA_VERSION,
                )
                for item in scenarios
            ),
        )


@dataclass(frozen=True)
class ScreenAssertionResult:
    sample_id: str
    expected_screen: str
    observed_screens: tuple[str, ...]
    passed: bool

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "sample_id": self.sample_id,
            "expected_screen": self.expected_screen,
            "observed_screens": list(self.observed_screens),
            "passed": self.passed,
        }


@dataclass(frozen=True)
class BackendCaptureResult:
    status: str
    returncode: int | None
    window_geometry: tuple[int, int, int, int]
    traceback_present: bool
    stdout_bytes: int
    stderr_bytes: int
    screen_assertions: tuple[ScreenAssertionResult, ...] = ()


class RenPyCaptureBackend(Protocol):
    def capture(
        self,
        launcher: Path,
        project_root: Path,
        output_root: Path,
        save_root: Path,
        plan: RenPyCapturePlan,
    ) -> BackendCaptureResult: ...


class WindowsRenPyCaptureBackend:
    _VK_CODES = {"escape": 0x1B, "enter": 0x0D, "space": 0x20}
    _SCREEN_STATE_ENV = "HANENGINE_RENPY_SCREEN_STATE"
    _WINDOW_TITLE_ENV = "HANENGINE_RENPY_WINDOW_TITLE"

    @staticmethod
    def _install_screen_probe(project_root: Path, plan: RenPyCapturePlan) -> Path | None:
        screen_names = tuple(
            dict.fromkeys(
                scenario.expected_screen
                for scenario in plan.scenarios
                if scenario.expected_screen is not None
            )
        )
        if not screen_names:
            return None
        game_root = project_root / "game"
        if not game_root.is_dir():
            raise RenPyVisualCaptureError("Ren'Py shadow project is missing its game directory")
        probe_path = game_root / f"_hanengine_visual_probe_{uuid.uuid4().hex}.rpy"
        names_literal = json.dumps(screen_names, ensure_ascii=True)
        probe_path.write_text(
            "init -1000 python:\n"
            "    import json as _hanengine_json\n"
            "    import os as _hanengine_os\n"
            f"    _hanengine_screen_names = {names_literal}\n"
            "    def _hanengine_write_screen_state():\n"
            "        try:\n"
            f"            _state_path = _hanengine_os.environ.get('{WindowsRenPyCaptureBackend._SCREEN_STATE_ENV}')\n"
            "            if not _state_path:\n"
            "                return\n"
            "            _screens = [name for name in _hanengine_screen_names if renpy.get_screen(name) is not None]\n"
            "            _temporary = _state_path + '.tmp'\n"
            "            with open(_temporary, 'w', encoding='utf-8') as _stream:\n"
            "                _hanengine_json.dump({'screens': _screens}, _stream, sort_keys=True)\n"
            "            _hanengine_os.replace(_temporary, _state_path)\n"
            "        except Exception:\n"
            "            pass\n"
            "    renpy.config.periodic_callbacks.append(_hanengine_write_screen_state)\n",
            encoding="utf-8",
            newline="\n",
        )
        return probe_path

    @staticmethod
    def _read_observed_screens(state_path: Path) -> tuple[str, ...]:
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ()
        screens = payload.get("screens") if isinstance(payload, Mapping) else None
        if isinstance(screens, (str, bytes)) or not isinstance(screens, Sequence):
            return ()
        if any(not isinstance(item, str) or not item for item in screens):
            return ()
        return tuple(screens)

    @staticmethod
    def _capture_window_png(hwnd: int, width: int, height: int, output: Path) -> bool:
        """Capture the target HWND without depending on the desktop foreground image."""
        try:
            import ctypes
            from ctypes import wintypes
            from PIL import Image
        except ImportError:
            return False
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        user32.GetWindowDC.argtypes = (wintypes.HWND,)
        user32.GetWindowDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
        user32.ReleaseDC.restype = ctypes.c_int
        user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
        user32.PrintWindow.restype = wintypes.BOOL
        gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
        gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
        gdi32.SelectObject.restype = wintypes.HANDLE
        gdi32.GetDIBits.argtypes = (
            wintypes.HDC,
            wintypes.HBITMAP,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.UINT,
        )
        gdi32.GetDIBits.restype = ctypes.c_int
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = (wintypes.HDC,)
        gdi32.DeleteDC.restype = wintypes.BOOL
        hdc = user32.GetWindowDC(hwnd)
        if not hdc:
            return False
        memory_dc = gdi32.CreateCompatibleDC(hdc)
        bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
        if not memory_dc or not bitmap:
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(hwnd, hdc)
            return False
        previous = gdi32.SelectObject(memory_dc, bitmap)
        try:
            rendered = user32.PrintWindow(hwnd, memory_dc, 2)
            if not rendered:
                return False

            class BitmapInfoHeader(ctypes.Structure):
                _fields_ = (
                    ("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                )

            class BitmapInfo(ctypes.Structure):
                _fields_ = (("bmiHeader", BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3))

            info = BitmapInfo()
            info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = 0
            pixels = ctypes.create_string_buffer(width * height * 4)
            copied = gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                height,
                pixels,
                ctypes.byref(info),
                0,
            )
            if copied != height:
                return False
            image = Image.frombytes(
                "RGBA",
                (width, height),
                pixels.raw,
                "raw",
                "BGRA",
                0,
                1,
            )
            image.save(output, format="PNG")
            return True
        finally:
            if previous:
                gdi32.SelectObject(memory_dc, previous)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(hwnd, hdc)

    @classmethod
    def _wait_for_expected_screen(
        cls,
        scenario: CaptureScenario,
        state_path: Path,
        process: subprocess.Popen[str],
    ) -> ScreenAssertionResult | None:
        if scenario.expected_screen is None:
            return None
        deadline = time.monotonic() + scenario.screen_timeout_seconds
        observed: tuple[str, ...] = ()
        while time.monotonic() < deadline:
            observed = cls._read_observed_screens(state_path)
            if scenario.expected_screen in observed:
                return ScreenAssertionResult(
                    sample_id=scenario.sample_id,
                    expected_screen=scenario.expected_screen,
                    observed_screens=observed,
                    passed=True,
                )
            if process.poll() is not None:
                break
            time.sleep(0.05)
        return ScreenAssertionResult(
            sample_id=scenario.sample_id,
            expected_screen=scenario.expected_screen,
            observed_screens=observed,
            passed=False,
        )

    def capture(
        self,
        launcher: Path,
        project_root: Path,
        output_root: Path,
        save_root: Path,
        plan: RenPyCapturePlan,
    ) -> BackendCaptureResult:
        if os.name != "nt":
            raise RenPyVisualCaptureError("Windows capture backend is only available on Windows")
        try:
            import ctypes
            import mss
            import mss.tools
            import pygetwindow
        except ImportError as exc:
            raise RenPyVisualCaptureError("Windows capture requires mss and pygetwindow") from exc
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        state_path = save_root.parent / "screen-state.json"
        self._install_screen_probe(project_root, plan)

        def force_foreground(hwnd: int) -> None:
            foreground = user32.GetForegroundWindow()
            process_id = ctypes.c_ulong()
            foreground_thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(process_id))
            target_thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            current_thread = kernel32.GetCurrentThreadId()
            attached: list[int] = []
            for thread in (foreground_thread, target_thread):
                if thread and thread != current_thread and user32.AttachThreadInput(current_thread, thread, True):
                    attached.append(thread)
            try:
                user32.ShowWindow(hwnd, 5)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
                user32.SetForegroundWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                for thread in attached:
                    user32.AttachThreadInput(current_thread, thread, False)

        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment.setdefault("RENPY_RENDERER", "angle2")
        environment[self._SCREEN_STATE_ENV] = str(state_path)
        process = subprocess.Popen(
            [str(launcher), str(project_root), "--savedir", str(save_root)],
            cwd=launcher.parent,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        def locate_window(
            timeout_seconds: float,
            *,
            expected_size: tuple[int, int] | None = None,
        ):
            window_title = os.environ.get(self._WINDOW_TITLE_ENV, plan.window_title)
            deadline = time.monotonic() + timeout_seconds
            last_window_key: tuple[int, int, int, int, int] | None = None
            stable_reads = 0
            while time.monotonic() < deadline:
                matches = []
                for candidate in pygetwindow.getAllWindows():
                    if not candidate.title or window_title.casefold() not in candidate.title.casefold():
                        continue
                    candidate_process_id = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(
                        candidate._hWnd,
                        ctypes.byref(candidate_process_id),
                    )
                    size = (candidate.width, candidate.height)
                    if (
                        candidate_process_id.value != process.pid
                        or not user32.IsWindowVisible(candidate._hWnd)
                        or size[0] < 320
                        or size[1] < 180
                        or (expected_size is not None and size != expected_size)
                    ):
                        continue
                    matches.append(candidate)
                if matches:
                    candidate = max(matches, key=lambda item: item.width * item.height)
                    window_key = (
                        candidate._hWnd,
                        candidate.left,
                        candidate.top,
                        candidate.width,
                        candidate.height,
                    )
                    if window_key == last_window_key:
                        stable_reads += 1
                    else:
                        last_window_key = window_key
                        stable_reads = 1
                    if stable_reads >= 2:
                        return candidate
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            raise RenPyVisualCaptureError("Ren'Py window did not reach stable capture geometry")

        window = None
        stdout = ""
        stderr = ""
        screen_assertions: list[ScreenAssertionResult] = []
        try:
            window = locate_window(plan.window_timeout_seconds)
            force_foreground(window._hWnd)
            time.sleep(plan.post_focus_wait_seconds)
            geometry = (window.left, window.top, window.width, window.height)
            capture_size = (window.width, window.height)
            output_root.mkdir(parents=True, exist_ok=True)
            for scenario in plan.scenarios:
                expected_screen_reached = False
                for action in scenario.actions:
                    for _ in range(action.repeat):
                        window = locate_window(
                            scenario.screen_timeout_seconds,
                            expected_size=capture_size,
                        )
                        force_foreground(window._hWnd)
                        if action.kind in {CaptureActionKind.CLICK, CaptureActionKind.RIGHT_CLICK}:
                            user32.SetCursorPos(
                                window.left + round(action.x * window.width),
                                window.top + round(action.y * window.height),
                            )
                            if action.kind is CaptureActionKind.CLICK:
                                user32.mouse_event(2, 0, 0, 0, 0)
                                user32.mouse_event(4, 0, 0, 0, 0)
                            else:
                                user32.mouse_event(8, 0, 0, 0, 0)
                                user32.mouse_event(16, 0, 0, 0, 0)
                        else:
                            try:
                                key_code = self._VK_CODES[action.key]
                            except KeyError as exc:
                                raise RenPyVisualCaptureError(f"unsupported key: {action.key}") from exc
                            user32.keybd_event(key_code, 0, 0, 0)
                            user32.keybd_event(key_code, 0, 2, 0)
                        time.sleep(action.delay_seconds)
                        if (
                            scenario.expected_screen is not None
                            and scenario.expected_screen in self._read_observed_screens(state_path)
                        ):
                            expected_screen_reached = True
                            break
                    if expected_screen_reached:
                        break
                assertion = self._wait_for_expected_screen(scenario, state_path, process)
                if assertion is not None:
                    screen_assertions.append(assertion)
                window = locate_window(
                    scenario.screen_timeout_seconds,
                    expected_size=capture_size,
                )
                force_foreground(window._hWnd)
                screenshot_path = output_root / f"{scenario.sample_id}.png"
                if not self._capture_window_png(window._hWnd, window.width, window.height, screenshot_path):
                    with mss.mss() as screen:
                        image = screen.grab(
                            {
                                "left": max(window.left, 0),
                                "top": max(window.top, 0),
                                "width": window.width,
                                "height": window.height,
                            }
                        )
                        mss.tools.to_png(image.rgb, image.size, output=str(screenshot_path))
        finally:
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
        traceback_present = (project_root / "traceback.txt").exists()
        status = "passed" if window is not None and not traceback_present else "failed"
        return BackendCaptureResult(
            status=status,
            returncode=process.returncode,
            window_geometry=geometry,
            traceback_present=traceback_present,
            stdout_bytes=len(stdout.encode("utf-8")),
            stderr_bytes=len(stderr.encode("utf-8")),
            screen_assertions=tuple(screen_assertions),
        )


@dataclass(frozen=True)
class CapturedScreenshot:
    sample_id: str
    relative_path: str
    sha256: str
    width: int
    height: int

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "sample_id": self.sample_id,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class CaptureVariantReport:
    variant: str
    source_tree_sha256: str
    source_preserved: bool
    status: str
    returncode: int | None
    window_geometry: tuple[int, int, int, int]
    traceback_present: bool
    stdout_bytes: int
    stderr_bytes: int
    screenshots: tuple[CapturedScreenshot, ...]
    screen_assertions: tuple[ScreenAssertionResult, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "variant": self.variant,
            "source_tree_sha256": self.source_tree_sha256,
            "source_preserved": self.source_preserved,
            "status": self.status,
            "returncode": self.returncode,
            "window_geometry": list(self.window_geometry),
            "traceback_present": self.traceback_present,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "screenshots": [item.to_dict() for item in self.screenshots],
            "screen_assertions": [item.to_dict() for item in self.screen_assertions],
        }


@dataclass(frozen=True)
class RenPyCapturePairReport:
    created_at: str
    authorization_reference: str
    plan_sha256: str
    plan_schema_version: str
    reference: CaptureVariantReport
    candidate: CaptureVariantReport
    schema_version: str = RENPY_CAPTURE_REPORT_SCHEMA_VERSION

    @property
    def capture_passed(self) -> bool:
        return (
            self.reference.status == "passed"
            and self.candidate.status == "passed"
            and self.reference.source_preserved
            and self.candidate.source_preserved
        )

    @property
    def semantic_alignment_verified(self) -> bool:
        return (
            self.plan_schema_version == RENPY_CAPTURE_PLAN_SCHEMA_VERSION
            and bool(self.reference.screen_assertions)
            and bool(self.candidate.screen_assertions)
            and all(item.passed for item in self.reference.screen_assertions)
            and all(item.passed for item in self.candidate.screen_assertions)
        )

    @property
    def passed(self) -> bool:
        return self.capture_passed and self.semantic_alignment_verified

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "authorization_reference": self.authorization_reference,
            "plan_sha256": self.plan_sha256,
            "plan_schema_version": self.plan_schema_version,
            "capture_passed": self.capture_passed,
            "semantic_alignment_verified": self.semantic_alignment_verified,
            "passed": self.passed,
            "reference": self.reference.to_dict(),
            "candidate": self.candidate.to_dict(),
        }


def load_renpy_capture_plan(path: Path) -> RenPyCapturePlan:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RenPyVisualCaptureError("capture plan could not be read") from exc
    return RenPyCapturePlan.from_dict(_mapping(payload, "renpy_capture_plan"))


def _variant_report(
    variant: str,
    source: Path,
    output_root: Path,
    plan: RenPyCapturePlan,
    backend: RenPyCaptureBackend,
    launcher: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> CaptureVariantReport:
    from .validation import tree_sha256

    source_before = tree_sha256(source)
    with tempfile.TemporaryDirectory(prefix=f"hanengine-renpy-{variant}-") as temporary:
        temporary_root = Path(temporary)
        shadow = temporary_root / "project"
        shutil.copytree(source, shadow, symlinks=True)
        previous_environment = os.environ.copy()
        try:
            if environment:
                os.environ.update(environment)
            result = backend.capture(
                launcher,
                shadow,
                output_root,
                temporary_root / "savedir",
                plan,
            )
        finally:
            os.environ.clear()
            os.environ.update(previous_environment)
        if plan.schema_version == RENPY_CAPTURE_PLAN_SCHEMA_VERSION:
            expected_assertions = [
                (scenario.sample_id, scenario.expected_screen)
                for scenario in plan.scenarios
            ]
            actual_assertions = [
                (assertion.sample_id, assertion.expected_screen)
                for assertion in result.screen_assertions
            ]
            if actual_assertions != expected_assertions:
                raise RenPyVisualCaptureError("capture backend did not report every screen assertion")
    source_after = tree_sha256(source)
    screenshots: list[CapturedScreenshot] = []
    for scenario in plan.scenarios:
        path = output_root / f"{scenario.sample_id}.png"
        if not path.is_file() or path.is_symlink():
            raise RenPyVisualCaptureError(f"capture is missing: {variant}/{scenario.sample_id}.png")
        width, height = _png_size(path)
        screenshots.append(
            CapturedScreenshot(
                sample_id=scenario.sample_id,
                relative_path=f"{variant}/{scenario.sample_id}.png",
                sha256=_sha256(path),
                width=width,
                height=height,
            )
        )
    return CaptureVariantReport(
        variant=variant,
        source_tree_sha256=source_before,
        source_preserved=source_before == source_after,
        status=result.status,
        returncode=result.returncode,
        window_geometry=result.window_geometry,
        traceback_present=result.traceback_present,
        stdout_bytes=result.stdout_bytes,
        stderr_bytes=result.stderr_bytes,
        screenshots=tuple(screenshots),
        screen_assertions=result.screen_assertions,
    )


def _write_report(report: RenPyCapturePairReport, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def run_renpy_capture_pair(
    launcher: Path,
    reference_project: Path,
    candidate_project: Path,
    plan_path: Path,
    output_root: Path,
    *,
    authorization_reference: str,
    reference_game_language: str | None = None,
    candidate_game_language: str | None = None,
    reference_window_title: str | None = None,
    candidate_window_title: str | None = None,
    backend_factory: Callable[[], RenPyCaptureBackend] = WindowsRenPyCaptureBackend,
) -> RenPyCapturePairReport:
    authorization_reference = _string(authorization_reference, "authorization_reference")
    launcher = launcher.expanduser().resolve(strict=True)
    reference_project = reference_project.expanduser().resolve(strict=True)
    candidate_project = candidate_project.expanduser().resolve(strict=True)
    plan_path = plan_path.expanduser().resolve(strict=True)
    output_root = output_root.expanduser().absolute()
    if not launcher.is_file():
        raise RenPyVisualCaptureError("launcher must be a file")
    if not reference_project.is_dir() or not candidate_project.is_dir():
        raise RenPyVisualCaptureError("reference and candidate projects must be directories")
    if reference_project == candidate_project:
        raise RenPyVisualCaptureError("reference and candidate projects must differ")
    for source in (reference_project, candidate_project):
        if output_root == source or source in output_root.parents or output_root in source.parents:
            raise RenPyVisualCaptureError("output_root must be outside both project trees")
    if output_root.exists() and any(output_root.iterdir()):
        raise RenPyVisualCaptureError("output_root must be empty")
    output_root.mkdir(parents=True, exist_ok=True)
    plan = load_renpy_capture_plan(plan_path)
    backend = backend_factory()
    reference = _variant_report(
        "reference",
        reference_project,
        output_root / "reference",
        plan,
        backend,
        launcher,
        environment={
            key: value
            for key, value in {
                "HANENGINE_GAME_LANGUAGE": reference_game_language,
                WindowsRenPyCaptureBackend._WINDOW_TITLE_ENV: reference_window_title,
            }.items()
            if value is not None
        },
    )
    candidate = _variant_report(
        "candidate",
        candidate_project,
        output_root / "candidate",
        plan,
        backend,
        launcher,
        environment={
            key: value
            for key, value in {
                "HANENGINE_GAME_LANGUAGE": candidate_game_language,
                WindowsRenPyCaptureBackend._WINDOW_TITLE_ENV: candidate_window_title,
            }.items()
            if value is not None
        },
    )
    reference_sizes = [(item.sample_id, item.width, item.height) for item in reference.screenshots]
    candidate_sizes = [(item.sample_id, item.width, item.height) for item in candidate.screenshots]
    if reference_sizes != candidate_sizes:
        raise RenPyVisualCaptureError("reference and candidate captures must use identical dimensions")
    report = RenPyCapturePairReport(
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        authorization_reference=authorization_reference,
        plan_sha256=_sha256(plan_path),
        plan_schema_version=plan.schema_version,
        reference=reference,
        candidate=candidate,
    )
    _write_report(report, output_root / "capture-report.json")
    return report


__all__ = [
    "BackendCaptureResult",
    "CaptureAction",
    "CaptureActionKind",
    "CaptureScenario",
    "CaptureVariantReport",
    "CapturedScreenshot",
    "RENPY_CAPTURE_PLAN_SCHEMA_VERSION",
    "RENPY_CAPTURE_REPORT_SCHEMA_VERSION",
    "RenPyCaptureBackend",
    "RenPyCapturePairReport",
    "RenPyCapturePlan",
    "RenPyVisualCaptureError",
    "ScreenAssertionResult",
    "WindowsRenPyCaptureBackend",
    "load_renpy_capture_plan",
    "run_renpy_capture_pair",
]
