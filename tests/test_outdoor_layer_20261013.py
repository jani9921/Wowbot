"""Live 2026-10-13 05:47: above Hrun's pit (navmesh layers 39.3 / 96.0 at the
Alaria pin) a route was planned from the cave layer while the addon said
the player was outdoors; following its x/y the player fell into the pit."""
from types import SimpleNamespace

from wowbot.navigation.z_resolver import ZResolver


class _Navmesh:
    def walkable_heights_at(self, instance_id, point, radius=2.5):
        return [39.31, 95.97]

    def terrain_sample(self, instance_id, point):
        return SimpleNamespace(is_hole=False, terrain_z=95.34)


def _state(indoors, x=97., y=-2249.):
    return {"player_world_position": {"x": x, "y": y, "instance_id": 2175},
            "movement": {"indoors": indoors}}


def test_outdoors_the_player_is_not_put_on_the_cave_floor_below():
    z = ZResolver(_Navmesh())
    z.seed_player(2175, 97., -2249., 39.31, 1.)          # a wrong earlier belief
    resolved = z.observe_player(_state(False, 97.5, -2249.), 2.)
    assert abs(resolved.z - 95.97) < .01 and resolved.source == "OUTDOOR_TERRAIN"


def test_indoors_the_cave_floor_is_kept():
    z = ZResolver(_Navmesh())
    z.seed_player(2175, 97., -2249., 39.31, 1.)
    resolved = z.observe_player(_state(True, 97.5, -2249.), 2.)
    assert abs(resolved.z - 39.31) < .01


def test_outdoor_sweep_cell_over_the_pit_is_not_walked():
    """Live 05:56: the sweep cell (67, -2229) had only the pit bottom under
    it; the route led along the rim and the character fell into the cave."""
    from types import SimpleNamespace
    from wowbot.navigation import NavigationService
    from wowbot.navigation.z_resolver import ResolvedPosition

    class Geometry:
        def walkable_heights_at(self, instance_id, point, radius=2.5):
            return [-23.] if point["x"] < 80 else [38., 96.]
    service = NavigationService(navmesh=Geometry())
    service._z.player = ResolvedPosition(90.7, -2248.1, 95.5, .85, "MMAP", 2175, at=1.)
    service._z._indoors = False
    cell = {"x": 67., "y": -2229.4, "coordinate_space": "WORLD_YARDS"}
    assert not service.search_cell_on_player_floor(cell)
    assert service.search_cell_on_player_floor({**cell, "x": 100.})
