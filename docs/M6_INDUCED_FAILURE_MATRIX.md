# M6 induced-failure matrix

Status date: 2026-09-18. This is an evidence ledger, not a release claim.
Every row needs both deterministic replay coverage and, before release, a
selected-PID live record in `LIVE_VALIDATION.md`.

| ID | Induced situation | Offline evidence | Expected bounded outcome | Live |
| --- | --- | --- | --- | --- |
| M6-F01 | `OUT_OF_RANGE` | `tests/test_m0_acceptance_matrix.py` | same attempt asks canonical approach/retries | OPEN |
| M6-F02 | `FACING_INVALID` | `tests/test_agent_core.py::test_combat_facing_error_half_turns_then_retries_ability_without_stale_repeat` | one facing correction, then retry or terminal failure | OPEN |
| M6-F03 | `LOS_FAILED` | `tests/test_m0_acceptance_matrix.py` | one local NavigationService reposition, bounded retry | OPEN |
| M6-F04 | `TARGET_LOST` | `tests/test_m0_combat_loot_skills.py` and `tests/test_autonomous_commitment_loop.py` | typed failure; replan only after distinct missing observations | OPEN |
| M6-F05 | `NPC_MOVED` | `tests/test_navigation_service.py::test_move_to_entity_refreshes_the_same_reach_when_selected_target_moves` | refresh same canonical reach target; preserve high-level goal | OPEN |
| M6-F06 | interaction click/cursor miss | `tests/test_quest_understanding_patch.py::test_cursor_miss_is_not_learned_as_object_rejection` | resample hover; do not poison rejection memory | OPEN |
| M6-F07 | static obstacle | `tests/test_obstacle_perception.py` + traversal tests | evidence-only obstacle; no direct vision input | OPEN |
| M6-F08 | hard stuck | `tests/test_m0_acceptance_matrix.py` + `tests/test_stuck_resolver.py` | STOP_AND_OBSERVE then bounded recovery ladder | OPEN |
| M6-F09 | oscillation/repeat | `tests/test_m0_interrupt_resume.py::test_repeated_same_action_failure_is_engine_blocked_by_loop_guard` | suspect/confirm then bounded backoff | OPEN |
| M6-F10 | low-confidence entity | `tests/test_m0_interact_skill.py` | no interaction/input target accepted | OPEN |
| M6-F11 | temporary occlusion | `tests/test_world3d_pipeline.py` and `tests/test_perception_unknown_regression.py` | preserve UNKNOWN track history; no new identity | OPEN |
| M6-F12 | stale target position | `tests/test_navigation_service.py::test_move_to_entity_refuses_a_stale_target_position_sample` | reobserve; do not move from stale coordinates | OPEN |
| M6-F13 | quest progress absent | `tests/test_m0_interrupt_resume.py::test_combat_success_without_quest_credit_is_not_quest_success` | no credit fabricated; bounded suppression/replan | OPEN |
| M6-F14 | unexpected modal | `tests/test_supervisor.py` safety checkpoint test | release input, MANUAL, explicit external condition | OPEN |
| M6-F15 | combat preempts navigation | `tests/test_m0_interrupt_resume.py::test_combat_preemption_resumes_the_same_quest_navigation_subgoal` | same safe quest subgoal resumes/revalidates | OPEN |

`OPEN` means the offline behavior exists but still lacks required user-operated
live evidence. `OFFLINE TEST OPEN` identifies a missing deterministic case;
these are next implementation/verification work, not accepted coverage.
