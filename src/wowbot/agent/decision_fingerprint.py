"""Evidence-gated Planner anti-loop state with no execution authority."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

from .models import Goal, Proposal, canonical


@dataclass(frozen=True, slots=True)
class DecisionFingerprint:
    """Stable decision + target + strategy identity from the design spec."""

    decision: str
    target: str
    strategy: str
    objective: str
    goal: str

    @classmethod
    def from_proposal(cls, proposal: Proposal, goal: Goal | None) -> "DecisionFingerprint":
        params = proposal.parameters
        target = _first_identity(params, (
            "guid", "target_guid", "entity_id", "track_id", "marker_id",
            "npc_id", "object_id", "quest_id",
        ))
        objective = _first_identity(params, ("objective_id", "objective_ref"))
        strategy = _first_identity(params, (
            "strategy", "purpose", "source", "transition_kind", "capability",
            "interaction_kind",
        ))
        return cls(
            proposal.skill.upper(),
            target or "NONE",
            strategy or "DEFAULT",
            objective or "NONE",
            str(getattr(goal, "goal_id", None) or "NONE"),
        )

    @property
    def key(self) -> str:
        return canonical({
            "decision": self.decision,
            "target": self.target,
            "strategy": self.strategy,
            "objective": self.objective,
            "goal": self.goal,
        })


@dataclass(frozen=True, slots=True)
class DecisionBlock:
    fingerprint: DecisionFingerprint
    evidence_signature: str
    failure_reason: str
    blocked_at: float


class DecisionFingerprintGuard:
    """Suppress one non-retryable decision until relevant evidence changes.

    This is deliberately Planner-side filtering only.  It never starts,
    cancels, dispatches or finalizes a skill and it never treats a new frame or
    timestamp alone as new evidence.
    """

    def __init__(self, *, max_entries: int = 2048) -> None:
        self.max_entries = max(32, int(max_entries))
        self._blocks: OrderedDict[str, DecisionBlock] = OrderedDict()

    def permits(self, proposal: Proposal, goal: Goal | None,
                state: Mapping[str, Any] | None) -> bool:
        fingerprint = DecisionFingerprint.from_proposal(proposal, goal)
        block = self._blocks.get(fingerprint.key)
        if block is None:
            return True
        current = evidence_signature(state)
        if current != block.evidence_signature:
            self._blocks.pop(fingerprint.key, None)
            return True
        return False

    def record_nonretryable(self, proposal: Proposal, goal: Goal | None,
                            state: Mapping[str, Any] | None, *,
                            reason: object, now: float) -> DecisionBlock:
        fingerprint = DecisionFingerprint.from_proposal(proposal, goal)
        block = DecisionBlock(
            fingerprint,
            evidence_signature(state),
            str(getattr(reason, "value", reason)),
            float(now),
        )
        self._blocks[fingerprint.key] = block
        self._blocks.move_to_end(fingerprint.key)
        while len(self._blocks) > self.max_entries:
            self._blocks.popitem(last=False)
        return block

    def clear(self, proposal: Proposal, goal: Goal | None) -> None:
        self._blocks.pop(DecisionFingerprint.from_proposal(proposal, goal).key, None)

    def reset(self) -> None:
        self._blocks.clear()

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple({
            "decision": value.fingerprint.decision,
            "target": value.fingerprint.target,
            "strategy": value.fingerprint.strategy,
            "objective": value.fingerprint.objective,
            "goal": value.fingerprint.goal,
            "evidence_signature": value.evidence_signature,
            "failure_reason": value.failure_reason,
            "blocked_at": value.blocked_at,
        } for value in self._blocks.values())


def evidence_signature(state: Mapping[str, Any] | None) -> str:
    """Hash relevant semantic evidence while excluding frame/time churn."""
    value = state or {}
    player_position = value.get("player_world_position") or value.get("position") or {}
    projection = {
        "session": value.get("session_id") or value.get("character_guid"),
        "map": value.get("map_id"),
        "instance": value.get("instance_id"),
        "phase": value.get("phase"),
        "quest_revision": value.get("quest_state_revision"),
        "position": _point(player_position),
        "target": _unit(value.get("target")),
        "mouseover": _unit(value.get("mouseover")),
        "quests": _quests(value.get("active_quests")),
        "ui": {
            key: bool((value.get(key) or {}).get("open") or value.get(f"{key}_open"))
            for key in ("quest_ui", "gossip_ui", "vendor_ui", "loot_ui")
        },
        "combat": bool(value.get("is_in_combat")),
        "loading": bool(value.get("loading")),
        "world_map_open": bool(value.get("world_map_open")),
    }
    encoded = json.dumps(projection, sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def _first_identity(params: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = params.get(key)
        if value not in (None, ""):
            return f"{key}={value}"
    if all(isinstance(params.get(key), (int, float)) for key in ("x", "y")):
        return f"xy={round(float(params['x']), 3)},{round(float(params['y']), 3)}"
    return None


def _point(value: Any) -> tuple[float, ...] | None:
    if not isinstance(value, Mapping):
        return None
    result = []
    for key in ("x", "y", "z"):
        number = value.get(key)
        if isinstance(number, (int, float)) and math.isfinite(float(number)):
            result.append(round(float(number), 2))
    return tuple(result) or None


def _unit(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or not value:
        return None
    return {
        key: value.get(key)
        for key in ("guid", "npc_id", "name", "is_dead", "is_attackable",
                    "in_range", "health", "max_health", "quest_role")
        if value.get(key) is not None
    }


def _quests(value: Any) -> tuple[tuple[Any, ...], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result = []
    for quest in value:
        if not isinstance(quest, Mapping):
            continue
        objectives = quest.get("objectives") or ()
        objective_state = tuple(
            (item.get("objective_id") or item.get("id"), item.get("current"),
             item.get("required"), item.get("finished"))
            for item in objectives if isinstance(item, Mapping)
        )
        result.append((quest.get("quest_id") or quest.get("id"),
                       quest.get("state"), quest.get("completed"), objective_state))
    return tuple(result)

