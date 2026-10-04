"""Legacy console logger retained under a non-stdlib-colliding package name."""

from __future__ import annotations

import datetime as _dt
from typing import Any

try:
    from src.core.interfaces import ILogger
except (ImportError, ModuleNotFoundError):
    class ILogger:  # Legacy compatibility only; wowbot does not import this module.
        pass


class ConsoleLogger(ILogger):
    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        self.history: list[str] = []

    def log(self, client_id: str, message: str, level: str = "INFO", **fields: Any) -> None:
        if level == "DEBUG" and not self.verbose:
            return
        ts = _dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        extra = " ".join(f"{key}={value}" for key, value in fields.items())
        line = f"[{ts}] [{client_id}] {message}"
        if extra:
            line += f"  {extra}"
        self.history.append(line)
        print(line)
