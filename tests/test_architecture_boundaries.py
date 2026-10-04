"""Static guards for M1/M5 ownership boundaries, not a substitute for live tests."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src" / "wowbot"


def _source(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_policy_and_perception_modules_do_not_import_the_windows_input_backend():
    for relative in (("agent", "planner.py"), ("agent", "world.py"), ("agent", "perception.py"),
                     ("agent", "quest_dialog_planning.py"), ("agent", "target_planning.py"),
                     ("agent", "quest_location_planning.py"),
                     ("agent", "quest_planning.py"),
                     ("agent", "combat_planning.py"),
                     ("agent", "visual_inspection_planning.py"),
                     ("agent", "visual_search_planning.py"),
                     ("agent", "map_search_planning.py"),
                     ("agent", "observation_ingestion.py"),
                     ("agent", "terminal_result.py"),
                     ("agent", "quest_terminal.py"),
                     ("agent", "inspection_terminal.py"),
                     ("agent", "navigation_terminal.py"),
                     ("agent", "memory_terminal.py"),
                     ("navigation", "service.py"), ("navigation", "local_planner.py"),
                     ("vision", "world3d", "pipeline.py")):
        source = _source(*relative)
        assert "windows_input" not in source
        assert "SendInput" not in source


def test_world_reducers_have_one_model_target_but_no_planner_or_executor_dependency():
    for name in ("world_addon_reducer.py", "world_event_reducer.py", "world_entity_reducer.py", "world_ui_reducer.py",
                 "world_state_projection.py",
                 "world_evidence_reducer.py"):
        source = _source("agent", name)
        assert "WorldModel" in source
        assert "import executor" not in source.lower()
        assert "from .executor import" not in source.lower()
        assert "windows_input" not in source


def test_navigation_planners_cannot_import_the_movement_input_controller():
    for name in ("global_planner.py", "corridor.py", "local_planner.py", "contracts.py"):
        source = _source("navigation", name)
        assert "movement_controller" not in source
        assert "windows_input" not in source


def test_command_dispatch_is_a_router_not_a_backend_or_policy_owner():
    source = _source("execution", "command_dispatch.py")
    assert "windows_input" not in source
    assert "SendInput" not in source
    assert "planner" not in source.lower()
    assert "WorldModel" not in source


def test_movement_skill_runner_cannot_dispatch_input_or_finish_active_skill():
    source = _source("skills", "movement.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert "active_skill" not in source


def test_interaction_runtime_runner_cannot_dispatch_input_or_finish_active_skill():
    source = _source("skills", "interaction_runtime.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".finish(" not in source


def test_combat_runtime_runner_cannot_dispatch_input_or_finish_active_skill():
    source = _source("skills", "combat_runtime.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".finish(" not in source


def test_loot_runtime_runner_cannot_dispatch_input_or_finish_active_skill():
    source = _source("skills", "loot_runtime.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".finish(" not in source


def test_visual_runtime_runner_cannot_dispatch_input_or_finish_active_skill():
    source = _source("skills", "visual_runtime.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".finish(" not in source


def test_recovery_planner_selects_intents_but_cannot_dispatch_input():
    source = _source("agent", "recovery_planning.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert "Command(" not in source


def test_planning_orchestrator_cannot_dispatch_input_or_mutate_world_model():
    source = _source("agent", "planning_orchestration.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".ingest(" not in source
    assert "Command(" not in source


def test_skill_executor_routes_lifecycle_but_cannot_dispatch_physical_input():
    source = _source("runtime", "skill_executor.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert "SendInput" not in source


def test_execution_bookkeeping_has_no_input_or_worldmodel_authority():
    source = _source("agent", "execution_bookkeeping.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".ingest(" not in source


def test_outcome_bookkeeping_cannot_verify_dispatch_or_finalize_skills():
    source = _source("agent", "outcome_bookkeeping.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".ingest(" not in source
    assert ".finish(" not in source
    assert "Verification" not in source


def test_active_skill_supervision_routes_only_and_has_no_execution_authority():
    source = _source("agent", "active_skill_supervision.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".ingest(" not in source
    assert ".finish(" not in source
    assert "ActiveSkillRuntime(" not in source


def test_action_launch_coordinator_cannot_dispatch_or_finalize():
    source = _source("agent", "action_launch.py")
    assert "windows_input" not in source
    assert ".dispatch(" not in source
    assert ".execute(" not in source
    assert ".finish(" not in source
    assert ".ingest(" not in source
    assert "ActiveSkillRuntime(" not in source


def test_world_anchor_reducer_is_stateless_and_has_no_action_authority():
    source = _source("agent", "world_anchor_reducer.py")
    assert "__init__(" not in source
    assert "windows_input" not in source
    assert ".dispatch(" not in source
    assert ".execute(" not in source
    assert "Planner(" not in source
    assert "WorldModel(" not in source


def test_command_acknowledgement_is_local_only_and_not_quest_aware():
    source = _source("execution", "command_ack.py")
    assert "Quest" not in source
    assert "quest" not in source
    assert "world_success\": None" in source
    assert "windows_input" not in source


def test_state_invalidation_policy_has_no_input_or_planning_authority():
    source = _source("runtime", "state_invalidation.py")
    assert "windows_input" not in source
    assert ".dispatch(" not in source
    assert ".execute(" not in source
    assert "Planner(" not in source
    assert "MovementController(" not in source


def test_world_section_update_tracker_is_stateless_attribution_only():
    source = _source("agent", "world_section_updates.py")
    assert "__init__(" not in source
    assert "windows_input" not in source
    assert ".dispatch(" not in source
    assert "Planner(" not in source
    assert "WorldModel(" not in source


def test_world_state_contract_is_read_only_projection_without_authority():
    source = _source("agent", "world_state_contract.py")
    assert "windows_input" not in source
    assert ".dispatch(" not in source
    assert ".ingest(" not in source
    assert "Planner(" not in source
    assert "WorldModel(" not in source


def test_navigation_proposal_adapter_cannot_start_or_dispatch_movement():
    source = _source("agent", "navigation_planning.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".start_skill_request(" not in source
    assert ".command(" not in source


def test_quest_domain_is_a_composed_policy_not_an_embedded_or_input_owning_brain():
    planner = _source("agent", "planner.py")
    quest = _source("agent", "quest_planning.py")
    assert "class QuestDomain" not in planner
    assert "from .quest_planning import QuestDomain" in planner
    assert "windows_input" not in quest
    assert ".execute(" not in quest
    assert ".dispatch(" not in quest
    assert ".ingest(" not in quest


def test_proposal_ranker_is_input_free_and_does_not_own_planning_or_world_writes():
    source = _source("agent", "proposal_ranking.py")
    assert "windows_input" not in source
    assert ".execute(" not in source
    assert ".dispatch(" not in source
    assert ".ingest(" not in source
    assert "class Planner" not in source


def test_combat_policy_is_composed_without_target_combat_or_input_authority():
    planner = _source("agent", "planner.py")
    policy = _source("agent", "combat_planning.py")
    assert "class CombatPlanningPolicy" not in planner
    assert "from .combat_planning import CombatPlanningPolicy" in planner
    assert "windows_input" not in policy
    assert "InputExecutor" not in policy
    assert "CommandDispatcher" not in policy
    assert "ActiveSkillRuntime" not in policy
    assert "ReachMovementController" not in policy
    assert ".execute(" not in policy
    assert ".dispatch(" not in policy
    assert ".ingest(" not in policy


def test_visual_inspection_policy_is_composed_without_recognition_or_input_authority():
    planner = _source("agent", "planner.py")
    policy = _source("agent", "visual_inspection_planning.py")
    assert "class VisualInspectionPolicy" not in planner
    assert "from .visual_inspection_planning import VisualInspectionPolicy" in planner
    assert "windows_input" not in policy
    assert "InputExecutor" not in policy
    assert "CommandDispatcher" not in policy
    assert "ActiveSkillRuntime" not in policy
    assert "ReachMovementController" not in policy
    assert "semantic_type =" not in policy
    assert ".execute(" not in policy
    assert ".dispatch(" not in policy
    assert ".ingest(" not in policy


def test_visual_search_policy_returns_intents_but_owns_no_camera_or_movement_input():
    planner = _source("agent", "planner.py")
    policy = _source("agent", "visual_search_planning.py")
    assert "class VisualSearchPlanningPolicy" not in planner
    assert "from .visual_search_planning import VisualSearchPlanningPolicy" in planner
    assert "windows_input" not in policy
    assert "InputExecutor" not in policy
    assert "CommandDispatcher" not in policy
    assert "ActiveSkillRuntime" not in policy
    assert "ReachMovementController" not in policy
    assert "CameraController" not in policy
    assert ".execute(" not in policy
    assert ".dispatch(" not in policy
    assert ".ingest(" not in policy


def test_map_search_policy_is_composed_without_input_movement_or_ranking_authority():
    planner = _source("agent", "planner.py")
    policy = _source("agent", "map_search_planning.py")
    assert "class WorldMapFallbackPolicy" not in planner
    assert "from .map_search_planning import WorldMapFallbackPolicy" in planner
    assert "windows_input" not in policy
    assert "InputExecutor" not in policy
    assert "CommandDispatcher" not in policy
    assert "ReachMovementController" not in policy
    assert "ProposalRanker" not in policy
    assert ".execute(" not in policy
    assert ".dispatch(" not in policy
    assert ".ingest(" not in policy
