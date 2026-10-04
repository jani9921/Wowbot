# Architecture (V4-097 required deliverable)

`src/wowbot/` is organized by responsibility rather than by feature. Each
package below owns one concern; none of them send input directly except
`execution/`.

## Package map

- **`runtime/`** -- typed contracts, the single `ActiveSkillState`, the
  `Supervisor` priority gate, the `EventBus`, failure taxonomy/escalation,
  retry/timeout policy, structured logging, state-invalidation matrix, and
  the M0 dispatcher. Owns no WoW input and no quest reasoning.
- **`skills/`** -- one file per canonical M0 skill (`target.py`,
  `interact.py`, `combat.py`, `loot.py`, `movement.py`, `search.py`,
  `object_use.py`, `quest_item.py`, `quest_tool.py`, ...), each exposing a
  typed phase enum and delegating pathing/verification to `navigation/` and
  `verification/` rather than re-implementing them.
- **`navigation/`** -- the single `NavigationService` composing global/local
  planning, arrival verification, stuck classification/recovery, search
  coverage, and (V4-025/V4-026) navigation-context and transition
  resolution. No skill sends movement input outside this package.
- **`verification/`** -- pure before/after comparators (`combat.py`,
  `interaction.py`, `loot.py`, `quest.py`, `quest_dialog.py`) that decide
  whether a skill's postcondition actually held; never issue input.
- **`vision/`** -- perception adapters (minimap, world map, 3D world,
  tooltip, UI parser) that turn captured frames into typed observations.
  Nothing here plans, targets, or dispatches.
- **`execution/`** -- the only package that touches real input
  (`command_dispatch.py`, `input_scheduler.py`); owns key-up cleanup, the
  input watchdog, and cancellation.
- **`agent/`** -- the composition root: `engine.py` (tick loop), `world.py`
  (`WorldModel`, evidence storage), the quest model/runtime, planner domain
  modules (`quest_planning.py`, `combat_planning.py`,
  `navigation_planning.py`, `recovery_planning.py`, `target_planning.py`,
  `planning_orchestration.py`), and the GUI/status projection.

## Responsibility boundaries

`tests/test_architecture_boundaries.py` enforces the load-bearing rules
(single dispatch/finalize authority, no second pathing system, no planner
embedded inside a domain policy, etc.) -- treat a failure there as the
architecture telling you a change crossed a package's stated concern, not
as a test to work around.

## Where a new capability belongs

- A new perception signal -> `vision/`, exposed as a typed observation, no
  semantics assigned there.
- A new way to decide *what* to do with an objective -> a domain module
  under `agent/`, composed by `planning_orchestration.py`.
  A new way to move/reach/recover -> `navigation/`.
- A new way to confirm a skill worked -> `verification/`.
- A new M0-level mechanical skill -> `skills/`, registered in
  `runtime/m0_dispatch.py`.

## Known gaps

See `docs/CURRENT_SOURCE_COVERAGE.md` for the current per-requirement audit
against this codebase; several V4/V5/DESIGN requirements are `PARTIAL` --
implemented but not fully matching the spec's exact contract shape -- and a
few remain process/definition sections with no code artifact to trace.
