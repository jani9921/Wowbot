"""Item-source discovery must reach the selected-target combat decision."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from wowbot.agent.combat_planning import CombatPlanningPolicy
from wowbot.agent.models import Goal, Observation
from wowbot.agent.packet_entity_facts import kill_objective_entries, kill_objective_units
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.server_kill_planning import ServerKillTargetPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel

QUEST = 990201
ITEM = 990301
ENTRY = 990401
GUID = f"Creature-0-3770-0-39-{ENTRY}-0000620D30"


def state():
    return {
        "session_id": "drop-combat-handoff", "timestamp": 100., "monotonic_time": 100.,
        "player_present": True, "map_id": 425, "orientation": 0.,
        "player_world_position": {"x": 0., "y": 0., "z": 74., "z_known": True,
                                  "z_observed": True, "instance_id": 0,
                                  "coordinate_space": "WORLD_YARDS"},
        "is_in_combat": False, "is_casting": False, "world_map_open": False,
        "health": 100, "max_health": 100, "events": [],
        "target": {"guid": GUID, "npc_id": ENTRY, "name": "Glasswing Hunter",
                   "attackable": True, "dead": False},
        "actionbar": [{"action": "ACTIONBUTTON2", "id": 100, "kind": "spell",
                       "name": "Charge", "is_harmful": True, "is_usable": True,
                       "in_range": True, "cooldown_remaining": 0}],
        "active_quests": [{"quest_id": QUEST, "is_complete": False, "objectives": [{
            "description": "0/3 Amber Carapace", "type": "COLLECT", "raw_type": "item",
            "current": 0, "required": 3, "is_complete": False}]}],
        "reference_knowledge": {"quests": {str(QUEST): {"quest_id": QUEST, "objectives": [{
            "objective_id": 990501, "order": 0, "description": "", "raw_type": 1,
            "credit_kind": "ITEM", "credit_object_id": ITEM, "mechanism": "COLLECT_DROP",
            "item_sources": [{"kind": "CREATURE", "entry": ENTRY, "item_id": ITEM,
                              "relation": "QUEST_ITEM_ASSOCIATION", "confirmed": False}]}]}}},
        "packet_entities": {GUID: {"guid": GUID, "kind": "CREATURE", "entry_id": ENTRY,
                                  "map_id": 0, "info": {"npc_flags": 0},
                                  "unit": {"health": 100, "unit_flags": 0},
                                  "position": {"x": 12., "y": 0., "z": 74., "age": 0.,
                                               "source": "PACKET_CREATE_MOVEMENT"}}},
    }


def modeled(value):
    world = WorldModel()
    world.ingest(Observation.create(value, 100.))
    world.quest_model.apply_reference_knowledge(value.get("reference_knowledge") or {})
    return world


def propose(world):
    return CombatPlanningPolicy(SkillRegistry()).propose(
        world.planning_snapshot(100.), Goal.parse("Questelj", 100.), 100., QuestDomain())


def combat(result):
    return [p for p in result.proposals if p.skill == "COMBAT"]


def test_discovery_target_and_combat_share_item_source_without_text_match():
    value = state()
    before = deepcopy(value)
    selected = deepcopy(value)
    selected["target"] = None
    tab, = ServerKillTargetPolicy().propose(selected)
    assert tab.skill == "TARGET" and tab.parameters["guid"] == GUID
    assert tab.parameters["objective_id"] == f"{QUEST}:0"

    world = modeled(value)
    old_target_entity = deepcopy(world.quest_model.records[QUEST].objectives[0].target_entity)
    result = propose(world)
    attack, = combat(result)
    assert attack.parameters["guid"] == GUID
    assert attack.parameters["quest_ids"] == [QUEST]
    assert attack.parameters["objective_ids"] == [f"{QUEST}:0"]
    assert SkillRegistry().available(attack, world)
    assert world.quest_model.records[QUEST].objectives[0].target_entity == old_target_entity is None
    assert world.quest_model.records[QUEST].objectives[0].current_count == 0
    assert value == before  # relevance must not manufacture credit or rewrite evidence


def test_same_source_remains_quest_combat_after_aggro():
    value = state()
    value["is_in_combat"] = True
    result = propose(modeled(value))
    attacks = combat(result)
    assert attacks and all(p.parameters["quest_ids"] == [QUEST] for p in attacks)
    assert all(p.parameters["objective_ids"] == [f"{QUEST}:0"] for p in attacks)
    assert not any(p.skill == "DEFEND" for p in result.proposals)


@pytest.mark.parametrize("finished", ["quest", "objective", "absent"])
def test_no_further_hunting_after_completion_or_removal(finished):
    value = state()
    if finished == "quest":
        value["active_quests"][0]["is_complete"] = True
    elif finished == "objective":
        value["active_quests"][0]["objectives"][0].update(
            current=3, is_complete=True, description="3/3 Amber Carapace")
    else:
        value["active_quests"] = []
    assert not combat(propose(modeled(value)))
    value["is_in_combat"] = True
    result = propose(modeled(value))
    assert not combat(result)
    defend = next(p for p in result.proposals if p.skill == "DEFEND")
    assert defend.parameters["quest_ids"] == []


@pytest.mark.parametrize("field,value", [
    ("kind", "VENDOR"), ("kind", "GAMEOBJECT"), ("kind", "CONTAINER"),
    ("relation", "VENDOR_STOCK"), ("relation", "UNKNOWN"), ("item_id", ITEM+1),
])
def test_other_acquisition_relations_or_conflicting_item_do_not_authorize_combat(field, value):
    payload = state()
    source = payload["reference_knowledge"]["quests"][str(QUEST)]["objectives"][0]["item_sources"][0]
    source[field] = value
    assert not combat(propose(modeled(payload)))


@pytest.mark.parametrize("change", [
    {"npc_id": ENTRY+1},
    {"guid": GUID.replace(str(ENTRY), str(ENTRY+1))},
    {"guid": None},
    {"guid": "WORLD3D:5"},
    {"npc_id": True},
    {"object_id": ENTRY},
])
def test_missing_or_conflicting_selected_identity_cannot_reuse_the_drop_relation(change):
    value = state()
    value["target"].update(change)
    assert not combat(propose(modeled(value)))


def test_valid_guid_can_supply_the_entry_when_the_client_omits_npc_id():
    value = state()
    value["target"].pop("npc_id")
    attack, = combat(propose(modeled(value)))
    assert attack.parameters["guid"] == GUID and attack.parameters["quest_ids"] == [QUEST]


@pytest.mark.parametrize("change", [{"attackable": False}, {"dead": True}, {"in_range": False}])
def test_source_relation_does_not_bypass_target_and_range_guards(change):
    value = state()
    if "in_range" in change:
        value["actionbar"][0].update(change)
    else:
        value["target"].update(change)
    assert not combat(propose(modeled(value)))


def test_unrelated_live_creature_is_not_attacked_just_because_a_collect_quest_is_open():
    value = state()
    value["target"].update(guid=GUID.replace(str(ENTRY), str(ENTRY+1)), npc_id=ENTRY+1)
    assert not combat(propose(modeled(value)))


def test_explicit_objective_identity_conflict_is_not_overridden_by_static_item_source():
    world = modeled(state())
    world.quest_model.records[QUEST].objectives[0].target_entity = {"npc_id": ENTRY+1}
    assert not combat(propose(world))


def test_item_use_objective_promotion_does_not_become_a_drop_hunt():
    world = modeled(state())
    objective = world.quest_model.records[QUEST].objectives[0]
    objective.type = "USE_ITEM_ON_TARGET"
    objective.target_object = {"item_id": ITEM}
    assert not combat(propose(world))


def test_ambiguous_blank_reference_rows_do_not_pick_a_collect_objective_by_index():
    value = state()
    other = deepcopy(value["active_quests"][0]["objectives"][0])
    other["description"] = "0/3 Silver Dust"
    value["active_quests"][0]["objectives"].append(other)
    assert kill_objective_entries(value) == {}
    assert not combat(propose(modeled(value)))


def test_all_explicit_creature_sources_remain_alternatives_not_one_required_target():
    value = state()
    source = deepcopy(value["reference_knowledge"]["quests"][str(QUEST)]["objectives"][0]["item_sources"][0])
    source["entry"] = ENTRY+1
    value["reference_knowledge"]["quests"][str(QUEST)]["objectives"][0]["item_sources"].append(source)
    value["target"].update(guid=GUID.replace(str(ENTRY), str(ENTRY+1)), npc_id=ENTRY+1)
    attack, = combat(propose(modeled(value)))
    assert attack.parameters["quest_ids"] == [QUEST]
    assert modeled(value).quest_model.records[QUEST].objectives[0].target_entity is None


def test_one_creature_can_serve_two_quests_and_primary_selection_still_applies():
    from wowbot.agent.packet_entity_facts import kill_objective_relations

    value = state()
    second = deepcopy(value["active_quests"][0])
    second["quest_id"] = QUEST+1
    value["active_quests"].append(second)
    value["reference_knowledge"]["quests"][str(QUEST+1)] = deepcopy(
        value["reference_knowledge"]["quests"][str(QUEST)])
    relations = kill_objective_relations(value)
    assert relations[str(ENTRY)] == ((str(QUEST), f"{QUEST}:0"), (str(QUEST+1), f"{QUEST+1}:0"))
    # Discovery keeps its stable first quest; combat can honor the other
    # explicitly selected primary objective without losing the shared source.
    assert kill_objective_entries(value)[str(ENTRY)] == (str(QUEST), f"{QUEST}:0")
    world = modeled(value)
    attack, = combat(propose(world))
    assert attack.parameters["quest_ids"] == [QUEST, QUEST+1]
    world.set_runtime_context(primary_quest={"quest_id": str(QUEST+1), "objective_id": f"{QUEST+1}:0"})
    scoped, = combat(propose(world))
    assert scoped.parameters["quest_ids"] == [QUEST+1]
    assert scoped.parameters["objective_ids"] == [f"{QUEST+1}:0"]
    world.set_runtime_context(primary_quest={"quest_id": "different"})
    assert not combat(propose(world))


def test_duplicate_difficulty_rows_do_not_duplicate_objective_credit_context():
    value = state()
    sources = value["reference_knowledge"]["quests"][str(QUEST)]["objectives"][0]["item_sources"]
    sources.append(deepcopy(sources[0]))
    attack, = combat(propose(modeled(value)))
    assert attack.parameters["quest_ids"] == [QUEST]
    assert attack.parameters["objective_ids"] == [f"{QUEST}:0"]


def test_recorded_blackrock_target_reaches_the_common_planner_before_aggro():
    from wowbot.agent.planner import Planner

    path = Path(__file__).parent / "fixtures" / "quest_drop_handoff_20261028.json"
    value = json.loads(path.read_text(encoding="utf-8"))["state"]
    now = value["monotonic_time"]
    world = WorldModel()
    world.ingest(Observation.create(value, now))
    world.quest_model.apply_reference_knowledge(value["reference_knowledge"])
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", now), world, now)
    assert proposals[0].skill == "COMBAT"
    assert proposals[0].parameters["quest_ids"] == [26389]
    assert proposals[0].parameters["objective_ids"] == ["26389:0"]
    assert world.quest_model.records[26389].objectives[0].current_count == 0


def test_finished_source_does_not_hide_a_second_open_quest_on_the_same_creature():
    value = state()
    second = deepcopy(value["active_quests"][0])
    second["quest_id"] = QUEST+1
    value["active_quests"].append(second)
    value["reference_knowledge"]["quests"][str(QUEST+1)] = deepcopy(
        value["reference_knowledge"]["quests"][str(QUEST)])
    value["active_quests"][0]["is_complete"] = True
    attack, = combat(propose(modeled(value)))
    assert attack.parameters["quest_ids"] == [QUEST+1]
    assert attack.parameters["objective_ids"] == [f"{QUEST+1}:0"]


def test_live_completed_count_does_not_need_a_separate_complete_flag_to_stop_hunting():
    value = state()
    value["active_quests"][0]["objectives"][0].update(current=3, description="3/3 Amber Carapace")
    assert not combat(propose(modeled(value)))

