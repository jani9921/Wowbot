import math

from wowbot.vision.world3d.association import linear_sum_assignment


def test_hungarian_assignment_finds_global_minimum():
    assert linear_sum_assignment([[6, 4], [9, 1]]) == [(0, 0), (1, 1)]


def test_hungarian_assignment_supports_rectangular_and_gated_costs():
    assert linear_sum_assignment([[math.inf, 1, 3], [2, math.inf, 4]]) == [(0, 1), (1, 0)]
    assert linear_sum_assignment([[math.inf], [2], [1]]) == [(2, 0)]
