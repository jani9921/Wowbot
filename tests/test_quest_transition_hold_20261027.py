"""User-run 00:27-00:31: one duel at a time, then wait for the follow-up."""
from copy import deepcopy

import pytest

from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.quest_transition_hold import QuestTransitionHold
from wowbot.agent.world import WorldModel
from wowbot.verification.quest_dialog import QuestDialogVerifier
from test_sparring_gossip_20261026 import camp, AVENGER

OLD = "Creature-0-1-2444-1-186274-0000000001"
NEW = "Creature-0-1-2444-1-186274-0000000002"


def reward():
    return {"session_id": "test", "map_id": 2022, "monotonic_time": 10.,
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2444},
        "is_in_combat": False, "target": False,
        "active_quests": [{"quest_id": 7, "is_complete": True, "objectives": []}],
        "quest_ui": {"open": True, "action": "COMPLETE", "quest_id": 7, "npc_guid": False},
        "reference_knowledge": {"quests": {"7": {"quest_roles": [{"npc_id": 186274, "role": "QUEST_ENDER"}]}}},
        "packet_entities": {OLD: {"guid": OLD, "entry_id": 186274, "kind": "CREATURE", "map_id": 2444,
            "distance": 2.4, "quest_giver": {"reward_ready": True, "age": .2}}},
        "events": [{"event_type": "TARGET_CHANGED", "sequence": 1,
                    "payload": {"guid": OLD, "name": "Wrathion"}}]}


def turned_in(value, now=11.):
    value = deepcopy(value)
    value.update(monotonic_time=now, active_quests=[], quest_ui={"open": False}, target=False)
    value["packet_entities"][OLD]["removed"] = {"reason": "OUT_OF_RANGE"}
    value["packet_entities"][NEW] = {"guid": NEW, "entry_id": 186274, "kind": "CREATURE",
                                    "map_id": 2444, "distance": 2.4, "info": {"npc_flags": 1}}
    value["events"] += [
        {"event_type": "NPC_INSTRUCTION", "sequence": 2, "payload": {"guid": "", "sender": "Wrathion"}},
        {"event_type": "QUEST_TURNED_IN", "sequence": 3, "payload": {"quest_id": 7}}]
    return value


def test_single_sparring_duel_has_a_short_transition_hold_without_wave_hold():
    policy = QuestDialogPlanningPolicy()
    value = camp(dialog=True)
    policy.propose(value, None)
    assert policy.scripted_event is None
    value.update(monotonic_time=11., target=False, quest_ui={"open": False})
    hold = policy.transitions.propose(value)
    assert hold and hold.skill == "WAIT" and hold.parameters["event_npc_guid"] == AVENGER
    # No START retry/observation may renew the 15-second no-fight deadline.
    policy.transitions.arm_duel(value, 66078, AVENGER)
    value["monotonic_time"] = 26.
    assert policy.transitions.propose(value) is None


def test_duel_combat_credit_and_context_change_release_only_their_hold():
    state = camp(dialog=True)
    policy = QuestDialogPlanningPolicy()
    policy.propose(state, None)
    state.update(monotonic_time=11., is_in_combat=True, quest_ui={"open": False})
    assert policy.transitions.propose(state) is None
    state.update(monotonic_time=12., is_in_combat=False)
    assert policy.transitions.propose(state) is not None
    state["active_quests"][0]["objectives"][0]["current"] = 1
    assert policy.transitions.propose(state) is None
    policy.transitions.arm_duel(state, 66078, AVENGER)
    state["session_id"] = "new session"
    assert policy.transitions.propose(state) is None


def test_missing_hard_target_during_scripted_gossip_is_wait_not_wrong_ui():
    before = camp(dialog=True)
    after = deepcopy(before)
    after.update(target=False, quest_ui={"open": False})
    result = QuestDialogVerifier().evaluate(before, after, action="GOSSIP_OPTION_SELECT",
        quest_id=66078, target_guid=AVENGER, gossip_option_id=0, gossip_transition="SCRIPTED_COMBAT")
    assert not result.success and result.reason is None


def test_wrathion_phase_replacement_without_selected_target_still_waits():
    hold = QuestTransitionHold()
    value = reward()
    hold.observe(value)
    after = turned_in(value)
    p = hold.propose(after)
    assert p and p.skill == "WAIT" and p.parameters["purpose"] == "POST_TURNIN_TRANSITION"
    assert hold.offer["guid"] == OLD  # never transfer the original identity
    after["monotonic_time"] = 25.
    assert hold.propose(after) is not None
    # Repeated old event ring entries cannot keep the wait alive forever.
    after["monotonic_time"] = 32.
    assert hold.propose(after) is None


def test_followup_marker_releases_wait_for_current_server_entity():
    hold = QuestTransitionHold()
    value = reward()
    hold.observe(value)
    after = turned_in(value)
    assert hold.propose(after) is not None
    after["packet_entities"][NEW]["quest_giver"] = {"quest_available": True, "age": .1}
    after["monotonic_time"] = 12.
    assert hold.propose(after) is None


def test_delayed_target_event_names_the_ender_before_the_speech_page():
    value = reward()
    value["events"] = []
    hold = QuestTransitionHold()
    hold.observe(value)
    after = turned_in(value)
    after["events"].insert(0, {"event_type": "TARGET_CHANGED", "sequence": 1,
                               "payload": {"guid": OLD, "name": "Wrathion"}})
    assert hold.propose(after) is not None
    after["monotonic_time"] = 25.
    assert hold.propose(after) is not None
    assert hold.offer["names"] == {"wrathion"}


@pytest.mark.parametrize("kind", ["other_speaker", "old_speech", "no_speech"])
def test_unrelated_or_pre_turnin_speech_cannot_extend_first_offer_wait(kind):
    value = reward()
    if kind == "old_speech":
        value["events"].append({"event_type": "NPC_INSTRUCTION", "sequence": 0,
                                "payload": {"sender": "Wrathion"}})
    hold = QuestTransitionHold()
    hold.observe(value)
    after = turned_in(value)
    after["events"] = [e for e in after["events"] if e["event_type"] != "NPC_INSTRUCTION"]
    if kind == "other_speaker":
        after["events"].append({"event_type": "NPC_INSTRUCTION", "sequence": 4,
                                "payload": {"sender": "Random NPC"}})
    assert hold.propose(after) is not None
    after["monotonic_time"] = 20.
    # Old speech observed before the actual turn-in is not a new speech line.
    assert hold.propose(after) is None


def test_planner_hold_prevents_move_target_swap_and_mount_before_followup():
    value = reward()
    from wowbot.agent.skills import SkillRegistry
    planner = Planner(SkillRegistry())
    world = WorldModel()
    world.state.update(value)
    planner.quest.dialog_policy.propose(value, None)
    after = turned_in(value)
    world.state.update(after)
    proposals = planner._candidates(Goal.parse("Questelj", 11.), world, 11.)
    assert [p.skill for p in proposals] == ["WAIT"]
    assert proposals[0].parameters["purpose"] == "POST_TURNIN_TRANSITION"


def test_ambiguous_giver_and_other_map_are_not_assumed_to_be_the_turnin():
    value = reward()
    value["reference_knowledge"] = {}
    value["packet_entities"][NEW] = {**deepcopy(value["packet_entities"][OLD]), "guid": NEW}
    hold = QuestTransitionHold()
    hold.observe(value)
    assert hold.offer is None
    value["packet_entities"].pop(NEW)
    value["packet_entities"][OLD]["map_id"] = 9999
    hold.observe(value)
    assert hold.offer is None


def test_combat_bypasses_the_followup_hold_and_safety_deadline_is_bounded():
    value = reward()
    hold = QuestTransitionHold()
    hold.observe(value)
    after = turned_in(value)
    after["is_in_combat"] = True
    assert hold.propose(after) is None
    after.update(monotonic_time=200., is_in_combat=False)
    assert hold.propose(after) is None
