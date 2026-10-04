# M0/M1 migration status

## Canonical execution path

`AutonomousAgent` owns orchestration only.  One `ActiveSkillRuntime` owns zero
or one running action; `pending` is a compatibility projection of that state.
`M0SkillDispatcher` routes migrated Target, Interact/Talk, Combat/Defend, Loot,
and Quest Dialog skills.  `NavigationService` is the one navigation entry point.

`SkillRegistry` remains an adapter for unmigrated skill contracts and command
construction.  It is not an authority for `QUEST_DIALOG`: invoking its legacy
dialog verifier fails closed, and dialog clicks/verification run only through
`QuestDialogSkill`.

## Deliberate temporary adapters

| Adapter | Why it exists | Constraint | Retirement condition |
|---|---|---|---|
| `AutonomousAgent.pending` | old engine/read-only tests | projects `ActiveSkillRuntime.attempt`; no separate storage | remove once callers consume active-skill snapshots |
| `AutonomousLoop` | commitment/replan policy | does not own input, an active attempt, or movement control | move policy callers behind the runtime facade after M0 live baseline |
| `SkillRegistry` | legacy/unmigrated skills | cannot execute or verify Quest Dialog | split remaining skill families into typed skills |

## Evidence status

The migration is **offline-tested** only.  It must not be read as M0 or M1
completion.  Live evidence, selected PID/cache provenance, and unresolved
behaviour are recorded only in `LIVE_VALIDATION.md`.
