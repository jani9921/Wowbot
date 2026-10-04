"""One reset path for authoritative player/session changes."""
from __future__ import annotations

from .models import Mode


def handle_session_change(agent, now: float) -> None:
    if agent.memory and agent.episode_id:
        agent.memory.finish_episode(
            agent.episode_id, agent.world.state, now, "CANCELLED",
            {"reason": "character_or_session_changed"})
        agent.episode_id = None
    agent.set_mode(Mode.MANUAL)
    agent.last_result = {"outcome": "CANCELLED", "reason": "character_or_session_changed"}
    agent.navigation.reset()
    agent.autonomy.reset(now, "SESSION_CHANGED")
    agent.planner.reset_session()
    agent.failures.clear()
    agent.failure_manager.reset()
    agent.approach_counts.clear()
    agent.current_plan = None
    agent.last_plan_signature = None
    agent.recovery_for = None
    agent.freshness_gate.reset()
    agent._invalidation_context = None
    agent._stationary_position = None
    agent._stationary_since = None
    agent.brain_scheduler.reset()
