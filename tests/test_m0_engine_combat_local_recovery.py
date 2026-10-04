"""Engine boundary replay for same-attempt combat local navigation."""
from test_agent_core import agent, state


def _spell():
    return {"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
            "is_harmful": True, "is_usable": True, "in_range": True,
            "cooldown_remaining": 0}


def _target():
    return {"guid": "mob-1", "attackable": True, "dead": False, "health": 20,
            "screen_position": {"x": .72, "y": .48, "sample_time": 1.}}


def test_engine_repositions_los_locally_without_replanning_or_replacing_active_combat():
    value, executor = agent()
    value.tick(state(1., target=_target(), is_in_combat=True, actionbar=[_spell()]), 1.)
    assert value.pending and value.pending.proposal.skill == "DEFEND"
    action_id = value.pending.action_id

    current = _target()
    current["screen_position"] = {"x": .72, "y": .48, "sample_time": 2.}
    value.tick(state(2., target=current, is_in_combat=True, actionbar=[_spell()],
                     ui_error="No line of sight"), 2.)

    assert value.pending and value.pending.action_id == action_id
    assert value.active_skill.state is not None
    assert value.active_skill.state.phase == "RECOVER_LOS"
    # M2.8 uses a bounded lateral probe chosen from free-space/target-bearing
    # evidence; it no longer advances blindly into the LOS blocker.
    assert executor.commands[-1].binding == "STRAFERIGHT"
    assert executor.commands[-1].simultaneous == ()

    # The exported error may still describe the previous cast.  The next
    # control step retries the ability on the committed target instead of
    # sending the agent back through TARGET/SEARCH/PLAN.
    current["screen_position"]["sample_time"] = 2.1
    value.tick(state(2.1, target=current, is_in_combat=True, actionbar=[_spell()],
                     ui_error="No line of sight"), 2.1)
    assert value.pending and value.pending.action_id == action_id
    assert executor.commands[-1].binding == "ACTIONBUTTON1"


def test_engine_uses_persistent_navigation_for_world_localized_combat_range_recovery():
    value, executor = agent()
    value.tick(state(1., target=_target(), is_in_combat=True, actionbar=[_spell()]), 1.)
    assert value.pending and value.pending.proposal.skill == "DEFEND"
    action_id = value.pending.action_id

    target = _target()
    target["world_position"] = {"x": 14., "y": 8., "instance_id": 2}
    value.tick(state(2., target=target, is_in_combat=True, actionbar=[_spell()],
                     player_world_position={"x": 1., "y": 1., "instance_id": 2},
                     ui_error="Need to be closer."), 2.)

    assert value.pending and value.pending.action_id == action_id
    assert value.active_skill.state is not None
    assert value.active_skill.state.phase == "RECOVER_RANGE"
    assert value.active_skill.state.skill_context["combat"]["approach_request"]["kind"] == "WORLD_COMBAT"
    assert value.navigation.movement_snapshot()["phase"] != "IDLE"
    assert executor.commands[-1].binding == "MOVEFORWARD"
