"""Shared wizard paths/constants and the background ProcessRunner.

Split out of wizard.py (2026-10-05); unchanged and re-exported there.
"""
from __future__ import annotations
from pathlib import Path
import queue
import re
import subprocess
import threading
from . import checks


PROJECT = Path(__file__).resolve().parents[3]


GUI_CONFIG = PROJECT / "output" / "agent" / "agent_gui.json"


RUNTIME_MODEL = PROJECT / "models" / "world3d_units_3class_v10_e65.pt"


STEPS = ("Rendszer", "Python csomagok", "WoW mappa", "Addon", "Navigációs adatok",
         "YOLO modell", "Automatikus indítás", "Befejezés")


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ProcessRunner:
    """Run commands one after another off the Tk thread, streaming output."""

    def __init__(self) -> None:
        self.lines: queue.SimpleQueue = queue.SimpleQueue()
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self.cancelled = False

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, commands: list[list[str]], cwd: Path, on_done) -> None:
        self.cancelled = False
        self.thread = threading.Thread(target=self._run, args=(commands, cwd, on_done), daemon=True)
        self.thread.start()

    def _run(self, commands, cwd, on_done) -> None:
        code = 0
        for command in commands:
            if self.cancelled:
                code = None
                break
            self.lines.put(f"> {subprocess.list2cmdline(command)}")
            try:
                self.process = subprocess.Popen(
                    command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, bufsize=0, creationflags=NO_WINDOW)
            except OSError as error:
                self.lines.put(f"Nem indítható: {error}")
                code = -1
                break
            pending = ""
            while True:
                chunk = self.process.stdout.read(4096)
                if not chunk:
                    break
                pending += chunk.decode("utf-8", errors="replace")
                parts = re.split(r"[\r\n]+", pending)
                pending = parts.pop()
                for part in parts:
                    if part.strip():
                        self.lines.put(part)
            if pending.strip():
                self.lines.put(pending)
            code = self.process.wait()
            self.lines.put(f"  -> {checks.explain_exit_code(code)}")
            if code != 0:
                break
        self.process = None
        on_done(None if self.cancelled else code)

    def cancel(self) -> None:
        self.cancelled = True
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
