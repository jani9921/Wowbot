"""No unsupported hover handoff in server mode; keep exact soft-recipient F7."""
from types import SimpleNamespace

import pytest

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.server_mode import pointer_target
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from test_server_positions_20261020 import HENRY, turn_in_state


def route(**params):
    return SimpleNamespace(proposal=Proposal.make("MOVE", "turn-in route", {
        "purpose": "LOCATE_TURN_IN_REGION", "quest_id": 55881,
        "x": 40., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS", **params}))


def hovered_other_quest():
    live = turn_in_state(server_mode={"active": True}, packet_entities={},
        mouseover_sample_time=100., cursor_sample_time=100.,
        cursor_position={"nx": .5, "ny": .5},
        mouseover={"guid": "Creature-0-1-2175-1-333-1", "npc_id": 333,
                   "name": "A Vendor", "is_attackable": False})
    live["active_quests"].append({"quest_id": 42, "is_complete": False, "objectives": [
        {"description": "Buy a book from A Vendor", "is_complete": False}]})
    return live


@pytest.mark.parametrize("identity_only", [False, True])
def test_hover_of_another_quests_vendor_never_cancels_server_turnin_route(identity_only):
    live = hovered_other_quest()
    assert movement_visual_interrupt(route(), live, identity_only=identity_only) is None
    live["server_mode"]["active"] = False
    assert movement_visual_interrupt(route(), live, identity_only=identity_only)["kind"] == "OBJECTIVE_UNIT_HOVERED"


def test_minimap_zone_cannot_prematurely_finish_a_server_objective_route():
    live = hovered_other_quest()
    live["mouseover"] = {}
    live["visual_candidates"] = [{"source": "MINIMAP_CV", "kind": "minimap_quest_area",
        "quest_area": {"player_inside": True}, "view_radius_yards": 160.}]
    move = route(purpose="LOCATE_QUEST_OBJECTIVE_REGION", quest_id=42)
    assert movement_visual_interrupt(move, live) is None
    live["server_mode"]["active"] = False
    assert movement_visual_interrupt(move, live)["kind"] == "QUEST_ZONE_ENTERED"


def test_planner_and_dispatch_admission_reject_a_hover_dependent_target_in_server_mode():
    proposal = Proposal.make("TARGET", "mouseover", {"guid": HENRY, "x": .5, "y": .5,
        "ground_truth_handoff": True, "click_current_cursor": True})
    move = route().proposal
    assert pointer_target(proposal)
    assert Planner.prefer_server_targets([proposal, move], server_mode=True) == [move]
    assert Planner.prefer_server_targets([proposal, move]) == [proposal, move]
    world = WorldModel()
    world.ingest(Observation.create(turn_in_state(), 100.))
    world.state["server_mode"] = {"active": True}
    assert not SkillRegistry().available(proposal, world)


@pytest.mark.parametrize("activation", ["TAB_SERVER_GUID", "TAB_DEFEND", "TAB_FRIEND_RESCUE"])
def test_server_key_target_paths_are_not_mistaken_for_pointer_targeting(activation):
    proposal = Proposal.make("TARGET", "key selection", {"activation_source": activation, "guid": HENRY})
    assert not pointer_target(proposal)
    assert Planner.prefer_server_targets([proposal], server_mode=True) == [proposal]


def test_exact_server_ender_still_takes_the_route_and_interacts_with_verified_recipient():
    live = turn_in_state(server_mode={"active": True})
    live["player_world_position"]["x"] = 37.
    live["soft_targets"] = [{"guid": HENRY, "unit_type": "NPC", "source_unit": "softinteract"}]
    live["soft_targets_sample_time"] = 100.
    move = route(knowledge_priority="SERVER_LIVE", server_entity_guid=HENRY)
    handoff = movement_visual_interrupt(move, live, identity_only=True)
    assert handoff["kind"] == "SERVER_TURN_IN_INTERACTION_READY" and handoff["guid"] == HENRY
    (proposal,) = ServerNpcInteractionPolicy().propose(live)
    assert proposal.skill == "INTERACT" and proposal.parameters["soft_guid"] == HENRY
    live["soft_targets"][0]["guid"] = "Creature-0-1-2175-1-333-1"
    assert ServerNpcInteractionPolicy().propose(live) == []
    assert movement_visual_interrupt(move, live, identity_only=True) is None


def vendor_reference():
    description = "Buy Archeologist Artifact Notes from Cataloger Jakes"
    raw = SimpleNamespace(tables={"creature_template"}, rows=lambda query, params:
        [{"entry": 198846, "name": "Cataloger Jakes"}] if params == ("Cataloger Jakes",) else [])
    catalog = SimpleNamespace(raw=raw, quest=lambda quest_id: {
        "quest_id": quest_id, "template": {"VerifiedBuild": 69497},
        "objectives": [{"description": description, "raw_type": 14, "credit_object_id": 140806,
                        "objective_id": 432305}]})
    return TDBKnowledgeProvider(catalog).quest(72709)


def test_scripted_buy_names_exact_vendor_templates_without_hardcoding_entry():
    (objective,) = vendor_reference()["objectives"]
    assert objective["credit_action"] == "BUY" and objective["credit_kind"] == "OTHER"
    assert objective["named_creatures"] == [{"entry": 198846, "name": "Cataloger Jakes"}]


@pytest.mark.parametrize("bought", [False, True])
def test_buy_vendor_is_server_approached_and_f7d_only_while_purchase_still_open(bought):
    from test_talk_ride_credits_20261021 import unit
    vendor = "Creature-0-3769-2444-47-198846-00005824C4"
    reference = vendor_reference()
    live = {
        "monotonic_time": 100., "orientation": 0., "map_id": 2022,
        "player_world_position": {"x": 0., "y": 0., "z": 91., "instance_id": 2444},
        "active_quests": [{"quest_id": 72709, "is_complete": False, "objectives": [
            {"description": reference["objectives"][0]["description"], "is_complete": bought},
            {"description": "Read the Archeology Artifact Notes", "is_complete": False}]}],
        "reference_knowledge": {"quests": {"72709": reference}},
        "packet_entities": {vendor: unit(vendor, 3., 0., 0x83)},
        "soft_targets": [{"source_unit": "softinteract", "unit_type": "NPC", "guid": vendor}],
        "soft_targets_sample_time": 100.}
    proposals = ServerNpcInteractionPolicy().propose(live)
    if bought:
        assert proposals == []
    else:
        (proposal,) = proposals
        assert proposal.skill == "INTERACT" and proposal.parameters["soft_guid"] == vendor
        assert proposal.parameters["quest_id"] == "72709"
