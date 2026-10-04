from wowbot.vision.ui_parser import parse_ui_observations


def test_ui_parser_normalizes_required_states_with_frame_contract():
    records = parse_ui_observations({
        "player_present": True, "health": 20, "max_health": 30,
        "target": {"guid": "Creature-1", "name": "Murloc", "health": 10},
        "is_casting": True, "quest_ui": {"open": True, "action": "ACCEPT"},
        "gossip_ui": {"open": True}, "vendor_ui": {"open": True},
        "loot_open": True, "active_quests": [{"quest_id": 1}],
        "ui_error": "Out of range", "loading": True,
    }, frame_id="addon:44", observed_at=4.4)
    by_name = {record["ui_element"]: record for record in records}

    assert {"PLAYER_FRAME", "TARGET_FRAME", "CAST_BAR", "QUEST_DIALOG", "GOSSIP", "MERCHANT",
            "LOOT", "QUEST_TRACKER", "ERROR_STATE", "LOADING_SCREEN"} == set(by_name)
    assert all(record["frame_id"] == "addon:44" and record["timestamp_monotonic"] == 4.4
               for record in records)
    assert by_name["QUEST_DIALOG"]["details"]["action"] == "ACCEPT"
    assert by_name["LOADING_SCREEN"]["state"] == "VISIBLE"
    assert all(record["fact"] is False for record in records)


def test_ui_parser_does_not_invent_absent_ui():
    records = parse_ui_observations({}, frame_id="addon:45", observed_at=4.5)
    assert all(record["state"] == "ABSENT" for record in records)
    assert all(record["confidence"] == 0. for record in records)
