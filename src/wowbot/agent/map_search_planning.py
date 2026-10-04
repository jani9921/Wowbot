"""World Map scan-session and last-resort reference-location policy.

This stateful policy owns only search lifecycle and proposal construction.  It
cannot rank a global winner, dispatch input, move the player, mutate the
WorldModel, or confirm an offline TDB hypothesis as a live entity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Callable

from .models import Goal, Outcome, Proposal, number
from .world_map_absence_resolver import MapAbsenceStep, WorldMapAbsenceResolver


@dataclass(slots=True)
class MapSearchState:
    scan_started: float | None = None
    probes: int = 0
    zoom_count: int = 0
    zoom_requested: bool = False
    exhausted: bool = False
    context: tuple | None = None
    last_scan_started: float | None = None
    used_location_fallbacks: set[tuple] = field(default_factory=set)
    active_map_id: int | None = None
    parent_map_id: int | None = None
    parent_hops: int = 0
    step_out_attempts: int = 0
    inspected_map_ids: set[int] = field(default_factory=set)
    # Skill-level gate, deliberately independent of Proposal.key.  A target
    # GUID disappearing from otherwise equivalent OPEN_MAP parameters must
    # not bypass the cooldown and create OPEN_MAP -> CLOSE_MAP churn.
    reopen_blocked_until: float = 0.0
    # Live 2026-10-01: the World Map CV produced no candidate on map 2175 in
    # any scan, yet every quest-progress context reset reopened the map
    # 30 s later (~15 s lost per OPEN/WAIT/CLOSE cycle, ~7 % of FULL_AI
    # time).  Remember empty scans per map across context resets.
    scan_saw_candidates: bool = False
    empty_scans: dict = field(default_factory=dict)
    empty_until: dict = field(default_factory=dict)


EMPTY_MAP_SCANS_BEFORE_BACKOFF = 2
EMPTY_MAP_BACKOFF_SECONDS = 600.


class WorldMapFallbackPolicy:
    """Bounded World3D -> World Map -> TDB-reference search lifecycle."""

    def __init__(self) -> None:
        self.state = MapSearchState()
        self.absence_resolver = WorldMapAbsenceResolver(max_parent_hops=2)

    def reset_session(self) -> None:
        self.state = MapSearchState()

    def status(self) -> dict[str, object]:
        state = self.state
        return {
            "zoom_supported": True,
            "zoom_count": state.zoom_count,
            "zoom_limit": 5,
            "zoom_requested": state.zoom_requested,
            "map_probes": state.probes,
            "map_scan_started": state.scan_started,
            "search_stage": ("DB_FALLBACK" if state.exhausted else
                             "WORLD_MAP" if state.scan_started is not None else "WORLD3D"),
            "map_search_exhausted": state.exhausted,
            "active_map_id": state.active_map_id,
            "parent_map_id": state.parent_map_id,
            "parent_hops": state.parent_hops,
            "map_filter_state": "UNKNOWN",
            "map_reopen_blocked_until": state.reopen_blocked_until,
            "empty_map_scans": dict(state.empty_scans),
            "empty_map_backoff_until": dict(state.empty_until),
        }

    def _refresh_context(self, world, quest) -> None:
        state = self.state
        context = (world.session_id, world.state.get("map_id"),
                   world.state.get("quest_state_revision"))
        if context == state.context:
            return
        state.context = context
        state.exhausted = False
        state.last_scan_started = None
        state.active_map_id = None
        state.parent_map_id = None
        state.parent_hops = 0
        state.step_out_attempts = 0
        state.inspected_map_ids.clear()
        quest.allow_db_fallback = False

    def _refresh_map_level(self, world, now: float) -> None:
        """Track addon-reported map hierarchy without inferring a level.

        A changed displayed map is evidence that the previous UI action moved
        to another level.  It is not evidence that a marker exists there.
        """
        state = self.state
        context = world.state.get("map_context") or {}
        active = number(context.get("active_map_id"))
        parent = number(context.get("parent_map_id"))
        # Retail uses 0 as the C_Map sentinel for "no known parent".  It is
        # not a real UiMapID and must never become a MAP_STEP_OUT target.
        # Likewise, a self-parent is malformed hierarchy evidence rather than
        # permission to right-click the map indefinitely.
        if active is None or int(active) <= 0:
            return
        active = int(active)
        parent_id = int(parent) if parent is not None and int(parent) > 0 else None
        if parent_id == active:
            parent_id = None
        if state.active_map_id is not None and active != state.active_map_id:
            if state.parent_map_id is not None and active == state.parent_map_id:
                state.parent_hops += 1
            state.scan_started = now
            state.last_scan_started = now
            state.probes = 0
            state.zoom_count = 0
            state.zoom_requested = False
            state.step_out_attempts = 0
        state.active_map_id = active
        state.parent_map_id = parent_id

    def _has_current_map_location(self, world) -> bool:
        state = self.state
        current_map = state.active_map_id or world.state.get("map_id")
        if state.last_scan_started is None:
            return False
        for location in world.state.get("remembered_locations", []):
            provenance = location.get("provenance") or {}
            observed = number(provenance.get("observed_monotonic"))
            x, y = number(location.get("x")), number(location.get("y"))
            # A cursor/tooltip observation on the outer screen/map edge is a
            # UI/quest-tracker hit, not evidence for a navigable map marker.
            # Live 2026-09-26: x=1.0 on the objective tracker incorrectly kept
            # the World Map search non-exhausted and caused a second full scan.
            inside_map_content = (x is not None and y is not None
                                  and .015 < x < .985 and .015 < y < .985)
            if (observed is not None and observed >= state.last_scan_started
                    and provenance.get("session_id") == world.session_id
                    and provenance.get("marker_associated") is True
                    and inside_map_content
                    and location.get("map_id") == current_map
                    and location.get("semantic_type") in {
                        "QUEST_GIVER", "QUEST_TURN_IN", "QUEST_RELATED"}):
                return True
        return False

    def pre_domain_proposals(
        self, goal: Goal, world, now: float, *, registry, quest,
        inspections: Callable,
    ) -> list[Proposal] | None:
        """Return an exclusive map/safety proposal list, or None to continue."""
        state = self.state
        self._refresh_context(world, quest)
        world_state = world.state
        self._refresh_map_level(world, now)
        evidence = (world.latest.observation_id,) if world.latest else ()
        map_key = world_state.get("map_id")
        if (not world_state.get("world_map_open") and not state.exhausted
                and now < float(state.empty_until.get(map_key, 0.))):
            # This map's CV has been empty: count the map step as done so the
            # documented order continues (World3D -> map -> DB) without
            # reopening a map that shows nothing.
            state.exhausted = True
            quest.allow_db_fallback = True
        if not world_state.get("world_map_open"):
            state.zoom_count = 0
            state.zoom_requested = False
        if world_state.get("is_dead") or world_state.get("is_ghost"):
            return [Proposal.make(
                "WAIT", "Halál/visszatérés: további recovery telemetria szükséges",
                evidence=evidence)]
        if world_state.get("world_map_open"):
            selected_guid = str((world.query.target() or {}).get("guid") or "")
            commitment = world.runtime_context.get("commitment") or {}
            if (goal.domain == "QUEST" and selected_guid
                    and selected_guid in quest.interaction_range_blocks
                    and commitment.get("kind") == "TARGET"
                    and str(commitment.get("target_guid") or "") == selected_guid):
                state.reopen_blocked_until = max(state.reopen_blocked_until, now + 30.)
                close = Proposal.make(
                    "CLOSE_MAP", "A commitolt 3D target megközelítése előtt a World Map bezárása",
                    {"guid": selected_guid, "purpose": "RESTORE_WORLD3D_FOR_APPROACH"},
                    priority=120, evidence=evidence)
                return [close if registry.available(close, world) else Proposal.make(
                    "WAIT", "A commitolt targethez visszatéréshez hiányzik a TOGGLEWORLDMAP binding",
                    evidence=evidence)]
            if state.scan_started is None:
                state.scan_started, state.probes = now, 0
                state.last_scan_started = now
                state.scan_saw_candidates = False
            if any(item.get("source") == "WORLD_MAP_CV"
                   for item in world_state.get("visual_candidates") or ()):
                state.scan_saw_candidates = True
            elapsed = now - state.scan_started
            if (goal.domain == "QUEST" and not world_state.get("is_in_combat")
                    and (state.zoom_requested or elapsed < 10 + 4 * state.zoom_count)
                    and state.probes < 4 + state.zoom_count):
                probes = inspections(world, now, "WORLD_MAP_CV", goal)
                if probes:
                    return probes
                if elapsed < 2:
                    return [Proposal.make(
                        "WAIT", "Várakozás a frissen megnyitott térkép képi jelöltjeire",
                        evidence=evidence)]
            location_found = self._has_current_map_location(world)
            if state.active_map_id is not None:
                state.inspected_map_ids.add(state.active_map_id)
            map_context = world_state.get("map_context") or {}
            parent_name = (str(map_context.get("parent_map_name") or "").strip()
                           or (f"map:{state.parent_map_id}"
                               if state.parent_map_id is not None else None))
            tracked = bool(world_state.get("active_quests"))
            directive = self.absence_resolver.next_step(
                tracked_quest_confirmed=tracked,
                marker_found_at_current_level=location_found,
                parent_hops_taken=state.parent_hops,
                marker_found_at_parent_level=(
                    False if state.parent_hops > 0 and not location_found else None),
                parent_zone=parent_name,
            )
            if (directive.step is MapAbsenceStep.STEP_OUT_TO_PARENT
                    and state.parent_map_id is not None
                    and state.step_out_attempts < 2
                    and not world_state.get("is_in_combat")):
                return [Proposal.make(
                    "INSPECT", "A marker hiányzik ezen a térképszinten; kilépés a Retail által jelentett szülőtérképre",
                    {"source": "WORLD_MAP_CONTEXT", "map_step_out": True,
                     "x": .5, "y": .5,
                     "from_map_id": state.active_map_id,
                     "expected_parent_map_id": state.parent_map_id,
                     "expected_parent_map_name": parent_name,
                     "absence_semantics": "UNKNOWN"},
                    priority=112, evidence=evidence)]
            state.exhausted = not location_found
            quest.allow_db_fallback = state.exhausted
            if location_found or state.scan_saw_candidates:
                state.empty_scans.pop(map_key, None)
            else:
                state.empty_scans[map_key] = state.empty_scans.get(map_key, 0) + 1
                if state.empty_scans[map_key] >= EMPTY_MAP_SCANS_BEFORE_BACKOFF:
                    state.empty_until[map_key] = now + EMPTY_MAP_BACKOFF_SECONDS
            close = Proposal.make(
                "CLOSE_MAP", "Térképvizsgálat befejezve vagy keret lejárt; vissza a 3D nézethez",
                priority=110, evidence=evidence)
            state.reopen_blocked_until = max(state.reopen_blocked_until, now + 30.)
            return [close if registry.available(close, world) else Proposal.make(
                "WAIT", "A térkép nyitva, de hiányzik a TOGGLEWORLDMAP binding",
                evidence=evidence)]
        # If a map that we were actively scanning disappears before this
        # policy produced a resolved location, treat that scan as terminated.
        # This includes an explicit user close and an unexpected UI close.
        # Leaving ``exhausted`` false here caused the next planner tick to
        # reopen the same map and repeat the same failed scan forever.
        if state.scan_started is not None:
            state.exhausted = True
            quest.allow_db_fallback = True
            state.last_scan_started = state.last_scan_started or state.scan_started
            state.reopen_blocked_until = max(state.reopen_blocked_until, now + 30.)
        state.scan_started, state.probes = None, 0
        if world_state.get("is_casting"):
            return [Proposal.make(
                "WAIT", "Folyamatban lévő varázslat; nem szakítjuk meg mozgással",
                evidence=evidence)]
        return None

    def add_quest_fallbacks(self, proposals: list[Proposal], goal: Goal,
                            world, now: float, *, blocked_until: dict[str, float]) -> None:
        """Append map/TDB proposals after live quest proposals are exhausted."""
        state = self.state
        world_state = world.state
        ui_open = ((world_state.get("quest_ui") or {}).get("open")
                   or world_state.get("quest_ui_open"))
        has_location = any(
            proposal.skill in {"MOVE", "REACH_LOCATION"}
            and blocked_until.get(proposal.key, 0) <= now
            for proposal in proposals)
        has_local_action = any(
            proposal.skill in {"TARGET", "INTERACT", "TALK", "QUEST_DIALOG", "FIELD_TURN_IN",
                               "EXTRA_ACTION", "OBJECT_USE", "SEEK_VISUAL_CUE",
                               "VISUAL_APPROACH", "REACQUIRE_TARGET"}
            and blocked_until.get(proposal.key, 0) <= now
            for proposal in proposals)
        if (world_state.get("world_map_open") is not False or ui_open or has_location
                or has_local_action or world_state.get("is_in_combat")):
            return
        selected_target = world.query.target()
        if (selected_target.get("guid")
                and selected_target.get("attackable", selected_target.get("is_attackable")) is True
                and not selected_target.get("dead", selected_target.get("is_dead"))):
            # Resolve/clear the current live identity before leaving World3D.
            # Opening a map cannot make a selected target's missing combat or
            # interaction capability become available.
            return
        evidence = (world.latest.observation_id,) if world.latest else ()
        if not state.exhausted:
            commitment = world.runtime_context.get("commitment") or {}
            committed_guid = (commitment.get("target_guid")
                              if commitment.get("kind") == "TARGET" else None)
            # A recent addon-confirmed 3D anchor for the exact committed GUID
            # is stronger local evidence than an unscoped World Map search.
            # Let VISUAL_APPROACH/reacquisition consume it; do not obscure the
            # scene and immediately close the map again.  This is bounded by
            # anchor age and does not infer identity from CV.
            anchor = ((world_state.get("confirmed_mouseover_anchors") or {}).get(
                str(committed_guid)) if committed_guid else None)
            state_time = number(world_state.get("monotonic_time")) or now
            anchor_time = number((anchor or {}).get("sample_time"))
            anchor_recent = (anchor_time is not None
                             and 0 <= state_time-anchor_time < 30.)
            if committed_guid and anchor_recent:
                return
            if now < state.reopen_blocked_until:
                return
            proposals.append(Proposal.make(
                "OPEN_MAP", "Nincs ismert questhely: térképi marker és tooltip keresése",
                {"map_id": world_state.get("map_id"), "session_id": world.session_id,
                 **({"guid": committed_guid, "purpose": "LOCATE_COMMITTED_TARGET"}
                    if committed_guid else {})},
                priority=60, evidence=evidence))
            return
        if world_state.get("target") or world_state.get("active_quests"):
            return
        references = sorted(
            world_state.get("quest_role_reference_candidates", []),
            key=lambda row: number(row.get("distance_yards")) or math.inf)
        reference = next((row for row in references
                          if row.get("role_hypothesis") == "QUEST_STARTER"
                          and (world.session_id, tuple(sorted(row.get("spawn_ids", []))))
                              not in state.used_location_fallbacks), None)
        if reference is None:
            return
        fallback_key = (world.session_id, tuple(sorted(reference["spawn_ids"])))
        proposals.append(Proposal.make(
            "REACH_LOCATION",
            "World3D és World Map nem adott célt: TDB questgiver-helyhipotézis felkeresése, helyszíni újraazonosítással",
            {**reference, "fallback_key": fallback_key,
             "purpose": "INSPECT_REFERENCE_LOCATION", "stop_distance": 6.0},
            confidence=.6, priority=40))

    def on_terminal(self, attempt, outcome: Outcome, reason: str, quest) -> None:
        """Apply map/reference lifecycle effects after canonical verification.

        This method does not decide success; it receives the already verified
        terminal outcome from AutonomousAgent's one finalization path.
        """
        proposal = attempt.proposal
        params = proposal.parameters
        if (proposal.skill == "INSPECT"
                and params.get("source") == "WORLD_MAP_CV"):
            self.state.zoom_requested = (
                not params.get("map_zoom_in")
                and outcome == Outcome.FAILURE
                and reason == "expected_observation_missing"
                and self.state.zoom_count < 5)
        if proposal.skill == "INSPECT" and params.get("map_step_out"):
            if outcome == Outcome.SUCCESS:
                self.state.step_out_attempts = 0
        if params.get("source") != "TDB_REFERENCE":
            return
        fallback_key = params.get("fallback_key")
        if proposal.skill == "REACH_LOCATION":
            self.state.used_location_fallbacks.add(
                (fallback_key[0], tuple(sorted(fallback_key[1])))
                if fallback_key else ())
        elif fallback_key:
            quest.used_spawn_fallbacks.add(tuple(fallback_key))
        if outcome == Outcome.SUCCESS and proposal.skill == "REACH_OBJECT":
            # Arrival proves only a reference location was reached. Permit one
            # new live interaction verification; it does not confirm identity.
            guid = params.get("guid")
            quest.interaction_range_blocks.pop(guid, None)
            quest.reference_arrivals.add(guid)
