"""Typed, bounded anti-loop evidence; this module never executes recovery."""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import math
from typing import Any, Mapping


class LoopLevel(StrEnum):
    NONE = "NONE"
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"


class LoopSignatureKind(StrEnum):
    LEGACY = "LEGACY"
    ACTION = "ACTION"
    SKILL = "SKILL"
    WORLD_STATE = "WORLD_STATE"
    ROUTE_SEGMENT = "ROUTE_SEGMENT"
    TARGET_FAILURE = "TARGET_FAILURE"
    MOVEMENT_OSCILLATION = "MOVEMENT_OSCILLATION"
    INTERACTION_CLICK = "INTERACTION_CLICK"


@dataclass(frozen=True, slots=True)
class WorldStateSignature:
    """Small semantic fingerprint; volatile CV/timestamp payloads are excluded."""

    fingerprint: str

    @classmethod
    def from_state(cls, state: Mapping[str, Any] | None) -> "WorldStateSignature":
        projection = _world_projection(state or {})
        encoded = json.dumps(projection, sort_keys=True, ensure_ascii=True,
                             separators=(",", ":"), default=str)
        return cls(hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16])

    @property
    def key(self) -> str:
        return f"WORLD_STATE:{self.fingerprint}"


@dataclass(frozen=True, slots=True)
class ActionSignature:
    action: str
    subject: str
    failure: str
    world_state: WorldStateSignature

    @property
    def key(self) -> str:
        return _key(LoopSignatureKind.ACTION, self.action, self.subject,
                    self.failure, self.world_state.fingerprint)


@dataclass(frozen=True, slots=True)
class SkillSignature:
    skill: str
    subject: str

    @property
    def key(self) -> str:
        return _key(LoopSignatureKind.SKILL, self.skill, self.subject)


@dataclass(frozen=True, slots=True)
class RouteSegmentSignature:
    map_id: str
    segment: str
    failure: str

    @property
    def key(self) -> str:
        return _key(LoopSignatureKind.ROUTE_SEGMENT, self.map_id,
                    self.segment, self.failure)


@dataclass(frozen=True, slots=True)
class TargetFailureSignature:
    target: str
    operation: str
    failure: str

    @property
    def key(self) -> str:
        return _key(LoopSignatureKind.TARGET_FAILURE, self.target,
                    self.operation, self.failure)


@dataclass(frozen=True, slots=True)
class LoopDecision:
    level: str
    signature: str
    count: int
    kind: str = LoopSignatureKind.LEGACY.value
    matching_signatures: tuple[str, ...] = ()


class LoopGuard:
    """Detect equivalent retry loops without becoming an execution authority.

    The guard only records evidence and returns a decision. The Supervisor is
    responsible for interrupt/escalation and the Agent remains the sole owner
    of cancellation, input release and replanning.
    """

    _MOVEMENT = frozenset({"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION",
                           "VISUAL_APPROACH", "SEEK_VISUAL_CUE", "APPROACH_TARGET"})
    _TARGET = frozenset({"TARGET", "ACQUIRE_TARGET", "CLEAR_TARGET"})
    _INTERACTION = frozenset({"INTERACT", "TALK", "OBJECT_USE", "ACCEPT_QUEST",
                              "TURN_IN_QUEST", "SELECT_GOSSIP"})
    _DIRECTIONS = frozenset({"TURNLEFT", "TURNRIGHT", "MOVEFORWARD", "MOVEBACKWARD",
                             "STRAFELEFT", "STRAFERIGHT"})
    _OPPOSITES = frozenset({
        ("TURNLEFT", "TURNRIGHT"), ("TURNRIGHT", "TURNLEFT"),
        ("MOVEFORWARD", "MOVEBACKWARD"), ("MOVEBACKWARD", "MOVEFORWARD"),
        ("STRAFELEFT", "STRAFERIGHT"), ("STRAFERIGHT", "STRAFELEFT"),
    })

    def __init__(self, *, suspect_count: int = 3, suspect_window: float = 10.,
                 confirmed_count: int = 5, confirmed_window: float = 20.,
                 max_signatures: int = 2048) -> None:
        if not (0 < suspect_count <= confirmed_count):
            raise ValueError("loop thresholds must be positive and ordered")
        if not (0. < suspect_window <= confirmed_window):
            raise ValueError("loop windows must be positive and ordered")
        self.suspect_count, self.suspect_window = suspect_count, suspect_window
        self.confirmed_count, self.confirmed_window = confirmed_count, confirmed_window
        self.max_signatures = max(32, int(max_signatures))
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._movement_actions: deque[tuple[float, str]] = deque(maxlen=12)

    def record_failure(self, signature: str, at: float) -> LoopDecision:
        """Compatibility API for an already-canonical string signature."""
        return self._record(str(signature), at, LoopSignatureKind.LEGACY)

    def record_attempt_failure(self, attempt: Any, failure: Any, at: float,
                               current_state: Mapping[str, Any] | None = None) -> LoopDecision:
        """Record every applicable M1.11 signature for one failed attempt."""
        proposal = attempt.proposal
        skill = str(proposal.skill).upper()
        params = proposal.parameters
        failure_name = str(getattr(failure, "value", failure)).upper()
        subject = _subject(params, proposal.key)
        before = WorldStateSignature.from_state(getattr(attempt, "baseline", None))
        after = WorldStateSignature.from_state(current_state)
        signatures: list[tuple[str, LoopSignatureKind]] = []

        if before == after:
            signatures.append((ActionSignature(skill, subject, failure_name, after).key,
                               LoopSignatureKind.ACTION))
        signatures.append((SkillSignature(skill, subject).key, LoopSignatureKind.SKILL))

        if skill in self._MOVEMENT:
            signatures.append((RouteSegmentSignature(
                str(params.get("map_id") or params.get("instance_id") or "UNKNOWN"),
                _route_segment(params), failure_name).key,
                               LoopSignatureKind.ROUTE_SEGMENT))
        if skill in self._TARGET:
            signatures.append((TargetFailureSignature(subject, skill, failure_name).key,
                               LoopSignatureKind.TARGET_FAILURE))
        if skill in self._INTERACTION:
            signatures.append((_key(LoopSignatureKind.INTERACTION_CLICK,
                                    skill, subject, failure_name),
                               LoopSignatureKind.INTERACTION_CLICK))

        return _strongest([self._record(key, at, kind) for key, kind in signatures])

    def observe_action(self, binding: str | None, at: float) -> LoopDecision:
        """Observe movement choices and detect repeated A-B-A-B oscillation."""
        normalized = str(binding or "").upper()
        if normalized not in self._DIRECTIONS:
            return LoopDecision(LoopLevel.NONE.value, "", 0,
                                LoopSignatureKind.MOVEMENT_OSCILLATION.value)
        self._movement_actions.append((float(at), normalized))
        while (self._movement_actions
               and at - self._movement_actions[0][0] > self.confirmed_window):
            self._movement_actions.popleft()
        values = [value for _, value in self._movement_actions]
        if len(values) < 4:
            return LoopDecision(LoopLevel.NONE.value, "", 0,
                                LoopSignatureKind.MOVEMENT_OSCILLATION.value)
        left, right = values[-2:]
        if (left, right) not in self._OPPOSITES:
            return LoopDecision(LoopLevel.NONE.value, "", 0,
                                LoopSignatureKind.MOVEMENT_OSCILLATION.value)
        alternating = 2
        expected = right
        for index in range(len(values) - 3, -1, -1):
            if values[index] != expected:
                break
            alternating += 1
            expected = left if expected == right else right
        if alternating < 4:
            return LoopDecision(LoopLevel.NONE.value, "", 0,
                                LoopSignatureKind.MOVEMENT_OSCILLATION.value)
        signature = _key(LoopSignatureKind.MOVEMENT_OSCILLATION,
                         *sorted((left, right)))
        return self._record(signature, at, LoopSignatureKind.MOVEMENT_OSCILLATION)

    def clear(self, signature: str) -> None:
        self._events.pop(str(signature), None)

    def clear_prefix(self, prefix: str) -> None:
        for key in tuple(self._events):
            if key.startswith(prefix):
                self._events.pop(key, None)

    def clear_subject(self, skill: str, subject: str) -> None:
        tokens = (str(skill).upper(), str(subject))
        for key in tuple(self._events):
            if all(token in key for token in tokens):
                self._events.pop(key, None)

    def snapshot(self) -> dict[str, int]:
        return {key: len(value) for key, value in self._events.items()}

    def _record(self, signature: str, at: float,
                kind: LoopSignatureKind) -> LoopDecision:
        timestamp = float(at)
        values = self._events.setdefault(signature, deque())
        self._events.move_to_end(signature)
        values.append(timestamp)
        while values and timestamp - values[0] > self.confirmed_window:
            values.popleft()
        while len(self._events) > self.max_signatures:
            self._events.popitem(last=False)
        count = len(values)
        recent = sum(timestamp - value <= self.suspect_window for value in values)
        if count >= self.confirmed_count:
            level = LoopLevel.CONFIRMED
        elif recent >= self.suspect_count:
            level = LoopLevel.SUSPECTED
        else:
            level = LoopLevel.NONE
        return LoopDecision(level.value, signature, count, kind.value, (signature,))


def _strongest(decisions: list[LoopDecision]) -> LoopDecision:
    if not decisions:
        return LoopDecision(LoopLevel.NONE.value, "", 0)
    order = {LoopLevel.NONE.value: 0, LoopLevel.SUSPECTED.value: 1,
             LoopLevel.CONFIRMED.value: 2}
    best = max(decisions, key=lambda item: (order[item.level], item.count))
    matches = tuple(item.signature for item in decisions if item.level == best.level)
    return LoopDecision(best.level, best.signature, best.count, best.kind, matches)


def _key(kind: LoopSignatureKind, *parts: Any) -> str:
    return ":".join((kind.value, *(str(part).replace(":", "_") for part in parts)))


def _subject(params: Mapping[str, Any], fallback: str) -> str:
    for key in ("guid", "entity_id", "target_guid", "track_id", "marker_id",
                "objective_id", "quest_id"):
        value = params.get(key)
        if value not in (None, ""):
            return f"{key}={value}"
    return f"proposal={fallback}"


def _route_segment(params: Mapping[str, Any]) -> str:
    route_id = params.get("route_id") or params.get("corridor_id")
    segment = params.get("segment_id") or params.get("waypoint_index")
    if route_id is not None or segment is not None:
        return f"{route_id or 'route'}@{segment or 0}"
    coordinates = []
    for key in ("x", "y", "z", "target_x", "target_y", "target_z"):
        value = params.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            coordinates.append(f"{key}={round(float(value), 2)}")
    return ",".join(coordinates) or "UNKNOWN"


def _world_projection(state: Mapping[str, Any]) -> dict[str, Any]:
    player = state.get("player") if isinstance(state.get("player"), Mapping) else {}
    target = state.get("target") if isinstance(state.get("target"), Mapping) else {}
    mouseover = state.get("mouseover") if isinstance(state.get("mouseover"), Mapping) else {}
    position = state.get("position")
    if not isinstance(position, Mapping):
        position = player.get("position") if isinstance(player.get("position"), Mapping) else {}
    quests = state.get("active_quests") or state.get("quests") or ()
    quest_projection = []
    if isinstance(quests, (list, tuple)):
        for quest in quests[:24]:
            if not isinstance(quest, Mapping):
                continue
            objectives = []
            for objective in (quest.get("objectives") or ())[:24]:
                if isinstance(objective, Mapping):
                    objectives.append((objective.get("objective_id") or objective.get("id"),
                                       objective.get("current"), objective.get("required"),
                                       objective.get("complete")))
            quest_projection.append((quest.get("quest_id") or quest.get("id"),
                                     quest.get("complete"), tuple(objectives)))
    return {
        "map": state.get("map_id") or player.get("map_id"),
        "position": tuple(_rounded(position.get(key)) for key in ("x", "y", "z")),
        "target": (target.get("guid"), target.get("dead"), target.get("health"),
                   target.get("health_pct")),
        "mouseover": mouseover.get("guid"),
        "combat": bool(state.get("is_in_combat")),
        "dead": bool(state.get("is_dead") or state.get("is_ghost")),
        "loading": bool(state.get("loading")),
        "ui": (state.get("ui_panel") or state.get("primary_panel"),
               bool(state.get("quest_dialog_open")), bool(state.get("gossip_open"))),
        "quests": tuple(quest_projection),
    }


def _rounded(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2) if math.isfinite(number) else None
