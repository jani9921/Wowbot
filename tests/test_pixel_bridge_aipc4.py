from adapters.pixel_bridge import payload_to_state


def _aipc4_payload() -> str:
    fields = [
        "AIPC4", "1700000000", "RetailWarrior", "1409", "42000", "61000", "1570",
        "85", "100", "20", "100", "0", "0", "0", "Quest NPC", "Exile's Reach", "North",
        "7", "0", "-1", "0",  # quest paging
        "0",  # action count
        "0", "0",  # quest UI open/count
        "", "0", "0", "0",  # quest UI action/x/y/id
        "0", "0",  # target attackable/dead
        "0",  # no unit mouseover block
        "50000", "25000",  # cursor
        "WORLD_MAP", "QUEST_GIVER", "1409", "43000", "62000", "", "",
        "Available Quest", "Quest NPC", "171997", "Creature-1-2-3-4-171997-ABC",
        "", "Available Quest", "",  # UI error, tooltip, tutorial
        "0",  # corpse count
        "0.7.0", "2", "42", "MAP_MOUSEOVER_CHANGED", "WOW_API_TOOLTIP", "1700000000",
    ]
    return "|".join(fields)


def test_aipc4_uses_paged_quest_layout_and_decodes_map_mouseover() -> None:
    state = payload_to_state(_aipc4_payload())
    assert state["zone_name"] == "Exile's Reach"
    assert state["quest_state_revision"] == 7
    assert state["map_mouseover"]["semantic_type"] == "QUEST_GIVER"
    assert state["map_mouseover"]["x"] == 0.43
    assert state["map_mouseover"]["unit"]["npc_id"] == 171997


def test_aipc4_decodes_addon_health_and_latest_event_metadata() -> None:
    state = payload_to_state(_aipc4_payload())
    assert state["protocol_version"] == "AIPC4"
    assert state["addon_version"] == "0.7.0"
    assert state["schema_version"] == 2
    assert state["latest_event"] == {
        "sequence": 42,
        "event_type": "MAP_MOUSEOVER_CHANGED",
        "source": "WOW_API_TOOLTIP",
        "timestamp": 1700000000.0,
    }
    assert state["heartbeat"]["player_present"] is True
