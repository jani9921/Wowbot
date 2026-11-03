"""Found 2026-10-12: the per-tick status refresh rewrote the world's runtime
context without the running skill and the last result.  Between planning
passes (when quest progress is learned on ingest) both were None, so every
quest_progress row stored skill=NULL."""
from test_agent_core import agent, state


def test_status_refresh_keeps_the_running_skill_and_last_result():
    value, _ = agent()
    value.tick(state(1.), 1.)
    value.last_result = {"outcome": "SUCCESS", "reason": "ok", "skill": "COMBAT"}
    value.status(1.1)
    context = value.world.runtime_context
    assert (context.get("last_result") or {}).get("skill") == "COMBAT"
    assert isinstance(context.get("active_skill"), dict) and "skill" in context["active_skill"]
