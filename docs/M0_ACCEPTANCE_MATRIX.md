# M0 acceptance matrix

Status: **offline replay foundation; not live-validated.**

`tests/test_m0_acceptance_matrix.py` runs the canonical M0 boundaries 100
times deterministically. Its current covered paths are:

- visible target acquisition followed by interaction UI verification;
- explicit friendly `OUT_OF_RANGE` evidence remaining inside the same
  Interact attempt through a `NavigationService.move_to_entity()` request and
  post-arrival interact retry;
- typed combat range failure followed by a fresh combat/death verification;
- one same-attempt, world-coordinate Combat range approach through
  `NavigationService`, with selected-GUID revalidation before rotation resumes;
- typed line-of-sight combat failure;
- bounded same-attempt line-of-sight correction followed by a re-cast against
  the same identity (the local command is produced only by
  `NavigationService` from a verified screen target);
- corpse loot verified by receipt/inventory evidence or, where no exact item
  contract exists, a confirmed quest-objective delta;
- loot-window opening does not complete Loot; a declared expected item must
  be received, and a range-error corpse approach remains in its original Loot
  action when same-instance coordinates are available;
- repeated, time-separated no-progress samples becoming `SUPPORTED_STUCK`
  before recovery is allowed.
- interrupt cancellation leaving no phantom active skill;
- bounded target-reacquisition camera gesture.

`tests/test_m0_search_skill.py` additionally exercises the canonical Search
skill at the `ActiveSkillRuntime` boundary: finite sector coverage, bounded
budget exhaustion, and immediate handoff when the first viable unknown subject
is found. `tests/test_m0_engine_combat_local_recovery.py` covers both local LOS
and persistent world-coordinate combat range recovery without a replacement
planner action. `tests/test_m0_safe_stop.py` injects an executor exception and
asserts the engine drops to Manual, calls safe stop, and finalizes the one
active skill without leaving a phantom action.

It validates that the active runtime can be cancelled cleanly after each
terminal boundary simulation. Engine-level bounded LOS reposition and a
combat-interrupt → precondition-gated single resume replay are covered in
`tests/test_m0_engine_combat_local_recovery.py` and
`tests/test_m0_interrupt_resume.py`. Broader live M0 acceptance is still
required; no M0 acceptance gate or live validation is claimed yet.

Latest full offline regression: **800 passed, 2 skipped**. The next gate is a
user-operated M0 live baseline with the selected PID and verified binding
inventory; live input is not started by this test matrix.
