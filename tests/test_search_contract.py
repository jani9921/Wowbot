from wowbot.skills.search_contract import SearchCapability, SearchContext, SearchOutcome


def test_all_four_capabilities_are_named_per_spec():
    assert {c.value for c in SearchCapability} == {
        "SEARCH_LOCAL_ENTITY", "SEARCH_LOCAL_OBJECT", "SEARCH_ENTRANCE", "REACQUIRE_TARGET",
    }


def test_all_four_outcomes_are_named_per_spec():
    assert {o.value for o in SearchOutcome} == {
        "FOUND", "NOT_FOUND_WITHIN_BUDGET", "CONTEXT_CHANGED", "BLOCKED",
    }


def _context(**overrides) -> SearchContext:
    defaults = dict(origin=(0.0, 0.0), radius=20.0, query="npc:quest_giver",
                    scan_budget=6, time_budget_seconds=15.0, started_at=0.0)
    defaults.update(overrides)
    return SearchContext(**defaults)


def test_tracks_sector_coverage_without_duplicates():
    context = _context()
    context.record_sector_scanned("N")
    context.record_sector_scanned("NE")
    context.record_sector_scanned("N")
    assert context.sectors_scanned == ["N", "NE"]


def test_tracks_visited_search_points_in_order():
    context = _context()
    context.record_search_point_visited((1.0, 1.0))
    context.record_search_point_visited((2.0, 2.0))
    assert context.visited_search_points == [(1.0, 1.0), (2.0, 2.0)]


def test_scan_budget_exhaustion_stops_the_search_not_a_forever_spin():
    context = _context(scan_budget=3)
    for sector in ("N", "E", "S"):
        assert not context.is_budget_exhausted(now=1.0)
        context.record_sector_scanned(sector)
    assert context.is_budget_exhausted(now=1.0)
    assert context.scans_remaining() == 0


def test_time_budget_exhaustion_also_stops_the_search():
    context = _context(scan_budget=100, time_budget_seconds=10.0, started_at=0.0)
    assert not context.is_budget_exhausted(now=5.0)
    assert context.is_budget_exhausted(now=10.0)
    assert context.is_budget_exhausted(now=99.0)
