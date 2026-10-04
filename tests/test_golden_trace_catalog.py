from pathlib import Path

from wowbot.diagnostics import (
    GOLDEN_TRACES,
    ReplayPlayer,
    load_golden_trace,
    validate_golden_catalog,
)


TRACE = Path(__file__).parent / "fixtures" / "golden_traces" / "m1_core.jsonl"


def test_all_seven_design_scenarios_are_real_semantically_valid_replay_sessions():
    catalog = validate_golden_catalog(TRACE)
    assert set(catalog) == {
        "interact", "combat_recovery", "navigation_stuck", "quest_speak",
        "quest_kill", "collect", "turn_in",
    }
    assert len(GOLDEN_TRACES) == 7
    assert all(len(records) == 6 for records in catalog.values())


def test_each_golden_trace_is_deterministically_self_comparable():
    for spec in GOLDEN_TRACES:
        records = load_golden_trace(TRACE, spec)
        player = ReplayPlayer()
        player.records = records
        comparison = player.compare_golden_trace(records)
        assert comparison.equal
        assert comparison.compared_records == len(records)


def test_golden_catalog_has_no_input_executor_dependency():
    source = (Path(__file__).parents[1] / "src" / "wowbot" / "diagnostics" /
              "golden_trace_catalog.py").read_text(encoding="utf-8")
    assert "InputExecutor" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source

