"""Z resolver (user 2026-10-06): the player's own layer from sample to sample
(Retail exports no height) and a target's walkable, reachable height scored
with MMAP, VMAP, terrain, the player's layer and the minimap floor cue."""
from types import SimpleNamespace

from wowbot.navigation.z_resolver import ZResolver


class _Geometry:
    """A ramp (z = 60 + x) under a rim at 98; a pit target with three floors."""

    def __init__(self, reachable=(44., 93.), surfaces=(), path_cost=None):
        self.reachable, self.surfaces, self.path_cost = set(reachable), list(surfaces), path_cost or {}
        self.paths = []

    def walkable_heights_at(self, instance_id, point, radius=2.5):
        if point["x"] > 500:
            return [-2., 44., 93.]                       # the target column
        return sorted({60. + point["x"], 98.})

    def walkable_points_near(self, instance_id, point, radius):
        return []

    def terrain_sample(self, instance_id, point):
        return SimpleNamespace(terrain_z=98., is_hole=False)

    def vmap_surfaces_at(self, instance_id, point):
        return self.surfaces

    def find_path(self, instance_id, start, end):
        self.paths.append((start["z"], end["z"]))
        if end["z"] not in self.reachable:
            return None
        anchors = ({"x": start["x"], "y": start["y"], "z": start["z"]},
                   {"x": end["x"], "y": end["y"], "z": end["z"]})
        return SimpleNamespace(anchors=anchors, cost=self.path_cost.get(end["z"], 60.))


def _at(x, t, events=(), stamp=1000):
    return {"timestamp": stamp, "events": list(events),
            "player_world_position": {"x": x, "y": 0., "instance_id": 2175}}


def test_the_own_layer_follows_a_ramp_and_never_jumps_to_the_rim():
    z = ZResolver(_Geometry())
    first = z.observe_player(_at(0., 1.), 1., route_z=61.)
    assert first.z == 60. and first.confidence == .5 and first.alternatives == (98.,)
    for step in range(1, 20):
        resolved = z.observe_player(_at(float(step), 1.+step*.2), 1.+step*.2)
        assert resolved.z == 60. + step
    assert resolved.confidence == .95


def test_a_fall_lands_on_the_highest_layer_below():
    z = ZResolver(_Geometry())
    z.seed_player(2175, 30., 0., 98., 1.)
    landed = z.observe_player(_at(30., 2., events=[{"event_type": "FALL_ENDED", "sequence": 7,
                                                    "timestamp": 1000}]), 2.)
    assert landed.z == 90. and landed.source == "FALL" and z.fall_count == 1


def test_a_layer_change_that_walking_cannot_explain_is_low_confidence():
    z = ZResolver(_Geometry())
    z.seed_player(2175, 0., 0., 75., 1.)            # 15 yd off any layer here
    jumped = z.observe_player(_at(0., 1.5), 1.5)
    assert jumped.confidence == .4 and "continuity_broken" in jumped.evidence


def _player(z_value):
    resolver = ZResolver()
    resolver.seed_player(2175, 520., 0., z_value, 1.)
    return resolver.player


def test_an_unreachable_floor_loses_to_a_reachable_one():
    geometry = _Geometry(reachable=(44.,))
    z = ZResolver(geometry)
    target = z.resolve_target(2175, 600., 0., player=_player(75.))
    assert target.z == 44. and target.reachable and set(target.alternatives) == {-2., 93.}


def test_the_minimap_floor_cue_picks_between_reachable_floors():
    geometry = _Geometry(reachable=(44., 93.), path_cost={44.: 70., 93.: 70.})
    below = ZResolver(geometry).resolve_target(2175, 600., 0., player=_player(75.), floor_hint="BELOW")
    above = ZResolver(geometry).resolve_target(2175, 600., 0., player=_player(75.), floor_hint="ABOVE")
    assert (below.z, above.z) == (44., 93.)


def test_vmap_confirms_a_floor_and_rejects_one_without_headroom():
    geometry = _Geometry(reachable=(44., 93.), surfaces=[93.5, 44.])
    target = ZResolver(geometry).resolve_target(2175, 600., 0., player=_player(75.))
    assert target.z == 44. and "vmap_floor" in target.evidence
    assert target.source == "COMBINED"


def test_a_low_confidence_target_is_approached_in_a_short_leg():
    from pathlib import Path
    import tempfile
    from test_agent_core import binding_file
    from wowbot.agent.bindings import BindingsCache
    from wowbot.navigation.mmap_navmesh import NavMeshPath
    from wowbot.navigation.service import NavigationService

    class _Long(_Geometry):
        def find_path(self, instance_id, start, end):
            anchors = tuple({"x": start["x"] + 10.*i, "y": 0., "z": 75., "instance_id": instance_id,
                             "source": "TRINITYCORE_MMAP"} for i in range(9))
            return NavMeshPath(anchors, 9, 1, 80.)

        def walkable_heights_at(self, instance_id, point, radius=2.5):
            return [75.]

    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))), navmesh=_Long(reachable=()))
    nav._z.resolve_target = lambda *a, **k: SimpleNamespace(x=80., y=0., z=75., confidence=.3,
                                                            source="TERRAIN", alternatives=())
    state = {"session_id": "s", "map_id": 1409, "orientation": 0., "monotonic_time": 1., "timestamp": 1000,
             "player_world_position": {"x": 0., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS",
                                       "sample_time": 1.}}
    nav.start_skill_request("MOVE", {"x": 80., "y": 0., "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                     "require_navmesh": True, "floor_hint": "SAME"}, state, "obs0", 1.)
    assert nav._active_request.destination["z_confidence"] == .3
    assert nav._active_route.anchors[-1]["x"] <= 30.
