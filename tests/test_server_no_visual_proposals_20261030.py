"""REV4 visual retirement step 2 (user 2026-10-30): the SERVER composition builds
no screen/map/camera search proposals; before, they were built and then
filtered, and the never-opened map kept the TDB fallbacks switched off."""
from types import SimpleNamespace

import pytest

from wowbot.agent.escort_follow import EscortFollowPolicy
from wowbot.agent.map_search_planning import WorldMapFallbackPolicy
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.server_mode import server_profile
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel

REFERENCE = {"source": "TDB_REFERENCE", "role_hypothesis": "QUEST_STARTER", "spawn_ids": [9],
             "npc_ids": [156626], "quest_ids": [54951], "world_map_id": 2175, "x": 10., "y": 20.,
             "z": 2., "distance_yards": 12., "coordinate_space": "WORLD_YARDS",
             "identity_confirmed": False}


def world(*, server=True, **extra):
    model = WorldModel()
    model.ingest(Observation.create({
        "session_id": "test:player", "timestamp": 1., "frame_id": "f1", "map_id": 1409,
        "world_map_open": False, "position": {"x": .5, "y": .5}, "orientation": 0.,
        "player_present": True, "is_in_combat": False, "is_casting": False, "target": {},
        "active_quests": [], **extra}, 1.))
    if server:
        model.state["runtime_profile"] = "SERVER"
    return model


def test_the_profile_marker_is_explicit():
    assert server_profile({"runtime_profile": "SERVER"})
    assert not server_profile({}) and not server_profile({"runtime_profile": "LEGACY_VISION"})


def test_server_map_step_counts_as_done_and_the_tdb_fallback_is_allowed():
    policy, quest, goal = WorldMapFallbackPolicy(), QuestDomain(), Goal.parse("Questelj", 1.)
    model = world(quest_role_reference_candidates=[REFERENCE])
    assert policy.pre_domain_proposals(goal, model, 1., registry=SkillRegistry(), quest=quest,
                                       inspections=lambda *a: pytest.fail("no map CV")) is None
    assert policy.state.exhausted is True and quest.allow_db_fallback is True
    proposals: list[Proposal] = []
    policy.add_quest_fallbacks(proposals, goal, model, 2., blocked_until={})
    assert [p.skill for p in proposals] == ["REACH_LOCATION"]          # never OPEN_MAP first
    assert proposals[0].parameters["purpose"] == "INSPECT_REFERENCE_LOCATION"


def test_the_legacy_profile_keeps_its_map_order():
    policy, goal = WorldMapFallbackPolicy(), Goal.parse("Questelj", 1.)
    proposals: list[Proposal] = []
    policy.add_quest_fallbacks(proposals, goal, world(server=False, quest_role_reference_candidates=[REFERENCE]),
                               1., blocked_until={})
    assert [p.skill for p in proposals] == ["OPEN_MAP"]


def test_an_open_world_map_is_closed_without_a_cv_scan_in_server():
    policy, quest = WorldMapFallbackPolicy(), QuestDomain()
    model = world(world_map_open=True, active_quests=[{"quest_id": 1, "objectives": []}])
    registry = SimpleNamespace(available=lambda proposal, _world: True)
    result = policy.pre_domain_proposals(Goal.parse("Questelj", 1.), model, 1., registry=registry,
                                         quest=quest, inspections=lambda *a: pytest.fail("no map CV"))
    assert [p.skill for p in result] == ["CLOSE_MAP"] and quest.allow_db_fallback is True


def test_server_planner_builds_no_inspection_or_visual_search():
    planner = Planner(SkillRegistry())
    model = world()
    assert planner.inspections(model, 1., goal=Goal.parse("Questelj", 1.)) == []

    def forbidden(*args, **kwargs):
        raise AssertionError("visual search must not run in the SERVER composition")
    planner.visual_search_policy.propose = forbidden
    planner.visual_inspection_policy.propose = forbidden
    proposals = planner.candidates(Goal.parse("Questelj", 1.), model, 1.)
    assert not any(planner.vision_driven(p) for p in proposals)


def test_escort_without_a_screen_entity_does_not_ask_for_a_visual_reacquire():
    objective = SimpleNamespace(target_entity={"name": "Inconspicuous Wagon"}, objective_id="65793:2",
                                confidence=.8, type="ESCORT")
    record = SimpleNamespace(quest_id=65793)
    assert EscortFollowPolicy().propose(objective, record, {"runtime_profile": "SERVER"}) == []
    (legacy,) = EscortFollowPolicy().propose(objective, record, {})
    assert legacy.skill == "SEEK_VISUAL_CUE"


def test_a_far_quest_item_target_is_walked_to_by_its_world_position_in_server():
    from wowbot.agent.quest_objective_planning import QuestObjectivePlanningMixin
    planner = QuestObjectivePlanningMixin.__new__(QuestObjectivePlanningMixin)
    planner.VISUAL_INTERACTION_HEIGHT = .2
    target = {"guid": "Creature-0-1-2-3-4-5",
              "screen_position": {"x": .5, "y": .5, "sample_time": 10., "track_id": "t1"},
              "world_position": {"x": 10., "y": 20., "coordinate_space": "WORLD_YARDS",
                                 "instance_id": 2444, "source": "PACKET_ENTITY"}}
    obj = SimpleNamespace(target_object={"item_id": 7}, objective_id="1:0")
    record = SimpleNamespace(quest_id=1)
    move = planner._item_target_approach({"runtime_profile": "SERVER", "map_id": 2022}, target, obj, record, 1, 10.)
    assert move.skill == "MOVE" and move.parameters["purpose"] == "APPROACH_ITEM_TARGET"
    legacy = planner._item_target_approach({"map_id": 2022}, target, obj, record, 1, 10.)
    assert legacy.skill == "VISUAL_APPROACH"


# Pure visual modules (built only for LEGACY_VISION or bypassed as a whole in
# SERVER) and helpers whose single caller is gated.
WHOLE_MODULE = {"wowbot/agent/visual_search_planning.py", "wowbot/agent/visual_inspection_planning.py",
                "wowbot/agent/map_search_planning.py"}
GATED_BY_CALLER = {
    ("wowbot/agent/entity_objective_flows.py", "propose_local_search"),
    ("wowbot/agent/object_interaction_flow.py", "propose_local_search"),
    ("wowbot/agent/travel_reach_fallback.py", "propose"),
    ("wowbot/agent/quest_location_planning.py", "turn_in_search"),
    ("wowbot/agent/quest_location_planning.py", "_minimap_dot_local_search"),
    ("wowbot/agent/escort_follow.py", "reacquire"),
    ("wowbot/agent/navigation_situation.py", "adapt"),          # returns early on server_mode_selected
}
VISUAL = {"SEEK_VISUAL_CUE", "VISUAL_APPROACH", "INSPECT", "OPEN_MAP", "REACQUIRE_TARGET", "CAMERA_CONTROL"}


def test_every_visual_proposal_producer_is_server_gated():
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src"
    ungated = []
    for path in sorted((src / "wowbot/agent").rglob("*.py")):
        relative = path.relative_to(src).as_posix()
        if relative in WHOLE_MODULE:
            continue
        text = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            makes = [n for n in ast.walk(function) if isinstance(n, ast.Call)
                     and getattr(n.func, "attr", None) == "make" and n.args
                     and isinstance(n.args[0], ast.Constant) and n.args[0].value in VISUAL]
            if not makes or (relative, function.name) in GATED_BY_CALLER:
                continue
            body = ast.get_source_segment(text, function) or ""
            if "server_profile(" not in body and "server_mode_selected(" not in body:
                ungated.append(f"{relative}:{function.name}")
    assert ungated == []
