"""The live 3/4 stall: reacquire a fourth actor after packet-cache eviction."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_healing_quest_tool_20261022 import GUID, OTHER, actor, model, state
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.agent.planner import Planner
from wowbot.agent.quest_item_search import SEARCH_PURPOSE
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.skills import SkillRegistry
from wowbot.navigation.service import NavigationService


def search_state():
    st = state()
    st["player_world_position"].update(x=3509.7, y=-40.6, z=32.7)
    st["packet_entities"] = {}
    st["active_quests"][0]["objectives"][0].update(current=3, description="3/4 Injured drakonids healed")
    st["reference_knowledge"]["quests"]["65996"]["pois"] = [{
        "poi_id": "65996:0:1", "objective_id": 429945, "objective_index": 0,
        "world_map_id": 2444, "ui_map_id": 2022, "verified_build": 66384,
        "points": [{"x":3416., "y":-221., "z":31.}, {"x":3477., "y":-211., "z":38.},
                   {"x":3728., "y":270., "z":71.}, {"x":3523., "y":135., "z":36.}]}]
    st["quest_locations"] = [{"quest_id":65996, "map_id":2022, "world_position":{
        "coordinate_space":"WORLD_YARDS", "instance_id":2444, "x":3536., "y":-6.}}]
    return st


def proposal(st, domain=None):
    candidates = (domain or QuestDomain()).propose(model(st), Goal.parse("Questelj", 10.))
    return next(p for p in candidates if p.parameters.get("purpose") == SEARCH_PURPOSE)


def credit(domain, st, guid, position):
    st["packet_entities"][guid] = {**actor(guid), "position": {
        **position, "age":0., "source":"PACKET_CREATE_MOVEMENT"}}
    domain.note_object_interaction_result(
        {"skill":"USE_ON_TARGET", "outcome":"SUCCESS"}, st,
        {"guid":guid, "item_id":193917, "objective_id":"65996:0", "quest_ids":[65996],
         "purpose":"HEAL_QUEST_ITEM"})


def test_three_credited_sites_leave_the_fourth_tdb_site_searchable_after_cache_eviction():
    st, domain = search_state(), QuestDomain()
    for i, point in enumerate(((3519.35,-55.79,34.56), (3416.16,-220.63,32.57), (3477.13,-210.85,38.07))):
        credit(domain, st, f"healed-{i}", dict(zip(("x","y","z"), point)))
    st["packet_entities"] = {}  # departed actors no longer in the packet projection
    search = proposal(st, domain)
    assert not search.parameters.get("server_entity_guid")
    nav = NavigationProposalAdapter(NavigationService())
    next_point = nav._search_waypoint(search, SimpleNamespace(state=st), 10.)
    assert next_point.skill == "MOVE"
    assert (next_point.parameters["x"], next_point.parameters["y"], next_point.parameters["z"]) == (3523.,135.,36.)
    assert SkillRegistry().available(next_point, model(st))
    assert Planner.prefer_server_targets([search], server_mode=True) == [search]


def test_last_seen_server_location_survives_out_of_range_then_cache_eviction():
    domain, st = QuestDomain(), state()
    st["packet_entities"][GUID]["position"].update(x=10., y=135.)
    domain.propose(model(st), Goal.parse("Questelj", 10.))
    st["monotonic_time"] = 20.
    st["packet_entities"][GUID]["removed"] = {"reason":"OUT_OF_RANGE"}
    first = proposal(st, domain)
    st["monotonic_time"] = 100.
    st["packet_entities"] = {}
    second = proposal(st, domain)
    assert first.parameters["search_area"] == second.parameters["search_area"]
    assert second.parameters["search_area"]["coverage_points"] == [{"x":10.,"y":135.,"z":20.}]
    assert not second.parameters.get("guid") and not second.parameters.get("server_entity_guid")
    assert movement_visual_interrupt(SimpleNamespace(proposal=second), st, identity_only=True) is None


@pytest.mark.parametrize("change", ["session", "phase", "map", "instance", "expired"])
def test_last_seen_memory_is_context_and_time_bounded(change):
    domain, st = QuestDomain(), state()
    domain.propose(model(st), Goal.parse("Questelj", 10.))
    st["packet_entities"] = {}
    if change == "session": st["session_id"] = "another-character"
    elif change == "phase": st["phase"] = "another-phase"
    elif change == "map": st["map_id"] = 1409
    elif change == "instance": st["player_world_position"]["instance_id"] = 2175
    else: st["monotonic_time"] = 611.
    assert not [p for p in domain.propose(model(st), Goal.parse("Questelj", 10.))
                if p.parameters.get("purpose") == SEARCH_PURPOSE]


@pytest.mark.parametrize("change", ["complete", "wrong_map", "wrong_instance", "ambiguous", "mixed_build",
                                   "condition", "wrong_objective", "contradicting_poi"])
def test_tdb_search_is_bound_to_unfinished_objective_and_valid_context(change):
    st = search_state()
    poi = st["reference_knowledge"]["quests"]["65996"]["pois"][0]
    if change == "complete": st["active_quests"][0]["objectives"][0]["is_complete"] = True
    elif change == "wrong_map": poi["ui_map_id"] = 1409
    elif change == "wrong_instance": poi["world_map_id"] = 2175
    elif change == "ambiguous": poi["geometry_ambiguous"] = True
    elif change == "mixed_build": poi["geometry_mixed_build"] = True
    elif change == "condition": poi["conditions"] = {"PlayerConditionID":99}
    elif change == "wrong_objective": poi["objective_id"] = 430207
    else: st["quest_locations"][0]["world_position"].update(x=4500., y=-3000.)
    assert not [p for p in QuestDomain().propose(model(st), Goal.parse("Questelj", 10.))
                if p.parameters.get("purpose") == SEARCH_PURPOSE]


def test_finite_shared_coverage_keeps_individual_heights_and_does_not_restart_on_credit():
    st = search_state()
    search = proposal(st)
    adapter, world = NavigationProposalAdapter(NavigationService()), SimpleNamespace(state=st)
    visited = []
    for i in range(4):
        step = adapter._search_waypoint(search, world, 10.+i)
        assert step.skill == "MOVE"
        p = step.parameters
        visited.append((p["x"],p["y"],p["z"]))
        adapter.navigation.mark_search_cell_visited(p["search_region_id"],p["search_cell_id"],10.+i)
    assert len(set(visited)) == 4 and {p[2] for p in visited} == {31.,38.,71.,36.}
    exhausted = adapter._search_waypoint(search, world, 15.)
    assert exhausted.skill == "WAIT" and exhausted.parameters["blocked_reason"] == "OBJECTIVE_SEARCH_EXHAUSTED"
    st["active_quests"][0]["objectives"][0]["current"] = 2
    assert adapter._search_waypoint(proposal(st), world, 16.).skill == "WAIT"


def test_blocked_search_skips_cell_instead_of_using_unadapted_centroid():
    st, nav = search_state(), NavigationService()
    nav.permits = lambda *args: False
    adapter, world = NavigationProposalAdapter(nav), SimpleNamespace(state=st)
    search = proposal(st)
    first = adapter._search_waypoint(search, world, 10.)
    assert adapter.adapt(search,[search],world,11.).skill == "WAIT"
    assert adapter._search_waypoint(search,world,12.).parameters["search_cell_id"] != first.parameters["search_cell_id"]


def test_fresh_subject_interrupts_search_and_resumes_identity_checked_chain():
    st = search_state()
    search = proposal(st)
    st["packet_entities"][GUID] = {**actor(), "position": {
        "x":3522.61,"y":135.41,"z":36.99,"age":0.,"source":"PACKET_CREATE_MOVEMENT"}}
    handoff = movement_visual_interrupt(SimpleNamespace(proposal=search),st,identity_only=True)
    assert handoff["kind"] == "SERVER_ITEM_SUBJECT_AVAILABLE" and handoff["guid"] == GUID
    steps = QuestDomain().propose(model(st),Goal.parse("Questelj",10.))
    move = next(p for p in steps if p.parameters.get("server_entity_guid") == GUID)
    assert move.parameters["purpose"] == "APPROACH_ITEM_TARGET"
    assert move.parameters["face_on_arrival"] and not [p for p in steps if p.skill == "USE_ON_TARGET"]
    assert Planner.prefer_server_targets([search,move],server_mode=True) == [move]


def test_departed_actor_does_not_interrupt_search_as_if_it_were_still_live():
    st = search_state()
    search = proposal(st)
    st["packet_entities"][GUID] = {**actor(), "removed":{"reason":"OUT_OF_RANGE"}}
    assert movement_visual_interrupt(SimpleNamespace(proposal=search),st,identity_only=True) is None


@pytest.mark.parametrize("change", ["complete", "tool_changed", "other_objective"])
def test_stale_search_contract_cannot_reacquire_for_finished_or_different_work(change):
    st = search_state()
    search = proposal(st)
    st["packet_entities"][GUID] = actor()
    quest = st["active_quests"][0]
    if change == "complete": quest["objectives"][0]["is_complete"] = True
    elif change == "tool_changed": quest["special_item"]["item_id"] = 123
    else: quest["objectives"][0]["description"] = "Defend this area"
    assert movement_visual_interrupt(SimpleNamespace(proposal=search),st,identity_only=True) is None


def test_new_departing_animation_actor_is_deferred_without_transferring_guid_credit():
    domain, st = QuestDomain(), state(distance=2.)
    domain.propose(model(st),Goal.parse("Questelj",10.))
    credit(domain,st,GUID,{"x":0.,"y":2.,"z":20.})
    st["packet_entities"][GUID]["removed"] = {"reason":"OUT_OF_RANGE"}
    st["packet_entities"][OTHER] = actor(OTHER,2.)
    candidates = domain.propose(model(st),Goal.parse("Questelj",10.))
    assert not [p for p in candidates if p.skill == "TARGET"]
    visit = domain._quest_item_visits[(st["session_id"],"65996:0",OTHER)]
    assert "used_until" not in visit
    st["monotonic_time"] = 26.
    assert any(p.skill == "TARGET" and p.parameters["guid"] == OTHER
               for p in domain.propose(model(st),Goal.parse("Questelj",10.)))
