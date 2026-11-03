"""Live 2026-11-02 (Jangolode, 613-651 s): the height probe tap was on its
cooldown, so nothing could bring the server height, yet every MOVE waited its
3 s and failed POSITION_UNCERTAIN -- ten times in 40 s ("wait between
navigations").  With no probe possible, a single navmesh floor at our XY is
our height and the route is planned at once; a layered spot still waits."""
from wowbot.navigation.service import NavigationService
from test_position_before_route_20261030 import configured, request, standing


def floors(nav, monkeypatch, heights):
    monkeypatch.setattr(nav._z, "_layers_at", lambda instance, x, y: list(heights))
    nav._movement.__dict__["_height_probe_at"] = 9.5          # the tap was used 0.5 s ago


def test_no_probe_possible_on_a_single_floor_plans_at_once(monkeypatch):
    nav, plans = configured(monkeypatch)
    floors(nav, monkeypatch, [41.2])
    nav.start_request(request(), standing(), 10.)
    assert plans and plans[0]["z"] == 41.2 and plans[0]["z_observed"] is False   # navmesh floor, not "observed"
    assert nav._position_wait is None


def test_a_layered_spot_or_an_available_probe_still_waits_for_the_server(monkeypatch):
    nav, plans = configured(monkeypatch)
    floors(nav, monkeypatch, [41.2, 85.])
    nav.start_request(request(), standing(), 10.)
    assert plans == [] and nav._position_wait is not None
    fresh, fresh_plans = configured(monkeypatch)
    monkeypatch.setattr(fresh._z, "_layers_at", lambda instance, x, y: [41.2])
    fresh.start_request(request(), standing(), 10.)              # the tap is available: use it
    assert fresh_plans == [] and fresh._position_wait is not None
