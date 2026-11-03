"""Veteran Reinforcements regression; synthetic observations, never client input."""
from copy import deepcopy

import pytest

from wowbot.agent.models import Goal, Observation
from wowbot.agent.quest_model import QuestModel, semantic_objective_key
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.world import WorldModel
from wowbot.agent.skills import SkillRegistry


GUID = "Creature-0-1-2444-1-190771-0000000001"
OTHER = "Creature-0-1-2444-1-190771-0000000002"


def quest():
    return {"quest_id": 65996, "title": "Veteran Reinforcements", "is_complete": False,
            "is_campaign": True, "special_item": {"item_id": 193917, "item_name": "Rejuvenating Draught"},
            "objectives": [{"type": "KILL", "raw_type": "monster", "is_complete": False,
                            "description": "0/4 Injured drakonids healed", "current": 0, "required": 4},
                           {"type": "KILL", "raw_type": "monster", "is_complete": False,
                            "description": "0/1 Meet Sendrax at the Conservatory Outpost", "current": 0, "required": 1}]}


def reference():
    return {"quests": {"65996": {"objectives": [
        {"objective_id": 429945, "order": 0, "credit_kind": "CREATURE_CREDIT",
         "credit_object_id": 190771, "credit_name": "Injured Ruby Culler",
         "description": "Injured drakonids healed"},
        {"objective_id": 430207, "order": 1, "credit_kind": "CREATURE_CREDIT",
         "credit_object_id": 194749, "credit_name": "Kill Credit: Erupting Cavern Guard [DNT]",
         "description": "Erupting Cavern Guard Healed"},
        {"objective_id": 429977, "order": 2, "credit_kind": "CREATURE_CREDIT",
         "credit_object_id": 190155, "credit_name": "Caretaker Azkra",
         "description": "Meet Sendrax at the Conservatory Outpost"},
    ]}}}


def actor(guid=GUID, y=10.):
    return {"guid": guid, "kind": "CREATURE", "entry_id": 190771, "map_id": 2444,
            "info": {"npc_flags": 0x1000000}, "dynamic_flags": {"value": 0},
            "position": {"x": 0., "y": y, "z": 20., "source": "PACKET_CREATE_MOVEMENT", "age": 0.}}


def state(distance=10., selected=False, ready=False):
    value = {"session_id": "test:heal-tool", "frame_id": "heal:1", "timestamp": 10.,
             "monotonic_time": 10., "player_present": True, "world_map_open": False,
             "map_id": 2022, "orientation": 1.5707963267948966,
             "player_world_position": {"x": 0., "y": 0., "z": 20., "z_known": True,
                                       "z_observed": True, "instance_id": 2444,
                                       "coordinate_space": "WORLD_YARDS"},
             "active_quests": [quest()], "reference_knowledge": reference(),
             "packet_entities": {GUID: actor(y=distance)},
             "inventory": {"items": [{"item_id": 193917, "bag": 2, "slot": 4}]},
             "target": False, "mouseover": False, "soft_targets": [],
             "server_mode": {"selected": True, "active": True, "enabled": True}}
    if selected:
        value["target"] = {"guid": GUID, "npc_id": 190771, "name": "Injured Ruby Culler",
                           "attackable": False, "dead": False,
                           "world_position": {"x": 0., "y": distance, "z": 20.,
                                              "instance_id": 2444, "coordinate_space": "WORLD_YARDS",
                                              "source": "PACKET_ENTITY"}}
        value["target_sample_time"] = 10.
    if ready:
        value["soft_targets"] = [{"guid": GUID, "npc_id": 190771, "source_unit": "softinteract",
                                  "is_attackable": False, "sample_time": 10.}]
        value["soft_targets_sample_time"] = 10.
        value["quest_item_target"] = {"guid": GUID, "sample_time": 10., "items": [
            {"quest_id": 65996, "item_id": 193917, "in_range": True,
             "is_usable": True, "cooldown_remaining": 0.}]}
    return value


def model(payload):
    world = WorldModel()
    world.ingest(Observation.create(payload, 10.))
    world.ingest(Observation.create({"session_id": payload["session_id"],
                                    "reference_knowledge": payload["reference_knowledge"]},
                                   10., source="REFERENCE_MEMORY"))
    return world


def test_exact_api_tool_and_heal_clause_outrank_defend_hint():
    quests = QuestModel()
    quests.semantic_hints[("65996", semantic_objective_key("Injured drakonids healed"))] = {
        "action": "DEFEND", "target": "injured drakonids", "complex_quest": True}
    quests.ingest([quest()], "live", 10.)
    objective = quests.records[65996].objectives[0]
    assert objective.type == "USE_ITEM_ON_TARGET"
    assert objective.target_object["item_id"] == 193917
    assert objective.raw["type"] == "KILL"  # keep the original coarse API evidence


def test_hidden_tdb_objective_cannot_shift_visible_objective_ids():
    quests = QuestModel()
    quests.ingest([quest()], "live", 10.)
    quests.apply_reference_knowledge(reference())
    heal, meet = quests.records[65996].objectives
    assert heal.raw["tdb_objective_id"] == 429945
    assert meet.raw["tdb_objective_id"] == 429977
    assert heal.target_entity["npc_id"] == 190771
    assert heal.target_entity["name"] == "Injured Ruby Culler"


def test_ambiguous_description_does_not_guess_a_reference_objective():
    quests = QuestModel()
    quests.ingest([quest()], "live", 10.)
    refs = reference()
    refs["quests"]["65996"]["objectives"].append({
        **refs["quests"]["65996"]["objectives"][0], "objective_id": 999, "order": 8})
    quests.apply_reference_knowledge(refs)
    assert "tdb_objective_id" not in quests.records[65996].objectives[0].raw


def test_neither_generic_defend_nor_missing_tool_invents_item_use():
    for with_item, description in [(False, "Injured drakonids healed"), (True, "Defend the outpost")]:
        value = quest()
        value["objectives"][0]["description"] = description
        if not with_item:
            value.pop("special_item")
        quests = QuestModel()
        quests.ingest([value], "live", 10.)
        assert (quests.records[65996].objectives[0].target_object or {}).get("item_id") is None


def test_server_known_heal_subject_approaches_without_visual_search_or_combat():
    candidates = QuestDomain().propose(model(state()), Goal.parse("Questelj", 10.))
    moves = [p for p in candidates if p.skill == "MOVE" and p.parameters.get("item_id") == 193917]
    assert moves and moves[0].parameters["server_entity_guid"] == GUID
    assert moves[0].parameters["require_navmesh"] is True
    assert moves[0].parameters["face_on_arrival"] is True
    assert not [p for p in candidates if p.skill in {"COMBAT", "DEFEND", "WAIT_EVENT"}]


def test_near_heal_subject_is_acquired_by_existing_verified_friendly_target_skill():
    candidates = QuestDomain().propose(model(state(distance=2.)), Goal.parse("Questelj", 10.))
    targets = [p for p in candidates if p.skill == "TARGET"]
    assert targets and targets[0].parameters["guid"] == GUID
    assert targets[0].parameters["activation_source"] == "TAB_FRIEND_RESCUE"
    assert targets[0].parameters["acceptable_guids"] == [GUID]
    assert not [p for p in candidates if p.skill in {"ASSIST", "USE_ON_TARGET"}]


def test_selected_ready_friendly_uses_exact_tool_not_an_event_wait():
    candidates = QuestDomain().propose(model(state(distance=2., selected=True, ready=True)),
                                        Goal.parse("Questelj", 10.))
    uses = [p for p in candidates if p.skill == "USE_ON_TARGET"]
    assert uses and uses[0].parameters["item_id"] == 193917
    assert uses[0].parameters["guid"] == GUID
    assert uses[0].parameters["activation_source"] == "INTERACT_KEY"
    assert not [p for p in candidates if p.skill == "WAIT_EVENT"]


@pytest.mark.parametrize("invalid", ["removed", "wrong_instance", "corpse", "wrong_entry"])
def test_invalid_actor_never_authorizes_approach_or_friendly_target(invalid):
    payload = state()
    unit = payload["packet_entities"][GUID]
    if invalid == "removed": unit["removed"] = True
    elif invalid == "wrong_instance": unit["map_id"] = 2175
    elif invalid == "corpse": unit["dead"] = True
    else: unit["entry_id"] = 190155
    candidates = QuestDomain().propose(model(payload), Goal.parse("Questelj", 10.))
    assert not [p for p in candidates if p.parameters.get("item_id") == 193917
                and p.skill in {"MOVE", "TARGET", "ASSIST", "USE_ON_TARGET"}]


def test_verified_heal_is_not_repeated_on_same_guid():
    domain = QuestDomain()
    payload = state()
    payload["packet_entities"][OTHER] = actor(OTHER, 20.)
    domain.note_object_interaction_result(
        {"skill": "USE_ON_TARGET", "outcome": "SUCCESS"}, payload,
        {"guid": GUID, "item_id": 193917, "objective_id": "65996:0",
         "quest_ids": [65996], "purpose": "HEAL_QUEST_ITEM"})
    candidates = domain.propose(model(payload), Goal.parse("Questelj", 10.))
    moves = [p for p in candidates if p.skill == "MOVE" and p.parameters.get("item_id") == 193917]
    assert moves and moves[0].parameters["server_entity_guid"] == OTHER


def test_reference_heal_identity_does_not_survive_reference_removal():
    quests = QuestModel()
    quests.ingest([quest()], "live", 10.)
    quests.apply_reference_knowledge(reference())
    assert quests.records[65996].objectives[0].target_entity["npc_id"] == 190771
    quests.apply_reference_knowledge({"quests": {}})
    assert quests.records[65996].objectives[0].target_entity.get("npc_id") is None


def test_stale_or_wrong_target_readiness_cannot_authorize_f7():
    payload = state(distance=2., selected=True, ready=True)
    payload["quest_item_target"]["sample_time"] = 8.
    candidates = QuestDomain().propose(model(payload), Goal.parse("Questelj", 10.))
    assert not [p for p in candidates if p.parameters.get("activation_source") == "INTERACT_KEY"]


@pytest.mark.parametrize("stage,skill", [("far", "MOVE"), ("near", "TARGET"), ("ready", "USE_ON_TARGET")])
def test_healing_chain_is_admitted_by_the_real_server_mode_registry(stage, skill):
    payload = state(distance=10. if stage == "far" else 2., selected=stage == "ready", ready=stage == "ready")
    world = model(payload)
    candidates = QuestDomain().propose(world, Goal.parse("Questelj", 10.))
    chosen = next(p for p in candidates if p.skill == skill and p.parameters.get("item_id") == 193917)
    assert SkillRegistry().available(chosen, world)


def active(proposal, before):
    from wowbot.agent.models import Attempt, Prediction
    from wowbot.runtime import ActiveSkillRuntime, Intent
    params = proposal.parameters
    attempt = Attempt("heal-test", proposal, before, "obs", 10., 15., (),
                      Prediction("p", "heal-test", "credit", 10., 15., "obs"))
    return ActiveSkillRuntime().start(
        intent=Intent(proposal.skill, params, params.get("guid"), params.get("objective_id")),
        attempt=attempt, now=10., before_snapshot=before)


def test_full_item_skill_sends_one_f7_and_needs_the_heal_objective_credit():
    from wowbot.skills import UseItemSkill
    from wowbot.runtime import SkillStatus
    payload = state(distance=2., selected=True, ready=True)
    candidates = QuestDomain().propose(model(payload), Goal.parse("Questelj", 10.))
    proposal = next(p for p in candidates if p.skill == "USE_ON_TARGET")
    skill = UseItemSkill(type("Bindings", (), {"contains": lambda self, action: action == "INTERACTTARGET"})())
    runtime = active(proposal, payload)
    result = skill.begin(runtime, payload)
    assert result.status is SkillStatus.RUNNING
    assert [c.binding for c in result.commands] == ["INTERACTTARGET"]
    unrelated = deepcopy(payload)
    unrelated["active_quests"][0]["objectives"][1]["current"] = 1
    unrelated["active_quests"][0]["objectives"][1]["is_complete"] = True
    assert skill.verify(runtime, unrelated, 10.2).status is SkillStatus.RUNNING
    credited = deepcopy(payload)
    credited["active_quests"][0]["objectives"][0]["current"] = 1
    assert skill.verify(runtime, credited, 10.3).status is SkillStatus.SUCCESS


def test_wrong_guid_at_command_boundary_cannot_receive_the_healing_item():
    from wowbot.skills import UseItemSkill
    from wowbot.runtime import SkillStatus
    payload = state(distance=2., selected=True, ready=True)
    proposal = next(p for p in QuestDomain().propose(model(payload), Goal.parse("Questelj", 10.))
                    if p.skill == "USE_ON_TARGET")
    runtime = active(proposal, payload)
    wrong = deepcopy(payload)
    wrong["target"]["guid"] = OTHER
    result = UseItemSkill().begin(runtime, wrong)
    assert result.status in {SkillStatus.FAILURE, SkillStatus.BLOCKED}
    assert not result.commands


def test_friendly_acquisition_verifies_exact_guid_after_ctrl_tab():
    from wowbot.skills import TargetSkill
    from wowbot.runtime import SkillStatus
    payload = state(distance=2.)
    proposal = next(p for p in QuestDomain().propose(model(payload), Goal.parse("Questelj", 10.))
                    if p.skill == "TARGET")
    skill = TargetSkill()
    runtime = active(proposal, payload)
    started = skill.begin(runtime, payload)
    assert [command.binding for command in started.commands] == ["TARGETNEARESTFRIEND"]
    wrong = deepcopy(payload)
    wrong["target"] = {"guid": OTHER, "npc_id": 190771, "attackable": False}
    wrong["target_sample_time"] = 10.2
    assert skill.verify(runtime, wrong, 10.2).status is SkillStatus.FAILURE
    runtime = active(proposal, payload)
    skill.begin(runtime, payload)
    right = deepcopy(wrong)
    right["target"]["guid"] = GUID
    assert skill.verify(runtime, right, 10.2).status is SkillStatus.SUCCESS


def test_selected_previously_credited_actor_is_not_used_again_without_alternatives():
    domain = QuestDomain()
    payload = state(distance=2., selected=True, ready=True)
    domain.note_object_interaction_result(
        {"skill": "USE_ON_TARGET", "outcome": "SUCCESS"}, payload,
        {"guid": GUID, "item_id": 193917, "objective_id": "65996:0",
         "quest_ids": [65996], "purpose": "HEAL_QUEST_ITEM"})
    candidates = domain.propose(model(payload), Goal.parse("Questelj", 10.))
    assert not [p for p in candidates if p.skill in {"ASSIST", "USE_ON_TARGET"}]


def test_failed_item_use_never_marks_a_healing_actor_done():
    domain = QuestDomain()
    payload = state()
    domain.note_object_interaction_result(
        {"skill": "USE_ON_TARGET", "outcome": "FAILURE"}, payload,
        {"guid": GUID, "item_id": 193917, "objective_id": "65996:0",
         "quest_ids": [65996], "purpose": "HEAL_QUEST_ITEM"})
    candidates = domain.propose(model(payload), Goal.parse("Questelj", 10.))
    assert any(p.skill == "MOVE" and p.parameters.get("server_entity_guid") == GUID for p in candidates)


def test_three_failed_friendly_selections_are_bounded_and_try_another_actor():
    domain = QuestDomain()
    payload = state(distance=2.)
    payload["packet_entities"][OTHER] = actor(OTHER, 20.)
    for _ in range(3):
        domain.note_object_interaction_result(
            {"skill": "TARGET", "outcome": "FAILURE"}, payload,
            {"guid": GUID, "objective_id": "65996:0", "purpose": "QUEST_ITEM_ACQUIRE"})
    candidates = domain.propose(model(payload), Goal.parse("Questelj", 10.))
    assert any(p.skill == "MOVE" and p.parameters.get("server_entity_guid") == OTHER for p in candidates)


def test_heal_objective_does_not_send_an_item_to_an_attackable_recipient():
    payload = state(distance=2., selected=True, ready=True)
    payload["target"]["attackable"] = True
    candidates = QuestDomain().propose(model(payload), Goal.parse("Questelj", 10.))
    assert not [p for p in candidates if p.skill in {"ASSIST", "USE_ON_TARGET"}]
