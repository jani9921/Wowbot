# M0 Phase B — TargetSkill

Validation status: **UNIT_VALIDATED**. No live client input was sent.

## Changed files

- `src/wowbot/skills/target.py`: deterministic TargetSkill FSM:
  `ACQUIRE_CANDIDATES → VALIDATE_IDENTITY → SELECT_TARGET → APPLY_TARGET →
  VERIFY_TARGET`.
- `src/wowbot/agent/engine.py`: TARGET command creation and verification now
  use TargetSkill. The old generic registry branch is no longer the active
  TARGET verifier.
- `tests/test_m0_target_skill.py`: invalid input, exact-GUID success, wrong
  GUID and typed timeout coverage.

## Ownership

TargetSkill is stateless. Its target expectation and phase are stored in
`ActiveSkillRuntime.state.skill_context`; it cannot own a second running
target action. The existing registry remains a temporary command/availability
adapter for un-migrated M0 skills only.

## Validation

- Target FSM/core/active-runtime group: **124 passed**.
- All target-related repository tests: **200 passed**.

## Remaining M0 work

`ACQUIRE_TARGET` and local search are still old registry/planner paths; they
will be migrated into the canonical SearchSkill after the remaining
commitment ownership is moved into Supervisor/active intent context. Interact,
Combat and Loot verification are not M0-complete yet.
