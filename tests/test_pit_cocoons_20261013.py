"""Live 2026-10-13 17:14-17:22 (Who Lurks in the Pit)."""
from wowbot.agent.goal_manager import GoalManager
from wowbot.agent.memory import AgentMemory
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.skills import SkillRegistry


def test_object_use_aborted_before_the_click_does_not_block_the_cocoons(tmp_path):
    """One identity_uncertain and two stale_observation aborts (no click)
    blocked OBJECT_USE for 120 s while a cocoon sat under the cursor."""
    manager = GoalManager(AgentMemory(tmp_path / "memory.sqlite3"))
    manager.set_goal(Goal.parse("Questelj egész nap", 1), 1)
    use = Proposal.make("OBJECT_USE", "cocoon", {"objective_id": "55639:0", "quest_ids": [55639]},
                        confidence=.8, priority=96)
    contracts = SkillRegistry().contracts
    assert manager.filter([use], contracts, 1)
    for at, reason in ((2, "identity_uncertain"), (3, "stale_observation"), (4, "stale_observation")):
        manager.outcome(use, False, reason, at)
    assert manager.filter([use], contracts, 5)
    # Real attempts (a click without credit) still escalate.
    for at in (6, 7, 8):
        manager.outcome(use, False, "quest_credit_not_received", at)
    assert manager.filter([use], contracts, 9) == []


QUEST = {"quest_id": 55639, "is_complete": False, "objectives": [
    {"description": "1/5 Trapped Expedition Member rescued from cocoons", "type": "INTERACT",
     "raw_type": "object", "current": 1, "required": 5, "is_complete": False}]}
SPAWNS = {"55639": {"spawn_candidates": [
    {"spawn_id": 8000025, "entity_kind": "GAMEOBJECT", "world_map_id": 2175, "x": 111.1, "y": -2217.9, "z": 33.},
    {"spawn_id": 8000024, "entity_kind": "GAMEOBJECT", "world_map_id": 2175, "x": 123.6, "y": -2238.9, "z": -5.9}]}}





def test_no_zone_sweep_while_a_yellow_objective_dot_shows_the_place():
    """User 17:31: the yellow dots mark the objectives; walk the zone only
    when none is shown (one may lie beyond the minimap edge)."""
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy()
    sweep = Proposal.make("SEEK_VISUAL_CUE", "zone", {"purpose": "SEARCH_LOCAL_OBJECTIVE_AREA",
                                                      "quest_id": 55639, "zone_sweep": True})
    dot_search = Proposal.make("SEEK_VISUAL_CUE", "dot", {"purpose": "SEARCH_LOCAL_OBJECT", "quest_id": 55639})
    state = {"monotonic_time": 10., "active_quests": [QUEST]}
    assert policy.drop_area_sweeps_while_dots([sweep, dot_search], state) == [sweep, dot_search]
    policy.dot_focus.remembered.append(["55639", 111., -2218., 9.])
    assert policy.drop_area_sweeps_while_dots([sweep, dot_search], state) == [dot_search]
    # A dot searched out without result no longer holds the sweep back.
    policy.dot_focus.exhausted.append(("55639", 111.5, -2217.))
    assert policy.drop_area_sweeps_while_dots([sweep, dot_search], state) == [sweep, dot_search]


def test_a_dot_move_the_navigation_reports_arrived_is_not_sent_again():
    """18:09 (pit bottom): the dot MOVE "arrived" without moving, 7 yd from
    the raw dot; the planner re-sent it ~90 times in 45 s."""
    from types import SimpleNamespace
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy()
    state = {"monotonic_time": 5., "active_quests": [QUEST], "map_id": 1409,
             "player_world_position": {"x": 92.3, "y": -2231.6, "instance_id": 2175}}
    policy.dot_focus.select(state, [(85.1, -2232.7, "55639")], x=92.3, y=-2231.6, now=5.)
    arrived = {"skill": "MOVE", "outcome": "SUCCESS", "reason": "reach_arrival_verified",
               "purpose": "APPROACH_MINIMAP_QUEST_DOT"}
    world = SimpleNamespace(state=state, runtime_context={"last_result": arrived})
    import wowbot.agent.quest_location_planning as module
    original = module.minimap_objective_dots
    module.minimap_objective_dots = lambda *_a, **_k: [(85.1, -2232.7, "55639")]
    try:
        assert policy.minimap_dot_move(world) is None
    finally:
        module.minimap_objective_dots = original
    assert policy.dot_focus.focus.search_started == 5.


def test_the_floor_walk_visits_the_tdb_spawns_in_route_order():
    """User 2026-10-13: the walk's route is the TDB spawns (+ the dots).
    On the real Hrun's pit mmap the order is 8000022 z60 -> 8000025 z33 ->
    8000023 z17 -> 8000026 z-1 -> 8000024 z-6 (top to bottom)."""
    from wowbot.navigation import NavigationService

    class Spiral:
        def find_path(self, instance_id, start, end):
            from types import SimpleNamespace
            # a straight descending ramp along +x: z = 100 - x
            anchors = tuple({"x": float(x), "y": 0., "z": 100.-x} for x in range(0, 101, 10))
            return SimpleNamespace(anchors=anchors, cost=100.)
    nav = NavigationService(navmesh=Spiral())
    state = {"player_world_position": {"x": 0., "y": 0., "instance_id": 2175}}
    targets = [{"x": 70., "y": 2., "z": 30., "hint": "low"}, {"x": 30., "y": -2., "z": 70., "hint": "high"}]
    hops = nav._sweep_hops(state, {"x": 100., "y": 0., "z": 0.}, targets)
    order = [hop.get("hint") for hop in hops if hop.get("target")]
    assert order == ["high", "low"]
    assert hops.index(next(h for h in hops if h.get("hint") == "high")) < hops.index(
        next(h for h in hops if h.get("hint") == "low"))


def test_the_floor_walk_targets_are_the_quests_object_spawns():
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy()
    state = {"active_quests": [QUEST], "player_world_position": {"instance_id": 2175},
             "reference_knowledge": {"quests": SPAWNS}}
    assert [t["hint"] for t in policy.floor_walk_targets(state, 55639)] == [
        "spawn:GAMEOBJECT:8000025", "spawn:GAMEOBJECT:8000024"]
    # z 33 and z -5.9: a multi-floor set (2026-10-14: no separate spawn MOVE).
    assert len(policy.multi_level_spawns(state, 55639)) == 2
