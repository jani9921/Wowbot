# V5 M1--M6 audit

Status date: 2026-09-20. This is an audit baseline, not a declaration that
M1--M6 are complete or live-validated.

## M2.8 LOS recovery checkpoint (2026-09-22)

- LOS recovery is now distinct from range recovery. `LosRecoveryPlanner`
  samples current `WORLD3D_TRAVERSABILITY_V5` side sectors and target bearing,
  selects one bounded lateral probe, then the opposite side; it never uses a
  fixed left-first rule and never advances blindly into the occluder.
- The third and final recovery step requires fresh, exact-GUID,
  same-instance world geometry. `NavigationService` creates a typed
  `REPOSITION_FOR_LOS` request, allowing `GlobalPlanner` to use the configured
  Trinity mmap route while the existing persistent movement controller stays
  the sole movement authority. Screen pixels are never projected into guessed
  world coordinates.
- `STRAFELEFT/STRAFERIGHT` are admitted only through the selected-PID
  movement lane and its watchdog-controlled lease. They are primary lateral
  translation, not ordinary action commands; focus loss, cancellation,
  explicit stop or a missed refresh releases them. A production-executor
  regression prevents fake-executor tests from hiding this authority contract.
- The budget is finite at three attempts. Missing replan geometry fails
  closed; exhausted recovery applies a temporary `LOS_OBSTACLE` DangerMap
  entry and reachability penalty through terminal bookkeeping, then returns a
  retryable typed `LINE_OF_SIGHT` failure to the planner.
- Focused LOS/combat/navigation/authority regression passed **68 tests**;
  complete offline regression passed **1433 tests, 3 skipped in 42.87
  seconds**. Selected-PID LOS recovery and mmap corridor execution remain
  `LIVE_OPEN`.

## M2.9 invalid-target recovery checkpoint (2026-09-22)

- `InvalidTargetRecoveryPolicy` checks the committed track/entity evidence:
  exact live GUID, alive state, hostility, targetability, quest relevance,
  lifecycle and a fresh confirmed screen anchor. Detection alone cannot become
  a selectable identity.
- The same active COMBAT attempt may reacquire only its original GUID, at most
  twice. If the explicitly selected bindings cache contains `CLEARTARGET`, the
  wrong selection is cleared before the verified anchor click; no binding is
  guessed when it is absent.
- A different local hostile may be returned only as a quest-relevant advisory
  `suggested_alternate_guid` on a retryable terminal result. The running skill
  never silently changes its committed target; Planner remains the selection
  authority for a later attempt.
- Focused target/combat regression passed **36 tests**; complete offline
  regression passed **1438 tests, 3 skipped in 36.62 seconds**. Selected-PID
  reacquisition remains `LIVE_OPEN`.

## M2.10 kill verification and M2.11 interaction FSM checkpoint (2026-09-22)

- `CombatVerifier` retains the required source-aware death fusion: deterministic
  same-GUID death events confirm directly; target-dead, HP-zero, corpse,
  objective-credit and combat-end evidence use deduplicated noisy-OR. Combat
  ending alone remains 0.25 support and cannot confirm a kill; duplicate rows
  from the same source do not inflate confidence.
- `InteractSkill` now exposes the exact canonical lifecycle: `IDLE`,
  `RESOLVE_TARGET`, `APPROACH`, `FACE`, `HOVER`, `VERIFY_HOVER`, `INTERACT`,
  `WAIT_RESULT`, `CLASSIFY_RESULT`, `RECOVER`, `SUCCESS`, `FAILED`. Existing
  exact-identity, bounded hover sampling, canonical approach, shared facing
  recovery and observable-result verification remain intact.
- Focused interaction/death/target regression passed **31 tests**; complete
  offline regression passed **1441 tests, 3 skipped in 38.64 seconds**.
  Selected-PID interaction state transitions and kill evidence remain
  `LIVE_OPEN`.

## M2.12--M2.14 hover, result and failure-matrix checkpoint (2026-09-22)

- Hover inspection ranks a learned stable point, object-specific point,
  NPC/creature upper torso derived from the bbox, center and bounded side
  samples. At most four unique points are attempted. Mouseover acceptance
  requires the exact GUID, sufficient identity confidence, a fresh sample and
  no contradictory visual-track identity.
- `InteractionResultClassifier` reports all nine observable effect outputs:
  gossip, quest detail/progress/complete, merchant, loot, object activation,
  target change, nothing and unknown. UI state, addon events and object
  disappearance/state change are evidence; a click is never success.
- `InteractionRecoveryPolicy` contains the explicit finite matrix. Approach,
  face and LOS reposition are capped at two; exact-target reacquisition at two;
  direct/UI-not-ready retry at three with a 250 ms bounded wait; UNKNOWN gets
  one observation before escalation. LOS uses the shared NavigationService
  movement lane, not interaction-owned movement.
- Focused interaction/authority regression passed **68 tests**; complete
  offline regression passed **1448 tests, 3 skipped in 38.47 seconds**.
  Selected-PID hover timing and recovery accuracy remain `LIVE_OPEN`.

## M2.15--M2.16 loot and assertion checkpoint (2026-09-22)

- Loot verification fuses correlated loot receipt, inventory gain, loot UI,
  corpse `lootable` transition and corpse interaction-state transition using
  independent-source noisy-OR evidence. Explicit expected item IDs still
  require the relevant item event/inventory delta; a right click or loot UI
  alone cannot increment progress or return success.
- `test_m2_assertions.py` is the executable M2 invariant gate: no cast without
  the intended target, no kill below the evidence threshold, finite range and
  LOS budgets, no click-only interaction success, intended-track preserving
  reacquisition, and no direct combat input/movement authority outside the
  shared execution/navigation boundaries.
- Focused M2 assertion/loot/interaction/architecture regression passed **58
  tests**; complete offline regression passed **1455 tests, 3 skipped in
  42.60 seconds**. M2 is offline-complete at this checkpoint; all selected-PID
  acceptance rows remain `LIVE_OPEN` and are not claimed as live validation.

## M1.10 Stuck Resolver FSM checkpoint (2026-09-21)

- All 15 required states exist in the canonical resolver.
- Duplicate observations/results cannot skip ladder steps; each emitted step
  is followed by an explicit VERIFY_RECOVERY transition.
- NEW_LOCAL_WAYPOINT is a verified normal MOVE built from validated navigation
  geometry. BLACKLIST_TEMP creates bounded danger memory and exhausts the
  ladder instead of stalling. Cliff recovery excludes forward jump.
- Focused regression passed **33 tests**; complete regression passed **1159
  tests, 3 skipped in 34.41 seconds**. Live proof remains open.

## M1.9 Progress Score checkpoint (2026-09-21)

- The exact five canonical evidence sources and suggested weights are the
  validated defaults; custom non-negative canonical weights are supported.
- Only available finite normalized components contribute, with automatic
  weight renormalization and no fake fallback value.
- Possible stuck, hard stuck and recovered use the specified thresholds,
  durations and hysteresis. Sensor dropout becomes UNAVAILABLE and restarts
  the temporal proof window.
- Focused regression passed **42 tests**; complete regression passed **1154
  tests, 3 skipped in 31.83 seconds**. Live calibration remains open.

## M1.8 Failure Manager checkpoint (2026-09-21)

- Failure values are normalized and mapped to typed domain recoveries.
- Retry state is per correlation chain, bounded in memory, and progresses
  through the complete finite V5 escalation ladder.
- Replan stages reset the current autonomy plan; GoalManager applies domain
  recovery, alternative-task suppression and finite goal failure. Persistent
  goals suppress exhausted tasks instead of looping the same correlation.
- Focused regression passed **54 tests**; complete regression passed **1151
  tests, 3 skipped in 38.61 seconds**. Live recovery proof remains open.

## M1.7 Verification Engine checkpoint (2026-09-21)

- A skill/start routine can no longer self-report terminal success: bare
  SUCCESS is retained as pending until a postcondition verifier runs.
- Generic registry, movement, visual and typed M0/domain terminal paths all
  pass the same confirmation boundary, which emits verifier identity and
  evidence diagnostics.
- MOVE, INTERACT, combat/KILL and quest ACCEPT/dialog outcomes retain their
  domain-specific evidence checks; local dispatch acknowledgement is not
  world success.
- Focused acceptance passed **37 tests**; complete regression passed **1147
  tests, 3 skipped in 39.73 seconds**. Live accuracy remains open.

## M1.6 Skill Executor checkpoint (2026-09-21)

- The canonical `ActiveSkillRuntime` now records the entire required V5 skill
  lifecycle without replacing its domain phase or creating another owner.
- `SkillContext` is typed and contains all eight specified fields, including
  snapshot version and a cancellation token that is closed on preemption.
- All registered contracts expose preconditions, expected postconditions,
  timeout, retry budget, recovery policy and verification method.
- Focused agent/runtime regression passed **137 tests**; complete regression
  passed **1145 tests, 3 skipped in 46.82 seconds**. Live timing remains open.

## M1.5 Supervisor FSM checkpoint (2026-09-21)

- Every required Supervisor state now has immutable priority,
  interruptibility, timeout and retry metadata plus evidence-backed entry and
  exit predicates.
- The production Supervisor exposes one lifecycle (`can_enter/enter/tick` and
  `can_exit/exit`) and an explicit death > disconnect > critical > combat >
  normal-domain preemption contract, including navigation-only stuck
  preemption.
- The contract remains a pure gate: it has no input backend, movement control,
  planning or WorldModel mutation path. Agent remains the only cancellation,
  key-release and terminal authority.
- Focused Supervisor/architecture regression passed **39 tests**. Complete
  offline regression passed **1141 tests, 3 skipped in 38.43 seconds**. Live
  selected-PID preemption/recovery evidence remains open.

## Goal completion authority checkpoint (2026-09-21)

- Explicit high-level completion conditions now belong to `GoalManager`, not
  the `AutonomousAgent` orchestration body. Duration, verified bag capacity and
  same-map MOVE arrival are the only generic terminal conditions handled by
  this boundary.
- Attempt count, completed-step count and projected progress cannot complete a
  quest goal. Quest completion remains owned by its evidence-backed domain
  lifecycle.
- Focused goal/engine/runtime/architecture regression: **157 passed**. Complete
  offline regression: **1085 passed, 2 skipped in 45.23 seconds**. This is an
  authority and offline-proof increment; selected-PID live gates remain open.

## Skill-launch and M4.8Z acceptance checkpoint (2026-09-21)

- Attempt creation plus lifecycle installation now has one explicit,
  non-dispatching boundary: `SkillExecutor.install_attempt`. It installs into
  the supplied canonical `ActiveSkillRuntime`, cannot own a parallel running
  skill, cannot send input and cannot finalize a terminal result. Agent remains
  the only dispatcher/finalizer. Focused regression: **154 passed**.
- The complete V5 OBS-A through OBS-J obstacle acceptance matrix is executable
  in `tests/test_v5_m4_obstacle_acceptance.py`. The scenarios cover clear
  progress, static and semantic-UNKNOWN collision, rotation suppression,
  temporary dynamic blockage, cliff safety, narrow doorway retention,
  false-positive decay, repeated-region route prior and bounded active
  perception.
- Cliff evidence is now a typed `DROP_OR_CLIFF` stuck class with a recovery
  ladder that excludes `JUMP_FORWARD`. Focused obstacle/navigation regression:
  **44 passed**. Complete suite: **1097 passed, 2 skipped in 44.99 seconds**.
  These are offline acceptance artifacts; selected-PID/live proof remains open.

## Planning and terminal-bookkeeping extraction checkpoint (2026-09-21)

- `PlanningOrchestrator.resolve` now composes proposal navigation adaptation,
  bounded recovery arbitration and plan revision behind the existing single
  input-free planning authority. It does not ingest WorldModel state, dispatch
  input or own movement. Focused regression: **159 passed**.
- Planner compatibility effects at the beginning of terminal processing now
  live in `ExecutionBookkeeper.record_terminal`: completed visual-search
  fallback state, failed/reached quest locations, interacted GUID context and
  supported-stuck reach retention. It returns retained resume data but cannot
  finish the active skill or write WorldModel state. Focused regression:
  **167 passed**.
- Complete offline regression: **1101 passed, 2 skipped in 38.37 seconds**.
  Remaining terminal outcome projection and selected-PID acceptance stay open.

## Verified-outcome bookkeeping checkpoint (2026-09-21)

- `AttemptOutcomeBookkeeper` now applies only already-verified compatibility
  effects: goal step/failure counters, exact failure-chain clearing, bounded
  planner backoff, loot cooldown/corpse memory and interaction-range evidence.
  It cannot verify an action, dispatch input, choose recovery or finalize the
  canonical active skill.
- `_finish` is now **83 lines** and the complete engine is **1206 lines**. The
  focused terminal/core/architecture regression passed **159 tests**; the full
  offline suite passed **1106 tests, 2 skipped in 41.79 seconds**.
- This closes another physical terminal-result extraction boundary, not any
  selected-PID live gate.

## Source precedence

1. `wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt`
2. `wow_agent_FINAL_M0_M1_master_prompt_v4.txt`
3. `wow_agent_complete_functional_design_spec.txt`

## Active component map

| Component | Current authority | Writes canonical state | Sends physical input | Migration decision |
| --- | --- | ---: | ---: | --- |
| Observation/event transport | `agent/runtime.py`, `agent/events.py` | through `WorldModel.ingest` | No | Keep; continue separating orchestration from policy. |
| Canonical belief state | `agent/world.py:WorldModel` | Yes | No | Adapt: reducers/snapshot construction still need extraction. |
| Read model | `agent/world_query.py:WorldQuery` | No | No | Active canonical read boundary. The retired in-file duplicate has been physically removed. |
| Planner | `agent/planner.py` composed with input-free domain policies | No | No | Adapt: resource/inventory/dungeon/PvP, quest, target/combat and recovery proposal policies are physically separated; the single Planner still composes and ranks all proposals. |
| Skill lifecycle | `agent/runtime/active_skill.py`, `runtime/m0_dispatch.py` | runtime attempt only | Via executor request | Keep/extend; one active-skill authority is required. |
| Navigation | `navigation/service.py` and `agent/movement_controller.py` | navigation/attempt evidence | Via executor only | Keep/extend; no domain-specific movement owner allowed. |
| World3D | `vision/world3d/pipeline.py` | No | No | Extend: V5 temporal traversability fusion is evidence-only. |
| Input boundary | `agent/executor.py`, `agent/windows_input.py` | No | Yes | Keep. `windows_input.py` is the sole backend-specific SendInput boundary. |

## Direct-input audit

The production source search found Windows input API use in
`agent/windows_input.py`; this is the designated backend. The remaining
Win32 occurrences are capture/window plumbing in `adapters/pixel_bridge.py`.
No planner, World3D pipeline, WorldModel, or domain module may import that
backend.

## Placeholder audit

`pass` occurrences remain in exception/optional-backend handling and are not
accepted as proof of an implemented capability. Critical execution paths must
be reviewed individually before their M1--M6 gate can be marked complete.

## Current M4.8 obstacle increment

- `vision/world3d/traversability.py` owns temporal sector belief only.
- First-frame obstruction is `SUSPECTED`, never hard-blocked.
- Repeated evidence may become `CONFIRMED/BLOCKED`; clean observation decays it.
- Camera rotation cannot create forward collision evidence.
- `AgentNavigator` consumes a confirmed frontal sector only after independently
  observed repeated no-progress movement; it cannot generate input itself.

## M1 canonical WorldModel reducer increment (2026-09-20)

- Raw addon events now enter canonical state only through
  `agent/world_event_reducer.py:WorldEventReducer`; target/mouseover entity
  state, location, relation and appearance updates enter only through
  `agent/world_entity_reducer.py:WorldEntityReducer`; source-attributable UI
  transition events are emitted only by `agent/world_ui_reducer.py:WorldUiReducer`.
  All reducers mutate the supplied `WorldModel`; none owns an alternate cache,
  planner or input dependency.
- `WorldModel.ingest` remains the sole ordering/session/freshness entry point
  and the sole model writer exposed to runtime callers. This is a bounded
  physical responsibility extraction, not a claim that all WorldModel
  reducer/evidence responsibilities are finished.
- Focused world/entity/runtime/navigation regression: **115 passed**. Complete
  offline regression after this extraction: **951 passed, 2 skipped** in 37.09
  seconds.
- `tests/test_architecture_boundaries.py` now guards the M1/M5 boundary:
  Planner/World/Perception/navigation planning modules cannot import the
  Windows input backend, and the extracted reducers cannot import an executor
  or planner. Focused architecture/runtime/navigation regression: **110
  passed**. Complete offline regression after the boundary guards: **956
  passed, 2 skipped** in 35.90 seconds.

## M4.1 frame-source contract increment (2026-09-20)

- The canonical World3D source now carries a required capture `frame_id`,
  monotonic observation timestamp and `client_id` all the way from frame-lane
  submission through the published `World3DObservationBatch` and its replay
  payload. A worker result cannot be attributed to the screen image present
  when it happens to finish.
- The one-in-flight World3D lane deliberately drops superseded captures rather
  than queueing stale vision; that loss is preserved as a structured
  `FRAME_DROPPED` event on the next source batch, with its count, client,
  frame reference and monotonic timestamp. Late/out-of-order pipeline results
  are rejected before they can refresh temporal evidence.
- Batch validation now rejects missing/empty source identities, invalid time,
  malformed frame events or source-mismatched drop evidence. This remains
  perception-only: it neither selects input nor changes movement ownership.
- Focused frame-source/World3D regression: **18 passed**. Full offline suite:
  **929 passed, 2 skipped** in 116.96 seconds. This is offline evidence only;
  M4's OBS live/replay acceptance matrix remains open.

## M4.2--M4.7 perception-contract increment (2026-09-20)

- A `World3DObservationBatch` now separates the *current-frame* detection
  list from temporal tracks. Every detection has a unique ID, source frame,
  screen-pixel bbox, confidence and the complete V5 class distribution. Raw
  CV publishes `UNKNOWN=1.0` rather than pretending a visual cue is an
  NPC/hostile/player fact.
- The source-local tracker exposes its V5 temporal state independently from
  compatibility lifecycle names: `TENTATIVE`, `CONFIRMED`, `OCCLUDED` or
  `LOST`. Its structured association evidence records generic-family
  compatibility, bbox overlap, feature similarity, camera-compensated motion,
  global screen-space association and temporal consistency; it remains
  non-factual.
- Raw detector geometry remains traceable. A separate EMA temporal view now
  smooths center, relative scale, velocity, bearing and distance trend. The
  distance output is explicitly `RELATIVE_SCREEN_SCALE` with no invented
  meter value; bearing is normalized to the V5 `[-1,+1]` screen-relative
  contract. Camera, player movement, entity residual and optical-flow evidence
  all carry source/confidence fields.
- Focused World3D/tracker/approach regression: **72 passed**. Full offline
  regression after this increment: **931 passed, 2 skipped** in 64.74 seconds.
  Live OBS validation remains open.

## M4.12 tooltip-observation increment (2026-09-20)

- Addon mouseover tooltip data is now normalized into a frame-stamped
  `TooltipObservation`: visibility, text, parsed name/type/relation,
  confidence, hover screen point and source are retained as separate evidence.
- A World3D link is emitted only when the current hover point is spatially
  close to an UNKNOWN subject; it is labelled `SPATIAL_HYPOTHESIS`, not an
  identity or role fact. Distant visual candidates cannot inherit the tooltip.
- Focused tooltip/runtime/approach regression: **80 passed**. The subsequent
  complete offline M4 suite passed **940 passed, 2 skipped** in 42.67 seconds;
  this has no input or movement authority and does not satisfy live evidence.

## M4.13--M4.14 active/UI contract increment (2026-09-20)

- `ActivePerception` now contains a bounded, single-owner probe FSM with the
  required states and a retained transition history. It accepts a requested
  probe, selects an allowed observation action, waits for a fresh result and
  explicitly evaluates positive or negative information gain. Combat or a
  higher-priority preemption terminates the probe; the class has no executor
  import, action lease or input method.
- Retail addon UI telemetry is normalized into individual frame-stamped UI
  observations for player/target/cast, quest/gossip/merchant/loot, tracker,
  error and loading state. Existing raw UI fields remain intact; the added
  `UI_STATE` projection is separate evidence rather than an implied action.
- Focused active-perception/UI/runtime/World3D regression: **90 passed**.
  The subsequent complete offline M4 suite passed **940 passed, 2 skipped** in
  42.67 seconds; all M4 live/replay acceptance cases remain open.

## M4.10--M4.11 map-surface state increment (2026-09-20)

- Minimap heading is now preserved as separate, confidence-labelled player
  orientation evidence; it is not inferred from a rim ornament or used to
  classify any marker. Marker locations remain player-relative local values.
- World Map telemetry now emits an independent frame-stamped state projection
  for open/map/zone/zoom/pan/player marker/objective region and map mouseover.
  The cursor remains `UNKNOWN`; normalized addon-map coordinates and existing
  calibration services are used instead of fixed screen pixels.
- Focused map/minimap/runtime/tooltip/active-perception/World3D regression:
  **73 passed**. The subsequent complete offline M4 suite passed **940 passed,
  2 skipped** in 42.67 seconds; M4 live evidence remains open.

## M4.15--M4.17 audit checkpoint (2026-09-20)

- The existing WorldModel evidence reducer already keeps correlation and
  independence groups, retaining only the strongest evidence per correlated
  group before fusion. The World3D/tooltip additions preserve those provenance
  fields rather than bypassing the reducer.
- The existing local dataset collector is retained as an addon-confirmed,
  bounded auto-label/hard-example pipeline. No trained model is claimed or
  promoted; labels remain explicitly `AUTO_LABELED` or unresolved hard cases.
- Direct sensor-hierarchy, dataset and World3D V3/V4 regression: **25
  passed**. M4's assertion and live OBS matrix remain open until the combined
  full suite and real-client records are collected.

### M4.8 evidence-fusion hardening (2026-09-18)

- Traversability fusion now applies all configured M4.8K channels separately:
  boundary, free-space violation, depth discontinuity, ego-motion mismatch and
  motion-conditioned collision. Unavailable channels are omitted and remaining
  configured weights are renormalized; no semantic obstacle class is required.
- The local output now includes danger/drop confidence and emits bounded
  `TRAVERSABILITY_UPDATED`, collision/mismatch and cliff-suspected evidence
  events. A high-confidence drop is `DANGEROUS`, distinct from an ordinary
  static `BLOCKED` sector.
- Focused World3D/navigation/stuck regression: **19 passed**. This is offline
  evidence only; OBS-A through OBS-J live/replay matrix remains open. Complete
  offline regression after the M3/M4 changes: **926 passed, 2 skipped** in
  50.10 seconds. The later M4.1 full-suite result above supersedes this suite
  count while preserving the narrower traversability checkpoint evidence.

## Current M5 danger and reachability increment

- `navigation/danger.py` owns expiring, confidence-weighted local danger
  entries. It creates hostile aggro cost only from explicit attackable telemetry
  with coordinates and permits the explicitly intended hostile entity.
- `navigation/reachability.py` tracks an entity approach confidence and only
  applies a short cooldown after repeated typed failures. A verified success
  clears the record.
- `NavigationService` composes both read-only decision components. They never
  produce commands; the existing movement controller remains exclusive input
  authority. Targeted navigation/engine regression: **122 passed**.

## M5.1--M5.4 layered-navigation checkpoint (2026-09-20)

- `navigation/contracts.py` defines immutable `NavigationRequest`,
  `GlobalRoute`, `PathCorridor` and `LocalMotionPlan` contracts. They carry no
  input object or executor reference.
- `navigation/global_planner.py`, `navigation/corridor.py` and
  `navigation/local_planner.py` are distinct planning components. Global
  replan is bounded to destination/corridor/map/danger/repeated-local-failure
  events; it is not called as a control-tick decision.
- The local planner consumes temporal World3D traversability as cost/evidence
  only, with no semantic obstacle label. It refuses to invent an off-corridor
  world coordinate from screen-relative sectors; an unsupported bypass becomes
  a local-replan request. `NavigationService` remains the sole component that
  can pass a destination to the existing `ReachMovementController`.
- The canonical `MOVE`, `REACH_LOCATION`, `REACH_OBJECT` and `FOLLOW` skill
  starts now enter that typed boundary once. The plan is refreshed by the
  `NavigationService`, never by a new per-tick planner or input owner.
- Progress now separately retains direction consistency, alternating-command
  oscillation and stuck probability. Those are diagnostic evidence rather
  than fake displacement, so a correctly-facing character against a wall can
  still become stuck only through the original temporal multi-source gate.
- A typed stuck classifier is invoked only after hard-stuck confirmation and
  chooses a bounded recovery ladder for static/dynamic blockage, oscillation,
  wrong heading or path loops. It does not send recovery input itself.
- Focused navigation contract/service/progress/engine/core regression:
  **131 passed**. Complete offline regression: **951 passed, 2 skipped** in
  31.46 seconds. This is an offline partial M5 checkpoint; calibrated
  corridor-to-controller bypass and live M5 acceptance remain open.

## Current M5 follow increment

- FOLLOW now retains one reach attempt while refreshing the group leader's
  current telemetry position. It holds inside a configured distance band and
  refuses stale or identity-mismatched leader data instead of chasing a
  remembered point.
- The same `ReachMovementController` remains the only movement owner; FOLLOW
  adds no parallel input loop. Targeted regression: **105 passed**.

## Current M3/M5 search-coverage increment

- `navigation/search_coverage.py` owns bounded, deterministic search cells,
  visit counts and target-detection completion. It only yields a waypoint.
- The engine converts a quest `SEARCH_AREA` visual-search hand-off into the
  next canonical MOVE cell first; the existing `SEEK_VISUAL_CUE` remains the
  post-coverage perception skill. No search component can send input.
- Targeted search/agent regression: **111 passed**.

## M3 quest-graph extraction (2026-09-18)

- `agent/quest_graph.py:QuestGraph` now owns dependency edges, conditional
  blockers, objective readiness and the read-only graph projection.
- `QuestModel` remains the normalized quest-record writer and delegates those
  projections to the graph service. The graph cannot mutate records, choose a
  skill, update failure memory, plan a route or send input.
- Focused quest/agent regression: **115 passed**. This is a modularity and
  offline correctness checkpoint only; M3 quest-line live acceptance is open.

## M3 quest-lifecycle increment (2026-09-18)

- `agent/quest_state.py` defines the canonical lifecycle distinction between
  availability, acceptance, active execution, objectives-complete, ready to
  turn in, turning in, completed, retryable failure and terminal failure.
- `QuestRecord` retains this evidence-derived lifecycle alongside its legacy
  activity projection, confidence, giver/turn-in/reward beliefs and update
  provenance. Thus all-complete objectives do not silently equal a turn-in.
- `QuestExecutionRuntime` and the planner consume the completion-surface
  lifecycle and route a verified local turn-in target to the shared `TALK` /
  interaction chain instead of a quest-specific click path. Focused
  quest/runtime/planner regression: **119 passed**.

## M3 objective-lifecycle increment (2026-09-18)

- Normalized objectives now retain their own explicit lifecycle:
  `PENDING`, `ACTIVE`, `BLOCKED`, `COMPLETE`, `FAILED_RETRYABLE` or
  `FAILED_TERMINAL`, plus the stable `(quest_id, objective_id)` failure-memory
  key. The existing count/completion projection is preserved for compatibility.
- Objective state accepts explicit addon state/failure facts and never derives
  progress from an attempted skill. Dependency readiness remains a read-only
  `QuestGraph` computation rather than an objective-side mutation.
- Focused quest/runtime/planner regression: **120 passed**. This is offline
  evidence only; M3's full live multi-step questline remains open.

## Current M6 structured-observability increment

- `runtime/structured_logger.py` provides a bounded common event format with
  timestamp, level, module, event type, correlation ID, entity ID and payload.
- The canonical engine record path feeds it, so action intents, terminal
  verifications, failures and supervisor/runtime events are queryable without
  creating a second action path. Targeted M6 regression: **136 passed**.

## M6.11 performance-observability increment (2026-09-20)

- `runtime/performance.py:PerformanceMonitor` retains bounded latency windows
  with latest/average/p50/p95, capture-rate samples and event-queue depth. It
  is read-only and cannot schedule input or recovery.
- `AutonomousAgent.tick` is measured by a transparent decorator, so every
  normal and early-return runtime tick contributes a `supervisor_tick` timing
  and current EventBus queue depth. `AgentStatusProjection` exposes this
  diagnostic projection.
- The actual runtime producers now report capture-poll latency and measured
  sensor poll rate, perception, World3D detector/tracker, observation-build,
  agent-tick and input-dispatch latency. No addon receive-rate proxy is
  presented as capture FPS. Focused runtime/executor regression: **133
  passed**. Complete offline regression after producer integration: **957
  passed, 2 skipped** in 38.24 seconds.

## M1 planner/runtime extraction checkpoint (2026-09-20)

- Quest-dialog proposal selection now lives in
  `agent/quest_dialog_planning.py`; quest offer ambiguity, reward selection and
  exact addon-confirmed quest button proposals are no longer implemented in
  the monolithic planner body.
- Fresh addon mouseover-to-target handoff now lives in
  `agent/target_planning.py`. It retains the exact cursor/telemetry freshness,
  player exclusion, combat protection and structured quest relevance gates,
  while owning no target state and sending no input.
- `agent/observation_ingestion.py` now owns creation, durable/ephemeral
  classification and atomic primary+supplemental ingestion. Session-change
  cancellation remains Agent/Supervisor orchestration and happens before the
  new sample is ingested.
- Focused quest-dialog regression: **115 passed**; focused target-policy
  regression: **148 passed**; focused ingestion/runtime/architecture
  regression: **139 passed**.
- Quest localisation now lives in `agent/quest_location_planning.py`: explicit
  turn-in locations, objective/search areas, addon quest locations and
  runtime-validated learned locations are resolved there. TDB references are
  still excluded from learned-location proposals and remain fallback-only.
- `agent/world_evidence_reducer.py` now owns non-addon perception projection,
  UNKNOWN visual-track evidence, visual relations, belief lifecycle and the
  deferred prediction queue, always mutating the supplied canonical model.
  Focused localisation regression: **132 passed**; focused evidence/world
  regression: **134 passed**.
- Complete offline regression after these extractions: **959 passed, 2
  skipped** in 44.32 seconds. These are structural and offline results, not
  live acceptance evidence.
- `execution/command_dispatch.py` is now the sole engine-facing command-lane
  router. Every command batch leaving `AutonomousAgent` is delegated exactly
  once to the existing authoritative `InputExecutor`, either through its
  discrete lane or its persistent movement lane. The router has no binding,
  PID, focus, Win32, planner, WorldModel or skill-lifecycle responsibility.
  Focused dispatch/executor/runtime/movement regression: **157 passed**;
  complete offline regression: **963 passed, 2 skipped** in 34.10 seconds.
- `agent/terminal_result.py` now creates the normalized failure/budget/loop
  assessment, immutable verification record and typed terminal `SkillResult`.
  The Agent remains the sole component that calls `ActiveSkillRuntime.finish`.
- `agent/quest_terminal.py` separately applies observed quest credit,
  quest-failure/success memory and the explicit combat-success-is-not-credit
  rule. `agent/inspection_terminal.py` separately evaluates hover quality,
  valid zero-information rejection evidence and sensor calibration; neither
  module selects or dispatches a follow-up action.
- Focused terminal/lifecycle regression: **107 passed**; focused quest
  terminal regression: **110 passed**; focused inspection/sensor regression:
  **137 passed**. Complete offline regression after these extractions: **966
  passed, 2 skipped** in 24.92 seconds.
- `agent/navigation_terminal.py` now reports verified entity, movement,
  obstacle and recovery outcomes exclusively through the existing
  `NavigationService`; it creates no second controller. Prediction errors are
  produced by the same canonical terminal assessment as verification.
- `agent/memory_terminal.py` now owns procedural timing, learned procedure,
  resource-site and inspection-learning persistence. It composes the
  inspection processor and cannot select or dispatch another action.
- Focused navigation-terminal regression: **117 passed**; focused
  memory-terminal regression: **135 passed**. Complete offline regression:
  **966 passed, 2 skipped** in 23.09 seconds. The engine terminal method has
  fallen from 342 to **155 lines**; engine source is now **1936 lines**.
- `skills/movement.py:MovementSkillRunner` now owns one input-free observation
  step of an already-active movement skill: it asks the sole
  `NavigationService` for assessment/commands and returns them to Agent
  orchestration. It cannot dispatch, finalize, or maintain a second movement
  state. Focused movement/navigation regression: **123 passed**; complete
  offline regression: **969 passed, 2 skipped** in 28.68 seconds.
- `skills/interaction_runtime.py:InteractionRuntimeRunner` now owns the
  world-coordinate approach step inside the same active INTERACT attempt. It
  composes NavigationService arrival with `InteractSkill.resume_after_approach`
  but cannot dispatch or finalize. Focused interaction/approach regression:
  **143 passed**; complete offline regression: **973 passed, 2 skipped** in
  28.91 seconds. The engine is now **1916 lines**; its tick remains oversized
  at 1311 lines and is not declared complete.
- The same Interaction runtime now owns visual approach continuation and both
  world-coordinate/visual approach startup contracts. It preserves typed
  resume failures, returns the required dispatch lane explicitly, and still
  cannot dispatch/finalize. Focused regression: **148 passed**; complete
  offline regression: **977 passed, 2 skipped** in 23.80 seconds. Engine source
  is **1857 lines** and its tick body is **1251 lines**; combat/loot and the
  remaining interaction face/retry path are still open.

## Current M6 entity/recovery/replay increment (2026-09-18)

- `runtime/entity_identity.py` establishes `WorldEntityId` as the only
  actionable cross-domain entity reference: it is a normalized, live addon
  GUID. NPC template IDs, names, visual tracks and map markers remain
  evidence, never a replacement input target. Active-skill startup,
  target-selection and navigation entry points share this boundary.
- Supervisor interruption replay covers a quest `MOVE` subgoal being
  preempted by combat and resuming that same quest/objective target after
  combat ends. A resumed intent must pass the current normal skill contract;
  it is never resumed solely because it was previously running.
- Death, loading, connection-loss and blocking-modal paths create an explicit
  `recovery` checkpoint in supervisor diagnostics. The engine releases input,
  preserves the high-level goal, changes to `MANUAL`, and reports the external
  stabilisation condition. It does not attempt an unverified revive or modal
  click. A user-armed, fresh safe observation clears the checkpoint and
  requires normal replanning.
- `agent.runtime.replay()` now writes `replay_package.json` alongside the
  existing result: source checksum, config snapshot, session metadata, world
  state deltas, decision/plan/action/verification trace, command log and
  terminal failures. It always uses `RecordingExecutor`; raster frame refs are
  explicitly empty for telemetry-only JSONL replays.
- Offline targeted regression for this increment: **46 passed**. This is
  still not an M6 live questline, induced-failure suite, or release-gate
  completion claim.

## Current M6 watchdog-observability increment (2026-09-18)

- EventBus diagnostics now expose its last publish/consume activity; a quiet
  empty bus is not considered a fault, while a nonempty bus that stops
  draining is explicit `event_bus_stalled` evidence.
- `HealthMonitor` separately reports stale observations, stalled event
  delivery, an overdue supervisor tick for an active skill, isolated
  subscriber errors, and an unhealthy input movement watchdog. It is
  read-only: the existing engine safety boundary retains all stop/mode
  authority.
- Targeted watchdog/runtime regression: **138 passed**. Full offline
  regression after the M6 increments: **896 passed, 2 skipped** in 42.19s.
  Neither result is a substitute for the M6 live acceptance scenario.

## M6.15--M6.17 static audit checkpoint (2026-09-18)

- The critical-path scan found no production `success = true`, quest/mob/item
  completion counter, or equivalent direct mutation that bypasses a
  verification result. `WAIT` has an intentionally successful internal cycle
  outcome only; it does not increment quest progress, loot, combat or goal
  completion. Those changes remain gated by their respective verifier and
  observed postcondition.
- The direct-input scan found physical key/mouse/wheel calls only in
  `agent/executor.py` and its designated `agent/windows_input.py` backend.
  Planner, domain, WorldModel, navigation and perception modules have no
  backend input call. This is a static audit result, not a proof of live
  behavior.
- Placeholder/duplication review remains open: the remaining monolithic
  engine/planner extraction and every live M6 release-gate scenario still
  require evidence before M6 can be marked complete.

## Runtime status-projection extraction (2026-09-18)

- `agent/status_projection.py` now owns complete diagnostic/status assembly.
  It is a read-only projection and leaves input, planning and WorldModel
  mutation authorities untouched.
- Focused engine/runtime/debug regression: **141 passed**. The rest of
`AutonomousAgent.tick` remains an explicit migration target, not an implied
completion of the runtime split.

## World snapshot-projection extraction (2026-09-18)

- `agent/world_snapshot.py` now owns both immutable planner-snapshot assembly
  and bounded diagnostic-snapshot assembly. It accepts `WorldModel` only as a
  read source; it cannot ingest observations, mutate evidence, select a
  proposal, or dispatch input.
- `WorldModel` remains the sole reducer/writer and delegates its two public
  projection methods to this module. Focused world/core/runtime regression:
  **128 passed**; complete offline regression after the extraction: **902
  passed, 2 skipped**. This does not close the remaining evidence/reducer
  split or any live acceptance gate.

## M6 induced-failure evidence ledger (2026-09-18)

`M6_INDUCED_FAILURE_MATRIX.md` maps all fifteen required M6 failure scenarios
to exact offline evidence or marks them explicitly missing. The focused gaps
were NPC-moved, exact stale-target, quest-progress-absent and engine-level
oscillation replays; each now has a focused replay. That last replay also
found and fixed the missing `RuntimeEvent` import on the confirmed-loop path.
Every row still requires selected-PID live evidence before the M6 gate can
close.

## Current M1 runtime increment

- `runtime/events.py` is now a bounded event transport with explicit critical
  retention, safe coalescing for high-frequency update events, subscriber
  isolation, and inspectable drop/coalesce diagnostics.
- `runtime/failures.py` owns domain retry budgets, correlated failure chains,
  success clearing, and backoff decisions. It does not send input, declare
  success, or replace verification.
- `runtime/supervisor.py` now exposes the active supervisory ownership state
  and a bounded transition history. This is diagnostic and priority-gating
  state only: `NavigationService` remains the sole movement owner and
  `ActiveSkillRuntime` remains the sole active-skill owner.
- `navigation/progress.py` is a separate, weighted and hysteretic progress
  evidence component. `navigation/stuck_resolver.py` is a separate bounded
  recovery-intent FSM. Neither sends input; `NavigationService` composes them
  with the one existing REACH movement controller.
- The legacy direct supported-stuck shortcut in `agent/engine.py` now asks
  the resolver for one next action. The first response is always
  `STOP_AND_OBSERVE`, then each subsequent step requires a failed prior step.
- Targeted runtime/core regression suite: **160 passed** on 2026-09-17.
  The complete offline suite after this increment: **862 passed, 2 skipped**.
  This does not replace the full suite, replay validation, or a live test.

## Current M1 freshness-gate extraction

- `runtime/freshness_gate.py` now owns the pure decision between normal
  runtime continuation, bounded camera-verification wait, and stale telemetry
  fail-safe. It has no input, executor, planner, or WorldModel dependency.
- `AutonomousAgent` remains the only component that performs the corresponding
  stop or MANUAL transition. This removes the freshness state machine from the
  engine tick without adding a second control authority.
- Targeted engine/runtime regression after extraction: **146 passed**.
M1 remains incomplete until its remaining extraction and acceptance gates,
including live evidence, are satisfied.

## M1 input-scheduler extraction (2026-09-18)

- `execution/input_scheduler.py:InputScheduler` now owns the one serialized
  persistent forward/steering lease, its watchdog and explicit release. It
  has no bindings, PID, focus, planner, WorldModel or Win32 API dependency.
- `agent/executor.py:InputExecutor` remains the one selected-PID input
  authority: it resolves the selected bindings cache, verifies foreground and
  F12 safety, then hands only validated physical keys to the scheduler.
  Ordinary hover/click input first releases the movement lease, so the two
  lanes cannot retain conflicting keys.
- Focused scheduler/executor/runtime-safety regression: **101 passed**. This
  is offline evidence only; it does not replace selected-PID live validation.

## M1 progress/stuck runtime-event acceptance (2026-09-18)

- The engine now emits a single `POSSIBLE_STUCK` event when a live movement
  attempt transitions to candidate stuck, and a critical `STUCK_DETECTED`
  event only when the controller has supported hard-stuck evidence. Fast-loop
  samples in the same phase are not allowed to flood EventBus.
- The new canonical replay installs an actual MOVE attempt, supplies fresh
  stationary telemetry and proves the event order. It also caught and avoids
  a false test setup where normal heading correction was being mistaken for a
  static obstruction. Targeted M1/progress/stuck/supervisor regression:
  **23 passed**. These are offline acceptance artifacts; the selected-PID live
  M1-A through M1-D records remain open.
- Structured diagnostics preserve the severity distinction as `WARN` for a
  candidate and `CRITICAL` for confirmed stuck, so a live log can distinguish
  normal no-progress observation from a required safety/recovery escalation.

## M1 stuck-recovery priority repair (2026-09-18)

- The engine previously allowed a medium-priority `SEEK_VISUAL_CUE` proposal
  to skip an already-supported movement obstruction because the recovery gate
  was incorrectly tied to a numeric priority cutoff. A replay exposed this:
  the resolver stayed IDLE after `supported_stuck`.
- A confirmed recovery now outranks exploration/search. It is still blocked by
  live combat/survival, casting, an already-open UI interaction, or an active
  combat/interaction skill. The same canonical replay proves the required
  sequence `STUCK_DETECTED → STOP_AND_OBSERVE → BACKWARD RECOVER`.
- Targeted M1/recovery/commitment regression: **34 passed**. Live M1-B/C
  records remain required.

## M1 recovery-resume contract (2026-09-18)

- On `supported_stuck`, the engine retains the failed high-level REACH intent
  without retaining an active skill or a held key. Only a verified successful
  `RECOVER` arms one normal-planner resume candidate.
- The candidate must still match the current map and (where relevant) target,
  and is suppressed by combat or open interaction UI. Lost preconditions are
  recorded and discarded instead of extrapolating stale movement state.
- The canonical replay now proves `STUCK_DETECTED → STOP_AND_OBSERVE →
  RECOVER → same MOVE proposal`, with the resume explicitly marked but routed
  through the ordinary active-skill dispatch boundary. Targeted regression:
  **118 passed**. Live M1-B/C remains open.

## Current full offline regression (2026-09-18)

After the WorldModel projection split, InputScheduler extraction and M1
movement-event replay, the complete suite is **905 passed, 2 skipped** in
48.42 seconds. This is regression evidence only, not a live-validation or
release-gate claim.

## Current M2 combat and interaction increment

### Target-manager lifecycle increment (2026-09-18)

- `agent/target_manager.py` now keeps the M2 target lifecycle explicitly:
  `NONE → CANDIDATE → ACQUIRING → ACQUIRED/ENGAGED`, with explicit
  `OCCLUDED`, `REACQUIRING`, `DEAD`, `LOST` and `UNREACHABLE` outcomes.
- Ranking keeps every individual evidence contribution and penalty in the
  diagnostic candidate record. A candidate has to carry a normalized **live
  addon GUID**; visual tracks, map markers, names and template IDs remain
  non-actionable evidence.
- Sticky selection has a configurable policy and switch margin. Target-state
  promotion is driven only by the selected-target telemetry record in
  `CombatController`, not by CV classification or a scoring result.
- The component has no executor, input, WorldModel-write or planner import.
  Focused target/identity/combat-skill regression: **18 passed**. This is an
  offline M2 checkpoint; combat lifecycle replay and selected-PID live
  validation remain open.

### Ability-rule authority increment (2026-09-18)

- `skills/ability_rules.py` is now the shared, pure ability model and rule
  evaluator. It exposes normalized ability definitions (range, timing,
  resource, target/facing/LOS requirements and tags) plus every candidate's
  eligibility, score and explicit rejection reasons.
- `CombatSkill` and `CombatController` now use that one evaluator; the former
  owns the active cast attempt and the latter only projects the top diagnostic
  candidates. This removes the two former, silently divergent combat-bar
  filters without creating a second input authority.
- Missing target, wrong target class, usability, range, cooldown, binding and
  resource failures are explainable rule outcomes. Rule selection remains a
  proposal until the existing correlated verification path observes the cast
  result. Focused ability/combat regression: **28 passed**; complete offline
  regression after the M2 changes: **912 passed, 2 skipped** in 25.92 seconds.

### Kill-evidence fusion increment (2026-09-18)

- `verification/combat.py` now retains source-labelled death evidence and
  confirms an M2 kill only at `DeadConfidence >= 0.85`, through a deterministic
  death event, or by a corroborated selected-target disappearance/combat-end/
  objective-credit combination.
- An objective counter increment alone is deliberately weak supporting
  evidence and cannot claim a kill. Target flags, zero HP, same-GUID corpse,
  combat-log death and correlated disappearance are independent evidence
  categories; a mismatched selected GUID still returns identity failure first.
- Focused combat/engine regression: **114 passed**. This protects offline
  fake-success paths; selected-PID combat evidence remains required.

### Interaction hover-verification increment (2026-09-18)

- `InteractSkill` now uses the M2 `HOVER → VERIFY_HOVER → INTERACT` path
  whenever an exact selected-target screen anchor is available. A matching,
  fresh addon mouseover GUID must arrive after the pointer command before the
  interaction binding is sent.
- Center, upper-center, left-center and right-center are the only sample
  points. Missing hover evidence after those four attempts is a typed
  low-confidence/replan outcome, never a blind interaction click. The
  selected-target fallback remains explicitly limited to cases with no usable
  screen anchor; it is not recorded as hover confirmation.
- Focused interaction/engine regression: **122 passed**. Selected-PID hover
  latency and UI-result validation remain open M2 live evidence. Complete
  offline regression after the M2 work: **920 passed, 2 skipped** in 49.33
  seconds.

- `skills/action_error_correlation.py` associates a client error with a
  particular ability attempt only when it is new and arrives inside the
  bounded correlation window. A retained `UI_ERROR_MESSAGE` is not silently
  re-used as range, facing, or line-of-sight evidence for a later cast.
- `skills/interaction_result.py` separates recovery classification from the
  observable interaction effect. The latter reports only a postcondition seen
  in the state delta (for example `QUEST_DETAIL_OPEN` or `LOOT_OPEN`), never
  a guessed success.
- `navigation/__init__.py` no longer eagerly imports `NavigationService` from
  a low-level progress import. This removes the `ReachMovementController` ↔
  `NavigationService` circular import while retaining the public service API.
- Full offline regression after these increments, executed in independent
  partitions on 2026-09-17: **880 passed, 2 skipped**. This is offline evidence
  only and does not satisfy any M1--M6 live acceptance gate.

## Current M3 quest failure-memory increment

- `agent/quest_failure_memory.py` stores a bounded cooldown for an exact
  quest/objective/target/skill failure key. It prevents immediate repeat
  attempts but leaves other targets, objectives, and skills available.
- The memory is recorded from the canonical terminal-result path, exposed to
  the planner through read-only runtime context, and cleared when the matching
  quest stage changes or the same action succeeds. It never mutates quest
  progress or declares a target invalid.
- Targeted quest/planner/runtime regression after the increment: **110 passed**.
  The M3 end-to-end acceptance flow remains open for replay and live evidence.

## Still open

- FAST/full addon-state ingestion, snapshot projection and non-addon evidence
  projection are now separate reducers while `WorldModel` remains the sole
  writer. Remaining WorldModel work is bounded projection/helper extraction,
  not a second state authority.
- World Map scan-session/TDB-fallback lifecycle is now extracted into the
  composed, input-free `WorldMapFallbackPolicy`; proposal ranking still has
  one authority. Selected-PID validation of that search order remains open.
- Finish splitting the remaining `AutonomousAgent.tick` planner-compatibility/
  goal-bookkeeping tail; observation
  ingestion, command-lane dispatch, generic/quest/navigation/memory terminal
  effects and inspection learning are now separate.
- Define and validate the remaining M1 progress/stuck/anti-loop contracts at
  the canonical runtime boundary; then extract the engine units without
  changing physical input ownership.
- Implement the remaining M1--M6 acceptance/replay/live gates. Offline tests
  do not equal quest completion or M6 completion.

## TrinityCore mmap route-source checkpoint (2026-09-21)

- `navigation/mmap_navmesh.py` lazily reads either an extracted mmap directory
  or the original zip and projects connected Detour ground polygons into
  `WORLD_YARDS` anchors. It is planning-only and cannot dispatch input.
- `GlobalPlanner` uses this route source only for same-instance, explicitly
  confirmed `WORLD_YARDS` endpoints; normalized map coordinates retain the
  old measured/direct fallback. `NavigationService` remains the sole movement
  authority and composes the resulting corridor with live local
  traversability, danger and stuck evidence.
- The supplied Retail 12.1 map 2175 data passed same-tile and cross-tile
  parsing/routing. Portable regression is in `tests/test_mmap_navmesh.py` and
  detailed evidence/configuration is in `docs/MMAP_NAVIGATION.md`.
- Selected-PID Exile's Reach execution, moving/dynamic obstacle behavior and
  final arrival are still `LIVE_OPEN`; offline navmesh parsing is not a live
  navigation completion claim.

## Active-skill runtime extraction checkpoint (2026-09-20)

- `InteractionRuntimeRunner` now owns the complete active interaction runtime
  FSM: world/visual approach continuation and startup, facing requests,
  bounded interaction retries and typed terminal results. Agent remains the
  only command dispatcher and active-skill finalizer. Focused interaction
  regression passed **150 tests**; the full suite passed **979 tests** with
  **2 skipped** in 19.85 seconds.
- `CombatRuntimeRunner` now owns active combat approach/resume, local combat
  reposition requests and rotation command projection. It cannot dispatch
  physical input or finalize an attempt. Focused combat/engine regression
  passed **118 tests**; the full suite passed **984 tests** with **2 skipped**
  in 24.52 seconds.
- `LootRuntimeRunner` now owns loot verification plus the bounded corpse
  approach/resume flow, including the typed `CORPSE_NOT_FOUND` path. The
  navigation service remains the movement authority and Agent remains the
  sole dispatcher/finalizer. Focused loot/engine regression passed **115
  tests**; the full suite passed **990 tests** with **2 skipped** in 51.77
  seconds.
- `AutonomousAgent.tick` is now 1104 lines and the complete engine is 1713
  lines (previous checkpoint: 1251/1857). The remaining split concerns skill
  result projection and planning/goal orchestration, not a second controller.
  These are offline architecture gates; selected-PID live M1--M6 validation
  remains open.

## Verification, recovery and planning ownership checkpoint (2026-09-20)

- `runtime/verification_engine.py` is now the canonical projection of a typed
  verifier result into pending/success/failure diagnostics. It cannot invent
  success: `RUNNING` stays pending and only a domain verifier's `SUCCESS`
  obtains a success reason. Focused regression passed **147 tests**; the full
  suite passed **995 tests** with **2 skipped** in 42.80 seconds.
- `agent/recovery_planning.py:RecoveryPlanner` owns supported-stuck priority,
  the conservative 120-second stationary watchdog and bounded recovery-intent
  selection. It emits no movement commands; `NavigationService` still owns
  recovery evidence and movement. Focused regression passed **131 tests**;
  the full suite passed **1000 tests** with **2 skipped** in 48.76 seconds.
- `agent/planning_orchestration.py` now composes fresh candidates, supervisor
  resume, verified recovery resume, confidence fallback, autonomy arbitration
  and plan revision/building. It cannot ingest WorldModel state or dispatch
  input. Focused regressions passed **121** and **122** tests; complete suites
  passed **1006/2** and **1007/2** respectively.
- `runtime/skill_executor.py` now owns proposal preparation, domain-skill start
  routing and construction of the immutable pre-action attempt/prediction
  window. The merged canonical world state is deep-copied for verification;
  compact FAST telemetry cannot fabricate inventory/quest deltas. It returns
  commands but has no physical dispatch/backend access. Focused regression
  passed **151 tests**; the full suite passed **1013 tests** with **2 skipped**
  in 26.22 seconds.
- Engine source is now **1384 lines** and `tick` is **747 lines** (earlier
  checkpoint: 1857/1251). Post-dispatch bookkeeping, remaining proposal
  adapters and the terminal compatibility tail still require extraction.
  None of these offline results closes a selected-PID live gate.

## M3/M6 adaptive end-to-end checkpoint (2026-09-20)

- `tests/test_v5_m3_adaptive_quest_environment.py` supplies only a high-level
  campaign goal, then changes simulated authoritative game state in response
  to the skill actually selected by the production Planner/SkillExecutor. It
  is not a fixed JSONL or input macro; an incorrect decision cannot advance
  the scenario.
- The scenario proves quest offer/accept, canonical navigation, combat,
  verified loot/objective credit, return, turn-in and follow-up detection. A
  deliberately ignored first interaction is advanced beyond its deadline so
  the normal verifier/failure/planner path must terminate and retry before the
  quest can complete.
- The separate lifecycle acceptance test proves an attempted combat or loot
  action cannot mutate objective counts without authoritative quest evidence.
  It also exposed and fixed full scoped objective IDs such as `701:loot` in
  `QuestProgressVerifier`.
- Complete offline regression after the adaptive scenario was **1038 passed,
  2 skipped** in 63.51 seconds; after extending the same OpenCV AUTO/CUDA/CPU
  backend to World3D preprocessing it is **1039 passed, 2 skipped** in 96.41
  seconds. The named deterministic M1--M6 offline scenarios are green; the
  selected-PID questline, induced failures and long-run performance gates are
  still open and M6 is not declared complete.

## Quest planning module and World3D compute checkpoint (2026-09-20)

- `QuestDomain` was physically extracted from the high-level planner into
  `agent/quest_planning.py`. It remains composed by the single `Planner`; it
  has no input dispatch, movement, runtime-finalization or WorldModel-ingest
  authority. `planner.py` is now **882 lines** instead of 1323, while the
  extracted quest policy is 458 lines.
- The OpenCV AUTO/CUDA/CPU backend now also supplies the shared World3D V2/V3
  BGRA-to-gray and downsample stage. V2 detector and fast patch tracker share
  one selected backend and expose the real backend/fallback diagnostics.
  Phase correlation, patch comparison, proposal scoring and semantics remain
  CPU-side and are not mislabeled as GPU execution.
- Architecture guards explicitly reject an embedded `QuestDomain` in
  `planner.py` and reject input, dispatch or ingest ownership in the extracted
  policy. Focused quest/agent tests passed **120**; World3D/OpenCV tests passed
  **60**. Latest full suite: **1040 passed, 2 skipped** in 218.76 seconds.
  Live validation remains open.
- Availability/cooldown filtering and explainable priority/reliability/pattern/
  cost ranking now live in the input-free `ProposalRanker`. The Planner still
  owns candidate composition and calls one ranker; no second decision loop was
  introduced. `planner.py` is now **851 lines**, and focused ranking/planner
  tests passed **115**. Latest full suite: **1043 passed, 2 skipped** in 38.73
  seconds.
- Active `SEEK_VISUAL_CUE` and `VISUAL_APPROACH` stepping now belongs to the
  shared input-free `VisualRuntimeRunner`. It returns commands, dispatch lane,
  camera intent, stop request or typed terminal result; only Agent dispatches
  and finalizes. Architecture guards enforce this boundary. Focused regression
  passed **155** tests. After the mmap route-source increment the latest full
  regression passed **1056 tests, 2 skipped** in 52.64 seconds. Engine is now
  **1289 lines** and `tick` **648 lines**.
- Target reacquisition, quest-target matching, combat/defend/escape and corpse
  loot proposal construction now belongs to the input-free
  `CombatPlanningPolicy`. It cannot rank a winner, dispatch input, mutate the
  WorldModel, own an active skill or start movement; the one `Planner` composes
  its proposals and the existing target/combat/runtime authorities remain
  canonical. `planner.py` is now **666 lines** and the extracted policy is
  **207 lines**. Direct policy and static authority-boundary tests are green;
  the latest complete offline regression is **1063 passed, 2 skipped** in
  44.46 seconds. No live gate is claimed.
- World3D/Minimap/World Map inspection eligibility and bounded per-group
  attention projection now live in the input-free `VisualInspectionPolicy`.
  Raw tracks remain UNKNOWN and `ActivePerception` remains the sole
  information-value authority; the policy cannot recognize identities, rank
  the global winner, mutate WorldModel or dispatch input. The Planner composes
  the resulting proposals and is now **509 lines**. Focused regression passed
  **146 tests**; the complete offline suite passed **1064 tests, 2 skipped** in
  42.37 seconds. No live gate is claimed.
- Distant UNKNOWN cue approach, bounded local camera-search intent, World3D
  before-map fallback and confirmed-target suppression now live in the
  input-free `VisualSearchPlanningPolicy`. The policy returns proposals plus
  explicit search-state values; it has no camera backend, movement controller,
  dispatcher, active-skill or WorldModel-write authority. `planner.py` is now
  **327 lines**. Focused regression passed **161 tests**; the complete offline
  suite passed **1065 tests, 2 skipped** in 33.36 seconds. No live gate is
  claimed.
- Runtime map validation no longer writes `runtime_map_validated` into the
  canonical WorldModel from Planner code. `QuestLocationPlanningPolicy`
  derives the eligibility from immutable provenance, session and scan-time
  inputs. A direct regression proves that a valid learned location produces a
  MOVE proposal while the stored observation remains unchanged. The complete
  offline suite now passes **1066 tests, 2 skipped** in 34.42 seconds.
- Live PID-12400 diagnostics separated a healthy ~34 Hz pixelstrip FAST source
  from a 4--5 Hz main-thread consumer. The large World diagnostic projection
  is now sampled at 4 Hz while control/result fields remain tick-fresh; new
  World3D observations force immediate diagnostic refresh. The previously
  unclassified ~179 KB/row `WORLD3D_LOCAL_VIEW` stream is now eligible for the
  existing derived-CV retention bound. Focused performance/retention tests and
  the complete offline suite pass at **1068 tests, 2 skipped** in 37.89
  seconds. Repeat FULL_AI rate validation remains live-open.
- M4.16 now has a model-neutral learned-detector interface, optional lazy
  Ultralytics backend, UNKNOWN-first evidence adapter, additive V2 integration,
  strict dataset auditor and gated training command. The user-supplied
  Wowpedia-derived dataset was measured rather than assumed valid: 6,155/6,155
  boxes are full-frame, train and val overlap completely, test is absent and
  duplicate stems exist. Training was therefore correctly refused and no model
  is promoted. Exact data requirements and the available 945 addon-confirmed
  crops are recorded in `WORLD3D_LEARNED_DETECTOR.md`. Full regression is
  **1073 passed, 2 skipped in 38.66 seconds**; detector accuracy and live
  latency/behavior remain open until a reviewed, disjoint real-game dataset
  and model artifact exist.
- `WorldMapFallbackPolicy` now owns map scan/zoom state, session reset,
  current-session marker validation, map open/close proposals, TDB-last-resort
  proposal construction and its verified terminal bookkeeping. It cannot rank
  globally, dispatch input, move, target or write WorldModel state. Planner
  retains compatibility properties backed by the single policy state and is
  now **298 lines**. Targeted map/planner/runtime regressions passed **208**;
  after terminal-effect extraction **203** targeted tests passed. Complete
  regression: **1078 passed, 2 skipped in 41.74 seconds**. Live World3D ->
  World Map -> TDB ordering remains open.
- `WorldAddonReducer` now owns decoded FAST/full addon projection, same-GUID
  partial-unit merge, quest/event/entity/UI reducer orchestration and evidence
  refresh. It has no independent store and mutates only the supplied canonical
  WorldModel. Direct tests prove same-GUID identity preservation, different-GUID
  non-inheritance and full-state event/quest projection. WorldModel is reduced
  from 1269 to **1175 lines**; the reducer is 124 lines. Focused regression:
  **172 passed**. Complete regression: **1081 passed, 2 skipped in 32.48
  seconds**. Live FAST-rate revalidation remains open.
- `WorldStateProjector` now owns the canonical query-state rebuild: source
  projection merge, camera fields, bounded corpse/mouseover/semantic retention,
  exact-GUID semantic projection and UNKNOWN-track association. It is stateless
  and writes only the supplied WorldModel; `_rebuild_state()` remains a thin
  compatibility delegation. Existing anchor/movement/camera invalidation tests
  plus the focused WorldModel suite pass **192 tests**. WorldModel is now
  **1072 lines** and the complete suite remains **1081 passed, 2 skipped**
  (39.33 seconds). Live identity/track association remains open.
- `ActiveSkillSupervisor` now owns the observation-to-step routing for an
  already-active TARGET, INTERACT/TALK, COMBAT/DEFEND, LOOT or generic M0
  skill. It returns inert command/diagnostic/terminal data only. Static guards
  prove that it cannot dispatch input, ingest WorldModel state, instantiate or
  finish `ActiveSkillRuntime`, or become a second skill authority. Agent still
  performs every physical dispatch and canonical terminal transition.
  `engine.py` is now **1000 lines** and `tick()` **428 lines**, down from
  1206/642 at the previous checkpoint. Direct and affected-domain regressions
  passed **202 tests**; complete regression passed **1109 tests, 3 skipped in
  45.72 seconds**. Selected-PID/live M1--M6 evidence remains open.
- `ActionLaunchCoordinator` now owns only launch-policy projection: canonical
  empty-start eligibility, immediate typed result mapping and dispatch-lane
  choice. It delegates attempt creation/start to `SkillExecutor` and the one
  supplied `ActiveSkillRuntime`; static guards prohibit dispatch, finalization,
  ingestion or a parallel active owner.
- The existing `ActiveSkillSupervisor` now routes MOVE/FOLLOW/REACH and
  SEEK/VISUAL_APPROACH through the existing `MovementSkillRunner` and
  `VisualRuntimeRunner` as well as the previously extracted target,
  interaction, combat and loot paths. This is one routing boundary, not a
  merged domain controller: all physical command dispatch and terminal
  application remain in Agent. Same-frame visual-success replanning and the
  REFERENCE_REACH_SEARCH no-progress exclusion have direct regressions.
  `engine.py` is **907 lines**, `tick()` is **263 lines**, affected regression
  passed **204 tests**, and full regression passed **1115 tests, 3 skipped in
  44.21 seconds**. Selected-PID/live acceptance remains open.
- `WorldAnchorReducer` now owns confirmed corpse-event and live mouseover/cursor
  anchor projection. It has no state, Planner, controller or input dependency;
  it mutates only the supplied canonical WorldModel. Exact-GUID association,
  simultaneous cursor/mouseover freshness, map-surface exclusion, UNKNOWN-track
  linkage and looted-corpse tombstones are preserved. WorldModel is now **923
  lines**, down from 1072. Focused regression passed **166 tests** and full
  regression passed **1116 tests, 3 skipped in 38.39 seconds**. Selected-PID
  mouseover/track association remains live-open.
- DESIGN-073 now has a bounded local command lifecycle in
  `execution/command_ack.py`: `CREATED`, `QUEUED`, `DISPATCHED`, `LOCAL_ACK`,
  `FAILED`, `CANCELLED`. Dispatch receipts correlate to the canonical
  `action_id`; status diagnostics expose the latest bounded receipts. A local
  acknowledgement explicitly reports no world success, so quest/combat/UI
  completion still requires its domain verifier. Focused regression passed
  **160 tests** and full regression passed **1120 tests, 3 skipped in 47.68
  seconds**. Selected-PID acknowledgement timing/failure remains live-open.
- DESIGN-077 now has a single explicit invalidation matrix for objective,
  loading, teleport, map-context, death, phase, floor and vehicle transitions.
  The policy can only clear canonical transient WorldModel projections and call
  declared reset callbacks; it has no executor/backend. Agent retains the one
  cancellation and movement-release authority. A production-Agent integration
  test proves an active REACH is cancelled on map change and stale screen
  anchors are removed. Full regression passed **1126 tests, 3 skipped in 45.01
  seconds**. The corresponding selected-PID transitions remain live-open.
- DESIGN-024/V4-029 shared facing is now offline complete. The one
  NavigationService-owned `FaceController` exposes the specified lifecycle,
  bounded turn command projection, timeout/cancel and fail-closed missing
  target/binding handling. The previous reversed deadzones were corrected to
  narrow-enter/wide-exit hysteresis. Focused regression passed **120 tests** and
  full regression passed **1128 tests, 3 skipped in 32.62 seconds**. Selected-
  PID facing accuracy remains live-open.
- V5 M1.2 EventBus now satisfies its offline interface and concurrency gates:
  bounded thread-safe queue/history/dedupe/subscriptions, critical-event
  preservation, low-value coalescing, observable depth, subscriber exception
  isolation, recent-event queries and correlated/idempotent envelopes. The
  parallel-producer regression preserves each producer's order across 800
  events. Focused regression passed **136 tests** and full regression passed
  **1129 tests, 3 skipped in 35.32 seconds**. Sustained selected-PID load is
  live-open.
- V5 M1.3 now attributes every accepted observation to affected major
  WorldState sections with observation ID, monotonic update time, source
  timestamp, source and model revision. `WorldSectionUpdateTracker` is stateless
  and has no planner/input authority; designated reducers remain the only
  mutation path. Planning snapshots expose read-only mappings and diagnostic
  snapshots isolated copies. Focused regression passed **40 tests** and full
  regression passed **1133 tests, 3 skipped in 32.85 seconds**. Selected-PID
  attribution remains live-open.
- V5 M1.4 normalized WorldState is now available as an immutable planning
  projection with all eleven named major sections plus Version/UpdatedAt.
  Existing snapshot/query consumers remain compatible. EntityMap enforces
  detection != recognition: raw/CANDIDATE semantic labels project as UNKNOWN,
  and only CONFIRMED semantics may become BestClass. Focused regression passed
  **133 tests** and full regression passed **1137 tests, 3 skipped in 30.48
  seconds**. Selected-PID field accuracy remains live-open.

## 2026-09-22 detailed coverage closure

The V5 line-by-line ledger now has **0 unreviewed TRACKED rows**: 166/169 are
`OFFLINE_VERIFIED`; V5-147, V5-148 and V5-168 remain deliberately
`OFFLINE_PARTIAL` because selected-PID end-to-end/live release evidence cannot
be replaced by replay. M4 gained explicit temporary dynamic-obstacle lifecycle,
two-stage cliff confirmation and context-sensitive terrain-transition evidence.
Focused audits passed for M4 (120 passed, 1 skipped), M5 (53 passed), M6 (62
passed) and M1 authority boundaries (89 passed). Final complete regression:
**1514 passed, 3 skipped in 47.34 seconds**. No WoW input was sent.

## 2026-09-23 World3D M4/M6 evidence extension

- M4 temporal continuity now includes a bounded retired-track archive and
  ambiguity-rejecting long-gap re-identification without semantic inference.
- M4 fusion exposes visual-condition-adjusted confidence, field freshness,
  semantic hysteresis, cross-view source ordering, death/corpse continuity and
  typed failure feedback.
- M6 replay contains the named World3D record sequence and an input-free
  graphical renderer/CLI.
- Context profiles alter the existing worker/detector/OCR schedule without a
  second perception, planner, movement or input authority.
- Complete offline regression: **1535 passed, 3 skipped in 65.44 seconds**.
  All selected-PID and long-run live evidence remains open.

## 2026-09-23 World Map hierarchy/resolver wiring

- Both Retail addon copies now export the active/displayed/player map IDs and
  the real Retail parent hierarchy (bounded to four, cycle-safe) on FULL and
  compact FAST telemetry.
- The existing `WorldMapAbsenceResolver` is composed by the canonical map
  fallback policy. A tracked-quest scan with no current-level marker may issue
  at most two parent-step attempts, and success requires the addon to report
  the exact expected parent map. Absence remains UNKNOWN; no screen pixel is
  converted into a world coordinate.
- Engine/runtime pure projection extraction is locked by authority-boundary
  tests; no second planner, reducer, executor or finalizer exists.
- Complete offline regression: **1554 passed, 3 skipped in 54.45 seconds**.
  No client input was sent. Parent-map UI behavior remains `LIVE_OPEN`.

## 2026-09-23 canonical arrival verification

- Replaced the distance-only arrival helper with one evidence-fused
  `ArrivalVerifier` producing `UNKNOWN`, `CANDIDATE` or `ARRIVED` plus
  confidence and traceable evidence.
- Reliable absolute distance, minimap convergence, interaction readiness,
  bbox growth, quest-area state change and map transition are separate inputs.
  Weak cues remain candidates; distance is used only with an explicit
  coordinate-reliability contract.
- Enter/exit hysteresis prevents threshold chatter. The production
  `ReachMovementController` now uses this verifier; no second movement or
  input authority was added.
- Focused navigation/movement regression: **32 passed**. Complete regression:
  **1570 passed, 3 skipped in 67.47 seconds**. Live arrival calibration remains
  open.

## 2026-09-23 typed quest progress verification

The authoritative quest-credit verifier now distinguishes quest start,
ongoing quest progress, objective completion, stage change, ready-for-turn-in
and final quest completion while preserving all existing skill-facing
`VerificationResult` behavior. Related focused regression: **34 passed**;
complete regression: **1574 passed, 3 skipped in 83.49 seconds**. Live addon
event ordering remains open.
