from pathlib import Path
import struct

from wowbot.navigation.contracts import NavigationRequest
from wowbot.navigation.global_planner import GlobalPlanner
from wowbot.navigation.mmap_navmesh import (DETOUR_NAVMESH_MAGIC, MMAP_MAGIC,
                                             NavMeshPath, NavPolygon,
                                             TrinityMMapNavMesh)
from wowbot.navigation.service import NavigationService


def _poly(refs, neighbours, flags=1):
    refs = tuple(refs) + (0,) * (6-len(refs))
    neighbours = tuple(neighbours) + (0,) * (6-len(neighbours))
    return (struct.pack("<I", 0xffffffff) + struct.pack("<6H", *refs)
            + struct.pack("<6H", *neighbours)
            + struct.pack("<HBB", flags, 4, 0))


def _tile(flags=1) -> bytes:
    # Two adjacent convex ground polygons in Detour (WoW Y,Z,X) space.
    vertices = (
        -2615., 0., -450.,  -2615., 0., -449.,  -2615., 0., -448.,
        -2613., 0., -450.,  -2613., 0., -449.,  -2613., 0., -448.,
    )
    header = struct.pack(
        "<15i10f", DETOUR_NAVMESH_MAGIC, 7, 9, 27, 0, 0,
        2, 6, 0, 0, 0, 0, 0, 0, 0,
        1.6, .533333, 1.6,
        -2666.666, -20., -533.333, -2133.333, 20., 0., 1.)
    mesh = (header + struct.pack("<18f", *vertices)
            + _poly((0, 1, 4, 3), (0, 2, 0, 0), flags)
            + _poly((1, 2, 5, 4), (0, 0, 0, 1), flags))
    return struct.pack("<5I", MMAP_MAGIC, 7, 16, len(mesh), 1) + mesh


def test_trinity_mmap_routes_verified_world_yards_through_polygon_graph(tmp_path: Path):
    (tmp_path / "2175.mmap").write_bytes(b"header-present")
    (tmp_path / "2175_32_36.mmtile").write_bytes(_tile())
    navmesh = TrinityMMapNavMesh(tmp_path)

    result = navmesh.find_path(
        2175, {"x": -449.7, "y": -2614.0, "z": 0.},
        {"x": -448.3, "y": -2614.0, "z": 0.})

    assert result is not None
    assert result.polygon_count == 2
    assert len(result.anchors) == 2  # funnel removes the needless portal-centre turn
    assert result.anchors[0]["coordinate_space"] == "WORLD_YARDS"
    assert result.anchors[0]["source"] == "TRINITYCORE_MMAP"
    assert result.anchors[-1]["instance_id"] == 2175
    assert navmesh.last_diagnostics["reason"] == "route_found"
    navmesh.find_path(
        2175, {"x": -449.6, "y": -2614.0, "z": 0.},
        {"x": -448.4, "y": -2614.0, "z": 0.})
    assert navmesh.last_diagnostics["graph_cache_hit"] is True


def test_default_walking_filter_does_not_route_over_water(tmp_path: Path):
    (tmp_path / "2175.mmap").write_bytes(b"header-present")
    (tmp_path / "2175_32_36.mmtile").write_bytes(_tile(flags=4))
    start = {"x": -449.7, "y": -2614.0, "z": 0.}
    end = {"x": -448.3, "y": -2614.0, "z": 0.}

    assert TrinityMMapNavMesh(tmp_path).find_path(2175, start, end) is None
    assert TrinityMMapNavMesh(tmp_path, allowed_flags=4).find_path(2175, start, end) is not None


def _graph_poly(key, x, height, z):
    return NavPolygon(key, (
        (x-.1, height, z-.1), (x+.1, height, z-.1),
        (x+.1, height, z+.1), (x-.1, height, z+.1),
    ), (), 1)


def test_polygon_astar_avoids_live_unwalkable_45_degree_cliff(tmp_path: Path):
    (tmp_path / "2175.mmap").write_bytes(b"header-present")
    navmesh = TrinityMMapNavMesh(tmp_path)
    start, cliff, detour_a, detour_b, destination = range(5)
    polygons = {
        start: _graph_poly(start, 0., 0., 0.),
        cliff: _graph_poly(cliff, 1., 1., 0.),  # exactly 45 degrees
        detour_a: _graph_poly(detour_a, 0., 0., 2.),
        detour_b: _graph_poly(detour_b, 2., 0., 2.),
        destination: _graph_poly(destination, 2., 0., 0.),
    }
    adjacency = {
        start: {cliff, detour_a}, cliff: {start, destination},
        detour_a: {start, detour_b}, detour_b: {detour_a, destination},
        destination: {cliff, detour_b},
    }

    chain = navmesh._a_star(polygons, adjacency, start, destination)

    assert chain == (start, detour_a, detour_b, destination)
    assert navmesh._walkable_transition(polygons[start].center,
                                        polygons[cliff].center) is False


def test_player_xy_is_projected_to_a_navmesh_surface_height(tmp_path: Path):
    (tmp_path / "2175.mmap").write_bytes(b"header-present")
    (tmp_path / "2175_32_36.mmtile").write_bytes(_tile())
    navmesh = TrinityMMapNavMesh(tmp_path)

    projected = navmesh.project_position(
        2175, {"x": -449.7, "y": -2614.0, "coordinate_space": "WORLD_YARDS"})

    assert projected is not None
    assert projected["z"] == 0.
    assert projected["z_known"] is True
    assert projected["z_observed"] is False
    assert projected["z_source"] == "NAVMESH_SURFACE"
    assert projected["source"] == "TRINITYCORE_MMAP_SURFACE"
    assert navmesh.last_surface_projection["status"] == "PROJECTED"
    assert navmesh.last_surface_projection["surface_index_candidates"] < 10


def test_surface_projection_reuses_bounded_spatial_index(tmp_path: Path):
    (tmp_path / "2175.mmap").write_bytes(b"header-present")
    (tmp_path / "2175_32_36.mmtile").write_bytes(_tile())
    navmesh = TrinityMMapNavMesh(tmp_path)

    first = navmesh.project_position(2175, {"x": -449.7, "y": -2614.0})
    cache_size = len(navmesh._surface_index_cache)
    second = navmesh.project_position(2175, {"x": -449.6, "y": -2614.0})

    assert first is not None and second is not None
    assert len(navmesh._surface_index_cache) == cache_size == 1
    assert navmesh.last_surface_projection["surface_index_candidates"] < 10


class _FakeNavMesh:
    def __init__(self):
        self.calls = []

    def find_path(self, instance_id, start, destination):
        self.calls.append((instance_id, start, destination))
        return NavMeshPath((
            {"x": start["x"], "y": start["y"], "z": 0., "source": "TRINITYCORE_MMAP"},
            {"x": 5., "y": 3., "z": 0., "source": "TRINITYCORE_MMAP"},
            {"x": destination["x"], "y": destination["y"], "z": 0., "source": "TRINITYCORE_MMAP"},
        ), 7, 2, 9.)


class _NoRouteNavMesh(_FakeNavMesh):
    def find_path(self, instance_id, start, destination):
        self.calls.append((instance_id, start, destination))
        return None


class _SurfaceFakeNavMesh(_FakeNavMesh):
    def __init__(self):
        super().__init__()
        self.projections = []

    def project_position(self, instance_id, point, *, z_hint=None):
        self.projections.append((instance_id, dict(point), z_hint))
        return {**point, "z": 42., "z_known": True, "z_observed": False,
                "z_estimated": True, "source": "TRINITYCORE_MMAP_SURFACE",
                "z_source": "NAVMESH_SURFACE"}


def _request(destination):
    return NavigationRequest("r", "c", "MOVE_TO_LOCATION", destination)


def test_global_planner_uses_mmap_only_for_same_instance_verified_world_space():
    provider = _FakeNavMesh()
    planner = GlobalPlanner(navmesh=provider)
    state = {"map_id": 1609, "player_world_position": {
        "x": 1., "y": 2., "z": 0., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS"}}
    destination = {"x": 9., "y": 4., "z": 0., "instance_id": 2175,
                   "coordinate_space": "WORLD_YARDS"}

    route = planner.plan(_request(destination), state, 1.)

    assert len(provider.calls) == 1
    assert route.anchors[1]["source"] == "TRINITYCORE_MMAP"
    assert route.regions[0]["route_source"] == "TRINITYCORE_MMAP"
    assert route.confidence == .95
    assert route.valid_until == 301.

    planner.plan(_request({"x": .9, "y": .4, "coordinate_space": "NORMALIZED_MAP"}),
                 state, 2.)
    planner.plan(_request({**destination, "instance_id": 999}), state, 3.)
    assert len(provider.calls) == 1


def test_navigation_service_keeps_single_movement_authority_for_mmap_waypoints():
    provider = _FakeNavMesh()
    service = NavigationService(navmesh=provider)
    state = {"player_world_position": {
        "x": 1., "y": 2., "z": 0., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS"}}
    destination = {"x": 9., "y": 4., "z": 0., "instance_id": 2175,
                   "coordinate_space": "WORLD_YARDS"}

    service.start_skill_request("MOVE", destination, state, "obs:1", 1.)
    snapshot = service.snapshot(1.)

    assert snapshot["authority"] == "NavigationService"
    assert snapshot["global_route"]["anchors"][1]["source"] == "TRINITYCORE_MMAP"
    assert snapshot["global_route"]["route_source"] == "TRINITYCORE_MMAP"
    assert snapshot["movement"]["destination"]["x"] == 5.
    assert snapshot["movement"]["destination"]["route_waypoint_final"] is False
    assert snapshot["navmesh"]["configured"] is True


def test_intermediate_mmap_waypoint_advances_when_sparse_samples_cross_it():
    service = NavigationService(navmesh=_FakeNavMesh())
    start = {"orientation": 0., "movement": {"moving": True, "speed": 7.},
             "player_world_position": {
                 "x": 1., "y": 2., "z": 0., "instance_id": 2175,
                 "coordinate_space": "WORLD_YARDS"}}
    destination = {"x": 9., "y": 4., "z": 0., "instance_id": 2175,
                   "coordinate_space": "WORLD_YARDS"}
    service.start_skill_request("MOVE", destination, start, "obs:start", 1.)
    # No observation lands inside the ordinary 4.5-yard arrival circle.  The
    # segment from start to this sample nevertheless traverses the (5,3)
    # corridor anchor and must never cause a reversal to that old anchor.
    crossed = {**start, "player_world_position": {
        **start["player_world_position"], "x": 8., "y": 3.75}}

    assessment = service.observe(crossed, "obs:crossed", 2.)

    assert assessment.reason == "route_waypoint_advanced"
    snapshot = service.snapshot(2.)
    assert snapshot["route_waypoint_index"] == 2
    assert snapshot["movement"]["destination"]["route_waypoint_final"] is True


def test_navigation_service_refreshes_player_surface_from_active_corridor():
    provider = _SurfaceFakeNavMesh()
    service = NavigationService(navmesh=provider)
    state = {"orientation": 0., "player_world_position": {
        "x": 1., "y": 2., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS", "z_known": False}}
    destination = {"x": 9., "y": 4., "instance_id": 2175,
                   "coordinate_space": "WORLD_YARDS", "require_navmesh": True}

    service.start_skill_request("MOVE", destination, state, "obs:surface", 1.)
    service.observe(state, "obs:surface:2", 1.1)
    snapshot = service.snapshot(1.1)

    assert provider.projections
    assert provider.projections[-1][2] == 0.
    assert snapshot["player_surface_projection"]["z"] == 42.
    assert snapshot["player_surface_projection"]["z_source"] == "NAVMESH_SURFACE"


def test_navigation_service_projects_one_fast_sample_only_once_across_observe_and_command():
    provider = _SurfaceFakeNavMesh()
    service = NavigationService(navmesh=provider)
    state = {"orientation": 0., "player_world_position": {
        "x": 1., "y": 2., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS", "z_known": False}}
    destination = {"x": 9., "y": 4., "instance_id": 2175,
                   "coordinate_space": "WORLD_YARDS", "require_navmesh": True}
    service.start_skill_request("MOVE", destination, state, "obs:start", 1.)
    provider.projections.clear()
    state = {**state, "player_world_position": {
        **state["player_world_position"], "x": 1.25}}

    service.observe(state, "obs:fast", 1.1)
    service.command(state, "obs:fast", 1.1)

    assert len(provider.projections) == 1


def test_required_mmap_route_never_falls_back_to_direct_line():
    provider = _NoRouteNavMesh()
    service = NavigationService(navmesh=provider)
    state = {"orientation": 0., "player_world_position": {
        "x": 1., "y": 2., "z": 3., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS"}}
    destination = {"x": 9., "y": 4., "instance_id": 2175, "map_id": 1409,
                   "coordinate_space": "WORLD_YARDS", "z_known": False,
                   "require_navmesh": True, "purpose": "LOCATE_TURN_IN_REGION"}

    service.start_skill_request("MOVE", destination, state, "obs:no-route", 1.)

    snapshot = service.snapshot(1.)
    assert snapshot["global_route"]["anchors"] == []
    assert snapshot["global_route"]["route_source"] == "MMAP_REQUIRED_UNAVAILABLE"
    assert snapshot["route_failure_reason"] == "required_navmesh_route_unavailable"
    assert service.command(state, "obs:no-route", 1.1) == ()
    assessment = service.observe(state, "obs:no-route", 1.1)
    assert assessment.terminal and not assessment.success
    assert assessment.reason == "required_navmesh_route_unavailable"


def test_api_world_endpoint_without_z_is_projected_onto_navmesh_height():
    provider = _FakeNavMesh()
    planner = GlobalPlanner(navmesh=provider)
    state = {"map_id": 1409, "player_world_position": {
        "x": 1., "y": 2., "z": 7., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS"}}
    destination = {"x": 9., "y": 4., "instance_id": 2175, "map_id": 1409,
                   "coordinate_space": "WORLD_YARDS", "z_known": False,
                   "require_navmesh": True}

    route = planner.plan(_request(destination), state, 1.)

    assert route.regions[0]["route_source"] == "TRINITYCORE_MMAP"
    assert provider.calls[0][2]["z_known"] is False
    assert route.regions[0]["map_id"] == 1409


def test_mmap_module_has_no_input_or_runtime_authority():
    source = Path("src/wowbot/navigation/mmap_navmesh.py").read_text(encoding="utf-8")
    assert "InputExecutor" not in source
    assert "Command(" not in source
    assert "WorldModel" not in source
