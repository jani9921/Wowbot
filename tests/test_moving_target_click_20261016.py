"""The user's moving target must not get stuck in a hover-only loop.

All input is inert Command data or RecordingExecutor output.
"""
import pytest

from test_active_pointer_tracking import scene
from test_m0_target_skill import active
from wowbot.skills import TargetSkill
from wowbot.skills.hover_confirm import hover_confirm_step
from wowbot.runtime import SkillStatus


def handoff_state(**changes):
    params = {"guid": "npc-1", "x": .4, "y": .5,
              "hover_x": .6, "hover_y": .6, "track_id": "WORLD3D:npc",
              "ground_truth_handoff": True, "click_current_cursor": True}
    state = active(params)
    state.before_snapshot = {"monotonic_time": 1., "player_present": True,
        "mouseover": {"guid": "npc-1"}, "mouseover_sample_time": 1.,
        "cursor_position": {"nx": .4, "ny": .5}, "cursor_sample_time": 1., **changes}
    return state


def test_confirmed_current_cursor_clicks_without_rehovering_the_predicted_box():
    skill = TargetSkill()
    state = handoff_state()
    started = skill.begin(state)
    assert [c.kind for c in started.commands] == ["CLICK_CURRENT_CURSOR"]
    assert not state.skill_context["target"].get("hover_pending")
    assert state.skill_context["target"]["clicked_at"] == 1.
    assert skill.verify(state, {"target": {"guid": "npc-1"},
        "target_sample_time": 1.04}, 1.04).status is SkillStatus.SUCCESS


@pytest.mark.parametrize("changes", [
    {"mouseover_sample_time": .5},
    {"mouseover_sample_time": 1.1},
    {"mouseover_sample_time": None},
    {"cursor_sample_time": None},
    {"cursor_sample_time": .9},
    {"mouseover": {"guid": "npc-other"}},
    {"cursor_position": {"nx": .6, "ny": .6}},
    {"world_map_open": True},
])
def test_fast_handoff_does_not_skip_confirmation_for_invalid_current_proof(changes):
    started = TargetSkill().begin(handoff_state(**changes))
    assert not any(c.kind.startswith("CLICK") for c in started.commands)


def test_continuous_tracking_gives_delayed_addon_a_chance_to_confirm_and_click():
    context = {"hovered_at": 10., "hovers": 1, "track_id": "WORLD3D:npc",
               "hover_point": (.55, .6)}
    click_at = None
    point = (.55, .6)
    for index in range(1, 9):
        now = 10. + index*.04             # 25 Hz detector/control
        current = scene(now, .55+index*.004)
        current.update(mouseover={"guid": "henry"}, mouseover_sample_time=now-.06,
                       cursor_position={"nx": point[0], "ny": point[1]}, cursor_sample_time=now-.06)
        verdict, commands = hover_confirm_step(context, current, now,
                                               expected_guid="henry", deadline=12.)
        if verdict == "CLICK":
            click_at = now
            assert [c.kind for c in commands] == ["CLICK_CURRENT_CURSOR"]
            break
        if commands:
            point = (commands[0].x, commands[0].y)
    assert click_at is not None and click_at <= 10.20
    assert context["hovers"] == 1           # following is not a failed retry


def test_delayed_wrong_guid_cancels_instead_of_clicking_during_feedback_hold():
    context = {"hovered_at": 10., "hovers": 1, "track_id": "WORLD3D:npc"}
    hover_confirm_step(context, scene(10.04, .58), 10.04, expected_guid="henry", deadline=12.)
    wrong = scene(10.12, .59)
    wrong.update(mouseover={"guid": "kee-la"}, mouseover_sample_time=10.08)
    assert hover_confirm_step(context, wrong, 10.12, expected_guid="henry", deadline=12.) == ("FAILED", ())


def test_feedback_hold_is_bounded_and_resumes_following_without_clicking():
    context = {"hovered_at": 10., "hovers": 1, "track_id": "WORLD3D:npc"}
    hover_confirm_step(context, scene(10.04, .58), 10.04, expected_guid="henry", deadline=12.)
    waiting = scene(10.08, .59)
    waiting.update(mouseover={"guid": "henry"}, mouseover_sample_time=9.9)
    assert hover_confirm_step(context, waiting, 10.08, expected_guid="henry", deadline=12.) == ("WAIT", ())
    verdict, commands = hover_confirm_step(context, scene(10.51, .62), 10.51,
                                           expected_guid="henry", deadline=12.)
    assert verdict == "HOVER" and commands[0].kind == "POINTER"
    assert hover_confirm_step(context, scene(12., .7), 12., expected_guid="henry", deadline=12.) == ("FAILED", ())


def test_real_agent_launch_clicks_verified_cursor_not_the_offset_box_centre():
    from test_murloc_handoff_20261016 import MOUSE, GUID, snapshot
    from wowbot.agent.engine import AutonomousAgent
    from wowbot.agent.executor import RecordingExecutor
    from wowbot.agent.models import Mode

    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    agent.set_goal("Questelj", 9.9)
    agent.set_mode(Mode.FULL_AI)
    candidate = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
        "track_id": "WORLD3D:npc", "x": .34, "y": .45, "observed_at": 10.,
        "confidence": .8, "stable_frames": 8, "lifecycle": "ACTIVE",
        "bbox_width_fraction": .1, "bbox_height_fraction": .12,
        "candidate_labels": ["learned_subject_like"]}
    try:
        agent.tick(snapshot(mouse=MOUSE, visual_candidates=[candidate]), 10.)
        assert agent.pending and agent.pending.proposal.skill == "TARGET"
        params = agent.pending.proposal.parameters
        assert params["guid"] == GUID and params["hover_x"] == .34
        assert params["x"] == .3       # exact addon-confirmed cursor, not bbox centre
        assert [c.kind for c in executor.commands] == ["CLICK_CURRENT_CURSOR"]
        assert agent.active_skill.state.skill_context["target"]["handoff_reused"]
        agent.tick(snapshot(10.04, mouse=MOUSE, target=MOUSE), 10.04)
        assert agent.last_result["skill"] == "TARGET"
        assert agent.last_result["outcome"] == "SUCCESS"
    finally:
        agent.set_mode(Mode.STOPPED)
