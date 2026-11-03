"""Exile's Reach live run 2026-10-25 10:23-11:00 (Ymir 70575), offline.

User: the First Aid Kit was not used on Kee-La and the two others until the
user targeted them ("standing at the NPC and F7 would do"); 5-6 goats and
porcupines died before one was looted; the meat was never cooked at the
campfire; the Scout-o-Matic and the Giant Boar were never mounted; in combat
the agent sometimes stood on WAIT until the target died.
"""
from copy import deepcopy
from types import SimpleNamespace

from wowbot.agent.goal_manager import GoalManager
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.packet_entity_facts import hidden_object_sources, kill_objective_entries, objective_objects
from wowbot.agent.server_loot_planning import ServerLootPolicy
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, spellclick_entries
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from wowbot.skills.interact import InteractSkill

KEE_LA = "Creature-0-3110-2175-79906-156612-00005C9C73"
SCOUT = "Creature-0-3110-2175-79906-156518-00005C9C73"
CAMPFIRE = "GameObject-0-3110-2175-79906-339769-00005C9C73"
GOAT = "Creature-0-3110-2175-79906-161130-00005DD0AA"


# -- 9. combat is never parked while a live attacker is selected ------------
def test_three_instant_combat_failures_do_not_park_a_live_fight():
    """10:52:41-43: COMBAT on Torgok failed out_of_range three times in 2 s;
    the task went UNRESOLVED for 120 s and only WAIT was left until 10:53:04."""
    manager, contracts = GoalManager(), SkillRegistry().contracts
    manager.set_goal(Goal.parse("Questelj", 1), 1)
    fight = Proposal.make("COMBAT", "Quest-cél elleni harc",
                          {"guid": "Creature-0-3110-2175-79906-162817-00005DD0F8",
                           "quest_ids": [55879], "objective_ids": []}, priority=100)
    assert manager.filter([fight], contracts, 10.)
    for at in (10.1, 10.6, 11.1):
        manager.outcome(fight, False, "out_of_range", at)
    assert manager.filter([fight], contracts, 12.) == []                 # out of combat: parked
    assert manager.filter([fight], contracts, 12., live_combat=True) == [fight]


# -- 2. our own corpse is looted before the next kill walk -----------------
def test_the_corpse_walk_outranks_the_boosted_next_kill_walk():
    """The next kill walk was 116 (100 + agenda 12 + campaign 4)."""
    state = {"monotonic_time": 100., "orientation": 0., "map_id": 1409,
             "player_world_position": {"x": -380., "y": -2540., "z": 10., "instance_id": 2175},
             "active_quests": [], "soft_targets": [],
             "packet_entities": {GOAT: {"guid": GOAT, "kind": "CREATURE", "entry_id": 161130, "map_id": 2175,
                                        "dynamic_flags": {"value": 0x4},
                                        "position": {"x": -370., "y": -2540., "z": 10.}}}}
    (walk,) = ServerLootPolicy().propose(state, 10.)
    assert walk.skill == "MOVE" and walk.parameters["purpose"] == "APPROACH_SERVER_CORPSE"
    assert walk.priority > 116.
    state["soft_targets"] = [{"source_unit": "softinteract", "guid": GOAT}]
    state["player_world_position"]["x"] = -372.
    (loot,) = ServerLootPolicy().propose(state, 10.)
    assert loot.skill == "LOOT" and loot.priority > 116.


# -- 1/4/5. spellclick units: walk up, F7, never Tab -------------------------
def _catalog(objectives, clickable):
    def records(kind, table, record_id):
        return ({"npc_entry": record_id, "spell_id": 300260},) if (
            table == "npc_spellclick_spells" and int(record_id) in clickable) else ()

    def rows(query, params):
        return []
    return SimpleNamespace(raw=SimpleNamespace(tables={"creature_template"}, rows=rows), records=records,
                           quest=lambda _: {"quest_id": 54951, "template": {"VerifiedBuild": 70575},
                                            "objectives": deepcopy(objectives)})


FIRST_AID = [{"objective_id": 388448, "raw_type": 0, "credit_object_id": 156609,
              "description": "First Aid Kit used on Bjorn Stouthands"},
             {"objective_id": 391858, "raw_type": 0, "credit_object_id": 156612,
              "description": "First Aid Kit used on Kee-La"}]


def test_tdb_spellclick_rows_make_an_interact_objective():
    reference = TDBKnowledgeProvider(_catalog(FIRST_AID, {156609, 156612})).quest(54951)
    rows = reference["objectives"]
    assert [row.get("credit_action") for row in rows] == ["SPELLCLICK", "SPELLCLICK"]
    assert rows[1]["spellclick_creatures"] == [{"entry": 156612, "name": None}]
    plain = TDBKnowledgeProvider(_catalog(FIRST_AID, set())).quest(54951)
    assert [row.get("credit_action") for row in plain["objectives"]] == [None, None]


def first_aid_state(*, kee_la_done=False, soft=True, distance=2.5, dz=0.):
    reference = TDBKnowledgeProvider(_catalog(FIRST_AID, {156609, 156612})).quest(54951)
    return {
        "monotonic_time": 100., "orientation": 0., "map_id": 1409,
        "player_world_position": {"x": -451.4, "y": -2606.0, "z": 0.6, "instance_id": 2175, "z_observed": True},
        "active_quests": [{"quest_id": 54951, "is_complete": False, "objectives": [
            {"description": "0/1 First Aid Kit used on Bjorn Stouthands", "is_complete": False},
            {"description": f"{int(kee_la_done)}/1 First Aid Kit used on Kee-La", "is_complete": kee_la_done}]}],
        "reference_knowledge": {"quests": {"54951": reference}},
        "packet_entities": {KEE_LA: {"guid": KEE_LA, "kind": "CREATURE", "entry_id": 156612, "map_id": 2175,
                                     "info": {"npc_flags": 0},
                                     "position": {"x": -451.4+distance, "y": -2606.0, "z": 0.6+dz}}},
        "soft_targets": [{"source_unit": "softinteract", "guid": KEE_LA}] if soft else [],
        "soft_targets_sample_time": 100.,
    }


def test_kee_la_gets_f7_not_tab():
    state = first_aid_state()
    assert "156612" not in kill_objective_entries(state)
    assert spellclick_entries(state) == {"156609": "54951", "156612": "54951"}
    (press,) = ServerNpcInteractionPolicy().propose(state)
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == KEE_LA
    assert press.parameters["purpose"] == "OBJECTIVE_SPELLCLICK"
    assert press.parameters["interaction_kind"] == "SPELLCLICK"
    assert InteractSkill._credit_purpose(press.parameters)          # verified by the quest credit
    (walk,) = ServerNpcInteractionPolicy().propose(first_aid_state(distance=25., soft=False))
    assert walk.skill == "MOVE" and walk.parameters["server_entity_guid"] == KEE_LA
    # Healed: she is no longer work.
    assert ServerNpcInteractionPolicy().propose(first_aid_state(kee_la_done=True)) == []


def test_a_hovering_vehicle_that_is_the_f7_recipient_is_pressed():
    """10:47:02-32: the Scout-o-Matic was the soft-interact unit 2.2 yd away
    and 4.8 yd above (5.3 yd); the 4 yd gate re-walked to it six times."""
    state = first_aid_state(distance=2.2, dz=4.8)
    (press,) = ServerNpcInteractionPolicy().propose(state)
    assert press.skill == "INTERACT"
    # Right under it, another unit takes the key: no walk to the same spot.
    state = first_aid_state(distance=1.5, dz=4.9, soft=False)
    assert ServerNpcInteractionPolicy().propose(state) == []


# -- 3. the campfire the server marks usable for the cook objective ----------
def cooking_state(*, usable=True):
    return {
        "monotonic_time": 100., "orientation": 0., "map_id": 1409,
        "player_world_position": {"x": -255., "y": -2490.8, "z": 18.0, "instance_id": 2175, "z_observed": True},
        "active_quests": [{"quest_id": 55174, "is_complete": False, "objectives": [
            {"description": "0/1 Cook the meat on the campfire", "type": "COLLECT", "is_complete": False},
            {"description": "5/5 Raw Meat collected from wildlife", "type": "COLLECT", "is_complete": True}]}],
        "reference_knowledge": {"quests": {"55174": {"objectives": [
            {"objective_id": 394179, "raw_type": 1, "credit_kind": "ITEM", "credit_object_id": 174074,
             "description": "Cook the meat on the campfire",
             "item_sources": [{"kind": "GAMEOBJECT", "entry": 339769, "item_id": 174074,
                               "relation": "QUEST_ITEM_ASSOCIATION"},
                              {"kind": "GAMEOBJECT", "entry": 349962, "item_id": 174074,
                               "relation": "QUEST_ITEM_ASSOCIATION"}]},
            {"objective_id": 396789, "raw_type": 1, "credit_kind": "ITEM", "credit_object_id": 174072,
             "description": "Raw Meat collected from wildlife",
             "item_sources": [{"kind": "CREATURE", "entry": 161130, "item_id": 174072,
                               "relation": "QUEST_ITEM_ASSOCIATION"}]}]}}},
        "packet_entities": {CAMPFIRE: {
            "guid": CAMPFIRE, "kind": "GAMEOBJECT", "entry_id": 339769, "map_id": 2175,
            "info": {"go_type": 3, "quest_objective_id": 394179},
            # 33280 until the fifth meat, 49700 (Activate 0x4) at 10:38:19.
            "dynamic_flags": {"value": 49700 if usable else 33280},
            "position": {"x": -247.78, "y": -2490.82, "z": 18.06, "instance_id": 2175}}},
    }


def test_the_campfire_is_the_cook_objective_s_use_spot_once_usable():
    assert hidden_object_sources(cooking_state(), 55174) == []          # not a hidden row
    assert hidden_object_sources(cooking_state(), 55174, described=True) == [
        ("394179", "339769"), ("394179", "349962")]                     # meat comes from goats
    (fire,) = objective_objects(cooking_state(), 55174)
    assert fire["guid"] == CAMPFIRE and fire["usable"] is True
    flow = ObjectInteractionFlow.__new__(ObjectInteractionFlow)
    spot, known = flow.packet_use_spot(cooking_state(), 55174, 18.0)
    assert known and spot["guid"] == CAMPFIRE
    # Before the meat: the server shows it but not usable; nothing to walk to.
    assert flow.packet_use_spot(cooking_state(usable=False), 55174, 18.0) == (None, True)
    # No learned-place walk for a described row (it is usable only later).
    assert flow.remembered_object_spot(cooking_state(usable=False), 55174) is None
