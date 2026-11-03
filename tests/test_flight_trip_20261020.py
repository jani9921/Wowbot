"""Take-off and landing spots under open sky, joined by walks (user 2026-10-20)."""
import math
from types import SimpleNamespace

import pytest

from wowbot.navigation.flight_trip import open_sky_spot, plan_trip


class World:
    """Flat ground at 0; roofs are (x0, x1, y0, y1, z) rectangles; terraces
    are (x0, x1, y0, y1, z) walkable areas at another height; walls cut walks."""

    def __init__(self, roofs=(), terraces=(), walled=lambda a, b: False):
        self.roofs, self.terraces, self.walled = roofs, terraces, walled

    # MapHeightSource side
    def reaches(self, x, y, ceiling):
        return 0. >= ceiling

    def model_reaches(self, x, y, ceiling):
        return any(r[0] <= x <= r[1] and r[2] <= y <= r[3] and r[4] >= ceiling for r in self.roofs)

    def top(self, x, y):
        return max([0.] + [r[4] for r in self.roofs if r[0] <= x <= r[1] and r[2] <= y <= r[3]])

    def covered(self, x, y, low, high):
        return any(r[0] <= x <= r[1] and r[2] <= y <= r[3] and low <= r[4] <= high for r in self.roofs)

    # navmesh side
    def walkable_heights_at(self, instance_id, point, radius):
        x, y = point["x"], point["y"]
        for t in self.terraces:
            if t[0] <= x <= t[1] and t[2] <= y <= t[3]:
                return [t[4]]
        return [0.]

    def find_path(self, instance_id, start, destination):
        a = (start["x"], start["y"], start["z"])
        b = (destination["x"], destination["y"], destination["z"])
        if self.walled(a, b):
            return None
        anchors = tuple({"x": p[0], "y": p[1], "z": p[2]} for p in (a, b))
        return SimpleNamespace(anchors=anchors, cost=math.dist(a, b))


SHED = (-5., 5., -5., 5., 6.)          # a 10 x 10 roof 6 yd up around (0, 0)


def test_open_ground_keeps_the_point_itself():
    spot = open_sky_spot(World(), World(), 1, (0., 0., 0.), landing=True)
    assert spot.point == (0., 0., 0.)
    assert spot.walk_yards == 0.


def test_under_a_roof_the_nearest_open_spot_and_its_walk_are_used():
    world = World(roofs=[SHED])
    landing = open_sky_spot(world, world, 1, (0., 0., 0.), landing=True)
    assert math.hypot(*landing.point[:2]) == pytest.approx(6.)   # first ring outside the shed
    assert world.covered(*landing.point[:2], 3., 2000.) is False
    assert landing.walk[0] == landing.point and landing.walk[-1] == (0., 0., 0.)
    take_off = open_sky_spot(world, world, 1, (0., 0., 0.), landing=False)
    assert take_off.walk[0] == (0., 0., 0.) and take_off.walk[-1] == take_off.point


def test_a_spot_on_another_terrace_or_without_a_walk_is_rejected():
    terrace = World(roofs=[(-12., 12., -12., 12., 6.)],
                    terraces=[(-100., 100., -100., 100., 40.)])  # every open spot is 40 yd up
    assert open_sky_spot(terrace, terrace, 1, (0., 0., 0.), landing=True) is None
    walled = World(roofs=[SHED], walled=lambda a, b: True)
    assert open_sky_spot(walled, walled, 1, (0., 0., 0.), landing=True) is None


def test_a_long_walk_loses_to_a_short_one():
    # Spots east of the shed are only reachable around a long wall.
    world = World(roofs=[SHED], walled=lambda a, b: a[0] > 0 and b[0] <= 0 and abs(a[1]) < 8)
    spot = open_sky_spot(world, world, 1, (0., 0., 0.), landing=True)
    assert not (spot.point[0] > 0 and abs(spot.point[1]) < 8)


def test_trip_walks_out_flies_and_walks_in():
    world = World(roofs=[SHED, (295., 305., -5., 5., 6.)])
    trip = plan_trip(world, world, 1, (0., 0., 0.), (300., 0., 0.))
    assert trip.reason == "routed"
    assert trip.take_off.walk_yards > 0 and trip.landing.walk_yards > 0
    assert trip.flight.waypoints[0][:2] == trip.take_off.point[:2]
    assert trip.flight.waypoints[-1] == trip.landing.point
    assert plan_trip(World(roofs=[SHED], walled=lambda a, b: True), World(roofs=[SHED], walled=lambda a, b: True),
                     1, (0., 0., 0.), (300., 0., 0.)).reason == "no_take_off_spot"
