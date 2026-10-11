"""Live 2026-10-11 15:52-15:59: Hjalmar turn-in, follow-up, Bjorn at the pit.

* 58914 was turned in at Hjalmar, the window closed and the follow-up 58915
  (also Hjalmar's) was not taken; a turn-in MOVE chosen a moment before the
  turn-in kept walking away for 35 s.
* The 55965 ender Bjorn stands at the pit entrance (TDB z 94.8); the learned
  ender spot had no height and the route went down into the cave.
"""
from types import SimpleNamespace

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Proposal
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.tdb_locations import role_region

HJALMAR = {"guid": "Creature-0-3769-2175-157555-162943-00004B6F4C", "name": "Hjalmar the Undying",
           "attackable": False}
QUEST = {"quest_id": 58914, "is_complete": True, "objectives": []}


def _state(t, *, open_=False, action="", quests=(QUEST,), target=HJALMAR, **extra):
    return {"monotonic_time": t, "target": dict(target), "active_quests": list(quests),
            "quest_ui": {"open": open_, "action": action, "quest_id": 58914 if action else 0,
                         "entries": []},
            "quest_ui_open": open_, "quest_ui_action": action, **extra}


def test_turned_in_npc_is_spoken_to_once_more_for_a_follow_up():
    policy = QuestDialogPlanningPolicy()
    policy.propose(_state(1., open_=True, action="COMPLETE"), None)
    # Still in the log for a moment: nothing yet.
    assert not [p for p in policy.propose(_state(1.5), None) if p.skill == "INTERACT"]
    talk = [p for p in policy.propose(_state(2., quests=()), None) if p.skill == "INTERACT"]
    assert talk and talk[0].parameters["guid"] == HJALMAR["guid"]
    # The window opened again: done, no second re-talk.
    policy.propose(_state(3., open_=True, quests=()), None)
    assert not [p for p in policy.propose(_state(4., quests=()), None) if p.skill == "INTERACT"]


def test_no_follow_up_talk_when_the_npc_offers_the_next_quest_itself_or_time_ran_out():
    policy = QuestDialogPlanningPolicy()
    policy.propose(_state(1., open_=True, action="COMPLETE"), None)
    policy.propose(_state(1.5, open_=True, action="ACCEPT", quests=()), None)
    assert not [p for p in policy.propose(_state(3., quests=()), None) if p.skill == "INTERACT"]
    late = QuestDialogPlanningPolicy()
    late.propose(_state(1., open_=True, action="COMPLETE"), None)
    assert not [p for p in late.propose(_state(30., quests=()), None) if p.skill == "INTERACT"]


def test_turn_in_walk_stops_when_the_quest_left_the_log():
    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "Leadási hely mmap útvonalon", {
            "purpose": "LOCATE_TURN_IN_REGION", "quest_id": 58914, "x": 0., "y": 0.,
            "coordinate_space": "WORLD_YARDS", "instance_id": 2175}))
    gone = movement_visual_interrupt(attempt, {"active_quests": [], "monotonic_time": 1.})
    assert gone == {"reason": "turn_in_quest_left_log", "kind": "QUEST_LEFT_LOG"}
    assert movement_visual_interrupt(attempt, {"active_quests": [QUEST], "monotonic_time": 1.}) is None


def test_learned_ender_spot_borrows_the_tdb_spawn_height():
    reference = {
        "learned": [{"kind": "QUEST_ROLE", "role": "QUEST_ENDER", "confirmed_historical": True,
                     "npc_id": 156891, "observer_position": {
                         "x": 102.34, "y": -2251.53, "instance_id": 2175}}],
        "spawn_candidates": [{"role": "QUEST_ENDER", "entry": 156891, "x": 89.684, "y": -2249.26,
                              "z": 94.7782, "world_map_id": 2175}]}
    state = {"map_id": 1409, "reference_knowledge": {"quests": {"55965": reference}},
             "player_world_position": {"x": 60., "y": -2300., "instance_id": 2175,
                                       "coordinate_space": "WORLD_YARDS"}}
    where = role_region(state, 55965, "QUEST_ENDER")
    assert where["z_known"] is True and abs(where["z"]-94.7782) < .01
    assert (where["x"], where["y"]) == (102.34, -2251.53)


def _planner_world(t, sample):
    from wowbot.agent.models import Observation
    from wowbot.agent.world import WorldModel
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": t, "frame_id": f"f{t}", "monotonic_time": t, "map_id": 1409,
        "orientation": 0., "position": {"x": .5, "y": .5}, "player_present": True,
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [], "world_map_open": False, "target": dict(HJALMAR),
        "quest_ui": {"open": True, "action": "", "quest_id": 0, "entries": []},
        "quest_ui_open": True, "state_sample_time": sample}, t))
    return world


def test_an_npc_window_that_stays_empty_is_closed_with_escape():
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    planner, goal = Planner(SkillRegistry()), Goal.parse("Questelj", 1.)
    assert [p.skill for p in planner.candidates(goal, _planner_world(1., 1.), 1.)] == ["WAIT"]
    # Six seconds later, with a full snapshot taken while it was open: close it.
    late = planner.candidates(goal, _planner_world(7.5, 7.), 7.5)
    assert [p.skill for p in late] == ["CLOSE_DIALOG"]
    commands = planner.registry.commands(late[0], _planner_world(7.5, 7.)) \
        if hasattr(planner.registry, "commands") else None
    if commands is not None:
        assert [c.binding for c in commands] == ["TOGGLEGAMEMENU"]


def test_selected_ender_outranks_the_turn_in_area_search():
    """Live 15:46: Jaina (56034 ender) was selected; the turn-in SEEK (70 +
    reliability) beat INTERACT (70) for 25 s."""
    from wowbot.agent.models import Goal, Observation
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    jaina = {"guid": "Creature-0-3769-2175-157555-156280-00004B6F4C", "name": "Lady Jaina Proudmoore",
             "npc_id": 156280, "unit_type": "NPC", "attackable": False, "dead": False}
    world = WorldModel()
    world.__dict__["quest_turn_in"] = {"56034": {"name": "Lady Jaina Proudmoore", "source": "QUEST_API"}}
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f1", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .5, "y": .5}, "player_present": True,
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [{"quest_id": 56034, "is_complete": True, "objectives": [
            {"description": "3/3 Re-Sizer v9.0.1 tested on Wandering Boars", "is_complete": True}]}],
        "world_map_open": False, "target": jaina}, 1.))
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    talk = [p for p in proposals if p.skill == "INTERACT" and p.parameters.get("guid") == jaina["guid"]]
    assert talk and talk[0].priority >= 90
    assert proposals[0].skill == "INTERACT"


def test_no_world_map_while_riding_a_vehicle():
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    from wowbot.agent.models import Observation
    def world(in_vehicle):
        w = WorldModel()
        w.ingest(Observation.create({
            "session_id": "s", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
            "orientation": 0., "position": {"x": .5, "y": .5}, "player_present": True,
            "world_map_open": False, "in_vehicle": in_vehicle}, 1.))
        return w
    proposal = Proposal.make("OPEN_MAP", "test", {"map_id": 1409})
    assert SkillRegistry().available(proposal, world(False))
    assert not SkillRegistry().available(proposal, world(True))


def test_no_world_map_over_an_open_npc_or_vendor_window():
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    from wowbot.agent.models import Observation
    def world(**extra):
        w = WorldModel()
        w.ingest(Observation.create({
            "session_id": "s", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
            "orientation": 0., "position": {"x": .5, "y": .5}, "player_present": True,
            "world_map_open": False, **extra}, 1.))
        return w
    proposal = Proposal.make("OPEN_MAP", "test", {"map_id": 1409})
    assert SkillRegistry().available(proposal, world())
    assert not SkillRegistry().available(proposal, world(quest_ui={"open": True}, quest_ui_open=True))
    assert not SkillRegistry().available(proposal, world(vendor_ui={"open": True}))


def test_map_is_not_opened_while_a_quest_place_is_known_or_right_after_a_turn_in():
    from wowbot.agent.map_search_planning import WorldMapFallbackPolicy
    policy = WorldMapFallbackPolicy.__new__(WorldMapFallbackPolicy)
    known = {"active_quests": [{"quest_id": 58914, "is_complete": True}],
             "quest_locations": [{"quest_id": 58914, "world_position": {
                 "x": 1., "y": 2., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}]}
    assert WorldMapFallbackPolicy._quest_place_known(known)
    assert not WorldMapFallbackPolicy._quest_place_known({**known, "active_quests": []})
    # The log changed at t=10; the snapshot is still from before it.
    base = {"active_quests": [{"quest_id": 1}], "quest_state_revision": "a",
            "monotonic_time": 5., "state_sample_time": 5.}
    assert not policy._quest_change_settling(base, 5.)
    after = {**base, "active_quests": [], "quest_state_revision": "b", "monotonic_time": 10.,
             "state_sample_time": 9.8}
    assert policy._quest_change_settling(after, 10.)
    assert not policy._quest_change_settling({**after, "monotonic_time": 11., "state_sample_time": 10.6}, 11.)
    assert not policy._quest_change_settling({**after, "monotonic_time": 17.}, 17.)


def test_unrelated_selected_friendly_does_not_freeze_the_search():
    """Live 15:50:53-15:51:03: Jaina stayed selected with nothing to do for
    Stocking Up; every search waited for "no target" -- 11 s of WAIT."""
    from types import SimpleNamespace
    from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy
    jaina = {"guid": "Creature-0-1-2175-1-156280-1", "name": "Lady Jaina Proudmoore",
             "attackable": False, "npc_id": 156280}
    world = SimpleNamespace(state={"target": jaina, "is_in_combat": False},
                            runtime_context={})
    irrelevant = VisualSearchPlanningPolicy._irrelevant_selection
    assert irrelevant(world, jaina, [], [])
    # Something else to do, an objective naming her, or a proposal about her: kept.
    assert not irrelevant(world, jaina, [], [Proposal.make("OPEN_MAP", "m", {})])
    assert not irrelevant(world, jaina, ["obj"], [])
    assert not irrelevant(world, jaina, [], [Proposal.make("INTERACT", "i", {"guid": jaina["guid"]})])
