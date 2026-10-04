from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import InteractSkill
from wowbot.skills.interact import InteractPhase


def active(*, target="npc-1", deadline=5):
    proposal = Proposal.make("INTERACT", "test", {"guid": "npc-1"})
    before = {"target": {"guid": target}, "active_quests": [], "quest_ui": {"open": False}}
    attempt = Attempt("a", proposal, before, "o", 1, deadline, (), Prediction("p", "a", "dialog", 1, deadline, "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("INTERACT", {"guid": "npc-1"}, "npc-1"), attempt=attempt, now=1,
                  before_snapshot=before)
    return runtime.state


def test_interaction_engine_exposes_complete_m2_fsm():
    assert {phase.value for phase in InteractPhase} == {
        "IDLE", "RESOLVE_TARGET", "APPROACH", "FACE", "HOVER",
        "VERIFY_HOVER", "INTERACT", "WAIT_RESULT", "CLASSIFY_RESULT",
        "RECOVER", "SUCCESS", "FAILED",
    }


def test_interact_requires_selected_expected_target():
    result = InteractSkill().begin(active(target="other"), {"target": {"guid": "other"}})
    assert result.status is SkillStatus.FAILURE


def test_interact_rejects_explicitly_low_identity_confidence_or_hostile_target():
    low = InteractSkill().begin(active(), {"target": {"guid": "npc-1", "identity_confidence": .5}})
    assert low.status is SkillStatus.FAILURE and low.reason.value == "LOW_CONFIDENCE"
    hostile = InteractSkill().begin(active(), {"target": {"guid": "npc-1", "attackable": True}})
    assert hostile.status is SkillStatus.FAILURE and hostile.reason.value == "NOT_INTERACTABLE"


def test_interact_succeeds_only_on_ui_or_quest_delta():
    skill, state = InteractSkill(), active()
    assert skill.begin(state, {"target": {"guid": "npc-1"}}).commands[0].binding == "INTERACTTARGET"
    assert skill.verify(state, {"target": {"guid": "npc-1"}, "active_quests": [], "quest_ui": {"open": False}}, 2).status is SkillStatus.RUNNING
    result = skill.verify(state, {"target": {"guid": "npc-1"}, "active_quests": [],
                                  "quest_ui": {"open": True, "action": "OFFER", "quest_id": 1}}, 2)
    assert result.status is SkillStatus.SUCCESS


def test_interact_requires_fresh_same_guid_hover_before_interacting_when_anchor_exists():
    skill, state = InteractSkill(), active()
    world = {"target": {"guid": "npc-1", "screen_position": {"x": .5, "y": .6}},
             "monotonic_time": 1.}
    started = skill.begin(state, world)
    assert started.commands[0].kind == "HOVER"
    waiting = skill.verify(state, {**world, "monotonic_time": 1.05}, 1.05)
    assert waiting.status is SkillStatus.RUNNING and not waiting.commands
    verified = skill.verify(state, {**world, "monotonic_time": 1.2,
                                    "mouseover": {"guid": "npc-1"}, "mouseover_sample_time": 1.2}, 1.2)
    assert verified.commands[0].binding == "INTERACTTARGET"
    assert verified.metadata["hover_verified"] is True


def test_interact_hover_sampling_is_bounded_and_never_clicks_after_four_misses():
    skill, state = InteractSkill(), active()
    world = {"target": {"guid": "npc-1", "screen_position": {"x": .5, "y": .6}},
             "monotonic_time": 1.}
    assert skill.begin(state, world).commands[0].kind == "HOVER"
    result = None
    for now in (.2, .4, .6, .8):
        result = skill.verify(state, {**world, "monotonic_time": 1 + now}, 1 + now)
    assert result.status is SkillStatus.FAILURE
    assert result.reason.value == "LOW_CONFIDENCE"


def test_interact_expected_result_rejects_wrong_opened_ui():
    skill, state = InteractSkill(), active()
    state.intent = type(state.intent)("INTERACT", {"guid": "npc-1", "expected_result": "GOSSIP_OPEN"}, "npc-1")
    skill.begin(state, {"target": {"guid": "npc-1"}})
    result = skill.verify(state, {"target": {"guid": "npc-1"},
                                  "quest_ui": {"open": True, "action": "OFFER", "quest_id": 1}}, 2.)
    assert result.status is SkillStatus.FAILURE
    assert result.reason.value == "WRONG_UI"


def test_interact_reports_range_and_timeout_as_typed_results():
    skill, state = InteractSkill(), active()
    skill.begin(state, {"target": {"guid": "npc-1"}})
    assert skill.verify(state, {"target": {"guid": "npc-1"}, "ui_error": "Out of range"}, 2).reason.value == "OUT_OF_RANGE"
    state = active(deadline=2)
    skill.begin(state, {"target": {"guid": "npc-1"}})
    assert skill.verify(state, {"target": {"guid": "npc-1"}}, 2).reason.value == "NO_RESPONSE"


def test_interact_keeps_same_attempt_and_requests_canonical_world_approach_after_range_error():
    skill, state = InteractSkill(), active()
    skill.begin(state, {"target": {"guid": "npc-1"}})
    world = {
        "target": {"guid": "npc-1", "world_position": {"x": 12., "y": 8., "z": 3., "instance_id": 7}},
        "player_world_position": {"x": 1., "y": 1., "z": 3., "instance_id": 7},
        "ui_error": "You need to be closer to interact with that target.",
    }
    result = skill.verify(state, world, 2.)
    assert result.status is SkillStatus.RUNNING
    assert result.metadata["approach_request"] == {
        "kind": "WORLD_ENTITY", "expected_guid": "npc-1", "stop_distance": 4.5,
    }
    assert state.phase == "APPROACH"
    resumed = skill.resume_after_approach(state, world)
    assert resumed.status is SkillStatus.RUNNING
    assert resumed.commands[0].binding == "INTERACTTARGET"
    assert state.local_retry_count == 1


def test_interact_uses_only_fresh_verified_visual_anchor_without_world_coordinates():
    skill, state = InteractSkill(), active()
    skill.begin(state, {"target": {"guid": "npc-1"}})
    anchor = {"x": .71, "y": .48, "sample_time": 8., "track_id": "world3d:7",
              "coordinate_space": "CLIENT_BOTTOM_LEFT", "source": "CONFIRMED_MOUSEOVER_ANCHOR"}
    result = skill.verify(state, {
        "target": {"guid": "npc-1", "screen_position": anchor},
        "monotonic_time": 9., "ui_error": "Out of range",
    }, 9.)
    assert result.status is SkillStatus.RUNNING
    assert result.metadata["approach_request"]["purpose"] == "INTERACT"
    assert result.metadata["approach_request"]["track_id"] == "world3d:7"


def test_interact_range_recovery_obeys_two_reposition_budget():
    skill, state = InteractSkill(), active()
    skill.begin(state, {"target": {"guid": "npc-1"}})
    world = {
        "target": {"guid": "npc-1", "world_position": {"x": 12., "y": 8., "instance_id": 7}},
        "player_world_position": {"x": 1., "y": 1., "instance_id": 7}, "ui_error": "Out of range",
    }
    assert skill.verify(state, world, 2.).status is SkillStatus.RUNNING
    assert skill.verify(state, world, 3.).status is SkillStatus.RUNNING
    result = skill.verify(state, world, 4.)
    assert result.status is SkillStatus.FAILURE
    assert result.reason.value == "OUT_OF_RANGE"
