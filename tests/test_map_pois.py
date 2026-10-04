"""Map-API POIs: API quest givers and dungeon/raid entrances (user 2026-10-01).

"Quest ikonokat is tudnia kellene megtalálnia, meg dungeon entrance-eket,
raid entrance-eket": the addon exports ``map_pois`` from the Retail map APIs;
with no active quest the planner walks to the nearest available "!" giver on
the navmesh, and a DUNGEON goal walks to the Encounter Journal entrance.
"""
from types import SimpleNamespace

from adapters.telemetry_packets import normalize
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.map_poi_planning import (
    API_QUEST_GIVER_PURPOSE, INSTANCE_ENTRANCE_PURPOSE, MapPoiPlanningPolicy, entrance_kind)
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.planning_domains import DungeonDomain


def _quest(quest_id, x, y, *, instance=2175, name="q"):
    return {"quest_id": quest_id, "quest_name": name, "map_id": 1409, "x": .5, "y": .5,
            "source": "QUESTLINE_API",
            "world_position": {"x": x, "y": y, "instance_id": instance, "ui_map_id": 1409,
                               "coordinate_space": "WORLD_YARDS", "source": "C_MAP_WORLD_POS"}}


def _entrance(name, atlas, x, y, journal_id):
    return {"name": name, "atlas_name": atlas, "journal_instance_id": journal_id,
            "map_id": 1409, "x": .7, "y": .2, "source": "ENCOUNTER_JOURNAL_API",
            "world_position": {"x": x, "y": y, "instance_id": 2175, "ui_map_id": 1409,
                               "coordinate_space": "WORLD_YARDS"}}


def _world(**overrides):
    state = {"monotonic_time": 1., "active_quests": [], "is_in_combat": False,
             "player_world_position": {"x": 0., "y": 0., "z": 0., "instance_id": 2175},
             "map_pois": {"available_quests": [], "dungeon_entrances": [],
                          "taxi_nodes": [], "area_pois": []}}
    state.update(overrides)
    return SimpleNamespace(state=state, query=SimpleNamespace(instance=lambda: {}))


def test_transport_normalizes_empty_and_malformed_poi_lists():
    value = normalize({"map_pois": {"available_quests": {}, "dungeon_entrances": "bad",
                                    "taxi_nodes": [{"node_id": 1}, 3]}})
    assert value["map_pois"] == {"available_quests": [], "dungeon_entrances": [],
                                 "taxi_nodes": [{"node_id": 1}], "area_pois": []}
    assert normalize({"map_pois": "bad"})["map_pois"]["available_quests"] == []


def test_no_active_quest_moves_to_the_nearest_api_giver_on_the_navmesh():
    world = _world(map_pois={"available_quests": [
        _quest(1, 300., 0.), _quest(2, 120., 0.), _quest(3, 50., 0., instance=9999),
        {"quest_id": 4, "x": .5, "y": .5}]})
    moves = MapPoiPlanningPolicy().quest_giver_moves(world)
    assert [move.parameters["quest_id"] for move in moves] == [2, 1]
    first = moves[0]
    assert first.skill == "MOVE" and first.priority == MapPoiPlanningPolicy.QUEST_GIVER_PRIORITY
    assert first.parameters["purpose"] == API_QUEST_GIVER_PURPOSE
    assert first.parameters["require_navmesh"] is True
    assert first.parameters["coordinate_space"] == "WORLD_YARDS"
    assert (first.parameters["x"], first.parameters["instance_id"]) == (120., 2175)
    assert moves[1].priority < first.priority


def test_api_giver_is_ignored_with_an_active_quest_or_in_combat():
    pois = {"available_quests": [_quest(2, 120., 0.)]}
    policy = MapPoiPlanningPolicy()
    assert policy.quest_giver_moves(_world(map_pois=pois, active_quests=[{"quest_id": 9}])) == []
    assert policy.quest_giver_moves(_world(map_pois=pois, is_in_combat=True)) == []


def test_reached_giver_area_hands_over_to_local_search_and_is_revisited_later():
    policy = MapPoiPlanningPolicy()
    near = _world(map_pois={"available_quests": [_quest(2, 6., 0.), _quest(5, 200., 0.)]})
    # Inside the arrival radius: no MOVE to it, the next giver is offered.
    assert [m.parameters["quest_id"] for m in policy.quest_giver_moves(near)] == [5]
    far = _world(map_pois={"available_quests": [_quest(7, 120., 0.)]}, monotonic_time=10.)
    move = policy.quest_giver_moves(far)[0]
    policy.mark_reached(move.parameters, 20.)
    assert policy.quest_giver_moves(far, now=30.) == []
    later = 20. + MapPoiPlanningPolicy.REVISIT_SECONDS + 1.
    assert len(policy.quest_giver_moves(far, now=later)) == 1


def test_planner_prefers_the_api_giver_over_sweep_and_map_scan():
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    state = dict(session_id="test:pois", map_id=1609, target={}, active_quests=[],
                 world_map_open=False, monotonic_time=1., orientation=0., is_in_combat=False,
                 is_casting=False, state_age=0., position={"x": .5, "y": .5},
                 player_world_position={"x": 0., "y": 0., "z": 0., "instance_id": 2175},
                 map_pois={"available_quests": [_quest(55122, 140., 30., name="Murloc Mania")]})
    model = WorldModel()
    model.state, model.session_id = state, state["session_id"]
    planner, goal = Planner(SkillRegistry()), Goal.parse("Questelj", 1.)
    first = planner.candidates(goal, model, 1.)[0]
    assert first.skill == "MOVE" and first.parameters["purpose"] == API_QUEST_GIVER_PURPOSE
    assert first.parameters["quest_id"] == 55122
    # Once the local camera sweep is exhausted the API route still precedes
    # the World Map CV scan.
    planner.camera_search_step = 4
    assert planner.candidates(goal, model, 1.5)[0].parameters.get("purpose") == API_QUEST_GIVER_PURPOSE


def test_api_giver_route_yields_only_to_quest_symbol_evidence():
    attempt = SimpleNamespace(proposal=Proposal.make("MOVE", "api giver", {
        "purpose": API_QUEST_GIVER_PURPOSE, "x": 140., "y": 30., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS", "require_navmesh": True, "quest_id": 55122}))
    body = {"source": "WORLD3D", "track_id": "WORLD3D:43", "stable_frames": 40,
            "confidence": .9, "observed_at": 10., "lifecycle": "ACTIVE",
            "candidate_labels": ["learned_subject_like"], "appearance": {},
            "visual_relations": []}
    state = {"monotonic_time": 10.,
             "player_world_position": {"instance_id": 2175, "x": 10., "y": 20.},
             "visual_candidates": [body]}
    assert movement_visual_interrupt(attempt, state) is None
    state["visual_candidates"].append({**body, "track_id": "WORLD3D:52", "stable_frames": 5,
                                       "candidate_labels": ["quest_marker_like"]})
    handoff = movement_visual_interrupt(attempt, state)
    assert handoff is not None and handoff["track_id"] == "WORLD3D:52"


def test_entrance_kind_from_encounter_journal_atlas():
    assert entrance_kind({"atlas_name": "Raid"}) == "RAID"
    assert entrance_kind({"atlas_name": "Dungeon"}) == "DUNGEON"
    assert entrance_kind({"atlas_name": ""}) == "UNKNOWN"


def test_dungeon_goal_walks_to_the_named_or_matching_kind_entrance():
    pois = {"dungeon_entrances": [
        _entrance("Darkmaul Citadel", "Dungeon", 400., 0., 1234),
        _entrance("Molten Core", "Raid", 90., 0., 741)]}
    domain = DungeonDomain()
    named = domain.propose(_world(map_pois=pois), Goal.parse("Menj a Darkmaul Citadel dungeonba", 1.))
    assert [p.parameters["journal_instance_id"] for p in named] == [1234]
    assert named[0].parameters["purpose"] == INSTANCE_ENTRANCE_PURPOSE
    assert named[0].parameters["entrance_kind"] == "DUNGEON"
    raid = domain.propose(_world(map_pois=pois), Goal.parse("raid", 1.))
    assert [p.parameters["journal_instance_id"] for p in raid] == [741]
    dungeon = domain.propose(_world(map_pois=pois), Goal.parse("dungeon", 1.))
    assert [p.parameters["journal_instance_id"] for p in dungeon] == [1234]


def test_status_summarizes_poi_knowledge():
    state = {"map_pois": {"available_quests": [_quest(1, 1., 1.)],
                          "dungeon_entrances": [_entrance("Molten Core", "Raid", 1., 1., 741)]}}
    status = MapPoiPlanningPolicy.status(state)
    assert status["available_quests"] == 1 and status["taxi_nodes"] == 0
    assert status["instance_entrances"] == [
        {"name": "Molten Core", "kind": "RAID", "journal_instance_id": 741}]
