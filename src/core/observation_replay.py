from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from pathlib import Path
import time
from typing import Any, Iterable

from src.adapters.file_bridge import player_state_from_json
from src.core.client_observation import ClientObservationSnapshot
from src.core.state import PlayerState


RECORDING_SCHEMA = "aipc.normalized-observation.v1"


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.name
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class ObservationRecorder:
    """Lightweight JSONL recorder for normalized, replayable client frames."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, snapshot: ClientObservationSnapshot) -> None:
        payload = {
            "schema": RECORDING_SCHEMA,
            "trace_id": snapshot.trace_id,
            "recorded_at": time.time(),
            "normalized_state": to_jsonable(snapshot.state),
            "diagnostics": to_jsonable(snapshot.diagnostics()),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def replay_states(path: str | Path, client_id: str = "client-1") -> Iterable[PlayerState]:
    for _, _, state in replay_records(path, client_id):
        yield state


def replay_records(path: str | Path, client_id: str = "client-1") -> Iterable[tuple[str, float, PlayerState]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("schema") != RECORDING_SCHEMA:
                raise ValueError(f"unsupported observation schema at line {line_number}")
            state = payload.get("normalized_state")
            if not isinstance(state, dict):
                raise ValueError(f"missing normalized_state at line {line_number}")
            yield (
                str(payload.get("trace_id") or ""),
                float(payload.get("recorded_at", 0.0)),
                player_state_from_json(client_id, state),
            )
