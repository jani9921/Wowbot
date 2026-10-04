# Test report

## 2026-09-24 INV-01 through INV-20 traceability

Latest complete regression: **1714 passed, 4 skipped in 44.24 seconds**.
All twenty global invariants now have an exact ID, named owner, and existing
enforcement evidence in a runtime-neutral registry. New behavioral tests prove
finite retry escalation and finite local visual search; the registry test
prevents any invariant from silently disappearing or pointing to missing
evidence. The registry itself owns no control authority. No live input was
sent.

## 2026-09-24 QuestAttemptMemory single owner

Latest complete regression: **1711 passed, 4 skipped in 70.57 seconds**.
`QuestAttemptMemory` now owns both bounded execution-failure suppression and
quest credit/strategy attempt history. Planner/QuestDomain and QuestRuntime
share the exact same production instance, including across goal-runtime
replacement; session reset clears rather than duplicates it. The engine size
gate remains green at 899 lines. DESIGN-078 remains PARTIAL only for the
remaining broad sensor/procedure/rejection persistence in AgentMemory. No live
client input was sent.

## 2026-09-24 EpisodeMemory extraction

Latest complete regression: **1707 passed, 4 skipped in 67.49 seconds**.
Episode start/step/finish/query is now owned by a dedicated `EpisodeMemory`
component using the existing shared SQLite transaction. `AgentMemory` keeps
only compatibility delegation; successful pattern promotion remains explicit
and one-shot. DESIGN-078 stays PARTIAL until quest attempts have one named
owner and the remaining broad stores are separated. No live input was sent.

## 2026-09-24 typed common evidence model

Latest complete regression: **1706 passed, 4 skipped in 71.90 seconds**.
Evidence, Belief, ContradictionRecord, and WorldRelation now have a dedicated
typed value-object module. Evidence exposes provenance references and temporal
confidence operations; WorldModel/WorldQuery offer a typed Belief projection
without breaking legacy dict callers. Observation projects sensor/type/
coordinate-space metadata. `world.py` remains below its size gate at 793
lines. No live client input was sent.

## 2026-09-24 arrival evidence completion

Latest complete regression: **1702 passed, 4 skipped in 59.26 seconds**.
The production arrival path now emits exact-marker minimap convergence and
explicit expected map/instance transition evidence in addition to distance,
World3D scale, UI-readiness, and quest progress. Wrong/stale/receding markers
and incidental map changes remain non-evidence. A verified expected transition
can complete the persistent REACH request before ordinary map-mismatch failure.
No live client input was sent; calibration remains live-open.

## 2026-09-24 SPEAK and KILL objective orchestration

Latest complete regression: **1698 passed, 4 skipped in 44.41 seconds**.
Named input-free SPEAK/KILL flow policies now connect objective-area arrival to
bounded local entity search and exact addon-backed identity handoff. A KILL
search rejects friendly/wrong hover evidence; valid targets pass to the sole
CombatPolicy/CombatSkill authority, while SPEAK passes to the existing
TALK/dialog chain. Death/action success still cannot fabricate quest credit.
No live input was sent; selected-PID validation remains open.

## 2026-09-24 quest world-object interaction flow

Latest complete regression: **1695 passed, 4 skipped in 46.84 seconds**.
The production quest path now composes location arrival, bounded local
UNKNOWN-cue search and visual approach, fresh addon-mouseover identity,
canonical `OBJECT_USE`, and quest-credit verification. Explicit object/item
IDs take precedence over tooltip text, so a visually plausible or similarly
named object cannot replace a declared quest object. GUID-less world objects
are supported without treating CV as ground truth. No live client input was
sent; selected-PID validation remains open.

## 2026-09-24 combat errors, gossip scoring and quest strategy history

Latest complete regression: **1690 passed, 4 skipped in 45.47 seconds**.
The canonical combat-error classifier is now consumed by both production
combat paths with bounded history; one missing-target frame remains diagnostic
until temporally corroborated, preventing commitment loss and unrelated-corpse
handoff. Multi-offer gossip selection can use exact objective/quest evidence
but remains fail-closed for fuzzy or tied matches. `QuestStrategyHistory` now
provides one bounded quest-local attempt/action-success/credit/confidence
ledger shared by no-credit escalation and collect-strategy adaptation.
`UseItemSkill` now exposes the complete design contract and typed range gate;
goal replacement atomically rebinds quest terminal processing to the new
QuestRuntime instead of retaining the prior goal's instance. Extra Action now
has one canonical, fail-closed handler contract, and `QuestAcceptFlow` prevents
an explicit quest goal from accepting a different open offer while preserving
the verified fast-lane UI path. No live client input was sent; selected-PID
M1-M6 validation remains open. A mode-guarded `FieldTurnInSkill` now owns
field completion while reusing the canonical dialog executor. After a verified
TRAVEL/REACH_AREA arrival without quest credit, the planner now performs one
bounded entrance/NPC/object/trigger localization instead of repeating the same
MOVE indefinitely.
Arbitrary quest escort entities now use the canonical persistent FOLLOW
controller with distance-band holding, bounded short-occlusion tolerance,
reacquisition and quest-credit verification; this is no longer limited to
party-leader telemetry.

## 2026-09-24 Planner DecisionFingerprint anti-loop

Latest complete regression: **1650 passed, 4 skipped in 47.18 seconds**.
The production Planner now owns an explicit, input-free
`DecisionFingerprintGuard`. After retry exhaustion, the exact same
decision+target+strategy is suppressed until relevant semantic evidence
changes; transport frame/timestamp churn cannot unlock it. Alternate targets
or strategies remain eligible. Focused Planner/runtime/terminal regression:
**51 passed**. This closes DESIGN-020 offline only.

## 2026-09-24 runtime observation/perception breakup

Latest complete regression: **1644 passed, 4 skipped in 57.27 seconds**.
The oversized observation/perception middle of `AgentRuntime.step()` was
extracted into `runtime_perception_phase.py` and
`runtime_observation_phase.py`. The phases retain passive sensor/cache and
evidence projection responsibilities but have no dispatcher, input backend,
planner construction, skill executor or terminal-result authority. Runtime
orchestration, selected-PID safety, replay recording and the single agent
ingest/plan/dispatch/finalize path are unchanged. `runtime.py` is now 542 lines
(981 before the breakup series). Focused runtime/scheduler/World3D/memory
regression: **49 passed**. This closes V4-095 offline only; no live input was
sent and selected-PID M1–M6 gates remain open.

## 2026-09-23 coverage closure: navigation context/transition and WorldModel breakup

Latest complete regression: **1643 passed, 4 skipped in 46.89 seconds**.
`NavigationSituationPolicy` now consumes the previously diagnostic-only
navigation context and transition resolver in the production Planner path.
It annotates route expectation, holds stale routes during loading/map
transition, performs one bounded `SEARCH_ENTRANCE`, and escalates exhausted
search to map relocalization. A regression prevents the map-near heuristic
from hijacking ordinary user MOVE goals. WorldModel execution-trace projection
and prediction lifecycle were extracted into authority-neutral components;
`world.py` fell from 952 to 827 lines. Required documentation, dead-code audit
and offline/live validation vocabulary now have automated contract checks.
Retail entrance traversal and the deferred MMAPS/VMAPS/FAST-Hz block remain
live-open.

## 2026-09-23 quest-area arrival evidence

Latest complete regression: **1601 passed, 3 skipped in 62.00 seconds**.
Focused arrival/navigation regression: **52 passed**. Production REACH now
derives quest-area arrival only from the scoped quest/objective's authoritative
progress. It rejects disappearance, regression, changed requirements and
unrelated objective changes. This semantic success finishes the full request
instead of being mistaken for arrival at one intermediate mmap waypoint.
DESIGN-031 remains PARTIAL for minimap, interaction-readiness and map-transition
evidence producers.

## 2026-09-23 production visual arrival evidence

Latest complete regression: **1595 passed, 3 skipped in 50.32 seconds**.
Focused navigation/evidence suite: **41 passed**. Production REACH now
generates weak bbox-growth evidence via ArrivalEvidence from its destination
GUID, a fresh mouseover anchor and distinct fresh World3D track samples.
Stable camera yaw and decreasing target distance are required. Wrong GUID,
occlusion, stale/repeated frames, camera rotation and receding geometry are
negative regressions. Weak scale evidence alone cannot finish REACH.
The unscoped state arrival_evidence dictionary no longer bypasses this
producer. Other arrival modalities remain open in DESIGN-031.

## 2026-09-23 arrival envelope and evidence expiry

Latest complete suite: **1588 passed, 3 skipped in 55.34 seconds**.
Focused navigation/controller suite: **39 passed**.
REACH now honors the explicit route arrival_radius when stop_distance is
absent. A one-yard route envelope no longer uses the default 4.5-yard stop.
Arrival hysteresis retains the wider exit envelope only with current usable
evidence; absent evidence returns UNKNOWN. Negative, boolean and nonfinite
distance contracts and nonfinite semantic scores cannot confirm arrival.
Seven regression cases exercise these production-controller and verifier
boundaries. DESIGN-031 remains PARTIAL pending sensor evidence production.

## 2026-09-23 quest-credit regression audit

Latest complete regression: **1581 passed, 3 skipped in 65.96 seconds**.
Seven new cases cover decreasing objective counts, changed requirements,
late objective appearance, absent/new stage metadata, retained turn-in
events and external mutation of a captured baseline. These must not produce
false quest credit. Related focused tests: **24 passed**.

Source inspection also corrected DESIGN-031 to PARTIAL: optional visual
arrival inputs have no production producer yet. Passing verifier unit tests
does not establish that end-to-end wiring.

## Latest offline regression

2026-09-16: `776 passed, 3 skipped` across the Python suite after the M0/M1
runtime, event, dialog, supervisor, turn-in, stage-transition, explicit
reward-selection, Extra Action, and canonical targeted-quest-item changes.

Focused regression after removing the duplicate dialog path:

`python -m pytest -q tests/test_m1_quest_dialog_skill.py tests/test_m0_dispatch.py tests/test_agent_runtime.py tests/test_m0_acceptance_matrix.py`

The current complete suite result is `776 passed, 3 skipped`; it includes
reward-row policy, exact-row validation, Extra Action FAST transport, canonical
quest tool/item checks, and the Lua addon mock-load test.

Skipped tests are environment/optional-fixture cases.  Offline tests do not
authorize input and do not replace a selected-PID live acceptance result.

## Latest V5 M1--M6 regression

2026-09-22: after the detailed M4/M5/M6 coverage audit and the dynamic
obstacle, temporal cliff-confirmation and evidence-only terrain-transition
contracts, `python -m pytest -q` completed with **1514 passed, 3 skipped in
47.34 seconds**. Focused audits were World3D/M4 **120 passed, 1 skipped**, M5
**53 passed**, M6 integration **62 passed**, and M1 authority boundaries **89
passed**. This is offline evidence only; M6 release remains blocked on the
selected-PID live questline, live F01--F15 and long-run performance evidence.

2026-09-20: `C:\Python313\python.exe -m pytest -q` completed with
**1038 passed, 2 skipped in 63.51 seconds**. This includes the adaptive,
Planner/SkillExecutor-driven M3/M6 quest scenario and its induced bounded
interaction retry. The result is offline evidence only; it does not close any
selected-PID live release gate.

After extending `OpenCvComputeBackend` to the shared World3D V2/V3 grayscale
and downsample stage, the complete result is **1039 passed, 2 skipped in 96.41
seconds**. CUDA selection remains capability-gated; this machine's OpenCV build
correctly reports CPU fallback.

After extracting `QuestDomain` into its own non-input-owning policy module and
adding the corresponding architecture guard, the complete result is **1040
passed, 2 skipped in 218.76 seconds**. The unusually slow duration was observed
in the early SQLite/runtime test group; no failure or hang occurred.

After extracting the pure `ProposalRanker`, the complete suite is **1043
passed, 2 skipped in 38.73 seconds**.

After extracting active visual search/approach stepping into the input-free
`VisualRuntimeRunner`, the complete suite is **1047 passed, 2 skipped in 43.76
seconds**.

After adding the read-only TrinityCore mmap route source, its same-instance
`WORLD_YARDS` gates and canonical NavigationService handoff, the complete
suite is **1056 passed, 2 skipped in 52.64 seconds** (2026-09-21).

After extracting target reacquisition, combat/defend/escape and confirmed
corpse-loot proposals into the input-free `CombatPlanningPolicy`, direct policy
tests and static single-authority guards were added. The complete suite is
**1063 passed, 2 skipped in 44.46 seconds** (2026-09-21). This is offline
evidence only; no selected-PID/live acceptance case was run or closed.

After extracting UNKNOWN-track inspection proposal construction into the
input-free `VisualInspectionPolicy`, the focused perception/planner boundary
suite passed 146 tests. The complete suite is **1064 passed, 2 skipped in
42.37 seconds** (2026-09-21). This remains offline evidence only.

After extracting distant-cue and local-search/map-fallback proposal policy into
the non-executing `VisualSearchPlanningPolicy`, the complete suite is **1065
passed, 2 skipped in 33.36 seconds** (2026-09-21). No live run was performed.

After removing Planner-side mutation from runtime map-location validation and
adding a direct WorldModel immutability regression, the complete suite is
**1066 passed, 2 skipped in 34.42 seconds** (2026-09-21).

After throttling only the large diagnostic World snapshot (not control state)
and adding `WORLD3D_LOCAL_VIEW` to derived-CV consolidation, the complete
suite is **1068 passed, 2 skipped in 37.89 seconds** (2026-09-21). Live FAST
consumer-rate validation remains open.

After adding the model-neutral, UNKNOWN-first learned World3D detector adapter,
strict YOLO dataset audit/training gate and additive V2 integration, the focused
learned-detector + World3D V2/pipeline suite passed **30 tests** (2026-09-21).
The supplied Wowpedia dataset failed the new audit, so this is adapter/contract
evidence only and does not claim a trained or live-validated model.
The complete suite then passed **1073 tests, 2 skipped in 38.66 seconds**.
An attempted one-epoch launch against the supplied dataset was correctly
refused before Ultralytics training because of duplicate stems, full-frame
label collapse, absent test split and train/validation leakage.

## 2026-09-23 World Map context and parent-level recovery

Addon map hierarchy export, compact FAST transport, WorldModel reduction,
read-only query projection, canonical resolver policy, bounded parent-map
input and addon-grounded verification passed focused suites (52 + 156 tests)
and the complete suite: **1554 passed, 3 skipped in 54.45 seconds**. No live
client or input was used; selected-PID World Map behavior remains open.

## 2026-09-23 canonical arrival verifier

The canonical evidence-fused arrival gate and its production
`ReachMovementController` wiring passed **32 focused tests**. The complete
offline suite passed **1570 tests, 3 skipped in 67.47 seconds**. This is
offline evidence only and does not close selected-PID arrival calibration.

The subsequent typed quest-progress closure passed **34 focused tests** and
the complete suite passed **1574 tests, 3 skipped in 83.49 seconds**. It adds
explicit quest-start and ongoing-progress states in addition to the design's
required output set; no live test was claimed.

After extracting the complete World Map scan-session/TDB-last-resort lifecycle
and its verified terminal bookkeeping into the input-free
`WorldMapFallbackPolicy`, targeted map/planner/runtime regressions passed
**208** and **203** tests. The complete suite passed **1078 tests, 2 skipped in
41.74 seconds** (2026-09-21). This is offline architecture/behavior evidence;
selected-PID search-order validation remains open.

After extracting decoded FAST/full addon-state projection into the stateless
`WorldAddonReducer`, direct reducer and WorldModel/runtime regressions passed
**172 tests**. The complete suite passed **1081 tests, 2 skipped in 32.48
seconds** (2026-09-21). The reducer owns no independent state and preserves the
single WorldModel writer; live FAST-rate evidence remains open.

After extracting source merge, transient-anchor pruning and confirmed
identity-to-UNKNOWN-track projection into the stateless `WorldStateProjector`,
the focused WorldModel/runtime/anchor suite passed **192 tests**. The complete
suite remained **1081 passed, 2 skipped in 39.33 seconds** (2026-09-21).
WorldModel is now 1072 lines; live association evidence remains open.

2026-09-23: after integrating World3D long-gap visual re-identification,
scene-quality and scene-change evidence, semantic fusion with
hysteresis/freshness, lifecycle and failure-feedback contracts,
context-aware scheduling profiles, and the graphical replay renderer, the
complete offline suite passed **1535 tests, 3 skipped in 65.44 seconds**. The
skipped cases and all selected-PID Retail acceptance rows remain open; no
 client input was sent.

## 2026-09-24 golden replay catalog and soft-target evidence

The seven design-required canonical replay scenarios now have typed,
semantically validated JSONL fixtures and deterministic comparison coverage.
Retail action targeting is carried on both FULL and FAST addon lanes, reduced
into the canonical WorldModel and exposed as read-only candidate evidence. It
cannot confirm identity/role, replace the selected target, create a Proposal or
dispatch input. Focused golden/addon/transport/world tests passed **49 tests**.
No selected-PID client input was used; Retail soft-unit availability and every
live acceptance gate remain open.

The previously absent DEFEND/WAIT objective execution path now has a bounded,
stationary `WAIT_EVENT` skill with the five design phases, authoritative quest
progress verification, combat-interrupt handoff and timeout reevaluation.
Focused skill/dispatcher/executor/supervision/architecture tests passed **163
tests**. No scripted Retail event was live-run, so live acceptance remains
open.

The runtime backpressure contract now has one shared implementation for
latest-state coalescing, stale dropping, bounded queues and critical-event
priority admission. The production sensor mailbox and EventBus both delegate
to it. Focused sensor/EventBus/backpressure tests passed **55 tests**.

The named runtime cadence contract is now production-wired for capture,
World3D, minimap, World Map and targeted OCR, while the planner remains
event-driven and the FAST movement consumer remains ungated. Focused scheduler,
runtime, perception, sensor and World3D regressions passed **148 tests** with
one optional fixture skip. Selected-PID rate calibration is still open.

## 2026-09-24 perception component ownership

The named `PerceptionPipeline` and World3D/minimap/World Map component seams
are now production-wired without creating duplicate detector or track identity
authorities. World3D tracker lifecycle querying/invalidation, minimap shared
temporal association, non-fatal cue disappearance, and map context/mouseover
normalization have direct contract coverage. Focused perception regressions
passed **38 tests with 1 optional fixture skip**; the complete suite passed
**1722 tests, 4 skipped in 57.86 seconds**. No client input was sent and World
Map selected-PID behavior remains a live acceptance gate.

## 2026-09-24 uniform skill lifecycle contract

All canonical M0 skill dispatch now crosses a stateless, runtime-checkable
`SkillBaseContract` implementing start/tick/cancel/enter/exit/snapshot. The
adapter owns no mutable lifecycle state and cannot finalize an attempt;
`ActiveSkillRuntime` remains the sole authority. Focused lifecycle and routing
tests passed **22 tests** and the complete suite passed **1724 tests, 4 skipped
in 56.00 seconds**. No live action was dispatched.

## 2026-09-24 canonical global and local navigators

The already-live global and local planning implementations now carry the
design's canonical `GlobalNavigator`/`LocalNavigator` names and method
contracts. Legacy planner imports are aliases to the same classes, not parallel
controllers; `NavigationService` instantiates the canonical types. Focused
route/local/service tests passed **16 tests** and the complete suite passed
**1727 tests, 4 skipped in 75.33 seconds**. This is offline structural and
behavioral evidence; mmap/vmap movement rate issues remain separately logged
for later live investigation.

## 2026-09-24 World Map resolver contract

The production map-open perception lane now uses the canonical World Map
resolver. Its full pure contract covers context, quest/turn-in/parent evidence,
mouseover normalization and bounded wrong-zoom requests without dispatching
input. Focused component/map regressions passed **33 tests**; the complete
suite passed **1728 tests, 4 skipped in 100.59 seconds**. Selected-PID timing
and marker calibration remain live acceptance work.

## 2026-09-24 Cross-View resolver

The runtime now uses a single `CrossViewResolver` over the existing conservative
association logic. It links map/minimap/World3D/tooltip/target evidence,
downgrades identity conflicts explicitly and selects a best identity without
turning appearance similarity into fact. Focused tests passed **39 tests** and
the complete suite passed **1731 tests, 4 skipped in 60.56 seconds**. No live
client or input was used.

## 2026-09-24 rejection-memory ownership

Visual zero-information suppression, contradiction, expiry, query and
reliability now belong to a dedicated durable `RejectionMemory`; the broad
`AgentMemory` API delegates without changing the database schema. Focused
rejection/quest tests passed **16 tests** and the complete suite passed **1733
tests, 4 skipped in 74.30 seconds**. Sensor/procedure trial ownership remains
open, so DESIGN-078 is still correctly marked PARTIAL.

## 2026-09-24 memory ownership completion

The final procedure/sensor empirical store was extracted into `LearningMemory`,
which now owns trial recording, profiles, precision/recall/confusion and drift,
reliability, expiry and consolidation. Together with the dedicated
`RejectionMemory` and the five design memory owners, `AgentMemory` is now a
compatibility facade over the unchanged durable schema. Focused owner/core
tests passed **110 tests** and the complete suite passed **1735 tests, 4
skipped in 86.93 seconds**. DESIGN-078 is now offline verified; live validation
remains separately tracked.
