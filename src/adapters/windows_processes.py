from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ClientProcess:
    pid: int
    name: str
    window_title: str
    path: str | None = None


def list_wow_processes() -> list[ClientProcess]:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-Process | Where-Object { $_.ProcessName -match 'wow|warcraft' } | "
            "Select-Object Id,ProcessName,MainWindowTitle,Path | ConvertTo-Json -Depth 2"
        ),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    data = json.loads(completed.stdout)
    rows = data if isinstance(data, list) else [data]
    return [
        ClientProcess(
            pid=int(row["Id"]),
            name=str(row.get("ProcessName") or ""),
            window_title=str(row.get("MainWindowTitle") or ""),
            path=row.get("Path"),
        )
        for row in rows
    ]


def processes_as_dicts() -> list[dict]:
    return [asdict(process) for process in list_wow_processes()]
