"""Flight routes: around like walking, over when that is faster.

User 2026-10-20: "kitudja kerülni jobbról balról is, nem kell neki fölé
repülni, ugyanúgy mint gyalog, csak kevesebb elakadás" / "de hát fölé is
repülhet, ha úgy gyorsabb".
"""
import math
from pathlib import Path

import pytest

from wowbot.navigation.flight_planner import (CLEARANCE_YARDS, CRUISE_ABOVE_YARDS,
                                              MapHeightSource, plan_flight)


class Heights:
    """Flat ground at 0 with box obstacles: (x0, x1, y0, y1, top, kind)."""

    def __init__(self, *boxes, roofs=()):
        self.boxes, self.roofs = boxes, roofs

    def _hits(self, x, y, kinds):
        return [box for box in self.boxes
                if box[5] in kinds and box[0] <= x <= box[1] and box[2] <= y <= box[3]]

    def reaches(self, x, y, ceiling):
        if self._hits(x, y, {"unknown"}):
            return None
        return any(box[4] >= ceiling for box in self._hits(x, y, {"terrain"})) or 0. >= ceiling

    def model_reaches(self, x, y, ceiling):
        return any(box[4] >= ceiling for box in self._hits(x, y, {"model"}))

    def top(self, x, y):
        if self._hits(x, y, {"unknown"}):
            return None
        return max([0.] + [box[4] for box in self._hits(x, y, {"terrain", "model"})])

    def covered(self, x, y, low, high):
        return any(abs(x-rx) < 3 and abs(y-ry) < 3 and low <= rz <= high for rx, ry, rz in self.roofs)


def flown_tops(source, route):
    """Highest surface under every cruise leg, sampled each yard."""
    tops = []
    for a, b in zip(route.waypoints[:-2], route.waypoints[1:-1]):
        steps = int(math.dist(a[:2], b[:2])) + 1
        tops.extend(source.top(a[0] + (b[0]-a[0])*i/steps, a[1] + (b[1]-a[1])*i/steps)
                    for i in range(steps+1))
    return tops


def test_open_ground_is_one_straight_leg_low_above_the_endpoints():
    result = plan_flight(Heights(), (0., 0., 5.), (300., 0., 0.))
    route = result.route
    assert result.reason == "routed"
    assert route.cruise_z == 5. + CRUISE_ABOVE_YARDS
    assert route.waypoints == ((0., 0., 35.), (300., 0., 35.), (300., 0., 0.))


def test_a_tall_ridge_with_an_end_is_flown_around_at_the_low_height():
    ridge = Heights((100., 112., -150., 150., 300., "terrain"))
    route = plan_flight(ridge, (0., 0., 0.), (200., 0., 0.)).route
    assert route.cruise_z == CRUISE_ABOVE_YARDS               # not over the 300 high ridge
    assert route.horizontal_yards > 300.
    assert max(flown_tops(ridge, route)) < route.cruise_z - CLEARANCE_YARDS


def test_a_low_wall_is_flown_over_when_the_detour_is_slower():
    wall = Heights((100., 112., -150., 150., 50., "terrain"))
    route = plan_flight(wall, (0., 0., 0.), (200., 0., 0.)).route
    assert route.cruise_z >= 50. + CLEARANCE_YARDS
    assert route.horizontal_yards == pytest.approx(200.)


def test_a_ridge_without_an_end_is_crossed_over_the_top():
    ridge = Heights((100., 112., -5000., 5000., 300., "terrain"))
    route = plan_flight(ridge, (0., 0., 0.), (200., 0., 0.)).route
    assert route.cruise_z >= 300. + CLEARANCE_YARDS
    assert max(flown_tops(ridge, route)) < route.cruise_z - CLEARANCE_YARDS


def test_unknown_heights_are_never_flown_through():
    gap = Heights((100., 112., -150., 150., 0., "unknown"))
    route = plan_flight(gap, (0., 0., 0.), (200., 0., 0.)).route
    assert None not in flown_tops(gap, route)


def test_a_tower_found_only_in_the_models_is_avoided():
    tower = Heights((90., 110., -10., 10., 200., "model"))
    route = plan_flight(tower, (0., 0., 0.), (200., 0., 0.)).route
    assert route.cruise_z == CRUISE_ABOVE_YARDS
    assert len(route.waypoints) > 3                           # turned around it
    assert max(flown_tops(tower, route)) < route.cruise_z - CLEARANCE_YARDS


def test_no_vertical_take_off_under_a_roof():
    result = plan_flight(Heights(roofs=[(0., 0., 15.)]), (0., 0., 0.), (300., 0., 0.))
    assert result.route is None
    assert result.reason == "start_covered"


MAPS = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_")


@pytest.mark.skipif(not (MAPS / "maps" / "2444.tilelist").is_file()
                    or not (MAPS / "vmaps").is_dir(), reason="Dragon Isles MAPS/VMAPS not installed")
def test_waking_shores_mountain_is_flown_around_on_the_real_maps():
    from wowbot.world_geometry.terrain_maps import TrinityMapTerrain
    from wowbot.world_geometry.vmaps import TrinityVMaps
    source = MapHeightSource(TrinityMapTerrain(MAPS, max_cached_tiles=32),
                             TrinityVMaps(MAPS / "vmaps"), 2444)
    # 100 yd ahead of the 2026-10-20 18:43-19:07 live position, facing 1.046:
    # the straight line crosses a 434 high mountain.
    start = (3541.3, -1602.2, 84.5)
    target = (start[0] + 900*math.cos(1.046), start[1] + 900*math.sin(1.046), 0.)
    target = (*target[:2], source.terrain.sample(2444, *target[:2]).terrain_z)
    route = plan_flight(source, start, target).route
    assert route is not None
    assert route.cruise_z < 400.
    assert max(flown_tops(source, route)) < route.cruise_z - CLEARANCE_YARDS


@pytest.mark.skipif(not (MAPS / "vmaps").is_dir(), reason="VMAPS not installed")
def test_fast_model_height_filter_matches_the_full_vertical_query():
    import random
    from wowbot.world_geometry.vmaps import TrinityVMaps
    vmaps = TrinityVMaps(MAPS / "vmaps")
    rng = random.Random(3)
    for _ in range(300):
        x, y = 3491. + rng.uniform(-300, 900), -1688. + rng.uniform(-300, 900)
        for bottom in (20., 90., 180.):
            assert vmaps.surfaces_above(2444, x, y, bottom) == vmaps.surfaces_at(2444, x, y, bottom=bottom)
