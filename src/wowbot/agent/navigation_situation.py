"""Input-free navigation-context and transition planning policy.

The classifiers in :mod:`wowbot.navigation` deliberately own no control
authority.  This adapter is the production consumer which turns their typed
assessments into one of three planner-level outcomes: continue the selected
navigation intent, run one bounded entrance/transition search, or re-localize
after that search was exhausted.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from wowbot.navigation import NavigationContext, TransitionKind

from .models import Proposal, number


class NavigationSituationPolicy:
    """Interpret context without moving, clicking, or owning retry state."""

    _MOVEMENT = frozenset({"MOVE", "FOLLOW", "REACH_LOCATION", "REACH_OBJECT"})
    _SIGNALS = frozenset({
        "repeated_local_route_blockage", "map_distance_low", "target_visible_3d",
        "local_map_context_differs", "floor_interior_map_appears",
        "cave_entrance_cue", "target_above_or_below", "portal_cue",
        "transport_cue", "entrance_icon_cue",
    })

    def adapt(self, proposal: Proposal, *, world, navigation,
              last_result: Mapping[str, Any] | None = None,
              map_relocalization_exhausted: bool = False) -> Proposal:
        if proposal.skill not in self._MOVEMENT:
            return proposal
        if not (callable(getattr(navigation, "current_navigation_context", None))
                and callable(getattr(navigation, "resolve_transition", None))):
            # Compatibility for deliberately minimal navigation test doubles.
            # The production adapter is always constructed with the canonical
            # NavigationService, where both methods are mandatory.
            return proposal

        state = world.state
        context = navigation.current_navigation_context(state)
        contextual = self._with_context(proposal, context)

        # Loading/map transfer is an observed transition, not a movement
        # failure.  Holding here also prevents a stale pre-transition route
        # from issuing another forward lease.
        if context.context is NavigationContext.TRANSITION:
            return Proposal.make(
                "WAIT", "Aktív map/loading átmenet: friss lokalizációra vár",
                {"navigation_context": context.context.value,
                 "context_evidence": list(context.evidence),
                 "replan_scope": "MAP_CONTEXT"},
                confidence=context.confidence, priority=max(100., proposal.priority),
                evidence=proposal.evidence + context.evidence)

        signals = self._transition_signals(
            contextual, state, world, context.context, last_result or {})
        quest_region_arrival_without_transition_evidence = (
            contextual.parameters.get("purpose") in {
                "LOCATE_QUEST_OBJECTIVE_REGION", "LOCATE_TURN_IN_REGION",
                "LOCATE_API_QUEST_GIVER"}
            and contextual.parameters.get("transition_required") is not True
            and not signals.get("repeated_local_route_blockage")
            and not any(signals.get(key) for key in {
                "local_map_context_differs", "floor_interior_map_appears",
                "cave_entrance_cue", "target_above_or_below", "portal_cue",
                "transport_cue", "entrance_icon_cue"}))
        if quest_region_arrival_without_transition_evidence:
            # A quest objective/turn-in POI becoming close while no unit is
            # selected means "search this local area", not "there must be an
            # entrance".  The generic heuristic previously converted both
            # objective arrival and Austin Huxworth turn-in arrival into
            # SEARCH_ENTRANCE -> OPEN_MAP loops without transition evidence.
            return contextual
        transition = navigation.resolve_transition(signals)
        if not transition.supported:
            return contextual

        # A bounded transition search already failed.  Do not repeat the same
        # camera path: hand control back to the existing map/localisation FSM.
        if self._transition_search_exhausted(last_result or {}):
            if map_relocalization_exhausted:
                return Proposal.make(
                    "WAIT", "A map-relokalizálás ebben a quest/map állapotban már kimerült; új bizonyítékra vár",
                    {"purpose": "RELOCALIZE_TRANSITION",
                     "transition_kind": transition.kind.value,
                     "navigation_context": context.context.value,
                     "replan_scope": "MAP_OR_QUEST_EVIDENCE",
                     "waiting_for": ["QUEST_STATE_CHANGED", "MAP_CONTEXT_CHANGED",
                                     "TARGET_IDENTITY_CHANGED"]},
                    confidence=max(.6, transition.confidence),
                    priority=max(96., proposal.priority),
                    evidence=proposal.evidence + transition.evidence)
            if state.get("world_map_open") is not True:
                return Proposal.make(
                    "OPEN_MAP", "Átjárókeresés kimerült: map-context relokalizálás",
                    {"purpose": "RELOCALIZE_TRANSITION",
                     "transition_kind": transition.kind.value,
                     "navigation_context": context.context.value},
                    confidence=max(.6, transition.confidence),
                    priority=max(96., proposal.priority),
                    evidence=proposal.evidence + transition.evidence)
            return Proposal.make(
                "WAIT", "Átjárókeresés kimerült; a nyitott map friss bizonyítékára vár",
                {"purpose": "RELOCALIZE_TRANSITION",
                 "transition_kind": transition.kind.value,
                 "navigation_context": context.context.value,
                 "replan_scope": "MAP_CONTEXT"},
                confidence=max(.6, transition.confidence),
                priority=max(95., proposal.priority),
                evidence=proposal.evidence + transition.evidence)

        query = {
            TransitionKind.ENTER_BUILDING: "entrance or doorway",
            TransitionKind.FIND_CAVE_ENTRANCE: "cave entrance",
            TransitionKind.CHANGE_FLOOR: "stairs ramp lift or floor transition",
            TransitionKind.USE_PORTAL: "portal",
            TransitionKind.USE_TRANSPORT: "transport",
            TransitionKind.UNKNOWN_TRANSITION: "entrance or local transition",
        }[transition.kind]
        return Proposal.make(
            "SEEK_VISUAL_CUE", "Támogatott útvonal-átmenet: korlátos helyi átjárókeresés",
            {"purpose": "SEARCH_ENTRANCE", "search_capability": "SEARCH_ENTRANCE",
             "query": query, "transition_kind": transition.kind.value,
             "navigation_context": context.context.value,
             "resume_navigation": contextual.parameters,
             "scan_budget": 6, "time_budget": 22.0},
            confidence=max(.55, transition.confidence),
            priority=max(97., proposal.priority),
            evidence=proposal.evidence + transition.evidence)

    @staticmethod
    def _with_context(proposal: Proposal, assessment) -> Proposal:
        route_expectation = {
            NavigationContext.OUTDOOR: "OPEN_TERRAIN_OR_CORRIDOR",
            NavigationContext.INDOOR: "TOPOLOGY_CONSTRAINED",
            NavigationContext.CAVE: "ENTRANCE_AND_TOPOLOGY_CONSTRAINED",
            NavigationContext.MULTI_FLOOR: "FLOOR_TRANSITION_REQUIRED",
            NavigationContext.TRANSITION: "MAP_CONTEXT_CHANGING",
            NavigationContext.VEHICLE: "VEHICLE_CONSTRAINED",
            NavigationContext.UNKNOWN: "EVIDENCE_LIMITED",
        }[assessment.context]
        params = {
            **proposal.parameters,
            "navigation_context": assessment.context.value,
            "navigation_context_confidence": assessment.confidence,
            "navigation_context_evidence": list(assessment.evidence),
            "route_expectation": route_expectation,
        }
        return Proposal.make(
            proposal.skill, proposal.reason, params, proposal.confidence,
            proposal.priority, proposal.evidence + assessment.evidence)

    def _transition_signals(self, proposal: Proposal, state: Mapping[str, Any],
                            world, context: NavigationContext,
                            last_result: Mapping[str, Any]) -> dict[str, Any]:
        nested = state.get("navigation_transition_signals")
        nested = nested if isinstance(nested, Mapping) else {}
        signals = {key: state.get(key, nested.get(key)) for key in self._SIGNALS}

        last_failed_movement = (
            str(last_result.get("outcome")) == "FAILURE"
            and last_result.get("skill") in self._MOVEMENT
            and str(last_result.get("reason") or "") in {
                "supported_stuck", "required_navmesh_route_unavailable",
                "path_blocked", "movement_safety_deadline",
            })
        signals["repeated_local_route_blockage"] = bool(
            signals.get("repeated_local_route_blockage") or last_failed_movement)

        if signals.get("map_distance_low") is None:
            params = proposal.parameters
            quest_location = bool(
                params.get("quest_id") is not None
                or params.get("objective_id") is not None
                or params.get("transition_required") is True
                or params.get("purpose") in {
                    "LOCATE_TURN_IN_REGION", "SEARCH_LOCAL_OBJECTIVE_AREA",
                    "SEARCH_TURN_IN_AREA"})
            signals["map_distance_low"] = (
                quest_location and self._map_distance_low(params, state, world))
        if signals.get("target_visible_3d") is None:
            target = state.get("target") or {}
            mouseover = state.get("mouseover") or {}
            signals["target_visible_3d"] = bool(
                target.get("guid") or mouseover.get("guid")
                or state.get("goal_relevant_world3d_track"))

        signals["floor_interior_map_appears"] = bool(
            signals.get("floor_interior_map_appears")
            or context is NavigationContext.MULTI_FLOOR)
        signals["cave_entrance_cue"] = bool(
            signals.get("cave_entrance_cue")
            or context is NavigationContext.CAVE
            and state.get("cave_entrance_detected"))
        return signals

    @staticmethod
    def _map_distance_low(destination: Mapping[str, Any], state: Mapping[str, Any],
                          world) -> bool:
        if destination.get("coordinate_space") == "WORLD_YARDS":
            player = state.get("player_world_position") or {}
            if (player.get("instance_id") != destination.get("instance_id")
                    or number(player.get("x")) is None or number(player.get("y")) is None
                    or number(destination.get("x")) is None
                    or number(destination.get("y")) is None):
                return False
            stop_distance = number(destination.get("stop_distance"))
            threshold = max(1.0, stop_distance if stop_distance is not None else 6.0)
            return math.hypot(
                float(destination["x"])-float(player["x"]),
                float(destination["y"])-float(player["y"])) <= threshold
        distance_fn = getattr(world, "distance", None)
        if not callable(distance_fn):
            return False
        distance = distance_fn(dict(destination))
        threshold = number(destination.get("stop_distance"))
        return distance is not None and distance <= (
            max(.001, threshold) if threshold is not None else .003)

    @staticmethod
    def _transition_search_exhausted(last_result: Mapping[str, Any]) -> bool:
        return (
            last_result.get("skill") == "SEEK_VISUAL_CUE"
            and last_result.get("purpose") == "SEARCH_ENTRANCE"
            and str(last_result.get("outcome")) == "FAILURE")
