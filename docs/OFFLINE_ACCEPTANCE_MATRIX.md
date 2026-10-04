# M1–M6 offline acceptance matrix

Updated: 2026-09-21

This matrix records the strongest current repository evidence for the V5
acceptance gates.  It deliberately distinguishes a passing component replay
from a complete cross-component acceptance scenario and from selected-PID live
evidence.

Status meanings:

- `OFFLINE_VERIFIED`: the complete named offline transition is asserted by a
  deterministic test through the relevant production boundary.
- `OFFLINE_PARTIAL`: required components are tested, but the complete named
  transition is not yet exercised as one scenario.
- `OFFLINE_MISSING`: no adequate repository proof currently exists.
- `LIVE_OPEN`: the gate also requires a user-operated Retail client run; an
  offline replay never closes that part.

## M1 — canonical runtime

| Gate | Offline state | Strongest evidence | Remaining proof |
|---|---|---|---|
| M1-A normal movement | `OFFLINE_VERIFIED` | `tests/test_persistent_movement_controller.py::test_reach_keeps_one_high_level_attempt_across_control_pulses`, `::test_arrival_not_first_small_progress_completes_reach` | `LIVE_OPEN` |
| M1-B static block | `OFFLINE_VERIFIED` | `tests/test_m1_runtime_acceptance.py::test_static_block_emits_candidate_then_confirmed_stuck_once`, `tests/test_m0_acceptance_matrix.py::test_m0_movement_requires_supported_stuck_evidence_before_recovery` | `LIVE_OPEN` |
| M1-C recovery escalation | `OFFLINE_VERIFIED` | `tests/test_stuck_resolver.py::test_stuck_resolver_escalates_replan_scope_without_input_commands`, `tests/test_navigation_v5_assertions.py::test_path_loop_is_the_only_typed_ladder_that_escalates_to_global_replan` | `LIVE_OPEN` |
| M1-D combat preemption/resume | `OFFLINE_VERIFIED` | `tests/test_m0_interrupt_resume.py::test_combat_preemption_resumes_the_same_quest_navigation_subgoal` | `LIVE_OPEN` |
| M1.5 Supervisor FSM contract | `OFFLINE_VERIFIED` | `tests/test_supervisor.py` covers all 12 required state contracts, evidence-backed lifecycle gates, explicit preemption ordering, bounded diagnostics and the production `tick/evaluate` path | Selected-PID death/disconnect/combat/stuck preemption timing remains `LIVE_OPEN` |
| M1.6 Skill Executor contract | `OFFLINE_VERIFIED` | `tests/test_active_skill_runtime.py` and `tests/test_skill_executor.py` cover the full lifecycle, typed SkillContext, precondition waiting, cancellation/preemption, single-active authority and every registered skill contract field | Selected-PID lifecycle/deadline/retry timing remains `LIVE_OPEN` |
| M1.7 Verification Engine contract | `OFFLINE_VERIFIED` | `tests/test_verification_engine.py`, `tests/test_action_launch.py`, `tests/test_active_skill_supervision.py`, movement/interact/combat/quest-dialog acceptance tests prove that only invoked postcondition verifiers can confirm SUCCESS | Selected-PID evidence latency/accuracy remains `LIVE_OPEN` |
| M1.8 Failure Manager contract | `OFFLINE_VERIFIED` | `tests/test_failure_manager.py`, `tests/test_goal_domain_manager.py`, `tests/test_terminal_result.py` cover normalization, per-chain budget, recovery mapping, every escalation stage, bounded storage, finite goal failure and persistent-task suppression | Selected-PID recovery effectiveness remains `LIVE_OPEN` |
| M1.9 Progress Score contract | `OFFLINE_VERIFIED` | `tests/test_navigation_progress.py` plus movement/stuck/obstacle suites cover configurable five-source fusion, missing-source renormalization, invalid signal rejection, dropout safety and temporal hysteresis | Selected-PID signal calibration remains `LIVE_OPEN` |
| M1.10 Stuck Resolver FSM | `OFFLINE_VERIFIED` | `tests/test_stuck_resolver.py`, `tests/test_recovery_planner.py`, `tests/test_navigation_terminal_processor.py`, navigation/obstacle acceptance cover all states, conditional stepping, local waypoint verification, blacklist termination and cliff safety | Selected-PID recovery effectiveness remains `LIVE_OPEN` |

M1 offline named gates: **4 verified / 4**.  This does not close M1 live
acceptance.

## M2 — combat and interaction

| Gate | Offline state | Strongest evidence | Remaining proof |
|---|---|---|---|
| M2-A normal combat | `OFFLINE_VERIFIED` | `tests/test_combat_controller_1_0.py::test_combat_lifecycle_range_health_trend_and_death`, `tests/test_combat_death_fusion.py`, `tests/test_m0_acceptance_matrix.py::test_m0_terminal_matrix_is_deterministic_across_100_replays` | `LIVE_OPEN` |
| M2-B out-of-range recovery | `OFFLINE_VERIFIED` | `tests/test_m0_combat_loot_skills.py`, `tests/test_combat_runtime_runner.py::test_combat_approach_continues_on_movement_lane`, `::test_combat_arrival_resumes_rotation_without_finalizing` | `LIVE_OPEN` |
| M2-C facing recovery | `OFFLINE_VERIFIED` | `tests/test_face_controller.py`, `tests/test_m0_combat_loot_skills.py` facing-error request, `tests/test_interaction_runtime_runner.py::test_running_verification_routes_face_request_through_navigation` | `LIVE_OPEN` |
| M2-D LOS recovery | `OFFLINE_VERIFIED` | `tests/test_los_recovery.py` covers evidence-ranked bilateral probes, finite budget, temporary danger and mmap-backed `REPOSITION_FOR_LOS`; `tests/test_m0_combat_loot_skills.py::test_los_recovery_has_two_lateral_probes_then_one_world_geometry_replan`; `tests/test_combat_runtime_runner.py::test_combat_third_los_step_starts_persistent_navigation_replan` | `LIVE_OPEN` |
| M2-E temporary target occlusion | `OFFLINE_VERIFIED` | `tests/test_v5_m2_target_occlusion_acceptance.py::test_combat_keeps_same_guid_and_track_across_occluded_then_reacquired`, plus tracker lifecycle tests | `LIVE_OPEN` |
| M2-F NPC interaction | `OFFLINE_VERIFIED` | `tests/test_m0_acceptance_matrix.py` target→interact→quest UI replay, `tests/test_interaction_runtime_runner.py` approach/arrival/result paths | `LIVE_OPEN` |

M2 offline named gates: **6 verified / 6**.

The complete M2.16 invariant gate is executable in
`tests/test_m2_assertions.py`; M2.8--M2.15 detailed recovery/evidence coverage
is in `tests/test_los_recovery.py`, `tests/test_invalid_target_recovery.py`,
`tests/test_interaction_m2_matrix.py`, and the canonical combat/loot tests.
Latest complete offline regression: **1455 passed, 3 skipped**. This does not
change any `LIVE_OPEN` row.

## M3 — quest execution

| Gate | Offline state | Strongest evidence | Remaining proof |
|---|---|---|---|
| Multi-step questline lifecycle | `OFFLINE_VERIFIED` | `tests/test_v5_m3_adaptive_quest_environment.py::test_agent_completes_adaptive_quest_and_discovers_follow_up` drives the production Planner/SkillExecutor from one high-level goal; observations are generated only in response to the selected skill. It covers accept, movement, combat, loot credit, return, a failed interaction with bounded retry, turn-in and campaign follow-up. `tests/test_v5_m3_questline_acceptance.py` separately proves attempted combat/loot cannot create objective credit | `LIVE_OPEN` |
| Quest graph/dependencies | `OFFLINE_VERIFIED` | `tests/test_quest_graph.py`, `tests/test_m1_primary_quest_runtime.py` | `LIVE_OPEN` |
| Search coverage/failure memory | `OFFLINE_VERIFIED` | `tests/test_search_coverage.py`, `tests/test_quest_failure_memory.py` | `LIVE_OPEN` |
| Accept/turn-in UI verification | `OFFLINE_VERIFIED` | `tests/test_m1_quest_dialog_skill.py`, `tests/test_m1_quest_progress_verifier.py` | `LIVE_OPEN` |

The M3 lifecycle work exposed and fixed the scoped objective-id verifier
mismatch in `src/wowbot/verification/quest.py`. The adaptive environment is
not a prerecorded macro: a wrong skill cannot advance its state. Latest full
regression before the World3D compute-backend extension: **1038 passed, 2
skipped** in 63.51 seconds. Latest complete regression after the World3D
backend, quest-domain, proposal-ranking, visual-runtime and mmap-route
extraction: **1056 passed, 2 skipped** in 52.64 seconds.

## M4 — World3D/perception/tracking

| Gate | Offline state | Strongest evidence | Remaining proof |
|---|---|---|---|
| M4-A stable TrackId | `OFFLINE_VERIFIED` | `tests/test_world3d_tracking.py::test_same_mob_keeps_track_across_relation_change`, `::test_crossing_tracks_no_id_swap` | `LIVE_OPEN` |
| M4-B occluded/reacquired | `OFFLINE_VERIFIED` | `tests/test_world3d_pipeline.py::test_temporary_occlusion_is_preserved_as_a_track_lifecycle`, `tests/test_world3d_tracking.py::test_unknown_subject_reacquires_after_short_detector_gap` | `LIVE_OPEN` |
| M4-C camera motion suppression | `OFFLINE_VERIFIED` | `tests/test_world3d_pipeline.py::test_camera_rotation_does_not_create_collision_evidence`, `::test_pipeline_preserves_camera_rotation_kind_for_traversability_fusion` | `LIVE_OPEN` |
| M4-D tooltip identity evidence | `OFFLINE_VERIFIED` | `tests/test_tooltip_observation.py` | `LIVE_OPEN` |
| M4-E obstacle updates free-space/traversability | `OFFLINE_VERIFIED` | `tests/test_world3d_pipeline.py::test_obstacle_only_changes_local_traversability_evidence_not_navigation`, `::test_temporal_traversability_requires_repeated_block_evidence_and_then_decays` | `LIVE_OPEN` |
| M4-F bounded ActivePerception | `OFFLINE_VERIFIED` | `tests/test_active_perception_fsm.py`, `tests/test_world3d_pipeline.py::test_active_perception_requests_are_read_only_and_can_emit_negative_evidence` | `LIVE_OPEN` |
| M4-G obstacle matrix OBS-A--OBS-J | `OFFLINE_VERIFIED` | `tests/test_v5_m4_obstacle_acceptance.py` executes every named V5 M4.8Z case through production fusion/progress/stuck/local-planning/danger/active-perception boundaries; cliff recovery explicitly excludes forward jump | Retail replay/calibration remains `LIVE_OPEN` |

M4 offline named gates: **7 verified / 7**.  Real-image and selected-PID live
validation remain separate gates.

## M5 — navigation

| Gate | Offline state | Strongest evidence | Remaining proof |
|---|---|---|---|
| M5-A normal destination | `OFFLINE_VERIFIED` | `tests/test_navigation_integration.py::test_engine_starts_and_arrives`, `tests/test_persistent_movement_controller.py::test_arrival_not_first_small_progress_completes_reach` | `LIVE_OPEN` |
| M5-B static obstacle local bypass | `OFFLINE_VERIFIED` | `tests/test_navigation_contracts.py::test_local_planner_consumes_confirmed_traversability_without_semantic_labels`, `tests/test_navigation_v5_assertions.py::test_one_transient_local_obstacle_does_not_force_a_global_replan` | `LIVE_OPEN` |
| M5-C repeated block, memory, alternate route | `OFFLINE_VERIFIED` | `tests/test_v5_m5_danger_route_acceptance.py::test_supported_route_failure_memory_rebuilds_an_alternate_corridor`, `tests/test_recovery_planner.py::test_path_loop_marks_danger_and_rebuilds_corridor_before_resuming` | `LIVE_OPEN` |
| M5-D hostile-region cost avoidance | `OFFLINE_VERIFIED` | `tests/test_v5_m5_danger_route_acceptance.py` proves cost-scored detour selection and sequential waypoint execution through the one NavigationService authority | `LIVE_OPEN` |
| M5-E moving NPC follow | `OFFLINE_VERIFIED` | `tests/test_follow_distance_band.py` | `LIVE_OPEN` |
| M5-F combat LOS reposition | `OFFLINE_VERIFIED` | retained-attempt LOS replay in `tests/test_m0_acceptance_matrix.py` and movement routing in `tests/test_combat_runtime_runner.py` | `LIVE_OPEN` |
| M5-G interaction usable-range approach | `OFFLINE_VERIFIED` | `tests/test_interaction_runtime_runner.py::test_successful_arrival_resumes_same_interaction_attempt`, `tests/test_agent_target_approach.py` | `LIVE_OPEN` |
| M5-H systematic search coverage | `OFFLINE_VERIFIED` | `tests/test_search_coverage.py` | `LIVE_OPEN` |
| M5-I oscillation detected and broken | `OFFLINE_VERIFIED` | `tests/test_v5_m5_oscillation_acceptance.py::test_induced_oscillation_is_evidence_gated_bounded_and_terminates_on_progress` | `LIVE_OPEN` |
| M5-J static TrinityCore navmesh corridor | `OFFLINE_VERIFIED` | `tests/test_mmap_navmesh.py` plus real Retail 12.1 map-2175 same-tile and cross-tile parsing/routing evidence in `docs/MMAP_NAVIGATION.md` | Selected-PID Exile's Reach route execution, dynamic obstacle response and arrival remain `LIVE_OPEN` |

M5 original named gates: **9 verified / 9**. The additional mmap route source
is offline verified; it does not replace any original gate or close live proof.

## M6 — integration/release

| Gate group | Offline state | Evidence | Remaining proof |
|---|---|---|---|
| Canonical action pipeline and single authorities | `OFFLINE_VERIFIED` | `tests/test_architecture_boundaries.py`, `tests/test_command_dispatch.py`, `tests/test_skill_executor.py` | `LIVE_OPEN` |
| Preemption/resume, death/loading/modal, stale-state guards | `OFFLINE_VERIFIED` | `tests/test_m0_interrupt_resume.py`, supervisor/runtime safety suites | `LIVE_OPEN` |
| Induced failure suite F01–F15 | `OFFLINE_VERIFIED` per current matrix | `docs/M6_INDUCED_FAILURE_MATRIX.md` and linked tests | Every row remains live-open |
| Replay, structured logs, performance measurements | `OFFLINE_VERIFIED` | typed `ReplayRecorder`/`ReplayPlayer`, opt-in `RuntimeReplayBridge`, replay/diagnostics/performance tests and `PerformanceMonitor` | Selected-PID file volume and long-run live evidence remain open |
| Autonomous beginning questline without fixed input script | `OFFLINE_VERIFIED` | `tests/test_v5_m3_adaptive_quest_environment.py` uses the production agent and reacts to its actual selected skills; it includes one induced interaction miss and verified bounded retry before completion | Full selected-PID live run required |
| Release gate | `OFFLINE_PARTIAL` | All named M1--M6 offline scenario rows now have direct deterministic evidence; latest full suite is **1159 passed, 3 skipped** | Cannot close before selected-PID live acceptance, long-run performance evidence, and live induced-failure rows |

## Current boundary

The named deterministic M1--M6 offline acceptance scenarios are green. This
does **not** make M6 release-ready: all selected-PID/live columns remain open,
including the autonomous questline, induced failures and long-run performance.
Those results must be recorded separately in `docs/LIVE_VALIDATION.md`.

Latest complete regression after the M2/M3 coverage closure, typed quest-chain
relations, M4 obstacle-overlay diagnostics, process-capture correctness fixes,
and the prior replay/SensorHub/error-correlation work: **1514 passed, 3
skipped** (2026-09-22). The three new tests cover dynamic-obstacle lifecycle,
temporal cliff confirmation and evidence-only water/terrain transitions. No
skipped/live gate is counted as passed.

## 2026-09-23 World3D detailed offline closure

Sections 7–8, 23–27, 47–54, 71–73 and 81–90 of the dedicated World3D design
now have direct production-code and regression evidence. This includes
ambiguity-rejecting long-gap re-identification, visual-condition confidence,
typed semantic fusion and field freshness/hysteresis, lifecycle/failure
feedback, context-profile scheduling, and a renderable deterministic replay.
The complete suite passed **1535 tests, 3 skipped in 65.44 seconds**. Detector
accuracy/calibration and World3D sections 93–94 remain `LIVE_OPEN`; this does
not claim a real client scenario succeeded.

## 2026-09-23 map-level resolver evidence

V4-018 is now `OFFLINE_VERIFIED`: real addon `parentMapID` evidence crosses
FULL/FAST transport into the canonical WorldModel, and the map policy uses the
bounded resolver with verified parent-context change. Full regression:
**1554 passed, 3 skipped in 54.45 seconds**. The corresponding selected-PID
right-click/marker/filter behavior remains `LIVE_OPEN`.

## 2026-09-23 arrival-verifier evidence

DESIGN-031 is now `OFFLINE_VERIFIED`: one canonical arrival gate fuses the
specified evidence, keeps weak evidence at `CANDIDATE`, and applies enter/exit
hysteresis. It is wired into the production REACH controller. Focused result:
**32 passed**; complete result: **1570 passed, 3 skipped in 67.47 seconds**.
Selected-PID thresholds and noisy live transitions remain open.

DESIGN-049 is also `OFFLINE_VERIFIED`: typed quest-credit outcomes now
separate quest start, ongoing progress, objective completion, stage change,
turn-in readiness and final completion. Complete regression: **1574 passed, 3
skipped in 83.49 seconds**. Live event-order validation remains open.
