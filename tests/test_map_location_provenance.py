from wowbot.agent.spatial_memory import SpatialMemory


def test_map_hover_retains_provenance_without_claiming_npc_position(tmp_path):
    memory = SpatialMemory(tmp_path)
    state = {"session_id": "test", "map_id": 1609, "frame_id": "frame-1",
             "cursor_position": {"nx": .4, "ny": .3},
             "map_mouseover": {"surface": "WORLD_MAP", "map_id": 1609,
                 "x": .619, "y": .829, "quest_id": 123,
                 "tooltip": "Available quest", "semantic_type": "QUEST_GIVER"}}
    locations = memory.ingest(state, 10, probe={"source": "WORLD_MAP_CV",
        "x": .4, "y": .3, "track_id": "unknown-marker-1"})
    assert len(locations) == 1
    location = locations[0]
    assert location["entity_position_confirmed"] is False
    assert location["coordinate_space"] == "NORMALIZED_MAP"
    assert location["provenance"]["coordinate_source"] == "MAP_CURSOR"
    assert location["provenance"]["quest_id"] == 123
    assert location["provenance"]["track_id"] == "unknown-marker-1"
    assert SpatialMemory(tmp_path).points.points(1609)[0]["provenance"] == location["provenance"]
