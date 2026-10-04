"""Traceable registry of the twenty non-negotiable architecture invariants."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArchitectureInvariant:
    invariant_id: str
    statement: str
    owner: str
    enforcement: tuple[str, ...]


def _item(index: int, statement: str, owner: str, *enforcement: str) -> ArchitectureInvariant:
    return ArchitectureInvariant(f"INV-{index:02d}", statement, owner, tuple(enforcement))


ARCHITECTURE_INVARIANTS = (
    _item(1, "zero_or_one_active_skill", "ActiveSkillRuntime", "src/wowbot/runtime/active_skill.py"),
    _item(2, "planner_never_sends_input", "Planner", "tests/test_architecture_boundaries.py"),
    _item(3, "world_model_never_starts_skill", "WorldModel", "tests/test_final_responsibility_model.py"),
    _item(4, "executor_is_not_quest_aware", "InputExecutor", "tests/test_architecture_boundaries.py"),
    _item(5, "verifier_never_executes_action", "VerificationEngine", "tests/test_final_responsibility_model.py"),
    _item(6, "one_navigation_authority", "NavigationService", "tests/test_architecture_boundaries.py"),
    _item(7, "one_stuck_authority", "StuckClassifier", "tests/test_stuck_resolver.py"),
    _item(8, "quest_credit_has_one_verifier", "QuestProgressVerifier", "tests/test_m1_quest_progress_verifier.py"),
    _item(9, "skill_success_is_not_quest_success", "VerificationEngine", "tests/test_m0_combat_loot_skills.py"),
    _item(10, "stage_change_invalidates_localization", "QuestExecutionRuntime", "tests/test_m1_primary_quest_runtime.py"),
    _item(11, "world_transition_invalidates_local_state", "StateInvalidationPolicy", "tests/test_state_invalidation.py"),
    _item(12, "cancel_and_fatal_release_keys", "InputScheduler", "tests/test_m0_safe_stop.py"),
    _item(13, "retry_is_bounded", "FailureManager", "tests/test_global_architecture_invariants.py"),
    _item(14, "local_search_is_bounded", "SearchSkill", "tests/test_global_architecture_invariants.py"),
    _item(15, "nonretryable_decision_needs_new_evidence", "DecisionFingerprintGuard", "tests/test_decision_fingerprint.py"),
    _item(16, "coordinates_have_explicit_space", "NavigationRequest", "tests/test_navigation_contracts.py"),
    _item(17, "one_writer_per_state_field", "WorldSectionUpdateTracker", "tests/test_world_section_updates.py"),
    _item(18, "raw_detection_requires_normalization", "WorldStateProjector", "tests/test_perception_unknown_regression.py"),
    _item(19, "missing_3d_cue_is_not_not_found", "WorldMapFallbackPolicy", "tests/test_quest_info_hierarchy.py"),
    _item(20, "cue_navigation_works_without_world_coordinates", "VisualApproachController", "tests/test_vision_seek.py"),
)


def invariant(invariant_id: str) -> ArchitectureInvariant:
    return next(item for item in ARCHITECTURE_INVARIANTS
                if item.invariant_id == str(invariant_id))
