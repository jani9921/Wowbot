"""Partial reference lists cannot invent a live item-objective identity."""
from copy import deepcopy

import pytest

from test_quest_drop_combat_handoff_20261028 import ENTRY, GUID, ITEM, QUEST, state
from wowbot.agent.packet_entity_facts import (
    NPC_SPELLCLICK, collect_creature_sources, collect_spellclick_units, kill_objective_entries,
)
from wowbot.agent.quest_reference_matching import reference_objectives


def two_items():
    value = state()
    other = deepcopy(value["active_quests"][0]["objectives"][0])
    other["description"] = "0/3 Silver Dust"
    value["active_quests"][0]["objectives"].append(other)
    return value


@pytest.mark.parametrize("first_complete", [False, True])
def test_incomplete_blank_catalog_cannot_bind_either_visible_item(first_complete):
    value = two_items()
    if first_complete:
        value["active_quests"][0]["objectives"][0].update(current=3, is_complete=True)
    assert collect_creature_sources(value) == {}
    assert kill_objective_entries(value) == {}


def test_exact_objective_id_can_resolve_a_partial_reference_list():
    value = two_items()
    value["active_quests"][0]["objectives"][0]["objective_id"] = 990501
    assert collect_creature_sources(value)[str(ENTRY)][0]["objective_id"] == "990501"
    assert kill_objective_entries(value)[str(ENTRY)] == (str(QUEST), "990501")


def test_unique_description_can_resolve_a_partial_reference_list():
    value = two_items()
    value["reference_knowledge"]["quests"][str(QUEST)]["objectives"][0]["description"] = "Amber Carapace"
    assert collect_creature_sources(value)[str(ENTRY)][0]["objective_id"] == f"{QUEST}:0"


def test_single_visible_item_and_single_blank_row_need_no_fabricated_order():
    value = state()
    value["reference_knowledge"]["quests"][str(QUEST)]["objectives"][0].pop("order")
    assert collect_creature_sources(value)[str(ENTRY)][0]["item_id"] == ITEM
    assert kill_objective_entries(value)[str(ENTRY)] == (str(QUEST), f"{QUEST}:0")


def test_complete_distinct_item_orders_keep_the_existing_multi_item_workflow():
    value = two_items()
    rows = value["reference_knowledge"]["quests"][str(QUEST)]["objectives"]
    other = deepcopy(rows[0])
    other.update(objective_id=990502, order=1, credit_object_id=ITEM+1)
    other["item_sources"][0].update(entry=ENTRY+1, item_id=ITEM+1)
    rows.append(other)
    sources = collect_creature_sources(value)
    assert sources[str(ENTRY)][0]["objective_id"] == f"{QUEST}:0"
    assert sources[str(ENTRY+1)][0]["objective_id"] == f"{QUEST}:1"


def test_duplicate_orders_do_not_make_a_complete_reference_alignment():
    value = two_items()
    rows = value["reference_knowledge"]["quests"][str(QUEST)]["objectives"]
    rows.append({**deepcopy(rows[0]), "objective_id": 990502})
    assert collect_creature_sources(value) == {}
    assert kill_objective_entries(value) == {}


def test_single_blank_row_cannot_override_an_explicit_objective_id_conflict():
    value = state()
    value["active_quests"][0]["objectives"][0]["objective_id"] = 999999
    assert collect_creature_sources(value) == {}
    assert kill_objective_entries(value) == {}


def test_duplicate_explicit_ids_cannot_be_repaired_by_the_single_item_fallback():
    value = state()
    row = value["reference_knowledge"]["quests"][str(QUEST)]["objectives"][0]
    row["objective_id"] = f"{QUEST}:0"
    value["reference_knowledge"]["quests"][str(QUEST)]["objectives"].append(
        {"objective_id": f"{QUEST}:0", "credit_kind": "CREATURE", "description": ""})
    assert collect_creature_sources(value) == {}


def test_legacy_parent_item_id_remains_a_hint_without_becoming_an_exact_click_relation():
    value = state()
    row = value["reference_knowledge"]["quests"][str(QUEST)]["objectives"][0]
    row["item_sources"][0].pop("item_id")
    binding, = collect_creature_sources(value)[str(ENTRY)]
    assert binding["item_id"] == ITEM and binding["item_id_explicit"] is False
    assert kill_objective_entries(value)[str(ENTRY)] == (str(QUEST), f"{QUEST}:0")
    value["packet_entities"][GUID]["info"]["npc_flags"] = NPC_SPELLCLICK
    assert collect_spellclick_units(value) == {}
    assert kill_objective_entries(value) == {}


@pytest.mark.parametrize("oid,text,expected", [(123, "other", [123]),
    ("7:0", "0/1 Amber", [123]), ("7:0", "", [])])
def test_disabling_ordinal_matching_keeps_exact_id_and_text(oid, text, expected):
    rows = [{"objective_id": 123, "order": 0, "description": "Amber"}]
    found = reference_objectives(7, oid, text, rows, allow_ordinal=False)
    assert [row["objective_id"] for row in found] == expected
