"""REV4 P8.2: recovery edges in the playbooks.

A failed step's typed reason names the step that repairs it (TARGET_NOT_FOUND
-> search/approach, OUT_OF_RANGE -> approach, no item -> collect), instead of
only "avoid the failed option, prefer anything else".  The bias works only
among proposals that already exist."""
from wowbot.agent.models import Proposal
from wowbot.agent.quest_attempt_memory import QuestAttemptMemory
from wowbot.agent.quest_playbooks import context_for, scores_for
from wowbot.quests.playbooks import failure_class, recovery_steps
from test_quest_playbook_runtime_20261027 import state

MOB = "Creature-0-1461-2534-147807-500-000065BDB3"
OTHER = "Creature-0-1461-2534-147807-500-000065BDB4"


def kill_state():
    value = state("KILL")
    value["packet_entities"] = {}
    return value


def candidate(skill, **params):
    return Proposal.make(skill, "existing policy candidate", {"quest_id": 10, "objective_id": "10:0", **params},
                         priority=50)


def failed(memory, proposal, value, reason, action="act:1"):
    ctx = context_for(proposal, value)
    memory.record_playbook_trial({"action_id": action, "at": 10., "episode_id": ctx.episode_id,
                                  "quest_id": "10", "objective_id": "10:0", "mechanism": ctx.book.mechanism,
                                  "step": ctx.step.name, "skill": proposal.skill, "option": ctx.option,
                                  "target_ref": ctx.target, "outcome": "FAILURE", "reason": reason,
                                  "action_verified": False, "quest_credit": False})


def test_reasons_are_classified_and_edges_name_the_repairing_step():
    assert failure_class("target_not_found") == "TARGET_MISSING"
    assert failure_class("trip_arrival_evidence_timeout:x") is None
    assert failure_class("route_endpoint_outside_arrival_envelope") == "OUT_OF_RANGE"
    assert recovery_steps("TARGET", "target_not_found") == ("TARGET_MISSING", ("APPROACH",))
    assert recovery_steps("FIGHT", "target_lost")[1][0] == "TARGET"
    assert recovery_steps("USE_ITEM", "expected_item_not_received")[1][0] == "LOOT"
    assert recovery_steps("APPROACH", "something_new") is None


def test_a_target_not_found_prefers_the_approach_over_another_blind_target():
    value, memory = kill_state(), QuestAttemptMemory()
    target = candidate("TARGET", target_guid=MOB)
    failed(memory, target, value, "target_not_found")
    approach = candidate("MOVE", server_entity_guid=MOB, x=10., y=0.)
    other = candidate("TARGET", target_guid=OTHER)
    scores = scores_for([target, approach, other], value, memory)
    assert scores[target.key]["selection"] == "avoid_failed_option" and scores[target.key]["adjustment"] < 0
    assert scores[approach.key]["selection"] == "recovery_edge" and scores[approach.key]["adjustment"] == 8.
    assert scores[approach.key]["recovery"]["class"] == "TARGET_MISSING"
    assert scores[other.key]["selection"] == "try_available_alternative" and scores[other.key]["adjustment"] == 4.


def test_a_later_success_closes_the_edge_and_an_unknown_reason_keeps_the_old_bias():
    value, memory = kill_state(), QuestAttemptMemory()
    target = candidate("TARGET", target_guid=MOB)
    failed(memory, target, value, "target_not_found")
    ctx = context_for(target, value)
    memory.record_playbook_trial({"action_id": "act:2", "at": 11., "episode_id": ctx.episode_id,
                                  "quest_id": "10", "objective_id": "10:0", "mechanism": "KILL",
                                  "step": "APPROACH", "skill": "MOVE", "option": "o2", "target_ref": MOB,
                                  "outcome": "SUCCESS", "reason": "reach_arrival_verified",
                                  "action_verified": True, "quest_credit": False})
    approach = candidate("MOVE", server_entity_guid=MOB, x=10., y=0.)
    assert scores_for([approach], value, memory)[approach.key]["selection"] == "try_available_alternative"
    unknown, memory = kill_state(), QuestAttemptMemory()
    failed(memory, target, unknown, "trip_arrival_evidence_timeout:trip_facing_not_verified")
    assert scores_for([approach], unknown, memory)[approach.key]["adjustment"] == 6.
