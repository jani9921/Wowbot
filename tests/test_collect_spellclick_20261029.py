"""Item-source association + live SPELLCLICK is an interaction, not a hunt.

Observed 2026-10-29: Connection to Ohn'ahra had reeds 4/4, feathers 0/8,
heart 0/1; the feather creature's server NPC flags were 0x01000000.
No names or quest-specific exception should be required for that mechanic.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Attempt, Outcome, Prediction
from wowbot.agent.packet_entity_facts import (
    collect_creature_sources, collect_spellclick_units, kill_objective_relations,
)
from wowbot.agent.server_npc_planning import (
    ServerNpcInteractionPolicy, objective_npc_available,
)
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import InteractSkill


def scene(qid=65805, bird=190708, predator=190961):
    guid = f"Creature-0-1463-2444-79-{bird}-0000636918"
    other = f"Creature-0-1463-2444-79-{bird}-0000636919"
    hostile = f"Creature-0-1463-2444-79-{predator}-0000636920"
    state = {
        "session_id": "selected-session", "monotonic_time": 100., "map_id": 2023,
        "soft_targets_sample_time": 100., "orientation": 0., "target": {},
        "soft_targets": [], "movement": {"moving": False},
        "player_world_position": {"x": 0., "y": 0., "z": 10., "z_observed": True,
                                  "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [{"quest_id": qid, "is_accepted": True, "is_complete": False,
                           "objectives": [
            {"description": "4/4 Reeds", "type": "COLLECT", "raw_type": "item",
             "current": 4, "required": 4, "is_complete": True},
            {"description": "0/8 Feathers", "type": "COLLECT", "raw_type": "item",
             "current": 0, "required": 8, "is_complete": False},
            {"description": "0/1 Heart", "type": "COLLECT", "raw_type": "item",
             "current": 0, "required": 1, "is_complete": False}]}],
        "reference_knowledge": {"quests": {str(qid): {"objectives": [
            {"order": 0, "objective_id": 423598, "description": "", "credit_kind": "ITEM",
             "credit_object_id": 191101, "item_sources": [
                 {"kind": "GAMEOBJECT", "entry": 376152, "item_id": 191101,
                  "relation": "QUEST_ITEM_ASSOCIATION"}]},
            {"order": 1, "objective_id": 423599, "description": "", "credit_kind": "ITEM",
             "credit_object_id": 191102, "item_sources": [
                 {"kind": "CREATURE", "entry": bird, "item_id": 191102,
                  "relation": "QUEST_ITEM_ASSOCIATION"}]},
            {"order": 2, "objective_id": 423600, "description": "", "credit_kind": "ITEM",
             "credit_object_id": 191103, "item_sources": [
                 {"kind": "CREATURE", "entry": predator, "item_id": 191103,
                  "relation": "QUEST_ITEM_ASSOCIATION"}]}]}}},
        "packet_entities": {},
    }
    for unit, entry, flags, x in ((guid, bird, 0x01000000, 20.),
                                 (other, bird, 0x01000000, 30.),
                                 (hostile, predator, 0, 50.)):
        state["packet_entities"][unit] = {
            "guid": unit, "entry_id": entry, "kind": "CREATURE", "map_id": 2444,
            "info": {"npc_flags": flags, "sampled_at": 100.},
            "unit": {"health": 100, "max_health": 100},
            "position": {"x": x, "y": 0., "z": 10., "source": "PACKET_CREATE_MOVEMENT"},
        }
    return state, guid, other


def close(state, guid):
    point = state["packet_entities"][guid]["position"]
    state["player_world_position"].update(x=point["x"]-2., y=point["y"], z=point["z"])
    state["soft_targets"] = [{"guid": guid, "npc_id": state["packet_entities"][guid]["entry_id"],
                              "source_unit": "softinteract", "unit_type": "NPC",
                              "is_attackable": False, "is_dead": False}]
    return state


def running(state, proposal):
    now = state["monotonic_time"]
    attempt = Attempt("pluck", proposal, deepcopy(state), "o", now, now+9., (),
                      Prediction("p", "pluck", "objective item credit", now, now+9., "o"))
    return ActiveSkillRuntime().start(intent=Intent(proposal.skill, proposal.parameters),
                                     attempt=attempt, now=now, before_snapshot=deepcopy(state))


@pytest.mark.parametrize("ids", [(65805, 190708, 190961), (50001, 80001, 80002)])
def test_blank_multi_item_rows_bind_exact_live_objectives_without_name_hotfix(ids):
    state, guid, other = scene(*ids)
    qid, bird, predator = ids
    assert collect_creature_sources(state) == {
        str(bird): [{"quest_id": str(qid), "objective_id": f"{qid}:1", "item_id": 191102,
                     "reference_objective_id": 423599}],
        str(predator): [{"quest_id": str(qid), "objective_id": f"{qid}:2", "item_id": 191103,
                         "reference_objective_id": 423600}],
    }
    assert set(collect_spellclick_units(state)) == {guid, other}
    assert kill_objective_relations(state) == {str(predator): ((str(qid), f"{qid}:2"),)}


@pytest.mark.parametrize("change", ["removed", "dead", "zero_health", "wrong_instance",
    "no_instance", "no_click", "credited", "count_full", "quest_done", "not_accepted",
    "wrong_item", "missing_item", "vendor", "wrong_kind", "ambiguous", "contradictory_text"])
def test_item_interaction_needs_open_exact_source_and_current_server_click_flag(change):
    state, guid, other = scene()
    state["packet_entities"].pop(other)
    entity = state["packet_entities"][guid]
    quest = state["active_quests"][0]
    row = state["reference_knowledge"]["quests"]["65805"]["objectives"][1]
    source = row["item_sources"][0]
    if change == "removed": entity["removed"] = True
    elif change == "dead": entity["dead"] = True
    elif change == "zero_health": entity["unit"]["health"] = 0
    elif change == "wrong_instance": entity["map_id"] = 2175
    elif change == "no_instance": state["player_world_position"].pop("instance_id"); entity["map_id"] = None
    elif change == "no_click": entity["info"]["npc_flags"] = 0
    elif change == "credited": quest["objectives"][1]["is_complete"] = True
    elif change == "count_full": quest["objectives"][1]["current"] = 8
    elif change == "quest_done": quest["is_complete"] = True
    elif change == "not_accepted": quest["is_accepted"] = False
    elif change == "wrong_item": source["item_id"] = 191103
    elif change == "missing_item": source.pop("item_id")
    elif change == "vendor": source["relation"] = "VENDOR"
    elif change == "wrong_kind": source["kind"] = "GAMEOBJECT"
    elif change == "ambiguous": state["reference_knowledge"]["quests"]["65805"]["objectives"].append(deepcopy(row))
    else: row["description"] = "a different item objective"
    assert collect_spellclick_units(state) == {}


def test_flag_on_one_guid_does_not_enable_another_guid_of_the_same_entry():
    state, guid, other = scene()
    state["packet_entities"][guid]["info"]["npc_flags"] = 0
    policy = ServerNpcInteractionPolicy()
    proposal, = policy.propose(state)
    assert proposal.skill == "MOVE" and proposal.parameters["server_entity_guid"] == other
    assert kill_objective_relations(state) == {"190961": (("65805", "65805:2"),)}


@pytest.mark.parametrize("action", ["BUY", "TALK", "RIDE", "SPELLCLICK"])
def test_explicit_nonkill_mechanic_is_not_reintroduced_as_an_item_drop_hunt(action):
    state, guid, _ = scene()
    state["packet_entities"] = {}    # no live click flag can suppress a mistaken hunt
    state["reference_knowledge"]["quests"]["65805"]["objectives"][1]["credit_action"] = action
    assert "190708" not in kill_objective_relations(state)


def test_source_is_approached_on_its_real_floor_and_interacted_without_selected_target():
    state, guid, _ = scene()
    policy = ServerNpcInteractionPolicy()
    move, = policy.propose(state)
    assert move.skill == "MOVE"
    assert {key: move.parameters[key] for key in ("x", "y", "z", "instance_id")} == {
        "x": 20., "y": 0., "z": 10., "instance_id": 2444}
    assert move.parameters["require_navmesh"] and move.parameters["face_on_arrival"]
    proposal, = policy.propose(close(state, guid))
    assert proposal.skill == "INTERACT"
    assert proposal.parameters["purpose"] == "OBJECTIVE_SPELLCLICK"
    assert proposal.parameters["objective_id"] == "65805:1"
    assert proposal.parameters["item_id"] == 191102
    assert proposal.parameters["soft_guid"] == guid
    active = running(state, proposal)
    result = InteractSkill().begin(active, state)
    assert result.status is SkillStatus.RUNNING
    assert [(command.kind, command.binding) for command in result.commands] == [("BIND", "INTERACTTARGET")]


@pytest.mark.parametrize("change", ["stale", "wrong_guid", "wrong_id", "behind", "moving", "attackable"])
def test_no_f7_without_fresh_exact_recipient_and_facing_still_pose(change):
    state, guid, other = scene()
    policy = ServerNpcInteractionPolicy()
    state = close(state, guid)
    if change == "stale": state["soft_targets_sample_time"] = 90.
    elif change == "wrong_guid": state["soft_targets"][0]["guid"] = other
    elif change == "wrong_id": state["soft_targets"][0]["npc_id"] = 999
    elif change == "behind": state["orientation"] = 3.141592653589793
    elif change == "moving": state["movement"]["moving"] = True
    else: state["soft_targets"][0]["is_attackable"] = True
    proposals = policy.propose(state)
    assert not any(p.skill == "INTERACT" for p in proposals)
    if change == "behind":
        assert proposals[0].parameters["face_on_arrival"]


def test_a_new_server_item_source_interrupts_the_existing_quest_region_walk():
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    state, guid, _ = scene()
    assert objective_npc_available(state, 65805, since=99.) == guid
    assert objective_npc_available(state, 65805, since=101.) is None
    attempt = SimpleNamespace(started_at=99., proposal=SimpleNamespace(skill="MOVE", parameters={
        "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "quest_id": 65805,
        "objective_id": "65805:1", "coordinate_space": "WORLD_YARDS", "instance_id": 2444}))
    for identity_only in (True, False):
        result = movement_visual_interrupt(attempt, state, identity_only=identity_only)
        assert result["kind"] == "SERVER_OBJECTIVE_NPC_AVAILABLE" and result["guid"] == guid


@pytest.mark.parametrize("explicit_id", [None, 423599])
def test_only_the_addressed_item_counter_can_verify_partial_collection(explicit_id):
    state, guid, _ = scene()
    if explicit_id is not None:
        state["active_quests"][0]["objectives"][1]["objective_id"] = explicit_id
    state = close(state, guid)
    proposal, = ServerNpcInteractionPolicy().propose(state)
    active, skill = running(state, proposal), InteractSkill()
    assert skill.begin(active, state).commands
    credited = deepcopy(state)
    credited.update(monotonic_time=103., soft_targets_sample_time=103.)
    credited["active_quests"][0]["objectives"][1]["current"] = 1
    credited["soft_targets"] = []             # the bird can fly away after credit
    assert skill.verify(active, credited, 103.).status is SkillStatus.SUCCESS


@pytest.mark.parametrize("evidence", ["other_item", "digest", "window", "quest_complete"])
def test_unrelated_credit_or_window_is_not_plucked_item_success(evidence):
    state, guid, _ = scene()
    state = close(state, guid)
    proposal, = ServerNpcInteractionPolicy().propose(state)
    active, skill = running(state, proposal), InteractSkill()
    skill.begin(active, state)
    after = deepcopy(state)
    after.update(monotonic_time=102., soft_targets_sample_time=102.)
    if evidence == "other_item": after["active_quests"][0]["objectives"][2]["current"] = 1
    elif evidence == "digest": after["quest_digest"] = [{"id": 65805, "done": 5}]
    elif evidence == "window": after["quest_ui"] = {"open": True, "action": "OFFER", "quest_id": 42}
    else: after["active_quests"][0]["is_complete"] = True
    result = skill.verify(active, after, 102.)
    assert result.status is not SkillStatus.SUCCESS and not result.commands


def test_press_is_throttled_and_consumed_guid_stays_retired_after_other_item_progress():
    state, guid, other = scene()
    policy = ServerNpcInteractionPolicy()
    proposal, = policy.propose(close(state, guid))
    policy.note_dispatched(guid, 100.)
    state.update(monotonic_time=101., soft_targets_sample_time=101.)
    assert not any(p.skill == "INTERACT" for p in policy.propose(state))
    policy.note_item_collected(state, proposal.parameters, 103.)
    state.update(monotonic_time=150., soft_targets_sample_time=150.)
    state["active_quests"][0]["objectives"][1]["current"] = 1
    state["active_quests"][0]["objectives"][2]["current"] = 1
    next_proposal, = policy.propose(state)
    assert next_proposal.parameters["server_entity_guid"] == other
    state["session_id"] = "new-session"
    next_proposal, = policy.propose(state)
    assert next_proposal.skill == "INTERACT" and next_proposal.parameters["soft_guid"] == guid


@pytest.mark.parametrize("outcome", [Outcome.SUCCESS, Outcome.FAILURE, Outcome.CANCELLED])
def test_only_verified_terminal_success_retires_the_item_source_in_the_real_bookkeeper(outcome):
    from test_execution_bookkeeping import terminal_planner, World
    from wowbot.agent.execution_bookkeeping import ExecutionBookkeeper
    state, guid, other = scene()
    policy = ServerNpcInteractionPolicy()
    proposal, = policy.propose(close(state, guid))
    active = running(state, proposal)
    planner = terminal_planner()
    planner.quest.server_npcs = policy
    ExecutionBookkeeper().record_terminal(
        active.attempt, outcome, "skill_postcondition_verified", 103.,
        planner=planner, world=World(state), recovery_resume=None)
    candidates = {row[1]["guid"] for row in policy.candidates(state)}
    assert other in candidates
    assert (guid not in candidates) is (outcome is Outcome.SUCCESS)


def test_explicit_kill_relation_remains_when_a_separate_item_source_is_clickable():
    state, _, _ = scene()
    state["active_quests"][0]["objectives"].append({
        "description": "0/1 Bird slain", "type": "KILL", "current": 0, "required": 1})
    state["reference_knowledge"]["quests"]["65805"]["objectives"].append({
        "description": "Bird slain", "credit_kind": "CREATURE_CREDIT", "credit_object_id": 190708})
    assert kill_objective_relations(state)["190708"] == (("65805", "65805:3"),)


def test_completed_visible_item_does_not_become_hidden_work_for_other_pending_items():
    from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
    from wowbot.agent.packet_entity_facts import hidden_object_sources
    state, _, _ = scene()
    reference = state["reference_knowledge"]["quests"]["65805"]
    reference["spawn_candidates"] = [{
        "entity_kind": "GAMEOBJECT", "entry": 376152, "spawn_id": "reeds",
        "x": 80., "y": 0., "z": 10., "world_map_id": 2444, "source": "LEARNED_SPAWN"}]
    flow = ObjectInteractionFlow()
    assert hidden_object_sources(state, 65805) == []
    assert flow.remembered_object_spot(state, 65805) is None
    # A real unfinished item is still collected; this is not a blanket removal
    # of blank-description item rows or of the hidden book-chest mechanic.
    state["active_quests"][0]["objectives"][0].update(current=3, is_complete=False)
    assert hidden_object_sources(state, 65805) == [("423598", "376152")]
    assert flow.remembered_object_spot(state, 65805)["object_id"] == "376152"
