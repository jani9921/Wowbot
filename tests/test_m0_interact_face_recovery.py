from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import InteractSkill


def _active():
    proposal = Proposal.make("INTERACT", "test", {"guid": "npc-1"})
    before = {"target": {"guid": "npc-1"}, "quest_ui": {"open": False}}
    attempt = Attempt("a", proposal, before, "o", 1., 5., (), Prediction("p", "a", "dialog", 1., 5., "o"))
    return ActiveSkillRuntime().start(intent=Intent("INTERACT", {"guid": "npc-1"}, "npc-1"),
                                      attempt=attempt, now=1., before_snapshot=before)


def test_interact_performs_one_same_attempt_face_recovery_then_retries_interact():
    skill, state = InteractSkill(), _active()
    assert skill.begin(state, {"target": {"guid": "npc-1"}}).status is SkillStatus.RUNNING
    facing = skill.verify(state, {"target": {"guid": "npc-1", "screen_position": {"x": .8}},
                                  "ui_error": "You must face the target."}, 2.)
    assert facing.status is SkillStatus.RUNNING
    assert facing.metadata["local_face_request"]["expected_guid"] == "npc-1"
    retry = skill.verify(state, {"target": {"guid": "npc-1", "screen_position": {"x": .8}}}, 2.2)
    assert retry.status is SkillStatus.RUNNING
    assert retry.commands[0].binding == "INTERACTTARGET"


def test_interact_does_not_loop_facing_recovery_after_two_attempt_budget():
    skill, state = InteractSkill(), _active()
    skill.begin(state, {"target": {"guid": "npc-1"}})
    skill.verify(state, {"target": {"guid": "npc-1", "screen_position": {"x": .8}},
                         "ui_error": "You must face the target."}, 2.)
    skill.verify(state, {"target": {"guid": "npc-1", "screen_position": {"x": .8}}}, 2.2)
    assert skill.verify(state, {"target": {"guid": "npc-1", "screen_position": {"x": .8}},
                                "ui_error": "You must face the target."}, 2.4).status is SkillStatus.RUNNING
    skill.verify(state, {"target": {"guid": "npc-1", "screen_position": {"x": .8}}}, 2.6)
    result = skill.verify(state, {"target": {"guid": "npc-1", "screen_position": {"x": .8}},
                                  "ui_error": "You must face the target."}, 2.8)
    assert result.status is SkillStatus.FAILURE
