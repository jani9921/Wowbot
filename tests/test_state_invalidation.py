from wowbot.agent.world import WorldModel
from wowbot.runtime import InvalidationEvent, StateInvalidationPolicy
from test_agent_core import agent, state as agent_state


def state(**updates):
    value = {
        "active_quests": [{"quest_id": 1, "objectives": [{
            "objective_id": "1:a", "current_count": 0,
            "required_count": 3, "is_complete": False}]}],
        "loading": False, "map_id": 2175, "is_dead": False,
        "phase_id": 4, "floor_id": 1, "in_vehicle": False,
        "player_world_position": {"x": 10., "y": 20., "z": 3.},
    }
    value.update(updates)
    return value


def test_matrix_detects_every_named_design_077_transition():
    policy = StateInvalidationPolicy()
    before = policy.context(state())
    changed = state(
        active_quests=[{"quest_id": 1, "objectives": [{
            "objective_id": "1:a", "current_count": 1,
            "required_count": 3, "is_complete": False}]}],
        loading=True, is_dead=True, map_id=2176, phase_id=5,
        floor_id=2, in_vehicle=True)
    events = set(policy.detect(before, policy.context(changed)))
    assert events == {
        InvalidationEvent.OBJECTIVE_CHANGED, InvalidationEvent.LOADING,
        InvalidationEvent.DEATH, InvalidationEvent.MAP_CONTEXT,
        InvalidationEvent.PHASE, InvalidationEvent.FLOOR,
        InvalidationEvent.VEHICLE,
    }


def test_same_map_large_world_jump_is_teleport_but_local_move_is_not():
    policy = StateInvalidationPolicy()
    before = policy.context(state())
    local = policy.context(state(
        player_world_position={"x": 12., "y": 23., "z": 3.}))
    teleport = policy.context(state(
        player_world_position={"x": 100., "y": 120., "z": 3.}))
    assert InvalidationEvent.TELEPORT not in policy.detect(before, local)
    assert InvalidationEvent.TELEPORT in policy.detect(before, teleport)


def test_world_source_correction_without_map_motion_is_not_a_teleport():
    policy = StateInvalidationPolicy()
    before = policy.context(state(
        position={"x": .5004, "y": .5096},
        player_world_position={"x": 402.48, "y": -2231.05, "z": 98.}))
    corrected = policy.context(state(
        position={"x": .5004, "y": .5096},
        player_world_position={"x": 284.56, "y": -2210.85, "z": 98.}))

    assert InvalidationEvent.TELEPORT not in policy.detect(before, corrected)


def test_large_world_jump_with_corroborating_map_motion_is_a_teleport():
    policy = StateInvalidationPolicy()
    before = policy.context(state(
        position={"x": .2, "y": .2},
        player_world_position={"x": 10., "y": 20., "z": 3.}))
    after = policy.context(state(
        position={"x": .8, "y": .7},
        player_world_position={"x": 110., "y": 120., "z": 3.}))

    assert InvalidationEvent.TELEPORT in policy.detect(before, after)


def test_context_reset_clears_only_transient_world_state_and_calls_declared_resets():
    policy = StateInvalidationPolicy()
    world = WorldModel()
    world.mouseover_screen_anchors["Creature-1"] = {"x": .5}
    world.corpse_anchors["Creature-2"] = {"x": .4}
    world.projections["WORLD3D"] = {"visual_candidates": [{"track_id": "t1"}]}
    world.projections["OTHER_SENSOR"] = {"safe": True}
    calls = []
    runtime = {
        name: (lambda reason, name=name: calls.append((name, reason)))
        for name in ("invalidate_objective", "reset_navigation", "reset_camera",
                     "reset_commitment", "reset_map_search")
    }
    decision = policy.apply(InvalidationEvent.TELEPORT, world, runtime)

    assert decision.cancel_active and decision.clear_visual_context
    assert world.mouseover_screen_anchors == {}
    assert world.corpse_anchors == {}
    assert "WORLD3D" not in world.projections
    assert world.projections["OTHER_SENSOR"]["safe"] is True
    assert {name for name, _ in calls} == {
        "reset_navigation", "reset_camera", "reset_commitment", "reset_map_search"}


def test_objective_change_invalidates_selection_without_erasing_visual_context():
    policy = StateInvalidationPolicy()
    world = WorldModel()
    world.mouseover_screen_anchors["Creature-1"] = {"x": .5}
    calls = []
    decision = policy.apply(
        InvalidationEvent.OBJECTIVE_CHANGED, world,
        {"invalidate_objective": lambda reason: calls.append(reason)})
    assert decision.invalidate_objective and not decision.cancel_active
    assert world.mouseover_screen_anchors
    assert calls == ["OBJECTIVE_CHANGED"]


def test_agent_map_context_change_cancels_active_reach_and_clears_screen_anchors():
    value, executor = agent(
        "Menj oda", {"destination": {"map_id": 1609, "x": .7, "y": .5}})
    value.tick(agent_state(1, map_id=1609), 1)
    assert value.pending is not None
    value.world.mouseover_screen_anchors["Creature-1"] = {"x": .5, "y": .5}

    value.tick(agent_state(2, map_id=2175), 2)

    assert value.pending is None
    assert value.last_result["outcome"] == "CANCELLED"
    assert value.last_result["reason"] == "state_invalidated:map_context"
    assert value.world.mouseover_screen_anchors == {}
    assert executor.stops >= 1
