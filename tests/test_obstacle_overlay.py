from wowbot.diagnostics import obstacle_overlay


def test_overlay_exposes_major_obstacle_evidence_without_semantic_requirement():
    result = obstacle_overlay({
        "frame_id": "frame:1", "timestamp": 2.,
        "ego_motion": {"commanded_motion": "FORWARD", "motion_kind": "NONE",
                       "motion_vector": {"x": 0., "y": 0.}},
        "traversability": {
            "coordinate_space": "WORLD_VIEWPORT_NORMALIZED",
            "sectors": [{
                "sector": "CENTER", "state": "DANGEROUS",
                "ground_confidence": .2, "free_space_confidence": .1,
                "obstacle_confidence": .9, "danger_confidence": .95,
                "drop_confidence": .9, "dynamic_probability": 0.,
                "traversability_score": .02, "traversal_cost": float("inf"),
                "collision_evidence_confidence": .8,
                "motion_mismatch_confidence": .9,
                "obstacle_lifecycle": "CONFIRMED",
                "evidence": ["unknown_collision"],
            }],
        },
    }, {"active_request": {"mode": "MOVE_TO_LOCATION"},
        "local_plan": {"local_waypoint": {"x": .4, "y": .6}}})

    assert result["schema"] == "OBSTACLE_OVERLAY_V1"
    assert result["frame_id"] == "frame:1"
    assert result["expected_ego_motion"] == "FORWARD"
    assert result["observed_ego_motion"] == "NONE"
    assert result["selected_local_waypoint"] == {"x": .4, "y": .6}
    center = result["sectors"][0]
    assert center["state"] == "DANGEROUS"
    assert center["drop_confidence"] == .9
    assert center["collision_confidence"] == .8
    assert center["evidence"] == ["unknown_collision"]


def test_overlay_is_read_only_and_handles_absent_optional_channels():
    world = {"traversability": {"sectors": [{"sector": "LEFT"}]}}
    result = obstacle_overlay(world)
    assert result["sectors"][0]["state"] == "UNKNOWN"
    assert result["dynamic_obstacles"] == []
    assert world == {"traversability": {"sectors": [{"sector": "LEFT"}]}}
