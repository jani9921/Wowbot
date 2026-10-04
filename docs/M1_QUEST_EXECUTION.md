# M1 quest execution layer

M1 reads normalized quest/UI/map/world observations, selects the primary quest,
classifies an active objective, asks M0 to execute, and requires quest-credit
verification before advancing.

Implemented offline foundations include `QuestExecutionRuntime`, primary quest
selection, objective location hierarchy, stage signatures/revisions,
turn-in resolution, and an explicit `QuestDialogSkill` for ACCEPT, COMPLETE,
TURN_IN, and CONTINUE.  Addon-exported `AVAILABLE`/`COMPLETE` gossip rows use
an explicit `GOSSIP_SELECT` transition: it must produce a next named action for
the same quest before any accept/turn-in button is considered.  Reward
selection is available only through `QuestRewardSelector`: an exact
`reward_item_id` / `reward_choice_index`, or an explicitly requested
`FIRST_UNAMBIGUOUS` policy when exactly one addon-exported row exists.  Missing
coordinates, ambiguous rewards, and unsupported gossip remain fail-closed.

`QuestOfferSelector` is the pure policy boundary for visible gossip offers: an
explicit goal quest ID wins, a single offered ID may be selected, and multiple
different IDs without an explicit goal remain blocked for user selection.

`NextQuestResolver` now supports a narrowly scoped campaign handoff: only a
goal explicitly configured with `mode: MAIN_CAMPAIGN`, and exactly one active
addon-flagged campaign quest, may replace a turned-in primary quest. An
explicit `quest_id`, multiple campaign candidates, or missing API support all
remain non-actionable.

Retail Extra Action is now represented by the canonical `QuestToolSkill`.
The read-only addon exports its visible/usable state and actual action
type/ID. The agent may execute `EXTRAACTIONBUTTON1` only through the explicitly
selected bindings cache, after the same live action type/ID has been rechecked.
For unattended quest execution, only an item-type action exactly equal to the
current Quest API `special_item` is admitted. A different action type requires
an explicit goal policy that repeats the observed type and ID. In both cases,
the sole success condition is `QuestProgressVerifier` credit for the declared
objective/quest; a button press, cooldown, or button disappearance is not
success.

Targeted action-bar quest items now use the canonical `QuestItemSkill` rather
than the generic registry. It requires an exact confirmed target GUID, a living
target, exact item ID, a current usable action-bar row and its action from the
selected binding cache. It verifies only the declared quest/objective credit;
the input acknowledgement, `ITEM_USED` event and cooldown movement remain
non-terminal diagnostics.
The same skill also owns friendly-target `ASSIST` item use and rejects harmful
items or a target that is not explicitly non-attackable.

`FOLLOW_INSTRUCTION` is likewise a canonical `InstructedSpellSkill`, not a
generic combat cast. It accepts only a fresh NPC instruction that explicitly
contains the exact current action-bar spell name, a confirmed living hostile
target GUID, the matching spell ID/action binding, and a binding present in the
explicitly selected cache. It succeeds only after matching normalized
quest/objective credit. Missing cache, a stale/wrong target, a cooldown, or an
ambiguous instruction fail closed; no cast acknowledgement is treated as quest
progress.

Structured world-object objectives (for example a tooltip-confirmed campfire)
now use canonical `ObjectUseSkill` as `OBJECT_USE`. It permits one right click
only when the immediate add-on mouseover identity and current normalized cursor
coordinate exactly agree with the intent. `OBJECT_USED`, a click acknowledgement
or a local visual transition is not quest completion: only matching normalized
quest/objective credit succeeds. The old generic `USE` registry surface is a
fail-closed compatibility adapter and is no longer emitted or executable for
this M1 route.

M1 is **not complete**.  A replay or a successful button click is not a quest
completion claim.  The remaining gates include live reward-layout validation,
broader gossip mechanics, generic object-use mechanics, all objective
mechanics, campaign UI handoff, and user-operated end-to-end live validation
of quest credit and turn-in.

The deterministic **offline** M1 gate is complete as of 2026-09-23:
`tests/test_m1_completion_gate.py` binds all named M1 capabilities to their
production owners, and `tests/test_m1_integration_scenarios_index.py` maps all
25 required scenarios to regression evidence. Scenario 16 now directly proves
that a minimap cue disappearing at an entered search area causes bounded local
3D reacquisition rather than a false TARGET_NOT_FOUND/map loop. This statement
does not alter the live-incomplete status above.
