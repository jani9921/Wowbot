"""V4-025/V4-026 wiring: NavigationService.current_navigation_context/resolve_transition."""
from wowbot.navigation import NavigationContext, NavigationService, TransitionKind


def test_navigation_service_classifies_context_from_state():
    service = NavigationService()
    assessment = service.current_navigation_context({"in_vehicle": True})
    assert assessment.context is NavigationContext.VEHICLE


def test_navigation_service_context_defaults_to_unknown_without_evidence():
    service = NavigationService()
    assessment = service.current_navigation_context({})
    assert assessment.context is NavigationContext.UNKNOWN


def test_navigation_service_resolves_transition_from_signals():
    service = NavigationService()
    result = service.resolve_transition({
        "repeated_local_route_blockage": True, "cave_entrance_cue": True,
    })
    assert result.kind is TransitionKind.FIND_CAVE_ENTRANCE


def test_navigation_service_transition_resolution_is_unsupported_without_signals():
    service = NavigationService()
    result = service.resolve_transition({})
    assert not result.supported


def test_these_reads_do_not_touch_the_stuck_resolver_state():
    service = NavigationService()
    before = service._stuck.active
    service.current_navigation_context({"in_vehicle": True})
    service.resolve_transition({"repeated_local_route_blockage": True})
    assert service._stuck.active == before
