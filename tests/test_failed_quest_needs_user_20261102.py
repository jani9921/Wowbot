"""REV4 P8.4: a FAILED quest is abandoned so the giver offers it again, and
typed dead-ends are named to the user once ("I don't know, I'm telling you").

Addon 0.9.84 puts "abandon this FAILED quest" on the same AIPC quest-action
button (failed first, else the emote); the agent presses it only when the
export names exactly that quest and the log still says FAILED.  Success is
the quest leaving the known log."""
from types import SimpleNamespace

from wowbot.agent.emote_planning import EmotePolicy
from wowbot.agent.models import Proposal
from wowbot.agent.needs_user import NeedsUserLedger
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_tool import ExtraActionHandler, addon_action_ready
from test_m0_combat_loot_skills import active

BINDING = "CLICK AIPCEMOTEBUTTON:LEFTBUTTON"
CACHE = SimpleNamespace(contains=lambda action: action == BINDING)


def failed(kind="ABANDON_FAILED", is_failed=True):
    return {"monotonic_time": 10., "is_in_combat": False,
            "emote_action": {"binding": BINDING, "applied": True, "kind": kind, "quest_id": 65793},
            "active_quests": [{"quest_id": 65793, "is_failed": is_failed, "is_complete": False, "objectives": []}]}


def test_a_failed_quest_is_abandoned_with_the_addon_button_and_verified_gone():
    (abandon,) = EmotePolicy().propose(failed())
    assert abandon.skill == "ADDON_ACTION" and abandon.parameters["action_kind"] == "ABANDON_FAILED"
    assert addon_action_ready(abandon.parameters, failed(), CACHE)
    skill = ExtraActionHandler(CACHE)
    state = active("ADDON_ACTION", abandon.parameters, failed())
    begun = skill.begin(state, failed())
    assert begun.status is SkillStatus.RUNNING and begun.commands[0].binding == BINDING
    assert skill.verify(state, failed(), 2.).status is SkillStatus.RUNNING
    gone = {**failed(), "active_quests": []}
    assert skill.verify(state, gone, 3.).status is SkillStatus.SUCCESS


def test_no_abandon_unless_the_button_and_the_log_both_say_failed():
    assert EmotePolicy().propose(failed(kind="EMOTE")) == []
    assert EmotePolicy().propose(failed(is_failed=False)) == []
    (abandon,) = EmotePolicy().propose(failed())
    assert not addon_action_ready(abandon.parameters, failed(is_failed=False), CACHE)


def test_typed_dead_ends_are_journaled_once_and_listed():
    ledger, journal = NeedsUserLedger(), []
    dead = Proposal.make("WAIT", "x", {"reason": "objective_probes_exhausted", "quest_id": "26209",
                                       "objective_id": "26209:0"})
    plain = Proposal.make("WAIT", "y", {"reason": "more_data"})
    ledger.observe([dead, plain], 10.)
    ledger.report(10., lambda at, kind, payload: journal.append((kind, payload)))
    ledger.observe([dead], 11.)
    ledger.report(11., lambda at, kind, payload: journal.append((kind, payload)))
    assert [kind for kind, _ in journal] == ["OBJECTIVE_NEEDS_USER"]
    assert journal[0][1]["quest_ids"] == ["26209"] and journal[0][1]["reason"] == "objective_probes_exhausted"
    assert len(ledger.snapshot()) == 1
    ledger.observe([], 11.+901.)
    assert ledger.snapshot() == []
