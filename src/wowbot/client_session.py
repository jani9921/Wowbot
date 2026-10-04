from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClientSession:
    session_id: str
    client_id: str
    character_name: str | None
    character_realm: str | None
    started_at: float
    state_path: Path
    session_dir: Path


def _slug(value: str | None) -> str:
    text = (value or "unknown").strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)
    return safe or "unknown"


def new_session(runtime_root: Path, client_id: str, character_name: str | None = None, character_realm: str | None = None) -> ClientSession:
    started_at = time.time()
    token = secrets.token_hex(6)
    session_id = f"{int(started_at)}-{token}"
    session_dir = runtime_root / f"session-{session_id}"
    session_dir.mkdir(parents=True, exist_ok=True)
    state_path = session_dir / "state.json"

    session = ClientSession(
        session_id=session_id,
        client_id=client_id,
        character_name=character_name,
        character_realm=character_realm,
        started_at=started_at,
        state_path=state_path,
        session_dir=session_dir,
    )
    write_current_session(runtime_root, session)
    return session


def write_current_session(runtime_root: Path, session: ClientSession) -> None:
    runtime_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": session.session_id,
        "client_id": session.client_id,
        "character_name": session.character_name,
        "character_realm": session.character_realm,
        "started_at": session.started_at,
        "state_path": str(session.state_path),
    }
    tmp = runtime_root / "current_session.json.tmp"
    final = runtime_root / "current_session.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(final)


def clear_stale_pointer(runtime_root: Path) -> None:
    pointer = runtime_root / "current_session.json"
    try:
        pointer.unlink()
    except FileNotFoundError:
        pass


def write_session_state(path: Path, state: dict[str, Any], session: ClientSession) -> None:
    enriched = dict(state)
    enriched["session_id"] = session.session_id
    enriched["session_started_at"] = session.started_at
    enriched["client_id"] = session.client_id
    enriched["state_fresh"] = True
    enriched["state_writer"] = "wowbot_session_bridge"
    enriched["state_written_at"] = time.time()

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

    # Keep a stable, easy-to-find current state alongside the archived session.
    current_path = session.session_dir.parent / "state.json"
    current_tmp = current_path.with_suffix(current_path.suffix + ".tmp")
    current_tmp.write_text(json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
    current_tmp.replace(current_path)
