"""Lightweight adapter for the canonical navigation/input authorities."""
from __future__ import annotations

from .models import Mode, Observation
from .world_addon_reducer import WorldAddonReducer
from wowbot.execution import DispatchLane


def advance_fast_movement(agent, payload: dict, now: float, movement_skills: set[str]) -> dict:
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
    if (payload.get("is_dead") is True
            or (payload.get("is_ghost") is True and previous.get("is_ghost") is not True)
            or (payload.get("is_in_combat") is True
                and previous.get("is_in_combat") is not True)):
        agent.command_dispatcher.stop_movement()
        return {"consumed": False, "force_medium": True,
                "reason": "fast_combat_or_death_transition"}
    # Live 2026-10-04 00:03: this lane consumes every FAST packet of an
    # active reach, so the world model saw no receive for 6 s, the freshness
    # gate suspended input, and it never recovered while packets kept
    # flowing here.  A consumed packet proves the pipeline is alive (same
    # rule as a duplicate packet in ``WorldModel.ingest``).
    agent.world.last_received = max(agent.world.last_received, now)
    state = {**agent.world.state}
    for key in WorldAddonReducer.FAST_KEYS:
        if key in payload:
            state[key] = payload[key]
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
            commands, DispatchLane.MOVEMENT,
            correlation_id=attempt.action_id)
        agent._fast_control_dispatches += 1
    return {"consumed": True, "terminal": False,
            "dispatched": bool(commands), "reason": assessment.reason}
