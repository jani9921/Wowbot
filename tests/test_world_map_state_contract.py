from wowbot.vision.world_map_state import world_map_state


def test_world_map_state_keeps_cursor_and_quest_regions_as_distinct_evidence():
    result = world_map_state({
        "world_map_open": True, "map_id": 1409, "zone_name": "Exile's Reach",
        "position": {"x": .42, "y": .61}, "world_map_pan": {"x": .2, "y": .3},
        "quest_locations": [{"quest_id": 55174, "x": .7, "y": .8}],
        "map_mouseover": {"surface": "WORLD_MAP", "tooltip": "Available Quest", "x": .7, "y": .8},
    }, frame_id="addon:51", observed_at=5.1, zoom_revision=3)

    assert result["open"] is True and result["map_id"] == 1409
    assert result["player_marker"]["coordinate_space"] == "MAP_NORMALIZED"
    assert result["quest_objective_regions"][0]["quest_id"] == 55174
    assert result["map_mouseover"]["semantic_type"] == "UNKNOWN"
    assert result["frame_id"] == "addon:51" and result["zoom_revision"] == 3
    assert result["layout_calibration"] != "FIXED_PIXELS"
