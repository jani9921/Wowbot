"""V4-091 offline M1 completion gate.

This gate binds every named M1 capability to its production artifact and
requires all 25 deterministic scenario rows to have regression evidence. It
does not substitute for selected-PID Retail validation.
"""
from pathlib import Path


def test_primary_selection_state_reading_and_objective_classification():
    from wowbot.agent.quest_runtime import QuestExecutionRuntime
    from wowbot.agent.quest_model import ObjectiveClassifier, QuestModel
    assert hasattr(QuestExecutionRuntime, "observe")
    assert hasattr(QuestExecutionRuntime(), "primary")
    assert hasattr(QuestModel, "ingest")
    assert hasattr(ObjectiveClassifier, "classify")


def test_hierarchical_location_and_all_three_visual_scales_exist():
    from wowbot.agent.objective_locator import ObjectiveLocator
    from wowbot.agent.world_map_absence_resolver import WorldMapAbsenceResolver
    from wowbot.vision.adapters.minimap import detect_minimap
    from wowbot.vision.world3d.pipeline import World3DPipeline
    assert hasattr(ObjectiveLocator, "locate")
    assert hasattr(WorldMapAbsenceResolver, "next_step")
    assert callable(detect_minimap)
    assert World3DPipeline is not None


def test_global_local_immediate_navigation_and_m0_execution_exist():
    from wowbot.navigation import NavigationService
    from wowbot.navigation.global_planner import GlobalPlanner
    from wowbot.navigation.local_planner import LocalPlanner
    from wowbot.runtime import ActiveSkillRuntime
    assert all(value is not None for value in (
        NavigationService, GlobalPlanner, LocalPlanner, ActiveSkillRuntime))


def test_credit_stage_turnin_completion_and_next_chain_owners_exist():
    from wowbot.agent.next_quest_resolver import NextQuestResolver
    from wowbot.agent.quest_runtime import QuestExecutionRuntime
    from wowbot.agent.turnin_resolver import TurnInResolver
    from wowbot.verification.quest import QuestProgressVerifier
    assert hasattr(QuestProgressVerifier, "evaluate")
    assert hasattr(QuestExecutionRuntime, "observe")
    assert hasattr(TurnInResolver, "locate")
    assert hasattr(NextQuestResolver, "resolve")


def test_all_25_m1_scenarios_have_explicit_offline_evidence():
    from test_m1_integration_scenarios_index import SCENARIO_COVERAGE
    assert set(SCENARIO_COVERAGE) == set(range(1, 26))
    assert all(files for _, files in SCENARIO_COVERAGE.values())


def test_gate_is_explicitly_offline_not_a_live_completion_claim():
    text = (Path(__file__).resolve().parents[1] / "docs" / "M1_QUEST_EXECUTION.md").read_text(
        encoding="utf-8")
    assert "not complete" in text.lower()
    assert "live validation" in text.lower()
