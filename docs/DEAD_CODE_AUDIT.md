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

## 2026-10-07 audit result (issues #33, #81, #87)

| Area | Result | Action |
|---|---|---|
| `navigation/engine.py` `NavigationEngine`, `navigation/memory.py` `NavigationMemory`, `navigation/learning.py` | only used by each other and their unit tests; the live agent routes through `NavigationService` (`navigation/service.py`), so route/segment experience is **not** learned from live runs | retained, deliberately not wired in (#33); the per-call never-closed sqlite connection was replaced by one persistent WAL connection with `close()` |
| `src/adapters/world_map.py`, `src/adapters/minimap.py` | imported the non-existent `src.adapters.windows_input`; the live agent uses `wowbot.vision.adapters.*` | retired (`git rm`, #81) |
| `src/core/observation_replay.py`, `src/mocks/mock_client.py` | imported modules that no longer exist (`src.adapters.file_bridge`, `src.core.state`, `src.core.commands`, ...) | retired (#87) |
| `tools/replay_observations.py`, `tools/observe_client_state.py` | the only callers of the above; themselves unimportable (`src.core.client_observation`, `src.core.quest_planner`, ...) | retired with them |

`tests/test_legacy_module_imports.py` imports every module still under
`src/adapters`, `src/core` and `src/mocks`, and keeps the retired paths absent.
The files remain available in git history.
