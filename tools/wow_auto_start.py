"""Start WoW (if needed), log in, enter the world and start the agent in FULL_AI.

User 2026-10-03.  Steps:
1. If no WoW window is open, start Wow.exe and wait for its window.
2. Type the password from ``config/wow_password.txt`` (first line; the user
   creates this file -- it is never written by the project) and press Enter.
3. Wait for character select and press Enter (default character).
4. Wait for the world to load, then start ``tools/run_agent.py --auto-full-ai``
   with the exact PID and the bindings cache last chosen in the GUI.

If WoW is already running, the login steps are skipped and only the agent
is started.  Keys are sent only while that exact WoW PID is the foreground
window.  ``--trial-seconds`` bounds the FULL_AI run (it returns to MANUAL).
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tools.wow_window import find_visible_wow_windows, focus_selected_wow_window  # noqa: E402

DEFAULT_WOW_EXE = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Wow.exe")
PASSWORD_FILE = ROOT / "config" / "wow_password.txt"
ACCOUNT_FILE = ROOT / "config" / "wow_account.txt"

user32 = ctypes.windll.user32
INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x0002, 0x0004
VK_RETURN = 0x0D


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _send(inputs: list[INPUT]) -> None:
    array = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    item = INPUT(type=INPUT_KEYBOARD)
    item.union.ki = KEYBDINPUT(vk, scan, flags, 0, None)
    return item


def _foreground_pid() -> int:
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _require_foreground(pid: int) -> None:
    focus_selected_wow_window(pid)
    for _ in range(20):
        if _foreground_pid() == pid:
            return
        time.sleep(.1)
        focus_selected_wow_window(pid)
    raise RuntimeError(f"A WoW (PID {pid}) nem került előtérbe; nem küldök billentyűt")


def type_text(pid: int, text: str) -> None:
    for char in text:
        _require_foreground(pid)
        code = ord(char)
        _send([_key(scan=code, flags=KEYEVENTF_UNICODE),
               _key(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)])
        time.sleep(.04)


def press_enter(pid: int) -> None:
    _require_foreground(pid)
    _send([_key(vk=VK_RETURN), _key(vk=VK_RETURN, flags=KEYEVENTF_KEYUP)])


def read_password() -> str:
    if not PASSWORD_FILE.is_file():
        raise SystemExit(
            f"Hiányzik a jelszófájl: {PASSWORD_FILE}\n"
            "Hozd létre, és az első sorába írd be a WoW jelszót (csak ezen a gépen tárold).")
    lines = PASSWORD_FILE.read_text(encoding="utf-8-sig").splitlines()
    password = lines[0].strip() if lines else ""
    if not password:
        raise SystemExit(f"A jelszófájl első sora üres: {PASSWORD_FILE}")
    return password


def set_account_name(wow_exe: Path) -> None:
    """Pre-fill the login screen's account name from config/wow_account.txt.

    Only the ``SET accountName`` line of WTF/Config.wtf is replaced (a copy of
    the original file is kept as Config.wtf.aipc-backup the first time).
    """
    if not ACCOUNT_FILE.is_file():
        return
    lines = ACCOUNT_FILE.read_text(encoding="utf-8-sig").splitlines()
    account = lines[0].strip() if lines else ""
    config = wow_exe.parent / "WTF" / "Config.wtf"
    if not account or not config.is_file():
        return
    text = config.read_text(encoding="utf-8", errors="replace")
    wanted = f'SET accountName "{account}"'
    rows = text.splitlines()
    if wanted in rows:
        return
    backup = config.with_name("Config.wtf.aipc-backup")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")
    rows = [row for row in rows if not row.startswith("SET accountName ")] + [wanted]
    config.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Fióknév beállítva a Config.wtf-ben: {account}")


def wait_for_window(timeout: float, pid: int | None = None) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows = find_visible_wow_windows()
        match = next((w for w in windows if pid is None or w.pid == pid), None)
        if match is not None:
            return match.pid
        time.sleep(1.)
    return None


def bindings_cache(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
    else:
        state = ROOT / "output" / "agent" / "agent_gui.json"
        try:
            path = Path(json.loads(state.read_text(encoding="utf-8")).get("bindings_cache") or "")
        except (OSError, ValueError):
            path = Path("")
    if explicit and not path.is_file():
        raise SystemExit(f"A megadott bindings-cache nem létezik: {path}")
    if not str(path) or not path.is_file():
        # Fresh PC: the GUI connects export-only and creates one.
        print("Nincs bindings-cache: export módban indul, és az addon exportjából készít egyet.")
        return None
    return path


def agent_environment() -> dict:
    env = dict(os.environ)
    defaults = {"AIPC_CAPTURE_BACKEND": "dxgi", "AIPC_CAPTURE_PROCESS": "1",
                # The live-vision preview window is diagnostics only (CPU);
                # off unless AIPC_LIVE_VISION is set explicitly.
                "AIPC_LIVE_VISION": "0", "AIPC_LIVE_VISION_HZ": "60",
                "AIPC_WORLD3D_PROPOSAL_MODE": "YOLO_ONLY", "AIPC_YOLO_PROCESS": "1",
                # Screenshots for the whole unattended trial (~2 s heartbeat).
                "AIPC_LIVE_CAPTURE_MAX_FRAMES": "900"}
    for key, value in defaults.items():
        env.setdefault(key, value)
    return env


def running_agents(pid: int) -> list[int]:
    """Process ids of run_agent.py instances already bound to this WoW PID.

    Live 2026-10-04 00:21: a finished trial's GUI stays open in MANUAL, so a
    new start put a second agent on the same client and profile database
    ("database is locked").
    """
    try:
        output = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
            capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in output.splitlines():
        process, _, command = line.partition("	")
        parts = command.split()
        if ("run_agent.py" in command and "--pid" in parts
                and parts.index("--pid") + 1 < len(parts)
                and parts[parts.index("--pid") + 1] == str(pid)):
            found.append(int(process))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wow-exe", default=os.environ.get("AIPC_WOW_EXE", str(DEFAULT_WOW_EXE)))
    parser.add_argument("--bindings-cache")
    parser.add_argument("--login-delay", type=float, default=20.,
                        help="seconds between the window appearing and typing the password")
    parser.add_argument("--charselect-delay", type=float, default=25.,
                        help="seconds between login and pressing Enter at character select")
    parser.add_argument("--world-delay", type=float, default=35.,
                        help="seconds for the world to load before the agent starts")
    parser.add_argument("--trial-seconds", type=float,
                        help="bounded FULL_AI run; the runtime returns to MANUAL afterwards")
    parser.add_argument("--no-agent", action="store_true", help="only log in")
    args = parser.parse_args()

    cache = None if args.no_agent else bindings_cache(args.bindings_cache)
    running = find_visible_wow_windows()
    if running:
        pid = running[0].pid
        print(f"A WoW már fut (PID {pid}); a belépést kihagyom.")
    else:
        password = read_password()
        exe = Path(args.wow_exe)
        if not exe.is_file():
            raise SystemExit(f"Nem található a WoW: {exe}")
        set_account_name(exe)
        print(f"WoW indítása: {exe}")
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
        pid = wait_for_window(180.)
        if pid is None:
            raise SystemExit("A WoW ablak 180 s alatt sem jelent meg")
        print(f"WoW ablak: PID {pid}; várok a belépő képernyőre ({args.login_delay:.0f} s)")
        time.sleep(args.login_delay)
        type_text(pid, password)
        press_enter(pid)
        password = ""
        print(f"Jelszó elküldve; karakterválasztó ({args.charselect_delay:.0f} s)")
        time.sleep(args.charselect_delay)
        press_enter(pid)
        print(f"Belépés a világba; betöltés ({args.world_delay:.0f} s)")
        time.sleep(args.world_delay)
    if args.no_agent:
        return 0
    others = running_agents(pid)
    if others:
        print(f"Már fut agent erre a WoW-ra (PID {pid}): {others}; előbb zárd be.")
        return 2
    env = agent_environment()
    if args.trial_seconds:
        env["AIPC_AUTO_FULL_AI_SECONDS"] = str(max(5., args.trial_seconds))
    command = [sys.executable, str(ROOT / "tools" / "run_agent.py"), "--gui", "--with-debugger",
               "--auto-full-ai", "--pid", str(pid)]
    if cache is not None:
        command += ["--bindings-cache", str(cache)]
    print("Agent indítása FULL_AI módban:", " ".join(command[2:]))
    return subprocess.call(command, cwd=str(ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
