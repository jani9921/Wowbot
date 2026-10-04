from wowbot.vision.world3d import build_scene_roi, WorldSceneProfile


def test_scene_roi_excludes_ui_bands():
    roi = build_scene_roi(1616, 868)
    assert roi.rect.left == 0
    assert roi.rect.top == 92
    assert roi.rect.right == 1616
    assert roi.rect.bottom == 647
    assert roi.learned_rect is not None
    assert roi.learned_rect.top == 12
    assert roi.learned_rect.bottom == 868
    # Upper middle world remains visible, while the addon block and the two
    # stable unit-frame islands are hard masks for learned inference.
    assert any(r.left == 0 and r.right >= 581 and r.bottom >= 156
               for r in roi.hard_excluded_rects)
    assert any(r.left <= 404 and r.right >= 581 and r.top >= 580
               for r in roi.hard_excluded_rects)
    assert any(r.left <= 1034 and r.right >= 1244 and r.top >= 590
               for r in roi.hard_excluded_rects)
    assert len(roi.excluded_rects) >= 3


def test_scene_roi_excludes_scaled_player_frame_but_not_third_person_self_avatar():
    width, height = 1177, 552
    roi = build_scene_roi(width, height)
    # Live 70%-UI capture: the player-frame portrait fragment at x=240..272
    # must not leak through a fixed-width mask.
    assert any(r.left == 0 and r.right >= 376 and r.top <= 316 < r.bottom
               for r in roi.excluded_rects)
    # The avatar band is metadata rather than a detector mask, so an NPC or
    # quest symbol overlapping the local character remains observable.
    assert roi.self_avatar_rect is not None
    assert roi.self_avatar_rect not in roi.excluded_rects
    assert roi.self_avatar_rect.left <= width*.5 <= roi.self_avatar_rect.right
    assert roi.self_avatar_rect.top <= height*.48 < roi.self_avatar_rect.bottom
    assert not any(r.left <= width*.5 <= r.right and r.top <= height*.25 < r.bottom
                   for r in roi.excluded_rects)


def test_custom_scene_profile():
    roi = build_scene_roi(1000, 800, WorldSceneProfile(top_excluded_px=20, learned_top_px=8, bottom_excluded_ratio=0.1, right_excluded_ratio=0.1))
    assert roi.rect.top == 20
    assert roi.rect.right == 900
    assert roi.rect.bottom == 720
    assert roi.learned_rect == type(roi.rect)(0, 8, 900, 800)


def test_small_frame_rejected():
    try:
        build_scene_roi(100, 100)
    except ValueError:
        return
    raise AssertionError("small frame should be rejected")
