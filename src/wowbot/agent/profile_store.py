"""Per-user profile directory for learned memory (user 2026-10-03).

Learned knowledge (agent memory, entity/point memory, quest-relevant creature
types) used to live in ``output/agent/pid-<PID>/`` and was lost with every new
WoW process.  It now lives in ``output/agent/profiles/<user>/``; the per-PID
folder keeps only that run's status, logs, captures and datasets.  Character
data stays separable: every memory row carries the session id, which contains
the character GUID.  The first time a profile is created the newest per-PID
memory is copied in (SQLite backup API, consistent including the WAL).
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import sqlite3

MEMORY_FILES = ("agent_memory.sqlite3", "entity_memory.sqlite3", "world_point_memory.sqlite3")


def profile_name() -> str:
    raw = os.environ.get("AIPC_PROFILE") or os.environ.get("USERNAME") or os.environ.get("USER") or "default"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._") or "default"


def profile_directory(output: Path) -> Path:
    """The profile folder for a per-PID output folder (else ``output`` itself).

    Only the GUI/live layout (``.../pid-<n>``) is redirected; tools and tests
    that pass their own folder keep everything in it.
    """
    explicit = os.environ.get("AIPC_PROFILE_DIR", "").strip()
    if explicit:
        directory = Path(explicit)
    elif output.name.startswith("pid-"):
        directory = output.parent / "profiles" / profile_name()
    else:
        return output
    created = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    if created or not (directory / MEMORY_FILES[0]).exists():
        migrate_latest(output.parent, directory)
    return directory


def migrate_latest(agent_root: Path, directory: Path) -> list[str]:
    """Copy the newest per-PID memory into a new profile (never overwrites)."""
    copied = []
    candidates = sorted((path for path in agent_root.glob("pid-*") if path.is_dir()),
                        key=lambda path: (path / MEMORY_FILES[0]).stat().st_mtime
                        if (path / MEMORY_FILES[0]).exists() else 0., reverse=True)
    source = next((path for path in candidates if (path / MEMORY_FILES[0]).exists()), None)
    if source is not None:
        for name in MEMORY_FILES:
            origin, target = source / name, directory / name
            if not origin.exists() or target.exists():
                continue
            with sqlite3.connect(f"file:{origin}?mode=ro", uri=True) as reader, \
                    sqlite3.connect(target) as writer:
                reader.backup(writer)
            copied.append(name)
    legacy = agent_root / "quest_relevant_npcs.json"
    if legacy.exists() and not (directory / legacy.name).exists():
        shutil.copy2(legacy, directory / legacy.name)
        copied.append(legacy.name)
    return copied
