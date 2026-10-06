"""Z resolver (user 2026-10-06): the player's own layer from sample to sample
(Retail exports no height) and a target's walkable, reachable height scored
with MMAP, VMAP, terrain, the player's layer and the minimap floor cue."""
from dataclasses import replace
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
    assert first.z == 60. and first.confidence == .75 and first.alternatives == (98.,)
    for step in range(1, 20):
        resolved = z.observe_player(_at(float(step), 1.+step*.2), 1.+step*.2)
        assert resolved.z == 60. + step
    assert resolved.confidence == .95


class _Ledge(_Geometry):
    """Off the rim's edge at x >= 35 only the ramp below remains under the player."""

    def walkable_heights_at(self, instance_id, point, radius=2.5):
        return [40. + point["x"]] if point["x"] >= 35 else sorted({60. + point["x"], 98.})


def test_a_fall_lands_on_the_highest_layer_below():
    z = ZResolver(_Ledge())
    z.seed_player(2175, 34., 0., 98., 1.)
    fall = [{"event_type": "FALL_ENDED", "sequence": 7, "timestamp": 1000}]
    landed = z.observe_player(_at(36., 2., events=fall), 2.)
    assert landed.z == 76. and landed.source == "FALL" and z.fall_count == 1


def test_the_fall_event_waits_for_a_column_without_the_old_floor():
    """FALL_ENDED comes 1-3 s late; over the old floor it was a hop."""
    z = ZResolver(_Ledge())
    z.seed_player(2175, 30., 0., 98., 1.)
    fall = [{"event_type": "FALL_ENDED", "sequence": 7, "timestamp": 1000}]
    hop = z.observe_player(_at(30., 2., events=fall), 2.)
    assert hop.z == 98. and z.fall_count == 0


def test_a_layer_change_that_walking_cannot_explain_is_low_confidence():
    z = ZResolver(_Geometry())
    z.seed_player(2175, 0., 0., 75., 1.)            # 15 yd off any layer here
    held = z.observe_player(_at(0., 1.5), 1.5)        # held briefly (edge, lag)
    assert held.z == 75. and held.confidence == .4 and "continuity_broken_hold" in held.evidence
    unresolved = z.observe_player(_at(0., 4.), 4.)
    assert unresolved.z == 75. and unresolved.confidence == .4
    assert "continuity_broken" in unresolved.evidence
    # A further identical sample cannot promote the wrong polygon to fact.
    repeated = z.observe_player(_at(0., 5.), 5.)
    assert repeated.z == 75. and repeated.confidence == .4


def test_cave_edge_keeps_a_nearby_lower_floor_instead_of_jumping_to_the_rim():
    class _CaveEdge(_Geometry):
        def walkable_heights_at(self, instance_id, point, radius=2.5):
            return [52.7, 99.6] if point["x"] < 1. else [98.4]

        def walkable_points_near(self, instance_id, point, radius):
            # The real 11:58 Hrun's edge had the lower centre 4.5 yd away.
            return ([{"x": point["x"]-2.1, "y": point["y"]-4., "z": 51.8}]
                    if radius >= 4.5 else [])

    resolver = ZResolver(_CaveEdge())
    resolver.seed_player(2175, 0., 0., 52.7, 1.)
    edge = resolver.observe_player(_at(1., 2.), 2.)
    again = resolver.observe_player(_at(1., 3.), 3.)
    assert edge.z == again.z == 51.8
    assert edge.source == again.source == "MMAP"
    assert "continuity_near" in again.evidence
    assert again.confidence == .7


def test_missing_lower_edge_floor_never_promotes_an_old_upper_alternative():
    class _MissingEdge(_Geometry):
        def walkable_heights_at(self, instance_id, point, radius=2.5):
            return [52.7, 99.6] if point["x"] < 1. else [98.4]

    resolver = ZResolver(_MissingEdge())
    resolver.seed_player(2175, 0., 0., 52.7, 1.)
    # A tracked lower floor can retain an upper alternative from a previous
    # ambiguous column; losing the lower polygon must not promote that rim.
    resolver.player = replace(resolver.player, alternatives=(99.6,))
    first = resolver.observe_player(_at(1., 2.), 2.)
    second = resolver.observe_player(_at(1., 3.), 3.)
    assert first.z == second.z == 52.7
    assert first.confidence == second.confidence == .4


def test_pending_hop_cannot_promote_a_pit_floor_without_a_real_drop():
    class _CaveEdge(_Geometry):
        def walkable_heights_at(self, instance_id, point, radius=2.5):
            return [-3.3, 97.7]

        def walkable_points_near(self, instance_id, point, radius):
            return [{"x": point["x"] + 2., "y": point["y"], "z": 46.6}]

    resolver = ZResolver(_CaveEdge())
    resolver.seed_player(2175, 0., 0., 46.6, 1.)
    hop = [{"event_type": "FALL_ENDED", "sequence": 7, "timestamp": 1000}]
    pending = resolver.observe_player(_at(0., 2., events=hop), 2.)
    resumed = resolver.observe_player(_at(0., 6., events=hop), 6.)
    assert pending.confidence == .5 and "fall_pending" in pending.evidence
    assert resumed.z == 46.6 and "continuity_near" in resumed.evidence


def test_required_route_rejects_low_confidence_player_floor_even_without_alternatives():
    from wowbot.navigation.service import NavigationService

    class _OnlyRim(_Geometry):
        def walkable_heights_at(self, instance_id, point, radius=2.5):
            return [98.4]

    nav = NavigationService(navmesh=_OnlyRim())
    nav._z.seed_player(2175, 0., 0., 52.7, 1.)
    nav.start_skill_request(
        "MOVE", {"x": 10., "y": 0., "instance_id": 2175,
                 "coordinate_space": "WORLD_YARDS", "require_navmesh": True},
        _at(1., 2.), "obs", 2.)
    assert nav._z.player.confidence == .4
    assert nav._route_failure_reason == "ambiguous_player_layer"


def test_a_fall_never_lands_further_than_a_real_fall_can_drop():
    """Live 2026-10-06: a 1 s "fall" (a hop) put the player on the pit floor 90 yd lower."""
    class _Pit(_Geometry):
        def walkable_heights_at(self, instance_id, point, radius=2.5):
            return [-23.2, 68.7]
    z = ZResolver(_Pit())
    z.seed_player(2175, 70.8, -2240.4, 67.9, 1.)
    after = z.observe_player({"timestamp": 1000, "events": [{"event_type": "FALL_ENDED", "sequence": 9,
                                                             "timestamp": 1000}],
                              "player_world_position": {"x": 70.8, "y": -2240.4, "instance_id": 2175}}, 2.)
    assert after.z == 68.7 and z.fall_count == 0


def test_on_a_polygon_edge_the_floor_around_keeps_the_layer():
    class _Edge(_Geometry):
        def walkable_heights_at(self, instance_id, point, radius=2.5):
            return [97.2]                               # only the rim is under this exact X/Y

        def walkable_points_near(self, instance_id, point, radius):
            return [{"x": point["x"]+2., "y": point["y"], "z": 67.2}]
    z = ZResolver(_Edge())
    z.seed_player(2175, 74.9, -2252., 67.1, 1.)
    kept = z.observe_player({"player_world_position": {"x": 75.6, "y": -2256., "instance_id": 2175}}, 1.5)
    assert kept.z == 67.2 and "continuity_near" in kept.evidence


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
