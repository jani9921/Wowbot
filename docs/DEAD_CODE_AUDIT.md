# Legacy and dead-code audit

## 2026-09-16 audit result

| Area | Result | Action |
|---|---|---|
| Active action state | `pending` is a read-through compatibility property | retain temporarily; it has no independent state |
| `SkillLifecycleController` | no import or call site remained after the active-runtime projection audit | removed; GUI/debug reads `ActiveSkillRuntime` projection only |
| Quest dialog | generic registry command/verification duplicated canonical semantics | removed from generic command and verification paths; legacy use fails closed |
| Structured quest world-object use | Planner emitted generic `USE`, mixing its right click and generic event verifier with M1 objective semantics | migrated to canonical `OBJECT_USE`/`ObjectUseSkill`; generic `USE` is now a fail-closed compatibility adapter with no structured M1 proposal call site |
| Navigation | public engine projections (`navigator`, `movement`) are diagnostics only | retain until callers are migrated; `NavigationService` owns state |
| Legacy `CombatController` | no longer observed, selected, or displayed by `AutonomousAgent`; planner admission is a stateless preview | retain only as a compatibility adapter for direct legacy callers/tests; it has no active runtime authority |
| Commitment policy | `AutonomousLoop` is instantiated and covered by commitment tests | not dead; document as an adapter, do not delete until runtime facade migration |
| Old visual/quest/resource features | many remain reachable through planner/registry | not dead; outside M0/M1 expansion freeze unless needed for stability |

The detached `SkillLifecycleController` was removed only after an all-source
import/call-site audit and full offline regression. This repository is
user-dirty; unrelated work was preserved. Selected-PID live evidence remains
separate and is not implied by this removal.
