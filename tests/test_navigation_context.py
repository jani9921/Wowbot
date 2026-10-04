from wowbot.navigation import NavigationContext, NavigationContextClassifier


def test_no_evidence_yields_unknown_not_a_guess():
    result = NavigationContextClassifier().classify({})
    assert result.context is NavigationContext.UNKNOWN
    assert result.confidence == 0.0


def test_vehicle_flag_takes_priority_over_everything_else():
    result = NavigationContextClassifier().classify(
        {"in_vehicle": True, "is_indoors": True, "loading": True})
    assert result.context is NavigationContext.VEHICLE
    assert result.confidence == 1.0


def test_area_transition_reports_transition_context():
    result = NavigationContextClassifier().classify({"area_transition_active": True})
    assert result.context is NavigationContext.TRANSITION


def test_loading_flag_also_reports_transition_context():
    result = NavigationContextClassifier().classify({"loading": True})
    assert result.context is NavigationContext.TRANSITION


def test_multiple_world_map_floors_reports_multi_floor():
    result = NavigationContextClassifier().classify({"world_map_floor_count": 3})
    assert result.context is NavigationContext.MULTI_FLOOR


def test_cave_entrance_signal_reports_cave():
    result = NavigationContextClassifier().classify({"cave_entrance_detected": True})
    assert result.context is NavigationContext.CAVE


def test_area_type_cave_reports_cave_even_without_entrance_flag():
    result = NavigationContextClassifier().classify({"area_type": "Cave"})
    assert result.context is NavigationContext.CAVE


def test_addon_is_indoors_true_reports_indoor():
    result = NavigationContextClassifier().classify({"is_indoors": True})
    assert result.context is NavigationContext.INDOOR
    assert "addon_is_indoors_true" in result.evidence


def test_addon_is_indoors_false_reports_outdoor():
    result = NavigationContextClassifier().classify({"is_indoors": False})
    assert result.context is NavigationContext.OUTDOOR
