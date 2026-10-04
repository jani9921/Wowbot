from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from typing import Any


def write_json_replace(
    path: Path,
    payload: Any,
    *,
    ensure_ascii: bool = False,
    attempts: int = 20,
) -> bool:
    """Best-effort atomic JSON update that tolerates short Windows file locks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    )
    # Compact, UTF-8-native encoding: these files are consumed by json.load,
    # never hand-edited, and the largest of them (agent_status.json) runs
    # 1.4MB+ with Hungarian text -- indent=2 + ensure_ascii=True (escaping
    # every accented char to \uXXXX) meaningfully inflated both size and
    # encode time for no benefit.
    temporary.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=ensure_ascii), encoding="utf-8"
    )
    try:
        for attempt in range(max(1, attempts)):
            try:
                temporary.replace(path)
                return True
            except PermissionError:
                if attempt + 1 >= attempts:
                    return False
                time.sleep(min(0.005 * (attempt + 1), 0.05))
        return False
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
