from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess
from dataclasses import dataclass

user32 = ctypes.windll.user32

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

@dataclass(frozen=True)
class WowWindow:
    hwnd: int
    pid: int
    title: str
    process_name: str


def _process_name(pid: int) -> str:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            text=True,
            encoding="cp1252",
            errors="replace",
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()
    except Exception:
        return ""
    if not out or out.startswith("INFO:"):
        return ""
    # CSV: "Image Name","PID",...
    return out.split('","', 1)[0].strip('"')


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def find_visible_wow_windows(title_terms: tuple[str, ...] = ("world of warcraft",)) -> list[WowWindow]:
    found: list[WowWindow] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title:
            return True
        lowered = title.casefold()
        if not any(term.casefold() in lowered for term in title_terms):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        name = _process_name(int(pid.value))
        found.append(WowWindow(int(hwnd), int(pid.value), title, name))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    # De-duplicate by hwnd and prefer actual WoW executable names.
    unique = {w.hwnd: w for w in found}
    return sorted(unique.values(), key=lambda w: ("wow" not in w.process_name.casefold(), w.pid))


def find_best_wow_window(preferred_pid: int | None = None) -> WowWindow | None:
    windows = find_visible_wow_windows()
    if preferred_pid is not None:
        for window in windows:
            if window.pid == preferred_pid:
                return window
        return None  # An explicitly chosen PID never falls back to another client.
    return windows[0] if windows else None


def focus_selected_wow_window(pid: int) -> bool:
    """Restore and focus only the exact selected WoW PID; never fall back."""
    window = find_best_wow_window(pid)
    if window is None:
        return False
    user32.ShowWindow(window.hwnd, 9)  # SW_RESTORE
    # SetForegroundWindow is asynchronous and its BOOL can be false even when
    # Windows completes the transition.  Finding the exact selected PID is
    # enough here: AgentRuntime performs the authoritative foreground-PID
    # check again after its five-second arming delay, before any input is sent.
    user32.SetForegroundWindow(window.hwnd)
    return True
