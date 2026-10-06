"""Pure runtime projections extracted from the AutonomousAgent authority.

This module has no executor, input backend, WorldModel mutation, event-bus
publication, planner, or active-skill finalization capability.  It only turns
already-owned runtime state into snapshots and proposed events.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from wowbot.runtime import RuntimeEvent


# Detection and interruption have different costs.  A .15 learned subject is
# useful evidence while stationary, but cancelling an owned navmesh route is a
# much stronger action and therefore requires stronger temporal/visual support
# near the route endpoint.
MOVEMENT_HANDOFF_SUBJECT_CONFIDENCE = .30
MOVEMENT_HANDOFF_SUBJECT_STABLE_FRAMES = 6
MOVEMENT_HANDOFF_RADIUS_YARDS = 25.

from .models import number


def active_skill_snapshot(active_skill) -> dict[str, Any]:
    state = active_skill.state
    if state is None:
        return {"skill": None, "phase": "IDLE", "status": "IDLE"}
    return {"runtime_id": state.runtime_id, "skill": state.skill_type,
            "phase": state.phase, "status": state.status.value,
            "target_guid": state.target_ref, "objective_id": state.intent.objective_ref,
            "started_at": state.started_at, "updated_at": state.phase_started_at,
            "local_retry_count": state.local_retry_count,
            "verification_reason": (state.last_result.reason.value
                                      if state.last_result and state.last_result.reason else None)}


def combat_runtime_snapshot(active_skill) -> dict[str, Any]:
    state = active_skill.state
    if state is None or state.skill_type not in {"COMBAT", "DEFEND"}:
        return {"authority": "ActiveSkillRuntime", "phase": "IDLE", "target_guid": None}
    context = state.skill_context.get("combat") or {}
    return {"authority": "ActiveSkillRuntime", "phase": state.phase,
            "target_guid": context.get("expected_guid"),
            "last_binding": context.get("last_binding"),
            "ability_uses": dict(context.get("ability_uses") or {}),
            "ability_attempts": list((context.get("ability_attempts") or [])[-8:]),
            "visual_follow": dict(context.get("visual_follow") or {}),
            "local_retry_count": state.local_retry_count,
            "approach_active": bool(context.get("approach_request"))}


def pending_autonomy_events(lifecycle: Iterable[dict[str, Any]], cursor: int
                            ) -> list[tuple[int, str, dict[str, Any]]]:
    rows = []
    for event in lifecycle:
        sequence = int(event.get("sequence") or 0)
        if sequence <= cursor:
            continue
        event_type = str(event.get("event") or "AUTONOMY_EVENT")
        aliases = {
            "SUBGOAL_COMMITTED": ("TARGET_COMMITTED"
                                  if event.get("kind") == "TARGET" else "SUBGOAL_COMMITTED"),
            "COMMITMENT_RELEASED": "TARGET_RELEASED",
        }
        rows.append((sequence, aliases.get(event_type, event_type), dict(event)))
    return rows


def visual_control_observation_id(world) -> str:
    latest = world.latest
    visual = world.latest_visual_observation_id or (
        latest.observation_id if latest else "none")
    if latest and latest.payload.get("transport_kind") == "FAST":
        return f"{visual}:fast:{latest.payload.get('fast_sequence', latest.observation_id)}"
    return visual


def movement_assessment_event(attempt, assessment, previous: tuple[str, str] | None,
                              now: float
                              ) -> tuple[tuple[str, str], RuntimeEvent | None]:
    current = (attempt.action_id, assessment.phase.value)
    if current == previous:
        return current, None
    event_type = None
    if assessment.phase.value == "CANDIDATE_STUCK":
        event_type = "POSSIBLE_STUCK"
    elif assessment.phase.value == "SUPPORTED_STUCK":
        event_type = "STUCK_DETECTED"
    elif (assessment.phase.value == "MOVING" and previous is not None
          and previous[0] == attempt.action_id
          and previous[1] in {"CANDIDATE_STUCK", "SUPPORTED_STUCK"}):
        event_type = "STUCK_RECOVERED"
    if event_type is None:
        return current, None
    return current, RuntimeEvent(
        event_type, now,
        {"action_id": attempt.action_id, "plan_id": attempt.plan_id,
         "skill": attempt.proposal.skill, "phase": assessment.phase.value,
         "reason": assessment.reason},
        event_id=f"movement:{attempt.action_id}:{assessment.phase.value}",
        source="MOVEMENT_CONTROLLER", correlation_id=attempt.action_id)


def target_named_by_open_objective(state: dict[str, Any]) -> bool:
    """The selected unit's name appears in an unfinished quest objective."""
    return _named_by_open_objective(state, state.get("target") or {})


OBJECTIVE_HOVER_MAX_AGE_SECONDS = .5


def mouseover_named_by_open_objective(state: dict[str, Any]) -> bool:
    """A fresh mouseover (not the selected unit) is named by an open objective.

    Live 2026-10-05 (Emergency First Aid): Kee-La passed under the cursor
    three times during the search MOVEs; the MOVE went on and the planner,
    which would select her, never ran.
    """
    mouse = state.get("mouseover") or {}
    if (mouse.get("is_player") is True or mouse.get("dead", mouse.get("is_dead"))
            or str(mouse.get("guid") or "") == str((state.get("target") or {}).get("guid") or "")):
        return False
    now, sample = number(state.get("monotonic_time")), number(state.get("mouseover_sample_time"))
    if now is not None and sample is not None and not 0 <= now-sample <= OBJECTIVE_HOVER_MAX_AGE_SECONDS:
        return False
    return _named_by_open_objective(state, mouse)


def _named_by_open_objective(state: dict[str, Any], unit: dict[str, Any]) -> bool:
    name = str(unit.get("name") or "").strip().casefold()
    if not unit.get("guid") or not name:
        return False
    return any(name in str(objective.get("description") or "").casefold()
               for quest in state.get("active_quests") or ()
               if isinstance(quest, dict) and quest.get("is_complete") is not True
               for objective in quest.get("objectives") or ()
               if isinstance(objective, dict) and not objective.get("is_complete"))


def quest_zone_entered(params: dict, world_state: dict[str, Any]) -> dict[str, Any] | None:
    """The objective MOVE has reached the quest zone: hand over to the search.

    User 2026-10-05: entering the zone means getting inside the blue quest
    area on the minimap; from there the yellow-dot approach, the visual seek
    and the minimap search take over instead of walking to the area's
    centre.  Objective dots drawn grey with a down/up arrow mean the
    objective is on another floor: then we are *not* in the zone yet (Hrun's
    pit: inside the blue area on the rim, the cocoons far below).  A descent
    to a lower layer ends when a yellow (same-space) objective dot shows.
    """
    minimap = [item for item in world_state.get("visual_candidates") or ()
               if isinstance(item, dict) and "MINIMAP" in str(item.get("source") or "")]
    labels = {str(label).lower() for item in minimap for label in item.get("candidate_labels") or ()}
    from .quest_location_planning import minimap_objective_dots
    quest = str(params.get("quest_id"))
    same_space = any(str(dot[2]) == quest for dot in minimap_objective_dots(world_state))
    if same_space:
        # The cave minimap can show an unrelated above/below objective at the
        # same time.  It must not veto this quest's same-space yellow marker.
        return {"reason": "quest_zone_entered_same_space", "kind": "QUEST_ZONE_ENTERED",
                "evidence": "MINIMAP_YELLOW_OBJECTIVE_DOT"}
    if params.get("destination_layer") == "LOWER":
        # A blue 2D area on the rim does not establish arrival below it.
        return None
    if {"objective_below_like", "objective_above_like"} & labels:
        return None
    area = next((item for item in minimap if item.get("kind") == "minimap_quest_area"
                 and (item.get("quest_area") or {}).get("player_inside") is True), None)
    if area is None:
        return None
    # The blue area belongs to a quest near this destination: the POI is in
    # minimap view.
    position = world_state.get("player_world_position") or {}
    px, py = number(position.get("x")), number(position.get("y"))
    dx, dy = number(params.get("x")), number(params.get("y"))
    view = (number(area.get("view_radius_yards"))
            or number((world_state.get("minimap_geometry") or {}).get("view_radius_yards")) or 160.)
    if None in (px, py, dx, dy) or math.hypot(dx-px, dy-py) > view:
        return None
    return {"reason": "quest_zone_entered", "kind": "QUEST_ZONE_ENTERED",
            "evidence": "MINIMAP_BLUE_AREA"}


def movement_visual_interrupt(attempt, world_state: dict[str, Any]) -> dict[str, Any] | None:
    """Return one goal-relevant visual handoff observed during navigation.

    Perception remains passive while NavigationService owns MOVE.  This gate
    does not issue input or recognize an entity: it only selects a stable
    UNKNOWN track that is worth handing to INSPECT/SEEK_VISUAL_CUE.  Generic
    scenery therefore cannot continuously preempt a committed route.
    """
    if attempt is None:
        return None
    params = attempt.proposal.parameters
    if attempt.proposal.skill not in {"MOVE", "REACH_LOCATION", "REACH_OBJECT"}:
        return None
    purpose = str(params.get("purpose") or "")
    if purpose == "APPROACH_MINIMAP_QUEST_DOT" and target_named_by_open_objective(world_state):
        # Live 2026-10-04 00:48: Captain Garrick was selected but the dot
        # MOVE kept walking into him and he pushed the player back; the
        # objective ("Abilities proven against ...") needs COMBAT/Charge.
        return {"reason": "minimap_dot_objective_npc_targeted",
                "kind": "OBJECTIVE_NPC_TARGETED"}
    reference_reach = (
        params.get("source") == "TDB_REFERENCE"
        and purpose == "INSPECT_REFERENCE_LOCATION")
    quest_route = purpose in {
        "LOCATE_TURN_IN_REGION", "LOCATE_QUEST_OBJECTIVE_REGION",
        "SEARCH_LOCAL_OBJECTIVE_AREA", "FIND_QUEST_GIVER_AREA",
        "LOCATE_API_QUEST_GIVER", "SEARCH_TURN_IN_AREA",
    }
    if not (reference_reach or quest_route or purpose == "APPROACH_MINIMAP_QUEST_DOT"):
        return None
    if mouseover_named_by_open_objective(world_state):
        return {"reason": "objective_unit_under_cursor", "kind": "OBJECTIVE_UNIT_HOVERED"}
    from .object_interaction_flow import open_object_objective, quest_object_candidates
    if (open_object_objective(world_state, params.get("quest_id"))
            and (quest_object_candidates(world_state)
                 or any(isinstance(target, dict) and target.get("unit_type") == "GAMEOBJECT"
                        for target in world_state.get("soft_targets") or ()))):
        # User 2026-10-06: the sweep walked past two cocoons the learned
        # detector saw.  The planner walks to the object and uses it.
        return {"reason": "quest_object_visible", "kind": "QUEST_OBJECT_VISIBLE"}
    if not (reference_reach or quest_route):
        return None
    if purpose == "LOCATE_QUEST_OBJECTIVE_REGION":
        entered = quest_zone_entered(params, world_state)
        if entered is not None:
            return entered
    mouse = world_state.get("mouseover") or {}
    expected = {str(value) for value in params.get("npc_ids", []) if value is not None}
    if params.get("npc_id") is not None:
        expected.add(str(params["npc_id"]))
    if (reference_reach and mouse.get("guid") and mouse.get("is_player") is not True
            and mouse.get("attackable", mouse.get("is_attackable")) is False
            and (not expected or str(mouse.get("npc_id")) in expected)):
        return {"reason": "live_reference_identity_observed",
                "kind": "REFERENCE_IDENTITY", "track_id": mouse.get("track_id")}
    now = number(world_state.get("monotonic_time"))
    objective_type = str(params.get("objective_type") or "").upper()
    position = (world_state.get("player_world_position")
                if isinstance(world_state.get("player_world_position"), dict) else {})
    player_x, player_y = number(position.get("x")), number(position.get("y"))
    destination_x, destination_y = number(params.get("x")), number(params.get("y"))
    same_instance = (params.get("instance_id") is None
                     or position.get("instance_id") is None
                     or str(params.get("instance_id")) == str(position.get("instance_id")))
    destination_distance = (
        math.hypot(player_x-destination_x, player_y-destination_y)
        if (same_instance and player_x is not None and player_y is not None
            and destination_x is not None and destination_y is not None)
        else None)
    learned_handoff_area = (destination_distance is not None
                            and destination_distance <= MOVEMENT_HANDOFF_RADIUS_YARDS)
    from .object_interaction_flow import only_object_objectives_open
    objects_only = only_object_objectives_open(world_state)
    best: tuple[
        tuple[float, float, float], dict[str, Any], set[str], float, int
    ] | None = None
    for candidate in world_state.get("visual_candidates", []):
        lifecycle = str(candidate.get("lifecycle") or candidate.get("track_state") or "").upper()
        from .self_avatar import is_self_avatar_box
        if (candidate.get("source") != "WORLD3D"
                or is_self_avatar_box(candidate)
                or candidate.get("inspectable") is False
                or (number(candidate.get("stable_frames")) or 0) < 3
                or lifecycle in {"LOST", "REJECTED", "SUPPRESSED"}):
            continue
        observed = number(candidate.get("observed_at"))
        if now is not None and observed is not None and now-observed > .75:
            continue
        appearance = candidate.get("appearance") if isinstance(
            candidate.get("appearance"), dict) else {}
        visual_group = candidate.get("visual_group") if isinstance(
            candidate.get("visual_group"), dict) else {}
        labels = {str(value).lower() for value in candidate.get("candidate_labels") or ()}
        labels.update(str(value).lower() for value in
                      appearance.get("anchor_candidate_labels") or ())
        labels.update(str(value).lower() for value in
                      visual_group.get("appearance_labels") or ())
        learned_label = str(appearance.get("learned_label_hypothesis") or "").lower()
        learned_subject = ("learned_subject_like" in labels
                           or learned_label in {"humanoid_unit_like", "creature_unit_like"})
        quest_cue = bool({"quest_marker_like", "quest_badge_like"} & labels)
        supported_overhead = any(
            edge.get("type") == "ABOVE"
            and str(edge.get("belief") or "").upper() == "SUPPORTED"
            for edge in candidate.get("visual_relations") or ())

        relevant = reference_reach and candidate.get("information_value") == "HIGH"
        if quest_route:
            if purpose in {"FIND_QUEST_GIVER_AREA", "LOCATE_API_QUEST_GIVER"}:
                # Roaming for a quest giver stops for a quest symbol or a
                # supported symbol<->subject group, not for passing creatures.
                relevant = quest_cue or supported_overhead
            elif purpose in {"LOCATE_TURN_IN_REGION", "SEARCH_TURN_IN_AREA"}:
                # A turn-in route is interrupted only by quest-symbol evidence
                # (or its supported subject relation), never by every creature
                # crossed on the road.  A unit box with a "?"/"!" box right
                # over its head is that evidence too (user 2026-10-03).
                from .quest_giver_evidence import subject_has_quest_symbol
                from .self_avatar import is_self_avatar_box
                relevant = quest_cue or (
                    not is_self_avatar_box(candidate)
                    and subject_has_quest_symbol(candidate, [
                        item for item in world_state.get("visual_candidates", [])
                        if isinstance(item, dict) and item.get("source") == "WORLD3D"]))
            elif objective_type in {"TALK", "TALK_TO", "SPEAK", "INTERACT_NPC"}:
                # The unit model no longer separates humanoid bodies from
                # creatures; addon identity decides who the NPC is.
                relevant = (quest_cue or (
                    learned_subject and learned_handoff_area))
            elif objects_only:
                # A cocoon objective: a passing creature/pet is no cue.
                relevant = quest_cue
            else:
                relevant = quest_cue or (learned_subject and learned_handoff_area)
        confidence = number(candidate.get("confidence")) or 0.
        stable_frames = number(candidate.get("stable_frames")) or 0
        minimum = (MOVEMENT_HANDOFF_SUBJECT_CONFIDENCE
                   if learned_subject and not quest_cue else .50)
        minimum_stability = (MOVEMENT_HANDOFF_SUBJECT_STABLE_FRAMES
                             if learned_subject and not quest_cue else 3)
        if (not relevant or confidence < minimum
                or stable_frames < minimum_stability):
            continue
        rank = (1. if quest_cue else .75 if supported_overhead else .5,
                float(stable_frames), confidence)
        if best is None or rank > best[0]:
            best = (rank, candidate, labels, minimum, minimum_stability)
    if best is not None:
        _, candidate, labels, minimum, minimum_stability = best
        return {
            "reason": ("quest_route_visual_cue_observed" if quest_route
                       else "live_visual_inspection_candidate_observed"),
            "kind": "QUEST_ROUTE_VISUAL_CUE" if quest_route else "REFERENCE_VISUAL_CUE",
            "track_id": candidate.get("track_id"),
            "route_purpose": purpose,
            "candidate_labels": sorted(labels),
            "destination_distance_yards": destination_distance,
            "handoff_confidence_gate": minimum,
            "handoff_stable_frames_gate": minimum_stability,
        }
    return None


def reference_reach_visual_interrupt(attempt, world_state: dict[str, Any]) -> str | None:
    """Compatibility projection retained for older tests/callers."""
    result = movement_visual_interrupt(attempt, world_state)
    return str(result.get("reason")) if result else None
