"""Canonical state-transition invalidation matrix (DESIGN-077)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class InvalidationEvent(StrEnum):
    OBJECTIVE_CHANGED = "OBJECTIVE_CHANGED"
    LOADING = "LOADING"
    TELEPORT = "TELEPORT"
    MAP_CONTEXT = "MAP_CONTEXT"
    DEATH = "DEATH"
    PHASE = "PHASE"
    FLOOR = "FLOOR"
    VEHICLE = "VEHICLE"
    CINEMATIC = "CINEMATIC"


@dataclass(frozen=True)
class InvalidationDecision:
    event: InvalidationEvent
    cancel_active: bool
    reset_navigation: bool
    clear_visual_context: bool
    reset_camera: bool
    reset_commitment: bool
    reset_map_search: bool
    invalidate_objective: bool


class StateInvalidationPolicy:
    """Detect context changes and invoke declared input-free reset callbacks."""

    _CONTEXT_RESET = dict(
        cancel_active=True, reset_navigation=True,
        clear_visual_context=True, reset_camera=True,
        reset_commitment=True, reset_map_search=True,
        invalidate_objective=False)
    # After a cinematic ends, the spec (V4-067) requires a full refresh of
    # both the local WorldModel context *and* quest state -- so this reuses
    # the standard context reset but also forces objective re-evaluation,
    # unlike a plain LOADING/TELEPORT reset.
    _CINEMATIC_RESET = dict(_CONTEXT_RESET, invalidate_objective=True)
    _MATRIX = {
        InvalidationEvent.OBJECTIVE_CHANGED: dict(
            cancel_active=False, reset_navigation=False,
            clear_visual_context=False, reset_camera=False,
            reset_commitment=True, reset_map_search=True,
            invalidate_objective=True),
        InvalidationEvent.LOADING: _CONTEXT_RESET,
        InvalidationEvent.TELEPORT: _CONTEXT_RESET,
        InvalidationEvent.MAP_CONTEXT: _CONTEXT_RESET,
        InvalidationEvent.DEATH: _CONTEXT_RESET,
        InvalidationEvent.PHASE: _CONTEXT_RESET,
        InvalidationEvent.FLOOR: _CONTEXT_RESET,
        InvalidationEvent.VEHICLE: _CONTEXT_RESET,
        InvalidationEvent.CINEMATIC: _CINEMATIC_RESET,
    }
    _VISUAL_PROJECTIONS = frozenset({
        "WORLD3D", "WORLD3D_LOCAL_VIEW", "MINIMAP_CV", "WORLD_MAP_CV",
    })

    @staticmethod
    def context(state: dict) -> dict:
        quests = state.get("active_quests") or []
        objectives = tuple(sorted(
            (str(quest.get("quest_id")), str(objective.get("objective_id")),
             objective.get("current_count"), objective.get("required_count"),
             objective.get("is_complete"))
            for quest in quests for objective in (quest.get("objectives") or [])))
        position = state.get("player_world_position") or {}
        map_position = state.get("position") or {}
        return {
            "objective_signature": objectives,
            "loading": bool(state.get("loading")),
            "map_id": state.get("map_id"),
            "position": (position.get("x"), position.get("y"), position.get("z")),
            "map_position": (map_position.get("x"), map_position.get("y")),
            "dead": bool(state.get("is_dead")),
            "phase": state.get("phase_id", state.get("phase")),
            "floor": state.get("floor_id", state.get("map_floor")),
            "vehicle": (state.get("vehicle_id"), bool(
                state.get("in_vehicle") or state.get("vehicle_ui")
                or state.get("vehicle_camera"))),
            "cinematic": bool(state.get("cinematic_playing")),
        }

    def detect(self, previous: dict | None, current: dict) -> tuple[InvalidationEvent, ...]:
        if previous is None:
            return ()
        events: list[InvalidationEvent] = []
        if (previous["objective_signature"] != current["objective_signature"]
                and (previous["objective_signature"]
                     or current["objective_signature"])):
            events.append(InvalidationEvent.OBJECTIVE_CHANGED)
        if current["loading"] and not previous["loading"]:
            events.append(InvalidationEvent.LOADING)
        # Fires on the falling edge (cinematic *ending*), not the start --
        # the spec requires the refresh to happen *after* the cinematic,
        # not a context reset the moment it begins.
        if previous["cinematic"] and not current["cinematic"]:
            events.append(InvalidationEvent.CINEMATIC)
        if current["dead"] and not previous["dead"]:
            events.append(InvalidationEvent.DEATH)
        for key, event in (("map_id", InvalidationEvent.MAP_CONTEXT),
                           ("phase", InvalidationEvent.PHASE),
                           ("floor", InvalidationEvent.FLOOR),
                           ("vehicle", InvalidationEvent.VEHICLE)):
            before, after = previous[key], current[key]
            if before is not None and after is not None and before != after:
                events.append(event)
        if (InvalidationEvent.MAP_CONTEXT not in events and not current["loading"]
                and self._teleported(previous["position"], current["position"],
                                     previous.get("map_position"),
                                     current.get("map_position"))):
            events.append(InvalidationEvent.TELEPORT)
        return tuple(dict.fromkeys(events))

    @staticmethod
    def _teleported(before, after, before_map=None, after_map=None) -> bool:
        if not before or not after or None in before[:2] or None in after[:2]:
            return False
        world_jump = math.hypot(float(after[0])-float(before[0]),
                                float(after[1])-float(before[1]))
        if world_jump < 50.:
            return False
        # Live 2026-09-23: the derived WORLD_YARDS source corrected itself by
        # 119 yd while the independently sampled normalized C_Map position was
        # bit-identical.  Treating that incoherent source correction as a real
        # teleport cancelled a healthy mmap reach.  When both representations
        # are available, a large world jump needs corroborating map movement.
        if (before_map and after_map and None not in before_map[:2]
                and None not in after_map[:2]):
            map_jump = math.hypot(float(after_map[0])-float(before_map[0]),
                                  float(after_map[1])-float(before_map[1]))
            if map_jump < 1e-5:
                return False
        return True

    def decision(self, event: InvalidationEvent) -> InvalidationDecision:
        return InvalidationDecision(event=event, **self._MATRIX[event])

    def apply(self, event: InvalidationEvent, world_model,
              runtime: dict) -> InvalidationDecision:
        decision = self.decision(event)
        if decision.clear_visual_context:
            world_model.mouseover_screen_anchors.clear()
            world_model.corpse_anchors.clear()
            for source in self._VISUAL_PROJECTIONS:
                world_model.projections.pop(source, None)
            world_model._rebuild_state()
        for enabled, name in (
                (decision.invalidate_objective, "invalidate_objective"),
                (decision.reset_navigation, "reset_navigation"),
                (decision.reset_camera, "reset_camera"),
                (decision.reset_commitment, "reset_commitment"),
                (decision.reset_map_search, "reset_map_search")):
            callback = runtime.get(name)
            if enabled and callback is not None:
                callback(event.value)
        return decision
