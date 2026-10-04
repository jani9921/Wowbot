from test_agent_core import agent, state
from wowbot.agent.models import Mode


def test_manual_cancel_stops_executor_and_finalizes_only_active_skill():
    value, executor = agent()
    target = {"guid": "mob-1", "npc_id": 5, "attackable": True, "dead": False}
    action = {"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
              "is_harmful": True, "is_usable": True, "in_range": True,
              "cooldown_remaining": 0}
    quest = {"quest_id": 1, "objectives": [{"raw_type": "monster", "target_npc_id": 5,
                                                "current": 0, "required": 1}]}
    value.tick(state(1, target=target, actionbar=[action], active_quests=[quest]), 1)
    assert value.pending and value.active_skill.exists
    value.set_mode(Mode.MANUAL)
    assert value.pending is None
    assert value.active_skill.state is None
    assert executor.stops >= 1
