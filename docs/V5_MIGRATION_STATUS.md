# V5 migration status

## M1.10 Stuck Resolver FSM checkpoint (2026-09-21)

All fifteen specified stuck states are active in one finite, evidence-gated
resolver. Every emitted recovery step must receive exactly one result and pass
through VERIFY_RECOVERY before the ladder can advance. NEW_LOCAL_WAYPOINT now
uses only NavigationService/corridor geometry and runs as a normal verified
MOVE; BLACKLIST_TEMP creates expiring danger memory and then terminates into a
global replan. DROP_OR_CLIFF still forbids JUMP_FORWARD. The resolver selects
intent only and has no input backend. Focused regression passed **33 tests**;
complete regression passed **1159 tests, 3 skipped in 34.41 seconds**. Live
recovery effectiveness remains open.

## M1.9 Progress Score checkpoint (2026-09-21)

The canonical ProgressMonitor implements the specified configurable five-source
weighted score and exact possible/hard/recovered timing gates. Missing sources
are excluded and remaining weights renormalized; invalid/nonfinite signals are
unavailable rather than fake progress. A total sensor dropout now reports
UNAVAILABLE and resets temporal gates, so an old HARD_STUCK classification
cannot trigger recovery without fresh evidence. MovementController and
StuckClassifier consume this same monitor. Focused regression passed **42
tests**; complete regression passed **1154 tests, 3 skipped in 31.83 seconds**.
Live threshold/signal calibration remains open.

## M1.8 Failure Manager checkpoint (2026-09-21)

Failure handling now has a finite typed escalation lifecycle. Reasons are
normalized, counted per bounded correlation chain, assigned a domain recovery,
and budgeted through SKILL_RETRY, DOMAIN_RECOVERY, PLANNER_REPLAN,
GOAL_ALTERNATIVE and GOAL_FAILED. Agent consumes replan decisions and
GoalManager consumes recovery/alternative/failure stages; persistent goals
suppress an exhausted task rather than repeating it forever. FailureManager
remains input-free. Focused failure/goal/terminal regression passed **54
tests**; complete regression passed **1151 tests, 3 skipped in 38.61 seconds**.
Live recovery effectiveness remains open.

## M1.7 Verification Engine checkpoint (2026-09-21)

Verification is now fail-closed at one confirmation boundary. A raw or
start-routine `SkillStatus.SUCCESS` remains pending; only an explicitly invoked
domain/generic/movement/visual postcondition verifier may confirm terminal
success. The decision records verifier identity and evidence. Dispatch/local
ACK remains separate from world success. MOVE arrival, interaction UI/result,
combat death/progress and quest-dialog acceptance paths are covered through
their production verifiers. Focused acceptance passed **37 tests**; complete
regression passed **1147 tests, 3 skipped in 39.73 seconds**. Live evidence
latency and correctness remain open.

## M1.6 Skill Executor checkpoint (2026-09-21)

The one `ActiveSkillRuntime` now carries the full V5 lifecycle independently
from domain-specific phase strings: CREATED, WAITING_PRECONDITIONS, RUNNING,
VERIFYING, RETRYING, RECOVERING, SUCCESS, FAILED and PREEMPTED. Its typed
SkillContext contains SkillId, CorrelationId, Parameters, StartedAt, Deadline,
Attempt, WorldSnapshotVersion and an observable CancellationToken. Every
registered SkillContract also declares all six required behavioral fields.
No dispatch or finalization authority moved out of Agent. Focused agent/runtime
regression passed **137 tests**; the complete suite passed **1145 tests, 3
skipped in 46.82 seconds**. Selected-PID lifecycle timing remains live-open.

## M1.5 Supervisor FSM checkpoint (2026-09-21)

The production Supervisor now exposes the complete V5 state contract for all
twelve required states: stable state ID, priority, interruptibility, timeout,
bounded retry metadata, evidence-backed enter/exit gates, a single tick path
and an explicit minimum preemption matrix. The existing `evaluate()` path is
the same tick authority and enters states through the lifecycle gate; this did
not create a second planner, executor, movement owner or input path. Agent
continues to own cancellation, key release and terminal application. Focused
Supervisor/architecture regression passed **39 tests** and the full suite
passed **1141 tests, 3 skipped in 38.43 seconds**. Live selected-PID transition
timing remains open.

## Goal completion authority checkpoint (2026-09-21)

Generic terminal-condition evaluation has moved from `AutonomousAgent` to the
existing `GoalManager`. The contract accepts only explicit duration, verified
bag-capacity, or same-map MOVE-arrival conditions; attempted work and projected
quest progress cannot author completion. Focused regression passed **157
tests** and the complete suite passed **1085 tests, 2 skipped in 45.23
seconds**. Remaining engine bookkeeping extraction and all selected-PID live
acceptance gates stay open.

## Skill launch and obstacle acceptance checkpoint (2026-09-21)

`SkillExecutor.install_attempt` now owns the non-dispatching bridge from one
prepared proposal to one immutable attempt and the supplied canonical
`ActiveSkillRuntime`. It cannot create a second active owner, dispatch input or
finalize a result. The full V5 M4.8Z OBS-A--OBS-J suite is also executable.
Cliff/drop evidence is typed separately and its bounded recovery ladder cannot
jump forward. Focused regressions passed **154** and **44** tests; the complete
suite passes **1097 tests, 2 skipped in 44.99 seconds**. Live acceptance stays
open.

## Planning and terminal compatibility checkpoint (2026-09-21)

The remaining navigation-adaptation, recovery-arbitration and Plan-revision
sequence now runs through `PlanningOrchestrator.resolve`, without input or
movement ownership. Terminal map-search/location/interaction compatibility
effects moved into `ExecutionBookkeeper.record_terminal`; Agent remains the
only active-skill finalizer. Focused regressions passed **159** and **167**
tests. The complete suite passes **1101 tests, 2 skipped in 38.37 seconds**;
live acceptance remains open.

## Verified outcome bookkeeping checkpoint (2026-09-21)

Goal/failure counters, backoff, interaction-range evidence and verified loot
compatibility effects now live in the input-free `AttemptOutcomeBookkeeper`.
It cannot verify, recover, dispatch or finish a skill. `_finish` is **83 lines**
and engine source is **1206 lines**. Focused regression passed **159 tests**;
the complete suite passes **1106 tests, 2 skipped in 41.79 seconds**. Live
acceptance remains open.

## Governing sources

This migration reconciles the user-supplied documents in this order when they
overlap:

1. `wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt`
   is the newest V5 target and supplies the M1--M6 extension, including the
   obstacle/traversability upgrade.
2. `wow_agent_FINAL_M0_M1_master_prompt_v4.txt` remains the M0/M1 ownership,
   safety, and no-wrapper-refactor baseline.
3. `wow_agent_complete_functional_design_spec.txt` defines the functional
   contracts and public boundaries.

The older V5 hardening and World3D design documents remain useful supporting
detail where they do not conflict with the three sources above. No document
authorizes memory access, injection, direct planner/vision input, or an
unverified success state.

## Audit finding

The current source is not yet V4/V5 ownership-clean. The active M0 skill
modules, runtime, and navigation service exist, but these three files still
mix too many responsibilities:

| Boundary | Current file | Current size | Required outcome |
| --- | --- | ---: | --- |
| Runtime orchestration | `agent/engine.py` | 1,917 lines | ingest/supervision/dispatch/verification separated behind one active-skill authority |
| Planning | `agent/planner.py` | 1,733 lines | quest, target-combat, localization, and recovery policies separated; planner emits intents only |
| World state | `agent/world.py` | 1,685 lines | reducer/evidence/query/snapshot responsibilities separated; only reducer mutates model |

## Migration order

1. **World read boundary** — the canonical public query is
   `agent/world_query.py:WorldQuery`; the former in-file duplicate has been
   physically removed.  The remaining WorldModel reducer split must preserve
   this as the only planner-facing read boundary.
2. **Planner domains** — extract quest-localization, target/combat selection,
   recovery, and plan types without changing proposal semantics.
3. **Runtime loop** — separate observation ingest, supervisor/safety,
   persistent-skill dispatch, and terminal-result handling. `AutonomousAgent`
   becomes a composition root, not a second state machine.
4. **World reducers/snapshots** — extract mutation reducers and diagnostic
   snapshot building while preserving `WorldModel` as the only writer.
5. **V5 M1 foundation** — central configuration, explicit failure/progress/
   stuck contracts, architecture guards, replay and golden-trace coverage.
6. **V5 M2--M6** — only after the above boundaries have one authority; the
   obstacle/traversability upgrade enters through World3D observations and
   NavigationService, never by giving perception direct input control.

Each extraction must migrate construction sites and call sites, pass focused
tests, then delete the retired authority. A compatibility shim is allowed only
while its removal criterion is named and tested.

## Validation status

World-query and initial planner-domain extraction are active and offline-tested
with the core agent/world snapshot/navigation set (**147 passed**). The V5 M4.8
increment now has a temporal, evidence-only traversability fusion: first-frame
obstacles remain `SUSPECTED`, repeated observations can become
`CONFIRMED/BLOCKED`, clean evidence decays, and camera rotation cannot produce
forward collision evidence. A confirmed frontal sector is consumed by existing
navigation only after repeated independently observed no-progress attempts.

This is an architectural/offline migration step, not M0/M1/M4 live validation
and not a claim that M1--M6 are complete.

## M1 canonical reducer extraction (2026-09-20)

Raw addon-event, target/mouseover entity and UI-transition reductions were
physically moved to `WorldEventReducer`, `WorldEntityReducer` and
`WorldUiReducer`. They retain one supplied canonical `WorldModel` write target
and have no planner/input dependency;
`WorldModel.ingest` remains the sole ordered runtime ingestion boundary.
Focused world/entity/runtime/navigation regression: **115 passed**; complete
offline regression after this extraction: **951 passed, 2 skipped** in 37.09
seconds. The wider WorldModel/evidence split and all M1 live gates remain open.
Static ownership guards additionally prevent direct Windows-input imports in
policy/perception/navigation-planning code and executor/planner imports in the
new reducers. Focused architecture/runtime/navigation regression: **110
passed**. Complete offline regression after the boundary guards: **956 passed,
2 skipped** in 35.90 seconds.

## M4.1 frame-source checkpoint (2026-09-20)

The canonical World3D publication now has a source-frame contract rather than
only a detector publication label: `frame_id`, monotonic timestamp and
`client_id` are created when the physical capture enters the worker lane and
remain on the batch/replay payload. Superseded in-flight captures are not
queued; they are recorded on the next batch as structured `FRAME_DROPPED`
evidence. Out-of-order timestamps and malformed/mismatched frame evidence are
rejected by the non-mutating batch validator. The change cannot issue input or
alter movement authority. Focused regression: **18 passed**; full offline
suite: **929 passed, 2 skipped** in 116.96 seconds. Live OBS validation is
still required.

## M4.2--M4.7 perception checkpoint (2026-09-20)

The batch now keeps raw per-frame UNKNOWN-first detections separate from
temporal tracks, with validated detection/frame/bbox/class-distribution
contracts. Tracking exposes V5 temporal lifecycle and evidence-only
association cues. Raw geometry is retained while an independent temporal view
smooths screen center, scale, velocity, bearing and relative distance. Camera,
player and entity motion evidence is source-labelled and confidence-bounded.
Focused regression: **72 passed**. This remains offline perception work and
does not change movement, input or live-validation status.

## M4.12 tooltip-observation checkpoint (2026-09-20)

Runtime now publishes a normalized addon-tooltip observation with frame,
hover, parsing and confidence provenance. It can create only a spatial
hypothesis to a near UNKNOWN World3D subject, never a semantic fact or direct
interaction command. Focused tooltip/runtime/approach regression: **80
passed**; the subsequent complete offline M4 suite passed **940 passed, 2
skipped** in 42.67 seconds. Live acceptance remains required.

## M4.13--M4.14 active/UI checkpoint (2026-09-20)

The active-perception component now has a bounded, single-probe FSM with
explicit gain evaluation and safety/preemption termination, but no input
authority. Runtime additionally emits separate frame-stamped UI observations
for all required Retail telemetry surfaces. Focused regression: **90 passed**;
the subsequent complete offline M4 suite passed **940 passed, 2 skipped** in
42.67 seconds. Live acceptance evidence remains pending.

## M4.10--M4.11 map-surface checkpoint (2026-09-20)

Minimap player heading is a separate source-labelled telemetry observation,
while marker coordinates remain local to the immutable player center. Runtime
also publishes a calibrated, frame-stamped World Map state projection for map
identity, layout state, player marker, objective regions and cursor evidence.
Focused regression: **73 passed**; the subsequent complete offline M4 suite
passed **940 passed, 2 skipped** in 42.67 seconds. The live map matrix remains
required.

## M4.15--M4.17 audit checkpoint (2026-09-20)

WorldModel's existing correlation/independence-group reducer remains the only
cross-sensor fusion boundary, and the dataset path remains explicitly
auto-labelled/hard-example collection rather than an unproven trained model.
Focused fusion/dataset/World3D regression: **25 passed**. Full and live M4
acceptance proof remain required.

## M5.1--M5.4 layered-navigation checkpoint (2026-09-20)

Typed request, global-route, corridor and local-motion-plan contracts are now
owned by distinct planning modules and composed only by `NavigationService`.
Global planning is event-bounded; local planning consumes temporal
traversability/cost evidence rather than semantic object labels. A
screen-relative blocked sector cannot become an invented detour coordinate:
the planner requests a local replan until supported geometry exists. The
existing `ReachMovementController` remains the only physical input owner.
The canonical MOVE/FOLLOW-family start path now passes through that typed
boundary once. Direction consistency and command oscillation are retained as
non-displacement diagnostics; typed recovery selection occurs only after the
existing hard-stuck gate. Focused navigation contract/service/progress/engine/
core regression: **131 passed**. Complete offline regression: **951 passed, 2
skipped** in 31.46 seconds. This is an offline partial M5 checkpoint, not
calibrated corridor-to-controller completion or live validation.

## M6.11 performance-observability increment (2026-09-20)

A bounded, read-only performance monitor now reports percentile latency and
queue-depth metrics; every `AutonomousAgent.tick`, including safety early
returns, records supervisor-tick latency. Capture/perception/input values are
only reported when their real producer records them, not inferred from addon
receive time. Focused runtime/world/navigation regression: **114 passed**.
Complete offline regression after this increment: **953 passed, 2 skipped** in
29.42 seconds.

## M1 runtime checkpoint (2026-09-17)

The event transport now has bounded retention, safe update coalescing and
diagnostics; the runtime has a domain failure-budget manager; and the
supervisor reports explicit ownership/recovery states with bounded transition
history. Navigation now composes a separate weighted `ProgressMonitor` and a
bounded `StuckResolver`; the latter selects recovery intents but does not send
input. These components do not add another planner, movement loop or input
backend. The focused regression set for this checkpoint passed **160 tests**.
The complete offline suite after this checkpoint passed **862 tests** with
**2 environment-dependent skips**.

The remaining M1 work is the controlled extraction of engine phases and the
progress/stuck/anti-loop acceptance paths, followed by replay and live
evidence. Therefore this checkpoint is not an M1 completion declaration.

## M2 checkpoint (2026-09-17)

Combat now records an explicit ability-attempt correlation token before each
input. A client error is accepted as recovery evidence only if it is fresh for
that attempt; retained UI text no longer causes a false repeat recovery.
Interaction results record both a recovery-safe category and an observable UI
effect category, keeping `input sent`, `observed UI`, and `success` distinct.
The complete offline suite is **880 passed, 2 skipped**. M2 still requires
replay and live acceptance cases; this checkpoint is not a completion claim.

## M2 target-lifecycle checkpoint (2026-09-18)

`TargetManager` is now a dedicated evidence-only target component with
configurable weighted scoring, hysteresis and the explicit lifecycle
`NONE/CANDIDATE/ACQUIRING/ACQUIRED/ENGAGED/OCCLUDED/REACQUIRING/DEAD/LOST/UNREACHABLE`.
It can rank only normalized live addon GUIDs. `CombatController` observes the
currently selected target telemetry to promote lifecycle state, while CV, map
markers and templates remain evidence and cannot directly create an actionable
target. Focused regression: **18 passed**. This is not M2 live completion.

## M2 ability-rule authority checkpoint (2026-09-18)

The pure shared `AbilityRuleEngine` now supplies `AbilityDefinition` and
explainable candidate evaluation to both `CombatSkill` and
`CombatController`. Range, cooldown, resource, binding and target preconditions
are recorded as explicit rejection reasons; ability input and post-cast
verification remain in the existing canonical skill path. Focused regression:
**28 passed**; full offline regression: **912 passed, 2 skipped** in 25.92
seconds. This remains offline M2 evidence only.

## M2 kill-evidence checkpoint (2026-09-18)

Combat verification now retains named dead-evidence sources and only confirms
a kill at the M2 threshold, by deterministic death event, or through a
correlated target-disappearance/combat-end/objective-credit combination.
Objective progress by itself no longer completes combat as a kill. Focused
combat/engine regression: **114 passed**. Live combat death evidence is still
required before M2 can close.

## M2 hover-verification checkpoint (2026-09-18)

When a selected target has a usable screen anchor, interaction now requires a
fresh matching addon mouseover after an explicit bounded hover sample. It
tries at most four safe points, then fails/replans rather than clicking blind.
Focused interaction/engine regression: **122 passed**. This is offline-only
evidence; live hover/tooltip latency remains part of M2 acceptance. Complete
offline regression after the M2 work: **920 passed, 2 skipped** in 49.33
seconds.

## M3 failure-memory checkpoint (2026-09-17)

The runtime now records bounded, exact quest-action failure cooldowns and
passes their read-only snapshot to the planner. A changed quest stage or a
verified success clears the matching record. This supports recovery without
making failed attempts into quest facts. M3's full generic objective and live
questline acceptance gates remain open.

## M3 quest-graph checkpoint (2026-09-18)

`QuestGraph` now owns the read-only dependency graph, conditional blockers and
objective-readiness projection, while `QuestModel` remains the only normalized
record writer. The graph cannot mutate quest state, select skills, navigate or
send input. Focused quest/agent regression: **115 passed**. This is offline
modularity evidence, not M3 questline live completion.

## M3 quest-lifecycle checkpoint (2026-09-18)

Quest records now carry an evidence-derived lifecycle that separates
`OBJECTIVES_COMPLETE`, `READY_TO_TURN_IN` and `TURNING_IN` from full
completion, together with confidence and giver/turn-in/reward beliefs. The
runtime/planner route a verified turn-in target to the shared interaction path.
Focused quest/runtime/planner regression: **119 passed**. M3 live questline
acceptance remains open.

## M3 objective-lifecycle checkpoint (2026-09-18)

Normalized objectives now expose explicit pending/active/blocked/complete/
retryable-failure/terminal-failure state and retain a stable quest-objective
failure-memory key. This never treats attempted actions as progress; graph
readiness remains a separate read-only computation. Focused regression:
**120 passed**. Full M3 live questline acceptance remains open.

## M4.8 traversability-fusion checkpoint (2026-09-18)

World3D traversability now fuses available boundary, free-space violation,
depth, ego-motion mismatch and collision sources with configured-weight
renormalization. Drop risk is an explicit `DANGEROUS` state and structured
traversability/collision/mismatch/cliff events retain their source evidence.
Focused World3D/navigation/stuck regression: **19 passed**. This is offline
evidence; the complete OBS-A through OBS-J matrix remains open. Complete
offline regression after the M3/M4 changes: **926 passed, 2 skipped** in
50.10 seconds.

## M5 danger and reachability checkpoint (2026-09-17)

Navigation now composes decaying danger costs and repeated-failure
reachability confidence. These layers are advisory route/approach gates only:
they do not dispatch input, infer entity meaning, or permanently blacklist a
location. The M5 route, follow/search and live acceptance gates remain open.

## M5 follow checkpoint (2026-09-17)

Group follow now refreshes only from current leader telemetry and maintains a
safe distance band without blindly chasing a stale last position. The movement
controller remains the sole physical control owner. Systematic search-region
coverage and live M5 acceptance still remain open.

## M3/M5 search-coverage checkpoint (2026-09-17)

Quest search areas now have a bounded coverage representation rather than a
repeated centre-point scan. Navigation provides the next cell and the existing
MOVE/visual-search skills retain their respective authorities. Replay and live
coverage validation remain open.

## M6 structured-observability checkpoint (2026-09-17)

The canonical runtime record path now also publishes bounded structured log
entries with correlation and entity identity fields. This is offline
observability infrastructure, not a substitute for the M6 live questline or
induced-failure acceptance suite.

## M6 entity/recovery/replay checkpoint (2026-09-18)

Cross-domain physical target identity is now represented by one normalized
live addon GUID type (`WorldEntityId`), rather than a mix of NPC template IDs,
visual track IDs and raw target fields. Combat-preempts-quest-navigation then
same-subgoal-resume is replay-covered. Death/loading/disconnect/blocking modal
states now retain the goal in an explicit no-input safety checkpoint and only
clear it after a fresh, user-rearmed safe observation. The deterministic
replay harness also emits a versioned replay package containing source hash,
config, deltas, traces and failures. All of this is offline-tested
infrastructure; M6 live acceptance remains open.

## M6 watchdog observability checkpoint (2026-09-18)

Health output now distinguishes a legitimate quiet EventBus from a stalled
queued bus, and independently exposes supervisor, subscriber and input-watchdog
fault evidence. It cannot send input or invent a recovery path. Targeted
regression: **138 passed**; full offline regression: **896 passed, 2 skipped**.
M6 live validation remains required.

## Runtime status-projection extraction (2026-09-18)

The full diagnostic/snapshot assembly was physically moved from
`AutonomousAgent.status()` to `agent/status_projection.py`. It is read-only:
it cannot plan, mutate beliefs, hold an action lease, or dispatch input.
The Engine remains the composition and control authority. Focused
engine/runtime/debug regression: **141 passed**. This is one bounded runtime
extraction; ingestion, dispatch and terminal-result orchestration still need
their own physical modules.

## World-query duplicate removal (2026-09-18)

The retired `_RetiredWorldQuery` body was physically deleted from
`agent/world.py`. `WorldModel.query` and the public compatibility import now
both resolve to the sole implementation in `agent/world_query.py`. Focused
world/query and core-agent regression: **108 passed**. This is a structural
cleanup only; reducers, evidence fusion and snapshot mutation boundaries are
still open and live validation is still required.

## World snapshot-projection extraction (2026-09-18)

`agent/world_snapshot.py` now owns both immutable planner-view construction
and bounded diagnostics construction. It is a read-only projection module;
`WorldModel` remains the sole observation/evidence reducer and does not share
write authority. Focused regression: **128 passed**; complete offline
regression: **902 passed, 2 skipped**. Reducer/evidence policy remains in
`WorldModel` pending a separate extraction and no live gate is claimed by this
structural change.

## M1 freshness-gate extraction (2026-09-17)

The stateful telemetry freshness policy has been extracted into a pure runtime
gate. It decides whether a camera verification may wait, or whether stale
telemetry must trigger the engine's existing fail-safe; only the engine can
stop input or switch mode. Targeted regression: **146 passed**. The broader
engine orchestration split and all live M1 acceptance cases remain open.

## M1 input-scheduler extraction (2026-09-18)

The persistent movement-key lease and watchdog now live in the execution-layer
`InputScheduler`. `InputExecutor` retains the only bindings/PID/focus/F12 and
backend authority, so this is not a second input path. Before regular UI
input, the executor releases the scheduler-owned movement lease. A direct
scheduler test also fixed non-deterministic set iteration: forward/steering
key-down order is now action-order stable for replay. Focused regression:
**101 passed**; live validation remains required.

## M1 progress/stuck event acceptance (2026-09-18)

The engine now turns only movement *phase transitions* into runtime events:
candidate evidence emits `POSSIBLE_STUCK`; independently supported hard-stuck
evidence emits critical `STUCK_DETECTED`. Navigation remains event-bus-free
and input-free; it only returns its evidence assessment. The canonical static
block replay confirms that the two events occur once and in order after fresh
stationary samples. Targeted regression: **23 passed**. M1 live movement,
recovery and preemption acceptance is still required.

## M1 recovery-priority correction (2026-09-18)

The static-block replay revealed that a priority threshold allowed visual
search to bypass a confirmed recovery state. Confirmed recovery now owns the
next bounded step unless live combat, casting or an already-open interaction
UI makes it unsafe. The replay verifies `STOP_AND_OBSERVE` before `BACKWARD`
RECOVER; it does not permit a direct blind recovery pulse. Targeted regression:
**34 passed**. This is not a substitute for live M1-B/C validation.

## M1 recovery resume (2026-09-18)

A successful, verified recovery now re-offers exactly the interrupted REACH
intent through the normal planner. Its map, target and UI/combat preconditions
are checked afresh; retained input state is never resumed. The offline replay
proves the complete bounded path through recovered MOVE. Targeted regression:
**118 passed**. Live M1-B/C is still required.

## Full offline regression (2026-09-18)

After the current WorldModel projection, execution scheduler and M1
progress-event changes, the full suite passed **905 tests** with **2 skipped**
in 48.42 seconds. This is only offline regression evidence; no M0--M6 live
completion gate is claimed.

## M1 modularisation checkpoint (2026-09-20)

Quest dialog selection, fresh mouseover target handoff and quest localisation
are now physically separate read-only proposal policies. Runtime observation
batching is owned by `ObservationIngestion`, and non-addon perception evidence
is applied by `WorldEvidenceReducer` to the sole canonical WorldModel. None of
these modules imports the input backend or owns movement. Focused regressions
passed at **115**, **148**, **132**, **139** and **134** tests respectively;
the combined full offline suite passed **959 tests** with **2 skipped** in
44.32 seconds. Engine supervision/dispatch/terminal-result extraction and all
selected-PID live acceptance gates remain open.

The subsequent dispatch extraction routes every engine command through one
execution-layer `CommandDispatcher`, while `InputExecutor` remains the only
PID/focus/binding/backend authority. Focused regression passed **157 tests**;
the full offline suite passed **963 tests** with **2 skipped** in 34.10
seconds. Active-skill supervision and terminal-result extraction remain open.

Generic terminal assessment, quest terminal effects and INSPECT learning are
now separate modules. The Agent remains the only active-skill finalizer and
no new input/movement authority was introduced. Focused terminal, quest and
inspection regressions passed **107**, **110** and **137** tests; the complete
offline suite passed **966 tests** with **2 skipped** in 24.92 seconds.
Remaining engine work is the active-skill supervision split plus the smaller
navigation/resource/memory terminal-effect tails.

Navigation/recovery terminal effects and procedural/resource memory effects
are now separate modules. Prediction-error construction also shares the
canonical terminal assessment. Focused regressions passed **117** and **135**
tests; the complete offline suite passed **966 tests** with **2 skipped** in
23.09 seconds. `_finish` is now 155 lines (formerly 342); active-skill
supervision and the remaining planner-compatibility bookkeeping are still
open.

The canonical `VerificationEngine`, input-free `RecoveryPlanner`,
`PlanningOrchestrator` and non-dispatching `SkillExecutor` now separate the
remaining core ownership concerns. Verification cannot self-author success;
recovery only selects a bounded intent; planning owns resume/arbitration/plan
revision; SkillExecutor owns preparation, typed domain start and immutable
attempt/prediction construction. The physical command path is still exclusively
`CommandDispatcher -> InputExecutor`. Focused checkpoints passed **147**,
**131**, **121/122** and **151** tests. The latest complete suite passed **1013
tests** with **2 skipped** in 26.22 seconds. Engine source is 1384 lines and
`tick` is 747 lines. Remaining compatibility-tail extraction and all live
M1--M6 acceptance gates stay open.

One observation step for an already-active movement skill is now implemented
by input-free `MovementSkillRunner`. NavigationService remains the only
movement state owner and Agent remains the dispatcher/finalizer. Focused
regression passed **123 tests**; the complete offline suite passed **969
tests** with **2 skipped** in 28.68 seconds. Interaction, combat and loot
runtime supervision remain to be physically separated.

The world-coordinate approach/resume path of an active INTERACT attempt now
lives in input-free `InteractionRuntimeRunner`. Agent alone dispatches returned
commands and finalizes the attempt. Focused regression passed **143 tests**;
the complete offline suite passed **973 tests** with **2 skipped** in 28.91
seconds. Visual interaction approach, combat and loot runtime paths remain.

InteractionRuntimeRunner now covers visual continuation and both approach
startup modes in addition to world-coordinate continuation. Focused regression
passed **148 tests**; the complete offline suite passed **977 tests** with **2
skipped** in 23.80 seconds. Engine source is 1857 lines and tick remains
oversized at 1251 lines, so the runtime breakup gate remains open.

The remaining interaction face/retry states now also belong to
`InteractionRuntimeRunner`; focused regression passed **150 tests** and the
complete suite passed **979 tests** with **2 skipped** in 19.85 seconds.
`CombatRuntimeRunner` subsequently took ownership of combat approach/resume,
local reposition and rotation projection; focused regression passed **118
tests**, with **984 passed, 2 skipped** overall in 24.52 seconds.
`LootRuntimeRunner` now owns verification and the corpse approach/resume FSM;
focused regression passed **115 tests**, with **990 passed, 2 skipped** overall
in 51.77 seconds. All three runners are input-free and cannot finalize active
skills. Engine source is now 1713 lines and `tick` is 1104 lines. Planning and
goal orchestration extraction plus every selected-PID M1--M6 live gate remain
open.

## M3/M6 adaptive quest acceptance checkpoint (2026-09-20)

The production agent now has a deterministic offline end-to-end acceptance
environment that reacts to the Planner/SkillExecutor's actual decisions
instead of replaying a fixed input sequence. One high-level campaign goal must
produce accept, movement, combat, loot/objective credit, return, turn-in and
follow-up discovery. The environment intentionally drops the first interaction
result, requiring a bounded verified failure and retry before it exposes the
quest dialog. The suite passed **1038 tests** with **2 optional skips** in
63.51 seconds at this checkpoint; after World3D compute-backend integration it
passes **1039 tests, 2 skipped** in 96.41 seconds. This closes the named offline
M3/M6 questline scenario only;
selected-PID live validation and the M6 release gate remain open.

## Quest-domain extraction and World3D compute checkpoint (2026-09-20)

The quest proposal domain is now a separate input-free policy module composed
by the single high-level Planner; `planner.py` fell from 1323 to 882 lines and
does not embed a second quest brain. The OpenCV capability-gated backend is
also shared by World3D V2/V3 luminance/downsample preprocessing, with an exact
historical CPU fallback and runtime diagnostics. The complete suite passes
**1040 tests, 2 skipped** in 218.76 seconds. These are structural/offline
results; selected-PID live gates remain open.

Availability/cooldown filtering and explainable utility ranking now live in
the input-free `ProposalRanker`; candidate composition remains with the single
Planner. `planner.py` is now 851 lines. Latest complete regression: **1043
passed, 2 skipped** in 38.73 seconds.

The active visual-search and visual-approach state machines are now composed
through the input-free `VisualRuntimeRunner`; Agent remains the sole dispatcher
and finalizer. Engine is 1289 lines and `tick` 648 lines. Focused regression
passed 155 tests; after the mmap route-source increment the full suite passes
**1056 tests, 2 skipped** in 52.64 seconds.

Target reacquisition, quest-target matching, combat/defend/escape and corpse
loot proposal generation have now been extracted into the input-free
`CombatPlanningPolicy`. It is a composed proposal source, not a second Planner,
TargetManager, CombatController, SkillExecutor or movement authority. Static
architecture guards reject input, dispatch, WorldModel ingestion, active-skill
or movement-controller ownership in this module. `planner.py` is **666 lines**;
the policy is **207 lines**. Direct policy tests cover quest-scoped target
credit, unrelated-hostile rejection, active self-defence, confirmed corpse
loot and exact-GUID reacquisition. Latest complete offline regression:
**1063 passed, 2 skipped in 44.46 seconds**. Live validation remains open.

Visual-track eligibility, information-gain ordering projection, map-marker
inspection and bounded per-group attention are now physically separated into
the input-free `VisualInspectionPolicy`. It consumes the canonical
`ActivePerception` scores and produces INSPECT proposals only; it cannot turn
appearance into semantics, mutate WorldModel, select the global winner or
dispatch input. `planner.py` is now **509 lines**. Focused regression passed
**146 tests** and the complete offline suite passed **1064 tests, 2 skipped in
42.37 seconds**. Live validation remains open.

The remaining distant-cue/local-search/map-fallback proposal block is now an
input-free `VisualSearchPlanningPolicy`. It returns immutable proposals and
explicit camera-search bookkeeping values to the single Planner; it cannot
operate the camera, movement controller, active skill, dispatcher or
WorldModel. `planner.py` is now **327 lines**. Focused regression passed **161
tests** and the complete suite passed **1065 tests, 2 skipped in 33.36
seconds**. Live validation remains open.

The World Map scan-session and TDB-last-resort lifecycle is now physically
extracted from Planner into the composed `WorldMapFallbackPolicy`. It owns one
bounded search-state object and verified terminal bookkeeping, but cannot rank
the global proposal set, dispatch input, own movement/targeting, or mutate the
WorldModel. Planner remains the sole proposal composer/ranker and is now 298
lines. The full offline suite passes **1078 tests, 2 skipped in 41.74 seconds**;
selected-PID search-order evidence remains open.

Decoded FAST/full addon projection is now physically extracted into the
stateless `WorldAddonReducer`. It writes only the supplied canonical WorldModel
and composes the existing event/entity/UI reducers; it owns no second state or
query surface. WorldModel is now 1175 lines. Direct same-GUID merge,
different-GUID isolation and full quest/event projection tests are green; the
complete suite passes **1081 tests, 2 skipped in 32.48 seconds**. Live FAST
consumer-rate validation remains open.

Canonical query-state rebuilding is now delegated to the stateless
`WorldStateProjector`: projection merge, camera projection, transient anchor
retention, exact-GUID semantics and visual-track association no longer live in
the WorldModel monolith. The model remains the only state owner and is now 1072
lines. Focused regression passed 192 tests; complete regression remains **1081
passed, 2 skipped in 39.33 seconds**. Live identity/track association is open.

Planner-side mutation of remembered map locations has also been removed.
Runtime validation is now a pure provenance/session/scan-time check inside
`QuestLocationPlanningPolicy`; it does not add derived fields to WorldModel.
A direct immutability regression is included. Complete offline regression:
**1066 passed, 2 skipped in 34.42 seconds**.

## Active-skill supervision extraction checkpoint (2026-09-21)

Already-active TARGET, INTERACT/TALK, COMBAT/DEFEND, LOOT and generic M0 skill
supervision is now routed by the composed `ActiveSkillSupervisor`. The module
returns commands, movement-lane intent, diagnostics and typed terminal data; it
cannot dispatch input, create or finish an `ActiveSkillRuntime`, ingest the
WorldModel or become a second execution authority. Agent remains the only
physical dispatcher/finalizer. `engine.py` is reduced from 1206 to **1000
lines**, and `tick()` from 642 to **428 lines**. Direct supervision and static
authority-boundary tests are included. Complete offline regression: **1109
passed, 3 skipped in 45.72 seconds**. Selected-PID live acceptance remains
open and the release state remains `OFFLINE_PARTIAL`.

The selected-action start boundary is now composed by the non-dispatching
`ActionLaunchCoordinator`: empty-start eligibility, typed immediate-result
projection and dispatch-lane selection no longer live in `tick()`. It delegates
attempt installation to the canonical `SkillExecutor`/`ActiveSkillRuntime` and
cannot dispatch or finalize. `ActiveSkillSupervisor` now also routes movement
and visual observations to their existing domain runners, so every already-
active skill has one supervision entry point without merging the underlying
Movement, Visual, Interaction, Combat or Loot controllers. Agent remains the
sole physical dispatcher/finalizer. `engine.py` is now **907 lines** and
`tick()` **263 lines**; direct/affected regression passed **204 tests**, and the
complete suite passed **1115 tests, 3 skipped in 44.21 seconds**. Live gates
remain open.

Confirmed corpse-event and live mouseover/cursor anchor projection now lives in
the stateless `WorldAnchorReducer`. It writes only the supplied canonical
WorldModel and preserves the exact GUID, cursor-freshness, map-surface,
same-frame association and looted-corpse tombstone contracts. The old
WorldModel methods remain thin compatibility delegations. WorldModel is reduced
from 1072 to **923 lines**; focused anchor/loot/identity regression passed **166
tests**, and the complete suite passed **1116 tests, 3 skipped in 38.39
seconds**. Live mouseover/track association evidence remains open.

DESIGN-073 command acknowledgement is now explicit and bounded. Every nonempty
canonical dispatch records `CREATED -> QUEUED -> DISPATCHED` followed by either
`LOCAL_ACK` or `FAILED`; queued work can be `CANCELLED`, receipts are correlated
to the active `action_id`, and status diagnostics expose only the bounded recent
set. `LOCAL_ACK` proves backend return only and carries `world_success: null`,
so it cannot satisfy a skill verifier. Focused execution/agent regression passed
**160 tests** and the complete suite passed **1120 tests, 3 skipped in 47.68
seconds**. Selected-PID acknowledgement latency/failure evidence remains open.

DESIGN-077 now has one explicit state-invalidation matrix and an Agent runtime
integration for `OBJECTIVE_CHANGED`, `LOADING`, `TELEPORT`, `MAP_CONTEXT`,
`DEATH`, `PHASE`, `FLOOR` and `VEHICLE`. Objective changes invalidate only
derived quest selection/search commitment. World-context changes cancel active
work through the canonical lifecycle, release the movement lease through the
single dispatcher, reset Navigation/Camera/commitment/map search and remove
only transient screen/visual projections. The policy has no executor or input
dependency. Direct matrix and map-change integration tests are green; complete
regression passed **1126 tests, 3 skipped in 45.01 seconds**. Real selected-PID
transition evidence remains live-open.

The shared `FaceController` now satisfies DESIGN-024/V4-029 as a complete
offline lifecycle: `begin`, target-error estimation, bounded turn projection,
alignment query, `tick`, timeout and `cancel`. Its former deadzone ordering was
anti-hysteretic; alignment now enters through a narrow band and exits through a
wider band, preventing correction chatter. NavigationService remains its only
owner and it returns commands without dispatching. Focused Interact/Combat/
Navigation regression passed **120 tests**; complete regression passed **1128
tests, 3 skipped in 32.62 seconds**. Live facing accuracy remains open.

V5 M1.2 EventBus is now offline complete. Its queue, history, subscriber map,
dedupe set and diagnostics are protected by one re-entrant lock; publish,
subscribe/unsubscribe, critical publish and recent-event queries retain bounded
backpressure, exception isolation, critical preservation and low-value
coalescing. A parallel 8-producer/800-event regression proves per-producer
ordering and concurrent ID deduplication. Focused runtime regression passed
**136 tests**; complete regression passed **1129 tests, 3 skipped in 35.32
seconds**. Sustained selected-PID producer load remains live-open.

V5 M1.3 WorldModel write attribution is now offline complete. The existing
designated addon/event/entity/UI/evidence reducers remain the only observation
writers; the stateless `WorldSectionUpdateTracker` records the latest
observation ID, received monotonic time, source timestamp, source and canonical
model revision for every affected Player/Target/Entity/Combat/Navigation/
Quest/Interaction/UI/Map/Environment/Recovery section. Planning snapshots expose
immutable attribution and diagnostics return isolated copies. Focused WorldModel
regression passed **40 tests**; complete regression passed **1133 tests, 3
skipped in 32.85 seconds**. Live attribution validation remains open.

V5 M1.4 now has a complete normalized WorldState projection beside the existing
compatible snapshot/query API. It exposes immutable `Version`, `UpdatedAt`,
`PlayerState`, `TargetState`, `EntityMap`, `CombatState`, `NavigationState`,
`QuestState`, `InteractionState`, `UIState`, `MapState`, `EnvironmentState` and
`RecoveryState`. Raw visual candidates remain `BestClass=UNKNOWN` until their
semantic belief is explicitly `CONFIRMED`; Entity evidence references the
World3D section observation rather than an unrelated latest addon packet.
Focused WorldModel regression passed **133 tests**; complete regression passed
**1137 tests, 3 skipped in 30.48 seconds**. Selected-PID field accuracy remains
live-open.
