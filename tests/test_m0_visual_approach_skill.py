from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import VisualApproachSkill


def active(guid="npc-1"):
    proposal = Proposal.make("VISUAL_APPROACH", "test", {"guid": guid, "track_id": "track-1", "purpose": "INTERACT"})
    attempt = Attempt("a", proposal, {}, "o", 1., 31., (), Prediction("p", "a", "ready", 1., 31., "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("VISUAL_APPROACH", proposal.parameters, guid), attempt=attempt, now=1.)
    return runtime.state


def state():
    return {"target": {"guid": "npc-1", "attackable": False}, "visual_candidates": [{
        "track_id": "track-1", "source": "WORLD3D", "x": .54, "y": .5,
        "confidence": .9, "bbox_height_fraction": .03, "lifecycle": "ACTIVE",
    }]}


def test_visual_approach_controller_is_owned_by_active_skill_context():
    skill = VisualApproachSkill()
    first = active()
    result = skill.begin(first, state(), "o1", 1.)
    assert result.status is SkillStatus.RUNNING
    assert "visual_approach_controller" in first.skill_context
    assert skill.snapshot(first)["authority"] == "ActiveSkillRuntime"

    second = active("npc-2")
    skill.begin(second, {**state(), "target": {"guid": "npc-2", "attackable": False}}, "o2", 2.)
    assert first.skill_context["visual_approach_controller"] is not second.skill_context["visual_approach_controller"]
