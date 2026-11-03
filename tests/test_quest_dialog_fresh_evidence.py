"""A current FAST button is not stale merely because STATE paging stalled."""
from copy import deepcopy
import json

import pytest

from adapters.telemetry_packets import PacketAssembler
from wowbot.agent.models import Attempt, Observation, Prediction, Proposal
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import QuestDialogSkill


def _world(action="CONTINUE", *, receive_offset=0.):
    assembler = PacketAssembler()
    full = {"monotonic_time": 1., "character_guid": "Player-test",
            "active_quests": [{"quest_id": 42, "objectives": []}],
            "quest_ui": {"open": True, "action": "ACCEPT", "quest_id": 99,
                         "x": .2, "y": .3}}
    world = WorldModel()
    world.ingest(Observation.create(assembler.feed(
        "AIPC5|test|1|0|1|STATE|" + json.dumps(full), 1.+receive_offset), 1.+receive_offset))
    fast = {"monotonic_time": 71., "quest_ui": {
        "open": True, "action": action, "quest_id": 42, "x": .41, "y": .72}}
    packet = assembler.feed("AIPC5|test|2|0|1|FAST|" + json.dumps(fast), 71.+receive_offset)
    world.ingest(Observation.create(packet, 71.+receive_offset))
    return world, assembler


def _active(proposal, before, now=71.):
    attempt = Attempt("test", proposal, {}, "before", now, now+10., (),
                      Prediction("prediction", "test", "state", now, now+10., "before"))
    return ActiveSkillRuntime().start(intent=Intent(proposal.skill, proposal.parameters),
                                      attempt=attempt, now=now, before_snapshot=before)


@pytest.mark.parametrize("action", ["CONTINUE", "COMPLETE", "TURN_IN"])
def test_fresh_fast_button_survives_old_state_and_is_rechecked_by_executor(action):
    world, _ = _world(action)
    proposal = next(p for p in QuestDialogPlanningPolicy().propose(world.state, None)
                    if p.skill == "QUEST_DIALOG")
    assert world.state["state_age"] == 70.
    assert SkillRegistry().available(proposal, world)
    result = QuestDialogSkill().begin(_active(proposal, world.state), world.state)
    assert result.status is SkillStatus.RUNNING
    assert result.commands[0].x == .41 and result.commands[0].y == .72


@pytest.mark.parametrize("change", ["expired", "future", "receive_expired", "session", "point", "action",
                                    "quest", "closed", "missing", "nan"])
def test_stale_or_mismatched_fast_button_cannot_bypass_state_guard(change):
    world, _ = _world()
    proposal = Proposal.make("QUEST_DIALOG", "test", {
        "action": "CONTINUE", "quest_id": 42, "x": .41, "y": .72})
    state = deepcopy(world.state)
    if change == "expired":
        state["monotonic_time"] = 72.
    elif change == "future":
        state["monotonic_time"] = 70.
    elif change == "receive_expired":
        state["quest_ui_fast_evidence"]["received_at"] = 60.
    elif change == "session":
        state["session_id"] = "other-session"
    elif change == "point":
        proposal = Proposal.make("QUEST_DIALOG", "moved", {**proposal.parameters, "x": .51})
    elif change == "action":
        state["quest_ui"]["action"] = "COMPLETE"
    elif change == "quest":
        state["quest_ui"]["quest_id"] = 99
    elif change == "closed":
        state["quest_ui_open"] = False
        state["quest_ui"]["open"] = False
    elif change == "missing":
        state.pop("quest_ui_fast_evidence", None)
    elif change == "nan":
        state["monotonic_time"] = float("nan")
    world.state = state
    assert not SkillRegistry().available(proposal, world)
    result = QuestDialogSkill().begin(_active(proposal, state), state)
    assert result.commands == ()


@pytest.mark.parametrize("action", ["ACCEPT", "REWARD_SELECT", "GOSSIP_SELECT", "GOSSIP_OPTION_SELECT"])
def test_detail_dependent_actions_still_require_current_state(action):
    world, _ = _world(action)
    proposal = Proposal.make("QUEST_DIALOG", "test", {
        "action": action, "quest_id": 42, "x": .41, "y": .72})
    assert not SkillRegistry().available(proposal, world)
    assert not QuestDialogSkill().begin(_active(proposal, world.state), world.state).commands


def test_packet_without_ui_does_not_refresh_carried_button_evidence():
    world, assembler = _world()
    old = deepcopy(world.state.get("quest_ui_fast_evidence"))
    packet = assembler.feed('AIPC5|test|3|0|1|FAST|{"monotonic_time":73}', 73.)
    assert "quest_ui_fast_evidence" not in packet
    world.ingest(Observation.create(packet, 73.))
    assert world.state.get("quest_ui_fast_evidence") == old
    proposal = Proposal.make("QUEST_DIALOG", "test", {
        "action": "CONTINUE", "quest_id": 42, "x": .41, "y": .72})
    assert not SkillRegistry().available(proposal, world)


def test_addon_sample_clock_and_python_receive_clock_are_not_compared_to_each_other():
    world, _ = _world(receive_offset=1000.05)
    proposal = Proposal.make("QUEST_DIALOG", "test", {
        "action": "CONTINUE", "quest_id": 42, "x": .41, "y": .72})
    assert SkillRegistry().available(proposal, world)
    result = QuestDialogSkill().begin(_active(proposal, world.state, now=1071.1), world.state)
    assert result.commands
