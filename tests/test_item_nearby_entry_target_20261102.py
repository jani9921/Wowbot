"""Live 2026-11-02 (26257 "It's Alive!"): the Harvest Watcher Heart's spell
"Wake Harvest Golem" targets 25 (UNIT_TARGET_ANY) + 46 (DEST_NEARBY_ENTRY).
46 was not a known selector, so the item read UNKNOWN and the agent only
walked the quest area.  Nearby-entry selectors (38/40/46) are automatic; with
an explicit unit target the item is a UNIT use (select the golem, use it)."""
from wowbot.quests.client_supplement import target_profile


def effects(*pairs):
    return [{"target_a": a, "target_b": b} for a, b in pairs]


def test_a_unit_target_plus_a_nearby_entry_destination_is_a_unit_use():
    assert target_profile(effects((25, 46)), [])["target_mode"] == "UNIT"


def test_a_nearby_entry_selector_alone_is_automatic_not_unknown():
    assert target_profile(effects((46, 0)), [])["target_mode"] == "AREA"
    assert target_profile(effects((38, 0)), [])["target_mode"] == "AREA"
