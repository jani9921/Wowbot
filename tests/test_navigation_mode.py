from wowbot.navigation.navigation_mode import (
    NavigationMode,
    NavigationModeEvidence,
    resolve_navigation_mode,
)


def test_reliable_world_position_selects_telemetry_assisted():
    evidence = NavigationModeEvidence(has_reliable_player_world_position=True)
    assert resolve_navigation_mode(evidence) is NavigationMode.TELEMETRY_ASSISTED


def test_telemetry_wins_even_when_vision_cues_are_also_present():
    evidence = NavigationModeEvidence(has_reliable_player_world_position=True, has_minimap_direction=True)
    assert resolve_navigation_mode(evidence) is NavigationMode.TELEMETRY_ASSISTED


def test_missing_xyz_alone_does_not_fail_when_any_vision_cue_exists():
    # "Do NOT fail merely because absolute XYZ is unavailable."
    evidence = NavigationModeEvidence(has_minimap_direction=True)
    assert resolve_navigation_mode(evidence) is NavigationMode.VISION_ONLY


def test_each_of_the_eight_named_vision_cues_alone_is_sufficient():
    fields = [
        "has_world_map_location_belief", "has_minimap_direction", "has_heading_change",
        "has_scene_motion", "has_landmarks", "has_objective_marker_trend",
        "has_local_entity_acquisition", "has_arrival_or_quest_state_evidence",
    ]
    for field_name in fields:
        evidence = NavigationModeEvidence(**{field_name: True})
        assert resolve_navigation_mode(evidence) is NavigationMode.VISION_ONLY, field_name


def test_no_evidence_at_all_is_unsupported_not_a_silent_guess():
    assert resolve_navigation_mode(NavigationModeEvidence()) is NavigationMode.UNSUPPORTED
