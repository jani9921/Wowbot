"""Known server actor -> approach; unknown actor -> finite existing coverage."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_rescue_credit_identity_20261022 import state, GUID
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Proposal
from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.agent.planner import Planner
from wowbot.agent.rescue_object_planning import RescueTargetPolicy, SoftInteractRescuePolicy
from wowbot.navigation.service import NavigationService


def search_state():
    st = state()
    st.update(session_id="test:rescue", server_mode={"active": True}, packet_entities={})
    st["player_world_position"].update(x=3070., y=-878., z=34., sample_time=100.)
    row = st["reference_knowledge"]["quests"]["65990"]["objectives"][0]
    row.update(objective_id=427775, order=0)
    st["reference_knowledge"]["quests"]["65990"]["pois"] = [{
        "poi_id": "65990:0:1", "world_map_id": 2444, "ui_map_id": 2022,
        "objective_id": 427775, "objective_index": 0, "verified_build": 66384,
        "points": [{"x":2997.,"y":-1040.,"z":36.}, {"x":3071.,"y":-872.,"z":39.},
                   {"x":2962.,"y":-919.,"z":35.}, {"x":2892.,"y":-1008.,"z":62.}]}]
    return st


def test_the_recorded_85_yard_actor_is_not_discarded_by_a_70_yard_hint_limit():
    st = state()
    st["player_world_position"].update(x=2984.9492, y=-954.6731, z=31.9873)
    st["packet_entities"][GUID]["position"].update(x=2997.6702, y=-1039.5938, z=36.5990)
    proposal, = RescueTargetPolicy().propose(st)
    assert proposal.skill == "MOVE" and proposal.parameters["server_entity_guid"] == GUID
    assert proposal.parameters["purpose"] == "APPROACH_RESCUE_NPC"


def test_a_soft_hint_and_old_near_flag_at_8_yards_do_not_cancel_approach_or_press_f7():
    st = state()
    st["player_world_position"].update(x=2989.1567, y=-1039.7213, z=36.1876)
    st["packet_entities"][GUID]["position"].update(x=2997.6702, y=-1039.5938, z=36.5990)
    st["soft_targets"] = [{"source_unit":"softinteract","guid":GUID,"npc_id":194231}]
    st["target"] = {"guid":GUID,"npc_id":194231,"interact_near":True}
    assert SoftInteractRescuePolicy().propose(st) == []
    approach, = RescueTargetPolicy().propose(st)
    assert approach.skill == "MOVE"
    assert movement_visual_interrupt(SimpleNamespace(proposal=approach), st, identity_only=True) is None


def test_a_near_airborne_soft_recipient_is_not_rejected_just_for_vertical_separation():
    st = state()
    p = st["packet_entities"][GUID]["position"]
    st["player_world_position"].update(x=p["x"]-2.,y=p["y"],z=p["z"]-8.)
    st["soft_targets"] = [{"source_unit":"softinteract","guid":GUID,"npc_id":194231}]
    press, = SoftInteractRescuePolicy().propose(st)
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == GUID


def test_missing_actors_propose_mmap_search_hints_not_combat_or_visual_search():
    proposal, = RescueTargetPolicy().propose(search_state())
    assert proposal.skill == "MOVE" and proposal.parameters["purpose"] == "SEARCH_RESCUE_OBJECTIVE"
    assert not proposal.parameters.get("server_entity_guid")
    assert {p["z"] for p in proposal.parameters["search_area"]["coverage_points"]} == {35.,36.,39.,62.}
    assert Planner.prefer_server_targets([proposal],server_mode=True) == [proposal]
    actor = Proposal.make("MOVE","server",{"server_entity_guid":GUID})
    assert Planner.prefer_server_targets([proposal,actor],server_mode=True) == [actor]


@pytest.mark.parametrize("change",["complete","wrong_map","wrong_instance","ambiguous","condition","wrong_objective","conflicting_objective_id","contradicting_poi"])
def test_reference_hints_require_an_open_matching_same_context_objective(change):
    st = search_state()
    poi = st["reference_knowledge"]["quests"]["65990"]["pois"][0]
    if change == "complete": st["active_quests"][0]["objectives"][0]["is_complete"] = True
    elif change == "wrong_map": poi["ui_map_id"] = 1409
    elif change == "wrong_instance": poi["world_map_id"] = 2175
    elif change == "ambiguous": poi["geometry_ambiguous"] = True
    elif change == "condition": poi["conditions"] = {"PlayerConditionID":99}
    elif change == "wrong_objective": poi.update(objective_id=123,objective_index=32)
    elif change == "conflicting_objective_id": poi["objective_id"] = 123
    else: st["quest_locations"] = [{"quest_id":65990,"map_id":2022,"world_position":{
        "coordinate_space":"WORLD_YARDS","instance_id":2444,"x":4000.,"y":-3000.}}]
    assert RescueTargetPolicy().propose(st) == []


def test_coverage_visits_points_once_and_keeps_their_individual_floor():
    st = search_state()
    proposal, = RescueTargetPolicy().propose(st)
    nav, world = NavigationService(), SimpleNamespace(state=st)
    adapter = NavigationProposalAdapter(nav)
    visited = []
    for index in range(4):
        next_point = adapter._search_waypoint(proposal,world,100.+index)
        assert next_point.skill == "MOVE" and next_point.parameters["require_navmesh"] is True
        p = next_point.parameters
        visited.append((p["x"],p["y"],p["z"]))
        nav.mark_search_cell_visited(p["search_region_id"],p["search_cell_id"],100.+index)
    assert len(set(visited)) == 4 and max(p[2] for p in visited) == 62.
    assert adapter._search_waypoint(proposal,world,105.).skill == "WAIT"


def test_search_retires_a_failed_cell_once_and_stops_at_its_time_budget():
    st = search_state()
    proposal, = RescueTargetPolicy().propose(st)
    adapter = NavigationProposalAdapter(NavigationService())
    world = SimpleNamespace(state=st)
    first = adapter._search_waypoint(proposal,world,100.)
    failure = {"action_id":"failed-cell","purpose":"SEARCH_RESCUE_OBJECTIVE","outcome":"FAILURE"}
    second = adapter._search_waypoint(proposal,world,101.,last_result=failure)
    assert first.parameters["search_cell_id"] != second.parameters["search_cell_id"]
    assert adapter._search_waypoint(proposal,world,102.,last_result=failure).key == second.key
    assert adapter._search_waypoint(proposal,world,341.,last_result=failure).skill == "WAIT"


def test_search_yields_to_a_new_server_actor_without_claiming_arrival():
    st = search_state()
    proposal, = RescueTargetPolicy().propose(st)
    fresh = state()
    fresh.update(server_mode={"active":True})
    handoff = movement_visual_interrupt(SimpleNamespace(proposal=proposal),fresh,identity_only=True)
    assert handoff["kind"] == "SERVER_RESCUE_ENTITY_AVAILABLE" and handoff["guid"] == GUID


def test_a_blocked_search_cell_never_falls_back_to_the_unadapted_centroid():
    st = search_state()
    proposal, = RescueTargetPolicy().propose(st)
    nav = NavigationService()
    nav.permits = lambda *args: False
    adapter = NavigationProposalAdapter(nav)
    world = SimpleNamespace(state=st)
    before = adapter._search_waypoint(proposal,world,100.)
    blocked = adapter.adapt(proposal,[proposal],world,101.)
    assert blocked.skill == "WAIT"
    after = adapter._search_waypoint(proposal,world,102.)
    assert after.parameters["search_cell_id"] != before.parameters["search_cell_id"]


def test_coverage_does_not_count_the_floor_below_as_visited():
    nav = NavigationService()
    region = {"x":10.,"y":20.,"map_id":2022,"instance_id":2444,"coordinate_space":"WORLD_YARDS",
              "coverage_points":[{"x":10.,"y":20.,"z":60.}],"visit_radius":6.}
    nav.begin_search_region("floors",region)
    st = {"monotonic_time":100.,"player_world_position":{"x":10.,"y":20.,"z":35.,
        "z_observed":True,"sample_time":100.,"instance_id":2444}}
    nav.observe_search_region("floors",st,100.,target_detected=False)
    assert nav.next_search_waypoint("floors",st)["z"] == 60.
    st["player_world_position"]["z"] = 60.
    nav.observe_search_region("floors",st,100.,target_detected=False)
    assert nav.next_search_waypoint("floors",st) is None
