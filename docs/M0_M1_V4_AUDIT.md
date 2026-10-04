# M0 + M1 V4 repository audit

> Historical baseline audit. Its initial gap list was written before the
> canonical M0 migration. For current implementation and evidence, use
> `M0_IMPLEMENTATION.md`, `M0_ACCEPTANCE_MATRIX.md`, and the two current root
> specifications. It is retained for traceability, not as a current status.

Date: 2026-09-16  
Specification: `wow_agent_FINAL_M0_M1_master_prompt_v4.txt` supplied by the
user. This document is an audit, not a claim of M0 or M1 completion.

## Baseline

- The working tree was already dirty when the audit began. Those changes are
  preserved and are not attributed to this migration.
- `python -m pytest -q -x -p no:cacheprovider`: **435 passed, 2 skipped,
  1 failed** in 19.86s.
- Failing test: `tests/test_perception_unknown_regression.py::test_real_world_screenshot_starts_unknown_and_tracks_overhead_relation`.
  The real screenshot detects an UNKNOWN overhead symbol but does not produce
  the required supported `ABOVE` relation. This is a real regression against
  the existing test contract, not a live validation result.
- No live client input was started or sent during this audit.

## Actual active data path

The current process path is:

`AgentRuntime.step` → `BufferedPixelSensor`/capture → optional
`PerceptionWorker` and `SpatialMemory` projections →
`AutonomousAgent.tick` → `WorldModel.ingest` → `Planner.candidates` →
`SkillRegistry.commands` → `InputExecutor` → `SkillRegistry.verify`.

The relevant entry points are:

| Responsibility | Active code | Finding |
| --- | --- | --- |
| Process/runtime | `agent/runtime.py:AgentRuntime` | Active; mixes capture orchestration, perception publication, arming, health reporting and agent invocation. |
| Main control loop | `agent/engine.py:AutonomousAgent.tick` | Active; approximately 69 KB and owns ingestion, planning, persistent movement control, verification, retry/backoff, cancellation and records. This is a God object. |
| World state/query | `agent/world.py:WorldModel`, `WorldQuery` | Active; world model is usable but runtime context and planner-facing raw state still leak into it. |
| Planning | `agent/planner.py:Planner` | Active; approximately 95 KB. It contains quest proposals, combat/interaction selection and low-level recovery choices. |
| Skill commands/verification | `agent/skills.py:SkillRegistry` | Active; combines contracts, input construction and verification with string reasons. |
| Current action | `engine.pending: Attempt` | Active authority today. |
| Subgoal commitment | `autonomy_loop.py:AutonomousLoop.commitment` | A second active lifecycle/ownership concept. |
| Lifecycle display | `skill_lifecycle.py:SkillLifecycleController` | A third, derivative lifecycle that can drift from `pending`. |
| Navigation | `AgentNavigator`, `ReachMovementController`, `VisualApproachController`, `SeekVisualCueController`, `navigation.NavigationEngine` | More than one controller/state authority exists. |

## Required ownership migration

| Existing authority | Disposition | Reason |
| --- | --- | --- |
| `engine.pending` | MIGRATE | Must become the single `ActiveSkillRuntime.state`, not coexist with it. |
| `AutonomousLoop.commitment` | MIGRATE/REMOVE | A target/subgoal reference belongs inside active-skill intent/context or Supervisor history. It must not independently keep a running action alive. |
| `SkillLifecycleController` | REMOVE after UI migration | It is observational duplication. The debug UI should read canonical active state. |
| `AgentNavigator` | MIGRATE | Candidate legacy global navigation implementation; select canonical navigation service after direct call-site audit. |
| `ReachMovementController` | MIGRATE | Candidate local/persistent movement component under canonical NavigationService. |
| `VisualApproachController`/`SeekVisualCueController` | ADAPTER_TEMPORARY | Local visual steering/search capabilities, not separate navigation authorities. |
| `navigation.NavigationEngine` | MIGRATE | Candidate navigation abstraction; must be reconciled with the active agent path before M0 navigation can be accepted. |

## V4 compliance gap summary

### M0 gaps

1. There is no typed shared `SkillStatus`, `SkillResult`, `FailureReason`,
   `VerificationResult`, retry policy or timeout policy. `Outcome` and many
   ad-hoc reason strings are used instead.
2. There is no single ActiveSkillRuntime. `pending`, commitment and lifecycle
   are independently mutable.
3. Planner selection runs inside the engine path and still encodes execution
   and recovery detail.
4. Navigation is duplicated and not exposed by one canonical API.
5. Verification is embedded in `SkillRegistry.verify`, rather than isolated
   by movement/interaction/combat/loot/quest responsibility.
6. A replay/debug capture exists, but no canonical deterministic decision
   replay contract for the M0 state machine exists.
7. Safe-stop behavior exists in executor/mode paths but is not represented as
   a canonical active-skill cancellation/fatal-error contract.

### M1 gaps

1. **Partially migrated (OFFLINE_TESTED):** `QuestExecutionRuntime` provides
   stable primary-quest ownership, while the full canonical objective FSM is
   still absent. Details: `M1_PHASE_A_QUEST_STATE.md`.
2. **Partially migrated (OFFLINE_TESTED):** deterministic `ObjectiveClassifier`
   now formalizes normalized/API/text evidence; full mechanic taxonomy and
   locator-driven execution remain absent.
3. No ObjectiveLocator applying local → minimap → world map → memory → search
   resolution order.
4. World-map/minimap CV components exist but are not first-class location
   resolvers consumed by a quest runtime.
5. **Partially migrated (OFFLINE_TESTED):** `QuestProgressVerifier` records
   before/after credit evidence separately from action success. It is not yet
   the decision gate for every objective flow.
6. Historical audit finding. The follow-up now has canonical turn-in,
   fail-closed gossip, and exact reward-row policy boundaries; extra-action
   and vehicle execution layers remain absent.

## Safety and source constraints confirmed

- Client-side screen capture, addon telemetry and OS input paths are already
  the project model; no process-memory, injection or binary patching path was
  found in the active implementation.
- Existing selected PID and bindings-cache checks are retained during the
  migration.
- The current user operates live testing. This migration will not take client
  control without a fresh live-test request.

## Migration order

1. **Completed (UNIT_VALIDATED):** repaired the existing overhead-relation
   regression; the targeted visual regression suite is 17/17 green.
2. **Completed (UNIT_VALIDATED):** added shared typed contracts and **one**
   ActiveSkillRuntime; `pending` is now a compatibility projection over that
   canonical state. Details: `M0_PHASE_A_ACTIVE_SKILL.md`.
3. **Completed (UNIT_VALIDATED):** selected `NavigationService` as the one
   live agent navigation authority and migrated engine call sites. Details:
   `M0_PHASE_B_NAVIGATION.md`.
4. **Completed (OFFLINE_TESTED):** migrated `INTERACT`, `TALK`, `COMBAT`,
   `DEFEND`, and `LOOT` through canonical typed M0 skills and isolated their
   pure interaction/combat/loot verification. Details:
   `M0_PHASE_C_INTERACTION_COMBAT_LOOT.md`.
5. Migrate remaining engine ownership from commitment/lifecycle to the active
   runtime, deleting or isolating the old authorities as each call site moves.
6. Migrate Search and remaining movement/face recovery APIs, then remove the
   legacy registry/controller execution adapters.
7. Split the remaining verification paths and add the full replay matrix.
8. Build the M1 quest state, classifier, locator, map/minimap resolvers and
   quest execution FSM on top of the migrated M0 skills.

No phase is marked DONE until its call sites are migrated, old authority is
removed or isolated, tests pass, and live validation is explicitly recorded.
