# Functional Design Specification reconciliation

Date: 2026-09-16  
Sources: `wow_agent_FINAL_M0_M1_master_prompt_v4.txt` (implementation
authority) and `wow_agent_complete_functional_design_spec.txt` (functional
design reference, sections 0–102).

This is a coverage and ownership ledger.  It is deliberately **not** a claim
that M0, M1, or a live quest flow is complete.  The detailed legacy master
coverage remains in `MASTER_COVERAGE.md`; the M0/M1 migration audit remains in
`M0_M1_V4_AUDIT.md`.

## Precedence and non-negotiable reconciliation

1. V4 is the active implementation and acceptance authority for the current
   M0/M1 delivery.  The functional design describes what each component means
   and who owns it; it does not silently replace V4 gates.
2. The adopted master invariant **DETECTION != RECOGNITION** takes precedence
   over the shorthand candidate labels in Functional Design §7/§8.  Raw World3D
   and minimap detectors emit UNKNOWN observations and appearance evidence.
   `NPC`, `HOSTILE`, `QUEST_BADGE`, and similar labels may only exist as an
   evidence-backed belief/hypothesis or telemetry-confirmed relation, never as
   a direct CV fact.
3. `ActiveSkillRuntime` is the single running-skill authority.  Legacy
   `engine.pending`, `AutonomousLoop.commitment`, and
   `SkillLifecycleController` are compatibility/observability paths only until
   their remaining call sites are retired; no new execution state may be added
   to them.
4. `NavigationService` is the canonical navigation boundary.  The persistent
   movement controller, visual approach, and visual seek remain bounded
   implementation capabilities beneath an active skill; none may start an
   independent navigation job.
5. The only authoritative confirmation of a quest objective is
   `QuestProgressVerifier`.  Input dispatch acknowledgement and local action
   verification are not quest credit.
6. Only screen capture, addon telemetry, and normal OS input are allowed.  The
   selected PID and selected bindings cache remain mandatory; no guessed keys,
   memory inspection, injection, or secret-value bypass exists.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `ACTIVE_OFFLINE` | Active code path with deterministic/offline test coverage. |
| `ADAPTER_OFFLINE` | Real capability exists behind a temporary adapter; ownership migration is incomplete. |
| `PLANNED` | Requirement is tracked but no canonical implementation is claimed. |
| `LIVE_REQUIRED` | Offline work exists, but a user-operated live client run is still required. |

## Section coverage

| Functional design sections | Intended owner | Current disposition |
| --- | --- | --- |
| 0–4: principles, decomposition, data contracts, events | `runtime.contracts`, `ActiveSkillRuntime`, `EventBus` | `ACTIVE_OFFLINE`: typed intents/results/statuses and a thread-safe bounded EventBus provide priority, event IDs/idempotency, correlation IDs, critical preservation, coalescing, recent history and isolated subscribers. Real sustained producer-load behavior remains `LIVE_REQUIRED`. |
| 5–6: capture, SensorHub, perception orchestration | `AgentRuntime`, `sensor`, `PerceptionWorker` | `ADAPTER_OFFLINE`: bounded/latest sensor paths and perception lanes exist. A single public `SensorHub`/`PerceptionPipeline` façade and explicit sensor failure contracts remain `PLANNED`. |
| 7–10: World3D, minimap, map, cross-view | `vision.*`, `WorldModel` evidence | `ADAPTER_OFFLINE` + `LIVE_REQUIRED`: candidate/tracking/unknown-first evidence, inner-circle minimap geometry and map adapters exist. Canonical resolver façades and live cross-view association remain `PLANNED`. |
| 11–14: WorldModel, query, player/UI state | `WorldModel`, designated reducers, `WorldSectionUpdateTracker`, `WorldStateContract`, `WorldQuery` | `ACTIVE_OFFLINE`: the model/query boundary is read-only, every accepted observation is attributable per major section, and planning exposes the complete immutable M1.4 normalized WorldState contract. EntityMap preserves UNKNOWN-first semantics. Selected-PID field and UI-context transition validation remains `LIVE_REQUIRED`. |
| 15–17: quest normalization, classifier, locator | `QuestModel`, `QuestExecutionRuntime`, `ObjectiveLocator` | `ACTIVE_OFFLINE`: stable primary quest/objective, conservative classifier and ordered locator are present. Full mechanic/locale coverage and concrete minimap/map resolver use are `PLANNED`. |
| 18–22: goals, supervisor, planner, active skills | `GoalManager`, `Supervisor`, `Planner`, `ActiveSkillRuntime` | `ACTIVE_OFFLINE` for the Supervisor FSM: all required states have explicit immutable contracts, evidence-backed enter/exit gates and a tested preemption matrix. Active-skill ownership remains singular and a combat interrupt can resume one still-valid intent once. Planner decomposition and remaining legacy lifecycle/commitment retirement continue separately. Selected-PID transitions remain `LIVE_REQUIRED`. |
| 23–26: target, face, movement, navigation | `TargetSkill`, `FaceController`, `NavigationService` | `ACTIVE_OFFLINE`: target, a first-class shared hysteretic facing lifecycle and canonical navigation service are migrated. Selected-PID facing accuracy and remaining navigation recovery live evidence are `LIVE_REQUIRED`. |
| 27–36: route/local navigation, progress/stuck/recovery/transition/search/camera | `NavigationService`, `SearchSkill`, `CameraController` | `ADAPTER_OFFLINE`: persistent progress/stuck belief, bounded camera search and visual seek exist. Route ownership, transition resolver, coverage memory and local obstacle policy need canonicalization. |
| 37–45: interact/combat/loot/use item/quest tools | M0 skills and verifiers | `ACTIVE_OFFLINE` for bounded `INTERACT`, `COMBAT`, `LOOT`, exact `USE_ON_TARGET`, and exact `EXTRA_ACTION` quest-tool handling. `QuestItemSkill` requires target GUID/item/action/cache agreement; `QuestToolSkill` requires the selected binding cache plus an addon-confirmed live action type/ID. Both verify only quest credit. Generic object use and broader quest-tool resolution remain `PLANNED`; these paths remain `LIVE_REQUIRED`. |
| 46–63: gossip, accept/dialog, objective flows, completion | quest runtime + dedicated UI skills | `ADAPTER_OFFLINE`: canonical `QuestDialogSkill` validates explicit, telemetry-confirmed gossip, Accept/Complete/Turn-in/Continue and exact reward-row actions; `QuestOfferSelector` and `QuestRewardSelector` remain fail-closed for ambiguity; `TurnInResolver` applies the conservative field UI → local role → declared turn-in location → current Quest API region order. Vehicle, escort and campaign continuation remain `PLANNED`; reward layout needs live validation. |
| 64–70: quest FSM, campaign, stages, invalidation, soft target | `QuestExecutionRuntime`, `NextQuestResolver`, `Supervisor` | `ADAPTER_OFFLINE`: primary quest, stage-safe locator invalidation, and one-candidate addon-confirmed `MAIN_CAMPAIGN` continuation exist. Full explicit canonical quest FSM, campaign UI handling, death/cinematic/vehicle handling and soft-target evidence adapter are `PLANNED`. |
| 71–77: bindings, executor, acknowledgements, safety, retry/timeout/invalidation | bindings, executor, runtime policies | `ACTIVE_OFFLINE` for verified binding inventory, normal executor boundary, typed retry/timeout policy, safe cancellation, bounded action-correlated local acknowledgement and the complete DESIGN-077 invalidation matrix. `LOCAL_ACK` is explicitly separate from world success. Selected-PID acknowledgement latency/failure and real loading/teleport/phase/floor/vehicle transitions remain `LIVE_REQUIRED`. |
| 78–85: memory, active perception, advisory reasoner, rejection | `AgentMemory`, `ActivePerception`, `OllamaReasoner` | `ADAPTER_OFFLINE`: memory/evidence/rejection and bounded active perception exist. Public split memory APIs and strategy history are `PLANNED`; reasoner stays advisory only. |
| 86–93: scheduler, performance, replay, GUI, acceptance | runtime/capture/replay/gui | `ADAPTER_OFFLINE`: bounded capture/perception scheduling, screenshot replay, diagnostics and acceptance foundation exist. Full replay player/golden-trace corpus and complete capability reports are `PLANNED`. |
| 94–96: M0/M1 tests and live validation | tests + user-operated sessions | `ACTIVE_OFFLINE` test foundation; `LIVE_REQUIRED`. The exact M0 replay gap is engine-level LOS reposition plus interruption-resume. M1 requires M0 live baseline first. |
| 97–102: ownership, end-to-end behavior, research notes | all boundaries | This document records the migration map. The end-to-end quest loop is `PLANNED`/`LIVE_REQUIRED`, not claimed complete. |

## Immediate implementation queue

1. Remove the remaining legacy lifecycle/commitment execution authority after
   each migrated call site has direct tests.
2. Live-validate the dedicated M1 reward-policy boundary, retaining the
   quest-credit verifier as the only credit owner.
3. Run the user-operated M0 live baseline after the above offline paths
   are green, and record source logs/screenshots and root cause in
   `LIVE_VALIDATION.md`.

No live client action was sent while producing this reconciliation.

## M1.5 Supervisor FSM checkpoint (2026-09-21)

V5 M1.5 is now an explicit production contract rather than an implicit enum
around `evaluate()`. All twelve required states expose immutable priority,
interruptibility, timeout and retry metadata; `can_enter`, `enter`, `tick`,
`can_exit`, `exit` and `can_preempt` enforce evidence-backed lifecycle and the
minimum death/disconnect/critical/combat/stuck ordering. The Supervisor cannot
dispatch input or become an active-skill owner; Agent remains the sole
cancellation, release and finalization authority. Focused Supervisor and
architecture regression passed **39 tests**; complete regression passed
**1141 tests, 3 skipped in 38.43 seconds**. Selected-PID preemption and recovery
timing remains live-open.
