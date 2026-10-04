from wowbot.agent.visual_approach import VisualApproachController, VisualApproachPhase


def test_many_fast_missed_observations_do_not_declare_track_lost_before_time_floor():
    # Live-observed 2026-09-14: max_missing_observations counts ticks, not
    # wall-clock time. Tuned for a ~10-15 Hz addon rate, 8 ticks used to mean
    # roughly half a second; on a much faster machine the same count of
    # missed observations can arrive in a tiny fraction of a second, firing
    # visual_track_lost far sooner than intended. Ten misses one millisecond
    # apart (11 ms total) exceed the count but not any reasonable elapsed
    # time, so the phase must still be OCCLUDED, not FAILED.
    controller = VisualApproachController()
    state = {"target": {"guid": "npc", "dead": False},
             "visual_candidates": [{"track_id": "track", "x": .5, "y": .5,
                                     "confidence": .8, "source": "WORLD3D"}]}
    controller.start({"guid": "npc", "track_id": "track", "purpose": "INTERACT"},
                     state, "o0", 0.)
    missing = {"target": {"guid": "npc", "dead": False}, "visual_candidates": []}
    for i in range(10):
        assessment = controller.observe(missing, f"o{i+1}", i * .001)
    assert controller.missing_observations > controller.max_missing_observations
    assert controller.phase == VisualApproachPhase.OCCLUDED
    assert not assessment.terminal
    assert assessment.reason == "visual_track_temporarily_occluded"


def test_track_lost_still_fires_once_the_time_floor_also_elapses():
    controller = VisualApproachController()
    state = {"target": {"guid": "npc", "dead": False},
             "visual_candidates": [{"track_id": "track", "x": .5, "y": .5,
                                     "confidence": .8, "source": "WORLD3D"}]}
    controller.start({"guid": "npc", "track_id": "track", "purpose": "INTERACT"},
                     state, "o0", 0.)
    missing = {"target": {"guid": "npc", "dead": False}, "visual_candidates": []}
    assessment = None
    for i in range(10):
        assessment = controller.observe(missing, f"o{i+1}", i * .2)
    assert controller.missing_observations > controller.max_missing_observations
    assert (i * .2) >= controller.max_missing_seconds
    assert controller.phase == VisualApproachPhase.FAILED
    assert assessment.terminal and not assessment.success
    assert assessment.reason == "visual_track_lost"
