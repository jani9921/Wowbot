import pytest

from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills.interact import InteractSkill
from wowbot.skills.interaction_recovery import InteractionRecoveryPolicy
from wowbot.skills.interaction_result import (InteractionEffectKind,
                                               InteractionResultClassifier,
                                               InteractionResultKind)


def active(deadline=5.):
    before = {"target": {"guid": "npc-1"}, "quest_ui": {"open": False}}
    proposal = Proposal.make("INTERACT", "test", {"guid": "npc-1"})
    attempt = Attempt("a", proposal, before, "o", 1., deadline, (),
                      Prediction("p", "a", "result", 1., deadline, "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("INTERACT", proposal.parameters, "npc-1"),
                  attempt=attempt, now=1., before_snapshot=before)
    return runtime.state


def test_hover_points_rank_learned_then_upper_torso_and_are_bounded_to_four():
    target = {
        "guid": "npc-1", "unit_type": "NPC",
        "screen_position": {
            "x": .5, "y": .5, "bbox": {"left": .4, "bottom": .3,
                                         "right": .6, "top": .7},
            "learned_interaction_point": {"x": .49, "y": .61},
        },
    }
    points = InteractSkill._hover_points({"target": target}, "npc-1")
    assert points[0] == (.49, .61)
    assert points[1] == pytest.approx((.5, .572))
    assert len(points) == 4


def test_hover_verification_rejects_low_confidence_or_wrong_track():
    base = {
        "monotonic_time": 2., "mouseover_sample_time": 2.,
        "target": {"guid": "npc-1", "visual_track_id": "track-a"},
        "mouseover": {"guid": "npc-1", "identity_confidence": .9,
                      "visual_track_id": "track-b"},
    }
    assert not InteractSkill._fresh_hover(base, "npc-1", 1.8)
    base["mouseover"]["visual_track_id"] = "track-a"
    base["mouseover"]["identity_confidence"] = .6
    assert not InteractSkill._fresh_hover(base, "npc-1", 1.8)
    base["mouseover"]["identity_confidence"] = .9
    assert InteractSkill._fresh_hover(base, "npc-1", 1.8)


def test_effect_classifier_covers_every_m2_output_from_observable_delta():
    classify = InteractionResultClassifier.classify_effect
    assert classify({}, {"events": [{"event_type": "GOSSIP_SHOW"}]}) is InteractionEffectKind.GOSSIP_OPEN
    assert classify({}, {"events": [{"event_type": "QUEST_DETAIL"}]}) is InteractionEffectKind.QUEST_DETAIL_OPEN
    assert classify({}, {"events": [{"event_type": "QUEST_PROGRESS"}]}) is InteractionEffectKind.QUEST_PROGRESS_OPEN
    assert classify({}, {"events": [{"event_type": "QUEST_COMPLETE"}]}) is InteractionEffectKind.QUEST_COMPLETE_OPEN
    assert classify({}, {"events": [{"event_type": "MERCHANT_SHOW"}]}) is InteractionEffectKind.MERCHANT_OPEN
    assert classify({}, {"events": [{"event_type": "LOOT_OPENED"}]}) is InteractionEffectKind.LOOT_OPEN
    assert classify({"interactable_object": {"guid": "o", "state": "READY"}},
                    {"interactable_object": {"guid": "o", "state": "USED"}}) is InteractionEffectKind.OBJECT_ACTIVATED
    assert classify({"target": {"guid": "a"}}, {"target": {"guid": "b"}}) is InteractionEffectKind.TARGET_CHANGED
    assert classify({}, {}) is InteractionEffectKind.NOTHING
    assert classify({}, {"events": [{"event_type": "INTERACTION_RESULT"}]}) is InteractionEffectKind.UNKNOWN


def test_failure_matrix_has_exact_finite_recovery_budgets():
    policy = InteractionRecoveryPolicy()
    expected = {
        InteractionResultKind.TOO_FAR: ("APPROACH", 2),
        InteractionResultKind.FACING: ("FACE", 2),
        InteractionResultKind.LOS: ("LOCAL_REPOSITION", 2),
        InteractionResultKind.CURSOR_MISS: ("HOVER_RESAMPLE", 4),
        InteractionResultKind.WRONG_ENTITY: ("REACQUIRE_EXPECTED", 2),
        InteractionResultKind.ENTITY_MOVED: ("REFRESH_AND_APPROACH", 2),
        InteractionResultKind.UI_NOT_READY: ("WAIT_AND_RETRY", 3),
        InteractionResultKind.TARGET_LOST: ("REACQUIRE_EXPECTED", 2),
        InteractionResultKind.UNKNOWN: ("OBSERVE_ONCE", 1),
    }
    for kind, (action, budget) in expected.items():
        rule = policy.rule(kind)
        assert (rule.action, rule.budget) == (action, budget)
        assert policy.available(rule, budget-1)
        assert not policy.available(rule, budget)


def test_los_ui_wait_and_expected_reacquire_are_bounded_recovery_actions():
    skill, state = InteractSkill(), active()
    skill.begin(state, {"target": {"guid": "npc-1"}})
    los = skill.verify(state, {
        "target": {"guid": "npc-1", "screen_position": {"x": .7, "y": .5}},
        "ui_error": "No line of sight"}, 2.)
    assert los.metadata["local_los_request"]["reason"] == "LINE_OF_SIGHT"
    retry = skill.verify(state, {"target": {"guid": "npc-1"}}, 2.1)
    assert retry.commands[0].binding == "INTERACTTARGET"

    waiting = skill.verify(state, {"target": {"guid": "npc-1"},
                                   "ui_error": "Please wait, not ready"}, 2.2)
    assert waiting.metadata["interaction_recovery"] == "WAIT_AND_RETRY"
    assert not skill.verify(state, {"target": {"guid": "npc-1"}}, 2.3).commands
    retried = skill.verify(state, {"target": {"guid": "npc-1"}}, 2.5)
    assert retried.commands[0].binding == "INTERACTTARGET"

    wrong = skill.verify(state, {
        "target": {"guid": "wrong"}, "monotonic_time": 2.6,
        "confirmed_mouseover_anchors": {
            "npc-1": {"x": .4, "y": .5, "sample_time": 2.6}}}, 2.6)
    assert wrong.commands[0].kind == "CLICK"
    assert wrong.metadata["interaction_recovery"] == "REACQUIRE_EXPECTED"


def test_unknown_interaction_gets_one_observation_then_escalates():
    skill, state = InteractSkill(), active()
    skill.begin(state, {"target": {"guid": "npc-1"}, "monotonic_time": 1.})
    # Live 2026-09-30: 0.25 s is shorter than server + addon + pixel latency.
    early = skill.verify(state, {"target": {"guid": "npc-1"}}, 1.3)
    assert early.metadata["interaction_recovery"] == "AWAIT_RESPONSE"
    first = skill.verify(state, {"target": {"guid": "npc-1"}}, 2.3)
    second = skill.verify(state, {"target": {"guid": "npc-1"}}, 2.6)
    assert first.metadata["interaction_recovery"] == "OBSERVE_ONCE"
    assert second.status is SkillStatus.FAILURE
    assert second.metadata["interaction_recovery"] == "UNKNOWN_ESCALATED"


def test_silent_interaction_is_not_judged_on_the_pre_press_observation():
    skill, state = InteractSkill(), active()
    skill.begin(state, {"target": {"guid": "npc-1"}, "monotonic_time": 1., "frame_id": "s:FAST:10"})
    state.before_snapshot = {"target": {"guid": "npc-1"}, "frame_id": "s:FAST:10"}
    stale = skill.verify(state, {"target": {"guid": "npc-1"}, "frame_id": "s:FAST:10"}, 2.3)
    assert stale.status is SkillStatus.RUNNING
    assert stale.metadata["interaction_recovery"] == "AWAIT_RESPONSE"


def test_lagging_telemetry_clock_does_not_age_a_fresh_interaction():
    """Live 2026-09-30: begin() stored the telemetry sample time, verify()
    compared it with the agent clock; a 2 s lag failed INTERACT in 0.4 s."""
    skill, state = InteractSkill(), active()
    skill.begin(state, {"target": {"guid": "npc-1"}, "monotonic_time": state.attempt.started_at-2.})
    early = skill.verify(state, {"target": {"guid": "npc-1"}}, state.attempt.started_at+.4)
    assert early.status is SkillStatus.RUNNING
    assert early.metadata["interaction_recovery"] == "AWAIT_RESPONSE"


def test_range_error_event_after_attempt_start_is_out_of_range_not_no_response():
    """Live 2026-10-01: "You need to be closer" (code 852) arrived as a
    UI_ERROR_MESSAGE event; the flattened ui_error showed it 3 s late, so the
    attempt ended as no_response and the per-GUID range was never learned."""
    from wowbot.runtime import FailureReason
    from wowbot.verification.interaction import InteractionVerifier

    before = {"monotonic_time": 100., "target": {"guid": "jaina"}}
    event = {"event_type": "UI_ERROR_MESSAGE",
             "payload": {"error_code": 852, "observed_at": 100.4,
                         "message": "You need to be closer to interact with that target."}}
    after = {"monotonic_time": 101., "target": {"guid": "jaina"}, "events": [event]}
    result = InteractionVerifier().evaluate(before, after, expected_guid="jaina")
    assert result.reason is FailureReason.OUT_OF_RANGE
    # An older error (before the attempt) is not attributed to it.
    stale = {**after, "events": [{**event, "payload": {**event["payload"], "observed_at": 98.}}]}
    assert InteractionVerifier().evaluate(before, stale, expected_guid="jaina").reason \
        is not FailureReason.OUT_OF_RANGE
    # The FAST lane's error code/time/sequence are enough on their own.
    fast = {"monotonic_time": 101., "target": {"guid": "jaina"}, "ui_error_code": 852,
            "ui_error_at": 100.5, "ui_error_sequence": 7}
    assert InteractionVerifier().evaluate(before, fast, expected_guid="jaina").reason \
        is FailureReason.OUT_OF_RANGE
