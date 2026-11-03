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
    UI_MAP = "UI_MAP"
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
        # Live 2026-10-31 02:09-02:12 (Fargodeep Mine entrance): the client's
        # UI map flipped between Elwynn (37) and the mine (39) every few
        # seconds while the character stood at one spot of the same world.
        # Each flip cancelled the MOVE and reset navigation (the tracked own
        # floor with it); the agent stood still for minutes.  An indoor /
        # outdoor UI-map step in one world is no world, floor or session
        # boundary: only the UI-map-derived views are refreshed.
        InvalidationEvent.UI_MAP: dict(
            cancel_active=False, reset_navigation=False,
            clear_visual_context=True, reset_camera=False,
            reset_commitment=False, reset_map_search=True,
            invalidate_objective=False),
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
        sample_time = position.get("sample_time", state.get("monotonic_time"))
        return {
            "airborne": bool((state.get("movement") or {}).get("flying")
                             or (state.get("packet_flight") or {}).get("adv_flying")),
            "position_time": sample_time if type(sample_time) in {int, float} else None,
            "objective_signature": objectives,
            "loading": bool(state.get("loading")),
            "map_id": state.get("map_id"),
            "instance": position.get("instance_id"),
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
                if event is InvalidationEvent.MAP_CONTEXT and self._same_world_ui_step(previous, current):
                    event = InvalidationEvent.UI_MAP
                events.append(event)
        if (InvalidationEvent.MAP_CONTEXT not in events and not current["loading"]
                and self._teleported(previous["position"], current["position"],
                                     previous.get("map_position"),
                                     current.get("map_position"),
                                     limit=self._jump_limit(previous, current))):
            events.append(InvalidationEvent.TELEPORT)
        return tuple(dict.fromkeys(events))

    @classmethod
    def _same_world_ui_step(cls, previous: dict, current: dict) -> bool:
        """A UI-map change inside one known world instance without a jump."""
        before, after = previous.get("instance"), current.get("instance")
        if before is None or after is None or str(before) != str(after) or current["loading"]:
            return False
        start, end = previous["position"], current["position"]
        if not start or not end or None in start[:2] or None in end[:2]:
            return False
        return not cls._teleported(start, end, limit=cls._jump_limit(previous, current))

    TELEPORT_YARDS = 50.
    # Live 2026-10-25 (Skyriding, 65-90 yd/s): one medium tick apart a glide
    # moved more than 50 yd, every such "teleport" cancelled the course MOVE
    # and reset navigation (the flight controller with it).  In the air the
    # jump must exceed what flight covers in the elapsed time.
    FLIGHT_YARDS_PER_SECOND = 100.
    FLIGHT_MARGIN_YARDS = 30.
    FLIGHT_UNKNOWN_ELAPSED = 3.

    @classmethod
    def _jump_limit(cls, previous: dict, current: dict) -> float:
        if not (previous.get("airborne") or current.get("airborne")):
            return cls.TELEPORT_YARDS
        before, after = previous.get("position_time"), current.get("position_time")
        elapsed = (after-before if before is not None and after is not None and after > before
                   else cls.FLIGHT_UNKNOWN_ELAPSED)
        return max(cls.TELEPORT_YARDS, cls.FLIGHT_YARDS_PER_SECOND*elapsed + cls.FLIGHT_MARGIN_YARDS)

    @staticmethod
    def _teleported(before, after, before_map=None, after_map=None, *, limit: float = 50.) -> bool:
        if not before or not after or None in before[:2] or None in after[:2]:
            return False
        world_jump = math.hypot(float(after[0])-float(before[0]),
                                float(after[1])-float(before[1]))
        if world_jump < limit:
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
