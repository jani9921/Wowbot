"""Pure runtime projections extracted from the AutonomousAgent authority.

This module has no executor, input backend, WorldModel mutation, event-bus
publication, planner, or active-skill finalization capability.  It only turns
already-owned runtime state into snapshots and proposed events.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from wowbot.query_ports import TravelCostPort
from wowbot.runtime import RuntimeEvent


# Detection and interruption have different costs.  A .15 learned subject is
# useful evidence while stationary, but cancelling an owned navmesh route is a
# much stronger action and therefore requires stronger temporal/visual support
# near the route endpoint.
MOVEMENT_HANDOFF_SUBJECT_CONFIDENCE = .30
MOVEMENT_HANDOFF_SUBJECT_STABLE_FRAMES = 6
MOVEMENT_HANDOFF_RADIUS_YARDS = 25.
# A turn-in walk stops for a quest symbol only near the known ender place.
TURN_IN_CUE_RADIUS_YARDS = 40.

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
    from .target_planning import is_player_unit, TARGET_HANDOFF_MAX_SAMPLE_AGE_SECONDS
    if (is_player_unit(mouse, state) or mouse.get("dead") is True or mouse.get("is_dead") is True
            or number(mouse.get("health")) == 0
            or str(mouse.get("guid") or "") == str((state.get("target") or {}).get("guid") or "")):
        return False
    if (state.get("map_mouseover") or {}).get("surface") in {"MINIMAP", "WORLD_MAP"}:
        return False
    now, sample = number(state.get("monotonic_time")), number(state.get("mouseover_sample_time"))
    if now is not None and sample is not None and not 0 <= now-sample <= OBJECTIVE_HOVER_MAX_AGE_SECONDS:
        return False
    if mouse.get("attackable", mouse.get("is_attackable")) is True:
        # Yield only to a hover the TARGET policy can actually consume. A
        # fresh GUID paired with an older/moved cursor is not a click point.
        cursor = state.get("cursor_position") or {}
        cursor_at = number(state.get("cursor_sample_time"))
        target = state.get("target") or {}
        if (state.get("is_in_combat")
                or (mouse.get("npc_id") is None
                    and str(mouse.get("unit_type") or "").upper() not in {"NPC", "CREATURE"})
                or (target.get("attackable", target.get("is_attackable")) is True
                    and target.get("dead") is not True and target.get("is_dead") is not True)
                or None in (now, sample, cursor_at, number(cursor.get("nx")), number(cursor.get("ny")))
                or not 0 <= now-sample <= TARGET_HANDOFF_MAX_SAMPLE_AGE_SECONDS
                or not 0 <= now-cursor_at <= TARGET_HANDOFF_MAX_SAMPLE_AGE_SECONDS
                or abs(sample-cursor_at) > .05):
            return False
    return _named_by_open_objective(state, mouse)


def _named_by_open_objective(state: dict[str, Any], unit: dict[str, Any]) -> bool:
    from .quest_semantics import target_matches_objective, target_matches_structured_entity
    from .target_planning import is_player_unit, tooltip_names_active_quest
    from .tooltip_quest import creature_tooltip_open, tooltip_objectives_done
    name = str(unit.get("name") or "").strip().casefold()
    if (not unit.get("guid") or not name or is_player_unit(unit, state)
            or unit.get("dead") is True or unit.get("is_dead") is True
            or number(unit.get("health")) == 0):
        return False
    objectives = [objective for quest in state.get("active_quests") or ()
                  if isinstance(quest, dict) and quest.get("is_complete") is not True
                  for objective in quest.get("objectives") or ()
                  if isinstance(objective, dict) and not objective.get("is_complete")
                  and not (number(objective.get("required")) is not None
                           and number(objective.get("current")) is not None
                           and number(objective["current"]) >= number(objective["required"]))]
    if unit.get("attackable", unit.get("is_attackable")) is True:
        # Use the same generic combat-subject/tooltip evidence as TARGET.
        # "defeated Murlocs" legitimately names Murloc Watershaper, without
        # inventing named identity from a detector box or a quest-ID hotfix.
        return bool(objectives) and ((unit.get("quest_related") is True
                                     and not tooltip_objectives_done(unit)
                                     and creature_tooltip_open(unit, state))
            or tooltip_names_active_quest(unit, state) or any(
            target_matches_structured_entity(unit, objective.get("target_entity"))
            or target_matches_objective(unit, objective) for objective in objectives))
    return any(name in str(objective.get("description") or "").casefold()
               for objective in objectives)


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


def movement_visual_interrupt(attempt, world_state: dict[str, Any], *,
                              object_at_hand=None, object_handoff=None, identity_only: bool = False,
                              skip_track_ids: frozenset[str] = frozenset(),
                              travel_cost: TravelCostPort | None = None) -> dict[str, Any] | None:
    """Return one goal-relevant visual handoff observed during navigation.

    Perception remains passive while NavigationService owns MOVE.  This gate
    does not issue input or recognize an entity: it only selects a stable
    UNKNOWN track that is worth handing to INSPECT/SEEK_VISUAL_CUE.  Generic
    scenery therefore cannot continuously preempt a committed route.

    ``object_at_hand(quest_id)`` answers whether an unspent quest object with
    a known spawn is near on the player's floor (None: unknown).
    ``object_handoff(params)`` stops a walk to one quest object for another
    one passed on the way, a spent target or a certified hovered one.
    """
    if attempt is None:
        return None
    params = attempt.proposal.parameters
    if attempt.proposal.skill not in {"MOVE", "REACH_LOCATION", "REACH_OBJECT"}:
        return None
    from .vehicle_prerequisites import movement_interrupt as vehicle_prerequisite_interrupt
    vehicle_handoff = vehicle_prerequisite_interrupt(params, world_state)
    if vehicle_handoff is not None:
        return vehicle_handoff
    if params.get("purpose") != "SCENE_COURSE":
        # Live 2026-10-25 21:05:56: the Skytop race scene started while a walk
        # to a quest NPC held the attempt; the timed course waited 15 s.
        from wowbot.quests.scene_path_planning import active_scene_course
        if active_scene_course(world_state)[0] is not None:
            return {"reason": "scene_course_started", "kind": "SCENE_COURSE_STARTED"}
    from .server_mode import server_mode_selected
    server_mode = server_mode_selected(world_state)
    from .vehicle_abilities import stationary_vehicle_controls
    if stationary_vehicle_controls(world_state):
        return {"reason": "vehicle_quest_controls_own_input", "kind": "VEHICLE_QUEST_CONTROLS"}
    from .rescue_object_planning import (open_rescue_entries, rescue_soft_target,
                                        rescue_interaction_in_range, RescueTargetPolicy)
    rescue = rescue_soft_target(world_state)
    target = world_state.get("target") or {}
    if rescue is None and target.get("interact_near") is True and target.get("guid"):
        entries = open_rescue_entries(world_state)
        if (str(target.get("npc_id")) in entries
                and rescue_interaction_in_range(world_state, target["guid"]) is not False):
            rescue = {"guid": target["guid"], "quest_id": entries[str(target["npc_id"])]}
    if rescue is not None:
        # Live 2026-10-21 10:34:42: a rescue NPC on a circling drake is the
        # soft-interact unit only for a moment; stop and press Interact.
        return {"reason": "rescue_npc_soft_interact", "kind": "RESCUE_NPC_SOFT_INTERACT",
                "guid": rescue["guid"], "quest_id": rescue["quest_id"]}
    purpose = str(params.get("purpose") or "")
    if purpose == "SEARCH_QUEST_ITEM_SUBJECT":
        from .quest_item_search import search_actor_available
        guid = search_actor_available(params, world_state)
        if guid is not None:
            return {"reason": "server_item_subject_available", "kind": "SERVER_ITEM_SUBJECT_AVAILABLE",
                    "guid": guid, "quest_id": params.get("quest_id")}
    if purpose == "SEARCH_RESCUE_OBJECTIVE":
        actor = RescueTargetPolicy._direct_credit_approach(world_state, open_rescue_entries(world_state))
        if actor is not None:
            return {"reason": "server_rescue_entity_available", "kind": "SERVER_RESCUE_ENTITY_AVAILABLE",
                    "guid": actor.parameters["server_entity_guid"], "quest_id": params.get("quest_id")}
    if purpose == "APPROACH_QUEST_OBJECT_SPAWN" and object_handoff is not None and not identity_only:
        handoff = object_handoff(params)
        if handoff:
            return handoff
    if (purpose in {"LOCATE_TURN_IN_REGION", "SEARCH_TURN_IN_AREA"}
            and params.get("quest_id") is not None
            and isinstance(world_state.get("active_quests"), list)
            and str(params["quest_id"]) not in {
                str(quest.get("quest_id")) for quest in world_state["active_quests"]
                if isinstance(quest, dict)}):
        # Live 2026-10-11 15:54: the turn-in MOVE chosen a moment before the
        # Hjalmar turn-in landed kept walking away for 35 s afterwards.
        return {"reason": "turn_in_quest_left_log", "kind": "QUEST_LEFT_LOG"}
    if (purpose == "LOCATE_QUEST_OBJECTIVE_REGION" and params.get("quest_id") is not None
            and world_state.get("packet_entities")):
        # A running POI search yields to the objective's NPC as soon as the
        # server sends it (live 2026-10-28 10:53: Left and Right 12 yd away).
        from .server_npc_planning import objective_npc_available
        guid = objective_npc_available(world_state, params["quest_id"],
                                       since=number(getattr(attempt, "started_at", None)),
                                       travel_cost=travel_cost)
        if guid is not None:
            return {"reason": "server_objective_npc_available", "kind": "SERVER_OBJECTIVE_NPC_AVAILABLE",
                    "quest_id": params["quest_id"], "guid": guid}
    if purpose == "APPROACH_SELECTED_TARGET":
        target = world_state.get("target") or {}
        if str(target.get("guid") or "") != str(params.get("target_guid") or ""):
            return {"reason": "selected_target_changed", "kind": "SELECTED_TARGET_CHANGED"}
        if target.get("screen_position") and not server_mode:
            # In view: visual approach / COMBAT / INTERACT take over.
            return {"reason": "selected_target_on_screen", "kind": "SELECTED_TARGET_ON_SCREEN"}
        return None
    if purpose in {"LOCATE_TURN_IN_REGION", "SEARCH_TURN_IN_AREA"} and params.get("quest_id") is not None:
        from .turnin_resolver import TurnInResolver
        ender = TurnInResolver.server_ender(params["quest_id"], world_state)
        if ender is not None:
            from .server_npc_planning import server_npc_interaction_ready
            if server_npc_interaction_ready(world_state, ender["server_entity_guid"], ender):
                return {"reason": "server_turn_in_interaction_ready", "kind": "SERVER_TURN_IN_INTERACTION_READY",
                        "quest_id": params["quest_id"], "guid": ender["server_entity_guid"]}
            same_guid = str(params.get("server_entity_guid") or "") == str(ender["server_entity_guid"])
            dx, dy = number(params.get("x")), number(params.get("y"))
            # Live 2026-10-25 10:57:25-10:58:49: a running ender drifted past
            # 2 yd every second and the walk restarted 30 times.  The tolerance
            # grows with the remaining distance; close by it stays 2 yd.
            player = world_state.get("player_world_position") or {}
            px, py = number(player.get("x")), number(player.get("y"))
            remaining = (math.hypot(dx-px, dy-py)
                         if None not in (dx, dy, px, py) else 0.)
            same_point = (dx is not None and dy is not None
                          and math.hypot(ender["x"]-dx, ender["y"]-dy) <= max(2., min(15., .25*remaining)))
            if params.get("knowledge_priority") != "SERVER_LIVE" or not same_guid or not same_point:
                # A running POI route yields to the matching server ender as
                # soon as its create/status event is fused. This is a replan,
                # not arrival, a click or a second navigation controller.
                return {"reason": "server_turn_in_entity_available", "kind": "SERVER_TURN_IN_ENTITY_AVAILABLE",
                        "quest_id": params["quest_id"], "guid": ender["server_entity_guid"]}
        if params.get("knowledge_priority") == "SERVER_LIVE":
            # The server route owns localisation all the way to F7 readiness;
            # visual boxes / marker IDs cannot steal it, even near the NPC.
            return None
        from .quest_poi_evidence import current_turnin_poi
        poi = current_turnin_poi(world_state, params['quest_id'])
        if poi is not None:
            x, y, z = (number(params.get(axis)) for axis in ('x','y','z'))
            same = (x is not None and y is not None
                    and math.hypot(poi['x']-x, poi['y']-y) <= 2.
                    and (not poi.get('z_known') or params.get('z_known') is True
                         and z is not None and abs(poi['z']-z) <= 2.))
            if params.get('knowledge_priority') != poi.get('knowledge_priority') or not same:
                packet = poi.get('knowledge_priority') == 'SERVER_POI'
                return {'reason': 'server_turn_in_poi_available' if packet else 'quest_api_turn_in_poi_available',
                        'kind': 'SERVER_TURN_IN_POI_AVAILABLE' if packet else 'QUEST_API_TURN_IN_POI_AVAILABLE',
                        'quest_id': params['quest_id']}
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
    if not server_mode and mouseover_named_by_open_objective(world_state):
        return {"reason": "objective_unit_under_cursor", "kind": "OBJECTIVE_UNIT_HOVERED"}
    # A cue cooldown is only about UNKNOWN visual evidence. A fresh public
    # ID for this route's giver/ender must still yield navigation immediately.
    # This requests a canonical TARGET; it never clicks or proves arrival.
    now = number(world_state.get("monotonic_time"))
    mouse = world_state.get("mouseover") or {}
    if not server_mode and purpose in {"LOCATE_TURN_IN_REGION", "SEARCH_TURN_IN_AREA",
                                      "LOCATE_API_QUEST_GIVER", "FIND_QUEST_GIVER_AREA"}:
        from wowbot.runtime.entity_identity import check_entity_identity
        from wowbot.runtime.skill_identity import sample_fresh
        expected_ids = list(params.get("npc_ids") or ())
        if params.get("npc_id") is not None:
            expected_ids.append(params["npc_id"])
        guid = params.get("target_guid") or params.get("guid")
        if (now is not None and mouse.get("guid") and mouse.get("is_player") is not True
                and mouse.get("attackable", mouse.get("is_attackable")) is False
                and number(world_state.get("mouseover_sample_time")) is not None
                and sample_fresh(world_state, "mouseover", now, max_age=.75)
                and any(check_entity_identity(
                    {"npc_id": npc_id, **({"guid": guid} if guid else {})}, mouse)
                        for npc_id in expected_ids)):
            return {"reason": "route_npc_identity_observed", "kind": "QUEST_ROUTE_NPC_HOVERED",
                    "guid": mouse["guid"], "npc_id": mouse.get("npc_id"),
                    "track_id": mouse.get("track_id")}
    if identity_only:
        return None
    if params.get('knowledge_priority') == 'PRIMARY_STATIC' and quest_route:
        # A generic YOLO object/UNKNOWN is not proof that the TDB destination
        # has been reached. The old handoff interrupted MOVE every time a
        # passing box appeared, before the totem/search zone. Exact live
        # mouseover above can still interrupt anywhere.
        player = world_state.get('player_world_position') or {}
        px, py = number(player.get('x')), number(player.get('y'))
        dx, dy = number(params.get('x')), number(params.get('y'))
        near_endpoint = (None not in (px, py, dx, dy)
                         and player.get('instance_id') == params.get('instance_id')
                         and math.hypot(px-dx, py-dy)
                         <= max(10., number(params.get('stop_distance')) or 0.))
        if not near_endpoint:
            return None
    from .object_interaction_flow import open_object_objective, quest_object_candidates
    if (not server_mode and open_object_objective(world_state, params.get("quest_id"))
            and (quest_object_candidates(world_state)
                 or any(isinstance(target, dict) and target.get("unit_type") == "GAMEOBJECT"
                        for target in world_state.get("soft_targets") or ()))
            # Live 2026-10-14 14:07:18-14:08:36: cocoons on other floors /
            # one already tried stopped every floor-walk MOVE at once; the
            # agent stood a minute on one spot.
            and (object_at_hand is None or object_at_hand(params.get("quest_id")) is not False)):
        # User 2026-10-06: the sweep walked past two cocoons the learned
        # detector saw.  The planner walks to the object and uses it.
        return {"reason": "quest_object_visible", "kind": "QUEST_OBJECT_VISIBLE"}
    if not (reference_reach or quest_route):
        return None
    if not server_mode and purpose == "LOCATE_QUEST_OBJECTIVE_REGION":
        entered = quest_zone_entered(params, world_state)
        if entered is not None:
            return entered
    mouse = world_state.get("mouseover") or {}
    expected = {str(value) for value in params.get("npc_ids", []) if value is not None}
    if params.get("npc_id") is not None:
        expected.add(str(params["npc_id"]))
    if (not server_mode and reference_reach and mouse.get("guid") and mouse.get("is_player") is not True
            and mouse.get("attackable", mouse.get("is_attackable")) is False
            and (not expected or str(mouse.get("npc_id")) in expected)):
        return {"reason": "live_reference_identity_observed",
                "kind": "REFERENCE_IDENTITY", "track_id": mouse.get("track_id")}
    if server_mode:
        # Server mode (user 2026-10-21): an unidentified World3D box never
        # stops a route while the server shows what is around.
        return None
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
        if str(candidate.get("track_id")) in skip_track_ids:
            continue
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
                if (not quest_cue and purpose == "LOCATE_TURN_IN_REGION"
                        and destination_distance is not None
                        and destination_distance > TURN_IN_CUE_RADIUS_YARDS):
                    # Live 2026-10-11 14:52: a porcupine with a generic
                    # symbol-like box over it stopped the turn-in walk ~10
                    # times 155 yd from the ender's known place.  Only a real
                    # quest marker/badge counts that far from the ender.
                    relevant = False
            elif objective_type in {"TALK", "TALK_TO", "SPEAK", "INTERACT_NPC"}:
                # The unit model no longer separates humanoid bodies from
                # creatures; addon identity decides who the NPC is.
                relevant = (quest_cue or (
                    learned_subject and learned_handoff_area))
            elif objects_only:
                # A cocoon objective: a passing creature/pet is no cue.
                relevant = quest_cue
            elif (params.get("scan_while_moving") is True
                  and (objective_type in {"KILL", "KILL_CREDIT", "COLLECT", "COMBAT"}
                       or params.get("scan_units") is True)):
                # scan_units: an item used on named creatures (live
                # 2026-10-11: Re-Sizer on Wandering Boars) needs units too.
                # Zone sweep for units (user 2026-10-10): a stable creature
                # anywhere in view is worth a look, not only one beside the
                # next cell -- the sweep would walk past the murlocs.
                relevant = quest_cue or learned_subject
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
