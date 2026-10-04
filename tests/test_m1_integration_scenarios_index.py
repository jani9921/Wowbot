"""Traceability index for the 25 M1 integration scenarios (V4-089).

This is deliberately not a re-implementation of the 25 scenarios as fresh
end-to-end tests -- most of them are already exercised, piecemeal, by
existing test files across the suite. What was missing was a single place
that maps each numbered scenario to where it is actually covered, so a
reviewer can answer "is scenario N covered?" without re-deriving it, and so
a scenario silently loses its only covering test file gets caught here
rather than discovered live.

Where no existing test confidently covers a scenario, it is listed with an
empty tuple rather than a guessed mapping.
"""
from __future__ import annotations

from pathlib import Path

TESTS_DIR = Path(__file__).parent

# scenario number -> (description, (covering test files...))
SCENARIO_COVERAGE: dict[int, tuple[str, tuple[str, ...]]] = {
    1: ("visible quest giver -> accept",
        ("test_m1_quest_offer_selector.py", "test_quest_dialog_fast_lane.py")),
    2: ("quest giver only on minimap -> locate -> accept",
        ("test_m1_objective_locator.py", "test_minimap_m74.py")),
    3: ("quest giver only on world map -> global nav -> local nav -> accept",
        ("test_m1_objective_locator.py", "test_world_map_calibration.py", "test_navigation_engine.py")),
    4: ("speak objective target initially not visible",
        ("test_m1_objective_classifier.py", "test_search_coverage.py")),
    5: ("kill area on map, no mobs initially visible",
        ("test_search_coverage.py", "test_search_region_engine_handoff.py")),
    6: ("kill wrong mob produces no credit -> strategy changes",
        ("test_credit_failure_escalation.py", "test_m1_quest_credit_gate.py")),
    7: ("collect via mob loot",
        ("test_m0_combat_loot_skills.py",)),
    8: ("collect via ground object",
        ("test_m1_object_use_skill.py",)),
    9: ("use quest tool button",
        ("test_m1_quest_item_skill.py",)),
    10: ("Extra Action Button objective",
         ("test_m1_extra_action_skill.py",)),
    11: ("travel/reach objective",
         ("test_m1_objective_locator.py", "test_navigation_engine.py")),
    12: ("multi-stage quest changes type",
         ("test_m1_primary_quest_runtime.py",)),
    13: ("turn-in NPC differs from giver",
         ("test_m1_turnin_resolver.py",)),
    14: ("field/remote turn-in",
         ("test_m1_turnin_resolver.py", "test_m1_primary_quest_runtime.py")),
    15: ("gossip choice required",
         ("test_m1_quest_offer_selector.py",)),
    16: ("minimap marker disappears on entering objective area",
         ("test_agent_map_discovery.py",)),
    17: ("wrong world-map zoom level",
         ("test_map_zoom.py",)),
    18: ("cave/entrance required",
         ("test_transition_resolver.py",)),
    19: ("indoor/multi-floor context change",
         ("test_navigation_context.py",)),
    20: ("interaction interrupted by combat",
         ("test_supervisor.py",)),
    21: ("loading/teleport",
         ("test_state_invalidation.py",)),
    22: ("cinematic",
         ("test_cinematic_handling.py",)),
    23: ("player death/recovery",
         ("test_supervisor.py", "test_m0_safe_stop.py")),
    24: ("vehicle/override state",
         ("test_state_invalidation.py",)),
    25: ("quest complete -> next campaign quest",
         ("test_m1_next_quest_resolver.py",)),
}


def test_scenario_index_covers_all_25_named_scenarios():
    assert set(SCENARIO_COVERAGE) == set(range(1, 26))


def test_every_referenced_covering_file_actually_exists():
    missing = []
    for scenario, (_, files) in SCENARIO_COVERAGE.items():
        for name in files:
            if not (TESTS_DIR / name).is_file():
                missing.append((scenario, name))
    assert not missing, f"scenario->file mapping references missing test files: {missing}"


def test_every_named_scenario_has_offline_regression_evidence():
    uncovered = {n for n, (_, files) in SCENARIO_COVERAGE.items() if not files}
    assert uncovered == set()
