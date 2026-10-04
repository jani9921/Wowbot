import pytest

from wowbot.agent.obstacle_perception import obstacle_bearing, tag_obstacle_candidates


def _candidate(**overrides):
    base = {"kind": "unknown_subject_candidate", "x": .5, "y": .4, "stable_frames": 4,
            "bbox_height_fraction": .25, "appearance": {"static_scene_score": .3}}
    base.update(overrides)
    return base


def test_tags_static_tall_close_stable_candidate_as_obstacle():
    tagged = tag_obstacle_candidates([_candidate()])
    assert tagged[0]["detector_kind"] == "obstacle_candidate"
    assert tagged[0]["kind"] == "unknown_subject_candidate"  # untouched


def test_does_not_mutate_the_input_list():
    original = [_candidate()]
    tag_obstacle_candidates(original)
    assert "detector_kind" not in original[0]


def test_ignores_a_moving_candidate_even_if_large_and_close():
    moving = _candidate(appearance={"static_scene_score": 0.})
    assert "detector_kind" not in tag_obstacle_candidates([moving])[0]


def test_ignores_a_small_distant_candidate_even_if_static():
    tiny = _candidate(bbox_height_fraction=.05)
    assert "detector_kind" not in tag_obstacle_candidates([tiny])[0]


def test_ignores_a_candidate_high_up_in_the_frame():
    sky = _candidate(y=.9)
    assert "detector_kind" not in tag_obstacle_candidates([sky])[0]


def test_ignores_a_freshly_seen_unstable_candidate():
    fresh = _candidate(stable_frames=1)
    assert "detector_kind" not in tag_obstacle_candidates([fresh])[0]


def test_obstacle_bearing_averages_tagged_candidates_x():
    state = {"visual_candidates": [
        {"detector_kind": "obstacle_candidate", "x": .2},
        {"detector_kind": "obstacle_candidate", "x": .4},
        {"detector_kind": "unknown_subject_candidate", "x": .9},  # not tagged, excluded
    ]}
    assert obstacle_bearing(state) == pytest.approx(0.3)


def test_obstacle_bearing_none_without_any_tagged_candidate():
    state = {"visual_candidates": [{"kind": "unknown_subject_candidate", "x": .5}]}
    assert obstacle_bearing(state) is None


def test_obstacle_bearing_none_with_no_candidates_at_all():
    assert obstacle_bearing({}) is None
