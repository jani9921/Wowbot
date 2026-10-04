from wowbot.vision.world_map_calibration import EXILE_REACH_12_1_5


def test_exile_reach_roundtrip_map_space():
    x, y = 0.619, 0.843
    px, py = EXILE_REACH_12_1_5.map_to_pixel(x, y)
    rx, ry = EXILE_REACH_12_1_5.pixel_to_map(px, py)
    assert abs(rx - x) < 1e-9
    assert abs(ry - y) < 1e-9


def test_exile_reach_known_player_pixel_matches_map_position():
    # Player text in the supplied screenshot reports 61.9 / 84.3.
    px, py = EXILE_REACH_12_1_5.map_to_pixel(0.619, 0.843)
    assert 580 < px < 590
    assert 550 < py < 555
