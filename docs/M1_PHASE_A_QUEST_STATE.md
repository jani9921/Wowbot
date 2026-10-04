# M1 Phase A — normalized primary quest and credit evidence

Status: **offline-tested foundation; M1 quest execution is not complete or
live-validated.**

- `QuestExecutionRuntime` maintains exactly one primary quest and one stable
  ready objective. It accepts an explicit goal/telemetry selection,
  auto-selects only when exactly one quest is active, and never silently
  switches to another side quest or independent ready objective.
- The runtime now exposes the deterministic M1 execution phase as planner
  context: `SELECT_PRIMARY_QUEST`, objective classification, local/global
  navigation, local search, transition resolution, information gathering,
  credit verification, and completion-mode resolution. It uses the same
  `ObjectiveLocator` instance as the shared QuestDomain and never sends input.
  Planner consumes the selected objective id, so parallel ready objectives no
  longer compete in the active proposal stream.
- `QuestDomain` filters ready objectives to the selected primary quest when
  one exists. It remains the existing shared planner domain; no parallel
  quest brain was created.
- `ObjectiveClassifier` formalizes the existing deterministic normalized/API/
  text-evidence classifier and exposes a separate M1 canonical objective kind
  while preserving current legacy objective type contracts.
- `QuestProgressVerifier` compares before/after normalized quest projections.
  The engine records its result separately from the action result, so an
  interaction/combat/loot success is never automatically asserted to be
  quest credit.
- `QuestDialogSkill` is now the canonical bounded UI action for an
  addon-confirmed `ACCEPT`, `COMPLETE`, `TURN_IN`, or `CONTINUE` dialog. It
  refuses unknown/reward actions, clicks only the current matching quest UI,
  and uses a dedicated verifier. `QUEST_ACCEPTED`/accepted-quest state and a
  matching `QUEST_TURNED_IN` event are also exposed to `QuestProgressVerifier`
  as quest-credit evidence; local click success alone is never credit.
- Completed quests retain their confirmed completion surface in the runtime:
  `FIELD_TURN_IN`, `VERIFY_COMPLETE` for `AUTO_COMPLETE`,
  `HANDLE_SPECIAL_UI`, or `LOCATE_TURNIN` for NPC completion.  This is state
  representation only; the planner and typed UI skills remain the sole input
  owners.
- `NextQuestResolver` continues only an explicit `MAIN_CAMPAIGN` goal after
  the previous primary quest has left active state, and only when exactly one
  active quest carries the addon's `is_campaign` API flag. It cannot replace a
  fixed `quest_id` goal or use gossip ordering as a campaign assumption.
- `TurnInResolver` owns completed-quest location evidence. Its ordering is
  field UI → live target role → declared turn-in location → current Quest API
  waypoint region → UNKNOWN. A memory waypoint alone does not authorize
  movement or identify an NPC.
- Quest-runtime stage signatures make every authoritative objective/count/
  completion-state transition explicit. A new stage clears the previously
  selected objective before classification/location resolution, records a
  revision trace, and therefore cannot reuse the old stage's location
  hypothesis.
- A successful `COMBAT` action with no observed quest credit now starts a
  two-second telemetry grace window. If the quest signature remains unchanged,
  the exact GUID/objective combination is temporarily suppressed for 45
  seconds. A verified progress change removes this memory immediately. This is
  bounded target-selection memory, not a semantic claim about the creature.
- `ObjectiveLocator` is now a separate evidence-only resolver and is consumed
  by `QuestDomain` for the existing objective-location proposals. Its order is
  matching local entity → objective/known map marker → remembered location →
  bounded search/transition hypothesis → unknown. It does not issue movement
  input and therefore does not duplicate NavigationService.

The engine's migrated M0 skills are now dispatched through
`M0SkillDispatcher`; this is the first extraction from the active-skill branch
of `engine.py`, keeping skill type branching out of the main loop over time.

The latest full offline regression is recorded in `CHANGELOG.md`. This is not
proof of accepting, completing, turning
in, rewarding, or chaining a live quest.

Remaining M1: gossip/reward policies, the remaining objective mechanics, and
live validation.
