# M0 deterministic execution core

M0 accepts a specified entity, object, or location.  It does not choose the
quest objective.  The canonical path is:

`Planner proposal -> ActiveSkillRuntime -> M0SkillDispatcher/NavigationService -> Verification -> typed result`.

Implemented offline-covered skills are Target, Interact/Talk, Combat/Defend,
Loot, Search, Visual Approach, persistent location movement, and Quest Dialog
interaction.  Combat range/facing/line-of-sight recovery is bounded and only
uses a fresh, exact-target screen position.  Interrupt cancellation releases
input; a resumable intent contains no held-input state.

Interact/Talk now owns its full local recovery chain in the same canonical
attempt: `VALIDATE_TARGET -> SEND_INTERACT -> explicit client OUT_OF_RANGE ->
APPROACH -> FACE -> SEND_INTERACT -> VERIFY`. For a selected entity with live,
same-instance world coordinates, `NavigationService.move_to_entity()` owns the
persistent reach controller. Without a world position, only a fresh,
GUID-associated World3D/mouseover screen anchor may start the existing visual
servo. Neither branch guesses a world coordinate or returns control to the
planner between movement pulses. One bounded range-recovery attempt is allowed
per interact attempt; terminal UI/quest evidence remains the only success
signal.

Combat follows the same bounded ownership rule for a selected hostile target.
On an explicit range failure with current same-instance world coordinates,
the existing `NavigationService.move_to_entity()` owns one persistent reach
sub-step in the same Combat attempt, then Combat revalidates the selected GUID
before resuming its rotation. Screen-local range/LOS/facing corrections remain
bounded fallbacks when exact world localization is unavailable; neither branch
creates a planner-owned MOVE action.

Loot follows the same bounded ownership rule for a selected dead target. An
explicit client range failure can enter one `NavigationService` world-space
corpse approach only when the corpse and player have current same-instance
coordinates; arrival retries `INTERACTTARGET` within the same Loot attempt.
A screen-only corpse is never converted into a guessed movement destination.
Opening a loot window is an intermediate observation, not success. Success
requires a source-consistent loot event or a real inventory delta, and a
declared expected item ID must be among the received/gained IDs. If such an
item is still absent at the Loot attempt deadline, the result is the typed
`EXPECTED_ITEM_NOT_RECEIVED`, not a misleading generic loot-window failure.
For loot intents without an explicit item-ID contract, a before/after quest
objective delta is also valid post-interaction success evidence, covering
auto-consumed quest items without guessing an inventory item.

`ObjectUseSkill` is the canonical screen-space M0 boundary for an M1
structured world-object objective. It rechecks immediate addon mouseover
identity plus cursor position, issues one right click, and returns success only
through `QuestProgressVerifier` credit. It is intentionally distinct from the
old generic `USE` registry adapter, which receives no structured M1 object
proposal.

M0 remains **not complete** until the V4 replay matrix and selected-PID live
validation demonstrate reliable target, movement, interaction, combat, loot,
cancellation, and safe-stop outcomes.  See `M0_ACCEPTANCE_MATRIX.md` and
`LIVE_VALIDATION.md` for evidence rather than treating this description as a
completion claim.
