# 2026-10-21 17:14 run: entity backlog and server NPC handoff

Status: implemented and OFFLINE_TESTED; user-operated post-fix validation pending.

## Observed failure

The user reported a circuit past all three NPCs followed by WAIT. The
selected-PID journal confirms no INTERACT/F7, 17 hover-caused MOVE
cancellations, and three TARGET attempts before the idle server-mode WAIT.
Ymir had already decoded the three NPCs, but the runtime world did not have
them. The initial inbox held 311 events while the main runtime was starting.
An unchanged-code probe verifies that consumed events older than two
seconds disappeared without a corresponding discard diagnostic.

## Corrections

1. Keep the two-second admission guard. If confirmed entity facts became
   stale in the queue, request a fresh snapshot from the existing producer.
   Same PID, character/session/map and IPC identity; no new sensor brain,
   arbitrary process inspection or action path. Recovery requests are
   bounded and retried on write failure. No gameplay secret/raw payload is
   added to the protocol or diagnostics.
2. Producer snapshots retain bounded entity-removal tombstones. A missed
   destroy can therefore invalidate an old receiver entity; late flag or
   movement updates cannot revive it without a create.
3. Stop proposing pointer-dependent TARGET in server mode. Such proposals
   are also denied in skill availability, before a withheld hover could
   start a useless verification attempt. Server Tab/defence/rescue/restore
   key paths keep their existing GUID/binding checks.
4. A hover from another quest, a screen box or minimap zone does not cancel
   or finish a server route. Existing exact server ender -> matching fresh
   soft recipient -> F7 remains the canonical handoff.
5. BUY objectives explicitly naming a seller resolve exact TDB creature
   templates, including scripted raw type 14 objectives. Real read-only TDB
   lookup confirmed both Jakes entries, including the currently observed
   198846. Entry candidates are not a GUID or a successful purchase. An
   already completed BUY row is not revisited for a later read/use step.
6. Shared final facing now uses the actor's unsmoothed world bearing,
   separate from the navmesh-projected walking endpoint. Current server
   actor position wins when available; removal prevents a blind turn.
   Fresh heading can verify an in-place turn without a new XY sample.
   Expiring the bounded turn now reports FACING_FAILED, never successful
   arrival. Selected-entity approaches request final facing as well.

The user additionally ran 17:45–17:50 on the still-unmodified runtime
(PID 3204, log prefix 20261021-174254). They explicitly report doing the
purchase and boarding the Disc manually; these are not autonomous successes.
Two server NPC MOVEs to Ambassador Fastrasz report SUCCESS while their
nearest saved world samples show approximately 29.5 and 49.5 degrees of
remaining heading error (samples are approximate, not synchronous dispatch
proof). Several plain quest-region arrivals also end facing away. Inspection
found a concrete common-controller bug: final facing used the smoothed/
projected path heading, and its 2.5 s expiry was accepted as arrival. The
new regressions require a bounded failure instead of that false success.
The existing old test that explicitly expected timeout-as-success was
updated to assert FACING_FAILED; identity checks were not relaxed.

## Validation

The new portable regression modules use no game input. They cover delayed
entity recovery through authenticated IPC and the actual WorldModel;
unchanged context/IPC identity; no stale movement or quest credit replay;
bounded retries, failed-write recovery, removals and clock edges; disabled
hover handoffs, exact F7 handoff and preserved key targeting; and exact
TDB BUY seller resolution plus completed-purchase exclusion.

The larger pre-facing suite returned 685 passed, 1 skipped and two failures.
Both failures reproduce on the unchanged actual project:
test_emergency_first_aid_uses_the_kit_on_the_selected_soldier and
test_close_faced_npc_with_matching_soft_target_gets_one_f7. The latter still
expects proposal construction itself to consume the press cooldown, contrary
to the preceding actual-dispatch-only correction. Neither test was weakened
or relabelled as a new passing runtime capability in this patch.

Final expanded suite: 66 modules, 924 passed, 1 skipped, three pre-existing
failures independently reproduced on the unchanged actual project. Besides
the two named above, the third is
test_identity_free_order_is_world3d_then_map_then_role_location_fallback
(expects SEEK_VISUAL_CUE, existing planner returns OPEN_MAP). A subsequent
targeted run after the final moving-selected-actor bearing correction
passes 105 tests. No pre-existing assertion was weakened to hide these.
All 450 Python source files parse. All 372 existing V4/DESIGN/V5 ledger
rows are unchanged, including all 203 authoritative V4/DESIGN rows.

The existing local-UDP test also fails on the unchanged
project inside the network-restricted sandbox and passes outside it; this
was not fixed by changing its assertions or weakening runtime guards.

The user must restart GUI/runtime and its Python Ymir bridge. Addon 0.9.73
and the pinned Ymir executable are unchanged. No live quest completion,
post-fix FPS or M0/M1 acceptance is claimed.

## Backup

Only tested source, test and documentation files are published to the
actual projekt directory. Original-file backups and the staged patch are
in work/live_fixes_20261021_1712 under the writable task workspace.
No SQLite database, generated runtime data, model or dataset is replaced.
