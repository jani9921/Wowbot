from wowbot.agent.visual_tracks import VisualTrackManager


def _item(track_id, kind, x, y, lifecycle, stable, bbox):
    left, top, right, bottom = bbox
    return {"track_id": track_id, "detector_kind": kind, "x": x, "y": y,
            "lifecycle": lifecycle, "stable_frames": stable,
            "bbox": {"left": left, "top": top, "right": right, "bottom": bottom}}


def test_quest_symbol_groups_with_the_live_body_not_a_coasting_duplicate():
    """Live 2026-09-30 (at 16-18 s): Jaina's '!' bound to LOST WORLD3D:8, not ACTIVE WORLD3D:2."""
    symbol = _item("WORLD3D:1", "unknown_symbol_candidate", .51, .790, "ACTIVE", 113, (448, 90, 462, 115))
    coasting = _item("WORLD3D:8", "unknown_subject_candidate", .49, .691, "LOST_TEMPORARY", 19,
                     (425, 130, 450, 180))
    live = _item("WORLD3D:2", "unknown_subject_candidate", .51, .645, "ACTIVE", 35, (440, 150, 468, 205))
    items = [symbol, coasting, live]

    VisualTrackManager._relations(items)

    assert symbol["visual_group"]["subject_track_id"] == "WORLD3D:2"
    assert live["visual_group"]["belief"] == "SUPPORTED"
    assert "visual_group" not in coasting


def test_largest_live_body_under_symbol_wins_over_nearer_partial_box():
    """Live 2026-09-30 frame 08:50:55: WORLD3D:8 was Jaina's staff tip, WORLD3D:2 her body."""
    symbol = _item("s", "unknown_symbol_candidate", .51, .790, "ACTIVE", 10, (448, 90, 462, 115))
    staff = _item("staff", "unknown_subject_candidate", .49, .691, "ACTIVE", 5, (423, 147, 449, 166))
    body = _item("body", "unknown_subject_candidate", .51, .645, "ACTIVE", 35, (433, 154, 473, 203))

    VisualTrackManager._relations([symbol, staff, body])

    assert symbol["visual_group"]["subject_track_id"] == "body"


def test_small_creature_at_the_feet_does_not_take_the_quest_symbol():
    symbol = _item("s", "unknown_symbol_candidate", .51, .790, "ACTIVE", 10, (448, 90, 462, 115))
    npc = _item("npc", "unknown_subject_candidate", .51, .66, "ACTIVE", 20, (435, 140, 470, 205))
    critter = _item("critter", "unknown_subject_candidate", .50, .63, "ACTIVE", 20, (440, 188, 462, 206))

    VisualTrackManager._relations([symbol, critter, npc])

    assert symbol["visual_group"]["subject_track_id"] == "npc"
