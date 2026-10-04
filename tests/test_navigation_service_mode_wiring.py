"""V4-023 wiring: NavigationService.current_navigation_mode()."""
from wowbot.navigation import NavigationMode, NavigationModeEvidence, NavigationService


def test_reliable_world_position_in_state_selects_telemetry_assisted():
    service = NavigationService()
    state = {"player_world_position": {"x": 10.0, "y": 20.0, "z": 0.0}}
    assert service.current_navigation_mode(state) is NavigationMode.TELEMETRY_ASSISTED


def test_missing_world_position_falls_back_to_caller_supplied_vision_evidence():
    service = NavigationService()
    evidence = NavigationModeEvidence(has_minimap_direction=True)
    assert service.current_navigation_mode({}, vision_evidence=evidence) is NavigationMode.VISION_ONLY


def test_no_position_and_no_vision_evidence_is_unsupported():
    service = NavigationService()
    assert service.current_navigation_mode({}) is NavigationMode.UNSUPPORTED


def test_reads_are_free_of_side_effects_on_the_service():
    service = NavigationService()
    before = service._active_route
    service.current_navigation_mode({"player_world_position": {"x": 1.0, "y": 1.0}})
    assert service._active_route is before
