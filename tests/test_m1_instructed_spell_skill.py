from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import InstructedSpellSkill


class _Bindings:
    def __init__(self, actions=("ACTIONBUTTON3",)):
        self.actions = set(actions)

    def contains(self, action):
        return action in self.actions


def _state(*, action_name="Fire Blast", target_guid="Creature-training"):
    return {
        "target": {"guid": target_guid, "attackable": True, "dead": False},
        "actionbar": [{"kind": "spell", "id": 108853, "name": action_name,
                       "action": "ACTIONBUTTON3", "is_usable": True,
                       "in_range": True, "cooldown_remaining": 0}],
    }


def _active():
    params = {
        "guid": "Creature-training", "binding": "ACTIONBUTTON3", "spell_id": 108853,
        "instruction": "Use Fire Blast on the training target.",
        "quest_ids": [77], "objective_ids": ["77:cast"],
    }
    before = {**_state(), "active_quests": [{"quest_id": 77, "objectives": [
        {"objective_id": "cast", "current": 0, "required": 1, "is_complete": False},
    ]}]}
    attempt = Attempt("action", Proposal.make("FOLLOW_INSTRUCTION", "test", params), before,
                      "obs", 1.0, 5.0, (), Prediction("prediction", "action", "state", 1., 5., "obs"))
    return ActiveSkillRuntime().start(
        intent=Intent("FOLLOW_INSTRUCTION", params, "Creature-training", "77:cast"),
        attempt=attempt, now=1.0, before_snapshot=before,
    )


def test_instructed_spell_requires_exact_live_spell_cache_and_quest_credit():
    skill, state = InstructedSpellSkill(_Bindings()), _active()
    started = skill.begin(state, _state())
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].binding == "ACTIONBUTTON3"
    assert skill.verify(state, _state(), 2.0).status is SkillStatus.RUNNING
    credited = {**_state(), "active_quests": [{"quest_id": 77, "objectives": [
        {"objective_id": "cast", "current": 1, "required": 1, "is_complete": True},
    ]}]}
    result = skill.verify(state, credited, 3.0)
    assert result.status is SkillStatus.SUCCESS
    assert result.evidence == ("objective_changed:77:cast",)


def test_instructed_spell_fails_closed_without_selected_cache_or_exact_instruction_action():
    assert InstructedSpellSkill().begin(_active(), _state()).status is SkillStatus.BLOCKED
    assert InstructedSpellSkill(_Bindings()).begin(_active(), _state(action_name="Arcane Blast")).status is SkillStatus.FAILURE
