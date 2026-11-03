"""Nearby packet actor must not disappear behind a six-template TDB preview."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Goal, Observation
from wowbot.agent.packet_entity_facts import kill_objective_entries
from wowbot.agent.planner import Planner
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, objective_npc_entries
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from wowbot.agent.world import WorldModel
from test_talk_ride_credits_20261021 import unit

GUID = "Creature-0-3769-2444-47-193363-00005824C3"
ENTRIES = (187406, 190269, 191807, 191879, 191891, 193362, 193363, 193364, 193365, 193366)


def reference(description="Ask Sendrax about the Djaradin", *, known=True):
    def rows(query, params):
        if "WHERE name=?" in query:
            return [{"entry": entry, "name": "Sendrax"} for entry in ENTRIES] if known and params == ("Sendrax",) else []
        if "WHERE entry=?" in query:
            return [{"name": "Kill Credit: Start Escort [DNT]"}]
        if "WHERE length(name)" in query:
            return [{"entry": entry, "name": "Sendrax"} for entry in ENTRIES]
        return []
    result = {"quest_id": 65760, "template": {"VerifiedBuild": 69497},
        "objectives_text": "Meet commander Lethanak at the Dragonheart Outpost.",
        "objectives": [{"objective_id": 429426, "order": 2, "raw_type": 0,
            "credit_object_id": 193423, "description": description}]}
    return TDBKnowledgeProvider(SimpleNamespace(raw=SimpleNamespace(
        tables={"creature_template"}, rows=rows), quest=lambda _: deepcopy(result))).quest(65760)


def state():
    return {"monotonic_time": 100., "state_age": .3, "map_id": 2022,
        "server_mode": {"active": True}, "orientation": 0., "target": False,
        "soft_targets_sample_time": 100.,
        "player_world_position": {"x": 0., "y": 0., "z": 91., "z_known": True,
            "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
        "packet_entities": {GUID: unit(GUID, 10., 0., 3)},
        "soft_targets": [{"guid": GUID, "source_unit": "softinteract"}],
        "active_quests": [{"quest_id": 65760, "is_complete": False, "objectives": [
            {"description": "0/1 Commander Lethanak met outside of Dragonheart Outpost", "type": "KILL", "is_complete": False},
            {"description": "0/1 Ride any mount to reach Commander Lethanak (Optional)", "type": "KILL", "is_complete": False},
            {"description": "0/1 Ask Sendrax about the Djaradin (Optional)", "type": "KILL", "is_complete": False}]}],
        "reference_knowledge": {"quests": {"65760": reference()}}}


def test_ask_about_uses_all_exact_actor_templates_not_the_six_row_preview():
    (row,) = reference()["objectives"]
    assert len(row["named_creatures"]) == 6 and not any(n["entry"] == 193363 for n in row["named_creatures"])
    assert row["credit_action"] == "TALK"
    assert len(row["talk_creatures"]) == 10 and any(n["entry"] == 193363 for n in row["talk_creatures"])
    assert "193363" in objective_npc_entries(state())
    assert "193423" not in objective_npc_entries(state())
    assert kill_objective_entries(state()) == {}


@pytest.mark.parametrize("description", ["Ask Sendrax about the Djaradin", "Ask Sendrax regarding the Djaradin",
    "0/1 Ask Sendrax about the Djaradin (Optional)"])
def test_explicit_named_about_conversation_has_a_single_exact_actor(description):
    row = reference(description)["objectives"][0]
    assert row["credit_action"] == "TALK" and row["conversation_source"] == "TDB_OBJECTIVE_TEXT"


@pytest.mark.parametrize("description", ["Ask Someone Unknown about the Djaradin",
    "Ask Sendrax and Someone Else about the Djaradin", "Kill Sendrax near the Djaradin",
    "Supplies gathered near Sendrax", "The Djaradin slain"])
def test_unknown_ambiguous_and_non_conversation_text_cannot_create_a_talk_actor(description):
    assert "credit_action" not in reference(description)["objectives"][0]


def test_a_matching_generic_name_without_an_exact_template_lookup_does_not_authorize_talk():
    assert "credit_action" not in reference(known=False)["objectives"][0]


def test_the_existing_server_policy_walks_to_the_real_guid_xyz_and_faces_it():
    live = state()
    (proposal,) = ServerNpcInteractionPolicy().propose(live)
    assert proposal.skill == "MOVE"
    assert proposal.parameters["server_entity_guid"] == GUID
    assert proposal.parameters["npc_id"] == 193363
    assert proposal.parameters["coordinate_space"] == "WORLD_YARDS"
    assert proposal.parameters["x"] == 10. and proposal.parameters["z"] == 91.
    assert proposal.parameters["require_navmesh"] and proposal.parameters["face_on_arrival"]


def test_approach_hands_off_only_to_the_exact_ready_soft_recipient():
    live = state()
    live["packet_entities"][GUID]["position"]["x"] = 2.
    (proposal,) = ServerNpcInteractionPolicy().propose(live)
    assert proposal.skill == "INTERACT" and proposal.parameters["soft_guid"] == GUID
    live["soft_targets"][0]["guid"] = "Creature-0-3769-2444-47-999-00005824C3"
    assert ServerNpcInteractionPolicy().propose(live) == []


@pytest.mark.parametrize("bad", ["objective_complete", "quest_complete", "entity_removed", "no_entity"])
def test_completed_quests_or_missing_actors_do_not_keep_a_server_approach_alive(bad):
    live = state()
    if bad == "objective_complete":
        live["active_quests"][0]["objectives"][2]["is_complete"] = True
    elif bad == "quest_complete":
        live["active_quests"][0]["is_complete"] = True
    elif bad == "entity_removed":
        live["packet_entities"][GUID]["removed"] = True
    else:
        live["packet_entities"] = {}
    assert ServerNpcInteractionPolicy().propose(live) == []


def test_the_shared_planner_no_longer_returns_no_server_work_wait():
    live = state()
    world = WorldModel()
    world.ingest(Observation.create(live, 100.))
    world.state.update(live)
    proposal = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 100.)[0]
    assert proposal.skill == "MOVE" and proposal.parameters["server_entity_guid"] == GUID


def test_after_opening_the_exact_actor_the_quest_marked_gossip_path_still_applies():
    live = state()
    live["quest_ui"] = {"open": True, "npc_guid": GUID, "action": "", "gossip_options": [
        {"id": 1, "available": True, "name": "Tell me a story.", "x": .1, "y": .5},
        {"id": 2, "available": True, "name": "|cFF0000FF(Quest)|r Let us go!", "x": .1, "y": .6}]}
    proposal = QuestDialogPlanningPolicy._talk_gossip(live, True)
    assert proposal is not None and proposal.parameters["gossip_option_id"] == 2
    assert proposal.parameters["target_guid"] == GUID
