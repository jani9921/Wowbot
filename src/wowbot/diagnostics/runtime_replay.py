"""Opt-in bridge from canonical runtime diagnostics to typed replay JSONL."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .replay import ReplayRecorder


class RuntimeReplayBridge:
    """Observe runtime boundaries without owning planning, skills or input."""

    def __init__(self, path: str | Path) -> None:
        self.recorder = ReplayRecorder(path)
        self._unsubscribe = None
        self._last_world_revision = -1

    def start(self, *, agent, metadata: Mapping[str, Any]) -> None:
        self.recorder.start_session(metadata=metadata)
        self._unsubscribe = agent.structured_logger.subscribe(self._on_log)

    def record_observation(self, observation: Any) -> None:
        self.recorder.record_observation(observation,
            correlation_id=str(getattr(observation, "correlation_id", "") or "") or None)

    def record_world_delta(self, world) -> None:
        revision = int(getattr(world, "revision", 0))
        if revision == self._last_world_revision:
            return
        self._last_world_revision = revision
        latest = getattr(world, "latest", None)
        self.recorder.record_world_delta({
            "revision": revision,
            "observation_id": getattr(latest, "observation_id", None),
            "section_updates": dict(getattr(world, "section_updates", {}) or {}),
        }, correlation_id=getattr(latest, "correlation_id", None))

    def checkpoint(self, state: Any = None) -> None:
        self.recorder.checkpoint(state)

    def close(self, *, metadata: Mapping[str, Any] | None = None) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self.recorder.close(metadata=metadata)

    def _on_log(self, entry) -> None:
        payload = dict(entry.payload)
        correlation_id = entry.correlation_id
        self.recorder.record_event({
            "event_type": entry.event_type,
            "level": entry.level.value,
            "module": entry.module,
            "entity_id": entry.entity_id,
            "payload": payload,
        }, correlation_id=correlation_id)
        if entry.event_type in {"ACTION_INTENT", "ACTION_EXECUTED"}:
            for command in payload.get("commands") or ():
                self.recorder.record_command(command, correlation_id=correlation_id)
        if entry.event_type == "VERIFICATION":
            self.recorder.record_verification(payload, correlation_id=correlation_id)
        if ("SKILL" in entry.event_type
                or entry.event_type in {"ACTION_INTENT", "ACTION_CANCELLED", "ACTION_EXECUTED"}):
            self.recorder.record_skill_transition(
                str(payload.get("skill") or "UNKNOWN"),
                payload.get("previous_status"),
                payload.get("status") or payload.get("outcome") or entry.event_type,
                reason=payload.get("reason"), correlation_id=correlation_id)
