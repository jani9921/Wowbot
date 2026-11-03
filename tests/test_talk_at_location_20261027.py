"""66049: a place suffix and a nameless TDB role hid the current Wrathion."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.conversation_actors import conversation_actors
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.quest_semantics import talk_to_subject
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider


GUID = "Creature-0-1461-2534-147807-187045-000060A8EF"
DESCRIPTION = "Speak with Wrathion at the Oathstone"


@pytest.mark.parametrize("text,name", [
    ("0/1 Speak with Wrathion at the Oathstone", "wrathion"),
    ("Talk to Captain Example near the gate", "captain example"),
    ("Meet Sendrax outside the camp", "sendrax"),
    ("Speak to Lady Example inside the cave", "lady example"),
    ("Speak with Marshal Dughan about the ritual", "marshal dughan"),
    ("Report to Keeper of the Grove", "keeper of the grove"),
])
def test_talk_subject_separates_the_location_from_the_npc_name(text, name):
    assert talk_to_subject({"description": text}) == name


def provider():
    source = {"quest_id": 66049, "template": {}, "objectives": [],
              "quest_roles": [{"npc_id": 187045, "quest_id": 66049, "role": "QUEST_ENDER",
                               "verified_build": 56513}]}
    lookups = []

    def npc(entry):
        lookups.append(entry)
        return {"npc_id": entry, "name": "Wrathion"}

    catalog = SimpleNamespace(raw=None, quest=lambda qid: source, npc=npc)
    return TDBKnowledgeProvider(catalog), source, lookups


def state():
    tdb, _, _ = provider()
    reference = tdb.quest(66049)
    reference["objectives"] = [{"description": DESCRIPTION,
        "credit_kind": "CREATURE_CREDIT", "credit_object_id": 190684,
        "credit_name": "[DNT] Kill Credit", "named_creatures": [
            {"entry": 57767, "name": "Wrathion"}, {"entry": 57777, "name": "Wrathion"}]}]
    return {"session_id": "test:oathstone", "monotonic_time": 100., "map_id": 2022,
        "orientation": 0., "is_in_combat": False, "target": False, "mouseover": False,
        "quest_ui": {"open": False}, "soft_targets_sample_time": 100.,
        "soft_targets": [{"guid": GUID, "source_unit": "softinteract"}],
        "player_world_position": {"x": 0., "y": 0., "z": 174., "z_known": True, "instance_id": 2444},
        "active_quests": [{"quest_id": 66049, "is_complete": False, "objectives": [
            {"description": "0/1 "+DESCRIPTION, "current": 0, "required": 1, "is_complete": False}]}],
        "reference_knowledge": {"quests": {"66049": reference}},
        "packet_entities": {GUID: {"guid": GUID, "entry_id": 187045, "kind": "CREATURE",
            "map_id": 2444, "info": {"npc_flags": 3},
            "position": {"x": 4.01, "y": 0., "z": 174., "source": "PACKET_CREATE_MOVEMENT"}}}}


def test_exact_role_name_is_enriched_once_without_mutating_catalogue_records():
    tdb, original, lookups = provider()
    result = tdb.quest(66049)
    assert result["quest_roles"][0]["name"] == "Wrathion"
    assert "name" not in original["quest_roles"][0]
    tdb.quest(66049)
    assert lookups == [187045]  # cached with the quest, no per-frame SQL


def test_explicit_existing_role_name_is_preserved():
    tdb, original, lookups = provider()
    original["quest_roles"][0]["name"] = "Known catalogue name"
    assert tdb.quest(66049)["quest_roles"][0]["name"] == "Known catalogue name"
    assert lookups == []


def test_current_server_actor_is_talked_to_without_a_hover_or_selected_target():
    payload = state()
    before = deepcopy(payload)
    assert conversation_actors(payload, 66049)[0]["entry"] == 187045
    (interact,) = ServerNpcInteractionPolicy().propose(payload)
    assert interact.skill == "INTERACT"
    assert interact.parameters["npc_id"] == 187045
    assert interact.parameters["soft_guid"] == GUID
    assert interact.parameters["activation_source"] == "SOFT_INTERACT"
    assert payload == before


@pytest.mark.parametrize("change", ["removed", "wrong_map", "done", "wrong_name"])
def test_role_name_never_overrides_current_actor_or_objective_evidence(change):
    payload = state()
    if change == "removed":
        payload["packet_entities"][GUID]["removed"] = True
    elif change == "wrong_map":
        payload["packet_entities"][GUID]["map_id"] = 2175
    elif change == "done":
        payload["active_quests"][0]["objectives"][0]["is_complete"] = True
    else:
        payload["reference_knowledge"]["quests"]["66049"]["quest_roles"][0]["name"] = "Sabellian"
    assert conversation_actors(payload, 66049) == []


def test_another_soft_recipient_cannot_authorize_interacting_with_wrathion():
    payload = state()
    payload["soft_targets"][0]["guid"] = "Creature-0-1461-2534-147807-187046-000060A8EF"
    assert not any(p.skill == "INTERACT" for p in ServerNpcInteractionPolicy().propose(payload))


def test_the_same_current_actor_can_ground_the_marked_gossip_option():
    payload = state()
    option = {"id": 91, "name": "(Quest) I am ready.", "quest_label_prepend": True,
              "available": True, "x": .1, "y": .3}
    payload["quest_ui"] = {"open": True, "action": "GOSSIP_OPTION_SELECT", "npc_guid": GUID,
                           "gossip_options": [option], "gossip_option": option}
    proposal = QuestDialogPlanningPolicy._talk_gossip(payload, True)
    assert proposal is not None and proposal.parameters["target_guid"] == GUID
    assert str(proposal.parameters["quest_id"]) == "66049"
