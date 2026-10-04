# M0 Phase C — Interact, Combat, Loot and cancellation

> Historical migration note updated 2026-09-16. The current M0 acceptance
> evidence is `M0_ACCEPTANCE_MATRIX.md`; this file does not claim live
> validation.

Status: **offline-tested migration increment; M0 is not accepted or live-validated.**

## Added canonical paths

- `InteractSkill` / `InteractionVerifier` now own the engine's `INTERACT` and
  `TALK` attempts. Interaction is successful only after a dialog/gossip/quest
  UI transition or a quest-state delta; a keypress is not success.
- `CombatSkill` / `CombatVerifier` now own `COMBAT` and `DEFEND` attempts.
  The skill validates the selected exact GUID, chooses only an explicitly
  usable harmful configured action, observes the GCD, and requires target
  death, corpse evidence, or supporting objective credit before terminal
  success. Range, facing, line-of-sight, path and target identity errors are
  typed failures.
- `LootSkill` / `LootVerifier` now own `LOOT`. A valid corpse anchor or exact
  dead selected target is required; the terminal success evidence is a
  source-consistent loot event, relevant inventory delta, or (without an exact
  item-ID contract) a quest-objective delta. A loot UI transition alone is
  never success.
- `set_mode(MANUAL|STOPPED)` stops the executor before cancelling and
  finalizing the sole `ActiveSkillRuntime`. It records `ACTION_CANCELLED` and
  does not misclassify user cancellation as a planning failure.
- `TimeoutPolicy` and `RetryPolicy` now provide the active engine's central
  deadline resolution and bounded failure backoff. Existing skill contracts
  remain the configured source of timeout baselines during migration.

The legacy `SkillRegistry.verify` remains only for skills not yet migrated.
The old stateful combat controller is no longer observed or invoked by the
agent runtime; Combat availability is a stateless preview and active execution
uses the typed M0 skill plus `NavigationService`.

## Offline evidence

- Focused M0 skill/lifecycle/policy selection is green; the authoritative
  aggregate is recorded in `M0_ACCEPTANCE_MATRIX.md`.
- Full offline suite, run in four deterministic partitions due host command
  limits: **800 passed, 2 skipped**.
- `tests/test_m0_replay_contract.py` performs 100 deterministic single-active
  lifecycle iterations; it proves runtime admission/finalization semantics,
  not live WoW behavior.

## Remaining M0 gate work

- User-operated selected-PID live validation of the full M0 matrix. Offline
  replay must not be represented as a completed WoW quest.
