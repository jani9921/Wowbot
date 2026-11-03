from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Attempt, Goal, Observation, Outcome, Prediction, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.proposal_ranking import ProposalRanker
from wowbot.agent.quest_attempt_memory import QuestAttemptMemory
from wowbot.agent.quest_playbooks import context_for, horizon_for, record_trial, scores_for
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.quest_terminal import QuestTerminalProcessor
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.quests.playbooks import PLAYBOOKS
from wowbot.verification.quest import QuestProgressVerifier


GUID = "GameObject-0-1461-2534-147807-377013-000060A8EF"


def state(mechanism="OBJECT_USE"):
    return {"session_id": "playbook:player", "monotonic_time": 10., "map_id": 2022,
        "player_present": True, "orientation": 0., "target": False, "mouseover": False,
        "player_world_position": {"x": 0., "y": 0., "z": 5., "instance_id": 2444},
        "active_quests": [{"quest_id": 10, "is_complete": False, "objectives": [
            {"description": "0/1 Activate the forge", "type": "KILL", "current": 0,
             "required": 1, "is_complete": False}]}],
        "reference_knowledge": {"quests": {"10": {"objectives": [
            {"objective_id": 400, "order": 7, "description": "Activate the forge",
             "mechanism": mechanism, "credit_object_id": 377013}]}}},
        "packet_entities": {GUID: {"guid": GUID, "kind": "GAMEOBJECT", "entry_id": 377013, "map_id": 2444}}}


def proposal(skill="OBJECT_USE", **params):
    return Proposal.make(skill, "existing policy candidate",
        {"quest_id": 10, "object_guid": GUID, "object_id": 377013, **params}, priority=50)


def attempt(candidate, before, action="act:1"):
    return Attempt(action, candidate, deepcopy(before), "obs:before", 10., 20., (),
        Prediction("pred:"+action, action, "expected", 10., 20., "obs:before"))


def world(value):
    result = WorldModel()
    result.ingest(Observation.create(value, 10.))
    return result


class Registry:
    contracts = {key: SimpleNamespace(cost=0.) for key in ("MOVE", "OBJECT_USE", "INTERACT", "WAIT_EVENT", "WAIT")}

    @staticmethod
    def available(item, _world):
        return item.parameters.get("available", True)


def rank(items, value, memory, *, blocked=None):
    return ProposalRanker.rank(items, goal=Goal.parse("Questelj", 1.), world=world(value), now=10.,
        registry=Registry(), memory=None, blocked_until=blocked or {}, recent={}, evidence=("fresh",),
        playbook_guidance=scores_for(items, value, memory))


def test_forecast_uses_the_quest_mechanism_instead_of_a_proxy_kill_label():
    value = state("CREDIT_OBJECT")
    candidate = proposal("INTERACT", object_guid=None, object_id=None, npc_id=42)
    candidate = Proposal.make(candidate.skill, candidate.reason,
        {**candidate.parameters, "objective_id": "10:0"})
    steps = Planner(SkillRegistry()).plan_horizon(candidate, world(value))
    assert "OBJECT_USE" in {row["capability"] for row in steps}
    assert "COMBAT" not in {row["capability"] for row in steps}
    assert all(row["status"] == "BLOCKED_BY_PRIOR_STEP" for row in steps[1:])


def test_known_transport_gets_board_then_observe_without_hover_or_attack():
    value = state("ARRIVE")
    value["active_quests"][0]["objectives"][0]["description"] = "0/1 Travel with Wrathion to the Throne"
    value["reference_knowledge"]["quests"]["10"]["objectives"][0]["description"] = "Travel with Wrathion to the Throne"
    candidate = proposal("INTERACT", object_id=None, interaction_kind="RIDE", expected_result="VEHICLE_ENTERED")
    ctx, stages = horizon_for(candidate, value)
    assert ctx.book.mechanism == "NPC_TRANSPORT" and ctx.step.name == "BOARD"
    assert [s["capability"] for s in stages] == ["WAIT_EVENT"]


def test_md_only_handlers_are_not_executable_capabilities():
    registry = SkillRegistry()
    for book in PLAYBOOKS.values():
        for step in book.steps:
            assert set(step.skills) <= set(registry.contracts)
    # REV4 P8.4/8.5 (2026-11-02): ESCORT, EMOTE, COLLECT_CONTAINER and the
    # unknown-source probes gained handlers; these remain written-only.
    for missing in ("PET_BATTLE", "PVP", "RESOURCE", "OTHER"):
        assert PLAYBOOKS[missing].steps == () and PLAYBOOKS[missing].missing
        assert context_for(proposal(), state(missing)) is None


def test_the_escort_book_never_forecasts_a_kill_and_loot_for_its_proxy_credit():
    # P8.4 (2026-11-02): the escort has a handler; its fight is the defence of
    # the escorted unit (its attackers only), never a KILL+LOOT of the credit.
    value = state("ESCORT")
    stages = Planner(SkillRegistry()).plan_horizon(proposal("MOVE"), world(value))
    assert [row.get("playbook_step") for row in stages][:1] == ["FOLLOW"]
    assert "LOOT" not in {row["capability"] for row in stages}
    defend = next(row for row in stages if row.get("playbook_step") == "DEFEND")
    assert "escort_attacker_targets_escort" in defend["preconditions"]


def test_hidden_reference_rows_are_matched_by_text_not_the_visible_array_index():
    value = state()
    value["reference_knowledge"]["quests"]["10"]["objectives"].insert(0,
        {"objective_id": 399, "order": 0, "description": "[DNT] Kill proxy", "mechanism": "KILL"})
    assert context_for(proposal(), value).book.mechanism == "OBJECT_USE"


def test_ambiguous_objectives_do_not_receive_guessed_playbook_or_trial():
    value = state()
    value["active_quests"][0]["objectives"].append({"description": "Another object", "current": 0, "required": 1,
        "is_complete": False, "mechanism": "OBJECT_USE"})
    item = Proposal.make("OBJECT_USE", "no objective or entry", {"quest_id": 10})
    assert context_for(item, value) is None
    assert record_trial(attempt(item, value), Outcome.FAILURE, "no_response", value, 11., QuestAttemptMemory()) is None


def test_explicit_objective_can_disambiguate_several_pending_objectives():
    value = state()
    value["active_quests"][0]["objectives"].append({"description": "Another object", "is_complete": False,
        "mechanism": "OBJECT_USE"})
    assert context_for(proposal(objective_id="10:1"), value).objective_id == "10:1"


def test_failed_option_prefers_an_existing_alternative_and_explains_why():
    value, memory = state(), QuestAttemptMemory()
    failed = proposal("MOVE", x=3., y=0., coordinate_space="WORLD_YARDS", server_entity_guid=GUID)
    different = proposal()
    record_trial(attempt(failed, value), Outcome.FAILURE, "facing_failed", value, 11., memory)
    result = rank([failed, different], value, memory)
    assert result.proposals[0].key == different.key
    assert result.scores[different.key]["quest_playbook"]["selection"] == "try_available_alternative"
    assert result.scores[failed.key]["quest_playbook"]["selection"] == "avoid_failed_option"
    assert len(result.proposals) == 2


@pytest.mark.parametrize("restriction", ["cooldown", "unavailable"])
def test_playbook_does_not_bypass_executor_preconditions_or_cooldowns(restriction):
    value, memory = state(), QuestAttemptMemory()
    failed = proposal("MOVE", server_entity_guid=GUID)
    record_trial(attempt(failed, value), Outcome.FAILURE, "facing_failed", value, 11., memory)
    alternative = proposal(available=restriction != "unavailable")
    result = rank([alternative], value, memory, blocked={alternative.key: 20.} if restriction == "cooldown" else None)
    assert [p.skill for p in result.proposals] == ["WAIT"]


def test_guidance_never_changes_proposal_key_or_grants_another_retry_chain():
    value, memory = state(), QuestAttemptMemory()
    candidate = proposal()
    before = (candidate.key, candidate.parameters_json)
    for index in range(3):
        record_trial(attempt(candidate, value, f"failed:{index}"), Outcome.FAILURE, "no_response", value, 11.+index, memory)
    guidance = scores_for([candidate], value, memory)[candidate.key]
    assert guidance["prior_failures"] == 3 and guidance["adjustment"] == -12.
    assert (candidate.key, candidate.parameters_json) == before


def test_frame_time_camera_and_player_movement_do_not_reset_failed_option():
    value, memory = state(), QuestAttemptMemory()
    candidate = proposal()
    record_trial(attempt(candidate, value), Outcome.FAILURE, "no_response", value, 11., memory)
    later = deepcopy(value)
    later.update(monotonic_time=100., frame_id="other", orientation=2.)
    later["player_world_position"]["x"] = 20.
    assert scores_for([candidate], later, memory)[candidate.key]["prior_failures"] == 1


def test_new_progress_or_session_does_not_inherit_the_previous_step_failure():
    value, memory = state(), QuestAttemptMemory()
    candidate = proposal()
    record_trial(attempt(candidate, value), Outcome.FAILURE, "no_response", value, 11., memory)
    for fresh in ("progress", "session"):
        later = deepcopy(value)
        if fresh == "progress":
            later["active_quests"][0]["objectives"][0].update(current=1, required=3)
        else:
            later["session_id"] = "other player"
        assert scores_for([candidate], later, memory)[candidate.key]["prior_failures"] == 0


def test_alternate_contact_keeps_the_same_episode_but_records_the_probe():
    value = state()
    a = context_for(proposal("MOVE", object_approach_probe=1, server_entity_guid=GUID), value)
    b = context_for(proposal("MOVE", object_approach_probe=2, server_entity_guid=GUID), value)
    assert a.episode_id == b.episode_id and a.option != b.option


def test_terminal_journal_links_failed_approach_to_verified_use_and_real_credit():
    value, memory = state(), QuestAttemptMemory()
    failed = record_trial(attempt(proposal("MOVE"), value, "move:bad"), Outcome.FAILURE, "facing_failed", value, 11., memory)
    after = deepcopy(value)
    after["active_quests"][0]["objectives"][0].update(current=1, is_complete=True)
    used = record_trial(attempt(proposal(), value, "use:good"), Outcome.SUCCESS, "object_use_credit_verified", after, 13., memory)
    assert failed["quest_credit"] is False
    assert used["after_failed_action"] == "move:bad" and used["action_verified"] and used["quest_credit"]
    assert used["episode_id"] == failed["episode_id"]


def test_dialog_success_or_other_objective_progress_is_not_claimed_as_this_quest_credit():
    value, memory = state("TALK"), QuestAttemptMemory()
    item = proposal("INTERACT", object_id=None, objective_id="10:0")
    value["active_quests"][0]["objectives"].append({"description": "Unrelated", "current": 0, "required": 1, "is_complete": False})
    after = deepcopy(value)
    after["gossip_ui"] = {"open": True}
    after["active_quests"][0]["objectives"][1].update(current=1, is_complete=True)
    row = record_trial(attempt(item, value), Outcome.SUCCESS, "dialog_opened", after, 11., memory)
    assert row["action_verified"] and row["quest_credit"] is False


def test_trials_are_deduplicated_bounded_and_cleared_with_the_shared_memory():
    value, memory = state(), QuestAttemptMemory()
    one = attempt(proposal(), value)
    assert record_trial(one, Outcome.FAILURE, "no_response", value, 11., memory)
    assert record_trial(one, Outcome.FAILURE, "no_response", value, 11., memory) is None
    for index in range(260):
        record_trial(attempt(proposal(), value, f"other:{index}"), Outcome.FAILURE, "no_response", value, 12.+index, memory)
    assert len(memory.playbook_snapshot()) == 256
    memory.reset()
    assert memory.playbook_snapshot() == []


def test_real_quest_terminal_processor_emits_the_trial_and_keeps_one_memory_owner():
    value = state()
    domain = QuestDomain()
    runtime = SimpleNamespace(record_failure=lambda **kw: None, record_success=lambda **kw: None)
    processor = QuestTerminalProcessor(QuestProgressVerifier(), runtime, domain)
    result = processor.process(attempt(proposal(), value), Outcome.FAILURE, "out_of_range", value,
        Goal.parse("Questelj", 1.), 11.)
    event = next(payload for name, payload in result.events if name == "QUEST_PLAYBOOK_TRIAL")
    assert event == domain.attempt_memory.playbook_snapshot()[0]
    assert event["reason"] == "out_of_range"


def test_real_planner_ranking_consumes_the_shared_trial_memory():
    value = state()
    planner = Planner(SkillRegistry())
    candidate = proposal()
    record_trial(attempt(candidate, value), Outcome.FAILURE, "out_of_range", value, 11., planner.quest_attempt_memory)
    registry = Registry()
    planner.registry = registry
    planner._rank_candidates([candidate], Goal.parse("Questelj", 1.), world(value), 12., ("obs",))
    assert planner.last_scores[candidate.key]["quest_playbook"]["prior_failures"] == 1


def test_open_credit_object_uses_object_stage_without_returning_to_its_unlocking_npc():
    value = state("CREDIT_OBJECT")
    ctx, stages = horizon_for(proposal("INTERACT"), value)
    assert ctx.step.name == "USE_OBJECT" and stages == ()


def test_real_server_ride_proposal_connects_to_the_travel_playbook_without_hover():
    from test_coal_turn_transport_20261027 import riding
    from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy

    value = riding()
    value["reference_knowledge"]["quests"]["66057"]["objectives"] = [{
        "objective_id": 428610, "order": 1, "mechanism": "ARRIVE",
        "description": "Travel with Wrathion to the Throne"}]
    (candidate,) = ServerNpcInteractionPolicy().propose(value)
    assert candidate.skill == "INTERACT" and candidate.parameters["expected_result"] == "VEHICLE_ENTERED"
    ctx = context_for(candidate, value)
    assert ctx.book.mechanism == "NPC_TRANSPORT" and ctx.step.name == "BOARD"
    assert ctx.objective_id == "66057:1" and value["mouseover"] is False


def test_friendly_gossip_actor_forecasts_dialog_before_combat_without_granting_attack():
    value = state("GOSSIP_ACTOR")
    candidate = proposal("MOVE")
    ctx, stages = horizon_for(candidate, value)
    assert ctx.book.mechanism == "GOSSIP_ACTOR"
    assert [s["capability"] for s in stages] == ["INTERACT", "QUEST_DIALOG", "COMBAT"]
    assert all("live_candidate_and_skill_preconditions" in s["preconditions"] for s in stages)


@pytest.mark.parametrize("outcome", [Outcome.FAILURE, Outcome.SUCCESS])
def test_old_location_commitment_does_not_hide_a_ready_same_objective_use(outcome):
    from wowbot.agent.autonomy_loop import AutonomousLoop

    value, memory = state(), QuestAttemptMemory()
    live, goal, loop = world(value), Goal.parse("Questelj", 1.), AutonomousLoop()
    move = proposal("MOVE", x=3., y=0., coordinate_space="WORLD_YARDS", server_entity_guid=GUID)
    loop.choose([move], move, goal, live, 10.)
    assert loop.commitment.kind == "LOCATION"
    record_trial(attempt(move, value), outcome, "facing_failed" if outcome == Outcome.FAILURE else "server_quest_object_ready",
        value, 11., memory)
    use = proposal()
    ranked = rank([move, use], value, memory)
    chosen = loop.choose(list(ranked.proposals), ranked.proposals[0], goal, live, 11., scores=ranked.scores)
    assert chosen.skill == "OBJECT_USE"


def test_an_unrelated_quest_cannot_release_a_location_through_playbook_guidance():
    from wowbot.agent.autonomy_loop import AutonomousLoop

    value, memory = state(), QuestAttemptMemory()
    live, goal, loop = world(value), Goal.parse("Questelj", 1.), AutonomousLoop()
    move = Proposal.make("MOVE", "other quest", {"quest_id": 99, "x": 3., "y": 0.})
    loop.choose([move], move, goal, live, 10.)
    record_trial(attempt(proposal("MOVE"), value), Outcome.FAILURE, "facing_failed", value, 11., memory)
    use = proposal()
    ranked = rank([use], value, memory)
    chosen = loop.choose(list(ranked.proposals), ranked.proposals[0], goal, live, 10.2, scores=ranked.scores)
    assert chosen.skill == "WAIT" and loop.commitment.kind == "LOCATION"


def test_target_commitment_keeps_guid_but_honors_alternative_ranking():
    from wowbot.agent.autonomy_loop import AutonomousLoop

    value, memory = state("TALK"), QuestAttemptMemory()
    guid = "Creature-0-1461-2534-147807-42-000060A8EF"
    value["target"] = {"guid": guid, "npc_id": 42, "name": "Actor", "attackable": False,
        "screen_position": {"x": .5, "y": .5, "sample_time": 10., "source": "NAMEPLATE_API",
                            "coordinate_space": "CLIENT_BOTTOM_LEFT"}}
    live, goal, loop = world(value), Goal.parse("Questelj", 1.), AutonomousLoop()
    interact = proposal("INTERACT", object_guid=None, object_id=None, guid=guid)
    approach = proposal("APPROACH_TARGET", object_guid=None, object_id=None, guid=guid)
    loop.choose([interact], interact, goal, live, 10.)
    identity = loop.commitment.commitment_id
    assert loop.commitment.kind == "TARGET"
    record_trial(attempt(interact, value), Outcome.FAILURE, "no_response", value, 11., memory)
    ranked = rank([interact, approach], value, memory)
    chosen = loop.choose(list(ranked.proposals), ranked.proposals[0], goal, live, 11., scores=ranked.scores)
    assert chosen.skill == "APPROACH_TARGET" and loop.commitment.target_guid == guid
    assert loop.commitment.commitment_id == identity


def test_talk_and_interact_with_the_same_key_do_not_count_as_different_solutions():
    value, memory = state("TALK"), QuestAttemptMemory()
    interact = proposal("INTERACT", object_id=None, activation_source="SOFT_INTERACT", purpose="SERVER_OBJECTIVE_NPC")
    talk = proposal("TALK", object_id=None, activation_source="INTERACT_KEY", purpose="TALK_OBJECTIVE")
    assert context_for(interact, value).option == context_for(talk, value).option
    record_trial(attempt(interact, value), Outcome.FAILURE, "no_response", value, 11., memory)
    assert scores_for([talk], value, memory)[talk.key]["selection"] == "avoid_failed_option"
