from wowbot.agent.stable_objects import StableObjectLayer


def raw(track_id, box, lifecycle="ACTIVE", *, kind="unknown_subject_candidate", confidence=.5,
        inspectable=True, stable=5):
    left, top, right, bottom = box
    return {"track_id": track_id, "detector_kind": kind, "lifecycle": lifecycle,
            "track_state": lifecycle, "x": (left+right)/2/892, "y": 1-(top+bottom)/2/502,
            "bbox": {"left": left, "top": top, "right": right, "bottom": bottom,
                     "coordinate_space": "CLIENT_PIXELS"},
            "confidence": confidence, "inspectable": inspectable if lifecycle == "ACTIVE" else False,
            "stable_frames": stable, "missing_frames": 0 if lifecycle == "ACTIVE" else 3,
            "missing_seconds": 0 if lifecycle == "ACTIVE" else .3}


BODY = (433, 154, 473, 203)


def establish(layer, track_id="WORLD3D:2", box=BODY, start=0.):
    for step in range(3):
        layer.update([raw(track_id, box)], start+step*.05)


def test_flickering_raw_track_is_presented_active_with_truthful_raw_state():
    layer = StableObjectLayer()
    establish(layer)
    held = layer.update([raw("WORLD3D:2", BODY, "LOST_TEMPORARY")], .3)[0]
    assert held["track_id"] == "WORLD3D:2"
    assert held["lifecycle"] == "ACTIVE" and held["track_state"] == "ACTIVE"
    assert held["raw_lifecycle"] == "LOST_TEMPORARY"
    assert held["coasting"] is True and held["presentation_hold"] is True
    assert held["inspectable"] is True  # 0.2 s coasting, inside the inspect hold
    assert "missing_seconds" not in held

    late = layer.update([raw("WORLD3D:2", BODY, "LOST_TEMPORARY")], 1.)[0]
    assert late["lifecycle"] == "ACTIVE" and late["inspectable"] is False

    expired = layer.update([raw("WORLD3D:2", BODY, "LOST_TEMPORARY")], 2.)[0]
    assert expired["lifecycle"] == "LOST_TEMPORARY" and expired["inspectable"] is False


def test_new_raw_id_for_the_same_box_keeps_the_object_id():
    layer = StableObjectLayer()
    establish(layer)
    shifted = (435, 156, 474, 204)
    out = layer.update([raw("WORLD3D:9", shifted, stable=1),
                        raw("WORLD3D:2", BODY, "OCCLUDED")], .3)
    assert [item["track_id"] for item in out] == ["WORLD3D:2"]
    assert out[0]["raw_track_ids"] == ["WORLD3D:2", "WORLD3D:9"]
    assert out[0]["raw_lifecycle"] == "ACTIVE" and out[0]["coasting"] is False
    assert out[0]["stable_frames"] >= 4
    assert layer.diagnostics()["duplicate_merges"] == 1


def test_simultaneous_distinct_boxes_stay_separate_but_exact_duplicates_merge():
    layer = StableObjectLayer()
    establish(layer)
    neighbour = (455, 154, 495, 203)   # IoU ~0.38 with BODY, both observed now
    out = layer.update([raw("WORLD3D:2", BODY), raw("WORLD3D:7", neighbour)], .3)
    assert {item["track_id"] for item in out} == {"WORLD3D:2", "WORLD3D:7"}

    layer = StableObjectLayer()
    establish(layer)
    duplicate = (434, 155, 473, 204)
    out = layer.update([raw("WORLD3D:2", BODY), raw("WORLD3D:8", duplicate)], .3)
    assert [item["track_id"] for item in out] == ["WORLD3D:2"]
    assert out[0]["duplicate_raw_tracks"] == 1


def test_partial_box_and_small_neighbour_are_not_absorbed():
    layer = StableObjectLayer()
    establish(layer)
    staff_tip = (423, 147, 449, 166)   # live 08:50:55 WORLD3D:8, IoU 0.06 with the body
    out = layer.update([raw("WORLD3D:2", BODY), raw("WORLD3D:8", staff_tip, stable=1)], .3)
    assert {item["track_id"] for item in out} == {"WORLD3D:2", "WORLD3D:8"}


def test_fresh_candidate_keeps_raw_lifecycle_and_objects_are_not_drawn_without_members():
    layer = StableObjectLayer()
    layer.update([raw("WORLD3D:4", BODY, stable=1)], 0.)
    fresh = layer.update([raw("WORLD3D:4", BODY, "OCCLUDED", stable=1)], .1)[0]
    assert fresh["lifecycle"] == "OCCLUDED"
    assert layer.update([], .2) == []


def test_box_is_smoothed_for_jitter_and_snaps_on_a_large_jump():
    layer = StableObjectLayer()
    establish(layer)
    jitter = layer.update([raw("WORLD3D:2", (437, 154, 477, 203))], .3)[0]
    assert jitter["bbox"]["left"] == 435   # halfway between 433 and 437
    jump = layer.update([raw("WORLD3D:2", (633, 154, 673, 203))], .35)[0]
    assert jump["bbox"]["left"] == 633


def test_symbol_objects_are_never_inspectable():
    layer = StableObjectLayer()
    symbol_box = (448, 90, 462, 115)
    for step in range(4):
        out = layer.update([raw("WORLD3D:1", symbol_box, kind="unknown_symbol_candidate")], step*.05)
    assert out[0]["inspectable"] is False and out[0]["lifecycle"] == "ACTIVE"


def test_patch_tracked_box_is_held_longer_than_a_blind_prediction():
    """The raw layer calls patch propagation LOST_TEMPORARY after two missed refreshes."""
    layer = StableObjectLayer()
    establish(layer)
    patch = raw("WORLD3D:2", BODY, "LOST_TEMPORARY")
    patch.pop("missing_seconds")
    patch["appearance"] = {"detector_miss_streak": 5}
    tracked = layer.update([patch], 2.5)[0]
    assert tracked["lifecycle"] == "ACTIVE" and tracked["raw_lifecycle"] == "LOST_TEMPORARY"
    assert tracked["inspectable"] is False   # click authority still needs a fresh detection

    blind = StableObjectLayer()
    establish(blind)
    predicted = blind.update([raw("WORLD3D:2", BODY, "LOST_TEMPORARY")], 2.5)[0]
    assert predicted["lifecycle"] == "LOST_TEMPORARY"


def test_same_upstream_id_rejoins_its_object_after_an_intake_stall():
    """Live 2026-09-30: public ids changed mostly while Live Vision stuttered;
    the feed kept its id, but the stalled raw track was re-created."""
    layer = StableObjectLayer(hold_seconds=.5, tracked_hold_seconds=1.)
    def item(raw, at_x):
        return {"track_id": f"WORLD3D:{raw}", "upstream_track_id": "WORLD3D_V3:166",
                "kind": "unknown_subject_candidate", "lifecycle": "ACTIVE",
                "confidence": .5, "x": at_x, "y": .5,
                "bbox": {"left": 100, "top": 100, "right": 140, "bottom": 200}}
    for step in range(4):
        first = layer.update([item(7, .3)], 10. + step * .04)[0]
    # 2.5 s stall, the raw layer re-created the track under a new raw id
    # at a new screen position (camera orbit), same feed identity.
    moved = item(9, .7)
    moved["bbox"] = {"left": 500, "top": 100, "right": 540, "bottom": 200}
    after = layer.update([moved], 12.7)[0]
    assert after["track_id"] == first["track_id"]
    assert layer.diagnostics()["upstream_rebinds"] == 1


def test_coasting_track_moves_with_the_camera_and_expires_quickly():
    """Live 2026-09-30 20:22: after a camera turn LOST_TEMPORARY boxes stayed
    behind (velocity-only coast) and lingered for ~1.2 s."""
    from wowbot.agent.visual_tracks import VisualTrackManager

    def subject(x, track, camera_dx=0.):
        return {"source": "WORLD3D", "kind": "unknown_subject_candidate",
                "detector_kind": "unknown_subject_candidate", "confidence": .8,
                "x": x, "y": .5, "upstream_track_id": track,
                "bbox": {"left": x*800-20, "top": 200, "right": x*800+20, "bottom": 300},
                "bbox_width_fraction": .05, "bbox_height_fraction": .2,
                "appearance": {"camera_motion_dx": camera_dx}}

    manager = VisualTrackManager(lost_grace_seconds=.35)
    for index in range(4):
        manager.update("WORLD3D", [subject(.30, "a"), subject(.70, "b")], index*.033)
    # The camera turns 40 px (.05 of an 800 px frame); only "b" is detected.
    after = manager.update("WORLD3D", [subject(.75, "b", camera_dx=40.)], .2)
    coasting = [item for item in after if item.get("raw_lifecycle", item.get("lifecycle"))
                in {"OCCLUDED", "LOST_TEMPORARY"} or item.get("coasting")]
    assert coasting and abs(coasting[0]["x"] - .35) < .02
    for step in range(1, 4):
        manager.update("WORLD3D", [subject(.75, "b")], .2 + step*.2)
    remaining = manager.update("WORLD3D", [subject(.75, "b")], 1.0)
    assert all(abs(item["x"] - .75) < .05 for item in remaining)


def test_hidden_coasting_track_is_not_drawn_but_keeps_its_id_on_return():
    """User 2026-09-30: with the short coast boxes vanished properly but a
    returning subject got a new id.  Presentation and identity are separate."""
    from wowbot.agent.visual_tracks import VisualTrackManager

    def subject(x):
        return {"source": "WORLD3D", "kind": "unknown_subject_candidate",
                "detector_kind": "unknown_subject_candidate", "confidence": .8,
                "x": x, "y": .5,
                "bbox": {"left": x*800-20, "top": 200, "right": x*800+20, "bottom": 300},
                "bbox_width_fraction": .05, "bbox_height_fraction": .2, "appearance": {}}

    manager = VisualTrackManager(lost_grace_seconds=1.5, present_grace_seconds=.3)
    for index in range(5):
        first = manager.update("WORLD3D", [subject(.40)], index*.033)
    identity = first[0]["track_id"]
    shown = manager.update("WORLD3D", [], .3)
    assert [item["track_id"] for item in shown] == [identity]      # brief gap: still drawn
    manager.update("WORLD3D", [], .5)
    hidden = manager.update("WORLD3D", [], .8)
    assert hidden == []                                             # stale box is not drawn
    back = manager.update("WORLD3D", [subject(.41)], 1.1)
    assert [item["track_id"] for item in back] == [identity]       # same id on return


def test_screen_anchored_avatar_keeps_one_world_id_through_turns_and_dropouts():
    """Live 2026-10-01 06:45: the feed kept the avatar on V3:5, but the World3D
    layer coasted it with the camera during a one-frame dropout, so its
    return opened WORLD3D:8/25/32/... and the two tracks alternated."""
    from wowbot.agent.visual_tracks import VisualTrackManager

    def avatar(camera_dx):
        return {"source": "WORLD3D", "kind": "unknown_subject_candidate",
                "detector_kind": "unknown_subject_candidate", "confidence": .6,
                "x": .5, "y": .38, "upstream_track_id": "WORLD3D_V3:5",
                "bbox": {"left": 395, "top": 225, "right": 448, "bottom": 370},
                "bbox_width_fraction": .063, "bbox_height_fraction": .305,
                "appearance": {"camera_motion_dx": camera_dx, "screen_anchored": True}}

    manager = VisualTrackManager(lost_grace_seconds=1.5, present_grace_seconds=.3)
    seen = set()
    t = 0.
    for frame in range(40):
        t += .033
        if frame % 7 == 3:                       # detector dropout during the turn
            out = manager.update("WORLD3D", [], t)
        else:
            out = manager.update("WORLD3D", [avatar(60.)], t)   # world turns 60 px/frame
        seen.update(item["track_id"] for item in out)
        assert len(out) <= 1, out
    assert len(seen) == 1, seen


def test_duplicate_track_sharing_an_upstream_id_is_retired_not_alternated():
    """Live 2026-10-01 06:45: WORLD3D:5 and WORLD3D:25/32/... both carried
    V3:5; the zero-cost tie made the assignment alternate between them."""
    from wowbot.agent.visual_tracks import VisualTrackManager

    def box(x, upstream):
        return {"source": "WORLD3D", "kind": "unknown_subject_candidate",
                "detector_kind": "unknown_subject_candidate", "confidence": .6,
                "x": x, "y": .38, "upstream_track_id": upstream,
                "bbox": {"left": x*843-26, "top": 225, "right": x*843+26, "bottom": 370},
                "bbox_width_fraction": .063, "bbox_height_fraction": .305, "appearance": {}}

    manager = VisualTrackManager(lost_grace_seconds=1.5, present_grace_seconds=.3)
    t = 0.
    for _ in range(10):
        t += .033
        first = manager.update("WORLD3D", [box(.5, "WORLD3D_V3:5")], t)
    owner = first[0]["track_id"]
    # One frame publishes the upstream id twice (feed duplicate).
    t += .033
    manager.update("WORLD3D", [box(.5, "WORLD3D_V3:5"), box(.35, "WORLD3D_V3:5")], t)
    shown = set()
    for _ in range(20):
        t += .033
        out = manager.update("WORLD3D", [box(.5, "WORLD3D_V3:5")], t)
        shown.update(item["track_id"] for item in out)
    assert shown == {owner}
