"""Lightweight adapter for the canonical navigation/input authorities."""
from __future__ import annotations

from .models import Mode, Observation
from .world_addon_reducer import WorldAddonReducer
from .engine_runtime_projection import movement_visual_interrupt
from wowbot.execution import DispatchLane
from wowbot.execution.command_dispatch import flight_ability_tap


def advance_fast_movement(agent, payload: dict, now: float, movement_skills: set[str], *,
                          state_override: dict | None = None, steer_pointer: bool = True) -> dict:
    """Consume one FAST sample without world fusion, planning or persistence.

    This module deliberately owns no controller or input state.  It advances
    the agent's one NavigationService and dispatches through its one
    CommandDispatcher while the caller holds the agent lock.
    """
    attempt = agent.pending
    if (agent.mode != Mode.FULL_AI or attempt is None
            or attempt.proposal.skill not in movement_skills):
        return {"consumed": False, "reason": "no_active_movement"}
    if (payload.get("session_id") != agent.world.session_id
            or payload.get("player_present", True) is False
            or payload.get("loading") is True
            or payload.get("input_blocked") is True):
        agent.command_dispatcher.stop_movement()
        return {"consumed": False, "force_medium": True,
                "reason": "fast_control_safety_transition"}
    # Issue #70: a fresh combat/death/ghost transition preempts the reach
    # now instead of at the next medium tick (up to 1 s later). Movement that
    # started inside combat or as a ghost (corpse run) is not a transition.
    previous = agent.world.state
    if ((payload.get("in_vehicle") is True and previous.get("in_vehicle") is not True)
            or (payload.get("in_vehicle") is False and previous.get("in_vehicle") is True)):
        # Do not consume the boarding edge as another successful ground
        # movement tick. Canonical fusion must see it and invalidate the
        # old route, even before the full vehicle action bar is assembled.
        # Losing the vehicle must likewise stop its flight/attack approach.
        agent.command_dispatcher.stop_movement()
        return {"consumed": False, "force_medium": True,
                "reason": "fast_vehicle_transition"}
    if (payload.get("is_dead") is True
            or (payload.get("is_ghost") is True and previous.get("is_ghost") is not True)
            or (payload.get("is_in_combat") is True
                and previous.get("is_in_combat") is not True)):
        agent.command_dispatcher.stop_movement()
        return {"consumed": False, "force_medium": True,
                "reason": "fast_combat_or_death_transition"}
    allows_flight = getattr(agent.navigation, "flight_controls_allowed", None)
    flight_control = callable(allows_flight) and allows_flight({**previous, **payload})
    if (payload.get("movement") or {}).get("falling") is True and not flight_control:
        # A fresh FAST fall is a physical safety transition.  Do not wait for
        # FALL_ENDED or the slower canonical tick while MOVEFORWARD is held.
        # The medium tick may see only the landing: record the hazardous
        # upper-route crossing from this exact FAST position before yielding.
        agent.command_dispatcher.stop_movement()
        state = {**agent.world.state}
        for key in WorldAddonReducer.FAST_KEYS:
            if key in payload:
                state[key] = payload[key]
        agent.navigation.observe(state, f"fast-fall:{now:.6f}", now, commanded=True)
        return {"consumed": False, "force_medium": True,
                "reason": "fast_fall_transition"}
    if payload.get("quest_ui_open") is True or payload.get("gossip_open") is True:
        # A FAST UI edge must release W before the paged detail state arrives.
        # The medium lane then verifies the dialog and chooses its action.
        agent.command_dispatcher.stop_movement()
        agent.navigation.cancel_movement()
        return {"consumed": False, "force_medium": True,
                "reason": "fast_interaction_ui_opened"}
    # Live 2026-10-04 00:03: this lane consumes every FAST packet of an
    # active reach, so the world model saw no receive for 6 s, the freshness
    # gate suspended input, and it never recovered while packets kept
    # flowing here.  A consumed packet proves the pipeline is alive (same
    # rule as a duplicate packet in ``WorldModel.ingest``).
    agent.world.last_received = max(agent.world.last_received, now)
    state = dict(state_override) if state_override is not None else {**agent.world.state}
    delta = {key: value for key, value in payload.items() if key in WorldAddonReducer.FAST_KEYS}
    WorldAddonReducer._stamp_unit_samples(delta)
    state.update(delta)
    from .world_packet_reducer import WorldPacketReducer
    feedback = getattr(agent, "packet_feedback", None)
    if flight_control and callable(feedback):
        # The newest own movement packet, not the medium tick's (user
        # 2026-10-25: Skyriding overshot every heading on 0.3-0.6 s old data).
        feedback(agent.world, now)
    WorldPacketReducer.project_flight_feedback(agent.world, state, now)
    WorldPacketReducer.project_own_navigation(agent.world, state, now)
    feedback_pending=getattr(agent.navigation,'route_feedback_pending',None)
    if callable(feedback_pending) and feedback_pending():
        agent.command_dispatcher.stop_movement()
        return {'consumed':False,'force_medium':True,'reason':'movement_route_plan_pending'}
    position_plan = getattr(agent.navigation, 'position_plan_pending', None)
    if callable(position_plan) and position_plan(state, now):
        agent.command_dispatcher.stop_movement()
        return {'consumed': False, 'force_medium': True,
                'reason': 'movement_position_acquired_pending'}
    ground_approach = getattr(agent.navigation, "needs_ground_approach", None)
    if callable(ground_approach) and ground_approach(state, now):
        # A ground-route query belongs to the canonical medium owner. The
        # fast lane releases the flight lease and requests that handoff.
        agent.command_dispatcher.stop_movement()
        return {"consumed": False, "force_medium": True,
                "reason": "movement_ground_approach_pending"}
    interrupt = movement_visual_interrupt(attempt, state, identity_only=True,
                                          travel_cost=agent.navigation.walk_cost)
    if interrupt and interrupt.get("kind") in {"OBJECTIVE_UNIT_HOVERED", "QUEST_ROUTE_NPC_HOVERED",
                                               "SERVER_TURN_IN_ENTITY_AVAILABLE", "SERVER_TURN_IN_INTERACTION_READY",
                                               "SERVER_TURN_IN_POI_AVAILABLE",
                                               "SERVER_OBJECTIVE_NPC_AVAILABLE",
                                               "RESCUE_NPC_SOFT_INTERACT", "VEHICLE_QUEST_CONTROLS",
                                               "SCENE_COURSE_STARTED", "QUEST_VEHICLE_PREREQUISITE"}:
        # Stop renewing the forward lease NOW and let the canonical medium
        # tick ingest this exact hover and select TARGET. No second planner,
        # skill finalization or click runs in this control lane.
        agent.command_dispatcher.stop_movement()
        return {"consumed": False, "force_medium": True,
                "reason": interrupt["reason"]}
    observation = Observation.create(payload, now)
    assessment = agent.navigation.observe(
        state, observation.observation_id, now, commanded=True)
    agent._fast_control_updates += 1
    agent._last_movement_assessment = (
        str(assessment.phase), str(assessment.reason))
    if assessment.terminal:
        agent.command_dispatcher.stop_movement()
        agent._fast_control_terminal = {
            "phase": str(assessment.phase),
            "success": bool(assessment.success),
            "reason": assessment.reason,
            "observation_id": observation.observation_id,
            "at": now,
        }
        return {"consumed": True, "terminal": True,
                "reason": assessment.reason}
    commands = tuple(agent.navigation.command(
        state, observation.observation_id, now))
    if commands:
        agent.command_dispatcher.dispatch(
            commands, DispatchLane.DISCRETE if flight_ability_tap(commands) else DispatchLane.MOVEMENT,
            correlation_id=attempt.action_id)
        agent._fast_control_dispatches += 1
    steer = getattr(agent, "_steer_object_lock", None)
    if steer_pointer and callable(steer):
        # The pointer follows a locked quest object with this FAST facing
        # (no button: the forward lease keeps running).
        steer(now, state, refresh=False)
    return {"consumed": True, "terminal": False,
            "dispatched": bool(commands), "reason": assessment.reason}
