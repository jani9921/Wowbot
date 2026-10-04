# M0 Phase A — typed active-skill authority

Validation status: **UNIT_VALIDATED**. No live client test was performed.

## Changed files

- `src/wowbot/runtime/contracts.py`: shared M0/M1 typed status, failure,
  intent, result, verification, navigation and objective-location contracts.
- `src/wowbot/runtime/active_skill.py`: the canonical one-at-a-time
  `ActiveSkillRuntime` and its immutable terminal-result rule.
- `src/wowbot/runtime/events.py` and `src/wowbot/runtime/supervisor.py`:
  single-threaded runtime events and explicit death/loading/UI/combat
  interrupt gates.
- `src/wowbot/agent/engine.py`: active action state now lives in
  `ActiveSkillRuntime`; old `pending` is a compatibility projection instead
  of a second mutable field. The old lifecycle display is projected from this
  state and no longer owns a separate lifecycle.
- `tests/test_active_skill_runtime.py`: one-active-skill, terminal and cancel
  state tests.

## Migrated call sites

`AutonomousAgent` start, verify and finish paths create, phase-transition and
finish the canonical active state. Existing GUI/runtime callers still read
`agent.pending`; that property returns the canonical attempt and does not
store another value.

The active engine now delegates blocking state and combat-interrupt decisions
to `Supervisor`; planner execution is reached only after that gate permits it.

## Isolated legacy paths

- `SkillLifecycleController` is no longer constructed or mutated by the
  active engine. The source file remains temporarily until external imports
  are audited/deleted; `status()["skill_lifecycle"]` is now a projection of
  `ActiveSkillRuntime`.
- `AutonomousLoop.commitment` remains a separate *future subgoal* mechanism.
  It does not replace the active attempt in this increment, but it still must
  be migrated into Supervisor/intent history before M0 is complete.
- Navigation controllers have not yet been selected/migrated. No M0
  navigation completion claim is made.

## Tests

- `tests/test_active_skill_runtime.py`, `tests/test_camera_and_domain_1_0.py`,
  `tests/test_agent_core.py`, `tests/test_agent_runtime.py`: **118 passed**.
- `tests/test_supervisor.py` plus the active-runtime group: **122 passed**.
- All tests that instantiate `AutonomousAgent` or `AgentRuntime`: **182
  passed, 1 skipped**.
- Visual regression repair:
  `tests/test_perception_unknown_regression.py`, `tests/test_visual_tracks.py`,
  `tests/test_world3d_assignment.py`: **17 passed**.
- Full suite was run after the Phase B migration in two deterministic file
  partitions because the host caps a single command at roughly 30 seconds:
  **417 passed, 2 skipped** and **284 passed, 1 skipped** — **701 passed,
  3 skipped** total.

## Known risks / next work

The legacy `SkillRegistry` still supplies command construction and string
verification. Phase B must select one navigation service and migrate skills
to deterministic typed FSMs. Then Phase C–G move verification, retry,
timeout, cancellation and replay responsibilities out of the engine.

## Live validation required

No live validation yet. The user should not start a client test until a
complete M0 vertical slice has been migrated and its test matrix is green.
