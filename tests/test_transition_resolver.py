from wowbot.navigation import TransitionKind, TransitionResolver


def test_no_blockage_and_no_map_absence_signal_does_not_propose_a_transition():
    result = TransitionResolver().resolve({})
    assert result.kind is TransitionKind.UNKNOWN_TRANSITION
    assert not result.supported


def test_single_isolated_signal_without_repetition_is_not_enough():
    # A one-off "target not visible" glance is not "repeated" blockage --
    # the resolver must not fire on a single frame of evidence.
    result = TransitionResolver().resolve({"target_visible_3d": False})
    assert not result.supported


def test_repeated_local_route_blockage_is_supported_evidence():
    result = TransitionResolver().resolve({"repeated_local_route_blockage": True})
    assert result.supported
    assert "repeated_local_route_blockage" in result.evidence


def test_map_distance_low_with_absent_3d_target_is_supported_evidence():
    result = TransitionResolver().resolve({"map_distance_low": True, "target_visible_3d": False})
    assert result.supported


def test_floor_signal_resolves_to_change_floor():
    result = TransitionResolver().resolve({
        "repeated_local_route_blockage": True, "floor_interior_map_appears": True,
    })
    assert result.kind is TransitionKind.CHANGE_FLOOR


def test_target_above_or_below_also_resolves_to_change_floor():
    result = TransitionResolver().resolve({
        "repeated_local_route_blockage": True, "target_above_or_below": True,
    })
    assert result.kind is TransitionKind.CHANGE_FLOOR


def test_cave_entrance_cue_resolves_to_find_cave_entrance():
    result = TransitionResolver().resolve({
        "repeated_local_route_blockage": True, "cave_entrance_cue": True,
    })
    assert result.kind is TransitionKind.FIND_CAVE_ENTRANCE


def test_portal_cue_resolves_to_use_portal():
    result = TransitionResolver().resolve({
        "repeated_local_route_blockage": True, "portal_cue": True,
    })
    assert result.kind is TransitionKind.USE_PORTAL


def test_transport_cue_resolves_to_use_transport():
    result = TransitionResolver().resolve({
        "repeated_local_route_blockage": True, "transport_cue": True,
    })
    assert result.kind is TransitionKind.USE_TRANSPORT


def test_entrance_icon_resolves_to_enter_building():
    result = TransitionResolver().resolve({
        "repeated_local_route_blockage": True, "entrance_icon_cue": True,
    })
    assert result.kind is TransitionKind.ENTER_BUILDING


def test_supported_but_no_specific_cue_stays_unknown_transition_for_bounded_search():
    result = TransitionResolver().resolve({"repeated_local_route_blockage": True})
    assert result.kind is TransitionKind.UNKNOWN_TRANSITION
    assert result.supported
