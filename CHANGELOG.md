# Changelog

## 2026-09-29 — camera-compensated YOLO track association

- The production learned-World3D path now uses Ultralytics BoT-SORT instead
  of the local fixed-distance detector association. Full-scene and foveal
  detections are associated only after conversion to canonical client-pixel
  coordinates.
- BoT-SORT uses sparse-optical-flow camera-motion compensation, a 30-refresh
  lost-track buffer and a visual-family gate so subject, symbol and object
  tracks cannot exchange IDs merely because their boxes overlap.
- Continuous latest-frame YOLO remains enabled. The high-rate CPU patch
  tracker and the slower canonical WorldModel/evidence cadence are unchanged.
- Ultralytics tracker loading is warmed in a background thread. Until ready,
  the legacy tracker continues publishing; the first native tracks inherit
  those already-published public IDs, avoiding both startup blocking and an
  ID discontinuity at cutover.
- `AIPC_WORLD3D_TRACKER=LEGACY|BYTETRACK|BOTSORT` provides an explicit A/B or
  rollback switch (`AUTO` selects BoT-SORT when the learned detector exists).
  `AIPC_WORLD3D_TRACK_BUFFER`, `AIPC_WORLD3D_GMC` and
  `AIPC_WORLD3D_GMC_DOWNSCALE` expose bounded calibration controls.
- Focused World3D/perception regression: **188 passed, 2 skipped**. The full
  canonical test directory completed **1864 passed, 4 skipped, 18 unrelated
  pre-existing failures**. No live-control run was performed.

## 2026-09-28 — continuous latest-frame World3D detector

- Removed the artificial 8/10/12/15 Hz learned-detector throttle. The runtime
  now keeps one inference in flight and immediately submits the newest frame
  after completion, with no stale-frame queue.
- Canonical WorldModel publication remains independently bounded, so faster
  visual refresh does not restore the former high-frequency evidence churn.
- Added detector cadence and throughput diagnostics plus
  `AIPC_WORLD3D_CONTINUOUS_DETECTOR=0` as an explicit legacy-cadence rollback.
- A production-path replay at a requested 40 Hz completed **36.32 detector
  refreshes/s**; complete refresh latency was **13.89 ms p50 / 17.73 ms p95**.
  Focused World3D/capture/runtime regression: **90 passed**. Status:
  **offline-tested, pending user-operated live validation**. Python restart is
  required; this scheduling change needs no addon update.

## 2026-09-28 — responsive GUI telemetry/runtime startup

- The Tk event thread no longer constructs `AgentRuntime` synchronously.
  Database, navmesh, capture, telemetry and perception initialization now run
  in a dedicated connection worker while the GUI continues processing window
  events and displays elapsed startup time.
- Worker results and errors are handed back to Tk through a thread-safe queue;
  the worker never touches Tk objects. Auto-FULL_AI waits for completed runtime
  startup before focusing the selected PID and requesting the normal safety
  gate.
- Reconnecting immediately demotes the old runtime to MANUAL before its slow
  shutdown continues off the UI thread. Focused GUI/runtime regression: **41
  passed, 1 pre-existing replay expectation failed**.
- Follow-up live evidence showed a roughly seven-second status gap on a second
  FULL_AI click. Goal/mode/test controls can wait for the agent lock, so they
  now use a serialized GUI control worker as well. Tk displays the active
  control operation and elapsed time instead of blocking.
- Rotating the bounded live-capture segment no longer joins an in-flight JPEG
  encoder. Each queued frame carries its original segment paths, allowing an
  old segment's final frame and a new run's first frame to drain safely.
- Repeated FULL_AI is now idempotent while FULL_AI is merely suspended by the
  foreground/telemetry safety gate. Returning focus to the selected WoW window
  resumes normally; an explicit MANUAL then FULL_AI remains the restart path.
- Updated focused GUI/runtime/live-capture regression: **47 passed, 1
  pre-existing replay expectation failed**.

## 2026-09-28 — Retail two-offer gossip-row recovery

- Addon 0.9.33 locates visible quest-list rows through bounded nested
  ScrollBox element data and exact title-region matching, fixing the live
  `x=0,y=0` export seen for Austin Huxworth's two available quests.
- An open quest list whose rows remain unaddressable now emits a high-priority
  safe WAIT instead of allowing World3D navigation or visual approach behind
  the modal UI.
- Focused regressions pass; live validation remains open.

## 2026-09-28 — bounded turn-in map relocalization

- A nearby turn-in POI with no selected NPC no longer invents an unknown
  entrance transition; local questgiver acquisition retains control unless
  explicit transition/blockage evidence exists.
- A failed World Map relocalization is now evidence-gated for the complete
  quest/session/map context. It cannot reopen repeatedly after an empty scan
  or user close without a quest, map-context, or target-identity change.
- Combined quest-dialog/navigation regression: **86 passed**; live validation
  remains open.

## 2026-09-26 — persistent combat visual follow and canonical rotation

- The canonical `CombatSkill` now owns per-attempt ability usage history and
  records a bounded ability-attempt trace. FAST `actionbar_fast` usability,
  range and cooldown values are used through the shared `AbilityRuleEngine`,
  so the next ready ability can be selected after a cast instead of stalling
  on stale slow-snapshot state.
- Added data-only starter Warrior metadata: Charge is the ranged gap closer;
  Shield Slam is preferred in melee while ready; Slam remains a melee
  fallback. Live WoW usability/range/cooldown stays authoritative.
- Added GUID-committed combat visual follow. Fresh selected-target tracks
  produce bounded facing corrections, repeated out-of-range samples produce
  persistent `COMBAT_TRACK_APPROACH`, and a temporarily off-screen target is
  reacquired only in its last supported bearing for at most 1.8 seconds.
  NavigationService remains the sole movement/facing command authority.
- COMBAT/DEFEND now request the fast visual-servo tracker profile (nominal
  60 Hz scheduling, measured runtime remains hardware/capture bounded).
- Addon 0.9.32 exports spell min/max range when Retail exposes it. Both addon
  source directories remain byte-identical; installation was not performed.
- Focused regression: **66 passed**. Complete suite: **1795 passed, 4 skipped,
  15 existing unrelated failures** after updating the addon-version contract.
  Combat tracking frequency, behind-target reacquisition and rotation remain
  **LIVE OPEN**.

## 2026-09-26 — quest-progress MMAP routing and Murloc loop correction

- Audited selected-PID 8260 run `live-debug-20260926-182316.jsonl`. YOLO was
  not blind to the Murlocs: the exact runtime crop from
  `0180-182617-568-critical.jpg` produced several `creature_unit_like`
  proposals, led by confidence `0.563`, `0.314` and `0.152`. Earlier in the
  same run addon identity confirmed `Murloc Spearhunter`, combat ran and loot
  was verified.
- The post-loot loop was a planning error: the in-progress Quest POI used
  normalized map coordinates for direct MOVE, then the close-marker/no-target
  heuristic invented an `UNKNOWN_TRANSITION`, producing
  `SEARCH_ENTRANCE -> OPEN_MAP -> WAIT` instead of local objective search.
- Active objective and in-progress quest-location movement now preserves the
  addon `C_MAP_WORLD_POS` endpoint, requires `WORLD_YARDS + instance_id`, and
  routes only through the canonical `NavigationService` with
  `require_navmesh=True`. A normalized UI-map point alone cannot launch MOVE.
- Plain quest-objective arrival no longer invents an entrance transition
  without explicit transition or repeated-blockage evidence. Successful POI
  arrival also retains its originating marker key so the same route is not
  reissued before local target/object search.
- Focused quest/navigation/combat regression: **85 passed**. Live validation
  remains open; restart the Python agent. Addon update is not required because
  the live payload already contained instance `2175` WORLD_YARDS coordinates.

## 2026-09-26 — visible quest marker retained through World3D evidence

- Audited selected-PID 8260 capture `0068-181050-761-critical.jpg`. The v4
  model detects Jaina's real overhead marker at confidence `0.01725` on the
  exact 512px World3D runtime crop, but the fixed top-right minimap exclusion
  deleted it afterward even though no minimap occupied that region.
- Learned subject and overhead-symbol proposals may now cross optional HUD
  rectangles. They remain UNKNOWN observations; temporal grouping, evidence
  and mouseover telemetry still perform identification.
- A temporally `SUPPORTED` UNKNOWN `symbol ABOVE subject` group is now eligible
  for `SEEK_VISUAL_CUE` even without hard-coded badge colour or body geometry.
  This closes the live WAIT loop where supported groups existed but the
  planner rejected every one of them.
- Focused World3D/SEEK regression: **78 passed**. Restart the Python agent
  before live validation; the addon is unchanged.

## 2026-09-26 — repeated World Map scan and opaque WAIT correction

- Audited the selected-PID 8260 live trace. WAIT followed a successfully
  selected Combat Dummy because Slam lacked resource and Attack had no verified
  binding; the generic message did not expose that unavailable COMBAT proposal.
- WAIT now records its exact capability/evidence category and the unavailable,
  cooling-down and blocked proposal skills.
- Rejected outer-edge World Map cursor/tooltips as navigable marker locations.
  The live false point was `x=1.0, y=.153` from the objective tracker and had
  incorrectly kept map search non-exhausted, causing a second full scan after
  the OPEN_MAP cooldown.
- A selected living attackable target now prevents a new map fallback cycle;
  its combat/interaction state must be resolved in World3D first.
- Focused regression: **163 passed**. Restart the Python agent before live
  retest; the addon is unchanged.

## 2026-09-26 — self-avatar mask removed from World3D detection

- Removed the third-person self-avatar rectangle from World3D UI exclusions.
  Learned, legacy and generic detector paths now receive the original pixels,
  so a nearby NPC/object/symbol cannot disappear merely because it overlaps the
  controlled character on screen.
- Retained the rectangle as non-semantic post-detection metadata. A large,
  centred and bottom-anchored UNKNOWN subject receives an
  `ATTENTION_SUPPRESS_ONLY` hint instead of being deleted or recognized as the
  player.
- SEEK and INSPECT ignore an uncorroborated likely self-avatar track, while an
  overhead relation, supported visual group or badge evidence overrides the
  hint for a nearby overlapping NPC.
- World3D regression: **135 passed, 1 skipped**. Selected-PID overlap behavior
  remains **LIVE OPEN**; no addon update is required, but restart the Python
  agent before testing.

## 2026-09-26 — distant overhead-cue recall gate

- Lowered the raw learned-detector observation gate from 0.05 to 0.01 and the
  `overhead_symbol_like` evidence gate from 0.08 to 0.01.
- Replaced SEEK's alternating left/right camera whips with a slow one-way
  four-step sweep. Both the empty-scene scan and IDENTIFY-track reacquisition
  now use 160 ms bounded drags separated by a 900 ms observation window.
- Kept the subject/object class gates and per-class budgets unchanged: weak
  overhead output remains UNKNOWN visual evidence and cannot directly assert a
  quest role.
- Added a regression proving a 0.02 overhead cue survives while a 0.02 weak
  humanoid proposal remains rejected; camera/seek focused suite: 54 passed.

## 2026-09-26 — combined 2794 v4 World3D runtime promotion

- Promoted `world3d_annotation_assist_combined_2794_v4` to the canonical
  learned World3D runtime revision.
- Built machine-local static FP16 TensorRT engines for the 512 global scan and
  640 foveal scan paths; the v4 PyTorch checkpoint remains the portable
  fallback.
- Kept UNKNOWN-first evidence semantics and the existing detector/tracker
  authority boundaries unchanged.
- Added a regression guard for the selected runtime model revision.
- Held-out Exile's Reach comparison showed improved aggregate mAP and improved
  creature/quest-object AP, but lower precision/recall at the operating point
  and a material corpse-class regression. Selected-PID live validation remains
  open.

## 2026-09-25 — learned World3D runtime recall correction

- Lowered the YOLO backend observation gate to 0.30 and retained conservative
  class-specific acceptance thresholds and candidate budgets.
- Stopped broad quest-tracker/nameplate overlay rectangles from deleting real
  learned subject detections behind translucent UI.
- Added an explicit self-avatar ROI so the controlled player remains
  suppressed without masking right/left world subjects.
- Corrected automatic NVIDIA selection and diagnostics to report the actual
  Ultralytics inference device (`cuda:0`).
- Real-frame replay now retains the 0.796 worg and rejects the controlled
  avatar; full regression: 1758 passed, 4 skipped.

## 2026-09-25 — stale quest reward UI invalidation

- Fixed a live WAIT/reward-selection loop while the active objective was only
  1/6 complete and no quest dialog was visible.
- Addon 0.9.30 gates retained quest reward choices behind effective UI
  visibility.
- Fresh FAST dialog-closed telemetry now invalidates the stale nested full-state
  quest dialog immediately.
- Regression: 1756 passed, 4 skipped; live retest remains open.

## 2026-09-24 — learned World3D model connected to live runtime

- Connected `world3d_annotation_assist_combined_1077_v1.pt` to the canonical
  GUI runtime perception path.
- Preserved UNKNOWN-first semantics and the single World3D V2/V3 pipeline.
- Added conservative class-specific confidence thresholds, per-class caps and
  a ten-candidate learned-output budget to reduce preview-style box floods.
- Moved model/CUDA warm-up off the perception lane; cheap CV remains active
  while the learned backend initializes.
- Added runtime model/device/threshold diagnostics and environment overrides.
- Offline regression: 1754 passed, 4 skipped; live validation remains open.

## 2026-09-16 — M0 audit closure: Combat reach, Loot credit, Search and safe stop

- An explicit Combat `OUT_OF_RANGE` response now starts one persistent,
  same-attempt `NavigationService.move_to_entity()` reach when the exact live
  hostile and player have same-instance world coordinates. Arrival revalidates
  the selected GUID before Combat resumes; screen-local correction remains a
  bounded fallback rather than a second movement owner.
- Loot now treats a confirmed before/after quest-objective delta as success
  evidence only when no exact expected item ID was declared. An explicit item
  contract still requires that item; deadline failure is now the typed
  `EXPECTED_ITEM_NOT_RECEIVED`.
- Added direct M0 coverage for Search sector coverage/exhaustion and discovery,
  selected-target destination refresh, Combat facing/lost-target/player-dead/
  timeout paths, and executor-exception safe stop.
- Removed the engine's remaining tick-by-tick legacy CombatController update.
  Combat proposal admission is now stateless, while runtime diagnostics read
  the canonical `ActiveSkillRuntime` combat context.
- Offline regression after this audit: **800 passed, 2 skipped**. This did not
  start a client, addon, or live controller and is not live validation.

## 2026-09-16 — M0 Interact owns approach and retry

- `INTERACT`/`TALK` no longer fail and hand control back to the planner after
  one confirmed client `OUT_OF_RANGE` response. The same active attempt now
  owns `APPROACH -> FACE -> INTERACT -> VERIFY`.
- `NavigationService.move_to_entity()` accepts only an exact selected GUID and
  live, same-instance target/player world positions. It refuses to invent a
  destination from screen pixels and retains the existing persistent movement
  controller as the sole world-space movement authority.
- If world coordinates are unavailable, a bounded fallback uses only a fresh
  GUID-associated World3D/mouseover anchor and the existing per-attempt visual
  servo. No new planner action is created between the range error and the next
  client interaction probe.
- Loot now applies the same-attempt world-coordinate recovery to an exact dead
  target only. A loot UI opening is no longer a completion signal; receipt or
  meaningful inventory evidence is required, and an explicitly declared item
  ID must match the received/gained item.
- Added unit and deterministic-acceptance coverage for the same-attempt
  recovery, coordinate/identity gates, visual-anchor gate, and one-recovery
  budget. This is offline evidence only; no selected client, addon, or live
  controller was started. Full offline regression: **791 passed, 2 skipped**.

## 2026-09-16 — M1 canonical world-object use boundary

- Structured quest world objects no longer emit the generic `USE` proposal.
  They use canonical `OBJECT_USE` through `ObjectUseSkill` and the one active
  M0 dispatch authority.
- Before its one right click, the skill rechecks that the exact current addon
  mouseover object/item identity and normalized cursor coordinate still match
  the intent. A stale crop, moved cursor, or different hovered object fails
  before input.
- `OBJECT_USED` acknowledgement is diagnostic only. The skill succeeds only
  when the declared normalized quest/objective receives credit.
- Complete offline regression: **776 passed, 3 skipped**. No client input,
  controller start, addon install, or live test occurred.

## 2026-09-16 — M1 canonical instructed-spell boundary

- `FOLLOW_INSTRUCTION` no longer has any generic-registry execution route.
  `InstructedSpellSkill` requires one confirmed living hostile target GUID,
  an exact live action-bar spell ID/name/binding matching the fresh NPC
  instruction, and the explicitly selected bindings cache before it sends
  one binding.
- Its only success signal is matching normalized quest/objective credit.
  Casting acknowledgement, cooldown movement, an action-bar row, or a phrase
  that merely resembles a spell name cannot complete the objective.
- `USE_ON_TARGET` was aligned with the same authoritative-cache rule: missing
  selected bindings now blocks rather than allowing a test-only implicit
  execution path. Duplicate legacy lifecycle membership was removed.

## 2026-09-16 — M1 canonical targeted quest-item boundary

- `USE_ON_TARGET` no longer dispatches through the generic registry. The
  canonical `QuestItemSkill` rechecks the selected target GUID, living state,
  exact item ID, current usable action-bar binding and selected bindings cache
  immediately before sending one key.
- The legacy generic verifier can no longer promote an `ITEM_USED` event or a
  cooldown transition into objective completion; `QuestItemSkill` accepts only
  matching normalized quest/objective credit.
- The same canonical boundary now owns `ASSIST` for friendly quest targets and
  rejects harmful action-bar items before dispatch.
- Complete offline regression: **776 passed, 3 skipped**. No live client input
  or controller start occurred.

## 2026-09-16 — M1 exact Extra Action quest-tool boundary

- Addon 0.9.25 exports the visible/usable state plus the actual Extra Action
  slot's `action_type` and `action_id`; the export remains read-only.
- `EXTRA_ACTION` is a canonical active skill. It requires the selected
  bindings cache to contain `EXTRAACTIONBUTTON1`, rechecks the live exported
  action identity immediately before dispatch, and treats only matching quest
  objective credit as success.
- The planner may automatically use only an item-type Extra Action whose ID
  exactly matches the active quest's Quest API `special_item`; other action
  types require an explicit goal policy carrying the same exported type/ID.
  A visible button, UI position, or guessed hotkey is never enough.
- Extra Action telemetry is carried in the FAST lane, but has not been
  installed or live-validated. Complete offline regression: **770 passed, 3
  skipped**.

## 2026-09-16 — M1 explicit gossip/reward transition and ownership cleanup

- `QUEST_DIALOG` no longer has a generic registry click or verifier path; only
  `QuestDialogSkill` may execute it, and old direct calls fail closed.
- Addon-exported `AVAILABLE`/`COMPLETE` gossip rows now become an explicit
  `GOSSIP_SELECT` action.  It must transition to a named action for the same
  quest before ACCEPT/COMPLETE/TURN_IN can run.
- Added the V4 handoff documents: migration status, dead-code audit, M0/M1
  implementation descriptions, test report, and known limitations.
- Multiple offered quest IDs now fail closed until the goal explicitly selects
  one; this policy is isolated in `QuestOfferSelector` rather than embedded in
  Planner.
- Addon 0.9.22 exports bounded reward-choice rows and their UI coordinates.
  `QuestRewardSelector` only permits an exact requested item/index, or a
  separately requested one-choice `FIRST_UNAMBIGUOUS` policy.
- Addon 0.9.23 exports the supported Quest API campaign flag. The runtime may
  continue only an explicit `MAIN_CAMPAIGN` goal into one unambiguous active
  campaign quest; it never guesses from titles, map markers, or side quests.
- Focused regression: 104 passed; complete offline suite: 765 passed, 3
  skipped. Live completion status is intentionally unchanged until
  user-operated evidence exists.

## 2026-09-26 — independent fast perception pump and blind-TAB guard

- Moved live World3D scheduling onto a latest-frame background pump so slow
  planner/SQLite ticks can no longer starve the fast tracker lane.
- Raised the tracker contract to 30 Hz (24 Hz while idle) while retaining an
  independently throttled detector and 4 Hz canonical evidence publication.
- Added explicit target/actual tracker diagnostics and background-worker
  health reporting. Offline measurement on the live-machine code path reached
  23.47 Hz tracker output; live WoW validation remains open.
- Removed quest-domain `TARGETNEARESTENEMY` as a search primitive. The binding
  remains available only as an in-combat defensive fallback.
- A TAB-selected GUID now proves identity only. It cannot become a persistent
  movement target without a fresh screen anchor or positive harmful-action
  range evidence; otherwise the commitment is released with
  `BLIND_TARGET_UNLOCATABLE`.
- An off-screen selected GUID no longer suppresses active World3D search; the
  camera may seek a visible candidate until hover/vision supplies localization.
- Focused target/search regressions pass. Complete repository regression:
  **1801 passed, 4 skipped, 15 pre-existing unrelated failures**; the remaining
  failures are the already-recorded navigation/search fixture debt.

## 2026-09-26 — tracker cadence headroom and live-frame annotations

- Raised the latest-frame perception pump to 120 Hz and tracker-only admission
  to 40 Hz. Detector refresh remains independently throttled and no frame
  queue is introduced.
- Offline production-path measurement improved from 23.47 to **33.11 tracker
  Hz**, with 4.09 detector Hz and 3.76 canonical Hz. Background `update()` p95
  was 0.27 ms; the periodic canonical path remains the only ~9 ms tail.
- Manually reviewed ten PID 8260 live frames. The set contains 24
  `creature_unit_like` boxes, one `corpse_like` box, and one explicit empty
  World Map hard-negative. The own player and UI/nameplates are excluded.
- Export audit: 10 images, 25 boxes, zero invalid/missing/orphan labels, zero
  split overlap, `training_ready=true`.

## 2026-09-16 — M0/M1 V4 audit and Phase A foundation

- Added the V4 repository/authority audit in `docs/M0_M1_V4_AUDIT.md`.
- Repaired the real-screenshot overhead-symbol → subject-probe temporal
  relation regression without assigning NPC/quest semantics to CV output.
- Added canonical typed runtime contracts and `ActiveSkillRuntime`.
- Migrated `AutonomousAgent`'s active `pending` attempt into that canonical
  runtime; the old lifecycle display is now derived state.
- Added the Supervisor interrupt gate and single-threaded runtime event bus.
- Added and adopted `NavigationService` as the active engine's canonical
  route/movement authority.
- Migrated the active `TARGET` execution/verification path to the typed M0
  TargetSkill FSM.
- Migrated `INTERACT`/`TALK`, `COMBAT`/`DEFEND`, and `LOOT` to canonical M0
  skills with pure before/after verifiers. User/manual cancel now closes only
  the canonical active skill after stopping input.
- Added deterministic one-active-skill replay coverage (100 iterations).
- Centralized active-engine timeout resolution and typed bounded retry backoff.
- Added M1 primary-quest ownership, deterministic objective-classification
  facade, and separately recorded quest-credit verification evidence.
- Full offline regression after M1 Phase A: **718 passed, 3 skipped**.
- Extracted M0 skill dispatch and M1 objective location resolution from the
  active engine/planner paths; their targeted regression selection is green.
- Full offline regression after this migration: **710 passed, 3 skipped**.
  No live validation claimed.
- Added a stable M1 primary-objective execution state machine consumed by the
  shared planner, plus bounded no-quest-credit target suppression after a
  successful combat result. Full deterministic regression: **733 passed, 3
  skipped**.
- Migrated bounded `SEEK_VISUAL_CUE` state into the canonical active-skill
  context through `SearchSkill`; engine-owned search state is now diagnostic
  compatibility only.
- Migrated `VISUAL_APPROACH` servo ownership into `VisualApproachSkill` and
  the canonical active-skill context without changing movement tuning.
- Added the Functional Design Specification reconciliation ledger, including
  V4 precedence, UNKNOWN-first perception reconciliation, and per-domain
  ownership/status mapping.
- Added bounded same-attempt combat local recovery: only an identity-matched,
  fresh screen-space target can request `NavigationService` to produce a short
  LOS/range/facing correction, followed by a controlled re-cast.
- Added event IDs, bounded event-bus idempotence and deterministic runtime
  event priority for safety/replay boundaries.
- Migrated `QUEST_DIALOG` to canonical `QuestDialogSkill`; exact addon-exported
  reward rows are now selectable only through the explicit `QuestRewardSelector`
  policy boundary (ambiguous/default clicks remain blocked).
- Added supervisor-owned suspend/resume: a combat interrupt cancels the only
  active skill, then may resume one precondition-valid intent once after the
  interrupt clears. Manual mode/goal replacement discards it.
- Added `TurnInResolver`, which prevents generic memory waypoints from being
  treated as an NPC turn-in destination and preserves field UI/local role
  priority over map-region fallback.
- Added explicit M1 quest stage-transition tracking. A fresh normalized stage
  invalidates the prior objective/location selection before reclassification.
- Full deterministic regression after the current M0/M1 increment: **749
  passed, 3 skipped**. This remains offline evidence only.
# 2026-09-26 — Fast camera tracking and detector cadence

- World3D detector profiles now request 8 Hz balanced, 10 Hz navigation,
  12 Hz quest search and 15 Hz combat refreshes.
- Detector scheduling is start-to-start. The existing single in-flight future
  remains the back-pressure boundary, so inference time no longer receives a
  second unnecessary cooldown and stale frames still cannot queue.
- The CPU patch tracker now accepts larger confidence-validated global camera
  translations and searches a wider residual neighbourhood for perspective
  motion. This addresses track loss while running or rotating the camera.
- Active tracker admission is 45 Hz with a 40 Hz completed-rate target.
- Focused World3D tests: 36 passed. Runtime/profile regression subset: 65
  relevant tests passed after cadence expectations were updated; one unrelated
  pre-existing replay command-count assertion remains outside this change.
# 2026-09-26 — Learned humanoid inspection handoff

- Stable `humanoid_unit_like` / `creature_unit_like` detections now remain
  UNKNOWN but become eligible for mouseover INSPECT at confidence 0.22 after
  three stable frames and at the model admission threshold after six frames.
- A nameplate is no longer a mandatory gate for learned subject proposals.
- Self-avatar attention suppression, combat target ownership, temporal
  stability, rejection memory and mouseover semantic confirmation remain in
  force.
- Focused inspection/seek/target regression: 72 passed.
# 2026-09-26 — Five-percent learned subject admission

- Runtime YOLO admission for `humanoid_unit_like` and
  `creature_unit_like` is now `0.05`.
- A temporally stable learned subject uses the same `0.05` gate for INSPECT;
  it remains UNKNOWN until mouseover/addon confirmation.
- Other class thresholds, self-avatar suppression, per-class box budgets,
  temporal stability and rejection memory are unchanged.
- Focused regression: 55 passed.

# 2026-09-28 — Quest-offer reward preview classification

- Addon `0.9.34` no longer interprets `GetNumQuestChoices()` as sufficient
  evidence of a selectable reward dialog. Retail may expose a reward preview
  while the quest-detail `Accept` button is visible.
- `REWARD_SELECT` is now exported only in a visible completion/turn-in
  context, and a visible `QuestFrameAcceptButton` takes precedence over stale
  completion hints.
- Focused addon/quest-dialog/reward regressions: **38 passed**. Live validation
  remains pending.

# 2026-09-28 — Combat FAST fallback preserves defensive response

- Addon `0.9.35` adds a bounded combat-priority FAST fallback. A field-rich
  hostile target can no longer evict `is_in_combat`, player life state, exact
  target identity, or the four-slot `actionbar_fast` readiness data.
- This prevents ability admission from degrading to `cooldown_unknown` and
  prevents quest-map MOVE from resurfacing while the player is being attacked.
- Focused transport/combat/interrupt regression: **112 passed**. Live
  validation remains pending.

# 2026-09-28 — Post-combat MOVE wall-contact detection

- The movement progress score no longer treats Retail's
  `moving=true/speed=7` run-animation state as proof of physical translation.
  Positive progress must come from position/visual displacement evidence;
  a stopped flag remains valid negative evidence.
- A commanded running state combined with an unchanged authoritative position
  is recorded as `MOTION_POSITION_MISMATCH`, allowing the existing bounded
  stuck-recovery path to activate.
- Turn-only heading corrections pause accumulated no-progress evidence;
  forward soft-steering no longer clears it. Focused navigation/resume
  regression: **58 passed**, with one unrelated existing quest-POI planner
  fixture deselected.
# 2026-09-28 - Navmesh cliff-transition rejection

- Live Exile's Reach evidence showed the mmap route jumping from `z=59.5` to
  `z=69.1` over only 7.7 horizontal yards at the Quilboar Briarpatch. Retail
  collision rejected that approximately 45-degree transition and the agent
  repeatedly ran into the cliff.
- Polygon A* now rejects transitions at or above the observed unwalkable
  slope and searches for a gentler connected mmap corridor. It still fails
  closed when no supported route exists; no direct-line fallback was added.
- Added a regression proving that a 45-degree shortcut is rejected in favour
  of a supported flat detour. Focused mmap/navigation regression: **88
  passed**; live validation remains open.

# 2026-09-28 - Targeted quest special items outside the action bar

- Addon `0.9.36` preserves Retail's raw `monster` objective type but
  normalizes it to `USE_ITEM` when the authoritative quest-log special-item
  name occurs exactly in the objective text. This fixes objectives such as
  `Re-Sizer v9.0.1 tested on Wandering Boars` without quest-ID hard-coding.
- The shared quest planner and canonical `UseItemSkill` now support an exact
  active-quest special item from a visible bag slot when it is absent from the
  action bar. The path opens bags, revalidates item ID + bag + slot + addon UI
  coordinate, right-clicks once, and still requires objective-progress credit.
- Focused addon/quest/planner/skill regressions: **72 passed**. Addon package
  `0.9.36` was installed byte-identically; live validation remains pending
  after `/reload` and a user-operated FULL_AI run.

