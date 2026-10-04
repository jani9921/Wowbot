from wowbot.agent.evidence_freshness import FreshnessTier, classify


def test_screen_space_bbox_is_fresh_only_very_briefly():
    assert classify("screen_space_bbox", 0.1) is FreshnessTier.FRESH
    assert classify("screen_space_bbox", 0.5) is FreshnessTier.STALE
    assert classify("screen_space_bbox", 2.0) is FreshnessTier.EXPIRED


def test_local_entity_location_has_a_short_medium_window():
    assert classify("local_entity_location", 1.0) is FreshnessTier.FRESH
    assert classify("local_entity_location", 3.0) is FreshnessTier.STALE
    assert classify("local_entity_location", 5.0) is FreshnessTier.EXPIRED


def test_minimap_marker_is_short_lifetime():
    assert classify("minimap_marker", 0.2) is FreshnessTier.FRESH
    assert classify("minimap_marker", 1.0) is FreshnessTier.STALE
    assert classify("minimap_marker", 3.0) is FreshnessTier.EXPIRED


def test_quest_objective_text_is_medium_long_lifetime():
    assert classify("quest_objective_text", 10.0) is FreshnessTier.FRESH
    assert classify("quest_objective_text", 60.0) is FreshnessTier.STALE
    assert classify("quest_objective_text", 200.0) is FreshnessTier.EXPIRED


def test_quest_completion_state_never_expires_by_clock_alone():
    # Per spec: "until replaced by newer authoritative quest state" -- not
    # a timer. An extreme age must still classify as FRESH.
    assert classify("quest_completion_state", 0.0) is FreshnessTier.FRESH
    assert classify("quest_completion_state", 999_999.0) is FreshnessTier.FRESH


def test_world_map_objective_area_is_medium_lifetime():
    assert classify("world_map_objective_area", 5.0) is FreshnessTier.FRESH
    assert classify("world_map_objective_area", 30.0) is FreshnessTier.STALE
    assert classify("world_map_objective_area", 90.0) is FreshnessTier.EXPIRED


def test_unknown_category_falls_back_to_a_conservative_default_not_eternal_freshness():
    assert classify("some_unmapped_source", 0.5) is FreshnessTier.FRESH
    assert classify("some_unmapped_source", 3.0) is FreshnessTier.STALE
    assert classify("some_unmapped_source", 10.0) is FreshnessTier.EXPIRED


def test_negative_age_is_clamped_rather_than_producing_a_nonsense_tier():
    assert classify("minimap_marker", -5.0) is FreshnessTier.FRESH
