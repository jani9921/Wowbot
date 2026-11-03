"""Near server work first; an objective row without a description (live 2026-10-21).

15:21:17-15:22:06 the server walk to an Encroaching Lava (70135, priority 104)
and the TDB route to Practice Materials 350 yd south (70124, 96+12+4) took
turns every 0.5-1 s (user: "nagyon sok move volt ami össze-vissza vitte,
oda-vissza").  At 15:26:13 the agent waited beside a dozen Primal Proto-Whelps
(193876): the TDB row of 70124 had no description, so its item-drop
creatures were never hunted.
"""
from wowbot.agent.packet_entity_facts import kill_objective_entries, kill_objective_units
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy

from test_server_kill_target_20261020 import unit

WHELP = "Creature-0-3769-2444-47-193876-0000588052"
LAVA = "Creature-0-3769-2444-47-187326-000258BBED"


def state(*units, collect_text="3/12 Primal Proto-Whelp Scale"):
    return {
        "monotonic_time": 100., "map_id": 2022,
        "player_world_position": {"x": 0., "y": 0., "z": 50., "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"},
        "active_quests": [
            {"quest_id": 70124, "is_complete": False, "objectives": [
                {"description": collect_text, "type": "COLLECT", "raw_type": "item", "is_complete": False}]},
            {"quest_id": 70135, "is_complete": False, "objectives": [
                {"description": "7/15 Primal elementals slain", "type": "KILL", "raw_type": "monster",
                 "is_complete": False}]}],
        "reference_knowledge": {"quests": {
            "70124": {"objectives": [{"description": "", "credit_kind": "ITEM", "credit_object_id": 198398,
                                      "item_sources": [{"entry": 193876, "kind": "CREATURE",
                                                        "relation": "QUEST_ITEM_ASSOCIATION"}]}]},
            "70135": {"objectives": [{"description": "Primal elementals slain", "credit_kind": "CREATURE_CREDIT",
                                      "credit_object_id": 190790,
                                      "credit_name": "Kill Credit: Wingrest Embassy Elementals [DNT]",
                                      "credit_creatures": [{"entry": 187326, "name": "Encroaching Lava"}]}]}}},
        "packet_entities": {item["guid"]: item for item in units}}


def test_a_row_without_description_is_the_quests_only_objective_of_its_kind():
    entries = kill_objective_entries(state())
    assert entries["193876"] == ("70124", "70124:0")
    assert entries["187326"] == ("70135", "70135:0")
    whelp = unit(WHELP, 12., 0.)
    assert [item["guid"] for item in kill_objective_units(state(whelp))] == [WHELP]
    # Two open item objectives: an empty row cannot say which one it is.
    ambiguous = state()
    ambiguous["active_quests"][0]["objectives"].append(
        {"description": "0/4 Something Else", "type": "COLLECT", "raw_type": "item", "is_complete": False})
    assert "193876" not in kill_objective_entries(ambiguous)


def test_a_live_objective_unit_nearby_is_local_work_for_every_route():
    near = state(unit(LAVA, 20., 5.))
    assert QuestLocationPlanningPolicy.local_work_at_hand(None, near) is True
    far = state(unit(LAVA, 60., 5.))
    assert QuestLocationPlanningPolicy.local_work_at_hand(None, far) is False
    looted = state(unit(LAVA, 20., 5., flags=0x4))                  # a corpse is no work
    assert QuestLocationPlanningPolicy.local_work_at_hand(None, looted) is False
