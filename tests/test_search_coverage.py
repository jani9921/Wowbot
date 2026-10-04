from wowbot.navigation.search_coverage import SearchCoveragePlanner
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy


def test_search_coverage_visits_each_cell_once_then_completes_without_target():
    coverage = SearchCoveragePlanner()
    coverage.begin("quest:area", {"map_id": 1, "x": .5, "y": .5, "radius": .03}, grid=2)
    visited = []
    for index in range(4):
        point = coverage.next_waypoint("quest:area", player_x=.5, player_y=.5)
        assert point is not None
        visited.append(point["search_cell_id"])
        coverage.observe("quest:area", player_x=point["x"], player_y=point["y"],
                         target_detected=False, now=float(index))
    assert coverage.next_waypoint("quest:area", player_x=.5, player_y=.5) is None
    assert len(set(visited)) == 4


def test_search_coverage_stops_when_target_is_detected():
    coverage = SearchCoveragePlanner()
    coverage.begin("quest:area", {"map_id": 1, "x": .5, "y": .5})
    coverage.observe("quest:area", player_x=.5, player_y=.5, target_detected=True, now=1.)
    assert coverage.next_waypoint("quest:area", player_x=.5, player_y=.5) is None


def test_search_coverage_keeps_zero_coordinate_as_a_real_player_location():
    coverage = SearchCoveragePlanner()
    coverage.begin("zero", {"map_id": 1, "x": 0., "y": 0., "radius": .03}, grid=2)
    point = coverage.next_waypoint("zero", player_x=0., player_y=0.)
    assert point is not None
    assert point["search_cell_id"].endswith(":0:0")


def test_world_search_coverage_is_bounded_and_requires_same_instance_navmesh():
    coverage = SearchCoveragePlanner()
    coverage.begin("quest:world", {
        "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
        "map_id": 1409, "x": -366., "y": -2559., "search_radius": 18.,
    }, grid=3)
    snapshot = coverage.snapshot()["quest:world"]
    for cell in snapshot["cells"]:
        assert ((cell["x"] + 366.) ** 2 + (cell["y"] + 2559.) ** 2) ** .5 <= 18.0001
    point = coverage.next_waypoint(
        "quest:world", player_x=-366., player_y=-2559.)
    assert point["coordinate_space"] == "WORLD_YARDS"
    assert point["instance_id"] == 2175
    assert point["require_navmesh"] is True


def test_blue_world_map_area_requires_quest_poi_and_affine_ground_truth():
    policy = QuestLocationPlanningPolicy()
    state = {
        "map_world_transform": {
            "ui_map_id": 1409, "instance_id": 2175,
            "origin": {"x": 1000., "y": 2000.},
            "x_axis": {"x": 100., "y": 0.},
            "y_axis": {"x": 0., "y": 200.},
        },
        "visual_candidates": [{
            "source": "WORLD_MAP_CV", "candidate_labels": ["blue_region_like"],
            "semantic_type": "UNKNOWN",
            "map_local_bounds": {"left": .4, "top": .5, "right": .6, "bottom": .7},
        }],
    }
    region = policy._remember_blue_search_region(
        state, "55122", {"map_id": 1409, "x": .5, "y": .6},
        {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
         "x": 1050., "y": 2120.})
    assert region["region_source"] == "BLUE_REGION_LIKE_ASSOCIATED"
    assert len(region["coverage_points"]) == 9
    assert all(1040. <= p["x"] <= 1060. for p in region["coverage_points"])
    assert all(2100. <= p["y"] <= 2140. for p in region["coverage_points"])

    unrelated = QuestLocationPlanningPolicy()._remember_blue_search_region(
        state, "55122", {"map_id": 1409, "x": .1, "y": .1},
        {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
         "x": 1010., "y": 2020.})
    assert unrelated is None
