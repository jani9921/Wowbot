"""Bounded screen-space forecasting, never identity, world XYZ or ReID."""
from copy import deepcopy

import pytest

from wowbot.agent.track_motion import TrackMotion, predicted_point
from test_parallel_control import control_sample, setup


def sample(at, x, *, track="one", facing=0., session="s", **box_extra):
    return {"session_id": session, "monotonic_time": at, "orientation": facing,
            "visual_candidates": [{"track_id": track, "source": "WORLD3D", "observed_at": at,
                                   "x": x, "y": .5, **box_extra}]}


def test_fast_channel_forecasts_a_moving_target_from_fresh_frames_without_medium_steps():
    agent, executor = setup()
    for index in range(8):
        now = 10.+index*.04
        payload, vision = control_sample(agent, now, index, .55+index*.004)
        agent.parallel_control.tick(payload, now, vision, now)
    model = agent.parallel_control.motion.snapshot("WORLD3D:npc")["prediction"]
    assert model["samples"] == 8 and abs(model["vx"]-.1) < 1e-6
    assert model["identity_proof"] is False
    pointer = [c for c in executor.commands if c.kind == "POINTER"][-1]
    assert .578 < pointer.x < .60   # lead, not a delayed old centre
    assert agent.pending.action_id == "a"


@pytest.mark.parametrize("changed", [{"coasting": True}, {"lifecycle": "LOST_TEMPORARY"},
                                     {"lifecycle": "OCCLUDED"}])
def test_a_lost_box_does_not_keep_motion_as_identity_or_a_new_aim(changed):
    motion = TrackMotion()
    for i in range(4):
        state = sample(10.+i*.1, .4+i*.01)
        motion.observe(state)
    state = sample(10.4, .44, **changed)
    motion.observe(state)
    assert "screen_velocity" not in state["visual_candidates"][0]
    assert not motion.snapshot("one")["prediction"]


def test_camera_turn_session_change_and_new_id_cannot_inherit_old_motion():
    motion = TrackMotion()
    for i in range(4):
        state = sample(10.+i*.1, .4+i*.02)
        motion.observe(state)
    turn = sample(10.4, .7, facing=.2)
    motion.observe(turn)
    assert "screen_velocity" not in turn["visual_candidates"][0]
    fresh = sample(10.5, .72, session="different")
    motion.observe(fresh)
    assert "screen_velocity" not in fresh["visual_candidates"][0]
    another = sample(10.6, .74, track="new", session="different")
    motion.observe(another)
    assert "screen_velocity" not in another["visual_candidates"][0]


def test_abrupt_reversal_or_spatial_discontinuity_does_not_predict_the_old_direction():
    motion = TrackMotion()
    for i in range(5):
        state = sample(10.+i*.1, .4+i*.02)
        motion.observe(state)
    reversed_state = sample(10.5, .46)
    motion.observe(reversed_state)
    assert "screen_velocity" not in reversed_state["visual_candidates"][0]
    jump = sample(10.6, .9)
    motion.observe(jump)
    assert "screen_velocity" not in jump["visual_candidates"][0]


def test_vision_rotation_or_zoom_invalidates_motion_even_if_body_heading_is_unchanged():
    motion = TrackMotion()
    for i in range(4):
        motion.observe(sample(10.+i*.1, .4+i*.02))
    changed = sample(10.4, .48)
    changed["camera_state"] = {"camera_motion_evidence": {"kind": "ROTATION", "confidence": .8}}
    motion.observe(changed)
    assert "screen_velocity" not in changed["visual_candidates"][0]
    zoomed = sample(10.5, .52)
    zoomed["camera_state"] = {"zoom_change": True}
    motion.observe(zoomed)
    assert "screen_velocity" not in zoomed["visual_candidates"][0]


def test_old_measurements_do_not_get_new_timestamps_or_future_motion():
    motion = TrackMotion()
    stale = sample(10., .4, screen_velocity={"x": .2, "y": 0.})
    stale["monotonic_time"] = 11.
    motion.observe(stale)
    assert "screen_velocity" not in stale["visual_candidates"][0]
    candidate = sample(10., .4, screen_velocity={"x": .2, "y": 0.})["visual_candidates"][0]
    before = deepcopy(candidate)
    assert predicted_point(candidate, {}, 11.) == (.4, .5)
    assert predicted_point(candidate, {}, 9.9) == (.4, .5)
    assert candidate == before


def test_epoch_reset_discards_fast_prediction_history():
    agent, _ = setup()
    for index in range(5):
        now = 10.+index*.04
        payload, vision = control_sample(agent, now, index, .55+index*.004)
        agent.parallel_control.tick(payload, now, vision, now)
    agent.parallel_control.expected_epoch = 2
    payload, vision = control_sample(agent, 10.24, 6, .58)
    vision["epoch"] = 2
    agent.parallel_control.tick(payload, 10.24, vision, 10.24)
    assert not agent.parallel_control.motion.snapshot("WORLD3D:npc")["prediction"]
