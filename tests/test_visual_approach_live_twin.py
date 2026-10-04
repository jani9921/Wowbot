from wowbot.agent.visual_approach import VisualApproachController, VisualApproachPhase


def _subject(track_id, x, y, lifecycle="ACTIVE", **extra):
    return {"track_id": track_id, "x": x, "y": y, "confidence": .5, "source": "WORLD3D",
            "detector_kind": "unknown_subject_candidate", "lifecycle": lifecycle,
            "bbox_height_fraction": .11, **extra}


def _start_seek(controller):
    state = {"visual_candidates": [_subject("WORLD3D:2", .51, .645)]}
    controller.start({"track_id": "WORLD3D:2", "purpose": "IDENTIFY"}, state, "o0", 0.)
    controller.observe(state, "o1", .05)


def test_seek_follows_live_twin_while_committed_track_coasts():
    """Live 2026-09-30: Jaina's WORLD3D:2 and WORLD3D:8 alternated LOST/ACTIVE."""
    controller = VisualApproachController()
    _start_seek(controller)
    coasting = {"visual_candidates": [_subject("WORLD3D:2", .51, .645, "LOST_TEMPORARY"),
                                      _subject("WORLD3D:8", .49, .69)]}
    for index in range(12):
        assessment = controller.observe(coasting, f"c{index}", .1 + index * .2)
    assert controller.intent["track_id"] == "WORLD3D:8"
    assert controller.phase != VisualApproachPhase.FAILED
    assert assessment.reason != "visual_track_lost"
    assert controller.track_rebindings >= 1


def test_seek_rebinds_when_committed_id_vanishes_but_rejects_ambiguous_or_self_boxes():
    controller = VisualApproachController()
    _start_seek(controller)
    vanished = {"visual_candidates": [_subject("WORLD3D:9", .52, .65)]}
    controller.observe(vanished, "v1", .2)
    assert controller.intent["track_id"] == "WORLD3D:9"

    ambiguous = VisualApproachController()
    _start_seek(ambiguous)
    two_close = {"visual_candidates": [_subject("a", .52, .65), _subject("b", .50, .64)]}
    ambiguous.observe(two_close, "a1", .2)
    assert ambiguous.intent["track_id"] == "WORLD3D:2"

    own = VisualApproachController()
    _start_seek(own)
    self_only = {"visual_candidates": [_subject("me", .51, .64,
                                                visual_identity={"kind": "SELF_PLAYER"})]}
    own.observe(self_only, "s1", .2)
    assert own.intent["track_id"] == "WORLD3D:2"
