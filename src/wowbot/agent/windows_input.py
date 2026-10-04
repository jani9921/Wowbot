"""Windows SendInput boundary; no process memory access or injection."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from .executor import ExecutionError
from .coordinates import pixel_context, client_to_screen


class Mouse(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD), ("time", w.DWORD), ("extra", ctypes.c_size_t)]


class Keyboard(ctypes.Structure):
    _fields_ = [("vk", w.WORD), ("scan", w.WORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", ctypes.c_size_t)]


class Hardware(ctypes.Structure):
    _fields_ = [("msg", w.DWORD), ("low", w.WORD), ("high", w.WORD)]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", Mouse), ("ki", Keyboard), ("hi", Hardware)]


class Input(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", InputUnion)]


KEYS = {"SPACE": 0x20, "TAB": 9, "ESCAPE": 27, "ENTER": 13, "BACKSPACE": 8,
        "SHIFT": 16, "CTRL": 17, "ALT": 18, "UP": 38, "DOWN": 40, "LEFT": 37, "RIGHT": 39,
        "HOME": 36, "END": 35, "PAGEUP": 33, "PAGEDOWN": 34, "INSERT": 45, "DELETE": 46,
        "NUMLOCK": 144, "NUMPADPLUS": 107, "NUMPADMINUS": 109, "NUMPADMULTIPLY": 106,
        "NUMPADDIVIDE": 111, "NUMPADDECIMAL": 110, "-": 189, "=": 187, "`": 192,
        "[": 219, "]": 221, "\\": 220, ";": 186, "'": 222, ",": 188, ".": 190, "/": 191}
KEYS.update({f"F{i}": 111 + i for i in range(1, 25)})
KEYS.update({f"NUMPAD{i}": 96 + i for i in range(10)})
KEYS.update({chr(i): i for i in range(48, 91) if chr(i).isalnum()})


class WindowsInput:
    def __init__(self, pid: int):
        self.pid = pid
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.GetForegroundWindow.restype = w.HWND
        self.api.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        self.api.GetWindowThreadProcessId.restype = w.DWORD
        self.api.SendInput.argtypes = [w.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.api.SendInput.restype = w.UINT
        self.api.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        self.api.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
        self.api.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.api.SetCursorPos.restype = w.BOOL
        self.coordinate_diagnostics = {}

    def is_selected_foreground(self) -> bool:
        hwnd = self.api.GetForegroundWindow()
        owner = w.DWORD()
        self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        return owner.value == self.pid

    def emergency_pressed(self) -> bool:
        return bool(self.api.GetAsyncKeyState(0x7B) & 0x8000)

    def is_key_down(self, key: str) -> bool:
        """Real OS-level key state, independent of our own _held bookkeeping.

        GetAsyncKeyState reflects physical key state regardless of which
        window has focus; a synthetic key we sent can still be reported
        down even if the target window silently dropped the event, so this
        is a best-effort check, not a guarantee the game itself saw it.
        """
        code = KEYS.get(key)
        return code is not None and bool(self.api.GetAsyncKeyState(code) & 0x8000)

    @pixel_context("api")
    def move(self, x: float, y: float):
        if not self.is_selected_foreground():
            raise ExecutionError("A PID megváltozott input előtt")
        hwnd = self.api.GetForegroundWindow()
        rect, origin = w.RECT(), w.POINT()
        if not self.api.GetClientRect(hwnd, ctypes.byref(rect)) or not self.api.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Every addon/UI coordinate uses normalized bottom-left client origin.
        screen_x, screen_y = client_to_screen(x, y, rect.right, rect.bottom, origin.x, origin.y)
        self.coordinate_diagnostics = {"dpi_context": "PER_MONITOR_AWARE_V2", "width": rect.right,
            "height": rect.bottom, "origin": [origin.x, origin.y], "requested": [x,y], "screen": [screen_x,screen_y]}
        if not self.is_selected_foreground() or self.api.GetForegroundWindow() != hwnd:
            raise ExecutionError("A kiválasztott ablak megváltozott koordinátaszámítás közben")
        if not self.api.SetCursorPos(screen_x, screen_y):
            raise ctypes.WinError(ctypes.get_last_error())

    def wheel_up(self):
        if not self.is_selected_foreground():
            raise ExecutionError("A kiválasztott PID nincs előtérben")
        event = Input()
        event.type = 0
        event.mi = Mouse(0, 0, 120, 0x0800, 0, 0)
        if self.api.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
            raise ExecutionError("Mouse wheel SendInput sikertelen")

    def key(self, key: str, down: bool):
        modifiers = []
        while any(key.startswith(m + "-") for m in ("CTRL", "SHIFT", "ALT")):
            modifier, key = key.split("-", 1)
            modifiers.append(modifier)
        order = modifiers + [key] if down else [key] + list(reversed(modifiers))
        # Validate first, so an unsupported chord cannot leave a modifier held.
        for part in order:
            if part not in KEYS and part not in {"BUTTON1", "BUTTON2", "BUTTON3", "BUTTON4", "BUTTON5"}:
                raise ExecutionError(f"Nem támogatott fizikai billentyű: {part}")
        for part in order:
            event = Input()
            if part.startswith("BUTTON"):
                code = int(part[-1])
                flags = {1: (2, 4), 2: (8, 16), 3: (32, 64), 4: (128, 256), 5: (128, 256)}[code]
                event.type = 0
                event.mi = Mouse(0, 0, (code - 3) if code >= 4 else 0, flags[0 if down else 1], 0, 0)
            else:
                event.type = 1
                event.ki = Keyboard(KEYS[part], 0, 0 if down else 2, 0, 0)
            if self.api.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
                raise ExecutionError(f"SendInput sikertelen: {ctypes.get_last_error()}")
