"""Live 2026-10-07 11:06 (Hrun's pit, "Who Lurks in the Pit" 1/5): after the
first cocoon the agent alternated two MOVEs every ~1.6 s for minutes, both
"reach_arrival_verified", inside a 4 yd patch on the spiral:

* the zone sweep offered hop 4 again and again: its planner-side "visited"
  test compared the addon's ``state.monotonic_time`` (GetTime at sampling)
  with the Z resolver's fix time (agent clock, ~0.1 s later), so the fix was
  always "from the future" and no hop was ever marked by position;
* the quest-area search cell (81,-2242) lies over the pit hole; its
  same-floor projection (76,-2235.7) is 8 yd away, outside the 7.5 yd visit
  radius, so the cell was never covered and was offered again.
"""
from types import SimpleNamespace

from wowbot.navigation.service import NavigationService


class _SpiralMesh:
    """A straight 'spiral' from the rim (98) down to the bottom (-20)."""

    def find_path(self, instance_id, start, destination):
        anchors = [{"x": 80. + i, "y": -2240., "z": 98. - 2.*i} for i in range(60)]
        return SimpleNamespace(anchors=anchors, cost=118.)


def _at(x, y, t):
    return {"monotonic_time": t,
            "player_world_position": {"x": x, "y": y, "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS", "sample_time": t}}


def _sweep():
    nav = NavigationService(navmesh=_SpiralMesh())
    nav.lower_layer_point = lambda state, destination: {"x": 139., "y": -2240., "z": -20.}
    first = nav.zone_sweep_next(_at(80., -2240., 10.), {"x": 81., "y": -2242.}, "pit")
    assert first["sweep_hop"] == 0
    return nav, first


def test_a_z_fix_taken_just_after_the_addon_sample_marks_the_hop_visited():
    nav, first = _sweep()
    # The agent resolved the layer at its own clock (10.1) for the addon
    # sample taken at GetTime 10.0 -- the normal receive latency.
    nav._z.seed_player(2175, first["x"], first["y"], first["z"], 10.1)
    nxt = nav.zone_sweep_next(_at(first["x"], first["y"], 10.), {"x": 81., "y": -2242.}, "pit")
    assert nxt["sweep_hop"] == 1


def test_a_stale_z_fix_still_does_not_mark_the_hop():
    nav, first = _sweep()
    nav._z.seed_player(2175, first["x"], first["y"], first["z"], 2.)
    again = nav.zone_sweep_next(_at(first["x"], first["y"], 10.), {"x": 81., "y": -2242.}, "pit")
    assert again["sweep_hop"] == 0


def test_a_verified_arrival_at_a_sweep_hop_retires_it_without_a_z_fix():
    nav, first = _sweep()
    destination = {**first, "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                   "location_source": "QUEST_ZONE_SWEEP", "stop_distance": 6.}
    before, after = _at(80., -2240., 10.), _at(first["x"]-4., first["y"]+2., 11.)
    nav.observe_verified_move(before, after, destination)
    # The next plan runs from elsewhere (the area search moved us away).
    nxt = nav.zone_sweep_next(_at(78., -2236., 12.), {"x": 81., "y": -2242.}, "pit")
    assert nxt["sweep_hop"] == 1


def test_an_arrival_elsewhere_does_not_retire_a_hop_of_the_current_sweep():
    nav, first = _sweep()
    stranger = {"x": first["x"]+40., "y": first["y"], "sweep_hop": 0,
                "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                "location_source": "QUEST_ZONE_SWEEP"}
    nav.observe_verified_move(_at(80., -2240., 10.), _at(120., -2240., 11.), stranger)
    again = nav.zone_sweep_next(_at(78., -2236., 12.), {"x": 81., "y": -2242.}, "pit")
    assert again["sweep_hop"] == 0


def test_a_verified_arrival_for_a_search_cell_covers_that_cell():
    nav = NavigationService(navmesh=_SpiralMesh())
    region = "55639:55639:area:1409:0"
    nav.begin_search_region(region, {"x": 81., "y": -2242., "radius": 30.,
                                     "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                     "map_id": 1409})
    standing = _at(76., -2235.7, 20.)
    nav.observe_search_region(region, standing, 20., target_detected=False)
    cell = nav.next_search_waypoint(region, standing)
    assert cell["search_cell_id"] == f"{region}:1:1"
    # The same-floor projection of the cell was reached, 8 yd from its X/Y.
    nav.observe_verified_move(_at(73., -2238.3, 19.), standing,
                              {**cell, "purpose": "SEARCH_LOCAL_OBJECTIVE_AREA"})
    nav.observe_search_region(region, standing, 21., target_detected=False)
    assert nav.next_search_waypoint(region, standing)["search_cell_id"] != cell["search_cell_id"]
