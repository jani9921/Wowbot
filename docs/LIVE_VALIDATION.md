# Live validation evidence and unresolved issues

## 2026-10-01 — World Map / minimap marker YOLO pipeline (offline-tested; no model trained; live open)

**Measured cause of "the map sees nothing"** (`tools/measure_map_marker_detection.py`,
report `output/map_marker_measurement_2026-10-01.json`, PID 3324 captures):

* 2010 live-capture frames scanned, **29** show the full-screen World Map (all
  Exile's Reach, map 1409, during `OPEN_MAP` / `WAIT` after `OPEN_MAP`).
* **0 of 29** had an active quest at that tick (`active_quests == []`), and visual
  inspection shows **no quest pin of any kind drawn** on these maps: no `!`
  offer, no `?` turn-in, no blue objective region. The only map icon is the
  player arrow. While standing next to a quest giver with a `!` overhead in
  3D, the World Map showed no offer pin there either. So either this
  server/client does not render quest-offer pins, or the World Map filter has
  them off. **This has to be checked in the game by eye.** No detector, learned
  or heuristic, can find pins that are not rendered.
* The heuristic detector is not blind. It found the player arrow on **29/29** frames,
  and the addon player position projected through the canvas landed within
  **median 1.09 px / max 1.74 px** of it. It also emitted **1127
  `gold_glyph_like` blobs (~39 per frame)**, and all of them are false
  positives on parchment art and labels. That is noise for the inspection
  planner, not quest evidence.
* The hard-coded map frame (`.055/.115/.945/.965`) was about 4% off vertically
  for this layout. The perception lane now uses the estimated canvas
  (`estimate_world_map_canvas`) for `map_local_position`/`map_local_bounds`,
  with the legacy frame as fallback.

**Implemented (offline-tested only):**

* `src/wowbot/vision/map_markers.py` defines the shared class table for both
  surfaces: `quest_available`, `quest_available_repeatable`,
  `quest_available_special`, `quest_turn_in`, `quest_turn_in_repeatable`,
  `quest_objective_pin`, `quest_area`, `quest_edge_arrow`, `player_arrow`.
  The module also holds the crop geometry, the weak review proposals and
  `LearnedMapMarkerDetector`. Learned boxes stay UNKNOWN map markers that
  carry appearance labels (`quest_available_like`, `blue_region_like`, ...);
  quest semantics still need the addon (tooltip / quest log / POI API).
* Runtime integration goes through the existing seams only, with no new brain.
  `WorldMapMarkerDetector` uses the model once its status is `ready`;
  learned markers replace the gold-glyph blobs, and heuristic blue areas are
  kept unless a learned area covers them. `PerceptionWorker._minimap` merges
  learned markers with the proven heuristic minimap markers. The model files
  are `models/world_map_markers.pt` / `models/minimap_markers.pt`, or the
  `AIPC_WORLD_MAP_MODEL` / `AIPC_MINIMAP_MODEL` env vars;
  `AIPC_MAP_MARKER_MODEL=0` disables them. **No model file exists, so runtime
  behaviour is unchanged apart from the map-local canvas fix.**
* Live collection: `MapMarkerCropCollector`
  (`output/agent/pid-*/map-marker-dataset/{world_map,minimap}`). It saves
  full-resolution crops while the map is open (every 1.5 s) or while the
  minimap is visible (every 4 s), deduplicated, with addon facts and
  proposals. The proposals are the player arrow, quest POIs/waypoints
  projected only when the player projection is verified, tooltip-confirmed
  hover pins, and heuristic blue areas. Encoding runs on a daemon thread with
  a bounded queue and drops on full, so it stays off the agent step.
  `AIPC_MAP_DATASET=0` disables it. Measured cost is about 130 ms per 1080p
  sample on that thread.
* Labelling workflow: `tools/build_map_marker_review_pool.py` →
  `tools/review_map_marker_annotations.py` (OpenCV, keys 1–9, zoom, addon
  facts shown) → `tools/train_map_marker_yolo.py`. The train tool exports
  whole-session splits, runs the shared structural audit, then applies a
  **quest-class coverage gate**: at least one quest class must have ≥20 train
  and ≥3 val reviewed boxes. A player-arrow-only model is refused.
* The 29 map-open captures were bootstrapped into
  `datasets/map_markers_world_map` (29 unreviewed crops, player-arrow
  proposals only, `downscaled_capture` provenance).
* Tests: `tests/test_map_marker_learning.py` has **17 passed**. Full suite:
  **18 failed / 1981 passed / 4 skipped**. All 18 failures are pre-existing
  and unrelated (quest/movement planner tests and module-size limits;
  `runtime.py` was already 653 lines against the 600 limit before this change).

**Not done / open:**

* **No model trained.** There are zero positive quest-marker examples in any
  recorded frame, and the training gate correctly refuses.
* Needed live data (user-operated): first confirm in game that quest pins are
  visible on the World Map, using the map filter (funnel icon) → quest
  options. Then play with quests in all states: available givers nearby,
  accepted with objective areas, ready for turn-in. Open the map at several
  places and hover pins. The collector records everything automatically.
  Review at least ~150 World Map crops and a few hundred minimap crops, then
  train.
* The canvas estimator only recognises the full-screen map with black
  margins. Windowed or zoomed maps fall back to the legacy frame, and POI
  projection is then reported as unverified. An addon export of the map canvas
  rect would remove this limit.
* The addon pixel strip overlaps the top-left of the map crop; the model
  must learn it as background.

## 2026-09-29 — BoT-SORT World3D identity continuity (offline-tested, live open)

The user-operated PID 9668 trace showed that detector throughput itself was
healthy, but the restored continuous-detector pipeline repeatedly replaced
visual IDs. The local association gate compared each fresh box with a narrow
position/scale/appearance window; camera motion and frequent full/foveal
refreshes therefore produced new upstream IDs. One Jaina track survived three
automatic hover confirmations and then ended as
`visual_track_lost_identity_reconfirmation_missing`. Separate logged
`capture_context_or_roi_changed` events correctly explain hard resets around
map/modal transitions, but not the within-context fragmentation.

The production learned-detector path now associates canonical client-pixel
boxes through Ultralytics BoT-SORT with sparse-optical-flow global camera
motion compensation, Kalman prediction, a 30-refresh lost-track buffer and a
subject/symbol/object family gate. The WorldModel/fusion layer remains the
canonical semantic identity authority; tracker IDs are still visual evidence,
not named-entity facts. Continuous latest-frame YOLO and the CPU patch tracker
remain enabled.

Ultralytics' first tracker import measured roughly nine seconds in a fresh
Python process, so it now warms in the background. Legacy association remains
active during warm-up, and native tracks inherit the already-published public
IDs at cutover. A saved 1105x573 WoW sequence measured **10.14 ms median / 14.77
ms p95** BoT-SORT+GMC association overhead and retained one ID across all 30
benchmark frames. Synthetic acceptance covers a 35-pixel camera pan, a
five-refresh detector gap, overlapping subject/symbol boxes and non-blocking
warm-up/public-ID handoff. Focused World3D/perception regression: **188 passed,
2 skipped**.

Status: **OFFLINE-TESTED, LIVE OPEN**. A restarted, user-operated MANUAL/FULL_AI
run must confirm stable IDs during real camera turns, full/foveal alternation
and brief occlusion. No client input was taken over and no FULL_AI process was
started or left running for this change.

## 2026-09-28 — GUI freeze during telemetry startup (offline-tested)

Inspection found that the Connect button constructed the complete
`AgentRuntime` synchronously inside Tk's event callback. Opening the large
memory databases and building navmesh, capture, telemetry and perception
therefore prevented Windows message processing and made the GUI appear hung.

Runtime construction/startup now runs in one dedicated connection worker and
hands the completed runtime or error back through a thread-safe queue. The Tk
loop remains active and displays elapsed startup time. Reconnect still revokes
the previous runtime's input immediately by switching it to MANUAL before the
slow close runs. This is **LIVE OPEN** pending a user-operated start with the
current selected PID; offline GUI tests prove that a deliberately blocked
runtime constructor does not block `connect()`.

Follow-up run `live-debug-20260928-135752.jsonl` proved a second freeze path:
there was an approximately seven-second diagnostic gap around the second
FULL_AI request. Runtime mode changes could wait for the agent lock in Tk's
callback, and live-capture rotation could join the encoder. Goal/mode/test
controls are now serialized through a background GUI control worker, while
capture rotation uses a bounded two-item queue with per-frame segment paths
and performs no join. At handoff the old running process still contains the
pre-fix code; another GUI restart and user-operated re-arm are required.

## 2026-09-28 — Quilboar Briarpatch cliff route (live root cause, fix offline-tested)

In the user-operated selected-PID 10516 run, MOVE repeatedly stopped near
world `(-10.5, -2573.2)` while targeting mmap waypoint
`(-12.8, -2566.9)`. The stuck detector and bounded backward recovery both
worked, but replanning selected the same polygon corridor. Reconstructing the
exact route from `mmaps.zip` showed an adjacent-polygon transition from about
`z=59.5` to `z=69.1` over 7.7 horizontal yards (approximately 45 degrees).
Retail collision did not permit that climb.

Polygon A* now rejects links at or above the observed unwalkable slope and
selects a longer westward corridor for both quest 55184 and quest 55186.
Focused mmap/navigation regression passes offline. This remains **LIVE OPEN**:
a restarted-agent run must demonstrate that the new corridor clears the cliff
and does not create a new wall-contact loop at a later waypoint.

## 2026-09-26 — opaque WAIT and repeated World Map scan (live root cause, fix offline-tested)

In selected-PID run 8260 (`live-debug-20260926-180427.jsonl`), ACQUIRE_TARGET
selected the attackable Combat Dummy at 18:05:30. The controller first waited
briefly for the committed subgoal and then emitted the generic "quest waypoint
/ confirmed object / available skill" WAIT until 18:05:58. Telemetry shows the
actual unavailable capability: Slam was `is_usable=false`,
`lacks_resource=true`; Attack was present as spell 88163 but had no exported
action/binding. Thus COMBAT existed as a proposal but failed admission.

The map reopened because the first scan persisted an objective-tracker tooltip
as a map location: `x=1.0`, `y=.153`, tooltip "Warming Up ... 0/1 Destroy a
Combat Dummy". Although unconfirmed and on the outer UI edge, its
`marker_associated=true` flag kept `map_search_exhausted=false`. Once the
30-second OPEN_MAP recent-action gate expired, the fallback policy performed a
second scan, five zoom steps and a parent-map attempt.

The correction rejects outer-edge tooltip coordinates from spatial map memory
and current-scan success, prevents map fallback while a living attackable
target is selected, and makes fallback WAIT report whether it needs a usable
combat action/resource, map cooldown, domain strategy or new evidence. Focused
regression: **163 passed**. This is **LIVE OPEN** pending a restarted-agent run
that proves one unsuccessful map scan becomes exhausted and is not repeated
without a quest/map/session revision. No addon update is required.

## 2026-09-26 — Exile's Reach Jaina acquisition (live, unresolved)

The user-operated selected-PID run (`pid-8260`, capture session
`20260926-174509-727-003`) showed Lady Jaina and a large overhead `!` in clear
view. At 17:45:21--22 `SEEK_VISUAL_CUE` had only one stable World3D track and
failed with `visual_track_lost`; it then interacted with the player `Poong`
instead of acquiring Jaina. Offline replay of the exact captured frames with
the production v4 model confirmed that the marker was absent in the first two
frames and appeared later at only 0.06 confidence, below the former 0.08
runtime class gate. Closer centered frames produced 0.19--0.35 overhead-symbol
confidence. Jaina entered addon target telemetry only after the user manually
selected her, so autonomous questgiver acquisition is **not live validated**.

The raw and overhead evidence gates were subsequently lowered to 0.01 while
all non-symbol class gates remained unchanged. This is offline-tested only;
the required retest must prove that the weak cue creates a persistent UNKNOWN
symbol/subject group and that `SEEK_VISUAL_CUE` approaches that group without
selecting another player. The same retest must also validate the replacement
one-way camera sweep (160 ms bounded drag, 900 ms observation interval); the
earlier live run's rapid alternating camera motion is not accepted behavior.

## 2026-09-23 — quest-area arrival evidence (offline only)

Target-scoped quest/objective progress now feeds the canonical arrival gate,
including correct behavior on a multi-waypoint route. Complete regression:
**1601 passed, 3 skipped in 62.00 seconds**. No client input was sent. A live
REACH_AREA objective still must prove Retail event timing and route handoff.

## 2026-09-23 — visual arrival evidence producer (offline only)

Production REACH now consumes target-associated bbox growth as weak evidence.
Full suite: **1595 passed, 3 skipped in 50.32 seconds**. No client input was
sent. Live inspection must establish real anchor freshness/camera availability
and scale reliability; unit/controller tests do not prove field accuracy.
Minimap/interaction/quest-area/map-transition producers remain open.

## 2026-09-23 — arrival envelope correction (offline only)

REACH honors explicit arrival_radius; stop_distance retains precedence.
Missing evidence no longer indefinitely latches ARRIVED, and invalid numeric
evidence cannot confirm arrival. Complete regression: **1588 passed, 3
skipped in 55.34 seconds**. No client input was sent. DESIGN-031 visual
sensor wiring and selected-PID calibration remain open.

## 2026-09-23 — quest-credit false-positive corrections (offline only)

Counter regression, changed requirements, late objective visibility, missing
stage metadata and retained turn-in events no longer confirm new quest
credit. Baseline return values cannot mutate the verifier's internal copy.
Full regression: **1581 passed, 3 skipped in 65.96 seconds**.
No client input or live test occurred.

Audit correction: the earlier canonical-arrival entry describes tested
verifier capabilities, not complete runtime sensor integration. No producer
of arrival_evidence exists yet; DESIGN-031 remains PARTIAL pending that work
and target-scoped end-to-end validation.

## 2026-09-23 — typed quest progress states (offline only)

Quest start and ongoing objective progress now have distinct typed outcomes,
alongside objective completion, stage change, ready-for-turn-in and final
completion. The complete offline suite passed **1574 tests, 3 skipped in 83.49
seconds**. No client input was sent. A user-operated run must still verify the
Retail event/order combinations for accept, counter advance, stage transition
and turn-in.

## 2026-09-23 — canonical arrival verifier (offline only)

The production REACH path now uses the evidence-fused, hysteretic
`ArrivalVerifier`; focused tests passed 32/32 and the complete regression
passed **1570 tests, 3 skipped in 67.47 seconds**. No client input was sent and
no live row was closed. A user-operated selected-PID run must still calibrate
distance envelopes and confirm noisy minimap/bbox/interaction transitions do
not create premature arrival or threshold chatter.

## 2026-09-23 — World Map hierarchy/resolver wiring (offline only)

The addon now exports Retail `parentMapID` hierarchy and the FAST lane carries
the active/parent map context. The canonical map policy can perform a bounded
parent-level step and accepts it only after fresh addon context confirms the
expected parent. Focused and complete offline suites passed (**1554 passed, 3
skipped**). No addon was installed, no client was controlled, and no live row
was closed. A user-operated test must confirm one local-map → parent-map step,
marker reacquisition, map restoration and fail-closed behavior when filters or
hierarchy prevent discovery.

## 2026-09-23 — World3D implementation block (offline only)

No Retail client test was run in this block. Long-gap visual
re-identification, scene-quality/change evidence, semantic
fusion/hysteresis/freshness, lifecycle/failure feedback, context scheduling,
and graphical replay rendering passed the complete offline suite (**1535
passed, 3 skipped**). This closes no selected-PID row. Stationary, approach,
occlusion, camera-turn, door/collision, and long-run threshold behavior still
require user-operated live validation.

## 2026-09-22 — Correlated client errors (offline only)

Addon 0.9.26 now emits `UI_ERROR_MESSAGE` as a normalized event and exports
`ui_error_at`, `ui_error_code` and `ui_error_sequence` on both FULL and FAST
telemetry lanes. The Python action correlator snapshots the sequence at cast
dispatch and accepts only a later sequence as evidence for that attempt. This
allows repeated identical LOS/out-of-range messages to remain distinguishable
without assuming the addon and Python monotonic clocks share an epoch.

No addon copy/install/reload or client input occurred. A user-operated live
test must confirm that one deliberately out-of-range cast and one obstructed
LOS cast each advance `ui_error_sequence`, preserve the selected target GUID,
and enter the matching bounded recovery. Localized message classification and
end-to-end pixel-strip latency remain `LIVE_OPEN`.

## 2026-09-16 — Canonical world-object use (offline only)

The M1 structured world-object route now reaches `ObjectUseSkill` as
`OBJECT_USE`. Before the single screen-space right click it checks the current
addon mouseover identity and precise cursor sample, then waits exclusively for
matching normalized quest credit. An `OBJECT_USED` event is intentionally not
success evidence. No client input, addon change, controller start, or FULL_AI
session occurred.

A future user-operated live test should use a nearby, tooltip-confirmed quest
object and preserve the log sequence: fresh object/cursor match → one dispatch
→ matching objective credit. It must also prove that a stale hover does not
click a different object.

## 2026-09-16 — Instructed spell / selected-cache gate (offline only)

`FOLLOW_INSTRUCTION` is now executed exclusively by `InstructedSpellSkill`.
Before any live input it requires the selected cache, the exact current
action-bar spell ID/name/binding, a fresh explicit instruction, and the same
confirmed living hostile target GUID. Success requires normalized quest credit.
The targeted quest-item path was tightened to the same cache requirement. No
client input, addon installation/reload, controller start, or FULL_AI session
occurred for this change.

A future user-operated live test must show the fresh instruction, selected
cache binding, exact target identity and post-cast objective credit in the log.
An observed cast or cooldown is explicitly insufficient.

## 2026-09-16 — Extra Action quest tool (offline only)

Addon 0.9.25 adds a read-only Extra Action export: visible/usable, canonical
`EXTRAACTIONBUTTON1`, and the action slot's type/ID where the Retail API makes
them accessible. The agent's canonical `QuestToolSkill` uses it only after an
exact identity match and a selected-cache binding preflight; success requires
quest-objective/quest credit. No addon copy/install/reload, client input,
controller start, or FULL_AI session occurred for this implementation.

The next user-operated live test must first confirm that a 12.1 client exports
the same Extra Action type/ID across several FAST samples. Only then may a
single active quest whose `special_item.item_id` exactly matches the export be
tried, with logs proving both the dispatched binding and subsequent quest
credit. A visible action button, input acknowledgement, or UI state change is
not acceptance evidence.

## 2026-09-16 — Targeted quest item (offline only)

`USE_ON_TARGET` now has a canonical item-skill boundary. A future user-operated
live test must demonstrate the same selected target GUID and current action-bar
item/binding immediately before input, then a matching normalized quest credit
after input. An `ITEM_USED` event, cooldown change, cast acknowledgement, or
manual player progress is insufficient. No client input or controller start
occurred while implementing this boundary.

## 2026-09-08 — user-run test / log-only inspection

The user tests and controls the WoW client. The assistant must not take over,
send input or start FULL_AI. Latest user clarification: focus was changed only
AFTER the controller stopped. A later `selected_PID_not_foreground` status is
therefore not evidence that focus loss caused the original stop.

Evidence inspected: `output/agent/pid-1284/agent_status.json` and the read-only
SQLite journal/observations in `output/agent/pid-1284/agent_memory.sqlite3`.

- The recorded stop was MANUAL / `telemetry_missing_or_stale`; the last INSPECT
  failed with `telemetry_stalled`. Why fresh observations stopped is unresolved.
- Last observation at monotonic 1783564.2584893, followed by the INSPECT failure
  at 1783566.352. Earlier observations had a fresh state; this does not establish
  uninterrupted delivery during the final attempt.
- The target was Bjorn Stouthands, map 1409. A preceding interaction reported
  `You need to be closer to interact with that target.` Friendly approach is not
  live-validated and that quest interaction must not be recorded as completed.
- Repeated TARGET/INSPECT successes are not completed quests. The log contained
  no accepted active quest at the final observation.
- Generic visual and obstacle hypotheses were being probed. Untracked candidates
  and parameter-jitter-dependent keys could defeat retry cooldowns.
- The user explicitly states the earlier **3/6 quest-item progress was manually
  looted by the user**, not the bot. Autonomous corpse/quest-item looting is NOT
  accepted as working.

## 2026-09-08 — offline vision fixes after that report

See VISION_PRECISION.md for implementation, measurements and limitations. This
milestone used code, logs and synthetic tests only; no new live test was run.
The controller was not started/restarted and no game input was sent. No change
was made to the user's selected bindings-cache or PID selection.

Next user-run acceptance must establish: bounded fresh telemetry through actions,
world/minimap processing latency, rejected terrain false positives, genuine
mouseover identities, approach within interaction range, quest acceptance and
actual inventory/quest-item increments after bot-initiated looting. None may be
inferred from synthetic replay or manual user progress.

A later read-only status snapshot (file modification time 05:36:32 local) showed
MANUAL, PID 1284, with a CANCELLED start: fresh addon data and the selected PID in
foreground were required. This is a later start rejection, not the original
INSPECT stop above. The assistant did not initiate that start.

Final offline regression: 191 passed, 2 skipped. The skipped tests require
optional real minimap-treasure and Exile's Reach map screenshot fixtures absent
from this archive; those visual cases have therefore not been validated.

## 2026-09-08 — map/minimap discovery integration (offline)

The user reports visible quest markers and tooltips on both map surfaces, but no
useful bot response. Read-only journal inspection found two MINIMAP_CV
quest_giver INSPECT intents at monotonic 1783530.6516053 and 1783563.5045834 among
the last 160 available action intents. This establishes that probes were issued,
NOT that the marker was identified or its quest accepted. The saved status still
had the old `vision: ready` format rather than the new per-lane diagnostics.

Code-level causes: only CLOSE_MAP existed; open maps were immediately closed;
world-map CV was not connected to the agent's perception loop; minimap probes had
low priority; plain quest titles classified UNKNOWN were discarded by spatial
memory. These are now addressed in the existing planner/perception/skill path.

New offline coverage (10 tests) includes priority minimap hovering; explicit
selected-cache map binding; map-open telemetry verification; waiting for map CV;
four-probe / ten-second planning budget; preserving a plain quest title associated
with a CV marker; retaining a minimap NPC name without inventing world position;
and a RecordingExecutor runtime round trip OPEN_MAP → INSPECT → CLOSE_MAP → MOVE
using addon-reported map coordinates. No actual keyboard/mouse input was sent.

Map discovery uses a 30-second retry cooldown. The existing coarse world-map
detector is reused and its screen-coordinate candidates remain hypotheses;
normalized navigation coordinates come only from addon WORLD_MAP mouseover.
Minimap local coordinates are never used for world movement or 3D target clicks.
Map tooltip association is labelled CV_MARKER_AND_ADDON_TOOLTIP, confirmed=false;
the original addon payload is retained unchanged. A pending bounded probe can
finish after the map's ten-second planning budget before the next close decision.

Full regression before the final map-state freshness guard: 201 passed, 2 optional
real-image tests skipped. No new live acceptance. Restart only the controller to
load these Python changes; no addon change/reload was needed. The user remains in
control of live testing, and autonomous quest acceptance/looting is still unproven.

## 2026-09-08 — binding inventory (offline only)

Added read-only full binding inventory in addon SavedVariables and repeated
16-row telemetry pages; controller stores client_bindings.json with actionbar
associations and selected-cache differences. Details: BINDING_INVENTORY.md.
The selected bindings-cache was not changed. No client input, addon installation
into the WoW directory, or FULL_AI start was performed. New Bindings.lua and TOC
must be installed/reloaded by the user before testing; old addon versions report
waiting_for_addon_catalog. Complete live export and its latency are unvalidated.
Final regression: 203 passed, 2 optional image-fixture tests skipped. The addon
mock now loads Bindings.lua in TOC order before the main exporter.

## 2026-09-08 — explicit controller-cache generator (offline)

Added a GUI generator that requires MANUAL, no pending/armed action, matching
PID/session/character, a complete in-memory inventory and receipt age <=30 s.
It writes a unique separate cache and provenance file, rejects key conflicts and
malformed rows, and never changes the authoritative account file or current
executor. Selecting the generated file requires an explicit GUI confirmation;
loading it requires reconnection. See BINDING_INVENTORY.md.

Read-only output inspection found no client_bindings.json yet, so no actual
live-derived controller cache was generated during this turn. No live client
input or GUI operation was performed. Synthetic export tests exercise exact key
preservation, secondary/unbound keys, identity/freshness/completeness rejection,
conflicts, injection and non-overwrite behavior.

## Binding context conflict correction (offline)

User screenshot reports duplicate key 1. Read-only inspection of the complete
pid-17572/client_bindings.json found ACTIONBUTTON1 and
HOUSING_TOGGLEBASICDECORMODE both claiming it. No key was changed. The addon now
exports GetBindingAction(key, false, Enum.BindingContext.None) for each key.
For duplicate claims the generator requires consistent nonempty client evidence
on every claimant, and preserves only the confirmed action. Missing/conflicting
evidence remains a blocking error. Category labels alone never resolve conflicts.
Old exports require updated Bindings.lua plus reload and a fresh catalog cycle.
The updated addon is packaged, not installed into the user's client directory.
Lua context-argument and Python conflict-resolution tests cover this correction;
actual live generation with the updated export remains unvalidated.

## Coordinate consistency correction — offline

An INSPECT requested normalized client (0.856747,0.825338); later addon cursor
samples were (0.911419,0.826568) and (0.917647,0.842558), the latter with Lady
Jaina Proudmoore tooltip. This is a mismatch, not proof of a DPI cause or proof
that the cursor was not moved externally. No live cursor test was performed.

Capture and WindowsInput.move now both enter thread-local PER_MONITOR_AWARE_V2
and restore the previous context, including on exceptions. Failure refuses the
operation. Physical pixel conversion uses width/height consistently with CV
normalization and clamps endpoints; negative desktop origins are supported.
Both paths recheck the foreground HWND. No global GUI DPI setting is changed.
Status adds sensor_diagnostics.capture_geometry and input_coordinates for the
next user-run comparison. Offline tests cover 1600x900/1445x813/1920x1080 pixel
round trips, negative origins, invalid coordinates and DPI-context restoration.

Reference: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddpiawarenesscontext
This is not a confirmed fix for exclusive-fullscreen capture or addon UI scale.
Restart only the controller; no addon modifications in this milestone.

## 2026-09-08 — detailed master M2–M7 foundation (offline only)

Addon, player, quest, mouseover, tooltip, minimap CV, world-map CV, WORLD3D,
spatial-memory and entity-memory evidence now have separate immutable Observation
records and explicit correlation/independence provenance. Visual detections use a
shared UNKNOWN track lifecycle; detector labels remain hypotheses. Identity,
location, dynamic role, state and appearance are separate WorldModel stores.

3D source-frame signatures are integrated into the runtime. Only an
addon-identified mouseover at the inspected track can associate an appearance;
three repeated associations are required before EntityMemory returns a SUPPORTED
candidate. Detector semantics are excluded from the appearance hash.

No client input, addon install or live validation occurred. This does not mark
M2–M7 complete. Full regression after the increment: 238 passed, 2 optional image
tests skipped. Detailed limitations: M2_M4_FOUNDATION.md and M5_M7_FOUNDATION.md.

## 2026-09-08 — detailed master M8–M14 foundation (offline only)

Added first-class persisted events, explicit quest lifecycle, structured quest and
objective graph, separate Plan/subgoal lifecycle, expanded SkillContract,
PredictionError and linked VerificationRecord. The planner consumes dependency-ready
quest graph nodes. Verification rejects distance-increasing MOVE and unrelated
Fishing spellcasts, and restricts loot objective progress to linked quests.

No live client action or acceptance occurred. These milestones remain partial;
open gates are recorded in M8_M14_FOUNDATION.md. Full regression after the
increment: 248 passed, 2 optional image tests skipped.

## 2026-09-08 — detailed master M15–M19 foundation (offline only)

Added context-scoped procedural trials, complete task episodes, conservative
verified pattern promotion, information-gain/cost active perception, bounded
Ollama advisory Observations, stale-AI rejection and dynamically weighted sensor
health/calibration. Generic probe yield is no longer misreported as detector
accuracy; detector precision needs explicit addon semantic ground truth.

No client input, addon install or live validation occurred. No learned pattern,
Ollama decision or calibrated detector is accepted for live autonomy. Remaining
gates are listed in M15_M19_FOUNDATION.md. Full regression: 263 passed, 2 optional
image tests skipped.

## 2026-09-08 — detailed master M20–M23 foundation (offline only)

Added typed interaction/combat capabilities, conservative persistent resource-site
learning, supported-site planner retrieval, COMBAT-versus-DEFEND intent and
configured low-health defensive preference. Existing movement behavior was
re-audited as a progress-verified short-pulse loop; unknown obstacle candidates
remain non-actionable instead of being promoted to walls.

No client input or live validation occurred. Movement obstacle handling, complete
gathering/fishing cycles and combat completion remain open. Details are in
M20_M23_FOUNDATION.md. Full regression: 268 passed, 2 optional image tests skipped.

## 2026-09-08 — detailed master M24–M27 foundation (offline only)

Added non-independent Dungeon/PvP knowledge layers, explicit Plan confidence,
typed failure classification, persistent explainable GoalManager tasks, bounded
UNRESOLVED handling and passive high-level-goal/task restoration. All action paths
still pass through the common planner, registry, prediction and verification loop.

No client input, dungeon, battleground or endurance test occurred. This is not
autonomous Dungeon/PvP or long-run acceptance. Remaining gates are recorded in
M24_M27_FOUNDATION.md. Full regression: 273 passed, 2 optional image tests skipped.

## 2026-09-08 — typed WorldModel graph, aging and pattern novelty (offline only)

Added immutable typed WorldQuery reads, evidence-linked typed graph relations,
age-gated visual/world-point retrieval and supported task-pattern similarity.
GENERALIZED patterns now require distinct contexts. Planner target/resource/track
reads have begun migration to the query facade.

No client input or live validation occurred. Relations are persisted per session,
but the graph is not yet complete or reconstructed by replay, and not every raw
state read has migrated. Full regression: 279 passed, 2 optional image tests
skipped.

## 2026-09-08 — quest semantics and relation replay follow-up (offline only)

Expanded generic localized objective semantics, structured target/item/event
extraction, quest-level dependencies, strict conditional gates, optional priority
and shared TALK/INTERACT/USE proposals. Offline replay now has assertions proving
that relations are rebuilt from observations and persisted for that session.

No client input or live quest validation occurred. Text ambiguity remains UNKNOWN,
and this does not prove arbitrary quest completion. Full regression: 283 passed,
2 optional image tests skipped.

## 2026-09-08 — obstacle and resource lifecycle follow-up (offline only)

Added conservative three-failure obstacle promotion, alternative MOVE selection,
full-inventory gating, explicit inventory-return destination, fishing lifecycle,
source-linked loot, object-use verification and combat objective-progress outcome.
Unknown visual masses still do not become obstacles without movement evidence.

No client input or live validation occurred. Vendor operations are intentionally
absent without an explicit safe item policy. Full regression: 291 passed, 2
optional image tests skipped.

## 2026-09-08 — visual counterexample demotion (offline only)

Visual identity memory now records both confirmed associations and explicit
counterexamples. One mismatch preserves a minimally supported candidate; repeated
contradictions can remove it from actionable re-identification while retaining
its audit history. More planner perception/location reads moved to WorldQuery.

No live recognition accuracy or concept-drift response was measured. Full
regression: 292 passed, 2 optional image tests skipped.

## 2026-09-08 — semantic/behavior/topology and UNKNOWN perception follow-up (offline only)

Added persistent context-scoped semantic facts, phase-aware NPC sightings,
conservative stationary/patrol hypotheses and evidence-gated map topology.
Verified movement now records directed traversed segments. Minimap direction
arrows are non-hoverable, the outer frame band is excluded from generic probes,
and color-agnostic UNKNOWN minimap candidates require temporal stability before
mouseover. World3D can create UNKNOWN entity tracks without a nameplate; any
nameplate signal is recorded only as secondary evidence. Minimap crops now use
their own visual-signature representation space and are trainable only from an
exactly associated addon-identified mouseover unit.

No client input or live validation occurred. In particular, this does not yet
prove that the live selected-target dot, NPC silhouettes, minimap geometry, or
cursor exclusion work at the user's current UI scale. Full regression: 305
passed, 2 optional image tests skipped. Follow-up association/selected-target
regression: 308
passed, 2 optional image tests skipped.

## 2026-09-08 — first-class derived lifecycle events (offline only)

WorldModel track appearance/stabilization/loss, entity appearance/location change
and material belief changes now produce provenance-linked `EventRecord` objects
and persist through the shared event store. Tests cover three-miss visual loss,
observation linkage, entity movement and persistence.

No live client event ordering or long-run event-volume test occurred. Full
regression: 310 passed, 2 optional image tests skipped.

## 2026-09-08 — predictive WorldModel follow-up (offline only)

Added typed non-action entity-persistence predictions, later-observation
verification, explicit `UNOBSERVED` expiry, mismatch-generated prediction error,
calibrated future confidence and model revision. Absence alone is tested not to
become negative evidence.

No live entity-persistence calibration occurred. Full regression: 312 passed, 2
optional image tests skipped.

## 2026-09-08 — quest-effect prediction and replay hydration (offline only)

`QUEST_ACCEPTED` now predicts a quest-ID-linked map marker and distinguishes
verified, sufficiently observed mismatch and insufficiently observed expiry.
The SQLite Observation store preserves producer order and independently rebuilds
WorldModel; the replay result exposes quest/entity/relation/event parity checks.

No live marker-appearance timing or recorded live-session hydration was tested.
Full regression: 315 passed, 2 optional image tests skipped.

## 2026-09-08 — generic multi-step plan representation (offline only)

Plans now expose ordered capability/verification steps, constraints, replan
triggers and explainable candidate utilities. Future steps remain blocked until
the currently selected skill is verified, and dependency-blocked objectives are
not promoted.

No live multi-step quest was executed. Full regression: 318 passed, 2 optional
image tests skipped.

## 2026-09-08 — UNKNOWN-first World3D/minimap perception boundary

The user-supplied 1418x881 Retail screenshot was executed as a real-image
regression. The visible overhead yellow symbol is emitted as an
`unknown_symbol_candidate`; after three observations it has a SUPPORTED visual
`ABOVE` relation to an UNKNOWN subject/probe. Neither crop, colour nor symbol
creates NPC/MOB/PLAYER/QUEST_GIVER/QUEST_TURN_IN or reaction ground truth. The
small symbol is not an inspection target; its stable subject/probe is.

The supplied real minimap screenshot was also executed through the circular ROI
regression. All public markers are `unknown_minimap_marker`, the player is the
exact configured center, positions are MINIMAP_LOCAL, and the outer rim/cardinal
decorations do not become marker tracks. A map transform remains unusable until
at least three validated correspondences pass the RMSE threshold.

This was screenshot/replay validation only: no client input, cursor movement or
quest action was sent, so live interactive behavior is not accepted here. Full
regression: 326 passed, 2 optional environment-dependent tests skipped. Protected
movement/combat/input file hashes matched the pre-patch record exactly.

## 2026-09-08 — goal lifecycle, sensor hierarchy and contradiction (offline)

Added explicit goal priority/progress/recovery/completion/failure lifecycle and a
replayable Goal→Subgoal→Plan→Action→Prediction→Observation→Verification graph.
Plan/action/verification traces are stored as immutable `AGENT_TRACE`
Observations and rebuild with the WorldModel from SQLite.

The evidence system now exposes a strict sensor tier before confidence. Tests
prove that several AI/CV claims cannot outvote mouseover ground truth, equal-tier
ground-truth disagreement remains AMBIGUOUS, and later independent evidence can
resolve the belief while preserving the original contradiction history. Three
independent visual observations may strengthen UNKNOWN evidence but do not assign
semantics.

No client input or live domain action was run in this increment. Live goal
recovery, event ordering and real sensor-conflict behavior remain unaccepted.
Full regression: 333 passed, 2 optional environment-dependent tests skipped.

## 2026-09-08 — AGENT-09–12 typed entity/location/role/marker model (offline)

Entity identity, location, dynamic role, state and appearance now have separate
typed models and query paths. Both the in-memory WorldModel and persistent
EntityMemory keep location clusters separate by map, phase, instance and quest
context while aggregating repeat sightings in the same spatial/context cell.
Dynamic quest roles remain contextual relations rather than identity labels.

MINIMAP and WORLD_MAP runtime observations now expose the same typed MapMarker
representation. Raw CV remains UNKNOWN and provides only appearance/evidence
hints; minimap-local coordinates cannot become world coordinates without a
TRUSTED validated transform.

No live client input was sent. Cross-view association, real role transitions and
current Retail UI-scale behavior remain unaccepted. Targeted regression: 64
passed. Full regression: 339 passed, 2 optional environment-dependent tests
skipped.

## 2026-09-08 — corridor-scoped movement obstacle evidence (offline)

After the user explicitly lifted the previous movement-code freeze, obstacle
claim invalidation was narrowed to the exact attempted map/start-cell/heading
path key. A successful sideways RECOVER pulse no longer erases evidence for the
blocked forward corridor, and success on one corridor no longer clears another.

No pulse duration, input timing or live movement strategy was changed, and no
client input was sent. Targeted regression: 4 passed. Full regression: 341
passed, 2 optional environment-dependent tests skipped.

## 2026-09-08 — committed autonomous loop 0.9.0 (offline only)

Added a persistent CommittedSubgoal above individual action attempts. An alive,
selected, goal-relevant target now owns the sequence across approach, combat and
loot; unrelated active-perception candidates cannot replace it. Target loss
requires three distinct observations. Quest-state change, arrival, verified
transient work, supported stuck, target loss, session change and skill failure
are explicit replan triggers. A guarded, queryable runtime phase machine and
lifecycle trace expose why execution continues or replans.

Existing persistent rejection memory and visual Entity re-identification remain
the supporting perception layers. No client input was sent. Full Retail live
acceptance is still required. Full offline regression: 429 passed, 2 optional
environment-dependent tests skipped.

## 2026-09-08 — MOUNT/DISMOUNT closed-loop lifecycle (offline)

Added MOUNT and DISMOUNT as normal shared skill contracts. Mount is proposed only
for a sufficiently long known route with an explicitly configured usable action;
dismount is proposed only before a confirmed on-foot capability and uses that
same selected binding. Continued mounted travel is not interrupted.

Button execution is not treated as success. MOUNT requires fresh `is_mounted`
true telemetry, and DISMOUNT requires an observed true-to-false transition.
Unchanged mounted state reaches failure/replan. No live client input was sent.
Targeted regression: 7 passed. Full regression: 345 passed, 2 optional
environment-dependent tests skipped.

## 2026-09-08 — quest-understanding/logging patch merge (offline)

Merged the supplied patch without overwriting newer world-model and movement
work. Unstructured KILL/TALK_TO/RETURN text can now resolve explicit
EntityMemory identity/location hypotheses; confirmed structured locations remain
higher priority. Target commitment suppresses inspection of a re-identified
already-selected live entity. Persistent map-scoped negative inspection evidence
survives track churn, reaches REJECTED after three zero-information results, and
is cleared by successful contradicting evidence.

The archive omitted the rejection implementation and tests named by its own
documentation; these were implemented during the merge. The source-level
`logging` package collision was also removed and a fresh interpreter resolves
the standard-library logging module. No live client input was sent. Supplied
patch tests: 13 passed. Integrated targeted suite: 9 passed. Full regression:
354 passed, 2 optional environment-dependent tests skipped.

## 2026-09-08 — Exile’s Reach starting-mechanics patchset (offline only)

The four supplied patch archives were manually merged without replacing newer
WorldModel, UNKNOWN-first perception, navigation, or lifecycle work. The shared
planner/skill/verification path now covers quest-giver tooltip confirmation,
repair, named-friendly quest-item use and least-used combat rotation.

The starting slice was extended with generic BUY/SELL objective semantics,
addon-confirmed vendor item and visible bag-item coordinates, known money,
conservative sale filtering, named neutral-target quest-item use, tooltip-
confirmed world-object interaction for campfire-like objectives, and NPC
say/yell instruction telemetry. An instructed action is selected only when the
message explicitly names a currently usable actionbar spell; otherwise the
normal combat rotation remains.

No WoW input or live quest completion occurred in this increment. Merchant API
availability, bag-frame coordinate mapping, quest special-item export, localized
objective text and actual Exile’s Reach sequencing remain live-validation items.
Full offline regression after integration: 403 passed, 2 optional
environment-dependent tests skipped.

## 2026-09-08 — pixel-strip resolution profiles (offline only)

Addon 0.8.8 normalizes the bridge frame against `UIParent` effective scale so
the new transport uses a stable four-physical-pixel cell pitch. The decoder now
selects an exact or nearest client-resolution profile, tries a bounded fast path,
retains legacy UI-scaled pitch discovery, validates payload checksum before
caching, and reports resolution/profile in sensor health.

Synthetic physical-frame regressions passed at 640×480, 1024×768, 1600×900,
1920×1080 and 3840×2160, plus legacy 2.5-pixel pitch, a nonstandard window size
and cache relocation. Full offline regression: 412 passed, 2 optional tests
skipped. No live borderless or exclusive-fullscreen capture was validated.

## 2026-09-08 — persistent REACH movement controller (offline only)

Replaced per-pulse MOVE completion with one persistent high-level REACH action.
The controller now owns bounded forward/steering segments, heading correction,
progress history, arrival and a staged stuck belief. A single weak observation
is `NO_PROGRESS_YET`; RECOVER is eligible only after repeated, time-separated
observations reach `SUPPORTED_STUCK` with at least two evidence sources.

AIPC5 pixel telemetry was extended compatibly with player speed and moving
ground truth. The selected-PID executor now refreshes a bounded movement lease,
keeping forward held while changing steering; a watchdog releases all keys when
updates stop. No client input was sent and the behavior is not live-accepted.
Targeted movement/protocol regression: 10 passed. Full offline regression: 421
passed, 2 optional environment-dependent tests skipped.

## 2026-09-08 — committed autonomous loop 0.9.0 (offline only)

The runtime now owns one explicit committed subgoal through acquire, approach,
execute and verify. Replanning is event-gated; an unrelated UNKNOWN observation
cannot interrupt a valid committed target. No client input was sent. Full
offline regression: 429 passed, 2 optional environment-dependent tests skipped.

## 2026-09-08 — World3D v2 0.9.1 (offline + screenshot replay only)

Added generic contrast/edge/vertical-geometry foreground proposals, global
camera-translation estimation, residual-motion evidence, camera/velocity/scale/
appearance track association, soft static-scene scoring, information-gain
ranking and tolerant visual re-identification. All raw detections and tracks
remain UNKNOWN; nameplate/symbol/body-like cues are appearance evidence only.

The installed 1418×881 Exile's Reach screenshot replay produced UNKNOWN symbol
and subject tracks plus a stable ABOVE relation without creating a quest-giver
fact. Measured end-to-end World3D processing was approximately 0.13–0.17 s per
frame on this host. This is offline replay, not live quest validation. No client
input was sent and no FULL_AI process was started. Full regression: 435 passed,
2 optional environment-dependent tests skipped.

## 2026-09-08 — live-debug/status freeze fix 0.9.2 (offline verified)

The first attempted 0.9.1 live-debug start did not create a status directory
for the current WoW PID. The still-open GUI consumed approximately one CPU core.
Inspection of the latest historical status found a 2.4 MB snapshot, including
1.4 MB / 5273 WorldModel relations. The runtime rebuilt the unbounded diagnostic
graph every control tick and Tk rendered the complete JSON every 500 ms.

The authoritative WorldModel and persistent memories remain unchanged. Only
the live diagnostic projection is bounded (latest 200 relations, 100
predictions/verifications, 50 errors/contradictions), with total counters kept.
The GUI now renders a compact projection only when it changes and limits visual
tracks/history. No client input was sent during diagnosis. Full regression:
439 passed, 2 optional environment-dependent tests skipped. A fresh live start
is still required; this entry is not live acceptance.

## 2026-09-08 — live World3D observation and status-bound fix 0.9.4

The selected client PID 22232 produced a fresh AIPC5 stream at map 1409 with no
minimap. The client-only recorder saved the visible Exile's Reach scene. The
World3D v2 lane produced 12 generic proposals and approximately 39–40 merged
candidates, including a stable UNKNOWN overhead-symbol track associated ABOVE
an UNKNOWN subject track. No quest-giver semantic fact was inferred from CV.

No agent input was enabled; the run stayed MANUAL. Live diagnostics exposed a
second growth bug: aggregate visual collection beliefs embedded complete track
histories in contradiction records, expanding status to 7.4 MB. Aggregate
collection evidence is now identity/type/lifecycle metadata only, while full
source projections and per-track evidence remain authoritative. Diagnostic
contradiction values are represented by byte size and SHA-256, and track
snapshots expose bounded latest features. Full regression: 443 passed, 2
optional environment-dependent tests skipped. Movement and quest interaction
are not yet live accepted.

## 2026-09-08 — selected-client live capture 0.9.3 (offline verified)

Added a bounded, read-only screenshot recorder using only the foreground frame
already captured from the explicitly selected WoW PID. It records JPEG frames
on meaningful state changes, failures and a two-second heartbeat, with a JSONL
manifest containing decision, result, World3D v2, commitment, movement/stuck,
target and quest context. Encoding runs on a single background worker and the
session is capped at 180 frames. It does not capture the desktop, access process
memory or send input. Live capture correctness still requires the next client
run.

## 2026-09-08 — bounded live action 0.9.4 and World3D-first fix 0.9.5

With selected WoW PID 22232, fresh AIPC5 telemetry and a one-action/five-second
budget, the agent chose `OPEN_MAP`, executed only the selected
`TOGGLEWORLDMAP` binding, verified `world_map_opened`, released its transient
commitment and returned to MANUAL. The action was bounded and mechanically
verified, but it was the wrong information-gathering choice: the starting
quest's overhead cue and subject were already visible in World3D.

Replay of the client-only 1119×525 frame showed that the 70%-UI overhead badge
was being proposed as a generic subject because its 23×17 bounding box is wider
than the previous symbol-like aspect limit. The appearance-only symbol proposal
now accepts small near-square badges, without adding `!`, NPC, quest-giver or
other semantic facts. A stable `symbol ABOVE subject` relation marks the
associated UNKNOWN subject as high information value. Its mouseover `INSPECT`
proposal now outranks `OPEN_MAP`; the symbol itself remains non-inspectable.
Replay selected the subject at normalized screen position approximately
`(0.500, 0.703)` before the player's own lower-center subject proposal and
before map opening. Full offline regression: 445 passed, 2 optional tests
skipped. This decision fix still requires a second bounded live action before
quest interaction can be accepted.

## 2026-09-08 — two-action live failure and CV cadence fix 0.9.6

Two further bounded one-action tests both selected `OPEN_MAP`, not `INSPECT`.
The first verified map opening; the second failed verification and returned to
MANUAL. No movement or persistent FULL_AI control occurred. Replay of the exact
pre-action live frame produced a stable UNKNOWN symbol/subject relation at the
visible quest-giver area, proving the detector and relation layer were working.

The failure was an integration cadence bug: `PerceptionWorker.update` only ran
when the paged pixel protocol published a complete telemetry snapshot. The
debugger showed 37 cached lane candidates, but their 0.75-second planner output
lease had expired by the next complete addon payload, so the WorldModel received
an empty visual projection and only `OPEN_MAP` remained actionable. Vision now
runs continuously on the latest foreground frame at its own bounded cadence;
visual observations are still attached only when a complete addon payload gives
them a valid correlation and ground-truth boundary. Targeted regression covers
sparse telemetry with continuously warmed vision. A new bounded live action is
required for acceptance.

The next two bounded 0.9.6 runs confirmed an additional timing edge. One began
with the map visibly open while addon UI telemetry reported it closed, so the
toggle acted as a close and `OPEN_MAP` verification failed. In the genuine 3D
run, World3D took 1.85–2.24 seconds under live capture/debug load; the valid
track still exceeded the old 0.75-second planner lease. Version 0.9.7 retains a
completed visual projection for up to 3 seconds, never beyond the authoritative
telemetry freshness boundary. Full offline regression: 447 passed, 2 optional
tests skipped. No ZIP was produced per user direction.

## 2026-09-08 — bounded 0.9.7 failure and fresh-World3D start gate 0.9.8

The user completed the requested bounded test twice; it was not repeated. The
latest selected-client capture remained safely bounded and returned to MANUAL,
but again chose `OPEN_MAP` and failed `expected_observation_missing`. The exact
pre-action frame was `output/agent/pid-22232/live-captures/20260908-204854/
0008-204933-461-heartbeat.jpg`. Its live World3D job reported 37 candidates but
took 4691.24 ms under load, so even the 3-second result lease was not current at
the decision boundary.

Direct replay of that frame identifies the visible 70%-UI overhead badge as a
12x9, high-chroma `unknown_symbol_candidate` at pixel bbox (561,92)-(573,101),
without assigning quest/NPC semantics. After three frames it has a SUPPORTED
ABOVE relation to an inspectable, high-information `unknown_subject_candidate`
at normalized position approximately (0.500,0.764). The appearance-only symbol
rule now admits this small high-chroma badge while retaining the tiny low-chroma
noise rejection regression.

FULL_AI arming now waits for both fresh addon state and a recent completed
World3D surface result. A slow or stale CV job therefore cannot cause absence
of visual evidence to select `OPEN_MAP`; the bounded action timer starts only
after the visual gate succeeds. Targeted detector, real-screenshot, perception
lease, sparse-telemetry and runtime-arming regressions passed. This is offline
integration verification of the fix, not live quest acceptance; a fresh 0.9.8
process and one bounded action remain required. Full regression: 448 passed,
2 optional environment-dependent tests skipped. No ZIP was produced.

## 2026-09-08 — two bounded 0.9.8 INSPECT runs and addon FAST ground truth 0.9.2

The user ran the bounded action twice. Both runs selected `INSPECT`; neither
opened the World Map or emitted movement. The first selected an unrelated
stable World3D cue at normalized (0.3064,0.6286). The second selected the
overhead-associated generic subject at (0.4914,0.6164), and the user visually
confirmed that the cursor landed on the quest giver. This validates the live
World3D candidate and inspection-coordinate path, but not yet the quest role.

Both actions were incorrectly verified as `expected_observation_missing`.
The action records prove that the next published state still contained the
pre-action cursor position and event sequence. AIPC5's compact FAST packet only
carried movement/target state, while current cursor and mouseover ground truth
waited for completion of the large paged STATE snapshot. The full snapshot can
take several seconds despite its 0.2-second source sampling interval.

Addon 0.9.2 now refreshes cursor, unit mouseover and map mouseover for every
FAST transport tick and sends a bounded subset in the existing AIPC5 protocol.
When a full compact packet would exceed its limit, inspection and movement
feedback are retained while duplicated health/target fields fall back to the
paged snapshot. The Python assembler overlays this current evidence on the
authoritative full state. Transport/package/integration regression: 53 passed.
The canonical and Retail-12.1.0 addon copies are identical and the files were
installed into the live Retail AddOns directory. A client `/reload` and one
bounded INSPECT run are required to validate the ground-truth round trip. Full
regression: 450 passed, 2 optional environment-dependent tests skipped.

## 2026-09-08 — live INSPECT confirmation and local-action priority fix 0.9.9

The user accidentally continued with unbounded FULL_AI after the bounded run.
The agent is now MANUAL; no uncontrolled input remains active. The bounded and
unbounded attempts both inspected World3D track 8 at approximately
(0.5004,0.7263). Addon 0.9.2 immediately returned current cursor and mouseover
ground truth identifying Lady Jaina Proudmoore, NPC 156626, as a non-attackable
NPC. Both INSPECT attempts therefore verified SUCCESS. This live-validates the
World3D candidate -> hover -> FAST telemetry -> entity identity round trip, but
does not by itself prove a quest-giver role.

The next decision incorrectly selected `OPEN_MAP`. The planner had already
generated an API-identified friendly-mouseover `TARGET` proposal, but its lower
priority lost to the no-location map fallback. Quest planning now suppresses
`OPEN_MAP` whenever a local TARGET/INTERACT/TALK/QUEST_DIALOG/USE action exists.
Confirmed friendly mouseover is targeted first; a confirmed friendly target is
then interacted with so the resulting dialog supplies ground truth. Targeted
planner/agent regressions: 74 passed. This requires a user-operated 0.9.9 live
test; the assistant did not install files or send client input for this fix.

## 2026-09-08 — live target/interact range failure and approach bridge 0.9.10

The user ran FULL_AI and reported that the cursor oscillated between Lady Jaina
and the player character. The live trace confirms that World3D inspection,
mouseover identity and target selection succeeded. `INTERACTTARGET` then
produced the explicit client error `You need to be closer to interact with that
target.` The planner had no friendly-target approach transition, treated this
as a generic skill failure, released the target commitment and resumed random
inspection. No movement command was emitted.

An explicit interaction-range bridge now treats that client message as range
evidence rather than target loss. A matching fresh addon mouseover/cursor pair
creates a bounded five-second `CONFIRMED_MOUSEOVER_ANCHOR`; it remains appearance
evidence, not an invented world coordinate. The same target commitment owns
short `APPROACH_TARGET` movement pulses until interaction can be retried. While
the commitment is active, unrelated INSPECT candidates—including the player's
own visible body—cannot interrupt it. Friendly approach is permitted only for
the identical selected GUID, explicit interaction purpose and validated screen
anchor; ordinary hostile approach retains its nameplate contract. Targeted
planner, approach, commitment and core regression: 72 passed. This still needs
live validation by the user; no addon was installed and no client input was
sent by the assistant.

## 2026-09-08 — persistent world-coordinate REACH_OBJECT 0.9.11 (offline)

The user reported that 0.9.10 selected Lady Jaina, moved once and then stopped.
The trace and implementation showed the architectural cause: the friendly
range bridge still emitted independently verified `APPROACH_TARGET` pulses,
so one small displacement counted as success and the planner retried INTERACT.
That 0.9.10 bridge is superseded; it is retained above only as historical live
evidence of the failure.

An interaction range error now creates one target-GUID-bound `REACH_OBJECT`
subgoal. The addon 0.9.3 source exports both player and target `UnitPosition`
in the explicit `WORLD_YARDS` coordinate space (including instance identity)
on the FAST lane. The same movement Action/Plan owns continuously refreshed
steering, endpoint updates, progress history, stuck evidence and arrival. It
does not return to INTERACT until distance is at most 4.5 yards. Missing
coordinates, instance mismatch or target identity change cause no blind input.

The controller now adds circular heading smoothing, deadzone+hysteresis, pure
turning before forward motion for large heading errors, gentle forward+turn for
moderate error, finer near-target control, immediate key release on arrival,
and measured-route collinear smoothing/look-ahead. The sub-350-ms value visible
inside input commands is only a fail-safe key lease refreshed by the same
persistent skill; it is not a planner pulse, skill success or replan boundary.
A bounded action budget counts REACH once and does not consume another action
for each internal controller update.

The final full suite passed 460 tests with 2 optional environment-dependent
skips.
Live acceptance is still pending: the user must install/reload addon 0.9.3 and
operate the next test. In particular, world-axis steering direction and the
4.5-yard interaction handoff are not yet live-validated. No addon was installed,
no client input was sent, and no ZIP was produced by the assistant.

## 2026-09-08 — post-reload FAST target projection failure

The 22:24–22:26 user-operated test in
output/live-debug/live-debug-20260908-222112.jsonl received addon 0.9.3 and
player WORLD_YARDS position (-446.89999, -2612.69995), instance 2175.
TARGET verified Jaina's GUID at 22:24:42, but subsequent FAST projections
contained only that GUID. The compact transport branch discarded name,
npc_id, attackable and dead. REACH_OBJECT did not execute; target world
position was also absent. Player-coordinate receipt does not validate NPC
coordinate availability or arrival. The final status was MANUAL.

Addon source 0.9.4 preserves identity/state fields in compact FAST packets,
includes target sample time, and explicitly reports unavailable world_position
as false. No old coordinate is invented or carried over. A Lua-to-Python
regression forces packet compaction and checks the resulting target state.
Affected transport/package/approach suite: 28 passed. User installation and
reload remain required; the assistant did not install or control the client.
The log also shows multi-second agent steps; continuous steering cadence is
not yet live-validated and requires separate diagnosis.

## 2026-09-08 — addon 0.9.4 target identity validated; NPC position unavailable

The user-operated 22:30–22:32 test used addon 0.9.4. Read-only inspection of
the latest 500 ADDON_TELEMETRY observations found 17 matching Jaina samples:
all 17 included player world coordinates; zero included target coordinates.
Compact packets explicitly reported world_position=false; full snapshots also
omitted NPC world_position. Name, NPC ID, attackable=false and dead=false were
preserved, validating the compact target-state repair.

REACH_OBJECT did not start. INTERACT failed expected_observation_missing and
planning subsequently waited for world coordinates. Final status was MANUAL.
The assumption that UnitPosition would provide this NPC's coordinates is not
supported by the live client. Do not request another unchanged movement test
or claim coordinate approach validated. Next implementation requires a
persistent identity-associated visual reach path (or a separately proven map
destination), plus independent steering cadence; no guessed world coordinate
or restricted-value bypass is acceptable.

### 2026-09-09 — TDB reference import, pending live calibration

Imported 261400 creature spawn references, including 900 on world map 2175.
NPC 156626 has one reference at (-435.153, -2610.99, 0.667893), phase 13845.
Runtime status now exposes `spawn_reference` for the selected NPC with distance
from player world position. References remain CANDIDATE, not live telemetry.
No client test run by assistant; reference-driven movement is not enabled.
See `docs/TDB_REFERENCE_IMPORT.md` for provenance, limits and manual test.

### 2026-09-09 — Map-first location provenance

World Map hover memory retains quest ID, track association and coordinate/
semantic source across restarts. Cursor coordinates are inspection areas,
not confirmed NPC positions. TDB excluded from learned-location planner path.
Live end-to-end map -> REACH -> local World3D interaction remains unvalidated.

### 2026-09-09 — Conditional DB reference REACH

User authorized DB navigation only as map fallback. Runtime projects reference
candidates through SPATIAL_MEMORY without modifying addon target positions.
QuestDomain uses REACH_OBJECT after explicit interaction range failure only if
no usable same-map MOVE location remains. Supported-stuck/deadline MOVE failures
allow fallback; uncertainty alone does not. Fallback requires selected GUID/NPC
ID, matching world map, a unique spawn within 60 yards / 8 vertical yards,
and no known phase conflict. Unknown phase is permitted as local exploration,
not confirmed presence. Reference arrival allows one fresh interaction attempt;
one fallback per session/GUID/spawn prevents repeated wrong-location loops.
The existing controller retains the GUID and stops on identity/context loss.
No new coordinate conversion, guessed NPC Z or live target position is produced.
Offline targeted tests: 9 passed. Live behavior remains pending user test.
This is local reference approach, not DB-wide pathfinding or obstacle routing.

### 2026-09-09 — Bounded World Map zoom inspection

Failed World Map INSPECT (expected_observation_missing) requests one wheel-up
at a fresh detected marker. Maximum five wheel-up events per map-open inspection
cycle; normal hover/reobservation separates attempts. Zoom is unavailable on
closed map or in combat and uses selected-PID foreground/F12 executor checks.
Perception context includes zoom revision, invalidating pre-zoom tracks and
in-flight detector results; planner rejects older revision coordinates.
Wheel dispatch is NOT recognition success: the zoom attempt is cancelled with
map_zoom_sent_reobserve_fresh_markers, followed by new detection/mouseover.
No zoom-level telemetry is claimed: five is a user-specified input budget, not
proof of the actual maximum UI zoom. Unknown map marker eligibility fixed.
Offline tests cover bounded zoom, stale revisions, closed-map/combat guards.
Live validation remains pending user-operated test; addon unchanged.

### 2026-09-09 00:37–00:40 — Pre-zoom-code live run diagnosed

The GUI agent process started at 00:37:50; planner zoom source was written at
00:38:29, so this run necessarily used the previously loaded module. Journal
evidence shows OPEN_MAP, HOVER at (0.49438,0.36926) with missing observation,
then HOVER at (0.49438,0.68862) with verified mouseover. No MAP_ZOOM_IN command
was present. Quest dialog was subsequently verified and quest count became 1.
The user's visual observation that the map appeared idle is consistent with
the long intervals: runtime steps took about 2–5 seconds.

Post-run audit found two blockers in the newly written zoom branch before its
first live execution: a failed hover's REJECTED memory could suppress the
requested zoom, and the ten-second map scan window could expire before a slow
next tick. Both are fixed: an explicitly requested bounded zoom bypasses that
single rejection, and a pending zoom may execute after the ordinary scan
window. `map_inspection` diagnostics now expose support/count/limit/requested/
probe count to GUI status and the read-only live debugger. Requires full agent
restart; addon reload is not required. Corrected code is still not live-validated.

### 2026-09-09 — Explicit 3D -> World Map -> DB fallback hierarchy

The latest run selected a persisted WorldPointMemory MOVE immediately after a
TARGET verification failure, bypassing a fresh map search. That point came from
an earlier scan and was not current-run evidence. Planner now permits a remembered
quest map point only when the active World Map scan re-associated its marker and
tooltip with current session and monotonic provenance.

Search order is now: useful/high-information World3D inspection -> current World
Map detection/hover (including bounded zoom) -> MAP_EXHAUSTED -> unique nearby
TDB reference REACH_OBJECT. A blocked local interaction no longer suppresses
OPEN_MAP. The DB path cannot start before MAP_EXHAUSTED and retains identity,
map, phase, distance and uniqueness gates plus on-location interaction verification.
Debugger status exposes search_stage and map_search_exhausted. Offline hierarchy,
zoom and discovery tests passed; corrected hierarchy needs an agent restart and
remains pending user-operated live validation.

### 2026-09-09 — Identity-free questgiver-location fallback completed offline

The exact TDB dump used for creature coordinates was parsed again as inert data;
its SHA256 was required to match the catalog provenance before 12,748 quest-starter
and 22,243 quest-ender relations were added. A pre-import SQLite backup was made.
No SQL was executed against the sandbox server.

When no live target exists, the quest planner now enforces the requested order:
high-information World3D inspection -> fresh World Map detection/hover/zoom ->
MAP_EXHAUSTED -> nearby TDB QUEST_STARTER location hypothesis. The final step uses
a persistent `REACH_LOCATION` WORLD_YARDS skill. It does not create a target,
quest role, NPC identity, or confirmed location. Phase variants within one yard
are clustered into one inspection region; the actual entity must be rediscovered
and confirmed locally by World3D/mouseover/addon telemetry. The location fallback
is one-shot per session/cluster and is not used while an active quest exists.

At the Exile's Reach start, NPC IDs 156626 and 166782 are two phase variants at
the same coordinate, so the planner approaches their shared region without
guessing which identity is present. Targeted unit/integration/regression suite:
107 targeted tests and the full suite (476 passed, 2 skipped) succeeded. Live
navigation, arrival, and post-arrival reacquisition are still
pending a user-operated test after an agent restart.

### 2026-09-09 — Unified CPU-first Vision V3/V4 0.9.13 (offline)

World3D V2 remains the sole full candidate detector inside a new unified V3
pipeline; it is not duplicated or overridden. Full detector refreshes are
adaptively scheduled (nominal 5 Hz), while a camera-aware bounded patch tracker
propagates the same UNKNOWN track IDs on intermediate capture frames. The
existing shared VisualTrackManager still owns persistent lifecycle/history and
symbol-ABOVE-subject scene relations.

Targeted OCR now evaluates at most three ranked crops every 600 ms. Modal
quest/gossip telemetry switches perception to a bounded UI_CV dialog ROI rather
than running World3D behind the UI. OCR text and text+scene relations produce
only non-fact hypotheses; raw semantic type remains UNKNOWN. The local production
OCR adapter reports backend_unavailable because tesseract is not installed on
this machine; injected crop OCR is offline-tested and no text is fabricated.

V4 records stable unresolved subject crops as bounded, rate-limited, unlabelled
hard examples with provenance. This is dataset collection, not automatic truth
or completed learning. Runtime diagnostics expose nested detector/tracker/OCR/
hard-example state. Reference-frame timing at 1418x881: full detector refresh
140–153 ms, tracker median 6.5 ms. This is offline replay, not live FPS or
precision/recall. See `docs/VISION_V3_V4.md`. Live validation remains pending.

An active INSPECT also enables a bounded cursor-fovea tooltip OCR region. Text
not spatially associated with a World3D candidate is preserved as a separate
UI_CV UNKNOWN text track. This path is offline-tested only.

Final 0.9.13 offline regression result: 483 passed, 2 skipped.

### 2026-09-09 05:42–05:43 — World3D identity handoff live diagnosis / 0.9.14 fix

User-operated FULL_AI run on selected PID 23188 confirmed that the unified
World3D pipeline produced 36–38 candidates and 21–31 stable tracks. At 05:42:40
the planner inspected a World3D candidate; at 05:42:42 addon mouseover ground
truth identified Lady Jaina Proudmoore (NPC 156626). This is live evidence that
the generic detection -> temporal track -> active mouseover -> identity path can
find the intended NPC. It is not yet evidence of successful visual approach.

The subsequent TARGET click was incorrectly failed after the two-second
verification deadline. The same GUID appeared as selected-target telemetry at
05:42:46, approximately four seconds after the click, but the commitment had
already been released and OPEN_MAP had started. World Map inspection produced no
validated destination, then the TDB fallback correctly activated and REACH_OBJECT
moved from player map position 0.6208657,0.8392472 to 0.6189826,0.8304573 before
reporting arrival. The user stopped/switched to MANUAL before the proposed final
INTERACT was executed. No uncontrolled FULL_AI process was left running.

Version 0.9.14 raises only the TARGET verification window from two to five
seconds. It also retains a short-lived addon-confirmed mouseover screen anchor
separately from semantic identity and world location. After a client-confirmed
friendly interaction-range error, APPROACH_TARGET now uses that anchor before
World Map or TDB fallback. The anchor does not assert NPC role or world
coordinates, expires after 30 seconds, and is accepted only for the same GUID.
The fallback hierarchy remains World3D -> World Map -> TDB when no valid local
anchor exists. Full 0.9.14 regression: 485 passed, 2 skipped. Corrected TARGET
retention and visual approach remain pending a new user-operated live run after
restarting the agent.

### 2026-09-09 05:56–06:00 — Self-selection regression diagnosed / 0.9.15 fix

The user-operated rerun exposed a separate World3D attention failure. Three
attempts inspected the same lower-left player-frame fragment at client bbox
240,316–272,380, and two attempts inspected the third-person local avatar at
560,284–592,348. Addon mouseover explicitly reported `is_player=true`,
`unit_type=PLAYER`, and GUID `Player-1402-0B51DA08`, but the generic friendly
mouseover branch incorrectly described and selected it as an NPC. The resulting
INTERACT attempts targeted the local character and could not make quest progress.

Version 0.9.15 adds two independent protections. The Retail World3D scene ROI
now scales the lower-left HUD exclusion with client width and excludes only the
lower-centre third-person self-avatar band while leaving the upper-centre world
visible. Separately, authoritative addon player identity (`is_player`,
`unit_type=PLAYER`, or the current character GUID) is rejected from generic NPC
TARGET, friendly INTERACT, and confirmed mouseover-anchor creation. Detection
remains UNKNOWN-first; the exclusion does not classify other subjects.

Offline replay of the exact 1177x552 live capture produced zero candidates in
both offending regions and retained ten candidates around the upper-centre
Jaina/overhead-symbol area. This is regression evidence, not proof that the next
live inspection will select Jaina. The corrected behavior requires an agent
restart and remains pending user-operated live validation. Full 0.9.15
regression: 487 passed, 2 skipped.

### 2026-09-09 06:12–06:14 — Quest UI reached; self-exclusion live-validated

The user-operated 0.9.15 run did not inspect, target, or interact with the local
player or lower-left player frame. This live-validates the two self-exclusion
regressions for this resolution/UI configuration. The first World3D candidate
inspection was unrelated and failed; World Map also produced no confirmed
destination. The TDB QUEST_STARTER fallback then moved from normalized player
position 0.61959,0.83816 to the Jaina spawn inspection region around
0.61864,0.83069.

At the fallback region, addon mouseover identified Lady Jaina Proudmoore and
TARGET was issued for GUID Creature-0-4256-2175-15-156626-000020B8C7. The
authoritative target projection arrived only after the five-second TARGET
deadline, so the action was temporarily recorded as failed even though the
correct target subsequently persisted. REACH_OBJECT finished and INTERACT
opened the real `Murloc Mania` quest dialog, visibly exposing the Accept button.
The user ended the test at that point and runtime returned to MANUAL; the quest
was not accepted and no completed quest is claimed.

Version 0.9.16 extends TARGET verification to eight seconds, based on the live
four-to-seven-second AIPC5/debug latency range. OPEN_MAP and CLOSE_MAP
verification are extended to five seconds because the same run showed their
authoritative UI state arriving after the prior two-second deadline. These are
verification windows only; they add no input and do not change the established
fallback order. The corrected timing remains pending a restarted live run.
Full 0.9.16 regression: 487 passed, 2 skipped.

### 2026-09-09 — Quest Accept telemetry existed; freshness false-positive fixed

Inspection of the recorded authoritative observations proved that INTERACT did
open quest 55122 (`Murloc Mania`). AIPC5 snapshots at monotonic 1872998.695 and
1872999.426 contained `quest_ui.open=true`, `action=ACCEPT`, and normalized
button coordinates 0.0369451,0.2226562. The planner never consumed them in
FULL_AI because a 3.38-second complete-snapshot interval crossed the previous
fixed three-second WorldModel freshness limit and fail-safe switched to MANUAL.

Version 0.9.17 uses a six-second complete-addon-receive window, derived from the
observed healthy 3–5-second paged AIPC5 cadence. It retains a separate eight-
second effective state-age ceiling (`exported state_age + receive gap`), plus
unchanged selected-PID foreground, input-blocked, loading, session-identity and
executor-stop guards. Diagnostics expose both freshness limits. This corrects a
false telemetry-loss decision; it does not make stale data ground truth or keep
FULL_AI alive through actual sensor loss. Unit tests cover the soft window and
hard effective-age cutoff. Accept execution remains pending a restarted
user-operated live run.
Full 0.9.17 regression: 488 passed, 2 skipped. Python compile validation also
passed. This is offline regression evidence only; quest Accept remains pending
the next user-operated live test after restarting the agent.

### 2026-09-09 06:28–06:33 — Quest Accept live-validated; bounded MOVE run

The user-operated run accepted quest 55122 (`Murloc Mania`). Authoritative
telemetry subsequently contained the accepted active quest and its 0/6 First
Aid Kits objective. This live-validates the 0.9.17 freshness correction for the
Accept path. The first run later encountered a separate 15-second pixelstrip
decode interruption and correctly fail-safed to MANUAL; telemetry recovered
afterward. A subsequent bounded run kept telemetry fresh throughout, selected
the addon's `QUEST_POI` destination on map 1409, made measured progress toward
0.6034011,0.7982250 without stuck evidence or recovery, and switched to MANUAL
exactly at the configured 30-second `bounded_live_test_timeout`. That second
MANUAL transition was intentional, not a movement or telemetry failure.

The Accept action itself had already been marked failed before its later paged
active-quest confirmation arrived. Version 0.9.18 therefore extends only the
`QUEST_DIALOG` verification window from three to ten seconds. Success still
requires authoritative quest-log change or a matching addon quest event; UI
closure alone is not accepted as proof. Live validation of the corrected
verification record remains pending an agent restart and a future quest dialog.
Full 0.9.18 regression: 489 passed, 2 skipped. Python compile validation passed.

### 2026-09-09 06:41–06:44 — Repeat pickup succeeds; steering oscillation isolated

The user reset and repeated the flow with 0.9.18. The agent found Jaina through
the existing local/map/TDB chain, opened the dialog, accepted quest 55122, and
this time recorded `QUEST_DIALOG SUCCESS / expected_observation_verified` when
the paged active-quest state arrived. This live-validates the 0.9.18 delayed
Accept verification window.

The subsequent persistent MOVE correctly committed to the addon `QUEST_POI`,
but did not reach it before the 90-second safety deadline. Screenshots and
authoritative orientation samples show alternating headings around the desired
bearing, with no obstacle/stuck evidence: former 280 ms turn/soft-steer leases
changed facing by roughly 0.7–0.9 radians and repeatedly overshot before the
1–4 Hz feedback loop could correct. Version 0.9.19 caps turn-in-place leases at
120 ms, soft steering at 80 ms, and dampens later turn duration after a measured
heading-error sign reversal. Planner destination and persistent REACH ownership
are unchanged. Corrected steering remains pending user-operated live validation.
Full 0.9.19 regression: 490 passed, 2 skipped. Python compile validation passed.

### 2026-09-09 — Continuous forward lease and bounded camera search (0.9.20)

The physical executor now keeps `MOVEFORWARD` held continuously across REACH
control updates instead of releasing it when each short command duration ends.
Turn keys remain short closed-loop corrections and are released independently;
arrival, failure, MANUAL/STOP, foreground loss, emergency stop, or a 6.25-second
unrefreshed movement watchdog releases all held keys. This separates persistent
forward ownership from steering correction without weakening input safety.

When the agent has reached a known location (or target acquisition/map fallback
has been exhausted) but has no current target or explicit local interaction, it
may perform up to four camera-only left-drag INSPECT actions. Each pan merely
requests new World3D UNKNOWN observations; it creates no NPC/hostile/quest
semantic fact. Goal-relevant evidence interrupts the scan, movement resets the
local scan budget, and World Map/TDB fallback remains available afterward.
Both changes remain pending user-operated live validation after restart.
Full 0.9.20 regression: 492 passed, 2 skipped. Python compile validation passed.

### 2026-09-09 — Live Murloc combat/corpse handoff audit and 0.9.21 fix

The user ran another FULL_AI test with the still-running 0.9.19 GUI, so its
movement behavior is explicitly **not** validation of the 0.9.20 persistent
movement controller.

Live evidence from `output/agent/pid-23188/live-captures/20260909-065115`:

- the agent reached the Murloc area, acquired and fought Murloc Spearhunter,
  then later acquired Murloc Watershaper;
- active quest 55122 remained at 0/6;
- the addon event history contained the killed target's exact Creature GUID
  and the tooltip text `Corpse`, followed by `COMBAT_ENDED`;
- top-level `target`, `dead_corpses`, and `killed_corpses` were already empty,
  so the planner skipped LOOT and searched for another enemy.

0.9.21 preserves a fresh GUID-bearing addon corpse-tooltip event as a bounded,
screen-space interaction anchor. It does not invent a world coordinate and it
rejects delayed event/cursor pairings. Combat verification accepts this exact
same-GUID corpse evidence as death confirmation. Before acquiring another
target, the committed target is right-clicked through the LOOT skill; the
anchor is removed after matching loot evidence.

Offline regression: 494 passed, 2 skipped. Python compile validation passed.
The corpse handoff and 0.9.20 movement/camera changes still require a new live
run with the 0.9.21 GUI; no claim of live validation is made.

### 2026-09-09 — 0.9.21 live movement/target test and 0.9.22 corrections

User-operated run: `output/agent/pid-23188/live-captures/20260909-071645`.
The run exercised the 0.9.20/0.9.21 control path and ended in STOPPED mode.

Validated observations:

- the first persistent MOVE reached the active quest POI, from approximately
  `(0.6029, 0.8068)` to `(0.6026, 0.7990)`, and produced
  `reach_arrival_verified`;
- camera search executed after arrival;
- target acquisition selected Murloc Watershaper with an authoritative GUID;
- no quest progress or successful loot was observed.

Failures found:

- after camera observation the unchanged quest POI was issued again, causing
  the controller to chase the area centre, overshoot, and eventually hit the
  90-second movement safety deadline;
- the relevant Murloc was out of spell range and had no nameplate/world
  position, so COMBAT was correctly unavailable but no executable persistent
  approach survived the mouseover observation;
- a corpse tooltip existed in delayed event history, but 0.9.21 deliberately
  rejected pairing that old event with the current cursor. Consequently the
  event-only corpse fallback did not produce a safe click anchor.

0.9.22 changes:

- successful quest-POI arrival is remembered for the unchanged quest
  signature, preventing the same area-centre MOVE from being reissued after
  camera observation or telemetry drift;
- in-progress quest POIs use an explicit inspection-area stop radius;
- simultaneous live addon mouseover and cursor samples are retained in the
  WorldModel as bounded identity-linked screen anchors, including dead-unit
  corpse anchors;
- a quest-relevant, out-of-range hostile with a confirmed anchor now receives
  one persistent APPROACH_TARGET action. Forward input remains leased across
  observations and stops only when attack range is confirmed, the target is
  lost, the deadline expires, or a safety/input guard fires.

Offline regression: 497 passed, 2 skipped. Python compile validation passed.
These 0.9.22 corrections remain pending user-operated live validation.

### 2026-09-09 — AIPC Agent 1.0 implementation, awaiting live validation

The adopted 0.9.1→1.0 specification was integrated into the existing shared
agent rather than implemented as parallel brains. Added/finished offline:

- event-gated slow Brain plus measured fast/perception rates;
- first-class estimated/verified CameraController and persistent
  VISUAL_APPROACH controller;
- ACTIVE/OCCLUDED/LOST_TEMPORARY/REACQUIRE_CANDIDATE visual lifecycle;
- batched/indexed observation persistence, bounded derived-observation
  consolidation and DB metrics;
- calibrated earliest/likely/deadline verification windows and richer
  PredictionError records;
- expanded read-only WorldQuery and Ollama observability;
- preservation of transient addon mouseover transitions and stable vision
  epochs during cursor movement.

No client was controlled for this implementation entry. Therefore no new
quest, camera, approach, combat, gathering or endurance behavior is marked
live-validated. The next evidence must come from a user-operated bounded test;
the agent must be MANUAL at handoff.

Offline verification for this implementation: 506 passed, 2 skipped; Python
compile validation passed. The skipped screenshot fixtures and all live/soak
gates remain explicitly unvalidated.

### 2026-09-09 — Jaina start-quest live audit and 1.0.1 correction

User-operated run: `output/agent/pid-12468/live-captures/20260909-170142`.
The character started directly in front of Lady Jaina Proudmoore with no
active quest. The run did not validate successful quest acquisition.

Observed failure chain:

- World Map search produced no usable marker and TDB reference fallback moved
  toward the expected starter region;
- addon mouseover identified NPC 156626 (Jaina), but the subsequent TARGET
  click did not produce a selected target;
- after TARGET verification failed, the live GUID commitment was released and
  a second TDB role candidate (NPC 166782) was selected;
- the persistent reference REACH then owned the loop and continued down the
  beach instead of stopping for newly visible World3D evidence.

The audit also exposed a coordinate-contract defect: Retail
`GetCursorPosition()` and the Windows input backend both use normalized
bottom-left coordinates, while mouseover-anchor projection and
VisualApproach were applying an additional `1-y` transform. That could steer
toward the vertical mirror of the visually observed subject.

1.0.1 corrections:

- mouseover anchors and VisualApproach now preserve the authoritative
  bottom-left coordinate contract;
- anchors carry player/world/map/orientation/camera snapshots and expire after
  material scene motion; GUID identity is retained independently of the stale
  pixel;
- cursor and mouseover samples must be temporally paired before a confirmed
  anchor can be produced;
- TDB reference movement is interrupted by a matching live addon identity or
  a stable high-information UNKNOWN World3D subject, so perception can inspect
  it before movement continues;
- failed TARGET verification retains the confirmed GUID commitment and
  suppresses switching to another TDB candidate;
- TDB role-location fallback keys normalize spawn ordering, closing a duplicate
  fallback path.

Offline regression after these corrections: 526 passed, 2 skipped; Python
compile validation passed. The fixed
Jaina approach/selection flow remains pending a fresh user-operated live test
after restarting the agent; the run above used the pre-fix process.

### 2026-09-09 — Jaina VisualApproach overshoot audit and 1.0.2 correction

User-operated run: `output/agent/pid-12468/live-captures/20260909-172954`.
The 1.0.1 run successfully inspected and selected Lady Jaina Proudmoore, then
received the authoritative client error `You need to be closer to interact
with that target.` and correctly committed a `VISUAL_APPROACH`. It did not
reach or open the quest dialog. Instead, it continued from approximately
`(0.6196, 0.8346)` to `(0.6130, 0.7997)`, passing Jaina and reaching the
Murloc camp before stale telemetry returned the runtime to MANUAL.

Root causes confirmed from the action trace and captured frames:

- full addon snapshots arrived only around 0.1–0.3 Hz, while completed local
  World3D tracking results were not projected into the agent between those
  snapshots;
- the initial addon-confirmed anchor had not yet been associated with the
  asynchronous World3D subject track when VisualApproach started;
- after scene motion invalidated the WorldModel anchor, VisualApproach still
  accepted its private frozen starting pixel as a fallback;
- when no visual command was emitted, the executor's forward lease could
  remain held until the 6.25-second watchdog, causing material overshoot.

1.0.2 corrections:

- active VisualApproach receives independent fresh WORLD3D-only control
  observations whenever a new perception projection completes; no addon fact
  is copied into this lane;
- the WorldModel exposes the latest visual observation identity and binds a
  delayed World3D subject projection to the simultaneous confirmed mouseover
  anchor;
- once a Track↔Entity association exists, loss of that track enters OCCLUDED
  instead of falling back to the original pixel;
- a missing/occluded visual command immediately releases movement keys before
  bounded camera reacquisition;
- untracked starting anchors have a sub-second temporal/scene validity gate;
- an exact selected friendly GUID is range-probed with `INTERACTTARGET` at a
  bounded 0.8-second cadence; opening quest/gossip UI verifies arrival and
  ends the approach.

Offline verification: 529 passed, 2 skipped; Python compile validation passed.
The corrected stop/reacquire/range-probe behavior is not yet live-validated;
it requires an agent restart and a new user-operated Jaina test.

### 2026-09-09 — World3D wrong-subject live audit and 1.0.3 correction

User-operated run: `output/agent/pid-12468/live-captures/20260909-174419`.
The run did not enter the corrected VisualApproach path and did not acquire the
starter quest. It first inspected `WORLD3D:7` at approximately `(0.734,
0.601)`, although the live frame contained Lady Jaina Proudmoore and a bright
overhead symbol-like cue near `(0.430, 0.656)`. Inspection failed, World Map
search found no useful marker, and the planner fell back to the TDB reference
region. The reference REACH moved from an estimated 6.89-yard distance to its
6-yard inspection tolerance, after which camera search also failed.

Root causes confirmed from the stored observations and the real captured
frame:

- the correct overhead cue was associated with a neighbouring/tiny colour
  component instead of producing a useful inspection region below the cue;
- a merely `CANDIDATE` overhead relation received the same HIGH inspection
  priority as a temporally `SUPPORTED` relation;
- source-level probe generation ignored stability already accumulated by the
  high-rate World3D tracker, delaying useful active perception until after
  fallback selection.

1.0.3 corrections:

- high-rate `track_hits` now contribute to symbol stability without changing
  the symbol's UNKNOWN semantics;
- tiny fragments and horizontally neighbouring bodies no longer suppress the
  neutral subject probe below an overhead cue;
- the probe bbox scales from the symbol/frame geometry and carries appearance
  evidence separately from semantic meaning;
- symbol-to-subject association prefers the derived probe or a genuinely
  body-sized region, and uses a tighter horizontal relation gate;
- only a temporally SUPPORTED overhead relation receives HIGH information
  value; candidate relations remain inspectable but cannot automatically
  outrank the supported center probe;
- active-perception and planner ranking now distinguish CANDIDATE from
  SUPPORTED relations while preserving `DETECTION != RECOGNITION`.

Offline replay of the actual `0005-174438-874-state_change.jpg` frame now
creates a stable UNKNOWN subject probe at approximately `(0.430, 0.531)`,
covering `(466,204)-(546,314)`, and ranks it as the first INSPECT proposal.
This is a replay result, not proof of quest interaction. Full offline
verification: 531 passed, 2 skipped; Python compile validation passed. A fresh
user-operated run is still required to validate Jaina mouseover, selection,
approach and quest-dialog opening end to end.

### 2026-09-09 — Delayed interaction result / map-overlay live audit and 1.0.4 correction

User-operated run: `output/agent/pid-12468/live-captures/20260909-174623`.
The World3D correction was live-confirmed through identity acquisition: the
agent hovered the visually relevant center region at approximately `(0.503,
0.659)`, addon telemetry identified Lady Jaina Proudmoore (NPC 156626), TARGET
selected that exact GUID, and target telemetry verified the selection. The
run did not open the quest dialog and therefore did not validate quest
acceptance.

Observed failure chain:

- INTERACT was issued at monotonic 20419.172 and expired as
  `expected_observation_missing` at 20423.361;
- Retail's authoritative `You need to be closer to interact with that target.`
  result arrived at 20425.133, after OPEN_MAP had already become the next
  action, so the error was incorrectly attributed to OPEN_MAP;
- VISUAL_APPROACH consequently started while the World Map overlay was open;
- movement advanced briefly, but the target track was unavailable behind the
  overlay; three bounded camera reacquisition actions could not restore it,
  and `visual_track_lost` ended the approach;
- subsequent map/TDB fallback did not move because player coordinates stopped
  changing, and the user returned the process to MANUAL.

1.0.4 corrections:

- INTERACT and TALK retain ownership for a seven-second observation window,
  covering the 4–6 second paged-export latency observed live;
- an unobserved interaction effect keeps the exact selected GUID committed and
  becomes a CANDIDATE range belief instead of authorizing map search;
- an explicit client range error upgrades that belief to SUPPORTED;
- if a World Map overlay is open while the same committed target has a range
  block, CLOSE_MAP is a mandatory precondition before VisualApproach;
- the close-map guard requires an active matching TARGET commitment, preserving
  the established World3D → World Map → DB discovery order for uncommitted
  searches.

Offline verification: 534 passed, 2 skipped; Python compile validation passed.
The delayed-result retention and map-close-before-approach changes require a
fresh user-operated live test. The agent was already MANUAL at audit/handoff.

### 2026-09-10 — TDB traversal overshoot live audit and 1.0.5 correction

User-operated run: `output/agent/pid-13664/live-captures/20260910-054446`.
The earlier World3D identity path remained functional, and the TDB reference
fallback brought the character onto Lady Jaina Proudmoore's line. Quest-dialog
opening and quest acceptance were not validated in this run.

The trace and captured frames establish the overshoot precisely:

- TDB `REACH_LOCATION` started at monotonic 63678.656 from approximately
  `(-447.4, -2611.2)`;
- the next complete addon sample at 63681.914 identified Lady Jaina
  Proudmoore, NPC 156626, by authoritative mouseover and ended the reference
  traversal successfully at approximately `(-434.1, -2611.5)`;
- planning returned at the following paged sample, when the character was
  already near `(-414.1, -2612.1)` and the transient mouseover identity was
  gone;
- the planner consequently selected camera search instead of immediately
  targeting Jaina. Real captures show the character passing Jaina and reaching
  the rib/fence scenery.

1.0.5 corrections:

- the independent high-rate World3D lane now also runs during a TDB reference
  search traversal, so a stable live UNKNOWN inspection candidate can stop the
  persistent forward lease between complete addon samples;
- World3D-only control frames never count as coordinate no-progress evidence
  and do not steer the world-coordinate controller without a fresh position;
- a matching live mouseover identity ends fallback movement and continues
  planning on the same observation, immediately selecting the exact GUID
  instead of waiting until the identity disappears;
- `stop_movement()` now sends a redundant idempotent key-up for each
  agent-owned movement key and publishes stop diagnostics; it does not send a
  reverse pulse or guess a binding.

Offline verification covers the fast World3D interruption, same-observation
TARGET transition, duplicate-safe physical key release, and existing movement
regressions. This correction still requires a fresh user-operated live test.
At audit/handoff PID 13664 was MANUAL, with no held keys or movement lease.

### 2026-09-10 — Identity-bound fast visual servo 1.0.6 (offline)

The visual movement path was audited against Master Agent sections 44, 48,
61, 73, 75 and 76. The unified World3D V3 stack already used its V2 detector
as the heavy candidate source and CPU patch propagation between detector
refreshes; no second competing World3D implementation was added.

The missing runtime connection was corrected:

- the exact UNKNOWN World3D `track_id` associated with an authoritative addon
  mouseover identity is now carried into the committed `VISUAL_APPROACH` REACH
  intent for friendly interaction and quest-relevant combat approaches;
- the Vision output remains an Observation/measurement and never recognizes
  or commands the entity directly; the persistent skill retains steering,
  forward, stop, occlusion and interaction-probe ownership;
- while that skill is active, patch-tracker/control scheduling targets 25 Hz;
  heavy candidate detection remains independently limited to approximately
  5 Hz, and measured CPU duration applies backpressure so frames cannot queue;
- existing track-loss safety, same-GUID commitment, action verification and
  immediate movement release remain intact.

Offline verification: 536 passed, 2 optional tests skipped. Tests explicitly
cover Track↔Entity propagation into the visual REACH intent, adaptive 25 Hz
tracker scheduling, CPU backpressure, reference-REACH visual interruption and
the earlier movement/reacquisition regressions. This is not live validation.
A restarted agent and user-operated Jaina test are required next.

### 2026-09-10 — Visual-servo measurement fusion 1.0.7 (offline)

The user-supplied gameplay/control decomposition was integrated into the
existing single-agent architecture rather than creating another movement or
vision brain. `VisualApproachController` remains a persistent terminal REACH
mode owned below the Planner.

- every fast update now records one timestamped `VisualServoMeasurement` with
  committed track identity, screen position/error, bbox scale delta, track
  confidence/lifecycle, predicted/observed status, camera motion, latest player
  world position/heading/speed/moving state, telemetry sample time and visual
  obstacle evidence;
- visual scale progress and no-progress observations are exposed separately;
  an obstacle candidate remains evidence and is never promoted to a proven
  blocked path by CV alone;
- a short-lived OCCLUDED track retains its predicted bearing and exact
  commitment, releases forward movement, and permits a small bounded camera
  reacquisition action; it cannot issue blind forward movement;
- the slow Brain remains event/cadence gated and the heavy V2 candidate
  detector remains inside the unified V3 stack rather than competing with the
  fast tracker.

Official Blizzard documentation confirms the relevant client behavior: the
Interact Key works for NPCs and quest objects when the player is in range and
facing them, while Action Targeting changes targets according to viewing
direction. These are treated as action/verification affordances, not visual
ground truth or permission to guess a binding.

Offline verification: 538 passed, 2 optional tests skipped. The added tests
cover multimodal measurement fusion, scale-progress evidence and predicted
occlusion camera-only control. Live terminal approach, interaction-ready
stopping and real-client loop-rate/latency remain unvalidated until a restarted
user-operated Jaina run.

### 2026-09-10 — 20–40 Hz FAST_STATE telemetry 1.0.8 (offline)

The existing AIPC5 FAST packet was completed as a real high-rate lane instead
of adding a competing protocol. The addon now renders on a 25 ms transport
ticker and multiplexes two FAST_STATE packets followed by one paged full-state
packet. Nominal rates are therefore 26.7 fresh control samples/s and 13.3 full
snapshot pages/s. The expensive quest/inventory snapshot remains limited to
5 Hz.

- FAST_STATE is collected into a separate read-only table on every transport
  tick; it no longer mutates the cached full snapshot.
- The bounded packet carries sample time, player map/world position,
  orientation, movement speed/state, target, mouseover and cursor/map-hover
  evidence. An overflow fallback guarantees that long tooltip text cannot
  suppress movement feedback.
- PacketAssembler exposes lane/kind/sequence/receive diagnostics.
- WorldModel merges only the explicit fast-field allowlist and does not
  refresh old quest, inventory or semantic-memory facts from a merged packet.
  A full paged snapshot sampled before a newer FAST packet remains admissible.
- Runtime diagnostics separately report `addon_fast_state_hz` and
  `addon_full_state_hz`; stale quest/spatial-memory projections are not emitted
  for each FAST sample.

Offline verification: 542 passed, 2 optional tests skipped. Coverage includes
the 2:1 schedule, fresh-data separation, oversized inspection fallback, lane
metadata, fast/full ordering and slow-fact isolation. This is not live
validation. The next user-operated client run must
confirm an observed 20–40 Hz `addon_fast_state_hz`, acceptable capture latency,
and stable movement feedback with the 0.9.5 addon installed/reloaded.

### 2026-09-10 — Jaina visual-approach live finding and optimization merge

User-operated PID 13664 testing confirmed that the agent found and selected
Lady Jaina Proudmoore. The first `VISUAL_APPROACH` update then lacked its
associated World3D track, issued a left-button camera pan and lost the selected
target. This was a real-client failure, not a synthetic replay result.

Corrections now preserve a fresh confirmed mouseover anchor while the visual
tracker catches up, prohibit left-button camera reacquisition while the exact
committed GUID is selected, and require at least two forward control updates
before another interaction-range probe. Every new FAST sequence can drive one
visual-servo measurement even when the heavy visual projection has not changed.

The related Claude variant was audited and its validated hot-path corrections
were integrated without replacing the current branch: cached immutable JSON,
fast JSON-tree copies, batched WorldModel rebuild, buffered SQLite relations,
one WAL connection, bounded derived-observation retention, split detector vs.
tracker diagnostics, and compact FAST quest progress. Existing agent-memory
files observed before this change ranged up to 264.65 MB, confirming that the
old 250,000-row raw-observation threshold was not operationally bounded enough.

Offline verification and a local performance microbenchmark are recorded in
`docs/CLAUDE_OPTIMIZATION_AUDIT.md`. A restarted, user-operated bounded client
test is still required; none of these offline results is marked live-validated.

### 2026-09-10 — Rejection-memory evidence quality v2 (offline)

The visual rejection path now separates an execution/aiming failure from
evidence about the observed candidate. `expected_observation_missing` is only
recorded as negative object evidence when the cursor reached the requested
inspection region, a newer observation arrived, the track remained valid and
the candidate had sufficient temporal support. Cursor misses, stale frames and
lost tracks do not teach scenery rejection.

The first valid zero-information hover creates a 15-second `SUPPRESSED` belief
to stop immediate bush/rock/lamp reinspection. Repeated attempts within the
same 30-second scene episode share one evidence group and therefore cannot
promote themselves to persistent rejection. Three temporally independent
zero-information episodes are still required for `REJECTED`; a successful
mouseover/tooltip remains explicit contradicting evidence and clears failures.

Appearance matching now uses a coarse, scale-tolerant signature together with
surface, visual kind and a conservative screen-locality cell. Screen locality
is intentionally temporary until a calibrated screen-ground projection exists:
it prevents a generic scenery appearance from suppressing similar entities
across the whole map. No semantic label is inferred from rejection.

New diagnostics expose `inspection_quality`, cursor distance, hover quality,
track stability, observation freshness, independent-trial count and suppression
expiry. This is offline-tested only; the next user-operated run must verify
that scenery is skipped after one valid hover while Jaina/overhead-symbol
candidates remain inspectable after cursor misses or telemetry delay.

### 2026-09-10 — Committed visual approach safety and fast-loop cost (offline)

The live Jaina overshoot and cursor oscillation paths received three bounded
corrections without changing target identity semantics:

- a movement lease now expires after 450 ms without control refresh instead
  of allowing several seconds of unattended forward input;
- a frozen World3D projection can no longer be made into a fresh steering
  command merely by newer FAST_STATE telemetry. New telemetry may still verify
  target/UI/range state, but only a new visual sample refreshes visual motion;
- an active target commitment rejects unrelated UNKNOWN inspections, generic
  camera searches and unrelated map actions. Only the exact GUID or its
  associated visual track may be inspected; an explicit committed-target map
  fallback remains available when no usable 3D anchor exists.

Near/rapidly-growing target tracks now trigger an earlier bounded interaction
probe, stopping movement before the probe. The high-rate executor no longer
creates two Timer threads per 20–40 Hz update; one persistent watchdog owns
steering and forward expiry.

Offline verification: 557 passed, 2 optional tests skipped. This is not a live
success claim. The next user-operated test must measure target overshoot,
cursor switching, observed tracker Hz, approach stop distance and quest-dialog
opening on the current PID/addon build.

### 2026-09-10 — visible Jaina tooltip without mouseover telemetry

In the user-operated PID 13664 run starting at approximately 16:14:19, the
World3D pipeline selected the stable subject below the overhead symbol and
moved the cursor onto Lady Jaina Proudmoore. The captured client frame visibly
contained Jaina's unit tooltip, but AIPC5 continued to report
`mouseover=false`. Consequently INSPECT could not obtain ground truth, no
target commitment was created, and the agent correctly continued to World Map
search instead of guessing quest-giver semantics. It later returned to
World3D and stopped MANUAL without accepting the quest. This run is a live
failure, but it localizes the break after visual pointing and before addon
identity export.

Addon 0.9.6 adds ordered public-API fallbacks for this exact case:
`UnitExists("mouseover")`/unit data first, then `GameTooltip:GetUnit()`, then
accessible structured primary-tooltip GUID metadata. FAST_STATE now preserves
the identity provenance, bounded tooltip text and structured IDs. Inaccessible
or secret values remain discarded. Python INSPECT verification accepts a new
world-tooltip observation as evidence, while semantic confirmation still
requires the exported structured identity/quest state.

The Claude addon copy was compared before this patch. Its Transport file was
byte-identical to the project version and its Lua difference was explanatory
comments around the quest digest, so it did not yet contain this tooltip-unit
fallback. Addon 0.9.6 requires a user-managed copy/reload before the next live
run.

## Ground-truth mouseover vs UNKNOWN inspection priority regression

User live-debug report: addon 0.9.6 delivered Lady Jaina Proudmoore through `WOW_API_MOUSEOVER` with GUID, NPC ID 156626, name and friendly state. The planner created the correct `TARGET`, but an unrelated UNKNOWN `INSPECT` had higher priority and won selection.

Source fix: a fresh addon-confirmed friendly NPC mouseover handoff now emits `TARGET` with explicit `ground_truth_handoff=true`, `confidence=1.0`, and priority 122. This is intentionally above the maximum active-perception `INSPECT` priority while remaining below the explicit survival interrupt priority (125).

Offline regression added: `test_ground_truth_mouseover_target_beats_new_unknown_world3d_inspection` reproduces a high-value supported-overhead UNKNOWN World3D candidate in the same planning cycle and asserts that the confirmed mouseover `TARGET` wins.

Validation status: **OFFLINE_TESTED**, not newly live-validated by this patch. After the
16:28 live trace was correlated with the exact planner candidates, the focused
handoff/latency/commitment regressions passed `4/4`; the current full suite result is
`559 passed, 2 skipped`. A restarted agent process is still required for live validation,
because the inspected run executed the older priority-72 handoff code loaded before the
priority-122 source correction.

### 2026-09-10 — pre-arm Jaina tooltip and premature World Map fallback

The user-operated PID 13664 run at 21:48–21:49 showed Lady Jaina Proudmoore's
tooltip in the captured 3D frame before FULL_AI armed. The addon samples during
that visible tooltip contained an empty mouseover object rather than a GUID.
When FULL_AI armed two seconds later the hover had already cleared, so no
`TARGET` proposal existed. `OPEN_MAP` outranked the remaining generic World3D
inspections, consumed the bounded run, and the runtime returned to MANUAL due
to `bounded_live_test_timeout`. This was not a failed priority-122 target click:
no target click was issued in this run.

Addon 0.9.7 now reads accessible text from structured primary-tooltip lines and
exports `TooltipDataType.Unit`, `unit_name`, and provenance even when Retail does
not expose a mouseover GUID. The agent may use that structured unit fact for a
selection-only click; success requires the selected target telemetry to return
a real GUID and the same normalized name before any interaction semantics are
allowed. This preserves `DETECTION != RECOGNITION` and does not treat CV text or
appearance as identity ground truth.

Quest search now performs up to four available World3D inspection probes before
allowing an `OPEN_MAP` fallback. The bound prevents an unlimited UNKNOWN-scene
loop while making World Map a genuine fallback at the Exile's Reach start.

Validation status: **LIVE FAILURE DIAGNOSED; FIX OFFLINE_TESTED**. Focused tests
passed `6/6`; the full suite passed `562`, with `2` optional tests skipped. The
0.9.7 addon still needs user-managed installation/reload and a new live run.

### 2026-09-10 — GUID transport verified; compact target lost identity fields

The user-operated run recorded in `live-debug-20260910-220443.jsonl` proves
that the 0.9.7 telemetry path delivered Lady Jaina Proudmoore's full GUID.
At 22:05:19 the agent selected `TARGET` from addon-confirmed mouseover identity
`Creature-0-4234-2175-9499-156626-000021EEC5`; at 22:05:20 target verification
succeeded and the same GUID plus NPC ID 156626 appeared in authoritative target
state. This disproves the earlier hypothesis that Retail universally withheld
NPC GUIDs in this scene.

The next decision incorrectly became `OPEN_MAP`. The smallest bounded FAST
packet retained target GUID/NPC ID/attackable state but omitted name and
`unit_type`; WorldModel replaced the complete nested target with that partial
object. QuestDomain therefore failed to produce `INTERACT`, despite an active
commitment to a selected non-attackable Creature GUID.

Source correction: FAST target/mouseover objects now merge omitted fields only
when their explicit GUID matches the existing unit. Explicit false still clears
the unit and a different GUID never inherits old identity. Independently, a
selected non-attackable `Creature-*`/`Vehicle-*` GUID with an NPC ID is sufficient
unit-identity evidence for a bounded INTERACT attempt; it does not assert a
quest-giver role. Focused regressions passed 4/4 and the complete suite passed
565 with 2 optional tests skipped. Status: **LIVE FAILURE DIAGNOSED; FIX
OFFLINE_TESTED**. Restart the Python agent before the next user-operated run.

### 2026-09-10 — correct World3D hover lost mouseover in oversized FAST payload

The user-operated PID 13664 capture session `20260910-221016` selected the
correct persistent Jaina subject (`WORLD3D:43`) below a SUPPORTED overhead
symbol relation. The first HOVER command's normalized client coordinate maps
back to Jaina in the captured frame; this was not a vertical-coordinate
inversion. A visible NPCodex tooltip was present, but the following FAST packets
contained neither `mouseover` nor `cursor`, so INSPECT expired with
`expected_observation_missing`, tried lower-ranked candidates, and finally
returned to MANUAL without targeting or accepting the quest.

Direct pixel-strip decoding identified the transport failure: NPCodex's long
tooltip text made the first two FAST payload variants exceed the 850-byte lane,
and the final control-core fallback discarded all mouseover identity. Addon
0.9.8 now removes bulky tooltip presentation text first while retaining bounded
mouseover GUID/name/NPC ID/unit type/attackable/dead/provenance plus cursor data.
Only a still-oversized or corrupt identity value may fall back to the minimal
control core, so malformed data cannot starve FAST_STATE.

Validation status: **LIVE FAILURE DIAGNOSED; FIX OFFLINE_TESTED**. The focused
long-tooltip, pathological-oversize and inspection-ground-truth regressions
passed 3/3; the complete suite passed 566 with 2 optional tests skipped. A WoW
`/reload` (or client restart) and a restarted Python agent are required before
the next user-operated live validation.

### 2026-09-10 — local SEEK was incorrectly gated behind map/location search

Planner inspection showed that the bounded World3D SEEK capability existed as
`CAMERA_CONTROL / SCAN_SECTOR`, but its eligibility required arrival at a known
location, a blocked target acquisition, or an already exhausted World Map
search. With no visible target at initial questgiver discovery, `OPEN_MAP` was
therefore selected before local camera search.

The quest discovery order is now: inspect any stable local World3D candidate;
otherwise scan four bounded camera sectors; then permit World Map; finally
permit the TDB reference-location fallback. The scan is restricted to quest
discovery with no competing executable domain action, so it cannot preempt
combat/loot, fishing, repair, vendor work, or other domains. Arrival at an
active quest waypoint may also start the same bounded local search. Immediate
quest accepted/turned-in transition frames remain observation-only.

Validation status: **OFFLINE_TESTED, LIVE VALIDATION PENDING**. New ordering and
regression coverage passed; the complete suite passed 567 with 2 optional tests
skipped. Restart the Python agent before the next user-operated live run.

### 2026-09-10/11 — Jaina reached and dialog visibly opened, but quest UI telemetry stayed closed

The user-operated PID 13808 run (`live-debug-20260910-231131.jsonl`, capture
session `20260910-231131`) produced the first visually confirmed end-to-end
approach to the initial questgiver in this sequence. World3D eventually hovered
Lady Jaina Proudmoore, addon 0.9.8 returned NPC ID 156626 and a Creature GUID,
TARGET verified, the range error correctly started VISUAL_APPROACH, and the
controller moved into interaction range. Capture 0054 at 23:13:01 visibly shows
the quest detail panel and enabled Accept button.

The controller nevertheless did not accept it. Full addon snapshots at
126385.094 and 126392.743 reported `quest_ui.open=false`, and FAST packets did
not carry quest UI state. INTERACT also incorrectly treated the appearance of
an explicit closed quest-ui object after an omitted partial field as success.
After the target track disappeared behind the modal panel, VISUAL_APPROACH
failed and the planner opened World Map over the still-open quest dialog.

Addon 0.9.9 adds a cheap FAST quest-UI projection based on direct named button
visibility plus bounded authoritative QUEST_DETAIL/PROGRESS/COMPLETE event
hints. It exports open/action/click point/quest ID on every control sample and
uses IsShown/IsVisible-compatible frame checks. INTERACT/TALK now verify only a
real open UI transition or quest-state change. Unrelated stale client errors no
longer fail observation-only INSPECT/OPEN_MAP actions.

Validation status: **LIVE APPROACH/DIALOG OPEN CONFIRMED; ACCEPT FIX
OFFLINE_TESTED, LIVE ACCEPT PENDING**. Six focused regressions and the complete
suite passed; current result is 571 passed with 2 optional tests skipped. Addon
0.9.9 requires reload/client restart and the Python agent requires restart.

### 2026-09-11 — bounded SEEK ran, but false modal quest UI disabled World3D

The user-operated PID 13808 run around monotonic 150793 executed all four
bounded `CAMERA_CONTROL / SCAN_SECTOR` steps. This live evidence confirms that
the newly ordered local SEEK path is reachable. It did not find Jaina because
every control sample simultaneously reported `quest_ui.open=true` with no
action, no click point, no quest ID and no entries. World3D V3 consequently ran
in `MODAL_UI` mode and replaced normal subject/symbol detection with one generic
dialog-region candidate. After the four blind scans, the planner correctly
stopped at WAIT rather than inventing a target.

The false open state was caused by `frameIsShown()` preferring WoW
`IsShown()` over `IsVisible()`. Retail can report a frame's own shown flag while
an ancestor makes it invisible. Addon 0.9.10 now treats parent-aware
`IsVisible()` as authoritative and uses `IsShown()` only as a compatibility
fallback. No semantic NPC/quest fact is inferred by this change.

The same long-lived runtime had also exhausted its 180-frame capture allowance,
so the actual SEEK frames were absent even though the action journal remained.
Each explicit FULL_AI/test request now rotates to a new bounded capture segment;
the selected PID scope and 180-frame per-segment bound remain unchanged.

Validation status: **LIVE SEEK EXECUTION CONFIRMED; ROOT CAUSE DIAGNOSED;
0.9.10 FIX OFFLINE_TESTED, LIVE VALIDATION PENDING**. The complete suite passes
573 tests with 2 optional tests skipped. The addon source was intentionally not
installed into the WoW directory; user-managed copy/reload and a restarted
Python agent are required before the next run.

### 2026-09-11 — 0.9.10 World3D recovery succeeded; visual servo remained intermittent

The user-operated PID 13808 run in capture segment
`20260911-061815-874-002` validated the addon visibility correction. Addon
0.9.10 was active, all 139 classified perception samples were `WORLD3D`, and
zero were `MODAL_UI`. The agent immediately inspected the correct on-screen
subject, received Lady Jaina Proudmoore's Creature GUID and NPC ID 156626,
verified TARGET, attempted INTERACT, observed the live out-of-range error and
started the committed `VISUAL_APPROACH`. Captures confirm that the character
moved toward Jaina while retaining the selected target. Quest acceptance was
not reached in this run.

The control trace exposed three independent servo faults. A 400–800 ms heavy
detector result was being reused as scheduler back-pressure for the following
cheap tracker job, so V3 performed almost no high-rate propagation. Duplicate
FAST telemetry without a new visual projection caused Engine to call
`stop_movement()` even though the track remained visible, turning the movement
lease back into pulses. The same frozen visual sample also accumulated false
no-progress evidence. Finally, a generic bbox height near 0.093 was treated as
interaction-near despite the authoritative client reporting out of range,
causing excessive stop-and-probe alternation.

The scheduler now uses measured propagation cost during a committed visual
servo while V3 retains the independent heavy-detector deadline. Duplicate
telemetry leaves the bounded movement lease to the fresh tracker/watchdog and
only an actual OCCLUDED state releases it immediately. No-progress counters
advance only on distinct visual samples. Generic bbox scale no longer shortens
the interaction-probe cadence at the observed Jaina distance, and the exact
selected GUID remains the authoritative bounded range probe.

Validation status: **LIVE WORLD3D/IDENTITY/TARGET/APPROACH CONFIRMED; SERVO
FIXES OFFLINE_TESTED, LIVE ACCEPT PENDING**. The complete suite passes 575 tests
with 2 optional tests skipped. Restart the Python agent before the next run;
the installed addon 0.9.10 does not need another copy for these Python-only
changes.

### 2026-09-11 — two post-servo runs found Jaina, but FAST inspection data was evicted

The two user-operated PID 13808 runs in capture segments
`20260911-063128-382-002` and `20260911-063150-846-003` both remained in the
World3D inspection phase. The detector repeatedly produced the stable subject
region under Jaina's overhead symbol and moved the cursor to it. Captured
frames visibly show the `Lady Jaina Proudmoore / Level 10` tooltip, but each
INSPECT ended as `expected_observation_missing`; neither run reached TARGET or
movement.

The journal and observation store isolate the failure from perception. HOVER
used the correct normalized point near `(0.579, 0.587)`, while following
field-rich FAST packets omitted both `mouseover` and `cursor_position`. A later
FULL_STATE, after the first run had already returned to MANUAL, exported the
same hover as authoritative NPC ID 156626 with the complete Creature GUID.
Thus the visible hover was correct, but the last transport-size fallback had
removed the exact evidence required by the verifier.

Addon 0.9.11 keeps bounded mouseover identity and the simultaneous cursor edge
in every normal FAST fallback, together with minimal movement and target
feedback. Pathologically long strings are omitted individually instead of
evicting the whole inspection sensor. INSPECT now holds the passive hover and
its committed visual candidate for five seconds instead of abandoning it after
two seconds, allowing several live control samples without emitting additional
input.

Validation status: **TWO LIVE FAILURES DIAGNOSED; TRANSPORT/VERIFICATION FIX
OFFLINE_TESTED, LIVE TARGET/ACCEPT PENDING**. Focused regressions pass 127/127;
the complete suite passes 576 tests with 2 optional tests skipped. Addon
0.9.11 requires a user-managed copy/reload before the next live test, and the
Python agent must be restarted for the updated INSPECT contract.

### 2026-09-11 — 0.9.11 FAST identity verified live; TARGET was gated by unrelated FULL_STATE age

The next two user-operated PID 13808 tests validated the transport correction.
In the first run, INSPECT received Lady Jaina Proudmoore's authoritative
mouseover GUID/NPC ID from FAST_STATE in about 0.75 seconds and immediately
issued the correct TARGET click. The selected target subsequently appeared
with the same Creature GUID, but only after the user had already returned the
agent to MANUAL, so that run did not verify the pending TARGET action.

In the second run, FAST_STATE again delivered Jaina's GUID at the correct
cursor coordinate and INSPECT verified successfully. The planner nevertheless
omitted TARGET because SkillRegistry applied the age of the separate paged
FULL_STATE snapshot to the fresh FAST mouseover action. It therefore continued
with unrelated UNKNOWN inspections even though current identity ground truth
was available.

TARGET availability now relies on QuestDomain's simultaneous mouseover/cursor
sample-time contract and is no longer rejected merely because the independent
full snapshot is older than two seconds. Detail-dependent actions keep their
existing full-snapshot age gate. This does not promote CV to ground truth and
does not weaken the selected-PID/session/fresh-telemetry safety boundary.

Validation status: **ADDON 0.9.11 FAST MOUSEOVER LIVE-VALIDATED; TARGET
FULL-STATE AGE FIX OFFLINE_TESTED; END-TO-END TARGET/ACCEPT PENDING**. The
complete suite passes 577 tests with 2 optional tests skipped. Only the Python
agent needs restarting before the next live run; addon 0.9.11 is already
installed and loaded.

### 2026-09-11 — SEEK_VISUAL_CUE GUID nélküli IDENTIFY szervó elkészült

A távoli, stabil, nagy információértékű UNKNOWN World3D cue-k most külön
`SEEK_VISUAL_CUE` persistent skillhez kerülnek. A skill nem követel GUID-ot vagy
kijelölt targetet: ugyanazt a `VisualApproachController` zárt hurkú szervót
használja `purpose=IDENTIFY` módban. Ebben a módban a régi kijelölt target
dead/combat-range állapota nem lehet siker vagy hiba, mert nem arról a vizuális
cue-ról szól, amely felé az agent halad.

A távoli/közeli contract `bbox_height_fraction < 0.09`: távol a szervó közelít,
0.09-nél visszaadja a candidate-et a normál INSPECT láncnak. Friss addon
mouseover GUID esetén korai siker keletkezik
`identity_available_during_visual_seek` okkal, majd TARGET → INTERACT folytatja.
A friss identity explicit handoff, ezért az ugyanabban a tervben levő új UNKNOWN
INSPECT már nem írhatja felül. A sorrend: közeli INSPECT 84–86, vizuális seek 78,
mouseover TARGET 72 (explicit handoff), OPEN_MAP 60, TDB REACH_LOCATION 40.

Validation status: **OFFLINE_TESTED; LIVE PENDING**. A teljes regressziós csomag
586 tesztet teljesít, 2 opcionális teszt kihagyva. Python-agent restart kell;
addonmásolás nem szükséges.

### 2026-09-11 — World3D proposal-flood csökkentése valós replay képen

A felhasználó által adott `image-1789125653376.png` replay-kép az előző
pipeline-ban 36 kimeneti candidate-et adott: ebből 16 általános
`visual_candidate`, 10 subject, 8 symbol és 2 scene volt. A fő ok a laza
multi-scale sliding window, a csak részleges deduplikáció és a korlátlanul
továbbadott gyenge generic proposalok együttese volt.

A World3D V2/V3 közös runtime út most containment-aware overlap suppressiont,
szigorúbb generic-window NMS-t és típusonkénti bounded candidate budgetet
használ. Ez megjelenési hipotéziseket rangsorol, nem szemantikát állapít meg;
minden megtartott candidate továbbra is UNKNOWN. A megadott képen BGRA inputtal
15 candidate maradt (8 subject, 4 symbol, 2 visual, 1 scene), miközben a korábbi
valós Exile's Reach symbol+subject regresszió továbbra is átmegy.

A projekt saját `tools/vision_replay.py` eszközt kapott. Ez a mentett képet a
live Windows capture-rel egyező BGRA csatornasorrendben küldi a detectornak, és
külön riportálja a pre-filter, overlap-suppressed, budget-suppressed és kept
számokat. A korábbi külső replay RGBA byte-sorrendet adott a BGRA pipeline-nak,
ami önmagában is hibás szín-cue-kat okozhatott.

Validation status: **OFFLINE_TESTED; LIVE PENDING**. A teljes regressziós csomag
587 tesztet teljesít, 2 opcionális teszt kihagyva. Python-agent restart kell;
addonváltozás nincs.

### 2026-09-11 — PID 23340: SEEK kiválasztva, de command nélküli indulás elvesztette a skill ownershipet

A user-operated `20260911-133723-087-002` futás képein a questgiver és a sárga
overhead cue végig látható volt. A futó process azonban még az előző World3D
pipeline-t használta: 25–36 candidate jelent meg, nem az új bounded 15–20-as
kimenet. Több stabil false symbolból generált `unknown_subject_probe` kapott
84 + utility prioritást, ezért a planner ötször próbált INSPECT-et különböző
helyeken. Egy hover egy másik playert igazolt; a többi valid hover nulla
információval zárult.

Monotonic 178287.862-nél a planner már helyesen a `SEEK_VISUAL_CUE` skillt
választotta (priority 78), track `WORLD3D:19`, bbox-skála 0.04665. Az első
projection 450 ms-nál régebbi volt, ezért a szervó biztonságosan nem adott W
commandot. Az engine ezt tévesen úgy kezelte, mintha a persistent skill el sem
indult volna: nem hozott létre pending attemptet, miközben a commitment ACTIVE
maradt. A következő tervben emiatt WAIT/INSPECT következett mozgás helyett.

A javítás command nélkül is létrehozza a `SEEK_VISUAL_CUE` persistent attemptet,
majd a következő friss tracker frame-en a shared servo adja ki a movement lease-t.
A symbolból származtatott subject probe most külön `servo_scale_fraction` mezőben
az észlelt cue valódi skáláját viszi tovább; a mesterséges 96–132 px probe-box
mérete többé nem jelent hamis közelséget. A `.09` alatti World3D subject/probe
nem INSPECT, hanem SEEK. A supported-overhead INSPECT prioritás explicit 84/86,
nem nőhet utilityvel 98 fölé.

Validation status: **LIVE FAILURE DIAGNOSED; FIX OFFLINE_TESTED, LIVE PENDING**.
A teljes regressziós csomag 588 tesztet teljesít, 2 opcionális teszt kihagyva.
Python-agent restart szükséges; addonváltozás nincs.

### 2026-09-11 — Goal-aware World3D attention és symbol–subject grouping

A `20260911-133723-087-002` user-operated capture offline replaye igazolta,
hogy az egyszerű sárga-symbol szabály a fáklyát stabilan fontos cue-ként tartotta
meg, miközben a Jaina fölötti valódi Retail badge több, sötét háttérrel elválasztott
arany komponensből állt és a széles foreground maskban összekapcsolódott a
környező név/body pixelekkel.

A detector ezért külön, CPU-takarékos gold-cluster appearance pass-t kapott. Az
eredménye továbbra is `unknown_symbol_candidate`; a `quest_badge_like` kizárólag
megjelenési evidence, nem `QUEST_GIVER` vagy más szemantikai fact. A replayen a
valódi badge bbox-a 576–599 / 201–220 lett `quest_badge_like`; a 477–484 / 173–186
fáklya csak generikus `quest_marker_like` maradt.

A stabil symbol és az alatta levő UNKNOWN subject/probe közös
`VisualObjectGroup`-szerű payloadot kap (`visual_group_id`, member trackek,
appearance label-ek, CANDIDATE/SUPPORTED belief). A csoport szemantikája UNKNOWN.
Quest/combat/gather célnál az active-perception score külön figyelembe veszi a
badge appearance-t és a supported csoportot, egy csoport csak egy INSPECT helyet
foglal, és agent-ciklusonként legfeljebb a három legerősebb World3D csoport jut
az inspection shortlistre. Az összes observation/track a World Modelben marad.

Validation status: **LIVE CAPTURE OFFLINE-REPLAYED; PATCH OFFLINE_TESTED, LIVE
PENDING**. A teljes regressziós csomag 592 tesztet teljesít, 2 opcionális teszt
kihagyva. A következő live futás előtt a Python agentet újra kell indítani;
addonváltozás nincs.

### 2026-09-13 — 9m29s VISUAL_APPROACH freeze diagnosed from live log; safety-deadline reset fixed

A user-operated PID 3808 FULL_AI run (goal "Questelj az Exile's Reach szigeten")
was inspected read-only from `output/live-debug/live-debug-20260913-190622.jsonl`
after the fact (agent already back in MANUAL). Between 19:08:16 and 19:17:45 the
status snapshot showed `decision.skill=VISUAL_APPROACH`,
`result.reason=visual_approach_safety_deadline` and the same `action_id`
completely unchanged for 9 minutes 29 seconds, while `brain_ticks` and
`sensor_diagnostics.polls/updates` kept advancing and fresh addon telemetry kept
arriving the whole time. This consumed roughly half of the ~19-minute session
with no movement command issued and no quest progress.

Root cause: `VisualApproachController.start()` (`visual_approach.py`) only called
`reset()` on an identity (guid/track_id/purpose) change. Restarting the same
identity after a terminal FAILED phase left `started_at` in the past, so the
first `observe()` inside the new `start()` immediately re-hit the 30s
`visual_approach_safety_deadline`, and `command()` returned no commands for a
FAILED phase. `engine.py`'s `if not commands: return self.status(now)` then
skipped creating a new `Attempt` entirely — so `_finish()` never ran again for
this identity. That silently disabled both existing retry-limiting mechanisms
added earlier the same day: `autonomy_loop.py`'s outcome() exemption/block (only
handled `visual_track_lost`, not this reason) and `engine.py`'s
`approach_counts[guid] >= 10` cross-commitment backstop (only incremented on a
completed Attempt). Neither could fire because no attempt ever completed.

Fix: `start()` now also resets when resuming from phase `FAILED` for the same
identity, so every restart gets its own full 30s budget. `autonomy_loop.py`'s
`outcome()` now also treats `visual_approach_safety_deadline` like
`visual_track_lost` (block VISUAL_APPROACH, force REACQUIRE_TARGET/replan)
instead of releasing the whole TARGET commitment on a bare timeout.

No client input was sent by the assistant; this was log-only inspection plus a
Python-only code fix. No addon change. Full regression: 573 passed, 24 skipped
(2 optional real-image fixtures plus the pre-existing environment-dependent
skips), 1 pre-existing unrelated flake
(`test_graph_vision_smoke_on_small_synthetic_image`, documented numpy/opencv
compat issue, per `HOW_TO_USE.md`).

Validation status: **LIVE FREEZE DIAGNOSED FROM LOG; FIX OFFLINE_TESTED, LIVE
PENDING**. The Python agent must be restarted before the next live run; no
addon copy/reload needed. Whether the underlying approach still converges
within a fresh 30s window against this class of target (or how often it needs
more than one retry) is unvalidated and requires a new user-operated test.

One related caveat worth a future look: once `visual_approach_blocked` is set
True on a commitment, the only paths observed that clear it back to False are a
successful VISUAL_APPROACH step or a fresh TARGET re-verification — a
successful REACQUIRE_TARGET alone does not. If REACQUIRE_TARGET keeps
succeeding without ever re-triggering a TARGET click (target stays selected
throughout), VISUAL_APPROACH could stay excluded from matching for the rest of
that commitment's life, since `commitment.last_updated` keeps refreshing on any
other matching proposal and the `STUCK_NO_MATCHING_PROPOSAL` timeout would
never fire. This pattern predates this fix (it already existed for
`visual_track_lost`); not changed here since it needs its own live evidence
before deciding on a fix, and was flagged to the user rather than fixed blind.

### 2026-09-13 — QUEST_DIALOG click coordinates silently stuck at 0,0

Continued user-operated testing the same evening found the freeze fix holding
(no more multi-minute stalls from `visual_approach_safety_deadline`), but
surfaced a separate, higher-impact bug: across several runs the bot correctly
detected an open quest-offer dialog (fast `QUEST_DETAIL`-event hint resolved
`action="ACCEPT"` almost immediately) yet never clicked Accept. Screenshot
evidence (`live-captures/20260913-195019-818-003/0032...0141`) showed the
identical Accept-highlighted "Murloc Mania" dialog open and completely
unchanged for 57+ seconds while `decision.skill` stayed `VISUAL_APPROACH` the
whole time; `QUEST_DIALOG` never appeared as a decision anywhere in that
session's log. The user reported this was a pre-existing issue even on the
original (slower) development laptop, at roughly a 7/10 quest-accept success
rate, and separately confirmed live via `/run print(QuestFrameAcceptButton,
QuestFrameAcceptButton and QuestFrameAcceptButton:IsShown())` that the
classic Retail button itself was present and shown — ruling out an addon/UI
frame mismatch, and also ruling out a Y-axis coordinate-space bug in
`coordinates.py`'s bottom-left-to-screen conversion (verified correct).

Root cause found in `planner.py`'s `QuestDomain.propose()`: `ui.get("x",
state.get("quest_ui_x"))` looks like a fast-lane fallback (mirroring how
`action` correctly falls back via `ui.get("action") or
state.get("quest_ui_action")` two lines above) but isn't one — `dict.get(key,
default)` only substitutes `default` when `key` is *absent*, and the
slow/paged `quest_ui` snapshot always carries `x`/`y` keys (the addon Lua
struct defaults them to 0, never omits them). The fallback to the fresher
`quest_ui_x`/`quest_ui_y` fast-lane fields was therefore dead code: `action`
resolved almost instantly while the click coordinate stayed 0,0 until the
slower full/paged snapshot happened to also refresh `quest_ui` with a real
position. `QUEST_DIALOG` requires `x > 0 and y > 0`, so it was silently never
proposed during that gap, leaving the dialog open indefinitely. The user
separately observed this machine's addon telemetry runs at a much higher rate
than the original laptop's ~10-15 Hz; a faster overall tick rate does not
close this specific fast/slow race and plausibly widens it (more of each
open-dialog window is spent before the slow snapshot's own next refresh),
matching why it read as worse here than the reported 7/10 baseline.

Fixed by preferring the fast-lane value only when the slow-lane one is
falsy/zero (`number(ui.get("x")) or number(state.get("quest_ui_x"))`), for
x, y and quest_id. The rest of the agent code was searched for the same
`<dict>.get(key, state.get(fast_key))` idiom; no other live dual-channel
field pair uses it, so this appears isolated to quest_ui, not systemic.

Added `tests/test_quest_dialog_fast_lane.py`: fast-lane fallback when the
slow snapshot is stale, preference for a genuinely refreshed slow-lane value,
and no proposal when neither channel has a valid coordinate. Full regression:
576 passed, 24 skipped, 1 pre-existing unrelated flake
(`test_graph_vision_smoke_on_small_synthetic_image`).

Validation status: **ROOT CAUSE ISOLATED VIA LIVE SCREENSHOT/LOG EVIDENCE AND
LIVE IN-GAME VERIFICATION; FIX OFFLINE_TESTED, LIVE ACCEPT PENDING**. Restart
the Python agent before the next run; no addon change needed. A flagged,
separate, broader concern (not yet audited or fixed): `VisualApproachController
.max_missing_observations = 8` (`visual_approach.py`) is a tick count, not a
wall-clock duration, so it is reached far sooner in real time on a
higher-Hz machine than it was tuned for; other tick-counted thresholds may
exist elsewhere in the codebase and warrant a dedicated pass.

### 2026-09-13 — quest_ui fix live-validated; bot re-approached the same NPC after accepting

A user-operated live restart validated the quest_ui fast-lane fix end to end:
`QUEST_DIALOG SUCCESS` fired, chat log showed `Quest accepted: Murloc Mania`,
and the objective tracker showed `0/6 First Aid Kits recovered from defeated
Murlocs` (confirmed via screenshot). Two further issues surfaced in the same
and a subsequent run:

1. The character visibly walked past/away from Lady Jaina Proudmoore during a
   VISUAL_APPROACH toward her (three screenshots, `current_target` confirmed
   as Jaina throughout via the memory DB's `AGENT_TRACE` observations, ruling
   out a target-identity mixup). The moment-to-moment steering samples
   (`VISUAL_APPROACH_CONTROL_UPDATE`) are not persisted to `agent_memory
   .sqlite3` (only `PLAN`/`VERIFICATION`/`ACTION_INTENT`/`ACTION_EXECUTED`
   are), so the exact steering defect could not be pinned from available
   logs alone. **Unresolved** — needs either persisted per-tick track
   samples or a shorter, targeted live capture to diagnose further.

2. Immediately after the successful accept, the bot re-selected and
   re-interacted with Jaina again instead of moving toward the quest
   objective. User confirmed the intended behavior: only quest-relevant NPCs
   (quest givers, quest-objective NPCs) should be worth revisiting — not any
   friendly target indefinitely.

Root cause for (2): `QuestDomain.propose()`'s generic "verify interaction of
the selected friendly unit" proposal (priority 70) has no "already did this,
nothing changed" concept — it fires every tick for as long as a friendly NPC
with a name/npc_id/quest_role stays targeted. A first attempt narrowed the
underlying `interaction_evidence` condition itself, but that broke 5 existing
tests: it also covers the deliberate, previously-validated "try INTERACT
before falling back to OPEN_MAP" behavior for whatever is *just* selected as
the live target, before any quest_role is even known yet
(`test_agent_core.py`'s `test_confirmed_friendly_target_is_interacted_with_before_opening_map`
and others). Reverted that part.

Fixed instead with `QuestDomain.interacted_guids: dict[str, str]`, recording
guid -> `quest_signature` at the moment INTERACT/TALK/QUEST_DIALOG last
succeeded (hooked in `engine.py`'s `_finish()`), and skipping the generic
proposal while the signature is unchanged. A changed signature (fresh
accept, objective completed) lifts the gate again, so a later legitimate
turn-in is unaffected. The first-contact and interaction-range-block paths
are untouched. Added `tests/test_friendly_interact_gate.py`. Full
regression: 581 passed, 24 skipped, 1 pre-existing unrelated flake.

Validation status: **RE-APPROACH-AFTER-ACCEPT FIX OFFLINE_TESTED, LIVE PENDING.
WALK-PAST-NPC STEERING ISSUE STILL UNDIAGNOSED** — needs its own live evidence
before any code change; do not guess at a fix without it.

### 2026-09-14 — MOVE froze for 64s+ after a successful accept; F12 used

A user-operated overnight run accepted "Murloc Mania" cleanly (QUEST_DIALOG
SUCCESS, chat confirmed "Quest accepted"), then `decision.skill=MOVE` toward
the quest waypoint displayed completely unchanged for 64+ seconds. Three
capture screenshots across that window (04:49:45, 04:50:17, 04:50:48) are
pixel-identical: no dialog, no obstruction, player standing still next to
Jaina the entire time. The user hit F12 (emergency stop) to end it.

This is the same architectural gap already fixed the previous night for
VISUAL_APPROACH's safety-deadline case, reached through a different terminal
phase and controller: `ReachMovementController.start()` discards its own
internal `observe()` return value; when that first observe() already lands
on ARRIVED (destination already within `stop_distance`) — plausible here
since Exile's Reach had not yet placed a precise quest-POI marker (the
"Find nearby objectives by looking at your Minimap" prompt was visible) —
`command()` correctly returns no commands for that phase, and engine.py's
`if not commands: return self.status(now)` gate then discarded the result
entirely instead of creating a trackable Attempt. `self.pending` stayed
`None`, so `_finish()` never ran, `mark_location_reached()` never got called,
and the identical MOVE proposal kept regenerating and silently
re-"arriving" forever. VISUAL_APPROACH has the identical gap through its own
first-tick OCCLUDED case.

Fixed by extending the existing SEEK_VISUAL_CUE exemption (already in place
because *that* skill can deliberately produce no commands on its first tick)
to also cover MOVEMENT_SKILLS and VISUAL_APPROACH — the downstream `if not
commands: pass` handling needed no change, it already creates and records
the Attempt for exactly this reason. The next tick's already-pending branch
then correctly reports the terminal outcome through `_finish()`. Added
`tests/test_persistent_skill_attempt_gate.py`, reproducing the "arrived
within stop_distance on the very first tick" case end to end through
`AutonomousAgent.tick()`. Full regression: 582 passed, 24 skipped, 1
pre-existing unrelated flake.

Validation status: **OFFLINE_TESTED, LIVE PENDING**. Restart the Python agent
before the next run; no addon change needed.

### 2026-09-14 — two additive, defense-only fixes made without further live re-validation

After the MOVE-freeze fix above, a longer overnight run showed MOVE now
correctly hitting its 90s `movement_safety_deadline` and recovering (RECOVER
-> SEEK_VISUAL_CUE -> COMBAT) instead of freezing forever -- confirming that
fix works. But `RECOVER`'s "world position unchanged for too long" trigger
showed the underlying non-movement was real, not just a reporting gap. The
user reported that manually moving the mouse made the character start
moving again. No capture screenshots exist for this exact window (the
180-frame segment cap had already rolled over by then).

Given the user explicitly asked what could be improved without further live
confirmation, two independent, purely-additive fixes were made -- both
structured so they can only add a missing safeguard, never remove or loosen
an existing one, which is what makes them safe to land without their own
live cycle:

1. `VisualApproachController.max_missing_observations` (8) is a tick count,
   not a duration -- tuned for a ~10-15 Hz addon rate (originally ~0.5s),
   it fires much sooner in real time on a faster machine (the user confirmed
   this machine runs noticeably faster than the original dev laptop).
   `SeekVisualCueController` reuses this same controller as its servo, so
   both skills were affected. Added `max_missing_seconds` (1.0) as a second,
   independent condition alongside the existing count, matching the
   already-proven count+duration pattern already used in
   `movement_controller.py`. At the original slow rate the duration was
   already satisfied whenever the count was, so behavior there is
   unchanged; only unrealistically-fast ticking is affected.

2. `execute_movement()` only tracks its own belief (`self._held`) of which
   keys are down and skips re-pressing one already believed held -- if the
   game or Windows silently drops a held key without us knowing (a brief
   focus glitch `is_selected_foreground()`'s HWND check would not catch),
   that belief and reality can diverge permanently for as long as the same
   direction keeps being requested, since nothing in that path ever forces
   a fresh key-down again. This matches the reported symptom: MOVE
   commanding the same direction for 64+ seconds with zero displacement,
   "fixed" by an unrelated real mouse move. Added `WindowsInput.is_key_down()`
   (`GetAsyncKeyState`, previously only used for the F12 kill switch) and a
   staleness check in `execute_movement()`: a "held" key verified as not
   actually down is released (no-op if already up) and re-pressed, exactly
   like a direction change already does. Additive and backend-gated
   (`getattr(..., "is_key_down", None)`); a backend without the check,
   including every existing test double, is unaffected, and when real state
   already agrees with tracking nothing changes either.

Neither fix is proven to be *the* explanation for the reported symptoms --
they are code-level gaps that match the evidence and can only help, not
hurt, which is why they were made without a live cycle in between. The
walk-past-NPC steering issue from the previous entry remains genuinely
undiagnosed and was not touched. Full regression after both: 587 passed,
24 skipped, 1 pre-existing unrelated flake.

Validation status: **OFFLINE_TESTED ONLY; NEITHER FIX HAS LIVE CONFIRMATION
YET**. Restart the Python agent before the next run; no addon change needed.

### 2026-09-14 — capture backend + addon 0.9.18 prepared; full pre-live checklist

Three related, larger changes were prepared this session in response to the
capture-pipeline bottleneck diagnosed above. None have live confirmation
yet; the user was away from the machine for the addon-side pieces. This
section is the single checklist to work through at the next live session,
in order (each step's result affects whether the next is worth trying).

**What was implemented:**

1. `dxgi_capture.py` -- optional `DxgiClientCapture`, selected only via
   `AIPC_CAPTURE_BACKEND=dxgi` env var (default unset = unchanged GDI
   `ClientCapture`, zero behavior change). Live smoke-tested on this machine
   against the real running WoW window: exact byte-length match, visually
   correct captured screenshot, clean create/grab/release, and (after an
   initial wrong measurement was caught and redone correctly) a genuine
   ~60 distinct-frame/sec ceiling — the display's own refresh rate, vs GDI's
   measured ~28 Hz raw poll rate. Also fixes a bug caught before landing: the
   new sensor-selection branch in runtime.py referenced `os.environ` without
   `import os`, which would have broken every default `AgentRuntime`
   construction (no existing test exercises that branch — all pass
   `sensor=...` explicitly).
2. Addon 0.9.18: `TRANSPORT_INTERVAL` raised 0.025 -> 1/60 (40 Hz -> 60 Hz)
   to match DXGI's measured ceiling.
3. Addon 0.9.18 + Python: fast-lane combat cast confirmation
   (`combatHint`/`readFastCombatHint`, mirroring `questUIHint`), wired
   through `telemetry_packets.py`, `world.py`'s `fast_keys`, and
   `skills.py`'s COMBAT/DEFEND `verify()` as `fast_cast_verified`
   (additive alongside the existing slow-lane `cast_verified`).

**What needs to be implemented still (not done this session):**

- Nothing code-wise is required before testing the above -- but if COMBAT
  still fails after this, consider a fast-lane objective-progress signal
  (beyond `quest_digest`, which only covers LOOT/GATHER-type counts) for
  kill-credit specifically, and revisit whether `combat_action()`'s ability
  selection is choosing a genuinely castable spell (some actionbar entries
  logged tonight showed `is_usable=false` / `lacks_resource=true` --
  untouched this session, may be a separate contributing cause of the 7/7
  COMBAT failures beyond confirmation timing).

**What needs to be tested live, in order:**

1. **Baseline sanity, GDI unchanged**: with `AIPC_CAPTURE_BACKEND` unset,
   confirm the agent behaves exactly as before addon 0.9.18/DXGI existed
   (this isolates whether any regression came from the addon change vs the
   capture change).
2. **Addon 0.9.18 alone**: install/reload it, restart the Python agent,
   still with GDI capture (`AIPC_CAPTURE_BACKEND` unset). Check in-game FPS
   during a FULL_AI run (the user's own FPS display) -- confirm 60 Hz Lua/UI
   work doesn't measurably drop it from the ~100 FPS reported at 40 Hz.
   Check `sensor_diagnostics`/`loop_rates` in the live debugger for whether
   `addon_payload_hz`/`addon_fast_state_hz` rose at all (GDI is still the
   receiving bottleneck here, so a large rise isn't expected yet -- this
   step is really about the addon-side FPS cost, isolated from capture).
3. **DXGI capture, addon 0.9.18 together**: set
   `AIPC_CAPTURE_BACKEND=dxgi` (requires `pip install dxcam`), restart.
   Confirm: no crash on startup (dxcam import/camera creation); a real
   AIPC5 payload actually decodes (unconfirmed in this session's smoke test
   -- no character was in-world then); `addon_payload_hz`/
   `addon_fast_state_hz` in the live debugger rise meaningfully toward the
   new 60 Hz ceiling (the whole point); `telemetry_stalled` failures become
   rarer across INTERACT/COMBAT/MOVE.
4. **Combat cast confirmation specifically**: run the actual kill-murlocs
   objective. Check whether COMBAT now verifies as SUCCESS promptly (well
   under the 8s timeout) instead of the 7/7 failure rate from earlier
   tonight, and whether `combat_last_spell_id`/`combat_last_cast_at` show
   up with real values in the live status (`world` section) during combat.
5. If all of the above hold: consider making `dxgi` the default backend
   (flip runtime.py's fallback), but only after step 3 has been confirmed
   clean across more than one session.

No addon-side change here has been installed into the user's live AddOns
directory by the assistant; both copies in the repo were updated and kept
byte-identical, per this project's own convention, but the user must
copy/reload them.

Validation status: **ALL THREE PREPARED; NONE LIVE-CONFIRMED**. Full
regression after all three: 613 passed, 6 skipped (lupa was newly installed
this session, unlocking Lua-execution tests that were previously silently
skipped), 1 pre-existing unrelated flake.

### 2026-09-14 — COMBAT never once succeeded in a 36-minute session; timeout too short for its own evidence

The user described the expected next step of the "Murloc Mania" questline
(target a murloc, attack with an actionbar ability, loot the corpse for
First Aid Kits) and asked for it to actually work; they were away from the
machine and could not run a new live test, so this was a static audit of
the already-captured overnight session instead of a fresh live cycle.

Grepping that session's own narrative found COMBAT proposed at least 7
times (05:14, 05:15, 05:25, 05:28, 05:30, 05:32, 05:34) and never once
verified as SUCCESS -- every single attempt ended `telemetry_stalled` or
`expected_observation_missing`.

Root cause: `SkillContract("COMBAT", ...)` and `("DEFEND", ...)` had a
3-second timeout, but `verify()`'s COMBAT/DEFEND branch (`skills.py`) checks
a `SPELLCAST_SUCCEEDED` entry in `events` and `objective_progress()`
(reading `active_quests`) -- neither `events` nor `active_quests` is in
`world.py`'s `fast_keys`, unlike LOOT's `quest_digest` fallback. GATHER/
HERB/MINE already use an 8-second timeout for the identical
"inventory_or_objective_progress" slow-lane category (their own contract
comment even says so); COMBAT/DEFEND's 3s was inconsistent with that
sibling precedent already sitting in the same file, and well below the
multi-second (sometimes 8+ second) paged-snapshot delays this same
session's own telemetry showed repeatedly for other skills tonight.

Widened both to 8s to match GATHER/HERB/MINE. This only gives legitimate
slow-lane confirmation more time to arrive before giving up; it does not
change what counts as success. Added
`tests/test_combat_verification_window.py`. Full regression: 588 passed,
24 skipped, 1 pre-existing unrelated flake.

Validation status: **ROOT CAUSE FOUND VIA LOG AUDIT (NOT A FRESH LIVE
CYCLE); FIX OFFLINE_TESTED, LIVE PENDING**. This is the most likely reason
the "kill murlocs" objective has not progressed at all tonight (0/6 the
entire session) -- worth prioritizing as the next thing to confirm live.

### 2026-09-14 — offline replay from recorded sessions: screenshots don't carry it, but the debugger now can

The user asked whether a saved-screenshot directory from a live-capture
session could be turned into something the agent could be run against
offline, to see what it would have decided -- and whether the addon/WoW
client is actually required for that.

First built `tools/screenshot_session_replay.py`, which decodes each
manifest-listed JPEG's embedded AIPC5 pixel-strip payload
(`decode_payload_from_bgra`) and feeds it through `PacketAssembler.feed()`
to reassemble complete states, exactly like the live pipeline does. Spot
checks first confirmed screenshots really do carry a fully decodable
payload despite JPEG compression (3/3 images across two different session
dates decoded successfully) -- so the theory looked sound.

Ran it against real data next, across several of tonight's and last
night's live-capture segments (up to 180 frames each). Result: **0
complete states reassembled in every segment tried**. Root cause, confirmed
by inspecting the actual decoded payload kinds/pages per segment: the debug
screenshot capture only saves a frame roughly every 0.5s (the same 0.5s
write-gate `runtime.py`'s `step()` uses for `agent_status.json`), while a
`STATE_Z` full snapshot is paged across multiple consecutive AIPC5 packets
transmitted at the addon's own transport rate (now up to 60 Hz). In every
segment checked, consecutive screenshots almost never land on two different
pages of the *same* snapshot sequence -- mostly isolated `FAST` packets
(which can't produce a result until a full snapshot already exists) and
`STATE_Z` fragments where only 1-2 of the required page indices were ever
observed. So: **screenshots alone, as currently captured, cannot be turned
into a replay trace** -- this isn't a guess, it's what happened on real
saved sessions.

The actual fix: `world.player` inside `agent_status.json` (surfaced via
`AutonomousAgent.status()` -> `WorldModel.snapshot()`) is already the exact
same dict shape `AutonomousAgent.tick()` ingests live as its `payload`
argument -- no pixel decoding needed at all. `tools/live_debug_monitor.py`
(the same `START_LIVE_DEBUGGER.bat` tool already run every session) now
also appends `output/live-debug/telemetry-<timestamp>.jsonl`, one
`{"at": ..., "state": ...}` row per observed tick, directly consumable by
the already-existing, already-tested `wowbot.agent.runtime.replay()` used
for `tests/fixtures/agent_quest_replay.jsonl`. This answers the user's
underlying question going forward: no, WoW/the addon is not needed to
replay a session recorded this way after tonight -- but sessions recorded
*before* this change have no such trace and cannot be replayed, since
nothing preserved their full state history until now.

Added `tests/test_screenshot_session_replay.py` (proves the packet-
reassembly mechanism itself is correct against synthetic dense frames, even
though it's a dead end against real sparse captures) and extended
`tests/test_live_debug_monitor.py` with `telemetry_row()` unit tests plus
one end-to-end test that feeds `live_debug_monitor`-shaped rows straight
through the real `replay()`. Full regression: 620 passed, 6 skipped, 1
pre-existing unrelated flake.

Validation status: **`screenshot_session_replay.py` LIVE-TESTED (against
real saved sessions) AND CONFIRMED NOT VIABLE with current capture cadence
-- kept as a correct, tested utility in case capture density changes
later, not as the working solution.** The `live_debug_monitor.py`
telemetry trace is **OFFLINE_TESTED (synthetic + real `replay()` round-
trip), LIVE PENDING** -- next live session should confirm
`output/live-debug/telemetry-*.jsonl` actually accumulates real rows, and
that replaying it afterward reproduces sensible decisions.

### 2026-09-14 — obstacle_candidate was dead code: nothing ever produced it

The user asked for the agent to be able to "see what it's stuck in and how
to get around it" -- something visibly beyond today's stuck-detection,
which only knows "position isn't changing."

Audited the full path before writing anything. Found that
`movement_controller.py` (stuck-evidence aggregation), `navigation.py`
(`observe_failed_move`'s blocked-corridor memory, `obstacle_trials`/
`obstacle_claims`) and `visual_approach.py` all already filter
`visual_candidates` for `(item.get("detector_kind") or item.get("kind"))
== "obstacle_candidate"` -- a fairly complete consumer side, including a
whole path_key-based "remember which corridor was blocked" memory system
(see `docs/MOVEMENT_OBSTACLE_EVIDENCE_FIX.md`, an earlier fix to that same
memory's evidence-clearing bug). But grepping the entire vision pipeline
(`world3d/probe.py`, `normalization.py`, `local_world.py`,
`mouseover_association.py`) turned up **zero** places that ever set that
label: `probe.py` hardcodes `"obstacles": []`, and `normalization.py` has
an explicit comment that obstacle candidates are "deliberately NOT
promoted" to that field. All three consumers were dead code in practice --
`observe_failed_move` always returned `None` because `hypotheses` was
always empty.

Root fix (Option A of three discussed with the user; a heavier "real
geometric obstacle map from client vmap/mmap-style data" option was
deliberately deferred, see `docs/OBSTACLE_MAP_OPTION_C_BACKUP_PLAN.md`):
reuse signals World3D's tracker already computes for every tracked
candidate -- no new CV. `obstacle_perception.py`'s `tag_obstacle_candidates()`
marks a tracked candidate `detector_kind: "obstacle_candidate"` when it is
static relative to camera-compensated motion (`appearance.static_scene_score`,
computed in `world3d/tracking.py` from `track.hits >= 4` and low mean
residual motion -- distinguishes static geometry from a moving mob/NPC),
fills a meaningful share of the frame height (close, not a distant speck),
sits in the lower/near part of the view, and has been tracked continuously
for a few frames (>=3, matching the `stable_frames` convention used
everywhere else in this codebase). Wired into `perception.py`'s
`_candidates()` right before it returns -- one import, one line.

This alone reactivates all three existing consumers with no changes to
them. Additionally made `RECOVER` directional instead of blind alternation:
`skills.py`'s RECOVER branch now calls `obstacle_perception.obstacle_bearing()`
and strafes away from a seen obstacle's average screen-x, falling back to
the previous blind left/right alternation only when nothing is currently
tagged as an obstacle.

Added `tests/test_obstacle_perception.py` (tagging heuristic: static/tall/
close/stable candidates get tagged, moving/small/distant/unstable ones
don't, input never mutated, `obstacle_bearing()` averages only tagged
candidates) and `tests/test_recover_obstacle_direction.py` (RECOVER strafes
right for a left-side obstacle, left for a right-side one, keeps the old
alternation with no obstacle visible, still jumps simultaneously). Full
regression: 633 passed, 6 skipped, 1 pre-existing unrelated flake.

Validation status: **OFFLINE_TESTED ONLY, LIVE PENDING.** This has never
run against a real captured frame with a real tracked candidate -- the
`static_scene_score`/`bbox_height_fraction`/`y` thresholds
(`obstacle_perception.py`'s module constants) are reasoned from the
tracker's own computation, not tuned against real footage. Next live
session should watch whether `detector_kind: "obstacle_candidate"` ever
actually appears in `visual_candidates` (surface it in
`live_debug_monitor.py` if not already visible enough), whether RECOVER's
strafe direction now looks sensible relative to what's actually blocking
the character on screen, and whether the thresholds need adjusting (too
strict: real obstacles never get tagged; too loose: normal NPCs/mobs get
mistagged and RECOVER fires or steers away from something that wasn't
actually blocking movement).

### 2026-09-14 — auto-labeled vision dataset collector (Stage 1 of active-learning)

The user asked how vision could eventually learn to tell NPCs from mobs
from scenery, then correctly guessed this had already been planned
(`docs/VISION_V3_V4.md`'s "V4 active-learning foundation" section) and
left unfinished at unlabeled hard-example collection. Full design
reasoning and code pointers are in `docs/VISION_V3_V4.md`'s own
2026-09-14 entry, not duplicated here.

Summary: `src/wowbot/agent/vision_dataset.py`'s `AutoLabeledExampleCollector`
correlates addon-confirmed mouseover identities with tracked WORLD3D
candidates at the same screen position, saving free, already-labeled
crops (`output/.../vision-dataset`) instead of the existing unlabeled
hard-example pile. Wired into `AgentRuntime.step()`, surfaced as
`vision_dataset` in `agent_status.json` and the live debugger. This
produces no behavior change by itself -- it is a data-collection
prerequisite for a future classifier (Stage 2) and pre-INSPECT filter
(Stage 3), both still unimplemented and, per the user's own framing
tonight, intentionally deferred until enough real play data accumulates.

Full regression: 650 passed, 6 skipped, 1 pre-existing unrelated flake.

Validation status: **OFFLINE_TESTED ONLY, LIVE PENDING.** Next live
session should watch `agent_status.json.vision_dataset.saved` (or the live
debugger's line for it) actually climb above 0 during normal mouseover
activity -- 0 all session would mean either mouseovers aren't landing near
a tracked candidate often enough, or the distance threshold needs
loosening.

### 2026-09-14 — AIPC5 FAST-lane 40 Hz attempt

The last DXGI gameplay trace was measured before changing code. Over roughly
240 seconds, the addon itself advanced its FAST sequence at about 37.5 Hz,
while the background capture worker polled at 27.6 Hz, assembled/published
17.7 updates/s and the main runtime consumed a median 12.0 updates/s. The old
metric name `addon_payload_hz` therefore described main-thread mailbox
consumption, not the Lua addon's source rate. The source used a 60 Hz ticker
but spent every third frame on a paged full-state packet (2 FAST : 1 STATE),
which made 40 FAST Hz impossible even with perfect capture.

Prepared version 0.9.19 changes that multiplex to 4 FAST : 1 STATE: nominally
48 FAST packets/s and 12 full-state pages/s. DXGI background polling now runs
at 120 Hz so it does not phase-lock against the ~60 Hz compositor; the GDI
fallback remains at its prior 40 Hz ceiling because each GDI poll performs a
full BitBlt. Sensor diagnostics now distinguish capture attempts, real frames,
decoded source packets, FAST source packets, STATE pages, assembler publishes,
mailbox updates and main-thread consumption.

The runtime projection returned by `PerceptionWorker` no longer republishes
six bounded but large per-track history arrays on every control observation.
Those histories remain intact inside `VisualTrackManager` and its diagnostic
snapshot; only the high-rate current-state projection is slimmed. A captured
live state showed those histories accounting for roughly 331 KB of a 479 KB
player projection, so this removes repeated deepcopy/JSON work without deleting
tracking evidence or changing the detector API.

Offline validation: transport reassembly (including long Unicode full state),
4:1 lane ratio, buffered sensor behavior/metrics, GDI/DXGI selection, runtime,
visual tracking and addon-package parity all pass: 70 passed, 2 optional DXGI
tests skipped. Full suite: 651 passed, 6 skipped, with the one previously known,
unrelated OpenCV line-detector shape failure in
`test_graph_vision_smoke_on_small_synthetic_image`.

Validation status: **OFFLINE_TESTED, LIVE PENDING.** Do not claim 40 Hz from
the nominal ratio. The next user-operated gameplay run must verify addon
0.9.19 after `/reload`, DXGI `interval_ms` about 8.333, source FAST rate near
40–48 Hz, continued complete full-state assembly, main `fast_control_hz`,
mailbox coalescing, step p95 and status-write latency. If source FAST reaches
the target but main consumption remains low, the next measured bottleneck is
the synchronous WorldModel/status/persistence path rather than the addon.

### 2026-09-14 — 0.9.19 live rejection and 0.9.20 correction

The user-operated 0.9.19 FULL_AI run immediately looked worse. The attached
console trace alternated `streaming` and `selected_PID_not_foreground` almost
every frame and eventually reported `expected_observation_missing`. The agent
was returned to MANUAL with zero held keys before the correction was prepared.

Root cause is confirmed and narrower than a real focus loss: dxcam's normal
`grab() -> None` result means the 120 Hz poll landed between two ~60 Hz desktop
presents. `PixelSensor` incorrectly assigned every `None` the GDI-specific
meaning `selected_PID_not_foreground`. Thus the new faster poll exposed an old
ambiguous return contract and made health flap at roughly every other poll.
The independent runtime/input foreground check remained authoritative; the
console sensor label was wrong.

Despite the bad label, a clean 4.67-second foreground slice measured 52.4 real
frames/s, 42.2 decoded FAST-looking frames/s and 38.3 assembler publishes/s,
versus the previous run's median ~12 main-thread payloads/s. The apparent
cumulative `source_fast_hz` was also misleading because it included the long
pre-focus period and counted duplicate displayed packets. These measurements
are therefore evidence that the capture path improved, but **not** evidence
that 0.9.19 was acceptable: health semantics and the displayed rates were
wrong, and main control remained about 28 Hz in that short slice.

Prepared 0.9.20 corrections:

- DXGI explicitly distinguishes `no_new_frame` from real focus loss and keeps
  the last valid frame/streaming health between compositor presents.
- Client rectangles partially outside the DXGI output are intersected and
  padded back to the original client coordinate space instead of throwing
  `Invalid Region` repeatedly.
- All sensor rates use rolling windows. `source_fast_hz` now counts only FAST
  packets accepted as fresh by `PacketAssembler`; decoded/repeated FAST frames
  are reported separately as `decoded_fast_frame_hz`.
- The status JSON write uses a latest-only background writer, removing the
  observed periodic synchronous write stalls from the control thread.
- Transport is 5 FAST : 1 STATE page (nominal 50/10 Hz) to leave measured
  headroom for a 40 Hz fresh FAST target while retaining roughly one complete
  compressed full snapshot per second at the observed page count.

Offline validation after correction: 78 focused tests passed, 2 optional tests
skipped. Full regression: 654 passed, 6 skipped, with only the same pre-existing
unrelated OpenCV line-detector shape failure.

Validation status: **0.9.19 LIVE-TESTED AND REJECTED; 0.9.20 OFFLINE-TESTED,
LIVE PENDING.** The next run should begin in MANUAL and remain foreground for
at least 15 seconds before judging rolling rates. Only after stable sensor
health, fresh full states and zero runtime/status-writer errors should a bounded
FULL_AI test be considered.

### 2026-09-14 — loot retry-loop diagnosis and correction

The user-operated `live-debug-20260914-202340.jsonl` / matching telemetry run
proved that the first corpse interaction did loot successfully: event sequence
3712 is `LOOT_RECEIVED` for a First Aid Kit and the corpse tooltip objective
advanced from 0/6 to 1/6. The failure was the behavior after that success. A
later `MOUSEOVER_CHANGED` for the same corpse GUID
`Creature-0-4240-2175-176566-150228-0000A83B47` recreated its confirmed corpse
anchor, causing repeated LOOT attempts against an already empty corpse.

The same run also falsified the TARGETLASTTARGET fallback. The selected cache
contains `F1 -> TARGETLASTTARGET`, but the current client binding inventory
reports no client key for that action, and pressing F1 did not restore the
corpse target. In addition, sending TARGETLASTTARGET before INTERACTTARGET is
incorrect when a dead target is already selected because it can toggle away
from that corpse.

Correction: successful loot now tombstones the exact corpse GUID for five
minutes, source-less LOOT_RECEIVED events retire the newest confirmed corpse
(with multi-item loot bursts kept on that same GUID), and later event or
live-mouseover samples cannot recreate that corpse anchor.
Targeted loot sends only INTERACTTARGET; confirmed screen-space corpse anchors
still use the live-proven right click. The planner no longer spends its
post-combat window on the unverified TARGETLASTTARGET fallback.

Validation status: **OFFLINE-TESTED, LIVE PENDING.** The focused agent suite is
81/81 passing. Full regression is 657 passed, 6 skipped, with only the same
pre-existing unrelated OpenCV line-detector shape failure. A user-operated live
run must confirm that each new corpse is right-clicked once,
LOOT_RECEIVED/objective progress retires it, and the agent moves on without
revisiting the same GUID.

### 2026-09-15 — V2 adoption audit and first correctness tranche

The user-supplied 73-section V2 specification is preserved byte-for-byte as
`MASTER_AGENT_PROMPT_V2.md` (SHA-256
`B93F21960D6D35A73D601BF16B5246486F7E1261EC11B7AB403A7218D83F124B`). It is a
companion to, not a silent replacement for, the existing 83-section agent
master. `MASTER_V2_COVERAGE.md` records every V2 section and explicitly lists
the unimplemented foundations; the checkmarks in the supplied document were
not treated as repository evidence.

Four runtime defects found during the audit were corrected. FULL_AI arming now
reruns binding preflight after ingesting the fresh selected-client actionbar,
and fails closed without input when a harmful action is missing from the
selected bindings cache. Character/session changes now close the old episode,
force MANUAL and clear every planner search, cooldown, location, interaction,
camera and scoring cache. Confirmed mouseover screen anchors now inherit the
previous merged camera estimate, so camera-only motion invalidates stale click
coordinates. Addon corpse-event coordinates are correctly labelled
CLIENT_BOTTOM_LEFT. The map line detector now accepts both OpenCV `(N,1,4)`
and `(N,4)` result shapes.

The World3D detector tracker and the source-level visual tracker no longer use
order-dependent greedy matching. Both use the same dependency-free Hungarian
minimum-cost assignment with family/distance hard gates. Regression coverage
includes the classic greedy candidate-steal/ID-switch case and rectangular,
fully gated assignment matrices.

The planner now receives a typed `WorldSnapshot` instead of the mutable
`WorldModel` object for proposal generation and plan-horizon construction.
Facts expose monotonic `age()`/`is_fresh()`, observation/source identity,
confidence and per-source revisions. Each snapshot has an integer revision,
top-level read-only state, explicit source health and the active commitment.
The view is intentionally shallow on the hot path to avoid reintroducing the
deep-copy latency that previously reduced control Hz; Agent.tick's lock keeps
the referenced nested observations stable for the planner call.

Validation status: **OFFLINE-TESTED, LIVE PENDING.** Python compile and import
smoke pass. Full regression is 670 passed, 6 optional tests skipped. The first
full attempt failed only because the system C: temporary drive had 11 MB free;
rerunning with a project-local F: temporary directory passed completely. No
live client input was taken over. The next user-operated run should revalidate
arming rejection, camera-anchor invalidation and track identity stability;
the larger V2 gaps remain listed in `MASTER_V2_COVERAGE.md` and are not claimed
complete.

### 2026-09-16 — 0.9.21 mouseover identity and target-relevance recovery

The exact selected PID 14960 and the explicit selected bindings cache were
used in a bounded live FULL_AI run. Addon 0.9.21 reported `Coastal Goat` as
`quest_related=true`, `quest_id=55174`, proving the tooltip-to-active-quest
handoff live. A preceding quest-related `Prickly Porcupine` was selected and
the visual approach controller moved the character toward the wildlife area.
The measured live transport remained near the intended rate (roughly 39–41 Hz
source/publish and 28–31 Hz main control).

The screenshot and matching status exposed a separate state-lifetime defect.
After player movement invalidated the porcupine's old screen-space mouseover
anchor, the world model also lost the independent semantic fact that this exact
GUID belonged to quest 55174. Because a different goat was currently under the
cursor while a live porcupine remained selected, the planner correctly refused
to switch targets, but could no longer justify combat against the selected
porcupine; the generic quest-location MOVE proposal therefore won.

Correction: confirmed tooltip semantics are now cached independently from
screen coordinates for the exact unit GUID and active, incomplete quest. The
screen anchor still expires immediately after material player/camera movement;
only `quest_related` and `quest_id` survive, for at most 120 seconds and only
while that quest remains active. The selected target is enriched from that
identity fact, so the combat planner can recover after a commitment release
without clicking an obsolete pixel. Completing or removing the quest retires
the semantic fact.

The same live session also confirmed the earlier no-path failure: Charge could
be reported in range while the client returned `No path available`. The combat
controller now rejects that binding for the recovery step and asks visual
approach to reposition before retrying. Debug telemetry/event files are now
rotating and bounded; the prior large evidence files are preserved unchanged.

Validation status: **MOUSEOVER QUEST MATCHING AND INITIAL TARGET/APPROACH
LIVE-VALIDATED; SEMANTIC-PERSISTENCE AND NO-PATH RECOVERY OFFLINE-TESTED, LIVE
PENDING.** Full regression after the semantic fix is 677 passed, 6 skipped.
The user invoked F12 during the run; the agent and debugger were closed with a
final STOPPED state and no held keys. Do not re-arm until the user explicitly
starts the next live attempt. A new run must still validate kill, loot receipt,
quest progress, and absence of repeated corpse interaction end to end.

### 2026-09-16 — first live kill/loot and exact-client binding correction

The authorized PID 14960 FULL_AI run selected and killed a `Coastal Goat` for
quest 55174. The user verified the authoritative visible quest counter reached
1/5, so the first kill and loot ultimately completed. The last captured full
telemetry before shutdown still showed 0/5; this is recorded as delayed capture,
not as evidence that the user's visible 1/5 result did not occur. Inventory
telemetry showed three free slots, so a full bag was not the cause.

Two independent defects were exposed. First, a LOOT attempt could be declared
successful about 140 ms after it began because its baseline was the compact
FAST packet while verification used the merged full world state. Pre-existing
inventory entries therefore looked new. Attempt baselines now deep-copy the
merged world state, and regression coverage proves a compact FAST packet cannot
create a false inventory delta. Second, unchanged but freshly received packets
share a content-addressed observation ID; verification no longer calls this a
telemetry stall when `last_received` advanced and the world is fresh. The latter
fix was live-validated: inspection correctly returned
`expected_observation_missing` with valid zero-information quality while source
FAST remained roughly 40–41 Hz.

Exact-PID addon evidence also proved the selected cache had drifted from the
client: the live client used Q/E for turn and A/D for strafe, while the cache
used A/D for turn and Q/E for strafe. That made repeated TURNLEFT commands
ineffective. The selected cache was corrected directly from the exact PID's
addon export; its pre-change copy is
`bindings-cache-pid-19664-de831c78eb53.pre-live-sync-20260916.wtf` with SHA-256
`D1A4A920EC381AF001CAA32DE13797513FC89634FC8D9C4C913D24FC5D5E8AB1`.
The corrected cache SHA-256 is
`B9D5E6E7983B7E05DDBEA1CFC312542598016C9566D6F66D1313CF5DABC19016`.

The runtime now compares every required binding against exact-client control,
actionbar, and paged catalog evidence before arming. It waits passively for
unseen pages, rejects a known mismatch at start, and returns to MANUAL with all
keys released if drift appears during FULL_AI. Validation status: **FIRST
KILL/LOOT USER-VALIDATED AT 1/5; PREMATURE-LOOT AND BINDING-DRIFT FIXES
OFFLINE-TESTED, LIVE RETEST PENDING.** Full regression is 684 passed, 6 skipped.
The next run begins only after the user imports the corrected cache and should
prove effective Q/E turning plus a second real loot transition to 2/5.

### 2026-09-16 — M0/M1 ownership and gossip transition follow-up (offline)

The duplicate generic `QUEST_DIALOG` command/verifier path was removed from
the runtime route.  Dialog actions now execute only through `QuestDialogSkill`.
Addon-exported `AVAILABLE` and `COMPLETE` gossip rows are treated as an
explicit `GOSSIP_SELECT` step, not as an inferred Accept click: the next
telemetry state must show a named action for the same quest before the agent can
click an Accept/Complete/Turn-in control.  Rewards and unsupported gossip are
still fail-closed.

The launcher batch files no longer force PID 14960, a stale cross-drive cache,
or `--auto-full-ai`.  They start the GUI in MANUAL with the read-only debugger;
the user must choose the live PID and fresh matching bindings cache before any
FULL_AI request.  This is a safety/configuration correction, not a live test.

Offline evidence: focused dialog/agent regression 104 passed; complete Python
regression 755 passed, 3 skipped; import and launcher argument smoke passed.
No WoW client, addon installation, input, or FULL_AI run occurred during this
follow-up.  The next user-operated acceptance should validate this concrete
chain: gossip row -> same-quest detail action -> accept -> active quest update,
then retain the existing target/combat/loot validation requirements.

If an NPC exposes multiple distinct offered quest IDs, `QuestOfferSelector`
now blocks rather than choosing by list order.  A goal with `quest_id` or
`primary_quest_id` selects that exact row; a single offered ID remains
unambiguous.  This addition is offline-tested only.

### 2026-09-16 — Addon 0.9.22/0.9.23 reward and campaign telemetry (offline)

The paired Retail 12.1.0 addon packages now export up to eight reward rows,
including their item id, UI coordinate, and selected state.  An unresolved
choice is represented as `REWARD_SELECT`, rather than being silently treated
as a `COMPLETE` click.  The controller's `QuestRewardSelector` will click only
an exact `reward_item_id` or `reward_choice_index`; `FIRST_UNAMBIGUOUS` is
available only when there is exactly one valid exported row.  Missing layout
coordinates, duplicate requested items, and unspecified/ambiguous choices
remain in `WAIT` with no UI input.

Offline regression: **765 passed, 3 skipped**, including Lua mock loading of
the addon and reward selector/skill/planner tests.  The addon has not been
installed or reloaded and no live action was performed in this follow-up.  A
future user-operated run must confirm one actual reward layout before this is
promoted beyond `ADAPTER_OFFLINE`.

The 0.9.23 follow-up also exports `C_QuestLog.IsCampaignQuest` when the Retail
API supplies it. `NextQuestResolver` can continue an explicit `MAIN_CAMPAIGN`
goal only if exactly one current active quest has that flag. The path has unit
coverage but has not been installed, reloaded, or validated in a live client.

### 2026-09-17 — User-operated Jaina approach / dialog-boundary run

Live evidence from the selected Retail client (`pid-17712`) confirms the
approach portion of the first Exile's Reach quest flow:

`World3D identification -> TARGET -> INTERACT -> VISUAL_APPROACH -> quest UI opened`.

The addon exported the precise first-offer action during the run:
`ACCEPT`, quest id `55122`, normalized button point
`(0.035912220595098, 0.4325391074527)`.  The agent correctly stopped movement
once the dialog opened.  Acceptance was **not** live-validated: the GUI's
`30 mp próba` deadline changed the runtime to MANUAL at the dialog boundary,
before a `QUEST_DIALOG` action could be planned and verified.

The bounded multi-action trial now grants one 5-second close-out window only
when its last fresh addon payload contains an open, exact, click-addressable
quest action.  That window may execute and verify one `QUEST_DIALOG` action,
then returns to MANUAL.  A missing/zero coordinate, unknown action, one-step
test, or expired close-out window remains fail-closed.  Offline regression for
this correction: **125 passed** (`test_agent_runtime`, `test_agent_core`, and
`test_autonomous_commitment_loop`).  A new user-operated run is required to
validate `ACCEPT -> QUEST_ACCEPTED/active quest` live.

### 2026-09-17 — Jaina dialog-preemption defect isolated (offline fix; live retest pending)

The subsequent user-operated Jaina runs reproduced a distinct defect after the
quest frame became visible. The durable action trace showed both
`VISUAL_APPROACH` and exact addon-exported `QUEST_DIALOG(ACCEPT, 55122)` in
the same candidate set. Generic target-commitment ranking selected
`VISUAL_APPROACH` (priority 102) over `QUEST_DIALOG` (priority 90), then
restarted the already-successful approach repeatedly. This is why the agent
could interact with Lady Jaina, report `interaction_ui_opened_during_approach`,
and nevertheless remain in `VISUAL_APPROACH`/`WAIT` without accepting.

The runtime now treats an open, exact, click-addressable `QUEST_DIALOG` as a
short UI transaction that preempts navigation after safety interrupts. The
planner also requires current `quest_ui.open` evidence before creating an
Accept/Complete/Continue/Turn-in candidate; a historic `QUEST_DETAIL` event
alone is no longer UI truth. The brain scheduler treats arrival of the action,
quest id, or normalized button point as an immediate world event, rather than
waiting for its regular cadence. Focused regression covers the exact
`TARGET commitment + VISUAL_APPROACH + ACCEPT` collision; 160 related tests
passed. This is **offline-tested only** until the user runs the next live
acceptance test with the updated controller and the current addon package.

### 2026-09-17 — Canonical World3D local-world batch (offline; live vision validation pending)

The current World3D V2 detector, V3 CPU patch tracker and V4 evidence fusion
are now published through one perception-only `World3DObservationBatch`. The
batch includes explicit coordinate spaces, track lifecycle/occlusion, global
camera and ego-motion evidence, screen bearing, scale-only distance belief,
local traversability sectors, obstacle/entrance/landmark candidates,
interaction-ready evidence and negative local-scan evidence. It is a separate
`WORLD3D_LOCAL_VIEW` projection in the WorldModel; it does not alter movement,
input, combat or planner ownership.

Focused offline regression: **55 passed** (World3D pipeline, ROI, V3/V4,
temporal tracks, perception, runtime, WorldModel). A full suite was started;
it reached 70% without a reported failure before the bounded command window
ended, so it is not recorded as a completed full regression. No WoW client,
addon installation or input was used.

Next user-operated live validation: with the client stationary and an NPC in
view, capture the debug output for a camera sweep, then a short approach and a
temporary occlusion. Inspect `world3d_batch` for stable track id, bearing,
scale trend, occlusion lifecycle, and local geometry evidence before enabling
any autonomous quest test.

### 2026-09-17 — Murloc World3D observation run (partial live evidence)

The selected Retail client captured the Murloc scene successfully at 980×612
DXGI client pixels. World3D remained `ready`, produced 10–20 current visual
proposals, and its global patch-flow emitted non-zero camera translation during
the user-operated camera sweep. The local batch was also confirmed in the
agent observation store as `WORLD3D_LOCAL_VIEW` (for example
`frame_id=world3d:2:294`), including explicit ROI/bearing/scale/traversability
payloads. No input was sent by the assistant.

This did **not** validate nameplate-to-body association: the displayed selected
target information was not sufficient proof that a visually separate label
belonged to the central Murloc. The run exposed a track-authority defect:
V3-associated candidates were unnecessarily reassociated by the presentation
tracker, and stale `LOST_TEMPORARY` tracks accumulated in the batch. The code
now preserves the V3 upstream track id and expires absent tracks after a small
observation quorum plus wall-clock grace. Offline regression after that fix:
**57 passed**. A repeat Murloc camera-sweep/short-occlusion test is required
before track continuity is marked live-validated.

### 2026-09-17 — Murloc repeat observation / proposal deduplication (offline fix; live retest pending)

The repeat run showed a different Murloc, so it is valid only as another
generic-subject tracking observation and **not** as entity re-identification
evidence. The visible central Murloc held a stable `WORLD3D:317` UNKNOWN
subject track, but the generic multi-scale sliding-window detector emitted
several overlapping, vertically offset attention regions over the same body.

The detector now suppresses only geometrically aligned, substantially
vertically overlapping generic subject windows and reduces its generic proposal
budget from eight to six. Adjacent side-by-side subject windows are explicitly
retained. This is proposal-level noise reduction only: it creates no semantic
NPC/MOB/quest fact and changes no movement, combat, planner or input code.
Focused regression after the correction: **64 passed**. A new user-operated
Murloc observation is required to verify that the live batch has one primary
subject track per visible body rather than several competing fragments.

### 2026-09-17 — Murloc proposal-deduplication retest (partial live validation)

The selected Retail client completed a new user-operated observation run
(`live-debug-20260917-040829.jsonl`). In the final World3D local batch, the
visible central Murloc region produced one primary active generic-subject track
instead of the prior stack of overlapping, vertically offset fragments. Six
active subject tracks remained in distinct horizontal screen regions, which is
expected because they are separate UNKNOWN attention regions in the scene; no
CV identity or role was inferred from them. The run therefore validates the
proposal-level duplicate suppression, but it does not validate entity identity,
nameplate-to-body association, targeting, combat, or movement.

The screen source remained healthy (about 55–57 captured frames/sec), while
the expensive detector refreshed at roughly 1.6–3.2 Hz and the controller loop
ran around 5–7 Hz in this capture. Those performance observations remain open
for the later World3D throughput gate; no input was sent in this validation.

### 2026-09-17 — Dense unselected Murloc scene (live observation; probe follow-up offline)

A user-operated run deliberately showed many Murlocs with no selected target.
The final canonical batch contained eight active UNKNOWN subject tracks and
two supported generic `ABOVE` scene-graph relations. This confirms the agent
did not rely on selected-target telemetry or merge the whole crowd into one
entity. It remains insufficient to claim exact body/nameplate correspondence:
several visible bodies still have weak foreground segmentation.

The detector now converts a robust horizontal overhead/nameplate-like cue with
no segmented body below it into a bounded `unknown_subject_probe`. It is an
UNKNOWN active-perception region only, with no NPC/MOB/hostile/quest semantic
claim. This lets a later mouseover or a stronger frame attach identity instead
of losing a visually important crowded-scene cue. Focused regression: **72
passed**. Live validation of the newly published probe is pending the next
user-operated run.

### 2026-09-17 — Dense unselected Murloc probe retest (partial live validation)

The new user-operated run (`live-debug-20260917-041648.jsonl`) showed several
visible, unselected Murlocs. The new bounded overhead-cue probes were emitted
and temporally stable: `WORLD3D:21` and `WORLD3D:22` remained `ACTIVE` through
all twelve sampled local-world batches, with two additional probes appearing
as the camera/scene changed. A stronger subject candidate also carried the
existing `subject_below_symbol_probe` relation cue.

This validates the probe publication and temporal continuity in a crowded,
unselected scene. It does not validate identity, Murloc classification,
mouseover association, targeting, combat, or movement; all probe semantics
remain `UNKNOWN` until independent ground truth is supplied.

### 2026-09-17 — Manual mouseover identity-association run (partial live validation)

The user manually hovered every visible Murloc without selecting a target.
The addon exported five distinct authoritative creature GUIDs: two `Murloc
Spearhunter` instances (NPC id `150228`) and three `Murloc Watershaper`
instances (NPC id `150229`). For each identity, the WorldModel recorded at
least one explicit `track -> MOUSEOVER_OF -> entity` relation. The spatial
association confidence ranged from about `0.56` to `0.93`; identity itself
remains addon ground truth, while the track link is `SUPPORTED` spatial
evidence.

This validates the UNKNOWN track/probe -> mouseover -> entity association path
in an unselected crowded scene. A single entity was associated with more than
one short-lived visual track as the detector refreshed, so stable long-horizon
visual re-identification remains an open refinement. No autonomous targeting,
movement, combat, or input was used.

### 2026-09-17 — Upstream visual-track restart handling (offline fix; live retest pending)

The manual mouseover run exposed that one confirmed creature could receive
several short-lived presentation track IDs when V3 restarted an upstream ID at
a detector refresh. The source-local World3D tracker now treats a changed V3
ID as a possible continuation only when the new UNKNOWN subject is close and
appearance-compatible. The original and replacement V3 IDs are retained as a
bounded alias chain and published in the canonical batch for audit. Exact
upstream IDs remain preferred; distant subjects are explicitly not merged.

Focused regression: **66 passed**, including nearby restart preservation and
distant-subject non-merge cases. Live validation is pending a repeated hover
run over one stationary, unselected Murloc across several detector refreshes.

### 2026-09-17 — Passive World3D visual-memory learning from exact mouseover (offline fix; live retest pending)

The hover trace showed that the same confirmed Murloc can expose different
body-region tracks concurrently; this is not necessarily an upstream restart.
The missing layer was visual-memory training: manual mouseovers previously
recorded a WorldModel relation but did not feed the exact signed World3D crop
into `EntityMemory` when identity arrived on the fast telemetry lane.

The runtime now accepts a passive label only when one fresh cursor sample, one
fresh addon mouseover GUID, and one signed UNKNOWN World3D subject coincide
within a tight screen-space threshold. It then performs `learn_only` spatial
memory ingestion; no planner, map lookup, target, movement, combat, or input
path runs. Focused regression: **81 passed**, including positive exact-match,
stale/far rejection, and fast-lane no-map-work coverage. A fresh manual hover
run is needed to confirm `ENTITY_MEMORY` recognition candidates live.

### 2026-09-17 — Passive visual-memory hover retest (partial live validation)

The user manually hovered two additional unselected Murlocs. Both fresh
cursor/GUID-aligned World3D crops were persisted under addon-confirmed
`npc:150228` (`Murloc Spearhunter`) in `entity_memory.sqlite3`; no visual
identity was fabricated by CV. The stored examples differ materially in scale
and shape, so the original per-signature three-repeat rule was too rigid for
the live data.

`EntityMemory` now retains the established single-template rule, while a
separate multi-example route may emit only a `CANDIDATE` when an identity has
at least two independently exact mouseover labels and a new crop strongly
matches one of those views. Older supported templates no longer suppress that
new candidate. Direct replay of the newly persisted live Spearhunter crop
returns `npc:150228` through
`MULTI_EXAMPLE_VISUAL_REIDENTIFICATION` with five independently stored
appearances and similarity `1.0`. This is recognition evidence only: it does
not establish a GUID, role, hostility, target, movement, or input action.

Focused regression after the change: **89 passed**. Live retest of candidate
publication from a newly captured frame remains pending the next
user-operated run.

### 2026-09-17 — Visual-memory candidate publication and precision correction

The follow-up single-Murloc live run published the desired detached visual
candidate after the user moved the cursor away: `WORLD3D:50` produced
`npc:150228` through `MULTI_EXAMPLE_VISUAL_REIDENTIFICATION` at `0.9447`,
with five independently stored labelled views. This validates the passive
hover -> learned appearance -> later visual-candidate path.

The same observation also exposed unacceptable lower-quality alternatives
(`0.72`–`0.86`) for unrelated previously labelled identities. Multi-view
identity suggestions now require similarity at least `0.90`; this leaves the
observed Spearhunter hit eligible but suppresses broad colour/shape
resemblance. The correction remains perception-only and cannot issue input.
Focused regression: **90 passed**. A final user-operated precision retest is
pending after agent restart.

### 2026-09-17 — Adjacent-Murloc isolation check (partial live validation)

The user showed two adjacent, unselected Murlocs and hovered only one. The
hovered subject (`WORLD3D:8`) retained the high-quality Spearhunter candidate
after cursor removal (`0.91`–`0.97`). The adjacent subject did not acquire
that Spearhunter candidate. This is the desired track-local behavior.

The trace did reveal that the runtime was still publishing older, low-quality
single-template approximate candidates (`0.72`–`0.86`) even though the
multi-view path was already strict. Runtime publication now filters both
approximate and multi-view re-identification below `0.90`; broad memory search
remains available internally but cannot become a WorldModel visual-evidence
candidate. No target, movement, combat, planner, or input path changed.
Focused regression: **91 passed**. A restart and one final adjacent-Murloc
precision retest are pending.

### 2026-09-17 — Selected-then-hovered adjacent Murlocs (live observation; temporal gate added)

The final adjacent-Murloc run briefly selected the first Murloc, then hovered
the second. Selection was present in exactly one telemetry sample and did not
participate in passive visual learning. The two mouseover GUIDs were distinct
creatures, both addon-confirmed `Murloc Spearhunter` (`npc:150228`), so their
visual examples correctly reinforce the same NPC-type memory rather than a
single instance GUID.

After cursor removal, the correct `npc:150228` result appeared repeatedly on
the relevant temporal track, but a different identity surfaced for one frame.
This is now handled by a track-local temporal evidence gate: a visual identity
is published only after repeated high-precision support on that exact track;
a one-frame alternative remains internal diagnostic data. It is passive
perception only and has no input or planning authority. Focused regression:
**92 passed**. Live retest after restart is pending.

### 2026-09-17 — Track-local temporal gate retest (partial live validation)

The rerun showed the intended behavior for the learned Spearhunter: only after
three or more repeated high-precision frames did `npc:150228` publish on a
World3D track. The prior one-frame Watershaper alternative did not publish.
The trace also contained old fallback `unknown:Player-*` identity keys from
historical mouseovers. They lack a complete current entity identity, so they
are now retained for diagnostics only and excluded from live visual-recognition
evidence. Focused regression remains **92 passed**. One restart/retest is
needed to confirm the final filter in the live process.

### 2026-09-17 — World3D visual-memory precision gate (live validated)

The restart retest published only three stable World3D track/identity pairs in
the final 50-second observation window. All were `npc:150228` Spearhunter
multi-example candidates, with similarity `0.9447`–`0.9724` and at least three
temporal support frames. No `unknown:*` identity and no sub-`0.90` alternative
was published. This validates the passive mouseover-label -> visual-memory ->
track-local temporal evidence pipeline for this adjacent-Murloc scene.

The gate remains limited to candidate evidence; it does not validate GUID
re-identification, role/hostility inference, target selection, movement,
combat, or autonomous input.

### 2026-09-17 — Active-perception ranking refinement (offline-tested; live pending)

Stable, high-precision visual-memory candidates now contribute two bounded
World3D inspection-ranking features: (1) temporal visual-memory strength and
(2) screen-space interaction readiness derived only from visible track scale.
Both are appearance/evidence terms; the track remains `UNKNOWN`, no world
coordinate is inferred, and mouseover telemetry remains the only identity
ground truth. The change touches neither target selection nor movement/input.

Focused regression: **103 passed**, including a test that a close, temporally
supported memory candidate outranks an otherwise equivalent plain UNKNOWN
track while retaining `semantic_type=UNKNOWN`. Live validation pending.

### 2026-09-17 — Manual active-perception ranking projection (offline-tested; live pending)

The first MANUAL run after the ranking refinement correctly produced passive
World3D and EntityMemory observations, but MANUAL mode intentionally does not
invoke Planner proposal selection. It therefore could not by itself prove the
future `INSPECT` ordering. A read-only `ACTIVE_PERCEPTION` projection now
publishes the ordered top World3D attention tracks directly into the WorldModel
as `active_perception_ranking`. Each row explicitly declares
`semantic_type=UNKNOWN` and `action_authority=NONE`; it is not a proposal and
cannot target, move, interact, or input.

Focused regression: **104 passed**, including a MANUAL-safe ranking case where
a temporally supported, close visual-memory candidate outranks an otherwise
equivalent plain UNKNOWN subject without becoming a fact. A restarted MANUAL
retest is pending.

### 2026-09-17 — Active-perception live-ranking calibration (offline correction; live pending)

The first ranking-projection run confirmed that the learned candidate was
present (`WORLD3D:6`, `npc:150229`, similarity `0.9171`) but placed third. The
trace showed why: the old novelty term subtracted more information value for a
remembered track than the memory term restored. This was a scoring error, not
a detection or identity failure.

The temporal memory-probe weight now reflects the value of obtaining a fresh
mouseover for a close, supported UNKNOWN track. It can outrank a generic
overhead cue when the visual-memory support is strong; neither candidate gains
semantic meaning or action authority. Focused regression: **105 passed**,
including this exact ordering case. A restarted MANUAL ranking retest is
pending.

### 2026-09-17 — Active-perception live-ranking second calibration

The retest showed the stable visual-memory candidate in the read-only ranking
with strength `0.9171`, but its expected gain was `0.5138` versus `0.5424` for
the strongest generic supported-overhead cue. The memory channel was therefore
working but still underweighted. The bounded memory-probe coefficient was
raised again so a high-precision, 3+ frame candidate has a clear margin over
that generic cue in the same measured scenario. Focused regression remains
**105 passed**. One final restarted MANUAL ranking retest is pending.

### 2026-09-17 — Generic-overhead specificity calibration (offline-tested; live pending)

The final passive-ranking retest showed that the high-quality `npc:150229`
visual-memory candidate was first in several frames, but generic tracks with a
`SUPPORTED` `ABOVE` relation could still win in other frames. The issue was not
memory confidence: a generic overhead fragment received the same full overhead
contribution as a visually specific quest-badge-like cue.

`ActivePerception` now records `overhead_specificity` separately from the
existence of an overhead relation. A generic supported relation contributes a
bounded value (`0.70`); a supported cue with badge-like appearance evidence or
an explicit `quest_badge_like`/`quest_marker_like` visual label retains full
value (`1.0`). This changes only passive UNKNOWN-track inspection ranking: it
makes no semantic assertion, planner decision, movement, target, or input
change.

Focused regression: **106 passed**, including the specific case that a
badge-like overhead cue retains priority over a generic overhead relation. A
restarted MANUAL live-ranking retest is pending.

### 2026-09-17 — World3D detector-gap identity retention (offline-tested; live pending)

The subsequent live run showed the calibrated ranking working while the
learned track existed: `WORLD3D:6` was first for three consecutive frames
with visual-memory strength `0.945`–`0.972`, ahead of the generic supported
nameplate/overhead track. Later the learned upstream V3 detector identity was
retired after three detector-refresh misses, so the upper temporal layer had
no stable identity to rank; this was a tracking-lifecycle issue, not an
attention-weighting issue.

The V3 detector tracker now preserves UNKNOWN identities for eight missing
detector refreshes. They remain absent/non-inspectable while not visible, but
a nearby reappearance can retain the same upstream identity and therefore
restore temporal and visual-memory continuity. The change creates no entity
fact and changes no planner, movement, targeting, or input behavior.

Focused World3D/attention/memory regression: **96 passed**, including a
five-refresh UNKNOWN-subject detector-gap reacquisition test. A restarted
MANUAL live retest is pending.

### 2026-09-17 — World3D detector-gap retention live result (MANUAL/passive validated)

The restarted MANUAL test validated the intended passive behavior. The
reacquired `WORLD3D:18` UNKNOWN track reached 29 frames of temporal support,
matched `npc:150229` through visual memory at similarity `0.9171`, and ranked
first (`0.4333`) ahead of generic supported nameplate/overhead tracks
(`0.3896` and `0.3867`). Later frames contained no currently visible
memory-associated candidate, so the ranking correctly contained only generic
UNKNOWN candidates rather than falsely retaining or inspecting the missing
track.

This validates tracking continuity and passive attention ordering only. It
does not validate target selection, mouseover execution, movement, or
interaction.

### 2026-09-17 — Canonical World3D INSPECT selection (offline-tested; live pending)

The existing `INSPECT` skill, hover command, and addon mouseover verification
remain the only execution path. The Planner previously used a separate,
hard-coded supported-overhead priority for its World3D `INSPECT` proposals,
which could contradict the now-validated passive attention ranking.

Planner selection now derives World3D `INSPECT` order from the same canonical
UNKNOWN-only `ActivePerception.rank_world3d()` projection. A proposal records
its `attention_rank` and `PLANNER_INSPECT_SELECTION` authority for traceability.
The ranking itself is still not an identity fact: the actual hover must yield
fresh addon mouseover/tooltip evidence before any entity association can occur.

Focused planner/World3D/attention regression: **117 passed**, including the
measured case where a stable visual-memory UNKNOWN track is selected before a
generic supported-nameplate/overhead cue. MANUAL passive validation is
complete; controlled live INSPECT validation is pending.

### 2026-09-17 — Controlled World3D INSPECT loop (live validated)

One bounded GUI test step executed exactly one `INSPECT` action. The Planner
selected `WORLD3D:48` with `attention_rank=1` from the canonical attention
projection (memory recognition `0.9171`, temporal support 7), issued one
hover at the track centre, and received fresh addon-ground-truth mouseover
evidence 0.74 seconds later:

- `Murloc Watershaper`
- `npc_id=150229`
- `is_attackable=true`

The inspection verifier recorded `hover_quality=1.0`, `at_probe=true`, and
`expected_observation_verified`, then returned to MANUAL. No target click,
movement, or combat command occurred. This live-validates the bounded
`rank → hover → fresh mouseover identity` loop. Target selection and combat
remain separate, unvalidated next stages.

### 2026-09-17 — Questgiver cue-selection failure and correction (live observed; offline-tested)

The bounded questgiver run in session `pid-17712`, capture segment
`20260917-094445-259-004`, was not a successful questgiver inspection. Jaina
and a visible yellow badge were present in the captured frame, and the
World3D pipeline produced the corresponding UNKNOWN subject-probe track.
However, two unrelated generic foreground tracks were selected for `INSPECT`
first (priorities 84/83). The badge-derived probe entered `SEEK_VISUAL_CUE`
only afterwards, lost its visual track during the resulting movement/camera
change, and no fresh mouseover identity was obtained.

The correction remains non-semantic: a stable `quest_badge_like` UNKNOWN
subject probe is now the first bounded `SEEK_VISUAL_CUE` candidate for a
QUEST goal, and unrelated World3D hover proposals are held back while that
identification attempt owns the subgoal. It does not create a `QUEST_GIVER`
fact; only a later mouseover/addon response may do so. Focused regression:
**172 passed**. A new user-run live test is required to validate
`badge cue → seek → fresh hover → TARGET`.

### 2026-09-17 — Hover-to-target pointer handoff correction (live observed; offline-tested)

The subsequent session proved the cue priority correction: `SEEK_VISUAL_CUE`
selected the badge-derived track first and obtained the fresh Jaina GUID
(`identity_available_during_visual_seek`). The following TARGET attempts still
ended in `target_not_found`. The captured tooltip confirmed that the physical
cursor was already hovering Jaina at handoff, while TARGET re-issued a cursor
move using independently scaled addon UI coordinates before clicking.

Ground-truth TARGET handoffs now emit `CLICK_CURRENT_CURSOR`: after the
fresh, co-sampled hover safety gate passes, the executor sends only the left
click and does not move the pointer. Ordinary TARGET, loot, object-use, and
dialog clicks retain their explicit coordinate paths. Focused regression:
**196 passed**. Live validation pending: `SEEK_VISUAL_CUE → Jaina mouseover →
TARGET current-pointer click → selected target`.

### 2026-09-17 — Jaina interaction approach overshoot guard (live observed; offline-tested)

The next bounded Jaina test live-validated the pointer-handoff correction:
the captured target frame and tooltip both showed `Lady Jaina Proudmoore` as
the selected target. The client then reported `You need to be closer to
interact with that target`, which is valid range evidence. The subsequent
visual approach was not safe: it sent repeated forward refreshes against the
same one-time mouseover-associated `WORLD3D:35` track. Its apparent scale
then collapsed from `0.1046` to about `0.04` while the player continued to
move, and Jaina left the view; the attempt ended `visual_track_lost` and the
planner returned to unrelated inspection.

The interaction servo now treats a single mouseover-to-track association as
re-checkable evidence, not permanent identity. For an `INTERACT` approach
whose screen anchor is `CONFIRMED_MOUSEOVER_ANCHOR` with
`track_association=CANDIDATE`, it advances only a bounded short segment,
then issues a coordinate hover over the current visual track and releases its
movement lease. It resumes only after a newer addon mouseover sample confirms
the same committed GUID. A different GUID or no response after the bounded
addon-latency window stops the approach as
`visual_track_lost_identity_reconfirmation_missing`; target commitment is
retained for controlled reacquisition rather than being replaced by random
`INSPECT`. This adds no CV-derived identity and makes no addon change.

Focused regression: **196 passed**, including fresh-hover continuation and
missing-reconfirmation stop tests. A user-run live test is pending:
`TARGET selected → range error → short advance → re-hover Jaina → continue
or safely stop`, with screenshots and the interaction journal retained.

### 2026-09-17 — Re-hover guard live result and selected-target reacquisition (live observed; offline-tested)

The restarted test in capture segment
`pid-17712/live-captures/20260917-100700-840-002` confirms the first half of
the guard in live gameplay. Jaina remained visibly selected in the captures;
the controller issued two bounded `HOVER` checks during the interaction
approach, and both received fresh matching Jaina GUID evidence
(`identity_rechecks=2`, `identity_reconfirmations=2`). It therefore did not
blindly drive from one unverified World3D candidate. The screenshots also
show the friendly target frame throughout this sequence.

Immediately after the second successful check, the generic World3D projection
temporarily disappeared even though Jaina was still visually on screen. The
old OCCLUDED path sent only `INTERACTTARGET` and then failed as target-lost;
it had no perception action capable of restoring the missing track. The
controller now re-hovers the last freshly GUID-confirmed screen point while
stationary before an OCCLUDED interaction probe. A fresh match lets the
WorldModel bind a new/current candidate again; a mismatch or timeout stops
without any blind forward movement. The selected target GUID remains the
authority and no click is emitted by this recovery.

Focused regression: **197 passed**. The next bounded live attempt should
verify `re-hover → temporary track gap → re-hover same point → restored
approach/interact`, rather than the former `INTERACTTARGET`-only loop.

### 2026-09-17 — Visual re-hover executor-route defect (live observed; offline-tested)

The immediately following live run entered MANUAL because of an executor
defect, not because the selected target was unsafe. The journal records the
exact error: `Érvénytelen movement lease` while a `VISUAL_APPROACH` emitted a
`HOVER` command. The nested INTERACT-owned visual-approach route already sent
HOVER through the ordinary mouse executor, but the top-level
`VISUAL_APPROACH` route incorrectly sent it to `execute_movement`, which
accepts only movement bindings. This was reached after the interaction
failure/replan path, hence the automatic MANUAL safety stop.

All three visual-approach dispatch routes now classify `HOVER` with
`INTERACTTARGET` as a normal non-movement input. The outer route also releases
any held movement lease before sending that hover. Focused regression remains
**197 passed**. A restarted user-operated test is required to prove this
specific executor route live; no addon change is needed.

### 2026-09-17 — Far-start quest-cue handoff defect (live observed; offline-tested)

In user-run capture segment
`pid-17712/live-captures/20260917-101549-428-002`, Lady Jaina and her yellow
overhead cue are visible throughout the recorded frames. The runtime also
selected `SEEK_VISUAL_CUE` before map fallback. This establishes that the
far-start failure was not an absence of a World3D candidate.

The defect was at the next boundary: once the visual servo reached its
apparent-scale readiness threshold, it returned successful
`visual_cue_ready_for_identification` immediately. That success released the
committed cue without first moving the pointer onto it, so the generic planner
then cycled unrelated `INSPECT` candidates rather than obtaining Jaina's
addon mouseover identity.

`SEEK_VISUAL_CUE` now holds the exact UNKNOWN cue at this boundary, issues a
normal-executor `HOVER` over that cue/probe, and waits for a newer addon
mouseover sample. A non-player GUID confirms identity; no expected GUID or CV
semantic label is required. If the addon produces no response within its
bounded 0.85-second window, the skill explicitly hands off as
`visual_cue_hovered_for_identification` rather than claiming recognition.
The SEEK executor route now also sends `HOVER` via the ordinary input executor
after releasing movement, preventing an invalid movement lease. Focused
regression: **163 passed**. Live validation pending: distant Jaina → seek →
cue hover → Jaina mouseover GUID → TARGET.

### 2026-09-17 — Distant quest-giver vertical slice (live observed; partially validated)

The longer user-run segment
`pid-17712/live-captures/20260917-144843-361-002` live-validates the new
distant-cue handoff. With Jaina visible at range, the agent performed the
new cue-specific HOVER at normalized `(0.4898, 0.6405)`, received fresh addon
identity, selected `TARGET`, and the client selected Lady Jaina Proudmoore.
It initially received the correct authoritative out-of-range message, then
the quest-dialog path opened and the capture shows **Quest accepted: Murloc
Mania**. The active quest and minimap became visible afterwards.

The same segment then used its location/navigation path to reach the Murloc
area, acquired an enemy, dispatched the Warrior rotation, and recorded one
`target_death_verified` combat success. This is useful M0 live evidence, but
not completion: there is no verified loot receipt or quest-item inventory
delta, and the subsequent combat attempt failed `IDENTITY_UNCERTAIN` after
the selected target/identity stream ceased being authoritative. The next fix
and validation focus is committed combat target continuity followed by corpse
loot verification; the quest-giver far-start handoff itself is now live
validated.

### 2026-09-17 — Objective-area inspection budget (offline-tested)

Review of the same Murloc Mania run found excessive generic World3D `INSPECT`
work after reaching the active objective area. The first high-information
hover is retained, but once that bounded probe has been used, active quest
search now suppresses additional generic World3D inspections and map opening.
It starts one persistent `SEEK_VISUAL_CUE` with
`SEARCH_LOCAL_OBJECTIVE_AREA`, which owns four systematic camera sectors.
Only its normal exhausted result unlocks map fallback. This preserves
UNKNOWN-first detection, does not semantically label any Murloc, and prevents
the prior inspect sweep from starving local search. Regression: **131
passed** across map discovery, seek, core-agent, and persistent movement
coverage. Live validation pending.

### 2026-09-17 — False recovery and combat wait diagnosis (offline-tested)

The user-run capture `output/live-debug/live-debug-20260917-145855.jsonl`
showed three separate faults, rather than a real movement obstruction:

1. FULL_AI was switched back on after a long MANUAL interval.  The global
   stationary watchdog retained its old timestamp, so it immediately proposed
   `RECOVER` even though the new run had not commanded movement yet.
2. The addon FAST lane was still delivering target/actionbar/control data, but
   the independently paged detail snapshot aged.  The old liveness gate
   treated that detail age as a telemetry loss and changed to MANUAL while
   packets were still arriving.
3. The same detail-age restriction marked `COMBAT` unavailable even when the
   current FAST target and actionbar confirmed a castable in-range ability.
   The committed target then had no eligible skill and correctly surfaced as
   `WAIT`; this was a bad admission gate, not a reason to wait in combat.

The control-freshness contract now uses recent packet receipt plus explicit
`player_present`; paged detail age remains diagnostic/provenance only. COMBAT
and DEFEND are admitted from their current fast target/actionbar inputs, and
every transition into FULL_AI resets the stationary-watchdog baseline. The
patch is offline-tested by focused core, target-approach, movement, and map
discovery coverage: **149 passed**. A user-operated live combat run is still
needed to validate the new path; no addon installation is required.
# 2026-09-21 — map 2175 TrinityCore mmap integration (offline only)

The user supplied `C:\Users\benei\Downloads\mmaps.zip` and identified Exile's
Reach as instance/map 2175. The archive and real `2175_32_36.mmtile` data were
parsed offline; same-tile and land-only cross-tile polygon routes were
produced. Water polygons are excluded from walking routes. The
route source is now composed by the canonical `NavigationService` only for
same-instance, addon-confirmed `WORLD_YARDS` endpoints. No client was driven
during this integration.

Live status remains **OPEN**. Required selected-PID proof:

1. GUI reports `navigation.navmesh.reason = route_found` for a 2175 reach;
2. emitted intermediate waypoints are followed in order without a second
   movement authority;
3. local World3D obstruction still overrides/bypasses the static corridor;
4. confirmed blockage causes bounded local/corridor replan rather than blind
   forward motion;
5. arrival is confirmed by fresh telemetry, not by route exhaustion alone.

### 2026-09-22 — Hz hot-path and process capture adoption (offline-tested)

The two supplied performance documents were reconciled with the actual source.
The seven hot-path fixes are present, and the process capture design has also
progressed beyond the older document status: `SharedFrameRingBuffer`, the
capture worker/client, opt-in runtime construction and bounded shutdown are
implemented behind `AIPC_CAPTURE_PROCESS=1`.

Offline audit found and fixed two Windows/runtime correctness defects before a
live run: attached Windows shared memory can report a page-rounded mapping
size, so the real slot size is now carried explicitly in the header; and an
unchanged shared-memory snapshot is sequence-deduplicated so a live-but-stalled
worker cannot replay one old pixel-strip frame as fresh telemetry. The seqlock
now becomes odd before data-slot writes, covering slot wraparound as well as
header publication. Targeted tests passed (**25 passed**) and the complete
suite passed (**1508 passed, 3 skipped**).

Validation status remains **OFFLINE_TESTED, LIVE PENDING**. The process route
is intentionally not the default until a user-operated selected-PID comparison
measures source/publish/control Hz, foreground safety, GUI responsiveness,
worker failure handling and clean shutdown with and without
`AIPC_CAPTURE_PROCESS=1`.

### 2026-09-22 — V5 M2/M3 closure and M4/M5 audit continuation (offline)

No WoW client input was sent in this phase. The stale V5 coverage rows for M2
and M3 were reconciled with production code and deterministic acceptance
evidence. M3 gained explicit quest-level graph nodes and typed
REQUIRES/UNLOCKS/FOLLOW_UP/EXCLUSIVE_WITH/SAME_AREA_SYNERGY relations without
inferring links from quest IDs or list order. M4 gained a read-only
`OBSTACLE_OVERLAY_V1` diagnostic projection for traversability, drop/dynamic
risk, ego-motion, collision and selected local waypoint evidence; it owns no
perception, planning or input authority. M5 named acceptance paths were
re-run, including danger detours, oscillation handling and map-2175 mmap
routing.

Focused results: M2 **65 passed**, M3 **33 passed**, M4 overlay closure **30
passed**, M5 **44 passed**. Complete regression: **1511 passed, 3 skipped**.
All selected-PID acceptance remains live-open.

### 2026-09-22 — detailed V5 M4–M6 offline closure

No WoW client input was sent. The remaining detailed M4/M5 coverage rows were
audited against production contracts and tests. Traversability now gives
dynamic blockers an explicit temporary `DYNAMIC` lifecycle/event, confirms a
cliff only after repeated drop evidence, and represents water/terrain changes
as context-sensitive evidence rather than a global block. Focused results:
World3D/M4 **120 passed, 1 skipped**, M5 navigation **53 passed**, M6 runtime
integration **62 passed**, M1 authority audit **89 passed**.

Complete regression: **1514 passed, 3 skipped in 47.34 seconds**. The V5
ledger now has no unreviewed `TRACKED` rows: 166 are `OFFLINE_VERIFIED` and
three M6 release/objective rows are deliberately `OFFLINE_PARTIAL`. This does
not close selected-PID acceptance, live induced failures, long-run performance
or the autonomous Retail questline gate.

### 2026-09-23 — quest turn-in mmap live defect and 0.9.28 telemetry repair

User-operated map-1409 / instance-2175 testing proved that the quest turn-in
proposal selected `TRINITYCORE_MMAP` (`route_found`, 39,139 loaded polygons,
140–144 route polygons), but traversal still went into the waterfall area.
The captured run exposed two distinct causes. First, the old turn-in route
accepted normalized UI-map coordinates and bypassed mmap; this is now
fail-closed and only same-instance `WORLD_YARDS` destinations marked
`require_navmesh` can start that MOVE. Second, across 93 captured telemetry
states the normalized player position changed while `player_world_position`
remained frozen at `(106.1, -2273.1, 0)`. Consequently the movement controller
could not advance past the old corridor anchor.

Addon **0.9.28** now converts every fresh player map sample with
`C_Map.GetWorldPosFromMapPos` on the FAST lane. The frozen `UnitPosition` X/Y
is no longer authoritative; UnitPosition contributes only explicit Z evidence,
and missing Z is no longer manufactured as zero. Both Retail addon packages
carry the same change. Offline regressions are green, but corrected waypoint
progression is **LIVE OPEN** until a user-installed/reloaded 0.9.28 run proves:

1. `player_world_position.source == C_MAP_PLAYER_WORLD_POS`;
2. world X/Y changes while the character moves;
3. `route_source == TRINITYCORE_MMAP`;
4. the route waypoint index advances rather than steering indefinitely toward
   the first anchor;
5. no direct normalized-map MOVE is emitted for quest turn-in.

Follow-up live evidence showed that 0.9.28 still accepted Retail's numeric but
false player `z=0` as an observed height. At player map position
`51.83,60.00`, this selected the lower mmap layer: 46 anchors / about 679
yards, initially heading south behind the mountain. The same X/Y with unknown
Z projects onto the local upper walkable surface at about Z=98 and produces a
13-anchor / about 320-yard route toward the `51.62,47.84` quest location.

Addon **0.9.29** therefore keeps player Z unknown. `NavigationService` now
projects every fresh player X/Y onto the active mmap surface and refreshes it
during command/observation and waypoint advancement. The nearest active-route
anchor is used as a layer-continuity hint so stacked floors do not switch
arbitrarily. Diagnostics expose `player_surface_projection` with
`source=TRINITYCORE_MMAP_SURFACE`, polygon identity, ambiguity, and whether the
route-layer hint was used. This is offline verified; 0.9.29 remains live-open.

### 2026-09-23 — Trinity MAPS terrain/liquid composition (offline)

The supplied Retail extraction root was audited at
`C:\Program Files (x86)\World of Warcraft\_retail_`. Map 2175 has matching
MAPS, VMAPS and MMAPS tile coverage at `31_36`. A bounded read-only Trinity
MAPS v10 reader and `WorldGeometryService` were added. MAPS now provides a
terrain Z hint before mmap polygon selection and exposes liquid evidence;
MMAPS remains the sole route authority. VMAPS is only discovered and reports
`NOT_IMPLEMENTED` for queries, so no unimplemented collision/LOS result can
silently become fact.

Real-data offline evidence: `(80.88, -2271.34)` on instance 2175 resolves to
terrain Z `98.18`, consistent with the previously selected upper mmap layer.
Complete regression: **1617 passed, 4 skipped**. The next user-operated live
run must still prove correct initial heading, waypoint advancement, and that
the waterfall/lower-layer route no longer recurs.

### 2026-09-23 — completed quest INSPECT starvation and liquid-layer repair

User-operated PID 12356 evidence showed quest 58914 complete with an explicit
API-converted turn-in endpoint `(355.0, -2264.0)`, but generic World3D/map
INSPECT ran first. When MOVE finally appeared it failed
`required_navmesh_route_unavailable`, and search resumed. The trace also
proved the installed addon was 0.9.28 and still exported the invalid
`C_MAP_PLAYER_WORLD_POS + UNIT_POSITION z=0 + z_known=true` combination.

Three corrections are offline-tested:

1. telemetry normalization defensively rejects that legacy false Z even when
   the installed addon has not yet reached 0.9.29;
2. a completed quest with a same-instance WORLD_YARDS waypoint bypasses
   preliminary generic INSPECT/SEEK/OPEN_MAP and commits directly to its mmap
   MOVE;
3. MAPS terrain beneath liquid is retained as environment evidence but is not
   used as a navmesh layer hint. This prevents submerged terrain below a
   bridge/bank/platform from selecting the wrong endpoint layer.

On the exact captured endpoints, the composed MAPS/MMAPS route now succeeds:
14 anchors, 44 route polygons, nine tiles and about 224.44 yards. Complete
regression: **1620 passed, 4 skipped**. Live validation remains open and
requires restarting the Python agent; addon 0.9.29 is still the preferred
client package.

### 2026-09-23 — turn-in reach stopped early / FAST coordinate consumption

The next user-operated PID 12356 run used addon 0.9.29 and immediately chose
the priority-110 mmap turn-in MOVE; the previous INSPECT starvation did not
recur. It nevertheless stopped far from the API endpoint. At the final useful
sample the player was around `(286.60, -2211.05)` while the turn-in endpoint
was `(355.00, -2264.00)`, about 86.5 yards away, so this was not the configured
six-yard final arrival envelope. The reach was interrupted by a false
`STATE_INVALIDATION_TELEPORT`, later entered supported-stuck recovery, and
finally demoted to MANUAL after `telemetry_stalled`.

The pixel transport itself remained healthy: the saved status measured about
37.31 decoded FAST frames/s and 27.5 fresh FAST states/s. X/Y, world X/Y,
orientation and movement are present in the FAST packet. The control process,
however, consumed only about 2.36 FAST states/s during the affected interval;
`agent.tick` p95 grew beyond 500 ms. Active mmap movement was projecting the
fresh player point onto roughly 39,139 polygons in a 3x3 tile window multiple
times for every consumed coordinate sample.

Offline corrections:

1. mmap surface projection now uses a bounded eight-yard spatial index. On
   the captured Exile's Reach area the warm projection changed from roughly
   48–89 ms to about 0.014 ms;
2. one FAST player sample is projected only once across observe/command/local
   planning, rather than repeatedly;
3. addon-only FAST updates patch the authoritative position/movement fields
   without cloning the unchanged ~145 KB World3D projection tree;
4. a >50-yard WORLD_YARDS source correction is not a teleport when the
   independent normalized map position is unchanged. A corroborated large
   map/world jump remains a teleport;
5. crash hydration now accepts a valid FAST observation whose optional
   wall-clock timestamp is JSON null and falls back to its durable receive
   time.

Real-data navigation benchmark: one route construction took about 1.29 s,
then 20 consecutive observe+command updates had a warm median of 0.081 ms and
warm maximum of 1.171 ms. Complete regression: **1626 passed, 4 skipped**.
The Hz improvement and successful close approach remain **LIVE OPEN** and
require restarting the Python agent; no addon reinstall is required for these
Python-side changes.

### 2026-09-23 — FAST control-lane live result and medium-deadline starvation fix

The next user-operated PID 12356 run proved that mmap routing was active and
that the addon producer itself remained healthy, but it did **not** validate
the intended high-rate consumer. In `live-debug-20260923-214706.jsonl` the
source FAST rate had a median of about 29.35 Hz while
`movement_fast_consumer_hz` had a median of only about 4.74 Hz. Medium step
latency had a median of about 307.64 ms. The character consequently passed the
destination before the next useful arrival sample; the user pressing S merely
counteracted an agent-owned W lease that was still being refreshed from the
last known not-arrived state.

Root cause was runtime cadence, not a missing coordinate and not the movement
lease contract. `_next_medium_at` was scheduled from the **start** of the
expensive medium tick. A ~300 ms tick therefore consumed almost the complete
333 ms medium interval; only one FAST iteration could run before another
vision/planner/persistence tick became due. The runtime now schedules the next
medium deadline from the expensive tick's **completion**, leaving a real
one-third-second window for the lightweight canonical movement lane.

No translation-lease shortening or synthetic key-up arrival workaround is
part of this correction. A targeted overrun regression sleeps longer than the
configured medium period and proves that one slow medium tick is followed by
at least nine fresh FAST navigation updates rather than another immediate
medium tick. The lane and runtime control facades were extracted into focused
modules so the architecture-size gates remain satisfied (`runtime.py` 896
lines, `engine.py` 890 lines). Complete regression: **1631 passed, 4 skipped**.
Higher consumer Hz and removal of the destination overrun remain **LIVE OPEN**
pending the next user-operated run; addon reinstall is not required.

### 2026-09-23 — FAST cadence improvement measured live; visual-search launch failure

Two user-operated runs after the completion-relative scheduler change show a
real improvement rather than a renamed/hidden metric. During active movement,
`live-debug-20260923-220737.jsonl` measured a 33.44 Hz median source and 17.30
Hz median movement consumer; `live-debug-20260923-221642.jsonl` measured 32.56
Hz source and 18.75 Hz movement consumer (20.11 Hz p90). The pre-fix live
median was about 4.74 Hz. Arrival was repeatedly recognized and movement keys
were released, but the consumer still did not reach the available source rate.

The second trace also captured an independent fail-closed defect. A newly
launched `SEEK_VISUAL_CUE` already had a close candidate, so its first command
was `HOVER`. `ActionLaunchCoordinator` classified visual-search launch
commands as movement unless they were camera pan or INTERACTTARGET; HOVER was
therefore rejected by the movement scheduler as `Érvénytelen movement lease`
and FULL_AI correctly demoted to MANUAL. HOVER is now explicitly dispatched on
the discrete lane at launch, matching the already-correct continuation path.

To reduce remaining movement-loop starvation without masking the source or
consumer metrics, a committed coordinate REACH now gets one uninterrupted
second of FAST feedback between expensive complete vision/planner/persistence
passes. Arrival, safety transition and controller failure still force an
immediate medium tick. This version was produced after the captured processes
started and therefore remains **LIVE OPEN**. Complete regression: **1631
passed, 4 skipped**; no addon reinstall is required, but the Python agent must
be restarted.

### 2026-09-24 — Trained World3D YOLO runtime integration (LIVE OPEN)

The 20-epoch `world3d_annotation_assist_combined_1077_v1.pt` model is now
wired into the production GUI → AgentRuntime → PerceptionWorker → unified
World3D V3/V2 path. It is additive evidence only: learned labels are normalized
to UNKNOWN subject/object/symbol/scene candidates and cannot directly assert
NPC, mob, hostility, quest role, target identity, movement, or interaction.

Runtime thresholds and per-label budgets are stricter than annotation preview
settings to suppress excess boxes. Model import/CUDA initialization and warm-up
run in a daemon thread; cheap CV remains available while status is `warming`.
Offline RTX 2050 measurement after warm-up was about 107--122 ms per learned
detector refresh at 640 px. Targeted regression: **62 passed**; complete suite:
**1754 passed, 4 skipped**. Actual selected-PID detection quality and cadence
remain **LIVE OPEN** until the next user-operated test.

### 2026-09-24/25 — stale reward-selection loop found live and corrected

PID 14320 reached an active combat objective (`1/6 Blackrock Worg slain`),
with no quest dialog visible in the captured frames, while canonical state
still reported `quest_ui.open=true`, `action=REWARD_SELECT`, `quest_id=0` and
one reward row with zero coordinates. The planner consequently alternated
WAIT/reward handling instead of progressing the active quest.

Two independent stale-state paths were corrected. Addon 0.9.30 reads reward
choices only while the effective parent-aware QuestFrame/GossipFrame visibility
is true, so retained `GetNumQuestChoices()` data cannot synthesize an open
dialog. Independently, a fresh FAST `quest_ui_open=false` now clears the stale
nested full-snapshot `quest_ui` object in the canonical WorldModel immediately.
Thus the Python correction works even before the next full snapshot, while the
addon correction prevents the false source state entirely. Focused regression:
**31 passed**; complete suite: **1756 passed, 4 skipped**. Retest is live-open;
the Python agent must be restarted and addon 0.9.30 copied/reloaded for both
halves of the fix.

### 2026-09-25 — learned detector replay/live discrepancy corrected (LIVE OPEN)

The latest PID 20916 diagnostic initially exposed one learned candidate and
reported no post-model threshold rejection, but controlled replay of its final
capture explained why annotation preview appeared much better than runtime.
At confidence 0.20/0.30 the full-frame model produced three boxes (0.843
creature, 0.479 humanoid, 0.390 humanoid); the old 0.48 backend gate retained
only the creature. More importantly, the runtime scene adapter then rejected
the strong right-side creature because its box intersected the broad quest
tracker exclusion band. Real WoW subjects can stand behind translucent HUD
regions, so intersection is not proof of UI content.

Runtime now admits learned detections at 0.30 for observable diagnostics and
uses class-specific gates (subject classes 0.40/0.42) plus existing class and
global budgets. Learned subject boxes may cross broad HUD overlays, while
non-subject cues retain UI exclusion. The explicit lower-centre self-avatar
rectangle remains a separate suppression rule, preventing the controlled
player from becoming an external subject candidate. CUDA auto-selection and
device diagnostics were also corrected: the same saved frame now yields the
real worg at 0.796, suppresses the player as self-avatar, and reports `cuda:0`.
Focused regression: **49 passed**; complete suite: **1758 passed, 4 skipped**.
Selected-PID behavior after restart remains live-open.

### 2026-09-25 — World3D TensorRT/foveated fast path (LIVE OPEN)

The visual runtime now separates 60 Hz patch tracking/view publication from
12 Hz canonical evidence processing and 5–8 Hz learned detection. YOLO runs in
a separate process with shared-memory image transport. This host has static
FP16 TensorRT engines for 512 global scans and 640 foveal scans; the portable
PyTorch checkpoint remains an automatic fallback. Global reacquisition runs
every third refresh and immediately after an empty foveal scan.

Offline measurement on the RTX 2050 reduced the 640 learned-detector median
from 20.24 ms (PyTorch) to 9.08 ms (TensorRT plus shared memory). The 4K-to-
1600x900 viewer render median fell from 29.08 ms to 7.35 ms. Focused regression:
**185 passed, 1 skipped**; complete suite: **1770 passed, 4 skipped**. Sustained
selected-PID viewer/source rate and live small-marker recall remain **LIVE
OPEN**. Restart the Python agent before testing; the addon was not changed.

### 2026-09-25 — 600--800 ms control-loop spike correction (LIVE OPEN)

The active PID 14752 run showed healthy component medians (capture 52--67 FPS,
pixelstrip 33.28 Hz, tracker p50 8.1 ms, detector p50 9.28 ms), but agent-tick
p95 was 255.92 ms and the user observed 600--800 ms stalls. The synchronous
memory pass removed 8,896 rows in one transaction, while status generation was
also allowed to rebuild the full diagnostic WorldModel projection on frequent
World3D updates.

Follow-up inspection showed the issue as an actual rate collapse, not merely a
latency-display problem: source capture remained 64.69 FPS and source FAST data
35.48 Hz while the main control loop fell to 2.67 Hz. Maintenance took 348.2 ms
and was incorrectly rescheduled every 500 ms because 233,983 authoritative and
derived observations were all counted as removable CV backlog; only eight were
actually eligible in that pass. The same short session had already persisted
16,427 redundant belief/contradiction events and 17,153 corresponding graph
relations from continuously changing camera, position and World3D samples.

Maintenance now has a global 256-row deletion budget per pass, calculates CV
backlog only from eligible derived sources, keeps a fixed 60-second cadence,
and is fully deferred while FULL_AI owns input. High-frequency temporal state
still enters evidence but no longer becomes a durable belief/contradiction
lifecycle event on every sample. Status keeps the large world projection for
one second without delaying lightweight control-state updates;
the first control-relevant World3D interrupt remains immediately visible.
Performance diagnostics now publish p99 and maximum latency, including a
separate `memory_maintenance` series. Complete regression: **1773 passed, 4
skipped**. This remains **LIVE OPEN** until a restarted Python agent produces a
new selected-PID trace; no addon update is required.

### 2026-09-25 — LIVE VISION resource contention isolated (LIVE OPEN)

After restarting with the maintenance correction, capture remained 64.68 FPS
and pixelstrip source FAST 30.86 Hz, while the optional live viewer coincided
with perception max 613.98 ms, patch-tracker p95 263.79 ms/max 316.34 ms and an
effective main loop of 14.48 Hz. Replaying the same gray conversion and camera
translation outside the live workload measured below 2 ms p95, proving that
the apparent tracker cost was scheduling/resource contention rather than its
algorithmic workload.

The spawned viewer process used OpenCV's host defaults: 12 CPU workers and
OpenCL enabled. It now starts with one OpenCV worker, OpenCL disabled and
below-normal Windows process priority. This changes diagnostics only; YOLO,
tracking evidence, planner and input authority are unchanged. Complete
regression: **1774 passed, 4 skipped**. Restarting the Python agent is required
to recreate the viewer process; addon update is not required. Result remains
**LIVE OPEN** until viewer-on rates are measured again.

### 2026-09-26 — combined 2794 v4 TensorRT runtime promotion (LIVE OPEN)

The default World3D learned detector now selects the combined-2794 v4
revision. Machine-local static FP16 TensorRT engines were built for both the
640 foveal path and 512 global path; the v4 PyTorch checkpoint remains the
portable fallback. A process-isolated smoke benchmark loaded both v4 engines
and reported `status=ready`, `device=cuda:0`, 6.83 ms median and 8.11 ms p95
over twelve blank-frame iterations. Focused model/runtime regression:
**48 passed**; complete regression: **1775 passed, 4 skipped**.

On the fixed 108-image / 176-instance Exile's Reach test split, v4 changed
precision 0.431 -> 0.396, recall 0.505 -> 0.452, mAP50 0.398 -> 0.404 and
mAP50-95 0.130 -> 0.140 relative to v3. Creature and quest-object AP improved,
while corpse AP regressed from 0.509 to 0.301 at mAP50. A separately reviewed
unseen Dragonflight video showed severe cross-domain weakness, so this
promotion is a runtime wiring change, not proof of general visual reliability.
Selected-PID behavior remains **LIVE OPEN**. Restart the Python agent before
testing; no addon update is required.

### 2026-09-26 — self-avatar occlusion correction (LIVE OPEN)

The lower-centre third-person avatar band was still part of
`WorldSceneROI.excluded_rects` for the legacy/generic World3D paths. That was a
true detection mask: an NPC standing close enough to overlap the controlled
character could be removed before tracking. The band is now metadata only and
all detector paths observe the original pixels.

Probable own-avatar detections are retained as UNKNOWN observations/tracks and
receive only a post-detection `ATTENTION_SUPPRESS_ONLY` hint. They cannot become
SEEK or INSPECT targets without independent evidence. An ABOVE relation,
supported visual group or badge-like cue cancels suppression, preserving a
nearby NPC in the same screen region. Focused regression: **65 passed**; all
World3D tests: **135 passed, 1 skipped**.

Live acceptance remains open. Restart the Python agent, place an NPC partly
behind/in front of the character silhouette, and verify that (1) the NPC and
its overhead cue remain candidate/track evidence, (2) the controlled avatar is
not selected for hover/SEEK, and (3) no unrelated self track receives input.
No addon refresh is required.

### 2026-09-26 — in-progress Murloc objective route/loop audit (LIVE OPEN)

Selected PID 8260, run `live-debug-20260926-182316.jsonl`, confirmed that the
Murloc problem was not detector blindness. The addon identified
`Murloc Spearhunter`; COMBAT and LOOT ran, and the exact runtime crop from
`0180-182617-568-critical.jpg` independently produced multiple
`creature_unit_like` detections (top confidence `0.563`). After loot, however,
the controller selected normalized Quest POI movement, interpreted arrival
without a currently selected target as an unknown route transition, and
entered `SEARCH_ENTRANCE -> OPEN_MAP -> WAIT/INSPECT`.

The live quest location already contained authoritative conversion evidence:
quest `55122`, UI map `1409`, instance `2175`, world X/Y
`-366.00003051758/-2558.9997558594`. In-progress quest movement now consumes
that WORLD_YARDS endpoint through mandatory MMAP routing, never the normalized
UI point. Ordinary objective-area arrival cannot create an entrance hypothesis
without explicit transition/repeated-blockage evidence, and completed route
bookkeeping preserves the original POI identity before handing back to local
target/object search. Focused regression: **85 passed**. Restart the Python
agent and retest the post-loot continuation; no addon refresh is required.

### 2026-09-26 — Jaina overhead marker / WAIT audit (LIVE OPEN)

Selected PID 8260, run `live-debug-20260926-180935.jsonl`, repeatedly entered
WAIT while Jaina and a large yellow overhead marker were plainly visible in
capture `0068-181050-761-critical.jpg`. Exact offline reproduction using the
same 512px World3D crop found the real marker as `overhead_symbol_like` at
confidence `0.01725`, above the configured `0.01` gate. The runtime loss was
therefore not a YOLO score failure: the marker intersected the fixed top-right
minimap exclusion and was discarded after inference. The trace also contained
stable UNKNOWN symbol/subject groups, but the planner did not treat a
`SUPPORTED` group belief as sufficient active-perception interest.

Both disconnects are corrected without assigning quest semantics. Learned
overhead symbols/subjects may survive optional HUD-region overlap, and a
temporally supported UNKNOWN `symbol ABOVE subject` group may start
`SEEK_VISUAL_CUE(purpose=IDENTIFY)`. Focused regression: **78 passed**. Live
acceptance remains open: restart the Python agent and confirm that the visible
marker becomes a persistent UNKNOWN track and leads to SEEK/hover rather than
the prior WAIT/map fallback. No addon refresh is required.

### 2026-09-26 — blue objective-region coverage and movement envelope (LIVE OPEN)

The Retail objective search region is **blue**, not yellow. World Map and
minimap detection now retain it as `UNKNOWN`/`blue_region_like` appearance
evidence with area geometry; colour alone never creates quest semantics. A
World Map blue area is associated only when an active quest's API POI lies in
or immediately beside its map-local bounds. The addon now exports Blizzard's
`C_Map.GetWorldPosFromMapPos` affine basis, allowing the associated visual
bounds to become bounded same-instance WORLD_YARDS coverage points.

Coverage waypoints require MMAP routing, remain inside the derived area
envelope, and stop as soon as a relevant live unit is identified. Without a
trusted transform the system uses only a small MMAP-routed circle around the
already-authoritative quest POI world centre; it never converts a raw screen,
minimap or normalized-map pixel directly into movement. Cross-instance/zone
movement is fail-closed for live sessions in this phase.

Focused regression: **45 passed**. Broad suite: **1757 passed, 4 skipped,
40 failed** before the test-fixture compatibility exemption; most failures
are legacy synthetic expectations for normalized-map direct MOVE, which is
now intentionally forbidden in live control, plus already-known search
cadence expectations. A fresh broad-suite count is still required after the
compatibility change. Live validation is open and requires copying the
updated addon, `/reload`, restarting the Python agent, and verifying map area
detection plus the resulting MMAP coverage route.

MMAPS is the current route/walkability authority and MAPS supplies terrain and
liquid evidence. VMAP files are discovered, but the repository still reports
`vmap_query_status=NOT_IMPLEMENTED`; independent VMAP collision/LOS queries
must not be claimed as implemented or live-validated. MMAP-generated
walkability already excludes its baked non-walkable geometry, but explicit
VMAP validation remains an open coverage item.

### 2026-09-26 — delayed combat target → visual approach handoff (LIVE OPEN)

Selected PID 8260, pre-fix run `live-debug-20260926-183950.jsonl`, selected
`Murloc Watershaper` with authoritative GUID/NPC ID and `attackable=true`, but
then entered WAIT. The trace proved World3D was active (`WORLD3D:47`,
`IDENTITY_OBSERVED`) while `target.world_position` was unavailable. Two
independent handoff faults were present: ACQUIRE_TARGET could time out one FAST
packet before the selected target arrived, and combat admission used slow
actionbar range/readiness while the current facts already existed in
`actionbar_fast`.

The ACQUIRE commitment now retains a bounded confirmation grace and promotes
only a later addon-confirmed living attackable GUID. Exact-GUID nameplates are
associated with the current generic UNKNOWN subject track, producing a
screen-space target anchor without inventing world XYZ or CV semantics. FAST
usable/range/cooldown facts are projected over stable action identities for
planner, visual servo and CombatSkill consumers. Consequently an out-of-range
selected target with no world position can enter persistent VISUAL_APPROACH;
each fresh target nameplate sample or the associated World3D track updates the
servo instead of reusing a frozen pixel.

Focused regression: **121 passed**. Complete repository run: **1787 passed,
4 skipped, 15 failed**; the remaining failures are recorded as current suite
debt outside this focused acceptance set and are not counted as live evidence.
Live acceptance remains open: restart the Python agent and repeat the Murloc
selection from outside spell range. No addon refresh is required.

### 2026-09-26 — combat rotation and fast visual follow (LIVE OPEN)

Offline inspection found that the canonical `CombatSkill` did not retain its
own ability-use history even though the diagnostic compatibility controller
did. The skill now selects from the FAST-overlaid actionbar with per-attempt
usage history and continues choosing ready abilities until combat completion.
Starter Warrior semantics cover Charge at range and Shield Slam/Slam in melee;
client usability, range and cooldown remain authoritative.

The selected GUID is now followed through its associated World3D screen track.
Fresh off-centre samples request bounded facing through NavigationService;
out-of-range samples repeatedly request visual approach; temporary off-screen
loss turns only in the last evidenced direction for at most 1.8 seconds. COMBAT
requests the fast visual-servo perception profile, but **30 FPS is not claimed
until measured live**.

Focused regression: **66 passed**. Complete repository regression after the
version-contract update: **1795 passed, 4 skipped, 15 pre-existing unrelated
failures**. Live procedure: install addon 0.9.32, `/reload`, restart Python,
select an attackable mob outside Charge range, and capture (1) approach,
(2) Charge, (3) Shield Slam/Slam continuation, (4) lateral/behind movement,
(5) `world_tracker_hz`, ability attempts and UI-error recovery.

### 2026-09-26 — tracker starvation and off-screen TAB target (LIVE OPEN)

PID 8260, `live-debug-20260926-203501.jsonl`: during FULL_AI the measured
rates were fast-control median 12.65 Hz, tracker median 6.75 Hz and detector
median 2.64 Hz. World3D work reached 407 ms at p95 while complete step p95 was
about 250 ms, proving that the prior synchronous perception call was being
starved by the medium planner/persistence tick.

The live trace also showed `ACQUIRE_TARGET` selecting a Coastal Goat through
`TARGETNEARESTENEMY`. The addon supplied a valid GUID, but there was no fresh
World3D/screen anchor and harmful actions were out of range. The old autonomy
loop nevertheless promoted it to a persistent TARGET commitment, after which
movement could not localize it.

The Python runtime now uses an independent latest-frame perception pump. An
offline production-path benchmark reached **23.47 tracker Hz**, **3.83 detector
Hz** and **3.61 canonical Hz** with no background error; this is offline
performance evidence, not live acceptance. Quest exploration no longer emits
blind `ACQUIRE_TARGET`. In-combat emergency acquisition remains permitted, but
an acquired GUID is promoted only with a fresh visual anchor or positive range
evidence. Otherwise it emits `BLIND_TARGET_UNLOCATABLE` and replans instead of
walking toward an unseen unit. The still-selected off-screen identity also no
longer blocks `SEEK_VISUAL_CUE`; World3D search continues until a local visual
anchor is available.

Next live acceptance: restart the Python agent (no addon change), run the same
kill-objective scene, and verify (1) tracker stays in the 20–30 Hz band, (2)
no post-combat blind TAB selection, and (3) visible candidates are acquired by
World3D/hover before approach.

Post-fix full offline regression: **1801 passed, 4 skipped, 15 known unrelated
failures**. No new failure remains in the target-localization or background
perception changes.

The final follow-up scheduler tuning uses a 120 Hz latest-frame pump with 40 Hz
tracker-only admission. Expensive detector and canonical work retain their own
independent cadence and no stale frame queue is allowed. Offline measurement
reached **33.11 tracker Hz**, 4.09 detector Hz and 3.76 canonical Hz;
background-update p95 was 0.27 ms. Live WoW rate confirmation remains required.
## 2026-09-26 — Fast camera tracking / detector cadence patch (offline)

The reported `detector_hz=3.84` exposed two separate limitations. Detector
refresh used a post-inference adaptive cooldown despite already having a
single-in-flight latest-frame boundary, and the CPU tracker rejected camera
translations beyond a small cap while its per-track residual search covered
only about eight full-resolution pixels. The detector now uses start-to-start
deadlines, profiles request 8/10/12/15 Hz (balanced/navigation/quest/combat),
and active tracking requests 40 Hz through a 45 Hz admission gate. Camera
translation and residual patch search were widened but remain confidence
gated. This is offline-tested only; live acceptance must confirm actual
detector/tracker Hz and target retention during running plus camera rotation.
## 2026-09-26 — Learned humanoid INSPECT eligibility (offline)

The production model admitted live `humanoid_unit_like` tracks between 0.154
and 0.599, but the generic Planner INSPECT gate required 0.65 and could also
require nameplate alignment. Stable learned subject tracks now use a temporal
gate: confidence 0.22 after three stable frames and 0.12 after six. They stay
semantically UNKNOWN until mouseover/addon evidence confirms identity. The
self-avatar suppression path is unchanged. Offline regression: 72 passed;
live validation must verify that a non-self humanoid receives HOVER/INSPECT.
## 2026-09-26 — Learned subject confidence 0.05 (offline)

At user request, both `humanoid_unit_like` and `creature_unit_like` now pass
the runtime learned detector at confidence `0.05`. Once temporally stable,
they are also eligible for mouseover INSPECT at `0.05`. Detection is still not
recognition: every proposal remains UNKNOWN until independent telemetry or
interaction evidence confirms it. Live validation is pending.
## 2026-09-26 22:51–23:02 — 0.05 subject gate live-log audit

PID 1852 produced three substantial fresh FULL_AI intervals after the learned
subject threshold change. Median `(tracker, detector, World3D, addon-fast,
fast-control)` rates were respectively `(7.10, 4.23, 23.04, 21.18, 25.17)`,
`(21.34, 6.13, 21.40, 15.30, 17.43)`, and
`(1.98, 1.98, 1.98, 21.65, 25.28)` Hz. The third interval is a failed
performance acceptance: addon-fast stayed healthy while vision collapsed.
The terminal diagnostic recorded 244.26 ms patch propagation and 938.02 ms
detector/world work, so this slowdown is in the World3D lane rather than the
addon transport.

The latest 180-frame capture segment was replayed through the production
TensorRT detector and current runtime admission policy. Ten evenly sampled
frames produced 24 admitted boxes: 17 `creature_unit_like`, 5
`humanoid_unit_like`, 1 `corpse_like`, and 1 `overhead_symbol_like`; one frame
had no admitted detection. Scores down to 0.051 were admitted, confirming the
0.05 subject gate. Visual review also shows weak false positives and repeated
self-avatar humanoid detections, so this is detector evidence, not recognition
or entity-count ground truth. Rendered evidence is stored under
`output/agent/pid-1852/runtime-detector-review-night-10/`.

## 2026-09-27 — Quest MOVE + passive visual search and combat resume (offline)

Quest navigation now keeps World3D perception passive while the single
NavigationService controller owns MOVE. A stable goal-relevant UNKNOWN track
can create one track-bound ownership handoff to `INSPECT`/`SEEK_VISUAL_CUE`;
generic scenery is not admitted. Quest turn-in traversal requires quest-symbol
or supported overhead evidence, while objective-area traversal may also admit
temporally stable learned humanoid/creature subjects at the configured 0.05
detector threshold. The handoff is recorded as cancellation, not arrival, so
it cannot falsely mark a quest waypoint reached or increment quest progress.

Combat retains higher priority. An interrupted quest MOVE keeps its exact
intent for up to 180 seconds while combat remains active, then resumes that
same quest/objective/destination after combat clears. Death, loading, manual
mode and invalid preconditions still discard autonomous resume. Offline
targeted regressions: 60 passed. Full repository run: 1807 passed, 4 skipped,
15 existing unrelated failures; no live claim is made yet.

## 2026-09-27 — Stuck watchdog dispatch gap (offline fixed, live pending)

Older live traces and the M1 canonical runtime replay agreed on one concrete
failure: a failed MOVE reached `SUPPORTED_STUCK` and the resolver entered
`STOP_AND_OBSERVE`, but movement teardown cleared the ProgressMonitor sample.
The resolver then had no fresh evidence with which to unlock its first bounded
recovery step, so `INSPECT`/`SEEK_VISUAL_CUE` could repeatedly occupy execution
while the stuck state itself remained visible in diagnostics.

NavigationService now retains a minimal, recovery-only observation anchor at
the already-supported stuck boundary. The same frame cannot confirm recovery.
One later telemetry frame either (a) shows meaningful displacement and clears
the stale stuck belief, or (b) independently confirms stopped/no-progress and
unlocks the finite `BACKWARD -> TURN -> STRAFE -> ...` ladder. RecoveryPlanner
then resets the background visual commitment and gives that one RECOVER intent
the execution slot; combat, casting and transactional UI safety gates remain
unchanged. The interrupted REACH is still resumed only after verified recovery.

Focused movement/recovery regression: **23 passed**, followed by **73 passed / 1
pre-existing quest-location failure** across the wider navigation set. Full
repository regression: **1812 passed, 4 skipped, 14 existing unrelated
failures**. A user-operated live run is still required before calling the
watchdog path live-validated.

## 2026-09-27 — World3D tracker-rate collapse diagnosis (offline fixed)

The three long PID-1852 runs did not show one uniformly slow tracker. A clean
World3D interval sustained median **21.34 tracker Hz / 5.96 detector Hz**,
proving that the runtime path can exceed 20 Hz. Two misleading/failing cases
were isolated:

1. During one long interval the World Map was active for 87% of samples. Its
   intentional ~2-Hz map perception shared the outer worker lane and was
   incorrectly counted as both World3D tracking and detector refresh.
2. In a genuine World3D interval an isolated **244.26-ms** patch-propagation
   spike became the scheduler's permanent cost estimate. Later frames returned
   to an 8–9-ms median, but the last-sample controller continued admitting work
   near 2 Hz. Detector refresh can only be harvested on those admitted tracker
   ticks, so both counters collapsed together while addon-fast and fast-control
   remained healthy.

World Map publications no longer mutate World3D detector/tracker counters or
cost estimates. Tracker backpressure now uses a bounded 31-sample rolling
median, preserving throttling for sustained overload while recovering quickly
from isolated viewer/OS/GPU contention. Diagnostics expose `active_surface`,
the raw last propagation cost, robust `propagate_scheduler_ms`, and its sample
count. Detection quality remains a separate open issue: the 0.05 learned-box
gate increases weak candidates, and low-cadence runs showed more occluded/new
tracks. The next live run must confirm sustained 20+ Hz before association or
model changes are judged. Focused regressions: **72 passed**.

## 2026-09-27 — Learned humanoid/creature runtime gate raised to 0.15 (offline)

The shared runtime admission threshold for learned `humanoid_unit_like` and
`creature_unit_like` proposals is now **0.15**. The detector, World3D INSPECT,
distant `SEEK_VISUAL_CUE`, and quest-MOVE visual handoff all import the same
constant, preventing a weak box from being rejected in one layer but acted on
by another. Exact-boundary regressions prove that confidence `0.149` is
rejected and `0.15` is admitted at detector, inspection, and movement-handoff
boundaries.

The backend inference floor intentionally remains lower so diagnostics/replay
can measure weak model outputs; those boxes do not become runtime subject
candidates below the class gate. This change does not alter the independently
configured overhead-symbol threshold and does not turn visual detections into
semantic facts. Focused regression: **52 passed**. Live selected-PID validation
is still pending and the previous 0.05 live/replay observations above remain
historical evidence, not the current policy.

## 2026-09-27 — World Map reopen/stuck loop diagnosed live, fixed offline

PID 20804 exposed a deterministic map lifecycle loop. Retail reported
`map_context.active_map_id=1409` with `parent_map_id=0`; the planner treated
the zero sentinel as a real parent, issued `MAP_STEP_OUT`, then failed with
`parent_map_context_not_observed`. When the user closed the map, the scan state
was cleared without being marked terminal, allowing `OPEN_MAP` to be selected
again after cooldown.

Map hierarchy normalization now accepts only positive, non-self parent UiMap
IDs. A map that disappears while an active scan is unresolved is marked
exhausted for the current session/map/quest revision, so a user or unexpected
UI close cannot immediately reopen the same failed scan. Valid addon-reported
parents still retain the bounded step-out procedure. Focused regressions:
**47 passed**. The fix requires an agent restart and remains pending live
confirmation.

## 2026-09-27 — MOVE / visual-cue interruption storm diagnosed live, fixed offline

PID 20804 confirmed that the apparent stop-and-go movement was mostly an
attention-policy failure rather than normal waypoint traversal. The trace
contained **79 MOVE intents, of which 77 were cancelled with
`quest_route_visual_cue_observed`**. Those cancellations produced **38
SEEK_VISUAL_CUE** attempts; **21** then failed with `visual_track_lost`. Most
were weak learned UNKNOWN subjects (roughly 0.17–0.25 confidence) or generic
symbol/subect probes encountered before the route endpoint.

Detection admission and committed-route interruption are now separate gates.
The learned detector remains at 0.15 so weak evidence can still be tracked and
inspected while stationary. Cancelling an objective MOVE for a generic learned
humanoid/creature now requires confidence >= 0.30, at least 6 stable frames,
and player distance <= 25 world yards from the route destination. Explicit
quest-symbol appearance remains eligible independently. A generic supported
`ABOVE` relation without quest appearance no longer interrupts a turn-in
route, and an unmarked creature never interrupts quest turn-in movement.

The handoff record now also carries the measured destination distance and the
exact confidence/stability gates used for the selected track. Focused
regression: **67 passed**; the wider navigation/movement selection completed
with **141 passed and 1 pre-existing quest-POI test failure**
(`test_reached_quest_poi_is_not_reissued_after_camera_observation_drift`).
This policy requires an agent restart and remains pending user-operated live
confirmation.

## 2026-09-27 — Foreign dead mobs incorrectly selected for LOOT (offline fixed)

Live feedback exposed a missing ownership distinction: any addon-confirmed
dead Creature/Vehicle mouseover was promoted to an actionable corpse anchor.
`DEAD` therefore incorrectly implied `LOOTABLE_BY_PLAYER`, and an unrelated
corpse could receive a priority-108 LOOT proposal.

The WorldModel now keeps a bounded exact-GUID `owned_corpse_guids` set. An
entry is created only from this agent's verified COMBAT/DEFEND result; the
immediate death transition may also use exact active-combat/committed-target
continuity. Explicit future client telemetry `lootable=true` is accepted as
authoritative, but name, proximity, visual corpse appearance and `dead=true`
alone are not. Mouseover events for foreign corpses no longer create
actionable corpse anchors, and the selected-dead-target fallback applies the
same ownership gate. Successful loot retires both the anchor and ownership
record.

Focused combat/loot/world regressions: **92 passed**, plus **15 passed** from
the agent-core loot/corpse/combat selection set. The change requires an agent
restart and remains pending user-operated live confirmation.

## 2026-09-27 — Selected hostile visual approach no longer requires hover (offline)

The last PID-20804 status captured the failure directly: the selected target
was an authoritative `Murloc Watershaper` GUID, `softenemy` reported the same
GUID, but `mouseover` and `nameplates` were empty. World3D still contained
stable learned creature/subject tracks. CombatPlanningPolicy previously built
VISUAL_APPROACH only from `target.screen_position` or a confirmed mouseover
anchor, so this state fell through to WAIT despite a visible candidate.

An already selected, living, attackable exact GUID can now use a stable
World3D subject as screen-space steering evidence when harmful actions report
out of range. The candidate requires the shared >=0.15 runtime subject gate,
at least 3 stable frames, valid screen coordinates and a live lifecycle. The
selected target remains the identity authority; the chosen UNKNOWN track is
labelled only `CANDIDATE_SELECTED_TARGET` and is not converted into a semantic
Murloc/entity fact. Mouseover is therefore no longer a continuous movement
precondition. If no stable visual track exists, the controller still refuses
blind forward movement.

Focused combat/visual-approach regressions: **57 passed**. Agent restart and
user-operated live confirmation remain required.

# 2026-09-27 — FULL_AI arming and telemetry-liveness correction (offline-tested)

- Live evidence inspected from `output/agent/pid-20804`: the selected-client
  capture decoded 1702 AIPC5 packets and remained `streaming`, while the main
  runtime's last payload age reached 14.338 seconds.  The old freshness gate
  demoted FULL_AI as soon as WorldModel freshness crossed its six-second TTL.
  This proves the observed MANUAL transition was not, by itself, evidence that
  the strip was invisible or the selected PID was wrong.
- FULL_AI arming is now a passive 45-second handshake over four explicit gates:
  selected-PID foreground, fresh addon state, recent World3D result, and the
  verified binding export.  `arm_blockers` reports the exact unresolved gate.
- A telemetry outage now immediately releases/disarms all input but preserves
  FULL_AI and its committed subgoal for up to 90 seconds.  Two consecutive
  fresh observations are required before input authority is re-armed.  A
  persistent outage still demotes to MANUAL.
- Foreground loss immediately releases movement.  A short GUI/Alt-Tab interval
  preserves the committed state; a sustained 15-second loss still demotes.
- Pixel telemetry diagnostics now distinguish capture/decode age, published
  update age, a frozen packet identity, and packet-assembly stalls.  SensorHub
  retains the last publication timestamp after mailbox consumption.
- Offline regression: freshness, SensorHub, buffered sensor and AgentRuntime
  group: 52 passed.  One pre-existing quest replay expectation remains red
  (`test_complete_offline_quest_combat_loot_turnin_replay`: fixture expects six
  commands, current planner emits five); it is outside this liveness patch.
- Live validation still required: restart the agent, arm FULL_AI once, and
  observe one natural telemetry interruption.  Expected result is
  `telemetry_suspended_waiting_for_stable_recovery`, no held keys, FULL_AI
  retained, followed by automatic continuation after two fresh packets.

## Follow-up inspection: evening runs

- `20260927-214644-890-002` ran for about 129 seconds and stayed FULL_AI after
  arming. Its largest accepted addon-observation gap was 5.21 seconds.
- `20260927-215117-757-003` exposed a separate race: after foreground was
  lost, the stale-but-still-fresh WorldModel launched `TARGET`; the input
  backend correctly rejected it with `A kiválasztott PID ablaka nincs
  előtérben`, and that action failure caused MANUAL before the intended focus
  grace expired. This was not a missing-strip demotion.
- Corrected after inspection: foreground suspension is now a planner boundary.
  It releases movement once, emits `selected_pid_foreground_suspended`, and
  does not call `Agent.tick` or launch any action until the selected PID is
  foreground again. Repeated suspended ticks no longer issue repeated stop
  calls. Likewise, telemetry suspension disarms input once per outage rather
  than once per control tick.
- The status projector now reports `selected_PID_not_foreground` while this
  gate is active instead of leaking a misleading concurrent
  `pixel_strip_not_visible` discovery status.
- Offline regression after follow-up: 53 focused liveness/sensor/runtime tests
  passed; 105 input/core tests passed with two unrelated existing planner
  expectation failures excluded from this patch's acceptance.
## 2026-09-27/28 — CLOSE_MAP toggle-loop diagnosis and offline fix

- Live database: `output/agent/pid-20804/agent_memory.sqlite3`.
- At `611633.512` the agent dispatched `CLOSE_MAP`; FAST telemetry at
  `611633.840` already reported `map_context.world_map_open=false`, proving
  the first toggle closed the map.
- The skill verifier only read the legacy top-level `world_map_open` field,
  so it timed out at `611638.526` with `expected_observation_missing` and
  retried the non-idempotent `TOGGLEWORLDMAP` binding. FAST telemetry at
  `611638.776` then reported the map open again. The same close/reopen loop
  repeated in several later episodes.
- Fixed at both boundaries: transport normalization now projects the compact
  FAST `map_context.world_map_open` bit to canonical top-level state;
  OPEN_MAP/CLOSE_MAP availability and verification also read the nested FAST
  bit directly; dispatch suppresses a stale toggle when the requested state
  is already achieved.
- Offline regression: transport, map discovery, skill verification and
  idempotent dispatch tests pass. This fix is **offline-tested**, not yet
  live-validated.

## 2026-09-27/28 — long passive WAIT diagnosis and cooldown correction

- The live debugger contained repeated 29–30 second WAIT segments with
  `Nincs tartós közeledés ... az út ideiglenesen tiltva`. The duration maps
  directly to `AgentNavigator.permits()` quarantining a no-progress
  destination for 30 seconds after its evidence window.
- Per user direction, the destination retry cooldown is now five seconds.
  The 12-second evidence window that distinguishes momentary low progress
  from circling is unchanged; only the subsequent passive quarantine was
  shortened.
- A regression proves that the destination remains blocked immediately after
  detection but becomes eligible again at the five-second boundary. This is
  **offline-tested**, pending live validation.
- The follow-up correction adds a single five-second wall-clock budget shared
  by every consecutive planner WAIT reason. Changing from route-blocked to
  unresolved to commitment-wait no longer restarts the clock. Each WAIT now
  exposes `waiting_for`, its start/deadline/elapsed time, the number of fresh
  observations seen, and the next action.
- At the deadline the runtime records `PASSIVE_WAIT_BUDGET_EXHAUSTED`, releases
  stale commitment ownership, and performs one forced replan using only an
  already generated, currently available non-WAIT proposal through the normal
  navigation/recovery/SkillExecutor boundaries. It never invents blind input.
  Starting a real non-WAIT skill resets the shared budget. Explicit
  `WAIT_EVENT`, loading/casting, active-skill verification, telemetry safety
  suspension and manual safety pauses remain governed by their own contracts
  and are not misclassified as passive planner WAIT.
- Focused wait/autonomy/navigation/scheduler diagnostics regression:
  **47 passed**. The lifecycle remains **offline-tested**, pending a live run
  proving no uninterrupted passive WAIT chain exceeds roughly five seconds
  before a visible forced-replan event.

## 2026-09-28 — multiple quest offers and starter Warrior combat rotation

- User live report: an NPC exposing two available quests left the planner in
  `quest_offer_selection_required`; combat repeatedly selected Charge and did
  not fall back to melee auto-attack when Slam lacked rage.
- The live `pid-20804` journal confirms the combat defect. One COMBAT attempt
  dispatched `ACTIONBUTTON1` at `613014.247` and again at `613015.170`, then
  produced no further rotation command before `COMBAT_TIMEOUT` at
  `613022.269`. The selected action-bar snapshot identifies button 1 as
  Charge and button 2 as Slam with `lacks_resource=true`.
- Multiple addon-confirmed quest rows now select exactly one deterministic
  visible row (completed row first, otherwise topmost screen row). Acceptance
  is still separately verified; a later planning cycle may consume the next
  remaining offer. Explicit quest ID/title evidence still overrides ordering.
- Combat now requires a fresh FAST sample before another decision, treats a
  movement-tagged ability as a once-per-attempt opener, and suppresses Charge
  whenever a melee-range offensive action confirms the target is already
  close. Starter Slam metadata includes its 20-rage cost.
- If no melee ability is currently usable, CombatSkill may issue exactly one
  right click only on the fresh screen position of the exact addon-selected,
  living, attackable GUID. It then continues the same combat attempt and can
  choose Slam/Shield Slam when readiness changes. No arbitrary screen point,
  guessed target, or unverified binding is used.
- COMBAT/DEFEND now own a bounded full fight (45 seconds) instead of timing
  out after an eight-second opener; typed death, target, range, facing and LOS
  failures still terminate earlier.
- Offline regressions: focused quest/combat suite **54 passed**. Broader
  quest/combat/runtime suite: **288 passed**, with the same three pre-existing
  unrelated planner/replay expectation failures already recorded elsewhere.
- Status: **offline-tested, not live-validated**. Agent restart is required;
  no addon update is required for this patch.

## 2026-09-28 — PID 10516 two-offer gossip row coordinates

- User-operated live run `live-debug-20260928-113943.jsonl` reached Austin
  Huxworth after successfully turning in quest `55173` (`Northbound`).
- Telemetry then exposed two exact `AVAILABLE` quest identities: `55186`
  (`Down with the Quilboar`) and `55184` (`Quilboar Shadow Magic`), but both
  rows had `x=0,y=0`. The planner therefore had no addressable
  `GOSSIP_SELECT` action and incorrectly resumed `VISUAL_APPROACH` while the
  modal quest list remained open.
- Addon `0.9.33` now resolves Retail ScrollBox rows through bounded nested
  element-data inspection plus exact visible title-region matching. It still
  exports no coordinate when the row cannot be proven.
- The planner now fails closed with `quest_dialog_rows_unaddressable` whenever
  an open quest list has identified rows but no verified click point. This
  prevents navigation or visual-approach input from running behind the modal
  UI while preserving the existing exact-coordinate requirement.
- Focused quest-dialog/addon plus end-to-end modal preemption regressions:
  **32 passed**. The expanded quest/UI/runtime run passed **83** tests and hit
  one already documented offline replay command-count expectation; a broader
  `test_agent_core.py` selection also retained two unrelated navigation
  expectation failures.
- Status: **live failure diagnosed; fix offline-tested, not yet
  live-validated**. Install addon `0.9.33`, `/reload`, restart the Python
  agent, and repeat the same two-offer interaction under user control.

## 2026-09-28 — PID 10516 repeated pre-turn-in World Map loop

- The same user-operated trace shows repeated World Map openings before the
  `55173` turn-in: map opened at relative timestamps `200.126`, `210.427`,
  `215.048`, `233.447`, `242.126`, and `246.577`. User-closed states were
  followed by another planner-driven open.
- Austin Huxworth (`npc_id=154327`) was not identified until `248.905`;
  target identity followed at `251.806`, the `COMPLETE` dialog at `253.711`,
  and the completed quest disappeared from the active log at `260.096`.
- Root cause: a close turn-in POI with no selected 3D identity was treated as
  generic `UNKNOWN_TRANSITION` evidence. The resulting cycle was bounded
  entrance search -> failed search -> map relocalization -> successful map
  toggle -> entrance search again. The transition policy exempted ordinary
  objective-region arrivals from this inference, but not
  `LOCATE_TURN_IN_REGION` arrivals.
- Turn-in-region arrival now shares the same evidence rule: without explicit
  transition evidence or repeated route blockage it remains a local
  questgiver-search context, not an invented entrance. Separately, once the
  canonical map-search owner marks the current quest/session/map context
  exhausted, transition recovery returns a safe WAIT and cannot reopen the
  map until quest state, map context, or target identity changes.
- Combined quest-dialog/navigation regressions: **86 passed**. Status:
  **live failure diagnosed; fix offline-tested, pending user-operated live
  validation**. Python agent restart is required; this part adds no further
  addon change beyond the already prepared `0.9.33` package.

## 2026-09-28 — PID 10516 quest offer misclassified as reward selection

- In the user-operated `telemetry-20260928-120406.jsonl` run, the two-offer
  gossip list was correctly exported at relative timestamp `80.155` with
  addressable rows for quests `55186` and `55184`.
- After selecting quest `55184`, the snapshot at `81.763` incorrectly changed
  to `action=REWARD_SELECT`. It contained one unselected reward preview,
  `Expeditionary Plate Warboots` (`item_id=175180`), with no selectable
  coordinate. This was a quest-offer screen, where the valid action was
  `ACCEPT`; reward selection is only meaningful during turn-in.
- Root cause: `readQuestUI()` consulted `GetNumQuestChoices()` before resolving
  the visible quest action. A reward preview on `QUEST_DETAIL` therefore
  overrode the visible Accept button.
- Addon `0.9.34` gates reward enumeration and `REWARD_SELECT` behind visible
  completion/turn-in context and explicitly excludes any screen with a visible
  Accept button. Focused addon/quest-dialog/reward regressions: **38 passed**.
- Status: **live failure diagnosed; fix offline-tested, not yet
  live-validated**. Install addon `0.9.34`, `/reload`, restart the Python
  agent, then repeat quest `55184` acquisition under user control.

## 2026-09-28 — PID 10516 MOVE failed to defend against an attacker

- User-operated run `live-debug-20260928-121240.jsonl` entered combat at
  monotonic timestamp `663819.078` while executing quest-map MOVE. The
  supervisor correctly cancelled MOVE and issued `ACQUIRE_TARGET`; at
  `663820.446` it had the exact living, attackable quest target Geolord
  Grek'og (`npc_id=151091`) selected.
- The runtime then spent roughly 47 seconds alternating
  `TARGET_COMMITTED` WAIT with quest-map MOVE. No COMBAT skill started before
  player death at `663867.341`. Shield Slam failures visible at the end were
  dispatched only after death and are not evidence of a timely defense.
- Telemetry proves the target-rich FAST packet crossed the 850-byte body
  limit. Before combat, the merged state retained `actionbar_fast`; from the
  combat edge onward the last-resort transport packet omitted both
  `is_in_combat` and `actionbar_fast`. The slow actionbar exposed usable Shield
  Slam but no authoritative cooldown value, so the ability boundary rejected
  it as `cooldown_unknown`; intermittent stale combat state also allowed MOVE
  to resurface.
- Addon `0.9.35` introduces a combat-specific bounded fallback that preserves
  player health/death/combat state, exact target identity, movement, and all
  four compact actionbar readiness rows. It deliberately drops lower-priority
  hover presentation only when required to remain within the packet bound.
- Focused transport, combat planning, canonical combat skill, and interrupt
  regressions: **112 passed**. Status: **live failure diagnosed; fix
  offline-tested, not yet live-validated**. Install addon `0.9.35`, `/reload`,
  restart the Python agent, and repeat an incidental pull during MOVE under
  user control.

## 2026-09-28 — PID 10516 resumed MOVE repeatedly runs into a wall

- In user-operated run `live-debug-20260928-122602.jsonl`, combat correctly
  preempted MOVE and started COMBAT. After COMBAT ended with `target_lost`, the
  supervisor offered its one retained quest-`55186` MOVE intent at `12:27:09`.
- The resumed MOVE repeatedly held `W` or soft-steered until the user returned
  to MANUAL at `12:28:04`. During representative wall-contact intervals the
  authoritative world position was unchanged for multiple seconds while the
  client continued to export `movement.moving=true` and `speed=7`.
- Root cause: the progress fusion counted that run-animation/input state as
  positive progress. Combined with heading correction clearing the
  no-progress sample window, `CANDIDATE_STUCK`/`SUPPORTED_STUCK` could never
  accumulate despite no world displacement.
- Positive `moving` telemetry no longer contributes progress; it cannot
  outvote a zero target-distance delta. The combination of a commanded run
  state and unchanged position now contributes explicit
  `MOTION_POSITION_MISMATCH` evidence. Pure turn-in-place corrections pause
  no-progress collection, while forward soft-steering preserves and advances
  it.
- The reconstructed post-combat wall trace now terminates as
  `SUPPORTED_STUCK` and hands control to the existing bounded recovery path.
  Focused regressions: **58 passed**, with one unrelated existing quest-POI
  planner fixture deselected. Status: **live failure diagnosed; fix
  offline-tested, pending user-operated validation**. Python agent restart is
  required; no addon update beyond installed `0.9.35` is needed.

## 2026-09-28 — quest 56034 attacked the use-item target

- The user-operated run reached `Re-sizing the Situation` (`quest_id=56034`)
  at objective `1/3 Re-Sizer v9.0.1 tested on Wandering Boars`, but attacked
  the selected Wandering Boar instead of using the quest item.
- Live telemetry identified the complete causal chain: Retail exported the
  objective as raw `monster`; addon `0.9.35` normalized that directly to
  `KILL`; exact special item `170557` was present in bag 0 slot 9 but absent
  from the action bar; the canonical item skill only supported actionbar
  bindings. The combat proposal was therefore internally consistent with an
  incorrect objective model.
- Addon `0.9.36` now records `type_source=QUEST_SPECIAL_ITEM_NAME_MATCH` and
  normalizes to `USE_ITEM` only when the API special-item name occurs exactly
  in the objective text. Raw type remains available as contradictory/source
  evidence.
- Planner execution supports the same exact active-quest item through the
  existing addon-exported bag-button coordinate. It opens bags if necessary,
  then revalidates item ID, bag, slot, coordinate space, coordinate, lock
  state, quest ID, and active quest special-item authorization before one
  right-click. Success remains gated on quest-objective progress rather than
  click acknowledgement.
- Focused Lua/export, package mirror, objective semantics, planner,
  SkillRegistry, canonical skill, credit verification, and runtime tests:
  **72 passed**. A broader unrelated suite reached **55 passed** before the
  pre-existing blocked-MOVE/`SEEK_VISUAL_CUE` selection assertion failed.
- Addon `0.9.36` was installed into the running Retail client and its Lua hash
  matched the tested source. Status: **live failure diagnosed; fix
  offline-tested and installed, not yet live-validated**. The user must
  `/reload`, restart the Python agent, and repeat the objective under manual
  supervision. No FULL_AI process was left running at handoff.

## 2026-09-28 — continuous learned-detector throughput

- The smooth detector refresh shown in the referenced YOLO video was treated
  as a throughput problem, not as proof that its author used a tracker or
  achieved 1--2 ms inference. The current runtime's former profile cadence was
  an avoidable ceiling even though local TensorRT inference was already fast.
- World3D now uses a single-in-flight latest-frame detector stream. Completed
  inference is consumed and the newest available frame is submitted
  immediately; there is no stale-frame queue. Canonical WorldModel publication
  remains separately bounded.
- Production-path offline replay over saved live frames, requested at 40 Hz:
  source calls `36.55 Hz`, completed detector refreshes `36.32 Hz`, caller
  `2.94 ms p50 / 4.97 ms p95`, complete refresh
  `13.89 ms p50 / 17.73 ms p95`, `319/319` submissions/completions, one busy
  frame superseded.
- Focused World3D, process/shared-image, capture, buffered-sensor, scheduler,
  and live-view regression: **90 passed**. One broader quest replay expectation
  fails in isolation as well and is not attributed to this change.
- Status: **offline-tested, not live-validated**. Restart the Python agent and
  observe live detector/viewer rate and client responsiveness under user
  control. No FULL_AI process was intentionally started or left running for
  this work. `AIPC_WORLD3D_CONTINUOUS_DETECTOR=0` restores the legacy cadence.

## 2026-09-29 — committed friendly NPC track churn and map fallback

- User-operated PID 1468 test reached the intended friendly NPC, but only
  after a visibly slow sequence with repeated World Map overlays. The
  persisted action trace contained six failed `VISUAL_APPROACH` attempts
  (`visual_track_lost` or
  `visual_track_lost_identity_reconfirmation_missing`) between the first
  target confirmation and the quest dialog.
- The exact addon-confirmed GUID remained selected while its steering anchor
  changed canonical ids (`WORLD3D:135`, `WORLD3D:8`, `WORLD3D:25`,
  `WORLD3D:16`, then no projected id). Raw capture remained approximately
  59 FPS, so the observed delay was decision/identity churn rather than a
  capture-loop throughput failure.
- Two explicit `OPEN_MAP` attempts used the reason "Nincs ismert questhely".
  The first was immediately followed by `CLOSE_MAP` because the same committed
  3D target still required approach, proving an avoidable fallback loop.
- `VisualApproachController` now permits an unambiguous, nearby replacement
  subject track to inherit only the steering association while Retail's
  selected GUID remains the identity authority. Ambiguous adjacent candidates
  are rejected, and the existing periodic addon mouseover recheck remains in
  force. `track_rebindings` is exposed in diagnostics.
- A recent confirmed mouseover anchor for the exact committed target now
  suppresses unscoped map fallback. Map close starts a 30-second skill-level
  reopen gate that cannot be bypassed by changing `OPEN_MAP` parameters, and
  `VISUAL_APPROACH`/`REACQUIRE_TARGET` count as local actions before map
  fallback.
- Focused tracker/approach/map regressions: **127 passed**. Full suite:
  **1869 passed, 4 skipped, 18 failed**; the same 18 failures are the known
  unrelated baseline categories (legacy normalized-map movement fixtures,
  search cadence expectations, one offline replay count, telemetry timeout,
  module-size gates, and adaptive quest fixture). Status: **live failure
  diagnosed; fix offline-tested, pending user-operated validation**. No client
  input was taken over during diagnosis or implementation.

## 2026-09-29 — BoT-SORT partial-assignment sticky fallback

- A subsequent user screenshot showed many short-lived UNKNOWN boxes. Runtime
  diagnostics confirmed `proposal_mode=YOLO_ONLY` (`legacy_candidates=0`,
  `generic_candidates=0`), so OpenCV proposal generation was not their source;
  the boxes originated as low-confidence learned detections and were propagated
  between detector refreshes by the CPU patch tracker.
- The detector association layer reported `fallback_legacy` with
  `RuntimeError: tracker assigned 2/3 detections`. Ultralytics MOT may
  intentionally withhold a new/tentative detection until a later confirming
  frame, but the adapter incorrectly treated any partial assignment as fatal
  and permanently disabled BoT-SORT for that process.
- Partial assignment is now a supported lifecycle state. Native assignments
  stay on BoT-SORT; only withheld tentative detections use the already-running
  conservative tracker as a temporary public-ID bridge. A later native track
  adopts that public ID, so the transition does not create a visible reset.
  Diagnostics expose `ready_partial`, `native_assignments`, and
  `tentative_legacy_bridge`; genuine exceptions still use the sticky safe
  fallback.
- Focused adapter test with a deterministic 2-of-3 native assignment and the
  broader World3D/perception/live-view regressions: **190 passed, 2 skipped**.
  Status: **offline-tested, pending process restart and user-operated live
  validation**. The already-running GUI still contains the pre-fix module.

## 2026-09-29 — post-restart committed-NPC reacquisition and map loop

- The user-operated PID 1468 run after the BoT-SORT update kept the tracker
  backend in `ready`; no fallback reason was recorded. Final diagnostics showed
  one published detection with one native assignment and no tentative legacy
  bridge. This live run therefore validates that partial native assignment no
  longer causes the former sticky tracker fallback.
- The approach still ended in `visual_track_lost`. Its committed visual ids
  changed repeatedly, but `track_rebindings` remained zero. The controller had
  not retained the proposal's exact addon-confirmed mouseover point as its
  initial re-hover anchor, so a short detector gap produced only interaction
  probes and could not generate the fresh cursor/GUID evidence needed to bind
  the replacement track.
- Two failed `OPEN_MAP` attempts occurred consecutively. The first proposal had
  the committed GUID while the second did not, bypassing the proposal-keyed
  cooldown; temporary loss of Retail target selection also bypassed the recent
  committed-anchor suppression.
- The initial exact mouseover position is now retained as a bounded re-hover
  anchor. A fresh anchor for the committed GUID suppresses map fallback even
  during a temporary selection dropout, and dispatching any `OPEN_MAP` starts
  the 30-second skill-level reopen gate immediately.
- Focused approach, reacquisition, map-policy, execution-bookkeeping, and map
  discovery regressions: **89 passed**. Full suite: **1872 passed, 4 skipped,
  18 known baseline failures**; no new failure category was introduced. Status:
  **live failure diagnosed;
  follow-up fix offline-tested, pending process restart and user-operated live
  validation**. The running GUI predates this follow-up patch; no client input
  was taken over.

## 2026-09-29 — two-run validation: stale friendly-interaction gate

- The user completed two further supervised runs; the shorter second run
  (`20260929-121852-237-004`) is treated as the primary reproduction, per the
  user's direction. No client input was taken over during analysis.
- The second run spent 7.1 seconds across three `SEEK_VISUAL_CUE` attempts
  (`WORLD3D:173`, `192`, then `189`); two ended in `visual_track_lost` and one
  succeeded. Saved frames show that the later inspection regions covered the
  visible Lady Jaina/quest-marker area, so this was not solely random OpenCV
  proposal noise. Detector association remained native BoT-SORT (`ready`).
- At monotonic `69888.111`, the addon already exposed Lady Jaina as the exact
  selected, alive, non-attackable target. Nevertheless the proposal set held
  only `OPEN_MAP`, which then opened and closed successfully. The missing
  `INTERACT` was traced to `interacted_guids`: an interaction about 146 seconds
  earlier had recorded the empty quest signature `[]`, and the later run had
  the same serialized signature, so the NPC was treated as already handled
  indefinitely.
- Detailed quest telemetry also flickered between the active quest and an
  empty array during the longer run. Therefore a simple signature-change reset
  would be unsafe. Successful friendly interactions now record their monotonic
  time; an equal-signature gate absorbs short telemetry flicker but expires
  after 60 seconds, so it cannot become a permanent NPC blacklist.
- Focused gate/bookkeeping/agent/map regressions: **16 passed**. Broader
  quest/map/approach regressions: **206 passed**, with only the same two known
  baseline assertions from `test_agent_core.py`. Status: **live failure
  diagnosed; fix offline-tested, pending process restart and user-operated
  validation**. Any already-running GUI predates this patch.

## 2026-09-29 — Jaina approach re-hover latency

- In the user-operated PID 1468 run (`20260929-122659-198-002`), the initial
  search interval is not a clean tracker validation: the saved capture begins
  with the Codex window occluding most of the WoW client. The search was
  initialized from those non-game pixels and its committed UNKNOWN track later
  drifted onto the Bjorn Stouthands area after the client became visible.
- The later, manually repositioned Jaina interval is clean. `INSPECT` produced
  exact Jaina GUID `Creature-0-3767-2175-337081-156626-00003A8AB8`, `TARGET`
  selected it, and Retail explicitly reported that the character needed to be
  closer. `VISUAL_APPROACH` also received the fresh exact
  `CONFIRMED_MOUSEOVER_ANCHOR` for Jaina.
- The approach then issued the required identity `HOVER`, released movement,
  and failed after its hard-coded 0.85-second response deadline. In this live
  trace the next addon detail/mouseover sample arrived 1.48 seconds later, so
  the controller rejected the correct identity before the exporter could
  answer; no `MOVEFORWARD` command was issued.
- The bounded identity-response window is now 2.0 seconds. Movement remains
  stopped while waiting, and a fresh contradictory GUID still fails
  immediately. A regression reproduces the observed 1.48-second addon latency
  and verifies that exact Jaina confirmation resumes bounded forward motion.
- Focused visual-approach regressions: **35 passed**; combined affected-area
  regressions: **93 passed**. Full suite: **1874 passed, 4 skipped, 18 known
  baseline failures**; no new failure category was introduced. Status: **live
  failure diagnosed; fix offline-tested, pending GUI restart and user-operated
  live validation**. No client input was taken over.

### Pre-restart Ke-La run is not a validation of `bfaba5b`

- Capture `20260929-124143-382-002` began at 12:41:44, while commit `bfaba5b`
  was created at 12:42:14 and the already-running GUI had imported the older
  modules. The process therefore could not contain either the expiring
  friendly-interaction gate or the longer approach re-hover deadline.
- Jaina was already selected in the first saved frame and her quest marker was
  plainly visible. At monotonic `71255.986`, however, the old planner emitted
  only `SEEK_VISUAL_CUE`; it did not emit `INTERACT` for the selected Jaina.
  The search later hovered and authoritatively identified Ke-La (NPC 156612),
  after which the generic friendly-NPC path selected and repeatedly interacted
  with Ke-La. This is the expected downstream symptom of the stale permanent
  `interacted_guids` gate fixed by `bfaba5b`, not a post-fix regression.
- Status: **invalid for post-fix validation; fresh GUI restart required**.

### Fresh-GUI Ke-La reproduction: quest-cue attention lost to bare body

- The user immediately repeated the scenario with a fresh GUI in capture
  `20260929-124502-711-002`; this is a valid post-`bfaba5b` reproduction.
  The addon had no selected target at the beginning of the new attempt, so the
  Ke-La target frame visible in the first saved screenshot was stale UI state,
  not an authoritative target in the current telemetry.
- World3D did detect the visible Jaina evidence at the same time: learned
  overhead symbol `WORLD3D:9` at `(0.547, 0.783)`, learned humanoid
  `WORLD3D:7` at `(0.544, 0.680)`, and derived symbol-subject probe
  `WORLD3D:13` at `(0.536, 0.564)`. It also detected the unrelated Ke-La body
  as `WORLD3D:8` at `(0.266, 0.606)`.
- The derived Jaina probe's effective confidence was reduced to `.304` by the
  normal fusion reliability factors. `VisualSearchPlanningPolicy` required
  `.65` for a non-learned subject probe, so it discarded that stable supported
  symbol-subject group. The bare Ke-La learned-body proposal remained eligible
  and its priority-85 `INSPECT` beat the generic priority-78 visual search.
  Addon mouseover then correctly identified the hovered unit as Ke-La; the
  error was therefore attention/ranking before ground-truth handoff, not addon
  identity confusion and not a missing YOLO detection.
- Stable supported learned-glyph subject probes now use a `.24` observation
  threshold, rank ahead of bare subjects during quest discovery, and suppress
  competing generic WORLD3D inspections for that planning cycle. This remains
  attention evidence only; addon mouseover is still required to establish NPC
  identity or quest role.
- Focused and broader affected-area regressions: **64 passed**, then **219
  passed with the same two known `test_agent_core.py` baseline failures**.
  Full suite: **1875 passed, 4 skipped, 18 known baseline failures**; no new
  failure category was introduced. Status: **live failure diagnosed; ranking
  fix offline-tested, pending fresh GUI user validation**.

### Fresh-GUI Ke-La reproduction: top-cropped Jaina marker

- The next user-operated fresh-GUI run is capture
  `20260929-125134-516-002`. The earlier ranking fix did not activate in this
  run: all selected search proposals were bare, marker-free learned subjects.
  The addon later authoritatively identified the approached unit as Ke-La, so
  this was again attention before identity handoff rather than GUID confusion.
- The first saved frame shows Jaina at approximately `x=730..765,
  y=138..199` and her quest marker at `x=736..764, y=65..104`. The production
  learned detector was physically cropped to the heuristic scene rectangle
  beginning at `y=92`; most of the marker was never supplied to YOLO.
- Learned inference now has a separate user-defined visible region extending
  from `y=12` through the unobstructed lower world. Hard UI islands mask the
  addon telemetry block, right-side HUD, chat, action bar/microbar, player
  unit frame, and target unit frame. Heuristic CV retains its conservative
  `y=92..618` scene rectangle.
- A 640-pixel full scan is retained for the taller learned view. At 512 the
  exact frame kept the marker but dropped Jaina's small body below admission;
  at 640 the final hard-masked production TensorRT replay admitted both
  Jaina's humanoid body (`.31`, `732,139..768,200`) and overhead symbol
  (`.18`, `735,69..758,101`). Their geometry satisfies the existing symbol-above-body
  visual-group relation. This changes visibility, not semantic identity:
  addon hover confirmation remains mandatory.
- Focused scene/learned-detector/pipeline regressions: **49 passed**. The final
  full suite after the user-drawn hard-mask refinement was **1877 passed,
  4 skipped, 18 known baseline failures**; no new failure category was
  introduced. A fresh user-operated live run is still required. No client
  input was taken over.

### Long Jaina search: off-frame probe and invalid viewport coordinate

- The user-operated long run spans captures `20260929-131947-705-002` and
  `20260929-132212-521-003`. It reproduced alternating successful Jaina
  recognition, repeated camera rotation, recognition without approach until
  manual mouse hover, and eventual recovery after the user nudged the player.
  The user also abandoned the briefly accepted quest and returned to the
  starting position; that manual reset is not counted as agent completion.
- The addon did authoritatively identify Lady Jaina Proudmoore multiple times.
  The failure was therefore not solely missing detector training. One
  `WORLD3D_LOCAL_VIEW` entry published a derived subject probe with bbox
  `[692,504,782,629]` for a `892x502` frame and
  `raw_screen_center.y=1.682624`. The probe had been fabricated below a stable
  symbol already at the bottom edge. The canonical pipeline then normalised
  client-pixel detections against the narrower heuristic scene ROI even though
  learned detections now use the taller full view. That invalid geometry can
  drive seek/approach toward an impossible point and explains the repeated
  rotations and identity-reconfirmation losses in this run.
- Derived symbol-body probes are now clipped to the inferred current frame and
  omitted when fewer than 24 visible pixels remain below the symbol. The
  canonical track contract normalises client-pixel boxes against the complete
  client frame and rejects boxes whose centre is outside that frame. Exact
  `892x502` regressions cover both the expanded learned view and the observed
  off-frame bbox.
- The third-person local-player pixels remain observable. A likely local-avatar
  track is now assigned a supported attention identity containing the addon
  character name/GUID, marked non-inspectable, and excluded from active
  perception/seek proposals. This does not promote semantic type to a fact and
  does not suppress a separate overlapping NPC/mob box with an independently
  supported overhead relation. The Live Vision overlay receives the character
  name and renders the local box as `Vbmnm [SELF]`; independently anchored
  overlapping subjects retain their normal detector label.
- Focused affected-area regressions: **83 passed, 1 skipped**. Final full suite:
  **1882 passed, 4 skipped, 18 known baseline failures**; the temporary
  nineteenth failure was found and removed before handoff. Status: **live
  failure diagnosed; geometry and self-avatar
  handling offline-tested, pending fresh GUI user validation**. The client is
  in MANUAL and no client input was taken over.

### Follow-camera visual search control policy

- The user configured Retail to keep the camera following the character and
  requested that visual search rotate the character instead of independently
  dragging camera yaw. No new live input was authorized or performed for this
  change.
- Horizontal `SEEK_VISUAL_CUE` scan steps, UNKNOWN-cue reacquisition,
  committed visual-track reacquisition, `CAMERA_CONTROL` yaw intents, and the
  legacy `INSPECT camera_pan` path now issue bounded `TURNLEFT`/`TURNRIGHT`
  player-yaw pulses. Retail follow-camera is expected to rotate the view with
  the character. Vertical `LOOK_UP`/`LOOK_DOWN` and explicit recenter intents
  retain camera gestures because player yaw cannot express pitch.
- The shared verification path accepts an authoritative addon player
  orientation delta or supported World3D camera flow. Search remains bounded
  to four observation-gated pulses, keeps the existing movement watchdog and
  binding authority, and records `PLAYER_YAW_FOLLOW_CAMERA` in its snapshot.
- Focused affected-area regression after movement-lane wiring: **75 passed**,
  plus the same one known freshness baseline failure. Final full suite: **1885
  passed, 4 skipped, 18
  known baseline failures**; no new failure category. Status: **offline-tested,
  pending fresh-GUI user-operated follow-camera validation**. The running
  client was not controlled by the assistant.

### Torch false-positive received forward-movement authority

- The user-operated run started at `2026-09-29 13:39:59` and is preserved in
  capture `20260929-134029-231-002` plus
  `live-debug-20260929-133959.jsonl`. It loaded commit `1d67104` but predates
  the follow-camera commit. At `13:41:01`, the agent selected `WORLD3D:30`
  and issued two bounded `MOVEFORWARD` commands toward screen x `0.520`.
- The saved frame proves that coordinate belongs to the distant torch flame.
  YOLO supplied only `learned_symbol_like`; the visual-track layer then
  projected a synthetic `unknown_subject_probe` below it (`bbox
  419,134..509,259`). Active perception reported body geometry `0.0`, quest
  badge likeness `0.0`, and overhead specificity `0.0`, but the supported
  generic symbol/probe group was enough to receive the earlier visual-seek
  priority. This was a perception-to-control authorization defect, not a
  navmesh/route construction failure.
- A derived subject probe is now explicitly treated as an invented hover
  region rather than an observed body. `SEEK_VISUAL_CUE` immediately hovers
  such a probe at any apparent distance and cannot pass it to the forward
  visual servo first. Only fresh addon mouseover identity can complete that
  identification step. Real detected subject bodies retain the existing
  approach-then-hover behavior.
- Focused search and attention regressions: **34 passed**. Final full suite:
  **1887 passed, 4 skipped, the same 18 known baseline failures**; the two new
  tests cover the torch no-forward contract and successful fresh Jaina
  mouseover handoff. Status: **live failure diagnosed; authorization fix
  offline-tested, pending fresh-GUI user validation**. The client was left in
  MANUAL and no client input was taken over.

### Selected NPC track was not rebound after follow-camera yaw

- The user-operated fresh-GUI run beginning at `2026-09-29 14:01:22` is
  preserved in `output/live-debug/live-debug-20260929-140122.jsonl` and capture
  `output/agent/pid-1468/live-captures/20260929-140156-718-002`. The addon
  correctly established Jaina Proudmoore as the exact selected GUID. After the
  interaction produced no response, visual approach started on `WORLD3D:26`
  near screen x `0.084`.
- Player yaw with follow-camera moved Jaina across the frame. The old track
  became `LOST_TEMPORARY`, while the controller continued probing the stale
  left-edge position. Jaina was visibly present at the new right-side position,
  but the visual track was never rebound to the already-authoritative addon
  GUID. The approach therefore failed identity reconfirmation and the planner
  safely fell back to `WAIT`, because coordinate-free `REACH_OBJECT` is
  forbidden. Manual mouse hover happened to create the missing fresh anchor,
  which explains the long-standing apparent hover dependency.
- During occluded/lost recovery the controller can now rank a plausible fresh
  WORLD3D subject track and hover it while remaining stationary. It adopts that
  replacement track only when the fresh addon mouseover reports the same exact
  selected GUID. A candidate resolving to Kee-La or another GUID is rejected
  non-terminally and cannot receive movement authority; another candidate may
  then be tested. Direct periodic checks of an already-bound track retain their
  stricter terminal failure behavior.
- Focused approach/planning regressions: **65 passed**. Final full suite:
  **1889 passed, 4 skipped, the same 18 known baseline failures**; no new
  failure category. Status: **live failure diagnosed; GUID-gated visual-track
  rebinding offline-tested, pending fresh-GUI user validation**. The detector's
  high-refresh latest-frame path is retained, and no client input was taken
  over by the assistant.

### Learned overhead symbol fabricated a large subject bbox

- In the user-operated Live Vision frame reported at `2026-09-29 14:56`, the
  YOLO `overhead_symbol_like` detection on a distant torch was accompanied by
  a large white `UNKNOWN` bbox below it. The large bbox was not detector
  output: `VisualTrackManager._subject_probes()` manufactured a 72--104 by
  96--132 pixel `unknown_subject_probe` below every stable isolated symbol.
  This is the same fallback mechanism that created the earlier misleading
  `WORLD3D:122` hover candidate.
- Learned/YOLO symbol observations no longer create a synthetic subject probe.
  The real symbol track remains available as UNKNOWN evidence, but a real
  learned `humanoid_unit_like` or `creature_unit_like` detection is now needed
  before a subject bbox and symbol/body group can exist. The legacy heuristic
  nameplate path retains its bounded fallback because it has no trained body
  detector.
- When both a legacy derived probe and a real body-sized detector observation
  are present, relation grouping now selects the real body. A derived probe is
  preferred only over a tiny colour fragment that cannot represent a body.
- Focused perception/search regressions: **49 passed, 1 skipped**. Full suite:
  **1891 passed, 4 skipped, the same 18 known baseline failures**; the two new
  regressions cover suppression of learned-symbol probes and real-body
  precedence. Status: **live failure diagnosed; fix offline-tested, pending a
  fresh-GUI user validation**. No client input was taken over by the assistant.

### Empty detector refresh caused whole-overlay bbox flicker

- The user reported that every Live Vision bbox could disappear together and
  return almost immediately. Code-path inspection confirmed that a completed
  YOLO refresh with zero detections called `CpuPatchTracker.anchor(..., ())`,
  clearing every fast track at once. The empty batch was also published to the
  agent, so this was not merely an overlay rendering artifact.
- Detector misses now use bounded temporal hysteresis. Existing patch tracks
  survive up to eight consecutive empty detector refreshes (configurable with
  `AIPC_WORLD3D_EMPTY_REFRESH_GRACE`), first as `OCCLUDED` and then as
  `LOST_TEMPORARY`. These tracking-only predictions remain visible but are
  explicitly non-inspectable and cannot gain movement/interaction authority.
  A real detection resets the miss streak; exhausting the bounded grace still
  removes the tracks.
- Detector anchors also apply an adaptive EMA to bbox coordinates and public
  confidence (`bbox alpha 0.75`, `confidence alpha 0.35`). A large position or
  scale jump bypasses EMA so a camera turn or doubtful reassociation cannot
  leave an actionable trailing box. Both alphas are environment-configurable.
- Focused World3D/perception/Live Vision regressions: **44 passed, 1 skipped**.
  Full suite: **1895 passed, 4 skipped, the same 18 known baseline failures**;
  no new failure category. Status: **root cause confirmed and offline-tested;
  pending fresh-GUI user validation**. No client input was taken over by the
  assistant.

## 2026-09-30 — 3-class unit detector v8 wired into runtime (offline)

- New runtime model `models/world3d_units_3class_v8` (`.engine` 640 and
  `_512.engine` TensorRT FP16, `.pt` fallback). Taxonomy: `creature_unit_like`
  (humanoid, creature and corpse merged), `quest_object_outline_like`,
  `overhead_symbol_like`; world-object and entrance classes were dropped.
  Trained 120 epochs from v7 on 4072 user-reviewed frames
  (`datasets/world3d_units_3class_v8_all_reviewed`, best epoch 37).
- Held-out test split (489 frames, same frames for all models), AP50 /
  recall at the 0.15 runtime gate: unit v4 .357/.47, v8 .441/.60; quest outline
  v4 .371/.45, v8 .384/.45; overhead symbol v4 .218/.32, v8 .368/.60. Many v8
  "false positives" at >=0.4 were visually confirmed unlabeled distant units.
- Measured TensorRT latency on this RTX 2050: 7.0 ms (640), 5.6 ms (512).
- Runtime changes: default model names switched to v8; the merged unit class
  keeps the former combined subject budget (8); a TALK-objective movement
  handoff no longer requires the retired `humanoid_unit_like` label.
- Full suite: **1908 passed, 4 skipped, the same 18 known baseline failures**.
  Status: **offline-tested, pending fresh-GUI user-operated live validation**.
  Rollback: set `AIPC_WORLD3D_MODEL` to
  `models/world3d_annotation_assist_combined_2794_v4.engine` before launch.

### 2026-09-30 08:13 — v8 first live run: unresponsive Kee-La interaction loop

- User-operated PID 17636 run with the v8 unit model
  (`live-debug-20260930-081019.jsonl`, capture `20260930-081318-822-002`).
  No quest was active and Lady Jaina was not in the initial view. World3D
  correctly detected the only visible unit, which addon hover identified as
  Kee-La (NPC 156612). Addon mouseover carried no quest role or tooltip for
  either Kee-La or Jaina, so only the overhead symbol can distinguish a quest
  giver visually.
- The generic friendly path targeted Kee-La and issued INTERACT three times
  (08:13:24, 08:13:33, 08:13:50), each `no_response`. Only successful
  interactions fed the `interacted_guids` gate, so the unresponsive NPC stayed
  eligible. Jaina was found at 08:14:03; two VISUAL_APPROACH attempts then
  ended in `visual_track_lost_identity_reconfirmation_missing` before the user
  returned to MANUAL.
- Fix: a friendly INTERACT failing with `no_response` records the GUID with
  the quest signature; for 300 s at the same signature it receives neither
  INTERACT nor mouseover TARGET hand-off. A changed quest signature clears it.
- Full suite: **1910 passed, 4 skipped, the same 18 known baseline failures**.
  Status: **live failure diagnosed; fix offline-tested, pending fresh-GUI
  user validation**. The Jaina approach identity-reconfirmation failure
  remains open.

### 2026-09-30 08:21 — v8 second live run: main-loop starvation, spinning in place

- User-operated run `live-debug-20260930-082106.jsonl`: the character turned
  in place and never approached. 47 of 147 FULL_AI status samples were
  `telemetry_suspended_waiting_for_stable_recovery`. The pixel strip source
  kept publishing at ~40 Hz, but the main thread reported
  `last_payload_ago` up to 14 s, World3D perception ran at only 0.9--1.6 Hz and
  the detector at 0.6--1.5 Hz (v8 TensorRT inference itself is 7 ms), and at
  08:21:58 the strip source itself dropped to 0 Hz. This is the known GIL
  starvation shape from 2026-09-22.
- The launchers in this project folder never set `AIPC_CAPTURE_PROCESS=1`, so
  the process-based screen grab (opt-in) was off. `START_AGENT.bat`,
  `START_AGENT_DXGI.bat` and `START_AGENT_LIVE_VISION.bat` now enable it
  unless the variable is already defined.
- Status: **launcher configuration fixed, pending fresh-GUI user validation**.
  If stalls persist with process capture enabled, the next candidates are the
  110--200 ms `status_write` per tick and moving World3D perception out of the
  agent process.

### 2026-09-30 08:36 — profiled main-loop stall: WORLD3D_LOCAL_VIEW SQLite writes

- With `AIPC_CAPTURE_PROCESS=1` active (08:29 run) World3D improved from ~1 Hz
  to a 6 Hz median, but 55 of 229 FULL_AI samples were still telemetry
  suspensions. A new opt-out in-process profiler
  (`wowbot.diagnostics.thread_profiler`, `thread_profile_history.jsonl`,
  `AIPC_THREAD_PROFILE=0` disables it) showed the Python process pinned at one
  core (98--108 %): agent 27 %, pixel sensor 16 %, perception pump 10 %,
  vision workers 15 %; the sampler itself was delayed up to 510 ms.
- 552 of 1024 agent-thread samples were inside the per-tick SQLite commit.
  `agent_memory.sqlite3` held 3272 `WORLD3D_LOCAL_VIEW` rows averaging 94 KB
  (raw detector batch, scene geometry, traversability): 316 MB in 25 minutes.
  `WORLD3D` was already ephemeral, `WORLD3D_LOCAL_VIEW` was not. Offline the
  same 400 KB status JSON serialises in 4 ms versus 138 ms live, confirming
  the status writer was a victim of contention rather than the cause.
- Fix: `WORLD3D_LOCAL_VIEW` joins `EPHEMERAL_OBSERVATION_SOURCES`; it is still
  ingested by the WorldModel but no longer appended to SQLite.
- Full suite: **1911 passed, 4 skipped, the same 18 known baseline failures**.
  Status: **root cause profiled live; fix offline-tested, pending fresh-GUI
  user validation**.

### 2026-09-30 08:40 — stall fix confirmed; duplicate self track kept inspectable

- Run `live-debug-20260930-084051.jsonl` (START_AGENT_DXGI, process capture,
  WORLD3D_LOCAL_VIEW no longer persisted): **0 of 110 FULL_AI samples stale**
  (previously 55/229), World3D perception median 18 Hz (previously 6 Hz, then
  1 Hz), Python process CPU 54 % of one core (previously pinned at ~100 %).
  Live-confirms the SQLite write-volume diagnosis.
- Kee-La received one `no_response` INTERACT and was not re-interacted:
  live-confirms the unresponsive-NPC gate.
- The cursor then sat on the player's own character for ~30 s during
  SEEK_VISUAL_CUE. Two tracks covered the player: WORLD3D:83 was correctly
  named SELF_PLAYER, but duplicate WORLD3D:41 (same bbox) stayed inspectable
  because a learned symbol WORLD3D:78 inside the top of the body box
  (y 236--268 vs body top 231, probably head/hair) formed a SUPPORTED ABOVE
  group, which the self projection treated as independent NPC evidence.
- Fix: in `_project_self_player_tracks` an ABOVE/group symbol only exempts a
  self-hinted box when the symbol ends at or above the top 12 % band of the
  box. A real overhead marker above a unit standing behind the player keeps
  that unit inspectable. Full suite: **1912 passed, 4 skipped, the same 18
  known baseline failures**. Status: **offline-tested, pending live run**.
- Open: SEEK kept rotating without locating Lady Jaina in this run.

### 2026-09-30 08:50 — quest symbol bound to a coasting duplicate body

- Run `live-debug-20260930-085035.jsonl`, capture `20260930-085054-257-002`:
  Lady Jaina and her quest marker were straight ahead at 08:50:55 (v8 symbol
  .64). The agent then turned left away from her and later targeted Kee-La.
- Jaina's body had two alternating tracks (WORLD3D:2 and WORLD3D:8). The
  symbol-above-subject relation chose the nearer body without regard to
  lifecycle, so the group sat on WORLD3D:8 while it was LOST_TEMPORARY and the
  ACTIVE WORLD3D:2 had no group. With no quest-cue target the planner fell back
  to the persistent sector search and turned away.
- Fix: `VisualTrackManager._relations` ranks live bodies (ACTIVE/STABLE/
  TENTATIVE/REACQUIRE_CANDIDATE) ahead of OCCLUDED and then LOST tracks before
  size and distance. Regression uses the live coordinates. Full suite: **1914
  passed, 4 skipped, the same 18 known baseline failures**. Status:
  **offline-tested, pending live run**. Not changed (per user): suppression of
  searching/incidental NPC targeting while a quest cue is visible.

### 2026-09-30 08:57 — pixel-strip decode pinned the sensor thread

- Run `live-debug-20260930-085737.jsonl`: 73 of 194 FULL_AI samples stale
  again. The thread profiler showed `aipc-pixel-sensor` at 80--92 % of a core
  for most 5 s windows (previous run 12.5 %), sampler wake-up gaps up to
  826 ms; hot stacks were the per-cell Python `_decode_grid` reached from the
  legacy rediscovery loop in `decode_payload_from_bgra`. Offline, one failing
  full discovery on an 892x502 frame took 200--280 ms.
- Fix: `_decode_grid` classifies all needed cells in one numpy pass (same
  rounding and colour rules); a failed decode at the cached geometry whose
  8-cell header is still present is reported as `torn_frame` and keeps the
  cache instead of triggering rediscovery; a moved strip (header absent) is
  still rediscovered immediately. Synthetic 892x502, 840-byte payload:
  cached decode 0.30 ms, torn frame 0.35 ms, failing full search 38 ms.
- Full suite: **1915 passed, 4 skipped, the same 18 known baseline failures**.
  Status: **offline-tested, pending live run**. The late Jaina selection in
  this run is not yet analysed.

### 2026-09-30 09:04 / 09:10 — track-loss rebinding; unresponsive gate wrongly blocked Jaina

- 09:04 run (`live-debug-20260930-090426.jsonl`, 0 stale, World3D 20.7 Hz):
  about 25 SEEK_VISUAL_CUE attempts ended in `visual_track_lost` within 1--3 s,
  and a Jaina VISUAL_APPROACH ended in
  `visual_track_lost_identity_reconfirmation_missing`. Cause: the committed
  track of an NPC with two alternating tracks coasted (OCCLUDED/LOST) while its
  live twin stood in the same place; the approach waited on the coasting track
  and SEEK had no rebinding at all.
  Fix: `VisualApproachController._live_continuation` adopts an unambiguous live
  WORLD3D subject box within 0.12 of the coasting/last real position with a
  0.5--2x height ratio (ambiguous pairs within 0.035 and SELF_PLAYER boxes are
  rejected), for SEEK and GUID approaches alike; GUID hover rechecks remain.
- 09:10 run (`live-debug-20260930-091038.jsonl`, 0 stale of 346): the user
  selected Lady Jaina; Retail reported "You need to be closer" at ~09:11:22,
  and a later silent INTERACT at 09:12:09 was recorded as `no_response`. The
  unresponsive-NPC gate (added this morning for Kee-La) then blocked her for
  300 s: 69 telemetry samples show her exact mouseover without a TARGET
  hand-off, and the planner alternated WAIT / SEEK_VISUAL_CUE.
  Fix: a silent INTERACT is not gated when that GUID had a range error in the
  last 120 s (`QuestDomain.out_of_range_at`), when a range error is current,
  when the target has a quest role, or when its anchored visual track has a
  SUPPORTED symbol group; the gate window is reduced to 60 s.
- Full suite: **1918 passed, 4 skipped, the same 18 known baseline failures**.
  Status: **live failure diagnosed; fixes offline-tested, pending live run**.

### 2026-09-30 — stable World3D presentation objects (offline)

- User request: raw lifecycle states (OCCLUDED/LOST/REACQUIRE) and id churn
  must stay internal; boxes should remain drawn and ACTIVE, with the raw facts
  recorded behind them.
- New `wowbot.agent.stable_objects.StableObjectLayer`, applied by
  `VisualTrackManager.update("WORLD3D", ...)` before symbol/subject relations,
  so planner, relations, WorldModel and the Live Vision overlay all see it:
  one object per visual phenomenon keeps the founding raw id; a new raw id
  whose box overlaps an object (IoU >= .35 or 75 % containment, height ratio
  <= 2.5, unambiguous) joins it; two boxes observed in the same frame merge
  only when IoU >= .6; the raw layer stays authoritative for ids it kept.
  Established objects (3+ live updates) are reported ACTIVE with an EMA-
  smoothed box (snap on large jumps) for 3 s while the image patch tracker
  still follows them and 1.5 s during a blind velocity coast; fresh
  candidates keep their raw lifecycle; memberless objects are not drawn.
  Logic fields: `raw_lifecycle`, `coasting`, `coasting_seconds`,
  `presentation_hold`, `raw_track_ids`, `duplicate_raw_tracks`; inspection
  authority on a coasting box expires after 0.6 s. Perception diagnostics
  expose `stable_objects` counters.
- Symbol relation now prefers the largest live body in the narrow window
  below the marker (live frame 08:50:55: WORLD3D:8 was Jaina's staff tip,
  WORLD3D:2 her body).
- Replay of today's recorded WORLD3D candidate streams (telemetry, ~2 Hz):
  established-box live->lost flips 19->7 and 90->55 (12->13 in the spinning
  09:04 run); symbols with a live grouped body 9->24 and 170->231, with a
  lost grouped body 16->10 and 108->69. Most new raw ids were genuinely new
  scene content while spinning, not churn. Layer cost: 0.13 ms median,
  1.3 ms max per update.
- Full suite: **1927 passed, 4 skipped, the same 18 known baseline failures**.
  Status: **offline-tested and replayed, pending fresh-GUI live run**.

### 2026-09-30 — loop-rate work toward >= 25-30 Hz (offline)

- Measured in the 09:10 run: captured frames 32 Hz, fresh FAST strip packets
  25 Hz, World3D perception/tracker 22.5 Hz, detector 13 Hz, but the agent
  consumed FAST state at only 10 Hz and fast control ran at 12 Hz (target
  40 Hz) because one agent step took 70 ms median / 218 ms p95. Brain 5.7 Hz
  (acceptable per user). Profile of the agent thread: 45 % in the per-step
  SQLite commit, ~20 % in `entity_memory.recognize_visual` (new connection
  and up to three queries per candidate per step), 10 % relation flush.
- Changes: `AgentMemory` optional deferred commit (savepoint per scope, one
  commit per `AIPC_MEMORY_COMMIT_SECONDS`, default 1.0 in the runtime),
  background PASSIVE WAL checkpoints on a separate connection
  (`AIPC_MEMORY_CHECKPOINT_SECONDS`, 5.0; auto-checkpoint off on the agent
  connection), relation flush at most every `AIPC_MEMORY_RELATION_FLUSH_SECONDS`
  (1.0), DB size via PRAGMA instead of `Path.stat()` (176-282 ms per call on
  the live DB); recognition results cached per visual signature for 1 s;
  `build_visual_signature` uses OpenCV reductions (bit-identical signature ids
  on 2000 real crops, 0.60 -> 0.23 ms per call, GIL released).
- Offline replay of 300 live states on a copy of the 384 MB live DB: slow
  ticks (> 40 ms) averaged 99 ms before and 64 ms after; p99 277 -> 75-157 ms
  depending on run noise; median ~10 ms. Remaining slow ticks coincide with
  full paged STATE ingestion (deep copies, JSON, observation inserts).
- Full suite: **1930 passed, 4 skipped, the same 18 known baseline failures**.
  Status: **offline-measured, pending live run with the thread profiler**.
  Note: FAST telemetry cannot exceed the WoW client frame rate (captured
  32 Hz in this run).

### 2026-09-30 10:01 run and memory write-behind (offline)

- Run `live-debug-20260930-100135.jsonl` (after deferred commit, background
  WAL checkpoint, relation-flush throttle, recognition cache, OpenCV
  signatures): fast control 12 -> 21 Hz, FAST state consumed 10 -> 14.5 Hz,
  agent step 70/218 -> 30/98 ms (median/p95), 0 stale samples. The WoW client
  delivered only ~28 new frames/s. Remaining agent-thread cost: per-step
  observation inserts (30 %) and relation flushes (16 %).
- `AgentMemory(async_writes=True)` (runtime default, `AIPC_MEMORY_ASYNC_WRITES=0`
  disables): observation and relation appends are enqueued and written by a
  daemon writer thread in per-item transactions; readers of those tables,
  hydration, consolidation, `commit_pending` and `close` drain the queue first.
  SQLite `cache_size` 32 MB in the runtime. Offline tests and replay remain
  synchronous.

### 2026-09-30 — capture-driven YOLO feed (offline)

- Problem (user analysis, confirmed in code): the YOLO process only received a
  frame when World3D's own cycle had consumed the previous result
  (`World3DPerceptionV3.process` submit/consume), so ~30-47 captured frames/s
  produced 10-13 detector refreshes.
- New `wowbot.vision.world3d.capture_yolo_feed`: when the process capture ring
  exists (`AIPC_CAPTURE_PROCESS=1`, launcher default) and
  `AIPC_YOLO_CAPTURE_FEED` is not 0, a spawned feed process attaches to the
  capture ring as an extra reader, runs the unchanged `LearnedWorldDetector`
  policy (same ROI, hard UI masks, foveal/full sampling, class gates) on the
  newest frame, and publishes into a latest-only mailbox, capped by
  `AIPC_YOLO_MAX_HZ` (default 30, GPU shared with the client). World3D V3 only
  polls the newest finished result and anchors it on the exact frame YOLO saw
  (`ProcessCaptureClient.frame_for_id`, last 16 frames); it never submits or
  waits. Without a capture process the former request/response path remains.
- Capture ring header gained `frame_id`, advanced only by real frame writes.
  Status-only updates (120 Hz `no_new_frame`) previously advanced the header
  sequence and replaced the `captured` status, so a slow reader could miss a
  frame and two processes could not agree on frame identity.
- End-to-end offline benchmark with the v8 TensorRT engines, a 55 Hz real-
  screenshot writer and a 25 Hz consumer: feed ran at **52.7 Hz** uncapped
  (independent of the consumer), capture-to-consume latency p50 30 ms / p90
  42 ms. Diagnostics: `detector.cadence_mode = CAPTURE_DRIVEN_FEED`,
  `detector.feed.inference_hz`, `consumed_hz`, latency percentiles.
- Full suite: **1932 passed, 4 skipped, the same 18 known baseline failures**.
  Status: **offline end-to-end benchmarked, pending live run**.

### 2026-09-30 12:15–12:48 — capture feed live, refresh cost, association in feed

- 12:15 run (feed, Live Vision on): Live Vision "view/source" and World3D fell to
  ~10–14 Hz while telemetry streamed (32 Hz before streaming). Cause measured:
  98 % of World3D frames became detector refreshes (42 % before), and a refresh
  cost 31 ms live (19 ms offline), of which **12.5 ms was BoT-SORT GMC**
  (Ultralytics sparse optical flow: full-frame gray of a strided BGR view +
  400-corner Lucas-Kanade). Visual signatures also ran on every refresh.
  Main-process thread CPU summed to ~96–103 % of one core, so the GIL was saturated.
- User observation (confirmed in code): association ran only on results
  World3D happened to take (10–16 Hz), so identities broke during turns.
- Changes (offline-tested):
  - `_PrescaledTranslationGMC`: BoT-SORT camera motion from sub-pixel
    `cv2.phaseCorrelate` on V2's existing quarter-resolution gray (~1 ms).
    Synthetic shifts: p90 error 2.5 px. On a panning sequence it produced
    **identical track ids** to the original sparseOptFlow (48 ids / 236
    observations at 27 Hz; no GMC: 71). Offline V3 refresh cost 19.4 -> 4.1 ms.
  - The feed process now runs YOLO -> V2 -> BoT-SORT on **every** YOLO
    result; World3D only anchors/propagates the newest tracked result.
    Generation counter: a World3D reset resets the feed's V2/tracker, and
    old-generation results are discarded.
  - Visual signatures capped at `AIPC_VISUAL_SIGNATURE_HZ` (default 12,
    the former refresh cadence).
- 12:46 run (new code): feed YOLO+V2+BoT-SORT at **27.1 Hz**, association
  4.3 ms per frame in the feed process, phaseCorrelate GMC active. MANUAL:
  World3D 24–27 Hz, refresh ~7 ms. FULL_AI: the agent thread used ~47 % of the
  GIL and World3D fell to 12–15 Hz (agent steps 40–200 ms). **Open.**
- **Open:** the feed generation reached 28 in about a minute. Every perception
  context reset clears the feed tracker, the visual tracks and the stable
  object layer, so identities restart. The cause is not determinable from the
  logs; `vision_diagnostics.world.context_resets` and
  `context_reset_reasons` now record which key changed.
- Suite: 1934 passed, 4 skipped, same 18 baseline failures.

### 2026-09-30 12:59 and 13:07 FULL_AI runs (feed association live)

- 12:59 run: 36 resets were recorded, but only the last 12 kept their cause:
  - `world_map_open` flicker (6 flips in 0.7 s around map open/close; FAST
    says open while an older full STATE snapshot says closed, and
    `_apply_full` replaces addon_state wholesale);
  - quest UI open/close;
  - minimap geometry None -> values.
  The cause of the first 24 is unknown (the user notes that no map was
  opened in the MANUAL part).
- 13:07 run: 8 resets, all explained (initial, session/character/map load,
  2 × map open/close, 1 × quest UI open/close); no flicker.
  - FULL_AI median: World3D 18.7 Hz (was 12–15), detector 14.6 Hz,
    fast control 21.6 Hz, step 30.8 ms.
  - Jaina quest accepted, but again only via an API-identified mouseover
    TARGET after SEEK_VISUAL_CUE failed repeatedly with `visual_track_lost`
    and no reset in between. SEEK targeted WORLD3D_21, 45, 91, 153, 182,
    193, 231, 268, 167, each ending in TARGET_NOT_FOUND. Upstream feed ids
    reached 3807 and public ids 343 in about 4 minutes.
  - The Murloc Watershaper fight ended with `combat_timeout`.
- The live-debug summary now carries `context_resets`/`context_reset_fields`/
  `context_reset_last`, a compact WORLD3D public-track list (`world_tracks`)
  and the `vision_seek` target track. The earlier monitor edit was never
  applied because a failed `grep` stopped the command chain.
- **Open:** why SEEK's public track disappears; the FAST-vs-STATE
  `world_map_open` flicker in the addon reducer.

### 2026-09-30 13:15–13:41 — identity churn root causes (offline, from live data)

- Live trace (13:15 run): SEEK targets repeatedly vanished (`visual_track_lost`).
  - Upstream feed ids were replaced for most tracks even with a still camera
    (WAIT, constant yaw).
  - All tracks were re-IDed at once during a SEEK camera turn.
- Cause 1, alternating FULL/FOVEAL detector crops:
  - The two crops return different object sets. Units outside the fovea
    vanish; distant units appear only in the fovea.
  - BoT-SORT confirms a new track only on the next frame, so full-frame-only
    objects never confirm.
  - Repeating one live frame 60× gave 20–54 ids; the full frame on every
    frame keeps every unit's id for 60/60 frames.
  - The feed now defaults to a full-frame scan
    (`AIPC_YOLO_FEED_ADAPTIVE_SAMPLING=1` re-enables the fovea).
- Cause 2, BoT-SORT `fuse_score=True`:
  - A match requires IoU × score ≥ .15. Admitted subject scores are
    ~.15–.35, so any jitter or motion re-IDed the object, and weak symbols
    could never re-match.
  - The new feed association trace (`feed_association_trace.jsonl`,
    13:29 run, 9860 frames) was replayed with the recorded warps. The replay
    reproduces the live id count exactly (15205 vs 15204 recorded).
  - With `fuse_score=False`: **1459 ids** (2079/min -> 199/min), 21.6 vs
    2.1 observations per id. This is now the default (`score_fusion` in
    diagnostics).
  - `new_track_thresh=.2` would give 130/min but would drop weak distant
    symbols from native tracks, so it was not adopted.
- 13:38 "why doesn't it approach Jaina" (screenshot; tracks 128 symbol and
  136 unit ACTIVE with stable ids for more than 10 s):
  1. The game target was still Kee-La (INTERACT no_response).
  2. Hover over Jaina succeeded (quality 1.0).
  3. TARGET returned IDENTITY_UNCERTAIN.
  4. INTERACT was attempted on the Jaina GUID without an approach and got
     NO_RESPONSE after 0.2 s.
  5. WAIT/INSPECT looped, and INSPECT failed with TELEMETRY_STALE 3×.
     REACH_OBJECT could not start without a proven position, and SEEK held a
     stale candidate (WORLD3D:87).
  6. Another player (Hexadoom) stood at Jaina's position.
  The unit box under the symbol may be that player's pet, not Jaina's body.
  **Open (planner).**
- Suite: 1936 passed, 4 skipped, same 18 baseline failures.

### 2026-09-30 13:40–13:56 — approach/interaction deadlocks, UI-flag debounce, holds

- 13:41 run: during OPEN_MAP the requested `world_map_open` flipped 28× in
  about 4 s (19–250 ms apart). The addon FAST/full paths use the same
  `IsShown()` and the sampled telemetry does not show it, so the root cause
  is unknown. Added a 0.25 s debounce for world_map/quest_ui/gossip flags in
  the perception context (`AIPC_PERCEPTION_UI_FLAG_DEBOUNCE`), plus
  `ui_flag_raw_flips` and the payload kind in reset reasons. 13:50 run:
  3 resets, 1 raw flip.
- 13:42 run chain:
  1. INTERACT on Jaina from far away gave `no_response` twice (Retail 12
     exports no NPC distance, and no range error came).
  2. VISUAL_APPROACH reached INTERACTION_READY.
  3. The kept range block re-proposed VISUAL_APPROACH for 20 s until
     `target_approach_budget_exhausted` switched to MANUAL.
- Fixes (offline):
  - A silent INTERACT without verified range creates a provisional range
    block, so approach comes first.
  - A successful VISUAL_APPROACH clears the block and the unresponsive
    verdict and records range evidence (`interaction_range.py`, 30 s).
  - "Unresponsive" is recorded only after verified range.
- 13:55 run (screenshot, Jaina with '!' visible, agent in WAIT):
  - Manually selected target, no fresh screen anchor, so the range block
    produced WAIT "REACH_OBJECT nem indulhat…" at priority 100, which vetoed
    SEEK and INSPECT (the deadlock known since 2026-09-12). It is now at
    priority 20.
  - Jaina's box was 8.3 % tall and the INSPECT scale floor was 9 %; a subject
    under a SUPPORTED overhead symbol may now be hovered down to 5 %.
  - These two have no dedicated unit test yet.
- User observation: during camera turns, boxes slide off their subjects and
  vanish late. Cause: the StableObjectLayer presentation hold (1.5 s / 3 s)
  keeps held boxes that are not camera-compensated. Runtime holds are now
  0.5 s / 1.0 s (`AIPC_STABLE_HOLD_SECONDS`,
  `AIPC_STABLE_TRACKED_HOLD_SECONDS`). Camera-compensated holds remain
  **open**.
- Suite: 1940 passed, 4 skipped, same 18 baseline failures.

### 2026-09-30 14:00–14:20 — re-identification, event-driven perception pump

- Orbit run (user circling an NPC): consecutive-frame association was fine
  (11356 kept vs 30 switched), but 73 % of new subject ids were short-gap
  re-births (median gap 0.25 s, displacement 0.61 box heights).
  - Added re-identification in the feed tracker: a new native track gets
    the id of a same-family subject that vanished less than 1.5 s ago,
    within 1.2 box heights of its GMC-compensated last position, with height
    ratio ≤ 1.7 and an unambiguous best match.
  - Replay of the orbit trace: subject ids 119 -> 77/min. Replay of the
    13:29 trace: 99 -> 62/min.
- Live Vision view/source was 15–22 Hz although V3 took about 2.6 ms.
  - Measured offline: a finished world job was harvested a median 12–14 ms
    late because pump ticks follow the Windows ~15.6 ms wait granularity
    (`timeBeginPeriod` had no effect).
  - Changes: the next frame is submitted before the previous one is
    post-processed, with the V3 diagnostics snapshot carried with the result.
    The pump wakes on job completion and on each new capture frame
    (`BufferedPixelSensor.frame_listeners`). GIL switch interval is 2 ms
    (`AIPC_GIL_SWITCH_INTERVAL`).
  - Offline harvest latency: 12–14 -> 0.09 ms. The live rate still needs
    measuring; `vision_diagnostics.world.cycle_ms` shows the breakdown.
- Live captures are now 1600×829 (the user raised the resolution).
- A second FULL_AI start finds Jaina directly because the game target and
  agent memory persist. The feed's TensorRT warm-up (~20 s) also leaves the
  first seconds of a fresh start without detections.
- Suite: 1942 passed, 4 skipped, same 18 baseline failures.

### 2026-09-30 17:22 run (1085×611 capture) — INTERACT verdict, public id stalls

- A fresh FULL_AI start found Jaina without SEEK: INSPECT, then mouseover
  TARGET, then VISUAL_APPROACH reached INTERACTION_READY. INTERACT still
  failed with `no_response` three times.
  - The journal shows the verdict 0.22–0.32 s after the key press, judged on
    the **pre-press observation itself** (observed_observation_id ==
    baseline). The cause: UI_WAIT 0.25 s plus an unknown-observation budget
    of 1.
  - Fix: a silent INTERACT fails only after `RESPONSE_TIMEOUT_SECONDS` = 1.2 s
    and a telemetry frame newer than the pre-press one (`AWAIT_RESPONSE`).
    Tests updated and added.
- User: the id stayed 166 while circling the NPC, but changed mainly when
  Live Vision stuttered.
  - The feed id survives intake stalls; the public layer did not. The
    StableObjectLayer now remembers feed (upstream) id -> object for 5 s and
    rebinds a re-created raw track to its object (`upstream_rebinds`).
    Spatial merging stays limited to the tracked-hold window.
- World3D published 15–16 Hz (MANUAL median 16.2, FULL_AI 15.1).
  - `cycle_ms`: queue 1.1, process 22.3, harvest latency 0.5 (event wake
    works), post 8.0.
  - V3 process time grew from about 2.6 ms at 906×510 to 17–22 ms at
    1085×611 under contention (agent 28 %, pixel sensor 17.5 %, pump 11 %
    of one core). **Open.**
- `world_map_open` raw flips: 24, but the debounce limited resets to 4
  legitimate ones.
- Suite: 1944 passed, 4 skipped, same 18 baseline failures.

### 2026-09-30 17:36 run (843×475) and option B (high resolution)

- Even at 843×475, World3D published only 13.9 Hz, although its cycle parts
  added up to ~15 ms (queue 1.0, process 11.5, harvest 0.6, post 2.3). The
  limit was the 22 ms time gate plus wake/GIL delays.
  - The world lane is now **frame-driven**: every new capture frame is
    submitted as soon as the previous job finished, and an identical frame
    is never reprocessed (`AIPC_WORLD3D_FRAME_DRIVEN`, default 1).
    `cycle_ms.submit_period` added.
  - Offline pump benchmark against a 42 Hz capture: 41 Hz, and 37 Hz with an
    agent-like CPU load (was 28–31).
- Pixel sensor: 12–21 % of one core in the main process. The capture
  process now decodes the AIPC5 strip next to the pixels, using the same
  1 s discovery throttle. The decoded packet travels in a per-slot payload
  area of the shared ring (`AIPC_CAPTURE_DECODE`, default 1).
- The user plans to play at 1600×900 or 1920×1080, so optimizations target
  high resolution. Live rates are not measured yet.
- Suite: see the next line of this file's history; no new failures.
- 17:39 run (843×475, frame-driven and capture-side decode loaded):
  - The pixel sensor thread fell 21 % -> 7.8 %, but World3D stayed at
    10–17 Hz: `cycle_ms` process 27.8, post 12.8, submit period 48.7 ms.
  - Offline, the identical per-frame world path costs a median 1.16 ms, so
    the live inflation (~25×) is waiting for the GIL (agent thread 31 %,
    pump 15 %; V3 re-acquires the GIL after many small numpy calls).
  - Mitigations: Live Vision now receives only the device name instead of
    the full V3 diagnostics each frame; GIL switch interval 0.5 ms.
  - If insufficient: run World3D perception (V3 + visual tracks) in its own
    process, as done for the YOLO feed. **Open.**
- Suite: 1946 passed, 4 skipped, same 18 baseline failures.
- User observation: Live Vision view/source is 50–60 Hz until YOLO labels
  appear, then falls to 10–17 Hz.
  - Cause: once tracks exist, the canonical evidence pipeline (scene
    quality, traversability, visual memory, nameplates, hard examples) ran
    on the pump thread 4×/s at 24 ms offline and 82 ms live, blocking
    harvest and submit.
  - Fix: in live (background) mode it now runs on its own single worker
    (`aipc-canonical`, latest-only, `AIPC_CANONICAL_ASYNC`). Live Vision uses
    the last finished canonical overlay. Offline/tests stay synchronous.
  - Suite: 1946 passed, 4 skipped, same 18 baseline failures. Not yet
    measured live.

### 2026-09-30 18:00 — World3D perception in its own process

- `perception_process.py`: the unchanged PerceptionWorker (V3, visual tracks,
  stable layer, canonical pipeline, minimap, Live Vision publication) runs in
  a spawned process.
  - It reads the capture ring itself and consumes the YOLO feed through a
    client endpoint (`CaptureDrivenYoloFeed.endpoint/from_endpoint`).
  - It publishes to the agent-owned Live Vision monitor through
    `LiveVisionPublisher`.
  - The agent-side `ProcessPerceptionWorker` exposes the same interface
    (latest-only request/result mailboxes).
  - Enabled when a capture process and a capture-driven feed exist
    (`AIPC_WORLD3D_PROCESS`, default 1).
- Offline end-to-end (real ring, fake feed, agent-like load in the main
  process): 39 Hz with 3 tracks and 31–38 Hz with 12 tracks at 1085×611.
- 17:58 live run (process mode): World3D world_perception_hz median 28.4
  (p10 18.7) in MANUAL, previously 15–18. The perception threads left the
  agent process profile.
  - `world3d_process_exited:3221225786` = STATUS_CONTROL_C_EXIT at GUI
    shutdown.
- Found afterwards: the World3D process, the feed worker and the capture
  client copied the whole frame on every ring poll even without a new frame
  (500 Hz × ~2.6 MB). All now check `peek_frame_id()` first.
- **Open:** canonical pipeline ~90 ms in the World3D process (deepcopy-heavy);
  the pixel sensor still at ~20 % in the agent process (check capture-side
  decode live).
- Suite: 1947 passed, 4 skipped, same 18 baseline failures.

### 2026-09-30 18:04–18:13 runs (World3D process live)

- World3D rates:
  - 18:04 run: MANUAL 36 Hz, FULL_AI 40.5 Hz (medians).
  - 18:12 run: MANUAL 63.6 Hz, FULL_AI 42.6 Hz (p10 22).
  - The agent loop in FULL_AI is 13–15 Hz (consumed FAST); earlier runs
    showed about 17–21. Not analysed yet.
- 18:04: after VISUAL_APPROACH reached Jaina, every proposal was filtered
  ("Minden jelenlegi részfeladat ideiglenesen unresolved") because the
  INTERACT task hit 3 failures (far no_response/out_of_range), which blocks
  it for 120 s.
  - Fix: GoalTask records the unit GUID, and a successful approach to that
    GUID reopens its INTERACT/TALK/QUEST_DIALOG tasks.
- User direction: with real-time vision, do not spend far INTERACTs to learn
  the range.
  - With active World3D, a selected friendly unit gets VISUAL_APPROACH first
    unless its own live box is interaction-sized or an approach verified the
    range within 30 s. Without World3D, interact-first is unchanged.
- 18:12: VISUAL_APPROACH declared INTERACTION_READY at box height ≥ .13, but
  the client answered `out_of_range` three times.
  - Fix: the client range error raises that GUID's required box height to
    1.3× its current height (cap .6) and clears the verified-range evidence.
    VISUAL_APPROACH carries the learned `ready_bbox_height`.
- Suite: 1950 passed, 4 skipped, same 18 baseline failures.

### 2026-09-30 18:16 run — INTERACT never opened a dialog

- Rates: World3D MANUAL 92 Hz / FULL_AI 59 Hz; agent fast control 24–30 Hz,
  consumed FAST 19–23 Hz.
- Session pid-3324: INTERACT had 0 successes (8 NO_RESPONSE, 5 OUT_OF_RANGE).
  F7 = INTERACTTARGET reaches the client (it answers "closer"), but next to
  Jaina INTERACT still failed within 0.4 s.
  - Root cause: `InteractSkill.begin()` stored `last_interact_at` (and the
    hover timers) from the telemetry sample clock, while `verify()` compares
    against the agent clock. A lagging telemetry timestamp made a fresh
    press look over 1.2 s old.
  - Fix: verify timers now use `attempt.started_at` (agent clock); hover
    freshness keeps the telemetry clock separately
    (`hover_sample_not_before`). Regression test added.
- The user saw the approach reach Jaina and end with
  `target_approach_budget_exhausted` (approach loop caused by the failing
  INTERACT).
- Suite: see the following entry; no new failures.

### 2026-09-30 18:26–18:41 — quest accepted; assistant-run bounded trials

- 18:26 user run: SEEK, INSPECT, TARGET, VISUAL_APPROACH, INTERACT
  (out_of_range), approach again, then **QUEST_DIALOG quest_dialog_verified;
  quest 55122 accepted** (quest_count 0 -> 1).
  - After the out_of_range the agent opened the World Map while Jaina and
    her '!' were visible, because the mouseover anchor had expired.
  - Fix: the selected unit's live World3D track (GUID-bound by the approach)
    now serves as the approach anchor (`WORLD3D_TARGET_TRACK`).
- The user authorised assistant-operated tests and left. Two bounded trials
  ran via `--auto-full-ai` with the new `AIPC_AUTO_FULL_AI_SECONDS`
  (150 s and 180 s; the runtime returns to MANUAL itself). Live Vision was
  off to keep WoW focused. After each trial the GUI was closed with
  WM_CLOSE and no agent/child process remained.
  - World3D: 94.7 and 99.3 Hz FULL_AI medians; agent fast control ~27 Hz.
  - No active quest (55122 no longer in the log), Jaina off-screen. The agent
    alternated WAIT ("több adat szükséges") and SEEK on "distant interesting"
    tracks. Those were weak, flickering detections (box 4–8 % of height,
    1–50 hits) that were lost on every camera turn (`visual_track_lost`).
  - Fixes:
    - FULL_AI arming waits for the World3D detector to produce refreshes
      (`waiting_for_world3d_detector`).
    - A goal-task block after 3 failures lasts 15 s for search skills
      (SEEK/INSPECT/OPEN_MAP/CLOSE_MAP) instead of 120 s.
  - **Open (design decision):**
    - SEEK candidate quality: require established tracks and prefer symbol
      groups.
    - Behaviour with no active quest: scan for quest symbols instead of
      chasing weak unknown boxes.
- Suite: 1951 passed, 4 skipped, same 18 baseline failures.

### 2026-09-30 evening / 2026-10-01 — camera-motion GMC, coasting, quest-giver search

- **Root cause of "boxes trail and vanish late on camera turns":** the PID 3324
  feed trace showed detections moving 20–100 px per frame during turns while
  the GMC warp stayed at ~1 px (95th percentile). Every turn frame spawned new
  BoT-SORT ids (65→67→68→73→75…).
  - The whole-frame phase correlation locked onto screen-fixed content: the
    AIPC pixel strip (top left, high contrast), HUD text, and the avatar the
    camera orbits.
  - Offline reproduction on real captures with a static strip/HUD: median
    error 24 px before the fix, 0.25 px after (p90 80 → 0.5 px).
- **Fix 1** (`world3d/camera_motion.py`): two world crops beside the avatar,
  below the strip and above the action bars. The candidate motions are
  similarity, mean, left, right and identity; the one that maps the most
  previous detections onto the current ones wins. BoT-SORT applies the
  resulting similarity warp. V2's own camera estimate uses the same crops.
  - The trace now records `gmc_hypothesis`, `gmc_scale` and `gmc_support`.
- **Live 20:22** (user-operated, first crop version): GMC saw turns (48 frames
  >15 px, max 99.6 px). In 40 of 54 turn frames it still returned 0, because
  running expands the image and the two crops disagree. This motivated the
  hypothesis selection above.
- **Fix 2** (`visual_tracks`): unmatched tracks coasted for 1.2 s on their own
  velocity only, without camera compensation (the visible LOST_TEMPORARY trail).
  - Coasting now adds the frame camera motion, and own velocity decays.
  - Presentation and identity are now separate: a lost box is drawn for 0.3 s
    (`AIPC_VISUAL_TRACK_PRESENT_GRACE`) but stays associable for 1.5 s
    (`AIPC_VISUAL_TRACK_LOST_GRACE`).
  - User feedback on an intermediate build (0.35 s total coast): "much
    better" visually, but reappearing subjects got new ids. The separation
    above addresses that; it is offline-tested only, **not yet live-validated**.
- **Quest-giver search with no active quest** (user: "Keressen quest givert";
  route from navmesh + map data):
  - Bare bodies without an overhead cue need ≥10 stable frames, ≥0.6 s age,
    no coasting and ≥4.5 % height before SEEK.
  - Symbol and body groups keep priority 86/87.
  - New last resort `FIND_QUEST_GIVER_AREA`, after World3D → world map → TDB
    role location. The navigation adapter walks a ring of 8 cells (28 yd);
    each cell must be contained by a walkable mmap polygon
    (`NavigationService.walkable_point`). It skips explored ground, retires a
    cell after 40 s, and allows at most 12 regions.
  - Arrival resets the camera sweep, so the loop is move → sweep → move.
  - The roaming MOVE yields only to quest-symbol or supported-group evidence.
  - Offline-tested only.
- A bounded trial at 18:56 never armed: the C: drive ran out of space
  (0 bytes). The user freed about 21 GB (old PID memory DBs, telemetry, temp
  files). The 20:16 trial ran 180 s and returned to MANUAL.
- **Open:**
  - The world-map/minimap CV sees nothing live. A separate task trains a YOLO
    model for map/minimap quest icons.
  - Live validation of fixes 1 and 2 and of quest-giver roaming.
- Suite: same 18 baseline failures, no new ones.
- **2026-10-01 06:13 (PID 4588, user-operated):** "GMC failed, falling back to
  identity" warnings. Every trace row had `warp: None`, so camera turns again
  produced new ids.
  - Cause: BoT-SORT passes `results_high.xyxy` as a numpy array and
    `select_by_detections` evaluated `boxes or ()`. The unit tests had used
    lists.
  - Fixed. The GMC now keeps the image-based hypothesis if detection
    selection ever fails.
  - Regression test drives the real BoT-SORT with numpy detections. It fails
    on the buggy version.
  - Live re-check pending.
- **2026-10-01 ~06:20 (PID 4588, user circling an NPC):** "started with id 9,
  now 302". The trace confirms GMC now measures turns (265 frames >15 px, max
  160 px; hypotheses: identity 919, left 324, right 186, similarity 174,
  mean 133).
  - **Main finding:** the own avatar (x .50, y .62, h .31, screen-fixed)
    changed feed id 12 times in 94 s (1→13→54→58→82→94→136→190→233→254→273→
    318→349). BoT-SORT applies the global camera warp to every track, but the
    camera orbits the avatar, so the avatar's prediction was pushed 50–100 px
    off its box.
    - There were also 1↔13 swaps (two near-identical boxes on the avatar,
      IoU ~.95).
    - Separately, 15 of 66 ended non-avatar subject tracks were re-born nearby
      within 0.5 s.
  - **Fix:** subject boxes in the avatar zone (|cx−.5W| < .06W, bottom
    > .55H, height > .15H) bypass BoT-SORT.
    - They get IoU-only association without camera warp, in the same public
      id space.
    - A box entering the zone inherits the id it was published with on the
      previous frame. Leaving the zone, the existing re-identification hands
      it back.
    - Kill switch: `AIPC_TRACK_SCREEN_ANCHORED=0`.
  - `reset()` now also clears the prescaled GMC's previous frame.
  - Regression test: avatar fixed while the world turns 24 px/frame; avatar
    and NPC each keep one id. It fails with the kill switch.
  - Live re-check pending; the remaining NPC re-births need a fresh trace
    after this fix.
- **2026-10-01 06:40 (PID 4588, user circling an NPC, screen-anchored build):**
  - The avatar stayed on one feed id (6: 1114 observations; 5: 97, the
    duplicate box on the avatar). Before: 12 ids in 94 s.
  - NPC re-births nearby within 0.5 s: 3 in 65 s (2.8/min), down from 15 in
    94 s (9.6/min).
  - Remaining case (49.49 s): during a fast turn one crop returned −58 px
    while the NPC box moved +66 px. No image hypothesis explained the box,
    so the track was re-born.
  - Fix: a shift measured between similar-size previous/current detections
    is also tried. It wins only by explaining strictly more boxes than every
    image hypothesis (17 of 1190 trace frames would change).
  - Live re-check pending.
- **2026-10-01 06:45–06:49 (PID 4588, 199 s, detection-shift build):**
  - Feed level: the avatar stayed on one id (5: 3966 observations). NPC
    re-births nearby within 0.5 s: 1.8/min. The `detections` hypothesis was
    chosen 25 times.
  - The user still saw "many new ids". These are World3D-layer ids.
    `live-debug` `world_tracks` showed upstream `V3:5` (the avatar) under
    WORLD3D:5 plus a series of short-lived second tracks
    (6, 8, 21, 25, 32, 39, 42, 47, 48, 60, 89, 101).
  - Two tracks carrying the same upstream id tied at cost 0 in the
    assignment, and the presentation alternated between them.
  - The real feed trace had only 1 frame of 6526 with a duplicate id (the
    avatar and a symbol box on the AIPC-strip edge both got 5). The creation
    of the remaining duplicates is **not fully explained**.
  - Fixes:
    - The feed enforces unique ids per frame; screen-anchored ids are claimed
      first, and the legacy-bridge id may not reuse an anchored id.
    - Anchored outputs carry `screen_anchored`. V3 patch propagation searches
      them around zero shift, and `visual_tracks` applies no camera term to
      them (prediction or coast).
    - UPSTREAM_EXACT ties prefer the current owner, then the older track.
    - An unmatched track whose upstream id is live on another track this
      frame is retired at once.
  - Tests reproduce the alternation (fails without the fix).
  - Live re-check pending, including the user's question whether viewing
    angle or position changes alone cause new ids.
- **2026-10-01 17:00–17:07 (PID 1712, 235 s, user-operated):**
  - No duplicate ids per frame (0 of 6086).
  - The avatar still changed id about 19 times. The detector did not see it in
    36 % of frames, with absences of 1–7 s, and anchored retention was 1 s.
  - NPC re-births nearby: 39 (10/min).
    - Most happened within ONE frame: the lost id was published on the
      previous frame, so it was not yet in `_recently_lost`.
    - 8 of 25 jumped 1.2–1.4 box heights (gate was 1.2).
  - Fixes:
    - Re-identification also considers ids published last frame and unmatched
      now (moved by this frame's warp). Anchored ids are excluded. Gate is
      now 1.5 box heights (unambiguous-best margin kept).
    - Anchored retention is 6 s (`AIPC_ANCHORED_RETENTION_SECONDS`), with a
      centre-distance fallback for reshaped boxes.
  - Test with a one-frame 1.3-height jump plus a 3 s avatar dropout fails on
    the old code.
  - Live Vision header now shows `draw`/`show` ms. Open question from the
    user: view 33 Hz vs source 50–60 Hz. The monitor runs BELOW_NORMAL with
    one OpenCV thread by design; the timing will show whether drawing,
    imshow or CPU priority is the limit.
- Suite: same 18 baseline failures.
- **Live Vision view rate** (user: view 33 Hz vs source 50–60 Hz):
  - The monitor loop woke on a 5 ms queue poll, a sleep and two blocking
    `waitKeyEx(1)` calls per displayed frame. At BELOW_NORMAL priority on a
    loaded host each wake-up can cost a scheduler quantum.
  - It is now event-driven: the only blocking wait is for the next frame (or
    the rate cap), and HighGUI events are pumped with the non-blocking
    `cv2.pollKey`.
  - Bench with all CPUs busy at normal priority and the consumer at
    BELOW_NORMAL: old loop 30.3–30.8 Hz; new loop 40.4 Hz with a 40.6 Hz
    source (the producer itself was CPU-limited in the bench).
  - Smoke-run of the real monitor process: alive throughout, exit code 0.
  - Priority deliberately unchanged. Live check pending.
- **2026-10-01 17:17 / 17:25 FULL_AI (PID 1712), Jaina approaches.** User:
  "very slow, stop-and-go, should arrive in 1-2 s"; "out of range, need to be
  closer"; later "arrived then overshot, still slow and choppy".
  - **Range errors were lost:** four "You need to be closer" (code 852) errors
    reached the agent as UI_ERROR_MESSAGE events. The flattened `ui_error`
    showed one, 3 s late, so INTERACT ended `no_response` and the per-GUID
    ready height was never learned.
    - Fixes: FAST keeps `ui_error_at/sequence/code`.
      `InteractionVerifier._range_event` maps a code-852 or "closer" event
      raised after the attempt began to OUT_OF_RANGE.
    - Live 17:25: INTERACT → `out_of_range` and the ready height was learned
      (0.13 → 0.186).
  - **Stop-and-go, cause 1:** the servo's periodic INTERACTTARGET range probe
    released the forward lease, and |error| > .22 turned in place.
    - Probe is now opt-in (`AIPC_VA_RANGE_PROBE=1`). Steering keeps W up to
      |error| .35 (arc).
  - **Stop-and-go, cause 2 (live 17:25):** identity re-hover every 3 forward
    updates. `identity_recheck_pending` lasted 2 s, there were 2–4 rechecks
    per approach, and one late addon sample failed the attempt
    (`visual_track_lost_identity_reconfirmation`).
    - One confirmation per bound track is now enough
      (`identity_confirmed_track_id`).
  - **Overshoot:** arrival required |error| ≤ .055, and the stop lagged one
    update while W was held.
    - INTERACT arrival now accepts |error| ≤ .20 and leads the stop by the
      current height growth.
  - Tests for each change fail on the old logic. Suite: same 18 baseline
    failures. Live re-check pending.
- **2026-10-01 17:31–17:35 FULL_AI (PID 1712, latest servo build, user-operated):**
  - Full chain observed live: SEEK → TARGET (mouseover API) → QUEST_DIALOG
    accepted 55122 "Murloc Mania" from Jaina (quest_dialog_verified) →
    navmesh MOVE to the quest area. The MOVE was cancelled by
    `quest_route_visual_cue_observed`.
  - Then SEEK/INSPECT/TARGET on Murloc Spearhunter → COMBAT → LOOT attempt.
    Objective still 0/6 First Aid Kits at the end.
  - The user judged the result "quite nice".
  - Remaining issues:
    - VISUAL_APPROACH still failed twice on the *first* identity re-hover
      (`visual_track_lost_identity_reconfirmation`, 17:33:24 and 17:33:36)
      and later on `visual_track_lost`.
    - COMBAT repeatedly ended `out_of_range` (17:32:31, 17:32:50, 17:34:32,
      17:35:00) instead of closing the distance.
    - ACQUIRE_TARGET for defence ended `expected_observation_missing`.
  - Not yet live-validated: continuous-W smoothness after the
    single-recheck/arrival changes (needs the user's visual judgement).
- **2026-10-01 evening, user directions and fixes (offline-tested; live
  pending unless noted):**
  - **User report (live):** 2/2 FULL_AI approaches reached Jaina and accepted
    the quest.
  - **Facing (user: "my character must face the target, the NPC/mob need
    not face me"):**
    - COMBAT visual follow is armed from the first control tick, not only
      after the first cast.
    - A target that left the screen near an edge (|x−.5| ≥ .3, ≤ 6 s old) is
      reacquired by turning toward that side for up to 3 s.
    - Without any bearing, combat continues and the client facing error
      drives the existing recovery (no blind spinning).
    - INTERACT: once in range the servo stops W and turns in place until the
      NPC is centred (|error| ≤ .055). After 0.8 s it accepts ≤ .20.
  - **Pointer (user: "the approach must not be interrupted when the mouse
    slides off; it may put it back meanwhile or keep it on the bbox"):**
    - Identity re-hover happens only in range. An unconfirmed re-hover no
      longer fails the approach (the selected GUID stays the authority).
    - New `POINTER` command: a pure pointer move that keeps the forward lease
      (executor + visual runtime + launch lane). HOVER still releases
      movement.
    - While advancing, the servo puts the pointer back on the target box
      every ≥0.5 s when it is >0.03 away (`AIPC_VA_POINTER_TRACK=0` disables).
  - **Loot diagnosis (live 17:32):**
    - LOOT right-clicked the corpse anchor, which is the *last mouseover*
      screen point (`mouseover_screen_anchors`), usually from before or
      early in the fight, so the click missed the corpse.
    - There was no approach (Retail exports no NPC world position) and the
      target was no longer selected.
    - The attempt vanished after 1.2 s on an ARRIVED replan.
    - Not fixed yet.
  - **Quest zone:** the addon exports only points: quest POI
    (`C_QuestLog.GetQuestsOnMap`) and `GetNextWaypoint`. The blue objective
    area polygon is not available as API data; the agent derives it from
    world-map CV (currently blind) or a radius around the POI.
  - Suite: same 18 baseline failures.
- **2026-10-01 17:54 FULL_AI (PID 1712).** User: "did not walk over properly,
  overshot, hesitated a lot before starting".
  - **Hesitation:** the first VISUAL_APPROACH started with no bound World3D
    track (`track None`) and failed after 1.2 s. REACQUIRE_TARGET then took
    8 s; the real approach began 24 s after FULL_AI.
  - **Stop-and-go:** the target sample stayed unchanged for 1.5 s (error
    frozen at .1447), so only 4 control updates happened in 2 s and W
    expired.
  - **Early "arrival":** INTERACT ended out_of_range at ready heights .13 and
    .156, then the learned height reached .213.
  - **Overshoot:** steering rebound to a .12-confidence track (WORLD3D:35),
    lost it, and ran on.
  - Fixes:
    - Default interaction height .19 (accepts succeeded ~.186). Learning is
      at least ×1.25 per client range error.
    - A still-fresh sample may re-lease W every .25 s (never a stale one).
    - Continuation rebinding requires confidence ≥ .30.
    - User idea, exit-edge correction: the last observed box edges are
      remembered. Lost through the bottom → MOVEBACKWARD (new movement-lane
      lease); left/right → turn that way; top → step forward (bounded
      1.5 s).
    - A box touching the screen bottom (≥ .93) counts as INTERACT arrival.
  - Combat follow handles left/right symmetrically.
  - Open:
    - The VA should not be proposed or started without a bound track.
    - A combat bottom-exit (mob behind/under the camera) back-step is not
      implemented yet.
    - LOOT should use the corpse's live box.
  - Suite: same 18 baseline failures.
- **User arrival rule (2026-10-01):** arrived when the unit's box stands next
  to, or overlaps by ~1/4–1/3, the own avatar's box.
  - Implemented as an extra INTERACT arrival criterion (`_beside_self`):
    - Self box: SELF_PLAYER identity or the feed's `screen_anchored` box.
    - Height ratio .6–1.8 and feet within .12 of each other, so a small
      distant unit behind the avatar does not count.
    - Horizontal overlap ≥ .25 of the narrower box, or a gap ≤ half the
      avatar width.
  - Offline-tested only. Suite: same 18 baseline failures.
- **2026-10-01 18:07–18:16 FULL_AI (PID 1712).** User: "followed a random
  gnome player, then stopped in WAIT at Jaina twice"; later "overshot, then
  WAIT REACH_OBJECT cannot start without world coordinates".
  - **executor_failure "Érvénytelen movement lease":** the in-range
    face-align turn could be .03 s, but the executor accepts .04–.35 s.
    Every approach that reached range failed and released the commitment.
    - Fixed (min .04).
    - An approach that *started* in range never turned (phase stayed IDLE);
      fixed.
    - A sweep test validates every servo movement command against the
      executor limits and fails on the old code.
  - **executor_failure "Érvénytelen klienskoordináta":** POINTER/HOVER on a
    box centre outside the client area. Now bounded to the screen.
  - **Gnome:**
    - The second rebinding path had no confidence/size gate. It now
      requires confidence ≥ .30 and height ratio .6–1.67.
    - Pointer identity: after our POINTER, a fresh mouseover naming another
      GUID rejects that track; the selected GUID confirms it.
  - **Overshoot through the unit:** the box vanished *at the own avatar*,
    not at a screen edge, and the approach failed after ~0.8 s of misses.
    - Vanishing over the avatar's lower box now counts as a BOTTOM exit
      (step back).
    - Track-lost failure is deferred while an edge correction (≤1.5 s) is
      pending.
  - **WAIT deadlock** (selected but off-screen unit; REACH_OBJECT needs XYZ,
    VISUAL_APPROACH a fresh anchor):
    - A unit that was on screen now gets REACQUIRE_TARGET toward its last
      bearing (with commitment) or a look-around SEEK.
    - A never-seen unit keeps the World3D → map → DB order.
  - **Loot (implemented, offline-tested):**
    - The kill anchor is the GUID-bound World3D box at death
      (`last_target_boxes`), not the last mouseover.
    - The planner uses the live corpse box. The click goes to the lower part
      of the box.
    - A corpse not beside the avatar (feet-level/horizontal rule for lying
      units) gets VISUAL_APPROACH purpose LOOT first. The registry branch
      requires a live corpse track and out of combat.
  - Suite: same 18 baseline failures. All of this is live pending.
- **Target switching (user 2026-10-01: "it only targeted the quest giver
  after I cleared the previous target by hand; it may simply click another
  unit; ESC clears a target"):**
  - A selected *player* no longer blocks visual search / quest-giver
    discovery (`_irrelevant_selection`). Clicking the right NPC replaces the
    selection.
  - The tooltip-only TARGET path no longer selects players (`is_player`,
    "(Player)").
  - ESC (`TOGGLEGAMEMENU` in the bindings cache) is deliberately *not* used:
    with nothing selected it opens the game menu.
  - Broader "unrelated NPC selection" handling was tried and reverted: it
    broke the documented friendly-interaction and map-discovery order
    (5 tests).
  - Offline-tested; suite same 18 baseline failures.
- **2026-10-01 18:25–18:30 FULL_AI (PID 1712, user-operated; code up to ~18:24,
  i.e. executor-lease fix, overshoot/backstep, reacquire, loot):**
  - **Live milestone.** Jaina: VISUAL_APPROACH 18:26:15 → INTERACT 18:26:17
    (1.6 s) → `interaction_verified` → QUEST_DIALOG accepted 55122 →
    navmesh MOVE to the area.
  - Murloc combat; LOOT `loot_verified` at 18:27:24 and 18:29:49, the first
    successful live loots. **Quest objective 3/6 First Aid Kits.**
  - Remaining issues:
    - COMBAT ended `out_of_range` five times; the follow-up
      VISUAL_APPROACH to the hostile lost its track.
    - One COMBAT `combat_timeout` was followed by LOOT `loot_ui_not_opened`.
    - MOVE `supported_stuck` once.
    - Several WAIT gaps between steps (map/SEEK churn).
- **Kill end = out of combat (user rule 2026-10-01).**
  - Live 18:27/18:28: Retail cleared the selection and the player left
    combat in the *same* sample. No target health or dead flag is exported
    (secret values), so COMBAT ran on for 17 s and 32 s (`combat_timeout`),
    and LOOT started late or failed.
  - `CombatSkill.verify` now ends with SUCCESS
    (`player_left_combat_after_engagement`) when all of these hold: own
    casts happened, the player was in combat during the attempt, is now out
    of combat, and the selection is empty. The kill is then marked and LOOT
    follows immediately.
  - While still in combat with the selection gone, another attacker is
    assumed (user): target loss → acquire the next attacker; no loot until
    combat ends. Retail area loot then collects every own corpse from one.
  - Tests: new out-of-combat kill test. The unrelated-corpse test now keeps
    combat on and asserts no kill and no loot anchor.
  - Suite: same 18 baseline failures.
- **Quest zone (re-checked):** the addon exports only points
  (`GetQuestsOnMap` POI per quest, `C_TaskQuest.GetQuestsOnMap`,
  `GetNextWaypoint`). No area polygon is available from the API.
- **2026-10-01 18:39 FULL_AI (PID 1712, out-of-combat rule build).** User:
  "did not loot, though it hovered one corpse; it was not out of range; it
  INSPECTed for 5–10 s after combat".
  - Telemetry: after each kill the player stayed in combat 2.6–3.5 s
    (265556 target gone → 265558.6 out of combat). With no selection every
    harmful action reads `in_range=False`, so COMBAT failed `out_of_range`
    before the drop. The kill was never marked, so the hovered corpse was
    not "own" and no LOOT followed.
  - Fix:
    - While the selection is gone but combat lingers, COMBAT waits up to
      6 s for the drop, then succeeds (kill, loot).
    - It leaves at once when own health falls (another attacker; own health
      is exported in combat) or after the grace (typed TARGET_LOST).
    - Auto-attack-only engagement counts too.
  - Tests: wait-for-drop and attacked-after-kill; the typed-results test
    now expects TARGET_LOST after the grace.
  - Suite: same 18 baseline failures.
- **2026-10-01 18:43–18:50 FULL_AI (PID 1712): QUEST 55122 "Murloc Mania"
  objective COMPLETE (6/6 First Aid Kits)**, fully autonomous.
  - Kills ended via the out-of-combat rule and were looted. The agent then
    took the mmap route to the turn-in location and started
    VISUAL_APPROACH to Jaina (18:50).
  - The user reported "not every mob was looted". Several LOOTs ended
    `loot_ui_not_opened`:
    - After one successful loot, Retail area loot had emptied the other
      corpses.
    - One corpse anchor was a stale mouseover point (no target-box binding
      without a nameplate), clicked three times.
  - Fixes:
    - A successful LOOT retires own kills from the last 30 s
      (`mark_area_looted`).
    - Two unopened loot windows release a corpse (`note_loot_failure`).
    - Hovering a corpse (dead mouseover of an owned kill) still refreshes
      its exact click point.
  - Test added. Suite: same 18 baseline failures.
- **Log review during YOLO v9 training (runs 18:25 and 18:43, 246 s FULL_AI):**
  - Time shares: COMBAT 33 %, **WAIT 29 %**, MOVE 15 %, SEEK 7 %, LOOT 4 %,
    INSPECT 3 %, map open/close ~3 %.
  - WAIT reasons:
    - "Több adat szükséges" 27 s;
    - "út ideiglenesen tiltva" (after MOVE stuck) 16 s;
    - "commitolt subgoal … várakozik" 15 s;
    - waiting for fresh World Map candidates 9 s.
  - Skill failures:
    - INSPECT `expected_observation_missing` (no addon hover answer) ×9;
    - SEEK `target_not_found` ×9;
    - COMBAT `out_of_range` ×7 (mostly the post-kill artefact, fixed);
    - LOOT `loot_ui_not_opened` ×6 (area loot, fixed);
    - MOVE stuck ×4;
    - ACQUIRE_TARGET no observation ×3.
  - **Fixed: World Map churn.**
    - Each quest-progress context reset reopened the map 30 s later,
      although its CV never produced a candidate on map 2175 (~15 s per
      OPEN/WAIT/CLOSE cycle).
    - Empty scans are now remembered per map across context resets. After
      2 empty scans the map is not reopened for 600 s and the map step
      counts as done (World3D → map → DB order preserved).
    - The memory is cleared as soon as a scan sees a candidate. Diagnostics:
      `empty_map_scans`, `empty_map_backoff_until`.
    - Test fails with the backoff disabled. Suite: same 18 baseline failures.
  - **Not changed** (user: questing first; quest-zone search only
    discussed):
    - The quest zone is the API POI point only, so the search area is an
      18 yd circle (3×3 cells, ≤22 s).
    - Proposed: subzone-name boundary (`GetSubZoneText`, e.g. "Murloc
      Hideaway" for Murloc Mania), expanding rings 18→35→60 yd on the
      navmesh, a learned heat map of seen/killed/looted quest mobs, DB
      spawns as fallback.

## 2026-10-01 — Map-API POIs: quest givers and dungeon/raid entrances (offline only)

- **Status: offline-tested, NOT live-validated.** Requires reinstalling the
  addon (0.9.37) in `_retail_\Interface\AddOns\`.
- **User direction:** quest icons, dungeon and raid entrances should be found;
  addon extension approved ("1. belefér, 2. mindkettő, 3. ez legyen a kövi").
- **Addon 0.9.37 `map_pois`** (full snapshot; 5 s cache per map; quest lines
  requested at most every 15 s; current map + parents up to the zone):
  - `available_quests` (≤25): `C_QuestLine.GetAvailableQuestLines` — the
    "!" givers, with `quest_id`, name, map X/Y and `world_position`
    (`C_Map.GetWorldPosFromMapPos`);
  - `dungeon_entrances` (≤10): `C_EncounterJournal.GetDungeonEntrancesForMap`
    (`atlas_name` classifies DUNGEON/RAID);
  - `taxi_nodes` (≤10) and `area_pois` (≤15): knowledge only for now.
  - Cache invalidated on QUESTLINE_UPDATE, QUEST_ACCEPTED/TURNED_IN,
    ZONE_CHANGED_NEW_AREA. Secret/hidden values are skipped.
- **Planner:**
  - No active quest, not in combat → MOVE (navmesh, WORLD_YARDS only) to the
    nearest same-instance API giver, purpose `LOCATE_API_QUEST_GIVER`,
    priority 80, stop 10 yd. Order: visible "!" badge SEEK (87) > API giver
    MOVE (80) > camera sweep (78) > roam (77); the World Map CV scan is not
    opened while an API route exists.
  - During the MOVE only quest-symbol evidence interrupts (same rule as the
    roam). Arrival does not trigger the entrance/transition search.
  - Reached area → local search owns it; that giver is retried after 300 s.
  - DUNGEON/raid goal outside the instance → MOVE to the Encounter Journal
    entrance (name in goal text, else matching kind), purpose
    `LOCATE_INSTANCE_ENTRANCE`.
  - Status: `map_pois` summary in the agent status.
- **Limits / to verify live:**
  - whether `GetAvailableQuestLines` lists the Exile's Reach / sandbox
    givers (non-questline "!" quests may be missing);
  - whether parent-zone positions convert to the player's instance;
  - entrance atlas names in 12.1.
- Tests: `tests/test_map_pois.py` (9), mock-Lua export test in
  `tests/test_agent_transport.py`; suite: same 18 baseline failures.

## 2026-10-02 — World3D YOLO v9 (4975 user-reviewed images): offline result

- **Status: OFFLINE_TRAINED, not promoted.** Live still loads
  `world3d_units_3class_v8.engine` by default.
- Training: `units3_v9`, initialised from v8. Train split 3982; val (504) and
  test (489) are the same as v8. Early stopping at epoch 68; best epoch 28.
- Same splits, same settings (PyTorch, 640 px):

  | model | split | P | R | mAP50 | mAP50-95 |
  |---|---|---|---|---|---|
  | v8 | val | .471 | .440 | .375 | .134 |
  | v9 | val | .405 | .476 | .368 | .134 |
  | v8 | test | .444 | .529 | .411 | .154 |
  | v9 | test | .512 | .546 | .439 | .172 |

- Per class (mAP50-95, val / test):
  - `overhead_symbol_like` (quest "!"/"?" badges) improved:
    v8 .139/.150, v9 .161/.175;
  - `creature_unit_like` slightly down on val, equal on test:
    v8 .175/.173, v9 .160/.170;
  - `quest_object_outline_like` is noisy (29 val instances):
    v8 .087/.139, v9 .080/.172.
- TensorRT FP16 engine built with the v8 export settings (640, batch 1):
  `models/world3d_units_3class_v9.engine`. Test split: v8 engine
  .392/.153, v9 engine .412/.166 mAP50 / mAP50-95; ~3 ms inference for both.
- Conclusion:
  - v9 is a modest gain (test and badges up, val tied), not a step change.
  - The full review did not move overall mAP much. The limit is more likely
    class definition / label consistency or model size than data volume.
- A live A/B is possible without code change, via
  `AIPC_WORLD3D_MODEL=<projekt>\models\world3d_units_3class_v9.engine`.
  Default promotion awaits user approval.

### 2026-10-02 — Why v9 scores low: error analysis (offline)

- **Question (user):** is it bad because the images are not sharp, and would
  every new creature/zone need ~30000 images?
- **Sharpness is not the cause.**
  - Laplacian variance shows the same creature recall for the low / mid /
    high sharpness thirds: .61 / .65 / .61.
  - Live captures are not sharper than the YouTube frames (median 614 vs
    699).
- **Dataset composition.**
  - 77 % of the dataset is YouTube frames (Exile's Reach, Midnight,
    Dragonflight/Northshire); 983 live captures are in train only.
  - val/test contain **no live frames** and are frame-level splits of the
    same videos. The score therefore says nothing about the user's own
    client, nor about unseen zones.
- **Recall by unit height** (creature class, conf .15 = runtime threshold):

  | unit height | recall |
  |---|---|
  | <5 % | .27 |
  | 5–10 % | .67 |
  | 10–20 % | .66 |
  | >20 % | .54 |

- **Label incompleteness is the dominant error.**
  - In a contact sheet of confident (≥.5) "false positives", ~10 of 12 were
    real unlabeled units: ship crew, training dummies, distant wolves, a troll.
  - v9 at conf ≥.4 finds boxes with no label (IoU < .1):
    - train: 1188 boxes in 868/3982 frames — a lower bound, since the model
      learned to skip them;
    - val: 182 boxes in 118/504 frames;
    - test: 165 boxes in 106/489 frames.
  - Measured precision (.38–.40) is therefore heavily understated, and
    training on frames with unlabeled units teaches the model to doubt real
    units.
- **Own-avatar convention is inconsistent.**
  - A unit in the avatar zone is labeled in ~25 % of frames (975/3982 train),
    although the avatar is visible in almost every third-person frame.
  - The model reproduces this: it predicts the avatar in 246/993 frames.
  - This explains most "missed big units". Excluding the avatar zone moves
    overall creature recall only .60 → .62.
- **Not the cause:** the number of creature types. The class is generic
  (`creature_unit_like`), so new creatures do not need new classes.
- **Proposed** (awaiting user decision):
  1. A model-assisted missing-label pass: review only the suggested boxes.
  2. One fixed avatar rule — never a creature, or its own `self` class; the
     live screen-anchored tracker already handles the avatar.
  3. A separate test set from the user's own client.
  4. Then retrain, and possibly try a larger model with a latency check.

### 2026-10-02 — Re-review setup (user: "átnézem újra a képeket")

- **Earlier rejections.** In the previous pool the user rejected 5697 model
  proposals in 2327 frames and accepted 37. Of today's 1532 confident
  unlabeled v9 boxes:
  - 1113 had been shown and rejected — a sample is about half real units
    (distant orcs, a wolf next to a labeled wolf), plus correct rejections
    (forge fire, quest-window portrait) and rule-dependent cases (training
    dummies);
  - 419 were never shown — mostly real units.
  - Conclusion: rules were inconsistent, not just effort.
- **New pool:** `datasets/world3d_units_v6_rereview`
  (`tools/build_world3d_rereview_pool.py`). The source
  `world3d_units_v5_review` is read-only and untouched.
  - 4975 frames, all UNREVIEWED, splits preserved.
  - 9581 earlier boxes pre-ACCEPTED.
  - 1650 v9 proposals (conf ≥.4, not overlapping a saved box of the same
    class).
  - 972 own-avatar proposals; in the other frames the avatar must be drawn
    by hand when visible.
  - Proposed rule list: see the pool's `README.txt` (pending user
    confirmation).
- **Annotator** (`tools/review_world3d_annotations.py`):
  - ←/→ arrow keys page previous/next (`cv2.waitKeyEx`; `waitKey & 0xFF`
    had masked them).
  - Paging with unsaved edits now warns first; pressing the same key again
    discards. This also covers N/P/[/], which previously dropped edits
    silently.
- Tests: `tests/test_world3d_annotator_paging.py` (4),
  `tests/test_world3d_rereview_pool.py` (3). Suite: same 18 baseline
  failures.

## 2026-10-02 — Installation wizard (offline)

- **User direction:** an installation wizard. The mmap/vmap extractors and
  their DLLs are in the Retail WoW folder. "Elég, ha mindhármat az
  extractorból nyeri ki, utána abból olvassa, nem kell a zip."
- **`INSTALL_WIZARD.bat` → `tools/install_wizard.py` →
  `src/wowbot/install/`.** The Tkinter wizard has seven steps; every action
  needs an explicit click:
  1. system;
  2. Python packages (pip, CUDA torch index);
  3. `_retail_` validation (Wow.exe, `.build.info` version, extractors,
     write access, admin relaunch);
  4. addon install/update;
  5. navigation data via the TrinityCore extractors in `_retail_`:
     - same steps as `extractor.bat`, non-interactive (`--silent`);
     - mmaps per selected map ID (default 2175) or all;
     - `Buildings` deleted only with an opt-in checkbox plus confirmation;
  6. TensorRT engine rebuild for the local GPU;
  7. save `config/local_env.bat` (`WOWBOT_WORLD_DATA_PATH`,
     `WOWBOT_MMAP_PATH=_retail_\mmaps`) and point `agent_gui.json` at the
     folder.
- PID and bindings-cache are deliberately left to the agent GUI.
- The `START_*.bat` files call `config\local_env.bat` when present.
- The agent GUI now defaults to `_retail_\mmaps` (folder browse) instead of
  `Downloads\mmaps.zip`.
- The generator writes `mmaps/{:04}.mmap` and `{:04}_{:02}_{:02}.mmtile`,
  the same names the reader expects. Checked in the binary and against the
  old zip.
- **Real folder state (read-only check):**
  - client 12.1.0.69933;
  - extractors and 15 DLLs present; folder writable;
  - maps: 1079 maps; vmaps: 969 maps; **mmaps: 0** — still to generate;
  - the 39k-file `Buildings` intermediate is still present;
  - installed addon 0.9.36 vs project 0.9.37.
- Not run by the assistant: the extractors themselves (they write to the
  user's WoW folder; the user starts them in the wizard).
- Tests: `tests/test_install_wizard.py` (10, including a hidden-window
  render of every page and real subprocess streaming/cancel). Suite: same 18
  baseline failures.

### 2026-10-02 — Annotator: delete an image + labels

- **Trigger:** DEL pressed twice, or the red "DEL  Delete IMAGE+labels"
  header button clicked twice; any other key cancels a pending delete.
- **Effect:**
  - image, label, saved review and proposals move to
    `review/deleted/<stem>/` together with a `record.json`;
  - only that manifest line is removed (records hidden by `--reviewed-only`
    stay), so the export skips the frame;
  - the last frame of a pool cannot be deleted.
- **Undo:** U restores the last deletion — files, manifest position and
  view.
- Nothing is destroyed. Re-review pool images are hard links, so the
  original v5 pool keeps its copy.
- Tests: 5 more in `tests/test_world3d_annotator_paging.py`.

## 2026-10-02 19:42–20:05 — Live: false "stuck" while running (root cause fixed offline)

- **Runs (pid 14400):**
  - 19:45 with addon 0.9.36: `map_pois` empty, as expected.
  - 19:50 and 20:01 with 0.9.37: the API quest-giver MOVE
    (`LOCATE_API_QUEST_GIVER`) started live and reached Jaina; quest 55122
    accepted.
  - After that, MOVE to the quest region failed `supported_stuck`
    repeatedly (19:45:57, 19:50:52, 20:04:20, 20:05:00), followed by RECOVER
    BACKWARD, a transition search and WAITs.
- **Root cause.** The MOVEMENT_CONTROL_UPDATE samples show `moving=True`,
  speed 7, but x/y frozen for 1–3 s.
  - Positions changed only at paged STATE snapshot times.
  - **All 1083 logged FAST states came from the bounded transport
    variants** (field-rich samples exceed 850 bytes). Those variants carried
    **no `player_world_position`**.
  - Every 30 Hz observation repeated the old position, counted as
    "no progress" plus `MOTION_POSITION_MISMATCH`, and so became stuck while
    running.
- **Fix (offline-tested):**
  - **Addon 0.9.38:** the bounded FAST variants (compact, combat, edge)
    carry `player_world_position={x,y (0.01 yd), instance_id,
    coordinate_space}`. The four `*_sample_time` copies of `monotonic_time`
    are dropped to make room; a live-like sample stays ≤ 850 bytes.
  - **Python `PacketAssembler`:** restores the sample times and the position
    metadata (`source`, `ui_map_id`, `z_known`, `z_source`), and stamps
    every position with its `sample_time` (FULL and FAST).
  - **`ReachMovementController`:** for WORLD_YARDS, progress/stuck evidence
    counts only new position measurements; repeats return
    `awaiting_fresh_position_sample`. This also protects older addons.
- **Tests:** `tests/test_fast_world_position.py` (5).
  - The slow-update running test fails on the old controller.
  - Wall contact with fresh measurements still gives `supported_stuck`.
  - Suite: 18 baseline failures, plus the timing-flaky
    `test_capture_worker` process test under full load (passes 3/3 alone).
- **Still open (same runs, not yet analysed in depth):**
  - long "Több adat szükséges" WAITs at the objective area while SEEK
    targets are lost (`visual_track_lost`);
  - `COMBAT facing_failed` on Murloc Watershaper (20:02:40);
  - `LOOT loot_ui_not_opened` after the 20:03:56 kill;
  - the Quartermaster Richter detour at 19:46.
- **Needs:** reinstall the addon (0.9.38), then a live run.

### 2026-10-02 20:04 — Real stuck at the Murloc Hideaway shipwreck: not in the navmesh

- **Live (old code):** MOVE `LOCATE_QUEST_OBJECTIVE_REGION` to the 55122 POI
  (-366, -2559), from (-371.6, -2582.0) (final waypoint, 23.6 yd).
  - Fresh positions stayed constant for ~60 s with `moving=True`: genuine
    wall contact with the shipwreck (user screenshot).
  - The cycle repeated: `supported_stuck` → RECOVER BACKWARD → the same
    route → stuck → transition search → WAIT.
- **Navmesh check:**
  - Zip navmesh (`Downloads/mmaps.zip`): the straight segment lies on one
    walkable polygon (2175 tile poly 1637); route cost 25.8 vs 23.7 yd
    straight.
  - **Same map generated locally** with the user's `mmaps_generator` from
    the user's own maps+vmaps (`2175 --silent --threads 4`, output to the
    scratchpad, 3 min, 330 files): identical polygons and route.
  - So the wreck is absent from TrinityCore mmaps (server-spawned object or
    non-baked collision). Re-extracting will not fix it.
- **Needed (not started; MOVE-stuck handling was deferred by the user):**
  - learned obstacles — after a supported stuck with fresh positions, block
    the navmesh area just ahead and re-plan around it, instead of
    re-running the same route;
  - for search-region MOVEs (quest objective / giver), being blocked within
    ~25 yd of the center counts as reaching the region and hands over to
    the local search.

### 2026-10-02 — Stuck recovery: jump, back off further, learn the obstacle (offline)

- **User directions:** jump (Space) while running into a small obstacle; back
  off more than one step; region-arrival-by-proximity rejected (an NPC
  behind the wreck would stay hidden), so keep the destination and route
  around.
- **Why the old ladder looped:** BACKWARD always "succeeded" (the position
  changed), so the resolver went IDLE. The same MOVE then hit the wreck
  again, and the ladder restarted at BACKWARD.
- **Changes:**
  - **Running jump:** `ReachMovementController` sends one MOVEFORWARD+JUMP
    on CANDIDATE_STUCK with `MOTION_POSITION_MISMATCH`, re-armed after
    progress.
  - **Executor:** JUMP may ride a MOVEFORWARD lease only, as a transient key
    released at the steering deadline.
  - **RECOVER BACKWARD:** 3×0.30 s (~4 yd) under the 350 ms step cap.
  - **RECOVER JUMP_FORWARD:** forward+jump, then forward again.
  - **Ladder order:** BACKWARD → MARK_DANGER → REBUILD_CORRIDOR →
    JUMP_FORWARD → STRAFE → TURN → NEW_LOCAL_WAYPOINT → LOCAL_REPLAN →
    GLOBAL_REPLAN → BLACKLIST_TEMP.
  - **Ladder memory:** a new stuck within 5 yd / 180 s of the previous one
    (same kind) resumes the ladder instead of restarting it.
  - **Learned obstacle position:** `mark_current_route_danger` places the
    NAVIGATION_FAILURE 2 yd ahead along the facing (r = 3 yd), not under the
    player.
  - **Navmesh-checked detour:** `DangerMap.avoidance_anchors` accepts only
    detour points the mmap contains (`walkable_point`), widening ×1.6/×2.3,
    and skips the detour if neither side is walkable. Without an mmap the
    old geometric detour is kept.
  - **`sample_time` kept:** `NavigationService._state_with_navmesh_surface`
    keeps it, so the fresh-position gate also works on routed MOVEs.
- **Tests:** `tests/test_stuck_obstacle_recovery.py` (7); ladder-order
  assertions in `tests/test_stuck_resolver.py` updated to the new order.
  Suite: 18 baseline failures.
- **Second pixel strip:** user-offered location noted — the right-hand
  quest-tracker area, if FAST bandwidth runs out later. Not needed now.

### 2026-10-02 20:02–20:04 — Loot analysis and fixes (offline)

- **User report:** the agent did not loot the first murloc although it
  inspected it dead; only the second loot happened, and it contained both
  corpses (area loot).
- **Murloc Watershaper (agent clock 356905–356954):**
  - TARGET by click, COMBAT pressed ACTIONBUTTON3 → "You are facing the
    wrong way!".
  - COMBAT failed `facing_failed` twice within 2 s; the target selection was
    gone (`tgt=None`).
  - The agent then WAITed ~14 s in combat, and the murloc died to
    auto-attack (356918.9).
  - No kill was recorded (`owned_corpse_guids` empty), so the dead hovers at
    356930–356954 never produced LOOT.
- **Murloc Spearhunter:**
  - LOOT right-click at 356984.2, as combat ended.
  - Auto-loot: LOOT_WINDOW_OPENED/CLOSED and LOOT_RECEIVED "First Aid Kit
    x2" (both corpses), seen by Python ~356986–356988.
  - The verifier still said `loot_ui_not_opened` at 356987.3: it searched
    for `LOOT_OPENED` (the addon emits `LOOT_WINDOW_OPENED`), and the 3 s
    deadline expired before the paged events arrived.
- **Fixes:**
  - **Ownership memory:** `WorldModel.combat_engaged` records every creature
    a COMBAT/DEFEND skill fought. `corpse_is_combat_correlated` accepts it
    for 120 s, so its dead hover creates an own corpse anchor and LOOT. If
    someone else killed it, the existing 2-failure loot limit retires it.
  - **`LootVerifier`:** only events with a sequence above the pre-click
    buffer count. `LOOT_WINDOW_OPENED`/`LOOT_OPENED` is accepted;
    open+close (auto-loot) counts as `loot_window_cycled` (0.80, success).
  - **LOOT contract timeout:** 3 → 6 s.
- **Tests:** `tests/test_loot_live_20261002.py` (5). The deadline test in
  `test_agent_core.py` was moved to 6 s with its rejection semantics kept.
  Suite: 18 baseline failures.
- **Still open (combat):**
  - FACING_WRONG_WAY without a known target screen point fails immediately
    instead of turning toward the attacker.
  - With the target lost while still in combat, the agent WAITed instead of
    re-acquiring the attacker.

### 2026-10-02 — Combat facing without nameplates (offline)

- **Finding:** in the Watershaper fight the game never lost the target (the
  paged STATE shows the GUID throughout; the name and health are secret in
  combat).
  - The combat visual follow and the facing recovery read only
    `target.screen_position`, which came only from addon screen/nameplate
    positions. Retail 12 exposes neither (user confirmed).
  - So live they never had a bearing: COMBAT failed `facing_failed`
    (attacker behind the character), then the facing-failure backoff parked
    COMBAT and the agent WAITed ~14 s while being hit.
- **Fixes:**
  - **Bound track:** `WorldStateProjector._bound_track_anchor` sets the
    selected target's `screen_position` from its World3D track — the track
    the addon mouseover GUID was bound to when TARGET clicked it, or the one
    remembered in `last_target_boxes`. Source `BOUND_WORLD3D_TRACK`, with
    the track's current x/y and sample time. No track → no position (nothing
    invented).
  - **Facing recovery:** `CombatSkill` FACING_WRONG_WAY without a visible
    target turns toward the last seen side (default left) via
    COMBAT_TRACK_REACQUIRE instead of failing. Timeout 1.8 → 3.0 s (a full
    keyboard turn is ~2 s).
  - **Backoff:** a COMBAT/DEFEND facing failure while still in combat with a
    live attackable target is blocked for only 0.5 s.
- **Tests:** `tests/test_combat_facing_live_20261002.py` (2), facing tests in
  `test_m0_combat_loot_skills.py` updated (2). Suite: 18 baseline failures.

### 2026-10-02 20:43–20:47 — Live (addon 0.9.38; loot/stuck fixes in, combat-facing fix not yet)

- **Quest-giver search:**
  - The API quest-giver MOVE arrived (20:44:24).
  - Visual search then targeted **Kee-La** (no "!", no quest): INTERACT
    `no_response` ×2, ~45 s lost before Jaina (20:45:18), with repeated SEEK
    sweeps and WAITs — the "SEEK loop".
  - The addon mouseover carries no quest role for Kee-La or for Jaina; only
    the overhead "!" distinguishes them.
  - Quest 55122 accepted 20:45:45.
- **Combat:** Murloc Spearhunter.
  - COMBAT `out_of_range` → VISUAL_APPROACH (interrupted by the quest MOVE)
    → COMBAT → `target_death_verified` 20:46:19.
- **No loot:** after the kill, `owned_corpse_guids=['…3FFBA4']`, but
  `confirmed_corpse_anchors=[]`, so no LOOT was proposed. A MOVE/map/WAIT
  (~28 s) followed until the user stopped.
  - The hover-time screen point had expired after the movement.
  - `last_target_boxes` was only ever filled through nameplates (absent
    live), so `mark_combat_kill` had no position.
  - The bound-track target projection (added at 20:45, after this run
    started) refreshes `last_target_boxes` from the followed track, so the
    kill now leaves a corpse anchor at the death-time box.
  - Test: `test_kill_of_a_tracked_target_leaves_a_lootable_corpse_anchor`.
- **Open:**
  - prefer "!"-badged NPCs over plain friendly NPCs when no quest is active;
  - the SEEK/WAIT loop at the quest-giver spot;
  - a quest MOVE interrupting VISUAL_APPROACH to a quest target.

### 2026-10-02 — Quest-giver API probe (addon 0.9.39, to run live)

- **Question (user):** does hovering or targeting an NPC reveal that it
  offers a quest? Early agent versions assumed so.
- **Code facts:**
  - `quest_role` is filled only from **World Map pin** tooltips, never for
    3D hovers; old logs show no role on Jaina either.
  - 3D hovers carry only `quest_related`/`quest_id`, from a tooltip match to
    an **active** quest's objectives.
- **Probe:** `quest_api_probe` in the full snapshot, plus
  `/aipc questprobe` in chat. For target / mouseover / softinteract it
  records:
  - known candidates (`UnitIsQuestBoss`, `UnitIsQuestGiver`,
    `C_QuestLog.UnitIsRelatedToActiveQuest`, `GetQuestIDForUnit`,
    `IsUnitOnQuest`, classification/reaction/selection type, …);
  - every global or `C_*` function whose name mentions
    quest/gossip/interact *and* unit, if read-style (Get/Is/Has/Can/Unit),
    called in pcall with the unit token only — actions such as InteractUnit
    are never called;
  - `C_TooltipInfo.GetUnit` line types/texts;
  - gossip/quest dialog available-quest counts.
- Secret values are masked as `SECRET`. A 12 KB guard drops the
  discovered-call details from the snapshot (never the snapshot itself).
- **Tests:** mock test in `tests/test_agent_transport.py`. Suite: 18
  baseline failures.
- **Live check needed:** target/hover Kee-La (no "!") and Jaina ("!") and
  compare.

### 2026-10-02 21:0x — Quest-giver API probe result (live, `/aipc questprobe` on Lady Jaina)

- **No API reveals quest-giver status on hover/target in Retail 12.1:**

  | API | Result on Jaina |
  |---|---|
  | `UnitIsQuestGiver`, `C_QuestLog.GetQuestIDForUnit` | MISSING (no such API) |
  | `UnitIsQuestBoss` | false |
  | `C_QuestLog.UnitIsRelatedToActiveQuest` | false (active quests only) |
  | `UnitIsInteractable` | true (any gossip/interaction NPC) |
  | `UnitClassification` / `UnitCreatureType` / `UnitSelectionType` | normal / Humanoid,7 / 3 |
  | `UnitIsTrivial` / `UnitIsGameObject` / `UnitIsTapDenied` | false |

  - **Discovery** (all quest/gossip/interact+unit read-style functions)
    found only `UnitQuestTrivialLevelRange[Scaling]` (5) and
    `C_PlayerInteractionManager.IsReplacingUnit` (false).
  - **Tooltip:** only name + "Level 10".
  - **Gossip/quest dialog lists:** empty (no window open).
- **Probe bug:** `UnitReaction`, `UnitCanAttack` and `UnitIsFriend` need two
  units and errored; irrelevant to the quest-giver question.
- **Conclusion:** the early-agent assumption that hover/target exposes a
  quest giver was false. Available quests are known only from:
  - the overhead "!" (vision);
  - the gossip/quest window after INTERACT;
  - map pins / `C_QuestLine` positions (`map_pois`).
- The probe was removed again in addon 0.9.40 at the user's request; it is no longer needed.

### 2026-10-02 21:10–21:20 — Live: loot works on the corpse point; quest 55122 completed (user report)

- **21:10 run:**
  - Jaina found fast (21:11:39).
  - Watershaper killed 21:12:28 and **LOOT was proposed** (corpse anchor now
    exists).
  - First click went to (0.498, 0.41): the dead-mouseover point had been
    bound to **WORLD3D:22 = the player's own box** (`screen_anchored`,
    self-avatar overlap 1.0). The corpse lay at the feet, and YOLO had no
    separate corpse box.
  - Second click at the exact dead-hover point (0.509, 0.482): no loot
    window and no error, most likely an empty corpse.
  - COMBAT then failed `executor_failure` ×3 on the Spearhunter — not yet
    analysed.
- **User, next run:** looted when the mouse was on the corpse; quest
  completed.
- **Fixes (offline):**
  - **Own-box exclusion:** `self_avatar.is_self_avatar_box` keeps the
    player's own box out of every association — mouseover anchors (reducer
    and projection), the bound target track, nameplate association, corpse
    view (falls back to the exact hover point) and quest-NPC evidence.
  - **Addon 0.9.41:** dead units carry `lootable` from `CanLootUnit(guid)`
    (hasLoot and canLoot) in target/mouseover. A LOOT failure on a corpse
    the addon reports as empty is released after 1 try instead of 2.
  - **Quest-NPC filter:** questing with no active quest selects a friendly
    NPC only if one of these holds:
    - a symbol box sits over its head (`quest_giver_evidence`), or badge
      evidence is on its own box;
    - no symbol is visible and the player is within 25 yd of a `map_pois`
      available-quest pin.
  - **TDB excluded (user, same day):** the TDB reference data is deliberately
    not part of this rule — it is a last-resort fallback from the early
    OpenCV era.
  - **Skip rule:** a symbol-less NPC that answers INTERACT with nothing is
    skipped for 300 s.
- **Tests:**
  - new: `tests/test_quest_npc_filter.py` (7);
  - added: avatar/empty-corpse tests in `test_loot_live_20261002.py` and a
    `lootable` addon test;
  - updated: targeting tests now give the hovered NPC a "!" box
    (`quest_npc_boxes`).
  - Suite: 18 baseline failures.


## 2026-10-03 — Turn-in, multi-offer, quest batching, Slam and combat lease fixes (offline)

Source: run `live-debug-20261002-212105` (21:21-21:55, PID 14400) and user
requests of 2026-10-03.

- **Turn-in stall (21:27-21:33, again 21:40, 21:42, 21:55):**
  - The API turn-in point (-423, -2611) lay ~14 yd from Jaina. The MOVE
    (stop 6 yd) arrived and was proposed again with priority 110.
  - Without progress, `AgentNavigator.permits` blocked the destination
    (WAIT "út ideiglenesen tiltva"), then the same MOVE returned.
  - While that route was "committed", every INSPECT/SEEK was filtered out, so
    the "?" NPC was never looked for.
  - **Fix:**
    - Within 12 yd of the point, or within 35 yd after an arrival, no MOVE is
      proposed. Instead a `SEEK_VISUAL_CUE` with purpose
      `SEARCH_TURN_IN_AREA` runs, around an 18 yd area.
    - `NavigationProposalAdapter` alternates camera sweeps with walks to
      mmap-validated cells of that area.
    - A body box with a "!"/"?" box over its head now gets top rank in the
      distant SEEK, INSPECT priority ≥ 88, and interrupts turn-in moves.
- **Stale primary quest:**
  - 55122 was turned in at 21:33 but stayed the runtime primary quest until
    the end (`NOT_ACTIVE_REASSESS`). It filtered out later quests'
    objectives, turn-ins and gossip offers.
  - **Fix:** for generic goals (no explicit quest id, not MAIN_CAMPAIGN), the
    primary follows the quest log:
    - exactly one quest in the log → that quest;
    - several quests → none is pinned, and all are planned.
- **Multiple offers (21:45):** an NPC offered 55186 and 55184. The agent
  waited 38 s because the turned-in primary quest hard-filtered the gossip
  rows.
  - **Fix:**
    - Only a quest the user named filters offers; the runtime quest is a
      preference only.
    - One row is selected at a time (COMPLETE rows first).
    - If the dialog closes while offered quests remain, the same targeted
      NPC is spoken to again (priority 95, at most 45 s).
    - **Addon 0.9.42** also exports the QuestFrame greeting panel
      (`QUEST_GREETING`) offers and turn-ins.
- **Batching (user):** "do quests at one place first, then turn them in
  together."
  - `QuestBatchPolicy` defers a completed quest's turn-in trip while another
    quest's API POI is within 120 yd.
  - Exceptions:
    - a turn-in point already within 40 yd is handed in now;
    - after 600 s a finished quest is no longer deferred.
- **Slam never used:** Shield Slam was pressed ~100 times, Slam once.
  - In combat the action cooldown is a secret value, so the FAST action bar
    reads 0 ("ready"). `IsUsableAction` ignores cooldowns, so Shield Slam
    (priority 40) always won.
  - **Fix:**
    - `AbilityRuleEngine` tracks the cooldowns of our own observed successful
      casts. Sources: the FAST `combat_hint`, or the late-adjusted
      `SPELLCAST_SUCCEEDED` events. Catalog values: Shield Slam 9 s,
      Charge 20 s.
    - A "not ready" answer blocks the spell for 2 s.
    - The addon's `combat_hint` never reached Python: no FAST variant carried
      it. Addon 0.9.42 adds it to all combat-capable variants.
- **COMBAT `executor_failure` ×11:**
  - A combat follow turn could be 0.035 s, but the executor accepts movement
    leases of 0.04–0.35 s only. The result was "Érvénytelen movement lease"
    and a failed COMBAT/DEFEND.
  - **Fix:** the minimum turn is now 0.04 s.
- **Tests:**
  - `tests/test_quest_batching_turnin_20261003.py` (8);
  - `tests/test_combat_local_cooldowns_20261003.py` (5).
  - Full suite: 18 baseline failures, no new ones.
- **Status:** OFFLINE only. The user must install addon 0.9.42, `/reload`,
  restart the agent and validate live:
  - turn-in "?" search;
  - multi-offer accept;
  - batching;
  - Slam use;
  - no executor_failure.

## 2026-10-03 — World3D YOLO v10 (3997 re-reviewed images): trained and set as default

- Dataset `datasets/world3d_units_3class_v10_rereviewed`:
  - 3997 reviewed frames (2 unreviewed frames skipped);
  - split: train 3147, val 440, test 410.
- Training `units3_v10`:
  - initialised from v9;
  - resumed once, at epoch 14;
  - early stop at epoch 71; Ultralytics `best.pt` = epoch 31.
- On the same new labels (mAP50 / mAP50-95):

  | model | creature (val) | creature (test) | test recall | symbol (test) | all (test) |
  |---|---|---|---|---|---|
  | v8 | .434/.163 | .449/.164 | .47 | .424/.173 | .416/.155 |
  | v9 | .407/.148 | .429/.157 | .41 | .493/.217 | .438/.177 |
  | v10 epoch 31 | .604/.243 | .651/.255 | .68 | .481/.207 | .515/.211 |
  | v10 epoch 65 | .646/.254 | .682/.266 | .72 | .468/.183 | .518/.200 |

- TensorRT FP16 engines, batch 1, test split:
  - `world3d_units_3class_v10.engine` (epoch 31): creature .642/.255;
  - `world3d_units_3class_v10_e65.engine` (epoch 65): creature .684/.267;
  - 512 px pairs: `..._v10_512.engine` and `..._v10_e65_512.engine`;
  - inference ~4.1–4.4 ms.
- **Runtime default (user decision):** `world3d_units_3class_v10_e65`, with
  its engine and the `_512` alternate.
- **Rollback:** `AIPC_WORLD3D_MODEL=<projekt>\models\world3d_units_3class_v8.engine`.
- **Status:** OFFLINE only. val/test contain no live-client frames, so live
  validation is pending.

## 2026-10-03 06:27–06:56 — Cooking Meat (55174) run: friendly-NPC detours, empty corpses, 2 min WAIT (fixed offline)

- Run `live-debug-20261003-062740`, addon 0.9.42, model v10_e65.
  - Earlier quests went well: 55122 turned in; 54951 and 54952 accepted and
    turned in.
  - Cooking Meat ("5 Raw Meat collected from wildlife"; Coastal Goat and
    Prickly Porcupine) reached only 1/5 in ~13 min.
- **Friendly NPC detours:**
  - An Alliance Sparring Partner (npc 164577) was targeted, approached and
    interacted with 6× (`no_response`).
  - Another player's companion pet "Pipfip" (`Pet-…` GUID) was
    targeted/interacted with. Then `REACH_OBJECT` WAIT looped 06:53–06:56.
  - **Fix (`friendly_npc_relevant`):** with an active quest, a friendly NPC
    is selected or approached only if one of these holds:
    - a ready objective needs an NPC (talk/interact/escort/use-on/unknown);
    - a "!"/"?" box sits over it;
    - a completed quest's turn-in point is within 35 yd.
  - Companion pets are never selected.
- **Empty corpse:** a goat corpse turned `lootable=false` after auto-loot,
  but LOOT was retried twice. **Fix:** no LOOT/approach proposal for a
  corpse the addon reports `lootable=false`.
- **2 min WAIT** "Több adat szükséges" at the quest area: the camera sweeps
  were exhausted, and COLLECT has no local entity search.
  - **Fix:** with an active quest's API area within 150 yd:
    - the camera sweep may run;
    - after the sweeps, a `SEARCH_LOCAL_OBJECTIVE_AREA` roam walks the
      30 yd area cell by cell, sweeping at each cell, and restarts once all
      cells were visited.
- **Open:** COMBAT failed with OUT_OF_RANGE twice on goats; not analysed yet.
- **Tests:** NPC filter (3 new), quest-area roam (1). Suite: 18 baseline
  failures, no new ones.

### 2026-10-03 — Cooking Meat: why goats/porcupines were seen but not attacked or looted (offline analysis + fixes)

- **Sources:** journal, FAST observations, the YOLO feed association trace
  and the screenshots.
  - The live-captures budget (181 frames) ended at 06:30, so there are no
    screenshots of 06:45–06:56.
- **YOLO perception was fine:**
  - 19 844 feed frames in the period; 97 % had at least one unit box
    (conf ≥ .25), 2.1 boxes per frame on average.
  - Goats and porcupines were hovered many times with `quest_related=true`
    and `attackable=true`.
- **TARGET failed 7× (`target_not_found`):**
  - SEEK hovered a goat while still walking and turning (TURNLEFT 0.16 s,
    0.1 s before the click). It ended as soon as the mouseover named the
    goat, and TARGET clicked the current cursor at once.
  - The goat was under the pointer only at the click instant. It slid away
    and the click hit nothing.
- **LOOT:** one right-click at a remembered point right after the kill, no
  check of what was under the pointer, then 12 s waiting. Repeated once.
- **Combat:** a goat last seen at x = .49 (straight ahead) lost its box. The
  follow logic kept turning left away from it, and COMBAT ended out_of_range.
- **Fixes (offline):**
  - **Hover-confirm-click (`skills/hover_confirm.py`):**
    - TARGET and LOOT hover the unit's current World3D box;
    - they click only after the addon mouseover names the expected GUID;
    - LOOT does not click when the corpse is reported `lootable=false`;
    - the box is re-hovered at its fresh position, up to 3 times, every
      0.45 s.
  - **Combat follow:** a target last seen in the centre band (|x − .5| < .15)
    is never searched by turning.
- **Tests:** TARGET/LOOT hover-confirm (2), centred lost target (1); 2 old
  click-first tests updated. Suite: 18 baseline failures, no new ones.

### 2026-10-03 — Other bugs found in the 06:27–06:56 log (fixed offline)

- **Confirmed live:** the new turn-in "?" search worked. At 06:40:53 the agent
  arrived, swept, walked a cell, found the NPC and turned in at 06:41:14.
- **Objective-area MOVE loop:** inside the quest area every kill credit changed
  the quest signature. The objective MOVE came back, made no progress and was
  blocked ("út ideiglenesen tiltva") at 06:31, 06:36, 06:37, 06:39 and 06:40.
  - **Fix:** within 20 yd of an unfinished quest's POI no objective MOVE is
    proposed; the local search and roam own the area.
- **INTERACT `executor_failure` "Érvénytelen movement lease"** (06:30): the
  INTERACT visual approach sent a POINTER command on the movement lane.
  - **Fix:** POINTER goes on the discrete lane, as for SEEK and
    VISUAL_APPROACH.
- **36 INSPECTs typed TELEMETRY_STALE:** the hover hit a box with no unit
  under it, mostly long-lived static tracks.
  - `failure_reason_from_legacy` mapped `expected_observation_missing` to
    TELEMETRY_STALE (sensor recovery).
  - **Fix:** it now maps to EXPECTED_STATE_NOT_REACHED.
- **Memory DB:**
  - DB 500 MB, WAL 2.26 GB, growth ~510 MB/h, 5.5k observations/min, query
    latency 13 s.
  - Cause: the per-tick projections MOUSEOVER, PLAYER_STATE, UI_STATE,
    WORLD_MAP_STATE and ACTIVE_PERCEPTION were persisted (~35k rows each in
    30 min) and never trimmed.
  - **Fix:** these projections are ephemeral; the addon telemetry stays
    durable. `journal_size_limit` caps the checkpointed WAL at 64 MB.
- **Tests:**
  - objective-area MOVE (1);
  - POINTER lane (1);
  - ephemeral projections (1); one old test adjusted.
  - Suite: 18 baseline failures, no new ones.

## 2026-10-03 — Quest area from the minimap outline + FAST consumption rate (offline)

- **Quest area recognition (user request):**
  - Retail exposes only the quest POI centre. The objective area is drawn on
    the minimap as a light-blue outline (RGB ~73/115/146).
  - `vision/minimap_quest_area.py` segments the outline inside the minimap
    disc and fills it when closed. Output is in disc-normalised offsets.
  - Offline, on 1411 live Exile's Reach crops:
    - 937 detected, 597 closed;
    - the API POI lay inside the outline's box in 585 of the 597;
    - the POI was ≤ 4.2 yd from the learned area in 90 %;
    - north-up confirmed (bearing error ~4°), ~3.58 yd/px at a 44.7 px disc
      radius (~160 yd view radius).
  - Perception emits a `minimap_quest_area` MINIMAP_CV candidate.
  - `QuestAreaMemory` converts it to 4 yd WORLD_YARDS cells and attaches it to
    the unfinished quest whose POI is within 40 yd.
  - Use in planning:
    - inside the learned area counts as "in the objective area";
    - the quest-area roam uses coverage points spread over the learned shape
      instead of a 30 yd circle.
  - **Addon 0.9.43** exports `minimap_geometry.view_radius_yards`
    (`C_Minimap.GetViewRadius`), `zoom` and `rotate_minimap`. Without them,
    160 yd and north-up are assumed.
  - Replaying the live frames learned areas for quests 55122, 54951, 54952 and
    55174.
- **FAST rate ~12–14 Hz during FULL_AI:**
  - The addon/pixel source delivered ~32 fresh FAST packets/s (decoded
    ~39/s), but the agent consumed 14.2/s on average.
  - Agent-thread profile (4096 samples), top costs:
    - `entity_memory.recognize_visual`, ~18 %;
    - memory maintenance and metrics on the agent thread (COUNT(*) on the huge
      DB; 13 s query latency every 30 s);
    - JSON copies.
  - **Fixes:**
    - metrics use rowid ranges and indexed min/max at (395 ms → 122 ms on the
      live DB, cold) every 120 s instead of 30 s;
    - visual recognition at most once per track per 1 s;
    - the DB growth fix above removes the root of the slow queries.
  - Live rate still to be measured.
- **Tests:** `tests/test_minimap_quest_area.py` (5). Suite: 18 baseline
  failures, no new ones.

## 2026-10-03 — Campaign quests first (user decision: option B + C, offline)

- **Rule:**
  - a campaign "!" is always the next pickup, even when a side quest is
    nearer;
  - side quests are picked up when they are on the way (≤ 60 yd);
  - when no campaign quest is available or in progress (level/chain gate),
    side quests carry on;
  - no new campaign pickup while one is in the log.
  - While a campaign quest is open:
    - campaign proposals get +4 priority;
    - side-quest objective and turn-in trips farther than 120 yd are
      dropped.
- **Data:**
  - available quests already carried `is_campaign` from `C_QuestLine`; live
    confirmed (e.g. 54951 `is_campaign: true`);
  - active quests never had it: the addon called the non-existent
    `C_QuestLog.IsCampaignQuest`. **Addon 0.9.44** uses
    `C_CampaignInfo.IsCampaignQuest`, with the
    `C_QuestInfoSystem.GetQuestClassification` (Campaign) fallback.
- **Tests:** `tests/test_campaign_first.py` (5). Suite: 18 baseline failures,
  no new ones.

## 2026-10-03 09:42 — Porcupine hovered but not targeted (addon 0.9.42 still installed)

- The FULL_AI run lasted ~23 s; WoW still ran addon 0.9.42, not 0.9.44.
- A Prickly Porcupine was hovered for ~8 s during "Cooking Meat". Its tooltip
  read "Prickly Porcupine ~ Level 3 ~ Beast ~ Cooking Meat ~ 1/5 Raw Meat
  collected from wildlife", yet `quest_related` arrived empty.
  - The hostile TARGET rule needs `quest_related`, a configured npc_id, or an
    objective name match. "wildlife" names no creature, so nothing matched.
  - With the murlocs the objective text named them, so the name match
    covered such cases.
- **Fix (offline):** `tooltip_names_active_quest`, the same rule as the
  addon's, evaluated in Python. The unit's own tooltip (first line = its
  name) containing an unfinished active quest title makes it quest-relevant.
- **Open:** why the addon's own match returned nothing in this sample. Its
  code path looks correct; it needs a live check after installing 0.9.44.
- **Test:** `test_quest_npc_filter.py` (+1). Suite: 18 baseline failures, no
  new ones.

## 2026-10-03 13:01 — Assistant-run bounded FULL_AI trial (addon 0.9.44, user-authorised)

- **Confirmed live:**
  - addon 0.9.44 campaign flag (Cooking Meat `is_campaign=true`);
  - FAST consumption ~26 Hz in MANUAL (was ~14);
  - quest-area sweep and cell roam ("Quest keresési régió szisztematikus
    következő cellája");
  - quest-relevant hostile (Prickly Porcupine) proposed for TARGET.
- **Bug:** hover-confirm TARGET never clicked. Every 8 s, ~13× in a row, the
  attempt failed with `target_not_found`, although the addon confirmed the
  porcupine GUID under the pointer 0.5 s after the hover.
  - Cause: the skill runtime rewrites `state.phase` to "VERIFY" every tick,
    and the hover-pending check relied on the phase.
  - **Fix:** the pending hover is kept in the skill context (`hover_pending`)
    for TARGET and LOOT. LOOT also accepts loot that arrives during the hover
    wait.
  - Tests now overwrite the phase like the live runtime does.
  - Suite: 18 baseline failures, no new ones.
- FULL_AI was stopped by the assistant after the loop was identified (13:04).

## 2026-10-03 13:12-13:22 — bounded FULL_AI trial (PID 17996), COMBAT stall off-screen

- 13:12:36 COMBAT on Prickly Porcupine (`...161131-000040DFAA`): Charge (ACTIONBUTTON1) once, then the
  off-screen facing recovery sent ONE `TURNLEFT .075 s` and set `await_post_recovery_cast`.  Nothing was
  usable, the target stayed off-screen, and the await branch of `CombatSkill.verify` returned RUNNING with
  no commands every tick without checking the attempt deadline: **no input for ~4.5 min** (phase
  SELECT_ABILITY), then OUT_OF_RANGE at 13:17:41.  Loop rates were normal (fast control 22-29 Hz, step
  35-60 ms) — not a brain-Hz problem.
- Fix (offline-tested, `tests/test_combat_offscreen_stall_20261003.py`): post-recovery cast wait bounded
  to 1.5 s and the deadline; the off-screen facing recovery now continues through the visual-follow
  reacquire (bounded 3 s) instead of waiting for a cast; an attempt that issues nothing for 6 s while the
  target is neither on screen nor in melee range fails `FACING_FAILED` (`combat_stalled`) for a replan.
  **Not yet live-validated.**
- Rest of the trial (old code): 4 further COMBAT successes, 2 LOOT successes (quest progress 55174),
  4 LOOT `CORPSE_NOT_FOUND` (open).

## 2026-10-03 13:33-13:41 — bounded FULL_AI trial (PID 17996, old combat code still loaded for planning)

- 13:36:38 porcupine killed in melee (XP +27, 4/5 Raw Meat) but **no LOOT**: the corpse lay under/behind the
  character model (screenshots 0263/0264), no corpse anchor existed.  Open: hidden-corpse loot path.
- 13:36:39-13:37:38 Coastal Goat (neutral) selected and standing in melee over the character (0285): 0 rage,
  Charge min range 8 yd, Slam lacks rage, auto-attack admissible only with a screen box -> **WAIT ~60 s**;
  then COMBAT right-clicked the goat's box, which overlapped our own model -> no attack, COMBAT_TIMEOUT.
  Same again 13:39-13:41 with a porcupine (0479).
- Fixes (offline-tested): auto-attack by `INTERACTTARGET` (F7, matches the cache) when a harmful melee action is
  in range, no screen position needed (`SkillRegistry._auto_attack_available`, `CombatSkill._auto_attack_fallback`);
  quest relevance judged from the mouseover/tooltip before TARGET is remembered per GUID
  (`WorldModel.quest_relevant_units`, used by `combat_planning`); LOOT hover retries walk a 5-point pattern
  around the remembered corpse point (`CORPSE_SEARCH_OFFSETS`).
- Binding note: client reports `TARGETLASTTARGET` = F2, the selected bindings cache says F1 (mismatch) — not used.
- Soft targeting is live: `softenemy` exported (Coastal Goat / Prickly Porcupine); nameplates on screen but the
  nameplate export stays `{}`.

## 2026-10-03 13:42-14:19 — continuous bounded trials (user: "mehetnek a tesztek folyamat")

- **Live-validated:** auto-attack by `INTERACTTARGET` (13:46 Coastal Goat killed); Raw Meat **5/5** reached
  13:52:42 (COMBAT→LOOT chain); death recovery (addon 0.9.45): 14:15:34 ghost MOVE (`CORPSE_RUN`) to the
  C_DeathInfo corpse, 14:15:44 `DEATH_RECOVERY` Resurrect Now, questing resumed.
- 13:46:09 `softinteract` exported the exact dead goat GUID while the corpse hover search missed it ->
  LOOT now uses the interact key on an owned soft-interact corpse (offline-tested).
- 13:52:47-13:54 after 5/5 the goat tooltip still listed "Cooking Meat ~ 5/5 ..." (greyed, check-mark) and
  three more goats were killed -> completed n/m tooltip lines no longer count (addon flag and Python rule);
  remembered creature types (persisted in `output/agent/quest_relevant_npcs.json`) are tied to the
  objective text.
- 13:57-13:59 **character died**: "Target needs to be in front of you" with the goat beside the character;
  the facing recovery turned blindly for 3 s without attacking and failed, then COMBAT was not admissible
  in combat (Retail secrets: no range/usable values) -> 80 s WAIT under attack.  Fixes: facing sweep
  (35° turn + attack key while the client keeps answering "not in front", 10 steps), in-combat admission
  for a live hostile target, auto-attack with unknown range in combat.  Not yet live-validated.
- "Cook the meat on the campfire" arrives as an `item` objective; cook/burn/open clauses now classify
  as object interaction (OBJECT_USE via tooltip "Campfire").  Not yet live-validated.
- Death at 13:59 also showed the agent had no death handling (MANUAL stop); addon 0.9.45 + DeathRecoveryPolicy.
- 18:07 the client had been disconnected while idle (WOW51900319, after ~4 h in MANUAL).  User confirmed the
  realm is their own server (not official); the Battle.net launcher targets the live realm and is not used.

## 2026-10-03 evening — offline replay work (user away; client disconnected)

New tool `tools/replay_telemetry_decisions.py` replays a recorded `telemetry-*.jsonl` through an offline
agent (RecordingExecutor, no client input).  Findings and fixes, all offline-tested, **not live-validated**:
- Campfire (Cooking Meat step 2): the object name arrives only in a slow-lane `MOUSEOVER_CHANGED` event
  (FAST mouseover for objects is `{}` / bare quest flag) and the FAST reducer dropped events carried in
  merged control payloads (no full snapshot 77-97 s).  The newest change event is now attributed to a
  still cursor (`effective_mouseover`); replay of 14:15: OBJECT_USE right-clicks the Campfire at 85.9 s.
  YOLO saw the campfire only as `unknown_subject_candidate` (conf .27-.30) — data for a future class.
- FAST mouseover `quest_related` for creatures (no text) now needs an open creature objective in the
  quest log; replay of 14:15: no goat combat after 5/5.
- Planner policies receive a `WorldSnapshot`: the new soft-interact/hidden-corpse paths crashed there
  (AttributeError) and compared runtime-clock ownership with addon GetTime — both fixed; engine test.
- Empty INSPECT hovers: same point hovered 11-12x in ~100 s live; 25 s same-view suppression; replay of
  13:47 hovers (0.49, 0.42) once.
- Fatal fight replay (13:57): new code fights throughout (facing sweep + Slam), no 80 s WAIT.
- Memory moved from `output/agent/pid-<PID>/` to `output/agent/profiles/<user>/` (agent/entity/point
  memory, quest-relevant creature types; migrated from pid-17996).  Per-PID folders keep logs/captures.
- Export-only start: no bindings cache -> connect without key input/FULL_AI, wait for the addon binding
  export, create a controller cache, reconnect and arm (`AUTO_START` on a fresh PC).
- Install wizard (user: "szűz PC-re feltelepül és már indítható"): one-click "Minden egyben telepítés"
  (packages + TensorRT on NVIDIA, addon 0.9.45, maps → vmaps → mmaps 2175, engine for this GPU, local env
  incl. `AIPC_WOW_EXE`, desktop shortcuts); new "Automatikus indítás" step stores the login the user types
  (config/, local plain text); finish page starts AUTO_START; INSTALL_WIZARD.bat offers winget Python.
  Pages render (screenshots); not yet run end-to-end on a fresh PC.
- AMD/Intel GPUs (user: "és ha a másik gépen AMD GPU van?"): no CUDA/TensorRT there.  Without CUDA and with
  `onnxruntime-directml`, the detector loads `world3d_units_3class_v10_e65.onnx` and puts DirectML first
  (`vision/world3d/directml.py`); Ultralytics' auto-install of plain onnxruntime is suppressed.  Verified on
  this PC in an isolated CPU-torch + ultralytics 8.4.172 + onnxruntime-directml 1.24.4 venv: providers
  [Dml, CPU], 17.7 ms/frame end-to-end (CPU 251 ms), same detection (creature 0.80).  Not yet run on an
  actual AMD card.  The wizard detects the GPU vendor and installs onnxruntime-directml for AMD/Intel.

## 2026-10-03 23:47–23:58 trial (PID 15020) — Cooking Meat

- LIVE-VALIDATED: OBJECT_USE on the Campfire at 23:48:52 credited "Cook the meat on the campfire" (1/1); quest 55174 became complete. The campfire name came from the FAST-lane MOUSEOVER_CHANGED event memory (`effective_mouseover`).
- FAILED: at 23:49:17 a MOVE wedged the character between a post and a rock. RECOVER BACKWARD did not move it, so the stuck ladder went on to MARK_DANGER and replanning, which cannot free a wedged character. Fix (offline only): a physical escape that did not move is followed by the next untried physical escape (JUMP_FORWARD, STRAFE, TURN) before the learning/replanning steps; steps are not repeated within an episode, and the tried set survives a resumed ladder. Tests: `test_stuck_wedged_20261003.py`, `test_stuck_resolver.py`.
- FAILED: the turn-in "?" SEEK at the API turn-in point (-245, -2492) found nothing. An OPEN_MAP issued in a tick without the turn-in point then stayed open. The actionable-turn-in branch skips the map policy that closes it, and SEEK is unavailable over an open map, so the agent ran WAIT from 23:50 until it was stopped at 23:58. Fix (offline only; replay-confirmed): CLOSE_MAP when a turn-in point is known and the map is open (`planner.py`, `test_turnin_open_map_20261004.py`).
- Open issue: the turn-in NPC (Alaria) is still not recognised by the "?" vision search ~11 yd from the API point.

## 2026-10-04 00:02–00:08 trial (PID 15020) — turn-in search, stuck in WAIT

- CLOSE_MAP at the known turn-in point ran live (00:02:50, 00:02:56); the map no longer stays open.
- The agent targeted Alaria (00:03:05, TARGET via the API-identified mouseover) but did not turn in. The turn-in search MOVE started at 00:03:22.
- FAILED: from 00:03:29 FULL_AI showed `telemetry_suspended_waiting_for_stable_recovery` until it was stopped. Telemetry streamed at ~38 Hz the whole time; brain ticks stayed frozen at 40. Root cause, reproduced offline: during an active reach the FAST lane consumed every packet without updating world receive-liveness. Empty polls between packets ran medium ticks that re-armed the 1 s reach window, so no medium tick ingested a packet. After 6 s the world looked stale and never recovered. Fix (offline only): a consumed FAST packet updates `last_received`; an empty poll during an active reach waits for the medium slot; on recovery the status decision no longer keeps the suspension reason. Test: `test_fast_lane_freshness_20261004.py`.
- User rule from now on: live trials last at most 3–5 minutes (`--trial-seconds 300`).

## 2026-10-04 00:22–00:28 trial (PID 15020, single agent) — Cooking Meat turned in

- LIVE-VALIDATED: Cooking Meat (55174) turned in to Alaria at 00:23:47 (VISUAL_APPROACH to the mouseover-identified friendly target, then a QUEST_DIALOG click). The next campaign quest, Enhanced Combat Tactics (59254), was accepted at 00:25:32.
- Found: the first INTERACTTARGET got "You need to be closer" (code 852), but the verifier dropped the event (its addon observed_at lagged the snapshot clock by 6 s) and reported no_response. Fix (offline): event sequence ordering. Test: `test_interact_range_event_sequence_20261004.py`.
- Found (user observation): with a friendly target selected (Alaria after the turn-in), the planner's only proposal was WAIT "REACH_OBJECT nem indulhat ..." (range-blocked, no world position, no anchor); this hid the search fallbacks until the user pressed Esc. Fix (offline, replay-checked): that WAIT lasts only 10 s per range block. Not yet validated live.
- Earlier 00:16 trial: two agents ran on the same PID/profile DB ("database is locked"), because a finished trial's GUI stays open. `wow_auto_start.py` now refuses to start a second agent for the same PID.
- Open: 59254's objective NPC (Captain Garrick) is the yellow minimap dot next to the player inside the camp outline; the agent stood inside the learned area and only searched visually. No WoW API exposes minimap blips or NPC positions; the minimap dot bearing is the remaining evidence.

## 2026-10-04 00:40–00:51 trials (PID 15020) — minimap quest dot, Enhanced Combat Tactics

- New: `vision/minimap_quest_dot.py` detects yellow quest-objective dots in the minimap disc; perception publishes `minimap_quest_dot`. Offline over ~1500 live frames, dots appeared only while 59254 was active, with no foliage false positives. The planner walks to the nearest dot (`APPROACH_MINIMAP_QUEST_DOT`) when no unit is selected (a selected unit is also drawn yellow, per the user). The walk now stops at 15 yd (Charge band 8–25 yd, per the user) and hands over to COMBAT/INTERACT when the selected target is named by an open objective.
- 00:41 FAILED: the dot MOVE stood still. Detour's first corner was 1.1 yd from the player; every replan (the danger map changed with nearby mobs) restarted the route at that corner, which counted as arrived, so no movement command was ever issued. Fix: skip route anchors within 3 yd of the player after (re)planning (`test_route_start_corner_20261004.py`). Reproduced offline before the fix.
- 00:47 LIVE: with the route fix the dot MOVE walked to Captain Garrick (-241,-2538 → -211,-2513). Garrick pushed the walking player back until the MOVE timed out. Then FOLLOW_INSTRUCTION pressed Charge (ACTIONBUTTON1) on Garrick's instruction, and the objective went 0/3 → 1/3 → 2/3 → 3/3 (Charge/Slam). Enhanced Combat Tactics objective complete (user confirmed). Before handing over to the dot-stop/interrupt changes, COMBAT spent 30 s pressing Slam out of range (OUT_OF_RANGE).

## 2026-10-04 00:52–00:58 and 08:51 (user-run) — Enhanced Combat Tactics turn-in

- FAILED (both runs): Captain Garrick, the turn-in NPC, was selected (friendly after the sparring) about 15 yd from the completed quest's API turn-in point. The friendly-target branch had a range block and no fresh anchor, and returned the turn-in route MOVE (priority 114). The agent kept moving to the point, inspecting and opening the map instead of talking to Garrick (the user confirmed it had found him).
- Fix (offline; the user's 08:51 process predates it): a selected friendly unit that is named by a completed quest's objective text, or selected within 35 yd of a completed quest's turn-in point, gets INTERACT (priority 116, purpose TURN_IN_CANDIDATE) unless it was recently unresponsive. A range error uses INTERACT's own approach recovery. Test: `test_turnin_selected_npc_20261004.py`. A replay of the 08:51 telemetry with the new code issues INTERACTTARGET on Garrick at once.

## 2026-10-04 08:55 (user-run, new code) — turn-ins

- LIVE-VALIDATED: Enhanced Combat Tactics turned in to Captain Garrick (selected 57.7 s, quest frame 71.3 s, turned in 73.4 s) via the new TURN_IN_CANDIDATE INTERACT. Northbound accepted from Alaria at 84–88 s (complete on accept). The agent then travelled to Austin Huxworth (turn-in, ~(-151,-2642)).
- FAILED at the end: Huxworth was selected and on screen as a GUID-bound World3D track (`BOUND_WORLD3D_TRACK`, nameplate-confirmed). INTERACTTARGET got "need to be closer" three times and no approach ran; the agent turned away and lost him. Two causes: (1) INTERACT's visual approach, the VISUAL_APPROACH availability check and the planner's anchor freshness accepted only mouseover/nameplate-API anchors; (2) the bound track's sample time (runtime clock) was 0.2–3.6 s *newer* than the addon snapshot clock, and every freshness test required a non-negative age. Fix (offline): accept bound/target World3D tracks and ages down to −5 s. Test: `test_bound_track_approach_20261004.py`.
- User rule from now on: the user starts live tests; the assistant does not.

## 2026-10-04 09:01–09:10 (user-run) — two quests, rock stuck

- LIVE: Northbound turned in to Austin Huxworth (78 s). Quilboar Shadow Magic (55184) and Down with the Quilboar (55186) were accepted.
- FAILED: the agent headed for the farther quest (55186, 203 yd) through the nearer one's area (55184, 180 yd). Both MOVEs had identical utility: the WORLD_YARDS destinations were measured against the normalized map position and both hit the 20-point distance cap, so the quest-log order decided. Fix (offline): equal-utility MOVEs are ordered by real world-yard distance (the utility values are unchanged, so existing MOVE/SEEK priorities hold). Test: `test_move_distance_ranking_20261004.py`.
- FAILED: walked into a rock (not in the mmaps). BACKWARD did not move it; the ladder chose JUMP_FORWARD, but the planner's next query got "awaiting step result" without an action, so SEEK and a fresh MOVE ran. The user saw backing and jumping, then the agent took the same heading into the rock again: no obstacle was marked, because MARK_DANGER now follows the physical escapes and a successful escape ends the ladder. Fixes (offline): (1) the ladder step chosen on a failed result is handed to the next recovery query once; (2) a MOVE failing with supported_stuck marks a 90 s obstacle in front of the character at once, so every replan inserts a navmesh-validated left/right detour. Tests: `test_recovery_directive_handoff_20261004.py`.

## 2026-10-04 09:13 (user-run, with the distance tie-break)

- LIVE: the first MOVE went to the nearer quest (55184, 183 vs 205 yd), so the tie-break works. Inside the 55184 area at 1/7 (104 s, 16 yd from its POI) the area's own MOVE is suppressed for local search; with no quilboar in view, the other quest's route MOVE and its minimap dot (Grek'og, priority 92) won. The agent left, killed Geolord Grek'og (55186 complete at 139 s) and stood there. The user saw it pick the farther quest.
- Fix (offline): while the player is inside an unfinished quest's objective area, MOVEs and minimap-dot moves for other quests are held back for up to 120 s. Test: `test_local_area_focus_20261004.py`.
- Open: why the local search inside the 55184 area found no quilboar to fight.

## 2026-10-04 09:18 (user-run) — left the open quest for a turn-in dot; corpse inspects

- FAILED: Quilboar Shadow Magic (55184) stayed at 2/7. The agent walked north toward Down with the Quilboar's turn-in (~(105,-2415)) via APPROACH_MINIMAP_QUEST_DOT. The yellow dot was 10–15 yd from that completed quest's turn-in point (its ender), but with a single open quest the dot was attributed to 55184 without any distance check (200 yd from its POI). Fix (offline): ignore dots within 30 yd of a completed quest's turn-in point; attribute a dot to the single open quest only when that quest has no POI of its own. Test added to `test_minimap_quest_dot_20261004.py`.
- FAILED (user): the area was barely covered; there were seven INSPECT hovers on the same dead Quilboar Geomancer and two on the player. Fix (offline): a hover that ends on a dead unit or the player suppresses that screen point and its World3D track for 120 s (`test_inspect_empty_hover_20261003.py`).
- Idea from the user (not implemented): the selected target is drawn on the minimap as a gold-ringed dot in its reaction colour (red hostile, yellow neutral, green friendly), shown only while it is targeted; it would give an off-screen target's bearing and distance (casters). At the 843x475 capture resolution the marker is ~4–6 px; the existing captures gave no reliable red/green sample, so calibration frames are needed.

## 2026-10-04 09:28 — selected-target minimap marker (user screenshots)

- New: `vision/minimap_target_marker.py` detects the selected unit's minimap marker: a reaction-coloured core (green #3cac1f friendly, yellow #dfb125 neutral, red #7f1804–#9c0b05 hostile) inside four cream/gold crosshair pips at 0.03–0.085 disc radii. Perception publishes `minimap_target_marker`. When the selected target has no world position and exactly one marker matches its reaction (or its attackable flag), the world state sets `target.world_position` (source `MINIMAP_TARGET_MARKER`, estimate, `z_known: false`). Existing REACH/INTERACT/COMBAT approaches then work for off-screen targets (casters). Offline only; fixtures in `tests/data/minimap_target_marker/`.
- Found while calibrating: the yellow quest-dot detector also took the turn-in "?" glyph (a tall, thin stroke) and the yellow target marker as quest dots, which is why the agent walked to the Down with the Quilboar ender. Glyph-shaped blobs (taller than wide) and crosshair-marked blobs are now excluded. Over all ~1500 live captures, the 09:18 run yields no dots any more, while the Garrick dot (00:22–00:28) is still detected.

## 2026-10-04 09:34 (user-run) — stuck at the quest reward frame (addon 0.9.46)

- FAILED: turning in Quilboar Shadow Magic (55184), the quest frame offered one item reward (Expeditionary Plate Warboots). The addon exported `REWARD_SELECT` with that single choice at x=0,y=0 and hid Complete Quest, so QUEST_DIALOG had nothing to click. Retail gives a single reward on Complete Quest (user: "nem is lehet választani").
- Fix (addon 0.9.46, installed into WoW AddOns; needs /reload): REWARD_SELECT only for two or more choices; reward buttons are looked up in `QuestInfoRewardsFrame.RewardButtons` first (the old global names gave no coordinates). Lua syntax checked with lupa; the package test was updated. Not validated live.

## 2026-10-04 09:40 (user-run) — The Scout-o-Matic 5000 (addon 0.9.47)

- LIVE: addon 0.9.46 was loaded; Quilboar Shadow Magic was turned in with its single item reward, so the REWARD_SELECT fix is validated live.
- FAILED: "0/1 Use Scout-o-Matic 5000 to scout the area" arrives as a `monster` objective (normalized KILL). The Scout-o-Matic (Vehicle GUID, npc 156518, not attackable) was hovered, but a friendly NPC is irrelevant to a KILL objective, so it was never selected or used. Its tooltip did list the objective line.
- Fixes (offline): "Use <unit> to ..." on a monster/KILL objective is classified INTERACT_NPC with `target_entity.name` taken from the text. For a `Vehicle-` GUID the selected unit gets INTERACT (not TALK). Addon 0.9.47 (installed) exports `in_vehicle`, `has_vehicle_ui` and `on_taxi`. The interaction verifier accepts entering a vehicle, and the planner WAITs while riding (out of combat). Test: `test_use_npc_objective_20261004.py`.
- Vision note: the runtime YOLO (`world3d_units_3class_v10_e65`) classes are creature_unit_like / quest_object_outline_like / overhead_symbol_like. The Scout-o-Matic track was `creature_unit_like` (0.39). In the 843x475 capture its box had no yellow outline pixels at that distance. `quest_object_outline_like` maps only to object candidates (INSPECT priority x2); there is no class for an outlined quest *unit*.

## 2026-10-04 10:25 (user-run) — Scout-o-Matic ignored, Lindie targeted

- Vision: YOLO does see the airborne Scout-o-Matic region. Several `creature_unit_like` tracks sit in the top 30% of the screen; learned subject boxes are not dropped by the top-band UI exclusion (only object-class boxes are). The Scout-o-Matic was hovered six times.
- FAILED: the INTERACT_NPC classification made *every* friendly NPC relevant, so Lindie Springstock (59 hovers) was selected and visually approached again and again, and a player (Durukann-Turalyon, 44 hovers) was hovered. Fix (offline): when the ready NPC objectives name their unit ("Scout-o-Matic 5000"), only a unit with that name is relevant through the objective path; quest-symbol and turn-in-proximity relevance are unchanged. Test added to `test_use_npc_objective_20261004.py`.

## 2026-10-04 10:33 (user-run) — SEEK_VISUAL_CUE/WAIT loop

- FAILED: for minutes the agent alternated SEEK_VISUAL_CUE (purpose SEARCH_LOCAL_OBJECTIVE_AREA) and WAIT. Each SEEK issued no commands and "succeeded" in 0.1 s, because its postcondition (a visible unknown candidate) already held. Its proposal also filters out the WORLD3D INSPECT hovers, and the scan counter advances only on failure, so nothing was hovered (not the Scout-o-Matic either); moving the cursor by hand changed nothing.
- Fix (offline, replay shows INSPECT hovers and real SEEKs alternating): this local SEEK is not re-proposed within 12 s of the previous one; meanwhile the INSPECTs go through. Test: `test_agent_map_discovery.py::test_local_objective_seek_that_ended_at_once_lets_inspect_through`.

## 2026-10-04 10:40 (user-run) — Scout-o-Matic done; Re-sizing the Situation

- LIVE-VALIDATED: The Scout-o-Matic 5000. The agent selected the Scout-o-Matic (57.6 s), used it and sat in the vehicle (in_vehicle 64–154 s; addon 0.9.47). It WAITed through the ride and the cinematic (telemetry gap); 1/1 credit came at 132 s. It turned the quest in to Lindie, accepted Re-sizing the Situation (56034) and used the Re-Sizer on a Wandering Boar (1/3 at 209 s).
- FAILED (user): it charged the boar first. "0/3 Re-Sizer v9.0.1 tested on Wandering Boars" (normalized USE_OBJECT, quest special item) matched the boar's name, so COMBAT (91) outranked OPEN_BAGS (87; the item is not on the action bar). Fix (offline): when every matching (or ready) objective is an item-use objective (USE_ITEM / USE_ITEM_ON_TARGET / USE_OBJECT), the target is not combat-relevant out of combat; an attacker is still fought. Test: `test_item_use_no_combat_20261004.py` (fails without the fix).

## 2026-10-04 10:48 (user-run) — Re-Sizer on far boars (addon 0.9.48)

- Evidence: the agent never issued a deliberate item use. Credit 1/3 (10:44 run) followed a COMBAT whose auto-attack fallback pressed INTERACTTARGET on the boar at 496190.3; the player then cast spell 305716 and the objective advanced: Retail's Interact key uses an active quest's special item on its objective target. Credit 2/3 (10:52 run) had no interact press within 20 s; its cause is unexplained. The user did not click the item.
- FAILED: with a far boar selected nothing happened: (1) the Re-Sizer (bag 0 slot 10) had no screen coordinate: Retail 12 pooled/combined bag buttons were not found and the inventory cache was not refreshed after the bags opened; (2) the item block was skipped whenever local search proposed a SEEK; (3) there was no approach for an item target.
- Fixes (offline): addon 0.9.48 (installed; needs /reload) finds bag buttons via `EnumerateValidItems` incl. ContainerFrameCombinedBags and refreshes the inventory while bags are open. USE_ON_TARGET gets an `INTERACT_KEY` activation (INTERACTTARGET) when the selected target matches the item-use subject and the special item is in the bags. The item block is no longer skipped for a selected matching target. UseItemSkill ends on new RANGE / FACING / LINE_OF_SIGHT UI errors (user: "mindent"; `classify_ui_error`, `new_ui_errors`). On any of these the planner approaches the target (VISUAL_APPROACH on its screen anchor, else MOVE to its world/minimap-marker position), then retries the item. Tests: `test_item_use_no_combat_20261004.py` (12).

## 2026-10-04 11:02 (user-run) — Re-Sizer done; Giant Boar not mounted

- LIVE: Re-sizing the Situation reached 3/3 (65 s) and was turned in to Jaina; Ride of the Scientifically Enhanced Boar (55879) was accepted.
- FAILED: "0/1 Ride the Giant Boar" (monster → KILL). The Giant Boar is not attackable, so as with the Scout-o-Matic it was not relevant: the agent walked there with the cursor on it, then hovered other units. Fix (offline): the clause is generalized to use/ride/mount/board/enter <unit> → INTERACT_NPC (a "Use <item> on <unit>" clause is excluded), and such text-named units get INTERACT (mount/use) instead of TALK. Tests added to `test_use_npc_objective_20261004.py`.

## 2026-10-04 11:06 (user-run) — Giant Boar mounted; driving it (addon 0.9.49)

- LIVE: the agent mounted the Giant Boar ("1/1 Ride the Giant Boar" at 136 s; in_vehicle True, has_vehicle_ui False). The next objectives (Wowhead quest 55879): 0/8 Monstrous Cadaver slain, then Torgok.
- FAILED: the agent WAITed as a passenger ("taxi"). The boar's abilities sit on an override page fired by ACTIONBUTTON1..12, but the exported actionbar showed the player's own unusable spells. The user: steer the boar (MOVE), find cadavers visually (no quest area), and charge from range with ability 1, because walking into melee gets the player knocked back.
- Fixes (offline): addon 0.9.49 (installed; needs /reload) exports `vehicle_bar` (active vehicle/override/temp-shapeshift page via HasVehicleActionBar/HasOverrideActionBar/... with ACTIONBUTTONn bindings, range, usability); its fast lane follows that page, so the charge range is fresh. The world state replaces `actionbar` with the vehicle actions (`vehicle_controls`), so COMBAT/VISUAL_APPROACH use the boar's abilities; the approach already stops as soon as a harmful ability is in range, then COMBAT presses it. The passenger WAIT applies only without vehicle controls. Tests: `test_vehicle_bar_20261004.py`.

## 2026-10-04 11:19 (user-run) — Monstrous Cadavers not attacked

- Observed (addon 0.9.49 live): the vehicle bar works. ACTIONBUTTON1 = Trample (305556; instant, untargeted, 1 s cooldown per Wowhead, max_range 0), usable. The Monstrous Cadaver the user selected is `ClientActor-3-4-2127`, attackable false, so no combat path applied; the agent neither attacked nor inspected it.
- Fix (offline): new VEHICLE_ABILITY skill (press the vehicle bar binding; success on cast event, cooldown start or objective progress). While `vehicle_controls` is set and the selected unit matches an open KILL objective by name (any GUID kind), the combat planner drives at it: VISUAL_APPROACH (purpose VEHICLE_ATTACK, stops at bbox height 0.085), or a MOVE to its world/minimap position, then presses Trample once close — not running into it (user: knockback). While riding, a hovered unit named by an open KILL objective is selected. Tests: `test_vehicle_bar_20261004.py` (6). The 0.085 trample distance is an estimate to tune live.

## 2026-10-04 — vision dataset rewritten for detector training

- User: the `vision-dataset` crops (400 PNGs of 14x18 to 44x76 px with an addon mouseover label) are useless for training. Agreed: a detector needs full frames with every object boxed. A crop has no background or negatives, and a frame with only the confirmed box would teach the model that other units are background.
- New format (`vision_dataset.py`): `images/<id>.jpg` (full frame), `labels/<id>.txt` (YOLO, classes of the runtime model: creature_unit_like / quest_object_outline_like / overhead_symbol_like), `meta/<id>.json`, `data.yaml`. Each sample holds the addon-confirmed mouseover box plus the model's other non-coasting detections (confidence ≥ 0.25) as MODEL_PRELABEL boxes, marked `NEEDS_REVIEW`. Old crop files stay in the directory root and are no longer counted. Offline tests only.

## 2026-10-04 12:15 (user-run) — Giant Boar: own boar box was the "target", Trample misread

- Observed (journal + telemetry, session 1791108799): Trample (ACTIONBUTTON1) was pressed 4 times. Each press produced a "player" `SPELLCAST_FAILED` (Cast-2-0-0-0-305556-…), arriving ~3 s later on the slow lane, yet the boar lunged ~30 yd along its facing in ~2 s every time (e.g. 153.2,-2399.0 → 121.0,-2386.8 at facing 2.81). One lunge was followed by QUEST_LOG_CHANGED. Knockback was seen too: at 109–116 s the boar drove 65 yd straight with W and was then pushed ~20 yd back by a cadaver in its path.
- Root causes (offline):
  - The selected-target anchor searched "below" a BOUND_WORLD3D_TRACK centre (nameplate logic). Under a distant cadaver that found the own boar + rider box, which the fixed lower-centre self band does not cover at the vehicle camera (box y .32–.59). `last_target_boxes` then remembered it, so steering and the "close" check (bbox ≥ .085) followed the own avatar.
  - VISUAL_APPROACH with purpose VEHICLE_ATTACK had no ready state. It drove forward until the track was lost (TARGET_LOST) or it bumped into a cadaver.
  - TARGET verify failed IDENTITY_UNCERTAIN ~0.1 s after the click because the addon still reported the previous target.
- Fixes (offline, not yet live-validated):
  - Self avatar: `SelfAvatarIdentifier` (self_avatar.py), held per WorldModel. It is zoom, mount and vehicle independent and masks no pixels. Evidence:
    - hover GUID = player or `vehicle_guid`;
    - ego-rotation (a box stays screen-fixed while the facing turns ≥ 0.17 rad, seen twice);
    - focus geometry (centred, contains the orbit focus ≈ (.5,.52); a unit in front is drawn above it);
    - a confirmed spot follows gradual zoom;
    - vetoes: a box that moved with the world while turning, or one a hover named as another unit.
  - Target anchor: a bound track uses its own box only, never the self box.
  - Vehicle abilities are generic (user: every quest vehicle differs), in `vehicle_abilities.py`:
    - use mode = learned effect (a ≥ 6 yd forward lunge after a press → FORWARD_DASH) > live tooltip text > spell range (TARGETED);
    - FORWARD_DASH: VISUAL_APPROACH purpose VEHICLE_AIM turns in place, then presses the ability once the box is on the centre line. A non-self box ≥ .10 tall on the centre line triggers a reflex press (priority 105);
    - aims include hover-confirmed objective units, not only the selected target, and the nearest (tallest) box wins;
    - VEHICLE_ABILITY verify accepts a cast of any unit, the cooldown, objective progress or the observed lunge, and ignores the player-unit FAILED; timeout 3 s.
  - TARGET verify waits while the previous target is still reported.
  - Addon 0.9.50 (installed; needs /reload):
    - `vehicle_guid`, `camera_distance` (GetCameraZoom);
    - vehicle bar `description` (C_Spell.GetSpellDescription);
    - UNIT_SPELLCAST_* for vehicle/pet units with a `unit` field.
- Tests: `test_self_avatar_vehicle_20261004.py` (12), `test_vehicle_bar_20261004.py` (updated), `test_m0_target_skill.py` (+1).
- Unresolved: GetCameraZoom / vehicle GUID / vehicle cast events are unverified live on 12.1; the dash tolerance (aim_tolerance) and reflex height (.10) need live tuning; the Torgok objective is untested.

## 2026-10-04 — local LLM (Ollama) for quest/ability/speech text (offline)

- User: use the local AI for complex quests; ignore the v4 "M0 without LLM" rule (outdated). Simple "X slain / X collected" quests stay deterministic.
- Ollama is installed and was started by the assistant on the user's request (`ollama serve`, 127.0.0.1:11434). Installed models: llama3.2:3b, llama3:8b, deepseek-r1:7b. No qwen2.5 yet, so it is not downloaded (needs the user's OK).
- New `semantic_advisor.py`:
  - **Calls:** one background worker on CPU by default (`num_gpu` 0, 4 threads; the RTX 2050 4 GB is shared with WoW/YOLO). Never on the control path.
  - **Cache:** answers are cached per quest/spell/sentence in the profile (`semantic_cache.json`).
  - **Constraints:** answers use a fixed JSON shape with enums, and names must be copied from the game text. NPC speech that is not an instruction carries no ability.
  - **Tasks:**
    - per-objective quest interpretation, only for complex quests (special item, ride/use/object/escort/unknown wording);
    - vehicle-ability use mode;
    - NPC-speech instruction parsing.
  - **Consumers:**
    - QuestModel hints: fill UNKNOWN, turn ride/talk "monster" objectives into INTERACT_NPC, and on complex quests correct an API KILL/COLLECT to USE_ITEM_ON_TARGET/INTERACT/ESCORT/DEFEND when the answer copies names from the text;
    - `vehicle_abilities.ability_mode` (learned > explicit tooltip words > LLM > range);
    - an ability an NPC named is preferred.
  - Config: `config/ai_decision.json` → `semantic`; env `AIPC_SEMANTIC_ENABLED` / `AIPC_SEMANTIC_MODEL`; the test suite disables it.
- Addon 0.9.51 (installed; needs /reload): quest text captured from the quest dialog (GetQuestText/GetObjectiveText/GetProgressText/GetRewardText), or from GetQuestLogQuestText(index) guarded against index-ignoring. It is kept per character and exported one quest per snapshot as `quest_text`.
- Benchmark (`tools/semantic_benchmark.py`, `data/semantic_benchmark/cases.json`: 21 objectives, 6 abilities, 4 speech lines; LIVE + SYNTHETIC), llama3.2:3b, CPU:

  | Run | Action | Target | Item | Mode | Instruction | Ability | Median |
  |---|---|---|---|---|---|---|---|
  | whole quest per call | 15/21 | 18/21 | 3/5 | 5/6 | 3/4 | 2/4 | 6.2 s |
  | per objective + typed prompt | 20/21 | 19/21 | 3/5 | 5/6 | 3/4 | 4/4 | 4.8 s |

  First call after load ≈ 27–42 s. Remaining errors: Trample read as CLOSE (the explicit tooltip words win before the LLM); "Cook the meat on the campfire" read as an item use (the deterministic object-clause rule keeps INTERACT).
- Tests: `test_semantic_advisor_20261004.py` (10). Full suite: 18 baseline failures, 2243 passed.
- Not live-validated: no agent run with the advisor yet; qwen2.5 is not benchmarked.
- Model choice (same benchmark; user approved replacing the models): `qwen3:4b-instruct-2507-q4_K_M` (2.5 GB) scored action 19/21, target 21/21, item 2/3, mode 6/6, instruction 4/4, ability 4/4, median 6.1 s. Its errors (UNKNOWN for "Abilities proven…", COLLECT for "…bandaged") cannot change a type under the hint policy, so it is now the default. Removed at the user's request: deepseek-r1:7b and llama3:8b (too large for the 7.7 GB RAM).

## 2026-10-04 — turn-in NPC from the quest's own words (offline)

- Problem (earlier live runs): with no API for a quest's ender, the agent inspected several NPCs at a hub before finding the right one.
- Addon 0.9.52 (installed; needs /reload):
  - records the quest giver at QUEST_DETAIL (`UnitName/UnitGUID("npc")`) as `giver_name` / `giver_guid`;
  - records the ender at QUEST_COMPLETE as `ender_name` (ground truth for later checks);
  - exports both in `quest_text`.
- `quest_turn_in.py` decides the ender in this order:
  1. an explicit "Return to / Report to / Speak with / Bring … to <Name>" in the waypoint, objective, objectives, completion or progress text;
  2. "report / come back to me" → the recorded giver;
  3. the local LLM `turnin` task (semantic_advisor), only when 1–2 found nothing. Its answer must be GIVER or a name copied from the text.
- Published as `state["quest_turn_in_names"]` and used for completed quests:
  - `friendly_npc_relevant` (hover → TARGET of that NPC only);
  - `_turn_in_candidate` (the selected ender → turn-in INTERACT).
- Tests: `test_quest_turn_in_20261004.py` (4). Full suite: 18 baseline failures, 2247 passed. Not live-validated (needs quests accepted after the /reload, so their dialog text is captured).

## 2026-10-04 — live-capture retention and per-quest visual prototypes (offline)

- Live captures filled the disk (user). `LiveCaptureRecorder` now keeps only the newest 3 capture segments (`AIPC_LIVE_CAPTURE_KEEP`) across this output tree's `pid-*/live-captures`, and deletes older and empty ones in a background thread whenever a segment starts. Segments this recorder made in the last 2 minutes are never touched; they are registered before their folder exists, and the pruner reads that set under the lock after listing, which fixed a race found by the existing rotate tests. Captures in other project copies (`uj-mappa-*`) are outside this scope.
- Visual prototypes (user: "learn what shape had to be killed, inspect similar ones"):
  - `visual_signature.appearance_embedding`: a 37-d unit vector per World3D box (hue/sat/value histograms, 4×4 brightness layout, log aspect), ~0.1 ms per crop, not part of `signature_id`.
  - `visual_prototypes.VisualPrototypeMemory` (persisted in the profile as `visual_prototypes.json`) labels every addon-confirmed hover:
    - POSITIVE for the open quest named by the tooltip;
    - NEGATIVE for a corpse or a unit not tied to an open quest.
  - Each box gets `prototype_positive/negative/lift`. Lift > 0 only when the box is closer to the quest's confirmed looks than to both the rejected looks and the scene's median box.
  - ActivePerception adds `.30·lift·goal_relevance` to the information gain, so probe order changes but nothing is suppressed; the hover stays the identity authority. Nothing is scored without an open quest (turn-in hunting stays neutral).
- Tests: `test_visual_prototypes_20261004.py` (5), `test_live_capture.py` (+1). Full suite: 18 baseline failures, 2253 passed.
- Not validated: embedding separation on real Exile's Reach crops (synthetic colour tests only); the lift weight needs live tuning.

## 2026-10-04 14:15 (assistant-run on user request, 300 s) — dismounted boar, LLM too slow in play

- The user asked the assistant to enter the world (Enter at character select) and to run a test; addon 0.9.52 was live.
- FAILED: the agent WAITed the whole trial ("Több adat szükséges"). After the logout the Giant Boar was gone (user: leaving the world dismounts the vehicle), but "1/1 Ride the Giant Boar" stayed complete, so the open "0/8 Monstrous Cadaver slain" had no executable step.
- Fix (offline): `quest_model.remount_quests`. While the player is not in a vehicle and the quest still has open objectives, a done "Ride/Mount/Board/Enter <unit>" objective is presented as open again (`remount_required`), so the ordinary named-NPC INTERACT re-mounts it. It is applied on every full snapshot and immediately on a FAST `in_vehicle` / `on_taxi` change. Single-objective uses (Scout-o-Matic) are untouched. Tests: `test_vehicle_bar_20261004.py` (+2).
- LLM in play: qwen3:4b on CPU took 3 min just to load (14:17:48 → 14:20:36), and both requests hit the 240 s timeout.
  - Measured right after: 0.6 GB free RAM.
  - Private memory: WoW 6.6 GB, llama-server 3.3 GB, Claude app 2.8 GB, DtsApo4Service 1.6 GB.
  - VRAM: 0.55/4 GB used with WoW minimized.
  - Conclusion: a 4B model on CPU cannot run beside WoW on this 7.7 GB machine. Options: a smaller model on the GPU, or LLM questions only outside play.
- Processes: the assistant stopped the agent (MANUAL after the bounded trial) and the Ollama server after the test.

## 2026-10-04 17:35 (user-run) — boar re-mounted, 3/8 cadavers but slow; LLM on GPU worked

- LIVE (remount fix): the agent targeted and interacted with the Giant Boar and was back in the vehicle at 125.6 s. Quest 55879 went 0/8 → 1/8 (197 s) → 2/8 (359 s) → 3/8 (426 s).
- LIVE (addon 0.9.50): Trample presses produced vehicle/pet casts 321627 and 321628 (`unit` vehicle/pet), while the player-unit event for 305556 was a client-side FAILED, confirming the earlier reading. VEHICLE_ABILITY: 4 of 7 attempts verified.
- LIVE (LLM, `num_gpu` null, `num_ctx` 2048): qwen3:4b answered 4 questions, about 2.1 s each after one HTTP 500 during load:
  - "Ride the Giant Boar" → RIDE_VEHICLE/Giant Boar;
  - "Monstrous Cadaver slain" → KILL/Monstrous Cadaver;
  - Trample → FORWARD_DASH (attack);
  - turn-in unknown, because no quest text exists for a quest accepted before addon 0.9.51.
  - It agreed with the deterministic rules, so behaviour did not change.
- SLOW: of 310 s on the boar, 161 s were WAIT between skills. Plans showed VEHICLE_ABILITY (107.6) as the best candidate yet chose WAIT: the autonomy loop's TARGET commitment admits only TARGET_SKILLS and waited up to 3 s each time (`committed_skill_waiting`). The aim also alternated left/right because VEHICLE_AIM stops at the same tolerance the planner fires at.
- Fixes (offline):
  - while `vehicle_controls` is set, VEHICLE_ABILITY and VEHICLE_AIM/ATTACK approaches match any commitment;
  - the dash fires at 1.5× the aim tolerance (hysteresis);
  - boxes with visual-prototype lift ≥ 0.6 (look-alikes of hover-confirmed cadavers) are dash aims without a hover first, in FORWARD_DASH mode only.
  - Tests: `test_self_avatar_vehicle_20261004.py` (+2). Full suite: 18 baseline failures, 2256 passed.
- Open: one INSPECT hovered the screen centre (0.5, 0.514), probably the own boar; to be checked against `state.self_avatar` diagnostics next run.

## 2026-10-04 17:58 (user-run) — faster: 4/8 → 5/8 in 25 s, remaining stalls

- LIVE: after the commitment exemption the boar run reached 4/8 (889 s) and 5/8 (914 s). The new run lasted 91 s, with 36 s between skills (earlier 161 of 310 s).
- Remaining stalls:
  - 850–861 s: Trample killed the committed cadaver, then the autonomy loop chose `target_click_retry` TARGET for the dead GUID every tick. That TARGET produced no commands (not installed) while VEHICLE_ABILITY (107 utility) waited.
  - 916.4/916.9 s: two presses 0.5 s apart; the second got the client error "Spell is not ready yet" and was mapped to INTERNAL_ERROR.
- Fixes (offline):
  - while `vehicle_controls` is set, a VEHICLE_ABILITY / vehicle VISUAL_APPROACH proposal preempts commitment handling in `AutonomousLoop.choose` (like quest dialogs);
  - the planner keeps a refractory window after each press (`vehicle_ability_pressed_at`, max(1.4 s, cooldown + 0.4 s)) and proposes WAIT (same priority) instead of a new press or a long INSPECT during the lunge.
  - Tests +1. Full suite: 18 baseline failures, 2257 passed.

## 2026-10-04 — why the aimed box was lost (offline analysis of the 17:58 run)

- In 91 s the World3D layer produced 1311 VISUAL_TRACK_APPEARED and 1306 LOST events (245 stabilized). Most are near-zero-confidence junk (runtime detector floor 0.01) appearing and vanishing.
- The aimed cadaver (`WORLD3D:8`) was a 14×26 px box at 0.25 confidence. It flickered out of detection, came back under a new id, and the approach's rebind rule (live twin / GUID rebind need ≥ 0.30 confidence) refused it, giving `visual_track_lost`. Fast boar turns add id switches.
- Fix (offline): `VisualApproachController._vehicle_rebind`, for VEHICLE_AIM/ATTACK only. When the aimed id is missing, it predicts the box position from the exact facing change since the last real sample (0.64 screen per rad; a left turn pans the world right). It then rebinds to the unambiguous, similar-size (0.6–1.67×) live non-self box within 0.09 of that point, accepting confidence ≥ 0.12.
- Test +1. Full suite: 18 baseline failures.
- User proposal adopted for every visual approach (not only vehicle aim): confidence inheritance. A box below 0.30 (down to 0.10) at the same place (≤ 0.05 screen, after correcting for the exact facing change) and the same size (0.75–1.33×) as the previous confident (≥ 0.30) box is the same target. Applied to the coasting-twin, vanished-id continuation and GUID rebind paths. Looser matches still need ≥ 0.30, keeping the 2026-10-01 "never jump to a weak neighbour" guard. Test +1. Full suite: 18 baseline failures, 2259 passed.

## 2026-10-04 18:20–18:35 (user-run) — 8/8 cadavers, scripted dismount, Torgok

- LIVE: 5/8 → 6/8 (1997 s) → 7/8 (2009 s) → 8/8 (2045 s). "0/1 Torgok slain" appeared, and 18 s later the server script took the player off the boar, which vanished (user: correct, scripted).
- FAILED twice (WAIT): the remount rule reopened "Ride the Giant Boar" because the quest was still open, and the agent looked for a boar that no longer existed. In the second run the agent was started after the dismount, so it had no history.
- Fixes (offline):
  - Remount is now stateless: a done ride objective is reopened only while the objective right after it (the vehicle's stage) is still open. Scripted exits within 30 s of a stage completion are also remembered.
  - EXIT_VEHICLE skill (VEHICLEEXIT binding, NUMPAD5 in the client; verify `in_vehicle` false). It is proposed when a ride quest is complete while still in the vehicle, or when a stage completed while riding and no script dismounted after 40 s (8 s when the LLM read every remaining objective as on-foot work).
  - Navigation: for a target without Z, `_probe_reachable_layer` scans the walkable layers at the target (start −60…+80 in 3-unit steps) and takes the shortest complete Detour path. Torgok's quest POI (244, −2243) has layers 80.9 / 83.8 / 122.0. The old "assume start height" choice gave a partial path; now: 66 yd, 4 corners, through the entrance step (82.8→84.1) onto the 83.8 floor.
  - Tests: `test_vehicle_bar_20261004.py` (+5), `test_native_detour_20261003.py` (+1, one label assertion widened). Full suite: 18 baseline failures.
- User information (not yet implemented):
  - a grey minimap quest dot means the objective is indoors (building/cave);
  - an arrow under the dot means below the player's height, an arrow over it means above;
  - the in-world navigation pin shows the distance ("64 yds"; C_Navigation API).
- User rule (implemented offline) for single named kills ("0/1 <Name> slain"): if the hover shows that unit dead (someone else killed it), record `respawn_watch[objective]`. The combat planner then proposes WAIT "várakozás a respawnra" at priority 82 for up to 180 s. That is above area search/pan/travel (76–78) and below INSPECT/TARGET/COMBAT (85+), so the respawned unit is still noticed; an alive hover clears the watch. Test +1. Full suite: 18 baseline failures.

## 2026-10-04 18:52 (user-run) — Torgok MOVE failed: terrain Z under the building

- FAILED: MOVE to Torgok's quest POI failed instantly three times with `required_navmesh_route_unavailable` (shown as INTERNAL_ERROR), and the agent WAITed in between. The live `WorldGeometryService` injects the TrinityCore maps terrain height for a target without Z (`_with_terrain_hint`). Under the building that is 80.9, the unreachable lower layer, marked `z_known` (estimated), so the new layer probe never ran. Navmesh diagnostics showed `endpoint_layer: known`, `no_polygon_path`, partial.
- Fix (offline): when an estimated target Z (not observed) has no complete path, `_native_find_path` probes all layers and takes the shortest complete one (`estimated_z_unreachable_shortest_layer`). Verified through `WorldGeometryService.from_paths` with the maps: 64.5 yd, through the entrance step, onto the 83.8 floor. Test +1. Full suite: 18 baseline failures.

## 2026-10-04 18:41 (user-run) — Torgok killed; turn-in MOVE out of the building failed

- LIVE: the agent reached Torgok in the building and killed him at 3878 s. Quest 55879 was complete and the loot verified. The addon 0.9.51+ quest text arrived ("…mow down the army of undead between us and Wrathion…").
- FAILED: the turn-in MOVE to the QUEST_POI (228, −2294; user: next step "Find Wrathion") failed with `required_navmesh_route_unavailable`. This time the *start* was wrong: inside Torgok's room (83.8 floor) the player got the terrain height under the building (80.9, an isolated navmesh island) as its estimated Z.
- Fix (offline): `_probe_reachable_layer` also probes the start layers when the start Z is unknown or estimated. A layer matching the last projected player surface (continuity, ≤ 15 yd) is preferred, then the shortest complete path. Verified via `WorldGeometryService`: out of the room 49.9 yd (83.8 → 80.9), into the room 64.5 yd. Test +1. Full suite: 18 baseline failures.

## 2026-10-04 18:55 (user-run) — out of Torgok's room to the turn-in; reward window stalled

- LIVE: the start-layer fix worked. The agent left the building and reached the turn-in POI (228, −2294). Wrathion and Lady Jaina were both near it.
  - TARGET Wrathion twice reported TARGET_NOT_FOUND although the target arrived later; the user reported WoW freezes (low RAM) at the time.
  - The agent then targeted Jaina (both friendlies are "near the turn-in point"). Approaching her opened the quest window with REWARD_SELECT for 55879, so Jaina is the ender; "Find Wrathion" is the next step per the user.
- FAILED: two reward choices (Expeditionary Short Sword 175170 / Expeditionary Cudgel 175173, both usable, no item level exported). The fail-closed selector needs an explicit goal policy, so QUEST_DIALOG was never proposed. WAIT (priority 95) ran until the passive-wait budget forced a replan, and a turn-in-area MOVE walked away from the open window.
- Fixes (offline):
  - `RewardPolicy.AUTO`, the planner default when the goal names none: usable first, then item level, then vendor price, then lowest row. Deterministic, never random; an explicit goal policy or BLOCKED still wins.
  - Addon 0.9.53 (installed; needs /reload) exports per reward choice `item_level` from the item link (C_Item.GetDetailedItemLevelInfo), `sell_price`, `equip_loc` and item class/subclass.
  - Tests updated: `test_quest_dialog_fast_lane.py` (BLOCKED still waits; no policy → AUTO) and `test_m1_quest_reward_selector.py` (+1). Full suite: 18 baseline failures.

## 2026-10-04 19:10 (user-run) — "You need to be closer" loop at Wrathion

- FAILED: Wrathion (human form, user) was targeted. Every VISUAL_APPROACH (INTERACT) returned ready within 0.1 s without issuing a command, and INTERACT answered "You need to be closer" four times. Readiness came from the screen box (learned scale, or the screen-bottom / beside-avatar shortcuts), not from real range.
- Fix (offline, user rule): after a client range error for that GUID (`interaction_range_failures`, passed as `range_failures`), the bottom/beside shortcuts are off and the approach must issue N real forward pulses before it may probe INTERACT again: N = 5, then 3, then 2 (`RANGE_ERROR_STEPS`; the user lowered it from 10/5/3/2 — "10 az sok"). The existing edge correction steps back on an overshoot. Tests +2. Full suite: 18 baseline failures.

## 2026-10-04 — reward chosen but Complete Quest never pressed (55879 turn-in)

- Live (user): the agent reached the turn-in NPC, the reward window opened, the agent clicked the AUTO-chosen reward (Expeditionary Short Sword vs Cudgel, both ilvl 7 / 15c → lowest index) and the client visibly selected it, but Complete Quest was never clicked.
- Log (`pid-8048/agent_status.json`): `quest_ui.action=REWARD_SELECT`, `reward_selected_index=0`, no `selected` flag on any choice; QUEST_DIALOG REWARD_SELECT failed twice with `expected_state_not_reached` (verify waits for the selected index), then the agent moved on.
- Root cause (addon): Retail 12 reward buttons (`QuestInfoRewardsFrame.RewardButtons`) are not CheckButtons — no `GetChecked`, never `PUSHED` — so a successful selection was invisible. While the index stayed 0 the addon (by design) withheld the Complete button.
- Fix: addon 0.9.54 reads the client's own choice `QuestInfoFrame.itemChoice` (set by `QuestInfoItem_OnClick`, passed to `GetQuestReward` by the Complete button); the item highlight anchored to a reward button is the fallback. The fast lane now also reports `REWARD_SELECT` (no coordinates) instead of `COMPLETE` while 2+ choices are unresolved, so it can never click Complete before a choice. Lua harness test via lupa (+1). Installed; needs `/reload`. Not yet live-validated.

## 2026-10-04 — vendor quest "Stocking Up on Supplies" (55194): Richter hovered, shop never opened

- Live (user): after the boar quest the agent took 55194 from Captain Garrick ("Purchase any item from Quartermaster Richter and sell any of your items to her"). It hovered Richter repeatedly (mouseover: quest_related, quest_id 55194) but never selected her or opened her shop; the loop was INSPECT → expected_observation_missing.
- Log (`pid-8048/agent_status.json`): both objectives arrive as API `object` → INTERACT with `current=1, required=1, is_complete=false`. The QuestModel marked them COMPLETE from the counters, so `ready()` was empty: no NPC objective, Richter irrelevant, nothing to do but inspect.
- Fixes (offline):
  - The API's explicit `finished=false` beats full counters (`quest_model._objective`); counters still complete an objective when `is_complete` is absent.
  - `vendor_clause()`: "… purchased/bought from X" → BUY, "… sold to X" → SELL, target_entity = X (`VENDOR_CLAUSE_TEXT`); text rules now also match purchased/bought/sold.
  - BUY/SELL are NPC objective types (only the named vendor is relevant) and use the SPEAK local search; a selected named vendor gets INTERACT `purpose=OPEN_VENDOR` (74); INTERACT/TALK verify also succeeds when `vendor_ui.open` turns true.
  - The existing open-shop flow then runs: OPEN_BAGS → BUY_VENDOR (cheapest affordable item) and SELL_VENDOR (non-quest, non-equippable item with a sell price).
- Tests: `tests/test_vendor_quest_20261004.py` (6). Full suite: 18 baseline failures only.
- Not yet live-validated. Open risks: a vendor that opens a gossip menu first ("Let me browse your goods") has no handler yet; with no junk in the bags, the sell objective has no candidate (equippable items are never sold).

## 2026-10-04 19:37 — Richter's shop opened, then WAIT (55194)

- Live (user): the agent inspected three characters before finding Quartermaster Richter, approached, opened the shop (merchant frame with Tough Jerky / Alliance Tabard visible; bags auto-opened), then stood in WAIT ("Több adat szükséges").
- Log: `vendor_ui.open=true` with an empty `items` table; `bags_open=true` with sellable junk (Large Flat Tooth, Ruined Pelt…). No BUY/SELL/OPEN_BAGS task was ever registered. INTERACT on Richter was verified as `no_response` twice although the shop opened. Replaying the final state with `primary_quest.objective_id=55194:0` (the BUY) reproduced the WAIT: only that objective was planned and it had no buyable row.
- Root causes / fixes:
  - Addon 0.9.55: Retail 12 merchant rows come from `C_MerchantFrame.GetItemInfo(i)` (table); `GetMerchantItemInfo` is only a fallback. Rows 1–10, button coordinates only on page 1 and only for visible buttons. Lua harness test via lupa.
  - Planner: while the shop is open every BUY/SELL objective of the primary quest is planned, not only the primary objective; extended-cost (currency) rows are never bought.
  - Canonical `InteractionVerifier`: an opened shop (`vendor_ui.open` false→true) verifies INTERACT (evidence `vendor_ui`).
- Tests: `tests/test_vendor_quest_20261004.py` (+3). Full suite: 18 baseline failures only. Addon installed; needs `/reload`. Not yet live-validated.
- Open: finding the named NPC took three INSPECTs (hover is the only name source). Nameplates are not an option: the API gives no nameplate screen position (user, confirmed earlier) — do not propose them again.

## 2026-10-04 19:36 — INSPECT circled the same three named NPCs

- Live (user): "4x egymás után körbe-körbe ment ugyanarra a 3 npc-re hover".
- Log (`profiles/<user>/agent_memory.sqlite3`, 528164–528186): INSPECT hovered Captain Garrick (WORLD3D:11), Private Cole (WORLD3D:51) and Quartermaster Richter (WORLD3D:9, already the target) in turn, four rounds. The tracks were stable and every hover returned the same GUID/name. The only hover memory was for empty hovers and corpses/players.
- Fix (offline): `VisualInspectionPolicy` remembers the identity each INSPECT returned (track, spot and view). For 60 s, while the view holds, it does not re-hover that track/spot if the unit is the current target, or if it is neither quest-related (its tooltip lists no open objective) nor needed by a ready NPC objective (`friendly_npc_relevant`). Unknown tracks and needed NPCs stay inspectable.
- Tests: `tests/test_inspect_known_hover_20261004.py` (2). Full suite: 18 baseline failures only. Not yet live-validated.

## 2026-10-04 — GitHub export installer review (offline only)

- Synced the newer project agent/addon sources into the export; kept export-specific GUI and installer work. No fresh-PC or live WoW installation was run.
- The all-in-one flow now fails cleanly when navigation extractors are missing, no longer reports shortcut failure as success, and ends on a backend summary (agent logic on CPU; expected YOLO TensorRT / PyTorch CUDA / DirectML / CPU and selected model file).
- Targeted installer/GUI/agent regressions: 103 passed. The larger suite stopped after 3 failures out of 227 tests; those same three offline route/replay assertions also fail unchanged in the source project, so they are not evidence of a successful live quest or a validated fresh install.
- Open: an existing TensorRT engine is selected by file presence without a GPU-compatibility inference check; the displayed backend is therefore a prediction until the agent's startup log confirms it. WoW and the TrinityCore extractors must already be available on the target machine.

## 2026-10-05 05:37 — vendor quest done and turned in; slow turn-in search, Westward Bound range loop

- Live (user, addon 0.9.55): Richter's shop opened, BUY_VENDOR and SELL_VENDOR ran, "Stocking Up on Supplies" (55194) completed — first live pass of the vendor flow. The turn-in at Captain Garrick came only after a long search; the agent then visited quest givers until it took "Westward Bound" (55965) from Bjorn Stouthands.
- Causes:
  - The known-hover memory (2026-10-04 fix) had judged Captain Garrick "not needed" while 55194 was open and kept skipping him for 60 s after it completed (user diagnosis). "Not needed" now holds only for the quest state (quest/objective progress signature) it was judged in.
  - 55194's text names no ender; the local LLM (cached answer, Ollama itself was not running) guessed "Quartermaster Richter". An LLM-sourced turn-in now keeps the recorded giver as a second candidate (`turn_in_names`).
  - 55965 "Meet Bjorn Stouthands west of the Alliance Camp." had no turn-in name: "meet (up) (with) / join <Name>" is now a turn-in text pattern.
  - At the turn-in point (5.4 yd) Bjorn stood farther off; the TURN_IN_CANDIDATE INTERACT (116) was sent four times in 11 s, each out_of_range, with no move in between. The first call stays (the 2026-10-04 00:55 Garrick case needs it); within 20 s of a failed call (`interaction_range_failed_at`) it is not repeated, and the search/approach proposals run instead (replayed on this run's final state: MOVE 114 instead of INTERACT 116; test `test_a_failed_turn_in_call_is_not_repeated_blindly`).
  - Before Bjorn, the agent walked to the API '!' spot where Private Cole stood (the relevant giver) but never hovered him again: he had been judged "not needed" from afar under the same track (user: "a 60mp-es inspect szabályod"). The verdict now also expires once the player moves > 5 yd, never applies to friendlies while no quest is active (quest-giver search), and the window is 20 s instead of 60 s.
- Tests +5 (`test_quest_turn_in_20261004.py`, `test_inspect_known_hover_20261004.py`, `test_turnin_selected_npc_20261004.py`). Full suite: 18 baseline failures only.
- Also synced from the GitHub repo into the project: installer/wizard/GUI changes, README, examples; the semantic interpreter again follows `config/ai_decision.json` (on by default, backs off when Ollama is down) instead of being forced off by the GUI.

## 2026-10-05 — large modules split (structure only, offline)

- User request: split the 900+ line Python files. Behaviour-preserving moves only: whole methods moved verbatim into mixin classes (the main class inherits them), module-level helpers/types moved to sibling modules and re-exported, so every existing import path still works (`SkillRegistry`, `AutonomousAgent`, `WorldModel`, `QuestDomain`, `PerceptionWorker`, `NavigationService`, `InstallWizard`, `runtime.replay`, `pixel_bridge.payload_to_state`, `world.SENSOR_TIERS`, …).
- One real function split: `QuestDomain._propose` (571 lines) now calls `_propose_objectives` (the per-objective loop) and `_propose_selected_friendly` (the selected friendly-unit block; a returned list keeps the former early returns). Both blocks are textually unchanged.
- Sizes (before → after): `visual_approach.py` 1276 → 444, `skills.py` 1175 → 22, `memory.py` 1161 → 431, `perception.py` 1099 → 224, `engine.py` 1019 → 664, `quest_planning.py` 1014 → 402, `world3d/tracking.py` 1007 → 504, `adapters/pixel_bridge.py` 978 → 404, `install/wizard.py` 949 → 177, `navigation/service.py` 947 → 551, `world.py` 919 → 493, `runtime.py` 749 → 503. No module is above 700 lines now except the untouched `skills/combat.py` (878), `navigation/mmap_navmesh.py` (849) and `world3d/pipeline.py` (832).
- The three module-size gates of `tests/test_v4_083_095_module_size_reduction.py` (runtime < 600, engine < 900, world < 850) pass now: the known baseline drops from 18 to **15** failures. Full suite after every file: no new failure.

## 2026-10-05 05:39 (pid 1212, re-analysis) — three quest givers visited, only the third taken

- User: after the 55194 turn-in the agent went to Private Cole for a quest but did not take it, then to another giver, and took only the third one (Bjorn, 55965). All three were campaign quests: the addon's `map_pois.available_quests` (C_QuestLine API, no map opening) listed 58914 "A Warrior's End" (187, -2280; 5 yd from the turn-in spot, Private Cole), 55965 "Westward Bound" (199, -2271) and 55196 "The Harpy Problem" (267, -2339; Henry Garrick).
- Timeline (agent clock): 564335 log empty, **Captain Garrick still selected**; 564341–564348 INSPECT hovered Private Cole (WORLD3D:1), Quartermaster Richter, Captain Garrick. The feed trace shows a "!" (score .59–.61) exactly over Cole's box the whole time (`symbol_above` true). No TARGET was proposed. 564348.6 VISUAL_APPROACH to Garrick (track lost, 3 s WAIT), 564353–564370 MOVE to the 55965 pin, 564371–564390 MOVE to the 55196 pin; Henry Garrick hovered at 564391.9 at his pin — no TARGET; 564392.6 OPEN_MAP "no known quest location"; 564399–564408 WAIT with no candidate; 564408 VISUAL_APPROACH to Captain Garrick from 88 yd (track lost); 564414.6 the client dropped the far target; SEEK_VISUAL_CUE found Bjorn ("!" over him), TARGET, accepted 55965.
- Root cause: with an empty quest log `QuestDomain._friendly_target_relevant` returned True for **any** selected friendly unit, so the stale Garrick selection entered `_propose_selected_friendly`, whose approach/WAIT branch returns early — before `TargetPlanningPolicy` builds the mouseover TARGET hand-off. Cole and Henry were hovered but could never be selected; the same branch produced the idle WAIT and the 88 yd approach. Pins arrived only at 564349 (14 s after the turn-in), so the 58914 pin was "reached" at once and the agent left for the next pins. This run still had the 60 s known-hover rule (fix written at 05:50, run 05:37–05:44); the earlier entry above that blamed only that rule for Cole is incomplete — Cole was hovered, the selection blocked him.
- Fix: no active quest + the selected friendly unit was talked to (INTERACT/TALK/QUEST_DIALOG success) within 300 s + no "!" over **its own** box (`selected_npc_shows_quest_symbol`: hovered now or bound track, never the box under the cursor) → it is released: it no longer enters the selected-friendly branch, and the next TARGET replaces it. Not a key press: Retail 12.1 has no CLEARTARGET binding (absent from the addon's 357-action binding export) and a blind Esc may open the game menu. A unit not yet talked to keeps the discovery rule; one with a "!" stays relevant (follow-up quest).
- Replay of the 564346 frame: before the fix INSPECT 88 / MOVE 84 / MOVE 83.5 and no TARGET; after it TARGET Private Cole first. Tests: `tests/test_stale_friendly_target_20261005.py` (5). Full suite: 2304 passed, 15 baseline failures, no new failure.
- Open (not changed): the overhead-symbol detector gate is .01 on purpose (a real Jaina marker scored .017), so faint false "!" boxes (this run: 4572 of 12044 symbol detections < .1) can veto the "no symbol visible, at an API giver spot" rule or put a false "!" over a neighbour. Henry's campaign "!" was not detected at all. Live validation of the fix pending.

---

## 2026-10-05 — quest_creature_memory + addon 0.9.56 (offline only)

- User requests: remember which NPC gives / takes each quest (the `C_QuestLine` "!" pins and the quest-log POIs carry no NPC name), what was done for every objective ("8/8 killed", boarded the boar, charged the zombie that looked like this, here), wire it into the agent so known creatures are recognised visually, and avoid needless INSPECTs.
- `src/wowbot/agent/quest_creature_memory.py` (profile file `quest_creature_memory.sqlite3`, separate from the debug log `agent_memory.sqlite3`): roles GIVER / ENDER / OBJECTIVE / VEHICLE per quest (npc id from the creature GUID, name, world position), up to four float16 appearance embeddings per creature type and map, PROGRESS rows per objective and method (skill, binding, own spell cast ≤ 5 s before, on foot / in vehicle, target creature, running centre + radius, count), and learned vehicle ability effects (formerly lost on restart). Only live observations; no TDB.
- Learning (`quest_creature_learning.py`): addon `quest_text` giver/ender GUIDs (giver stored at the API pin it was offered at), every objective counter rise, the unit targeted when boarding, hover looks, tooltips naming an open quest.
- Use: a remembered ender is turn-in evidence 0 (before text patterns / LLM); a hovered unit that is the remembered giver of a "!" pin within 25 yd may be selected without a detected "!" (the Henry Garrick case); a remembered ender/vehicle is a relevant friendly unit; with no quest, when every nearby pin's giver is known, other friendly NPCs are not hovered again while the view holds; World3D boxes get `creature_memory_lift` (closer to a wanted creature's looks than to the other known looks here), used by ActivePerception with weight .25 — ordering only, since the embedding does not identify a creature (Zombie Servant vs Monstrous Cadaver .985, two Jaina samples .50); remembered objective creatures re-seed `quest_relevant_npcs` while the objective is open.
- Addon 0.9.56: completion line of finished quests (`GetQuestLogCompletionText(index)` → `completion_log_text`, a turn-in text source), `ender_guid` from QUEST_COMPLETE, and the latest dialog's quest text is exported first for 5 s even when the quest is not (yet / any more) in the log. Installed into the Retail AddOns folder; `/reload` needed. Whether Retail 12.1 returns the completion line is **unverified live**.
- Size measured: one playthrough (3 000 quests, 2 000 creatures) ~1.9 MB; worst case 200 000 quests with all roles + progress ~90 MB.
- Tests: `tests/test_quest_creature_memory_20261005.py` (10), addon harness `test_dialog_quest_text_is_exported_first_with_the_ender_guid`. Full suite: 2315 passed, 15 baseline failures, no new failure. Live validation pending.
- Agent memory audit (same day, read-only): `agent_memory.sqlite3` is 993 MB over ~40 h / 16 sessions. Read back for decisions: skill/procedure statistics (≤ ±5 ranking points), rejection trials, goals/episodes. Debug/replay only: ADDON_TELEMETRY 257 MB (three 2026-10-03 sessions 208 MB), AGENT_TRACE/RUNTIME 49 MB. Never read: journal 82 MB, world_relations 72 MB, events ~35 MB, ENTITY_MEMORY observations 39 MB (98 % empty rows). Never filled: semantic_facts, task_patterns, resource_sites. Retention targets exist but `consolidate()` deletes ≤ 256 rows per minute and is deferred in FULL_AI, so it cannot keep up; no VACUUM. Open: separate log from memory, trim at startup, keep the last few sessions.

---

## 2026-10-05 12:23-13:10 (pid 2456, three user runs) — Hrun's pit, quest pins, memory

- **quest_creature_memory LIVE:** the profile DB was created and filled from real dialogs: 55965 Westward Bound giver and ender Bjorn Stouthands (two creature ids, 154300 / 156891), 55639 giver Alaria, looks of Cole/Alaria/Bjorn. Bug found: the giver position was the player's position when the (session-persisted) dialog text was exported, not the giver's → giver position now only from the API pin.
- **Addon 0.9.56 LIVE:** `GetQuestLogCompletionText` works in Retail 12.1: `completion_log_text = "Meet Bjorn Stouthands west of the Alliance Camp."` arrived in the full snapshot.
- Semantic LLM: not used — Ollama was not running (`status unavailable`, connection refused); only cached answers.
- Run 1 (12:23): after turning in 55965 the agent left for Private Cole's pin (85 yd) 2 s after the turn-in; Alaria's new pin appeared 7 s later 2 yd from the turn-in spot. Cole was hovered three times with a "!" exactly over his box (feed trace) but never selected: the hover was bound to the probed box beside him. Later, Alaria's route was briefly not permitted and the adapter's "alternative" was the Harpy pin 155 yd east → 5 s east and back (user: "oda-vissza"). After accepting "Who Lurks in the Pit" (55639) no MOVE was proposed (the POI on the pit rim was "within the area" in 2D), the agent opened the map and talked to Bjorn twice (the cocoon objective, raw type `object`, made every friendly NPC relevant).
- Fixes: pin routes wait up to 10 s after a turn-in for the pin list to change; a blocked MOVE's alternative may not be > 2× + 40 yd farther; `npc_shows_quest_symbol` checks the boxes under the cursor too; game-object INTERACT/USE_OBJECT objectives make no friendly NPC relevant (vendor BUY/SELL excepted).
- **Pit/cave layer (design doc §5 step):** the mmap connects the rim (z 95) and the pit bottom (z −21) by a ~480 yd spiral (user: "spirálisan megy lefelé egy út"). `NavigationService.lower_layer_point` finds the deepest walkable point ≥ 15 yd below the POI surface within 35 yd that has a complete route (skipping unreachable pockets, e.g. an isolated covered region at −23); the quest planner proposes it when the POI area is reached in 2D and the quest's own text points down (pit/cave/descent/bottom…, priority 80), the minimap shows the objective below (learned grey-dot-down class, 80) or 25 s of rim search gave no progress (62). Replay of run 1: right after the accept, MOVE to (85.9, −2208, −21.1), route z 95→76→61→41→25→…→−19.
- Run 2 (12:52, LIVE): the agent **went down the spiral** (descent MOVE, layer cue QUEST_TEXT). First it walked 95 yd east to a "yellow minimap dot" that was Private Cole's yellow "!" icon (now filtered: dots within 20 yd of an API giver pin are icons). A Barrow Spider attacked at (83, −2269) on the 64 yd ledge; after the kill and loot the resumed route started at the terrain height — the rim 34 yd above — and the agent walked on the spot under its first waypoint (78.1, −2263.2, z 97.7). User also saw a cocoon (yellow dot, visible in 3D) that the agent ignored.
- Fix: own-layer tracking (§4.3): `NavigationService` follows the player's walkable layer sample by sample (route projections, then a 0.5 s continuity projection) and a new route starts there as an *estimated* height (`z_source NAVMESH_LAYER_CONTINUITY`, ≤ 40 yd, ≤ 180 s). The z flags now reach the navmesh, so an incomplete path from an estimated start still runs the Torgok/Wrathion start-layer probe (user concern: leaving a building must keep working). Real mmap: old start 98 → 521 yd route back over the rim; tracked 64 → 399 yd straight down.
- Run 3 (13:01): one cocoon credited (0/5 → 1/5); repeated spider fights; the descent and the POI MOVE alternated.
- **Zone entry (user rule):** entering the quest zone = getting inside the blue minimap area; from there the yellow-dot approach, visual seek and minimap search take over instead of walking to the centre. Grey objective dots with a down/up arrow = the objective is lower/higher than us (we are in the zone but not on its floor); yellow = same space. "Free 8 monkeys" style objectives show yellow dots in the zone; "slay 5 murlocs" show none. Implemented: an objective MOVE ends (`QUEST_ZONE_ENTERED`) when the minimap area says the player is inside and no other-floor cue is present; a descent ends when a yellow objective dot of the quest shows. Minimap classes added (learned map-marker vocabulary, ids appended): `objective_dot_same_space`, `objective_dot_other_space`, `objective_dot_below`, `objective_dot_above`; the 843 px capture is too small to measure the grey dot/arrow, so they need labelled data (review tool: keys 1-9, 0, C).
- **In-zone navigation (user: "a quest zónán belül hogy közlekedik"):** exploration starts at the zone edge, not at the centre. A zone with floors far below the POI is walked by `NavigationService.zone_sweep_next`: the mmap route from the player's tracked layer to the deepest reachable point, resampled into 15 yd hops (Hrun's pit: 34 hops, z 91 → −22), walked down and then back up once; the planner re-decides after every hop (yellow dot 88, inspect/seek, combat), a hop ends early when a yellow objective dot of the quest shows. Without a cue the sweep ranks 62 (below the local search), with a text/minimap-below cue 80. Flat zones keep the existing 2D search cells. Replay of run 1: right after the accept the first hop (z 91) is chosen. Next step (proposed): one zone map of all walkable polygons inside the blue area on every layer, visited in route order.
- **LIVE VISION route view (user request, offline):** inset + bearing line from the navigation's route / zone sweep (preview rendered on a 13:19 frame). Needs `AIPC_LIVE_VISION=1` as before.
- Open: cocoon (game-object) interaction — the objective locator gives no location for this objective, so the object search flow never runs; kill quests in caves rely on text / mmap / no-progress cues (no dots). Tests: `tests/test_pit_layer_and_pins_20261005.py` (13). Full suite: 2328 passed, 15 baseline failures. Not pushed (user: push after live validation).

---

## 2026-10-05 16:30-16:41 (pid 19152, user) — zone sweep up/down, minimap floor arrows

- LIVE (user): the agent walked the pit up and down (zone sweep) and saw the yellow dots, but not the arrow under a dot (objective on another floor).
- Cause: the WoW client was 843x475 (DXGI captures the client natively; no downscale): the minimap disc has a ~45 px radius, dots are 2-3 px, the arrow is not resolvable; the white line under a dot in the 16:31 frames was the blue zone outline's glow.
- User switched to 1600x900 (disc ~75 px). On the user's 16:40 screenshot the grey dots (~5x5 px neutral grey) each carry a "▼" (rows 4-5 / 2-3 / 1 px, centre ~0.1 R under the dot).
- `vision/minimap_floor_markers.py`: yellow dots from the existing detector (glyph/crosshair filters), grey dots (neutral, size/shape bounded by R), "▼"/"▲" components paired under/over a dot → floor SAME / BELOW / ABOVE / OTHER_SPACE (grey without arrow). Perception adds a `minimap_floor_markers` candidate with `objective_below_like` / `objective_above_like` / `other_space_like` labels (consumed by the zone-entry and descent logic) and tags yellow dots with their floor; a yellow dot with an arrow is not a walk-to dot. The yellow-dot size limit now scales with the disc radius. Fixture: `tests/fixtures/minimap/grey_dots_below_1600x900.png` (4/4 BELOW at R 72-78). On the 2026-10-04 fixtures a bluish round icon with a "▲" reads as ABOVE (plausibly real). Tests +3; full suite 2335 passed, 15 baseline. Needs a live run at 1600x900 (or Edit Mode minimap size).

---

## 2026-10-05 18:23-18:25 (pid 19152, user, 1600x829) — turning on the spot at the cave entrance

- LIVE (user): in the second FULL_AI run the agent walked the spiral down to the lower cave entrance (zone sweep, hop 4 of 34, z 68) and then stepped "körbe-körbe, centinként" for 30 s until the user stopped it.
- Journal: MOVE to hop 4 (69.79, −2246.58), stop distance 6; the arrival verifier said ARRIVED from 5.7 yd down to 0.08 yd, yet the controller phase stayed STEERING/MOVING and kept issuing `TURNRIGHT 0.12` / soft steers; no new intent, the destination never changed (not caused by the minimap dot).
- Cause 1: the mmap route ends on Detour's float32 point (69.79095459, −2246.58081) while the request is float64 (69.79095274, −2246.58089): 7.5e-5 yd > the 1e-5 `needs_replan` tolerance, so every `command()` replanned and restarted the controller, which reset ARRIVED to MOVING. This affected every navmesh MOVE (one Detour query and a waypoint-index reset per control step); the 2026-10-04 "danger map kept changing" replans were probably this. Fix: the route records the requested destination and `needs_replan` compares against it.
- Cause 2: the runtime runs the FAST lane and then the medium tick on the same FAST packet. The FAST lane consumed the arriving sample, saw ARRIVED and stopped, but only the medium tick finishes a skill; on that sample it saw no fresh position ("awaiting_fresh_position_sample") and continued. Fix: the controller repeats a terminal verdict (ARRIVED / FAILED / SUPPORTED_STUCK) on "awaiting" observations until the next `start()`.
- Minimap (user: the right-hand yellow dot with the down arrow is the quest object cocoon): with the addon's geometry (centre .9458/.1359, R .0941 h) the cocoon's dot reads BELOW in 26/28 frames; two frames lost the arrow (a dim ~150 arrow under the 165 threshold; a 1 px outline row over its base, rows [1, 5, 3, 1]). Fix: a second, dimmer (140) pass for unpaired dots and dropping 1 px rows beyond the base; a bright arrow that also passed the grey-dot mask is no longer reported as a separate grey dot. Now 28/28 BELOW, every grey pit dot BELOW. (An offline check with the old fixed .941 centre showed the minimap's gold W notch as two yellow dots; with the live geometry it is outside the disc.)
- Tests: `tests/test_sweep_arrival_circling_20261005.py` (5; three fail without the fixes), fixtures `tests/fixtures/minimap/cocoon_below_{outline,dim}_1600x829.png`, `pit_grey_below_1600x829.png`. Full suite: 2340 passed, the same 15 baseline failures. Pushed to GitHub on the user's request (v2026.10.05-3) before a live run; needs a live run.

---

## 2026-10-05 20:13-21:12 (pid 2400, user, new character) — one-hour run, nine quests turned in

- New character (level 6 at the end), Exile's Reach from the start. Turned in: Murloc Mania (55122), Emergency First Aid (54951, kits used by the user), Finding the Lost Expedition (54952), Cooking Meat (55174), Enhanced Combat Tactics (59254, last Charge by the user), Northbound (55173), Quilboar Shadow Magic (55184), Re-Sizing the Situation (56034), Stocking Up on Supplies (55194). Ride of the Scientifically Enhanced Boar (55879: ride, 8/8 cadavers, Torgok) completed, not yet turned in at the stop; Down with the Quilboar (55186) open. 729 actions, 457 succeeded.
- Time per skill (3507 s): MOVE 499 s (333 failed/cancelled), INSPECT 422 s (272 failed: 49 × 5.6 s), SEEK 332 s, COMBAT 294 s, TARGET 220 s (135 failed: 23 × 6.5 s, success median 2.7 s).
- **Jaina (first quest):** the TARGET click for Jaina selected another player standing in front of her (`Player-1402-…`); the addon exports no `is_player` for target/mouseover, so the planner tried INTERACT and then a VISUAL_APPROACH and followed the player 47 yd before returning. Fix: a `Player-` GUID is a player (`is_player_unit`, and the reducer marks target/mouseover `is_player`).
- **Emergency First Aid:** the primary objective was the kit on Bjorn; Kee-La was hovered three times (and Austin once) during the search/dot MOVEs and finally selected by the user, but her objective (same quest, same First Aid Kit) was skipped as "not primary"; no TARGET/USE was ever proposed. Fixes: a sibling item objective whose unit is hovered/selected is planned (replay: TARGET 83 on every Kee-La hover; OPEN_BAGS 85 / ASSIST 82 once selected); a quest-route or minimap-dot MOVE stops when a unit named by an open objective is under the cursor (`OBJECTIVE_UNIT_HOVERED`).
- **Enhanced Combat Tactics:** Garrick's lines are exported as NPC_INSTRUCTION events: "Charge towards me!" (agent charged, 1/3), "Charge at me again to close the distance" ×3 (agent pressed Slam, out of range: Charge is a once-per-fight MOVEMENT opener in the ability rules), "One last time. Charge!" (user). FOLLOW_INSTRUCTION was proposed once and preempted by DEFEND. Fix: inside COMBAT/DEFEND a fresh (≤ 12 s) unfollowed NPC instruction naming an ability lifts the opener limits (`movement_opener_already_used`, `melee_range_confirmed`) for that ability, once per instruction; usable/range/cooldown/binding/resource gates still apply.
- **Selection speed (user: remove the same-target hover ban, make selection snappier):** a TARGET clicked on the previous INSPECT's mouseover sampled before its own hover (616937: nothing under the pointer) and then waited out the 8 s deadline. Fixes: hover-confirm accepts only a mouseover sampled after the hover; after a click, 0.7 s of fresh target samples without the expected GUID re-hovers (≤ 3) or fails at once; a direct click fails after 0.7 s too; an INSPECT whose pointer is on the probe and whose post-hover (≥ 0.4 s) sample names nothing fails immediately (`expected_observation_missing`) instead of after 5 s; the known-unit hover block (`_known_unneeded`) is no longer applied (empty spot / corpse / own character suppression stays).
- **Moving tracks (user: the pointer arrives after the unit moved on):** `track_motion.py` measures each World3D box's screen velocity from its last positions (0.6 s window) and hovers lead it by capture age + 0.06 s pointer latency (≤ 0.5 s, ≤ 0.12 screen); no lead while the player turns. Used for INSPECT/TARGET hovers, the TARGET first hover and hover-confirm re-hovers; the INSPECT probe check uses the point actually sent.
- Tests: `tests/test_faster_hover_target_20261005.py` (7), `tests/test_npc_instruction_combat_20261005.py` (2); the key ones fail without the fixes. Full suite: 2349 passed, the same 15 baseline failures. Not pushed. Needs a live run.
- **Wandering, part 1 — Scout-o-Matic turn-in (618658–618869, ~210 s):** the ender Lindie Springstock (a gnome) was selected from 618679.9 on, but every interact answered "You need to be closer". The VISUAL_APPROACH started on her 5 %-high box (ready height 0.19), followed the wrong box in the crowd (Jaina, Alaria, Austin) for 24 yd and lost it; the agent then stood 70 s ~5 yd from her (INSPECTs only on YOLO boxes: Alaria, Jaina, Izus) and walked turn-in search cells for 90 s. A saved frame (980x508 client) shows Lindie at the right screen edge with the green selection ring and "?" partly under the "new gear" tutorial popup and no YOLO box at all. Not fixed: needs a bigger client (the 980x508 capture loses small NPCs) or a way to re-find a selected but unboxed unit.
- **Wandering, part 2 — Re-Sizer (618881–619456, 575 s; user: drove to the boars and did 2/3, 3/3):** INTERACT on a far boar did nothing (no error, no cast); the agent opened the bags and right-clicked the Re-Sizer, which only armed a targeting cursor; the agent's next TARGET left click on another boar at 619020 fired it (cast at 619025, 1/3). Between the credits it repeatedly walked to the quest POI and approached far unknown boxes to identify them. Fix (user 2026-10-06: "target first, then Interact Target within range, or right-click"): a quest special item on a selected matching target is used with INTERACTTARGET (no bag opening); no cast within 1.5 s means out of range -> the planner approaches the target and retries; without an INTERACTTARGET binding the target's box is right-clicked (hover-confirmed); the bag/action-bar path remains a fallback and then clicks the target's box once if no cast started (fires an armed cursor). User: INTERACTTARGET may not work at first; to be tested in the next fresh full run. Tests: `tests/test_item_use_interact_first_20261006.py` (6); two older tests that required the bag path were updated. Full suite: 2355 passed, the same 15 baseline failures.

---

## 2026-10-06 08:38-08:42 (pid 16752, user, new character, Hrun's pit) — fell off the spiral

- LIVE-CONFIRMED: zone-sweep hops now end on arrival (hops 1-3 each SKILL_SUCCESS in ~2 s; the 2026-10-05 circling fix works live).
- Bug (user): after falling off the spiral the agent tried to go back "in a straight line" to a waypoint above. Evidence: FALL_STARTED/FALL_ENDED (seq 3775/3776) arrived with the 661487.8 STATE page at (80.4, −2224.8); the addon sends no height, so the route projection kept the player on the upper layer and every replan started there; the minimap-dot MOVE's waypoint 9 (z 94.8, the rim) lay 7 yd away horizontally, right above him, and he walked into the wall for 12 s (no progress) until the user stopped.
- Fix: on a new FALL_ENDED the player is placed on the highest walkable layer below the tracked one (`walkable_heights_at`, ≥ 1.5 yd lower) and the route is planned again from there; a downward zone-sweep hop above the landing counts as passed (the planner continues the sweep from the new layer). Replay with the real mmap: fall detected 86.9 → 74.9, new route starts at 75.0. Tests: `tests/test_fall_off_spiral_replan_20261006.py` (3). Full suite: 2358 passed, 15 baseline failures. Needs a live run.
- **Z resolver (user design, same day):** `navigation/z_resolver.py` owns the player's layer and every target height (MMAP layers, VMAP floors/headroom, terrain, Detour reachability, minimap floor cue; low confidence → 30 yd leg then re-resolve); `world_geometry/vmaps.py` reads the TrinityCore VMAP_4.E collision data (vertical surfaces); `aipc_detour.dll` rebuilt with `aipc_nav_layers_at` / `aipc_nav_polys_near` (Detour queryPolygons/getPolyHeight; 0.01–0.3 ms vs 297 ms for the first Python tile parse; old DLL kept as `native/bin/aipc_detour.v1.bak`). Replay of the fall: layer 95.1 → 94.3 → fall 86.9 → 74.9, the sweep continues with the hop at 76.7 instead of climbing back to 83.7; the cocoon dot resolves to the 66.6 ledge (reachable, conf 0.86) instead of the rim. Tests: `tests/test_z_resolver_20261006.py` (7), fall tests (4). Full suite: 2366 passed, 15 baseline failures. Needs a live run. Design: `docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md` §13.

---

## 2026-10-06 09:20 (pid 1592, user, Hrun's pit) — fell on the spiral, ran back and forth, turned on the spot over the cocoon

- LIVE (user): fell on the spiral (client lag likely), ran back and forth, once into a wall, went deeper, stopped in front of a cocoon and ran back and forth there until stopped.
- Evidence: five FALL_STARTED/ENDED pairs, each 0-1 s (hops, jumps, steps down the slope — FALL_ENDED arrives 1-3 s late with the state page). The resolver took the first as a drop to the highest layer below in the column under the player: 67.9 → −23.2 (the pit floor, 90 yd lower); during the following SEEK it was not updated (only MOVEs fed it); a broken continuity then jumped to the rim (97.2). The cocoon dot resolved to the 60.8 ledge (correct), but with the player believed on the rim the controller stood 0.4 yd from the target in X/Y and 35 yd from it in height and turned left/right for 35 s. Intermediate waypoints were passed in 2D only.
- Fixes: the resolver runs every tick (also outside MOVE); a fall is decided on the following samples' own column (≤ 3 s): over the old floor it was a hop, a landing must be 1.5–40 yd lower; a polygon-edge sample keeps the floor found within 4 yd; a broken continuity holds the old layer 2 s before switching; a waypoint on another layer (> 6 yd) is not passed in 2D; within 3 yd of the destination in X/Y but > 4 yd off in height the MOVE ends (`destination_on_other_layer`); a zone-sweep hop the player is already past in height ends (`zone_sweep_hop_passed`, with or without a fall event). Replay of the run: player layer 94.8 → 90.9 → 74.9 → 67.9 → 67.2 (ledge) → 60.8 (at the cocoon), sweep hops 74.3 → 67.3 → 64.7 follow the player. Tests: `tests/test_z_resolver_20261006.py` (11), `tests/test_fall_off_spiral_replan_20261006.py` (8). Full suite: 2372 passed, 15 baseline failures. Needs a live run. Still open: the cocoon itself is never opened (game-object interaction).

---

## 2026-10-06 — read-only cave-run audit and generic layered-quest changes (offline only)

- The later `projekt/output/live-debug/telemetry-20261006-094818.jsonl` was **read only**. The user sometimes moved the character during FULL_AI; this source run cannot independently validate agent locomotion or quest completion. The objective was still at 2/5 in the examined portion. The nearby same-space yellow dot could disappear under the player marker while a farther dot remained, after which the planner reversed direction. A raw World3D quest-object-like box appeared around 0.45–0.47 confidence, but the canonical candidate was not inspectable; pixels alone did not establish its identity.
- The working copy (not `projekt`) now keeps one bounded dot focus, associates located vertical minimap arrows cautiously with an open quest, requires two fresh arrow samples, constrains target floors via the existing navmesh, and hands a reached dot to local visual/hover identification. No object is used solely because it has a quest-coloured box. The Z resolver preserves ambiguous player floors and disconnected same-Z target pockets; zone sweep and search coverage require matching 3D arrival. A known-Z turn-in and its local NPC-search cells retain their floor; the turn-in search stops after 120 seconds without new evidence instead of cycling forever. See `docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md` §14 and `tests/test_cave_quest_layer_flow_20261006.py`.
- The 3 yellow-dot MOVE decisions recovered by `tools/replay_telemetry_decisions.py` are an **offline** RecordingExecutor replay, not new live input or quest credit. Targeted cave/turn-in/coverage tests passed. The full target suite before the final turn-in-cell test: 2398 passed, 15 previously documented failures, 5 skipped; no increase in the failure count.
- **Unresolved / live-open:** correct floor of an unheighted turn-in or POI; entrance/exit selection when the map marker is close in X/Y but on another floor; first player-layer fix when starting inside a stacked cave without motion history; confirming the cocoon by tooltip and obtaining quest credit. The current fail-closed behaviour can pause movement when floor identity is ambiguous. The user must run the next client test; this offline work is not a completed cave quest.

---

## 2026-10-06 11:21-11:24 (pid 10208, user, working copy) — outdoor cave start blocked by ambiguous Z

- User stopped the run with F12; no uncontrolled FULL_AI was left running. The character stayed near (92.55, −2249.99) outside the cave. The minimap objective markers showed down arrows, but the agent spent the run in SEEK/INSPECT/WAIT and never issued a MOVE. The navigation failure was `ambiguous_player_layer`, not a controller that moved invisibly.
- The client's Retail telemetry does not give an observed player Z. At that X/Y the real navmesh offers z=95.24 and z=39.72; terrain matches the upper surface. The resolver's z=95.24 was **only a 0.5-confidence hypothesis**. A target near (81.24, −2278.25) resolved to z=61.24 with a reachable 114.9 yd route, but another lower target floor exists around z=−2.7. Therefore a down arrow alone cannot prove the player's floor: either player hypothesis has a possible objective below it.
- Found the missing independent signal: the addon reads `IsIndoors`, but its compact FAST transport omitted `movement.indoors` in all five payload profiles. The working-copy addon now carries a boolean indoor/outdoor value through them; a failed/unknown API read stays absent, never false. A bounded outdoor-start probe requires the current `indoors=false`, a fresh quest-associated down arrow, terrain matching the upper floor, and a reachable VMAP-backed lower target. It retains the lower alternative, stops on contradictory movement or after 25 yd / 45 s, and never calls the Z observed. Stale target data cannot authorize a new request.
- Offline tests: cave/Z/fall/reducer/addon package targeted run **64 passed**. The new addon has **not** been installed/reloaded in the client's WoW folder here, and this fix has **not** been live-validated. The user remains the live-test operator. Still open: verifying the `indoors` field arrives in a new live FAST sample, that the bounded route actually moves toward the cave, and that the cocoon receives quest credit; an indoor stacked start remains ambiguous.

---

## 2026-10-06 11:56-11:59 (pid 10208, user, working copy) — first cocoon credited, next route hit wall

- LIVE: the updated addon delivered `movement.indoors` (outdoors at the start, indoors on the cave path). The agent reached the first cocoon and the quest counter rose **0/5 → 1/5**. This is one real objective credit, not completion of the quest. The user then observed a turn and prolonged running into a wall and stopped the run. No assistant-controlled client input or FULL_AI restart occurred.
- Cause from `output/live-debug/{telemetry,live-debug}-20261006-115658.jsonl`: after credit, the player descended from z≈62 to z≈52.7. At (109.6, −2282.0) the exact navmesh column contained only the rim z≈98.4, while the lower cave polygon z≈51.8 was 4.5 yd away; the 4 yd nearby search missed it. The low-confidence branch then promoted a stale upper-layer alternative to z≈98.4 with confidence 0.85 despite no possible ascent. The next route contained a waypoint z≈96.9 even though the objective was z≈44.4; the character ran into the wall below the rim. Position jitter repeatedly cleared per-frame no-progress evidence, so hundreds of forward lease updates continued without `SUPPORTED_STUCK`.
- Working-copy fix (offline-tested, **not yet live validated**): nearby floor search 5 yd; a broken tracked floor keeps its previous Z at confidence 0.4 instead of promoting an upper polygon; the generic alternative-convergence branch applies only to unresolved *first fixes*; required navmesh routes reject a low-confidence player floor even if the exact column has only one polygon. A separate 4 s fresh-world-position plateau gate confirms wall contact only after uninterrupted forward commands plus running telemetry, handing `supported_stuck` to the existing recovery path. It does not trigger during turn-only input or genuine translation. The `SUPPORTED_STUCK` verdict now remains terminal through later fresh FAST samples until the skill explicitly restarts, so jitter cannot re-arm W before the medium tick records the result.
- Offline replay of the actual telemetry with the real navmesh now follows z≈52.7 → 51.8 → 47.5 → 46.6, rather than jumping to the rim (or later to the pit floor after a short hop). A route from the corrected lower position to the cocoon ledge is ≈77 yd instead of the false ≈250 yd rim detour. This replay is **not** a second live success. The next user-operated run must verify the second cocoon, continuous lower-layer routing and that a wall contact stops instead of renewing W indefinitely.

---

## 2026-10-06 12:15–12:54 (user-operated tests) — cocoon hover, use, loot and WAIT

- Sources read only: `output/live-debug/{telemetry,live-debug}-20261006-121555.jsonl`, `...-124623.jsonl`, `...-125157.jsonl`, and the profile memory database. The assistant did not operate the client. The last observed run was stopped by the user; no FULL_AI process was launched here.
- First run: `OBJECT_USE` had a `Thick Cocoon` mouseover event, but kept its old screen coordinate while the character/view turned. A right-click went to the stale point and produced no quest credit. The `quest_object_like` box existed at confidence ≈0.25 but the old 0.55 threshold discarded it. The quest-object threshold is now 0.20 for approach/hover only; the quest-symbol/torch threshold is unchanged. An irreversible right-click still needs fresh addon-confirmed object identity at the actual cursor after a new hover and a stable view.
- After a spider kill, an exact owned corpse anchor and LOOT candidate were present, but the agent resumed the old LOCATION MOVE for ≈4.8 s; LOOT then failed `CORPSE_NOT_FOUND`. The autonomy loop now lets confirmed owned-corpse LOOT preempt that LOCATION commitment. This preemption was observed working in the later 12:51 run, though the subsequent LOOT failed `LOOT_UI_NOT_OPENED`; loot success is **not** validated.
- Second run: `OBJECT_USE` hovered the cocoon but never sent a right-click, then timed out `QUEST_CREDIT_NOT_RECEIVED`. The engine sets a generic `VERIFY` phase before skill verification, skipping a phase-specific hover branch. The ObjectUse skill now uses its own `click_sent_at` stage and the supervisor forwards verification-generated commands. Saved telemetry replay shows HOVER → wait for a new sample → right-click; this exact path is **offline-tested, not yet live-validated**. A live quest-related addon mouseover may override optical-flow camera-yaw drift, not actual position/orientation/cursor changes.
- Third run: after DEFEND/LOOT, the planner reached the cocoon but fell through MOVE → SEEK → OPEN_MAP → exhausted WAIT. The FAST addon repeatedly reported a quest-related object under the moving pointer; an earlier `MOUSEOVER_CHANGED` named `Thick Cocoon`, but its stored cursor no longer matched. A bounded, same-quest, uninterrupted FAST-sample continuity now carries the name to the current pointer. Actual saved frames replay as `effective_mouseover = Thick Cocoon`; an exact confirmed hover may preempt LOCATION/map WAIT for OBJECT_USE. This is **offline replay**, not a successful live cocoon use.
- At the time of these tests, `INTERACTTARGET` was a one-shot fallback after verified hover/right-click and required a matching soft GAMEOBJECT target. No such target appeared, so there is no evidence that F7 fired or works on this cocoon. Next user-operated test must show right-click/F7 action, objective counter change, and that WAIT does not recur after combat; a hover or `OBJECT_USED` event alone is not success. The later 19:17 run below prompted a narrower fallback for a fresh exact addon hover without a soft target.

---

## 2026-10-06 19:17–19:18 (pid 12516, user) — first cocoon failed live validation

- Source: `output/live-debug/{live-debug,telemetry}-20261006-191438.jsonl`, the read-only profile journal, and the captured 19:17:41 frames. The quest objective remained 0/5. At 699809.596 the planner selected `OBJECT_USE` for the addon-confirmed `Thick Cocoon` under cursor (.55669, .54915) and sent HOVER. At 699809.864 the skill failed `stale_observation` before any right-click or cocoon F7, and recorded a 15 s suppression for that objective. This is a **failed live test**, not a completed cocoon.
- The camera-yaw estimate jumped −60 → +12 in roughly the same interval while the observed mouse cursor stayed at the same point, the character's heading/position were stable in the surrounding addon samples, and the optical-flow displacement was the same reused 20 px sample. The exact immediate failing predicate was not logged; the yaw estimate is a strong candidate for the false stale-view failure. ObjectUse now ignores that derived yaw when merely waiting for a post-hover sample, while still rejecting changed heading/position/cursor and requiring a fresh exact addon identity before right-click. Offline regression reproduces a stale yaw sample followed by a fresh hover and click; **live revalidation pending**.
- F7 **was sent later**, at 699819.103, but for `LOOT` on a dead Barrow Spider; loot was verified at 699822.556. It was not the cocoon fallback. The current addon reported `soft_targets={}` at the cocoon, so the prior fallback rule could not run even if right-click had been sent. The one-shot ObjectUse fallback now also accepts a newly sampled, exact same-quest object tooltip under the unmoved cursor with stable player view and no competing soft target, two seconds after right-click if there is still no quest credit. The selected client reported `INTERACTTARGET=F7`; no F7 is guessed when the binding is absent. This new fallback is offline-tested only.
- Next user-operated test: confirm `OBJECT_USE` HOVER → fresh addon sample → RIGHT CLICK; if no 0/5→1/5 credit, confirm exactly one cocoon-specific F7 and its effect. Check that a moved cursor, changed player heading/position or lost quest hover blocks both actions. Assistant did not operate the client.

---

## 2026-10-06 19:46–19:48 (pid 12516, user) — FAST cocoon identity lost before interaction

- Read-only sources: `output/live-debug/{live-debug,telemetry}-20261006-194607.jsonl`, profile journal, feed-association trace. The user fought a Barrow Spider; DEFEND verified death at 19:47:17. LOOT used `INTERACTTARGET` on the corpse and failed `LOOT_UI_NOT_OPENED` at 19:47:23. The agent then hovered learned `quest_object_like` WORLD3D:159 at (.57909,.51964), detector confidence ≈.69–.74, with the pointer inside its box. FAST mouseover reported `quest_related=true`, quest 55639 under that pointer, but no name; no `OBJECT_USE` was proposed. The SEEK finished, navigation switched to `SEARCH_ENTRANCE`, opened the map, exhausted local search, then resumed MOVE toward the lower route. Objective stayed 0/5.
- The `MOUSEOVER_CHANGED` event sequence 7282 did contain `Thick Cocoon`, but the relevant full STATE assembled at monotonic 701601.634, ≈12 s after the hover. By then later mouseover events were corpse/empty and the agent was searching elsewhere. The delay was not YOLO inference (the cocoon box was present); the 850-byte FAST packet's size fallbacks discarded the structured game-object name, leaving only the quest flag.
- Working-copy fix (**offline-tested, not live-validated**): both addon transport copies now promote the structured primary-tooltip game-object name to the bounded FAST mouseover. A final noncombat size fallback keeps short name + quest ID + cursor + movement/target control together if the richer packet overflows; no second pixelstrip is needed for this name. The agent accepts a fresh same-quest FAST name matching the objective's subject when the long tooltip is absent, rechecks after hover, and lets exact `OBJECT_USE` preempt an entrance-search commitment. Synthetic rich-packet, planner, active-skill and commitment tests pass. The on-disk installed Retail `Transport.lua` hash matched the modified source when checked; the running WoW addon still needs `/reload` or a client restart before this can be tested live. Assistant did not issue client input.

---

## 2026-10-06 19:54–20:00 (pid 12516, user) — cocoon use still blocked by stale hover

- Read-only sources: `output/live-debug/{live-debug,telemetry}-20261006-195457.jsonl`. Quest objective remained 0/5. The agent found visible cocoon candidates and twice proposed `OBJECT_USE` at about 19:58:48 and 19:58:50, but both attempts ended `stale_observation` before right-click/F7. This is a failed live test, not quest credit.
- The FAST mouseover still contained only `quest_related=true, quest_id=55639`; full `MOUSEOVER_CHANGED` events had `tooltip_data.unit_name="Thick Cocoon"` but were not fresh current-hover identity. The addon session ID changed at monotonic ≈702223, before FULL_AI began, so a UI reload did occur during this run. The actual bug in the newly loaded source was that real tooltip metadata carries `guid=""`; Lua treats the empty string as truthy, so the compact-name fallback rejected the object. Both source addon copies and the installed Retail `Transport.lua` now treat empty GUID fields as absent. The focused transport/object-use suite passes with this exact metadata shape; live revalidation requires another user `/reload` or client restart to load this correction and a fresh GUI/agent launch for Python changes. The assistant did not control the client.
- Full repository suite after the earlier transport changes: 2430 passed, 5 skipped, 15 failures matching the previously known baseline categories; focused suite after the empty-GUID correction: 89 passed. No second pixelstrip was added because the bounded FAST packet carries the short object name in the corrected offline test. Next live gate: observe `FAST_STATE.mouseover.name="Thick Cocoon"` at the current cursor, followed by a fresh ObjectUse verification and actual quest counter increase.

---

## 2026-10-06 20:07–20:10 (pid 12516, user) — corrected addon live, one cocoon credited

- Read-only sources: `output/live-debug/{live-debug,telemetry}-20261006-200718.jsonl` and the profile journal. The addon session changed to `1791310020-702769464`, and ten FAST quest-related samples carried `mouseover.name="Thick Cocoon"`, quest 55639. This validates that the corrected addon transport was loaded and the short name crossed the pixelstrip. No second strip was needed for this case.
- `OBJECT_USE` sent HOVER at 702862.879, verified RIGHT CLICK at 702863.777, and the bound `INTERACTTARGET` (F7) fallback at 702866.319. The quest counter subsequently changed **0/5 → 1/5**, with `QUEST_LOG_CHANGED` and a freed expedition member message in the next completed full snapshot at 702873.039. This is one live cocoon credit, not full quest completion. The journal had already marked `OBJECT_USE` failed `QUEST_CREDIT_NOT_RECEIVED` at 702870.911; this is a false negative caused by delayed credit visibility, not a failed interaction.
- The user then observed the agent inspecting a torch and spiders and stopped the run. The journal confirms two subsequent `INSPECT` hovers at 702903.328 and 702904.794 (second at .408,.242) after combat/loot activity; their exact visual identities are user-observed, not independently established by the journal. The full quest was not completed. A follow-up should make the compact FAST lane carry quest-credit change or otherwise defer the negative verdict until the relevant full snapshot; current rich FAST transport includes `quest_digest`, but size fallbacks drop it. No code change for this latency issue was made in this diagnostic turn.

---

## 2026-10-06 20:13–20:15 (pid 12516, user) — MOVE passed visual quest-object candidates

- Read-only sources: `output/live-debug/{live-debug,telemetry}-20261006-201336.jsonl` and the profile journal. The user observed the agent passing a cocoon and stopped the run. The objective in this run remained 0/5; no `Thick Cocoon` FAST name or ObjectUse execution was recorded. A FAST sample at 703212.138 carried only quest-related flag/quest 55639, not a confirmed object name.
- During MOVE, `visual_candidates` included active `quest_object_like` boxes at 703209.888 (WORLD3D:49, confidence .343, stable 4) and 703212.138 (WORLD3D:54, .256, stable 6), both above the class-specific .20 approach/hover gate. At 703213.518 the journal recorded a `SEEK_VISUAL_CUE` plan for objective 55639:0, but no SEEK action started. At 703213.767 a new quest-route MOVE started. The current autonomy loop preempts LOCATION commitments only for addon-confirmed exact `OBJECT_USE`, not for a visual object SEEK; this is a likely reason for passing a candidate before hover. The boxes are visual hypotheses, not proof of cocoon identity.
- A later raw learned `quest_object_outline_like` detection on WORLD3D:56 had learned confidence .698, but its fused confidence was .166 with ≈.612 self-avatar region overlap, below the .20 proposal gate; other nearby candidates had different track IDs. That further narrowed the opportunity after approach. Follow-up: test a bounded, quest-specific visual-object SEEK preemption of LOCATION MOVE when the box is fresh/stable, but keep right-click gated by fresh addon-confirmed identity so torch false positives cannot trigger use. No behavioral code was changed in this diagnostic turn.

---

## 2026-10-06 evening — working-copy port into `projekt`, cocoon/cave fixes (offline only)

- **Port.** The user asked to bring the good parts of `uj-mappa-2026-09-28-1918` (ChatGPT-assisted working copy) into `projekt`. That copy was taken from `projekt` at 09:57 and `projekt` had no later edits, so the diff was exactly the working copy's work: 19 source files (dot focus, vertical-arrow routes, Z-resolver pockets/refs/ambiguity, wall contact, Z-aware search cells, turn-in search limit, ObjectUse hover → fresh sample → right-click → F7, corpse LOOT / OBJECT_USE preemption), both addon copies (`indoors`, FAST game-object name; the installed Retail addon already matched them), 13 tests and its LIVE_VALIDATION/design entries above. Backup of the replaced `projekt` files: session scratchpad `projekt_before_chatgpt_port.tgz`. After the port: 2430 passed, 15 baseline failures.
- **User 09:42 run (pid 1592), "stopped to hover a hunter pet, never left the spiral".** Read-only: journal, `agent_status.json`, live captures, `live-debug/telemetry-20261006-094154.jsonl`. The zone-sweep MOVE was interrupted by a creature box (another player's pet "Gruffhorn") as a quest-route cue; INSPECT failed (cursor 0.28 off the moving box). From 665314.67 to 665339.97 the WorldModel accepted **no** addon packet although FAST sequences advanced 75534 → 76545: the pet's long name pushed FAST into the bounded edge variants, which carry no `timestamp`; `Observation.timestamp` became 0 and `WorldModel.ingest` dropped every packet as out-of-order while `last_received` kept the sensor "fresh". The navigator also banned the sweep hop after 12 s of "no progress" that was really standing during INSPECT. Fixes: the assembler restores a floored timestamp from the last stamped sample + addon monotonic delta; WorldModel never treats a missing timestamp as older; a destination is blocked for circling only after ≥ .004 map units (~4 yd) of actual travel without getting closer; with only game-object objectives open, creature boxes neither interrupt a quest-route MOVE nor get INSPECT.
- **Working-copy 20:07–20:14 runs.** The 20:07 cocoon credit (0/5 → 1/5) became `QUEST_CREDIT_NOT_RECEIVED` because the next complete STATE arrived 2 s after the 8 s deadline (FAST had dropped `quest_digest`); OBJECT_USE was then suppressed 15 s. ObjectUse now keeps waiting (≤ 10 s past the deadline) until a full snapshot sampled ≥ 1 s after the last right-click/F7. The agent had been started inside the pit: the first floor fix took the terrain-matching rim (z≈98) at .5 confidence; required routes then failed `ambiguous_player_layer` three times, the loop guard escalated, and ~45 s WAIT followed; the 20:13 run never entered the cave. Fixes: with addon `indoors=true`, a terrain-matching topmost layer with floors ≥ 8 yd below is pruned from first-fix/hypothesis sets; an ambiguous (< .6) player floor walks a 12 yd probe leg from the likeliest hypothesis that has a route (a continuity-held floor probes only itself), failing closed only when none has a route. Replay of the 20:08 segment with the real navmesh: 61.9 → 60.5 (.5) → 55.4 → 51.3 → 48.0 (.95) while the MOVE continues.
- **Telemetry finding (not fixed):** the 7-page STATE completed only 4 times in ~100 s (pid 1592) and seq 93 → 104 passed with one completion (20:07). Tooltips, quest credit and events therefore lag seconds behind; the addon shows each state page set only ~one round before re-encoding.
- Tests: `tests/test_cocoon_port_fixes_20261006.py` (7), updated `test_cave_quest_layer_flow_20261006.py` (+2, two fail-closed expectations now probe legs), `test_agent_core.py::test_navigation_circling_guard` (circling now requires travel). None of this is live-validated; the user runs the next test (addon unchanged since the working copy's 20:04 install).

---

## 2026-10-06 21:14–21:19 (pid 2212, user, `projekt` after the port) — cocoon credit, three cocoons left behind

- Sources (read only): profile journal session `1791313723-706465213`, `output/live-debug/{telemetry,live-debug}-20261006-211432.jsonl`, `output/agent/pid-2212/feed_association_trace.jsonl`. The user reports two cocoons opened across the evening's runs; this run shows one credit (0/5 → 1/5 at 706882.9, `QUEST_CREDIT_OBSERVED`). The user stopped the run; no FULL_AI left running.
- Flow that worked: start outside at the entrance (indoors=false) → zone sweep → down-arrow route (BELOW) 11 s down to the ledge → learned cocoon box SEEK → mouseover OBJECT_USE.
- Cocoon 1 (706862.8): the right-click turned the character 19° and stepped it 1.5 yd toward the cocoon (client auto-approach); no use started, no UI error; the cursor/view changed so the F7 fallback never qualified; the skill waited 15.4 s (no full STATE arrived: seq 450 for 18 s). A second OBJECT_USE (right-click + F7) credited it. Fix: once stopped after such a turn/step, click once more where a fresh sample names the object under the current cursor (never for a cursor-only move).
- Cocoon 2 (706931–706947): hovered at the screen bottom (a lower cocoon, not the YOLO box at y .17–.37); right-click and F7 both answered `You are too far away.` (`ui_error_at` 706931.839, code 289); 2 × 8 s waits, then a 15 s OBJECT_USE suppression and a SEEK/MOVE flip-flop (10 SEEKs of 0.2 s). Fix: OUT_OF_RANGE on that error; 6 s approach (cocoon SEEK at priority 93) with a learned ready box height (+25 %, ≥ 1.3 × the box at the error; credited cocoon box ≈ .19–.24); OBJECT_USE cooldown 5 s for out_of_range, 2 s for stale_observation, 3 s for identity_uncertain.
- 706962–706994: a quest-area search cell (142, −2218) without height resolved to the rim; the MOVE ran up the spiral to the entrance (indoors=false at 706984) and back. Fix: search cells carry `floor_hint: SAME`; indoors, a cell whose best SAME-floor target is > 15 yd off the player's floor is marked visited and skipped.
- Cocoon 3 (707071.9): OBJECT_USE began while the character still coasted after a dot MOVE; 0.9 yd later `stale_observation` (0.3 s) → 15 s suppression → OPEN_MAP, local SEEK, search cell, arrow MOVE: the cocoon was left. Fix: wait while moving, then re-hover the unmoved cursor and require fresh identity (≤ 2 rebases within 3 s).
- Still seen, not fixed: 8 consecutive 0.1 s "successful" zone-sweep MOVEs to the same rim hop (706902–706903); one `ambiguous_player_layer` at the entrance (706849.9) before the arrow route succeeded; ACQUIRE_TARGET `expected_observation_missing` and DEFEND `target_lost` in two spider fights; full STATE assembly remains rare (47 completions of 1720 pages in this run).
- Tests: `test_m1_object_use_skill.py` (+4: view rebase, coasting, too far, reclick/no reclick), `test_cocoon_port_fixes_20261006.py` (+1 too-far approach). Offline only; the next user run must show the reclick, the approach after "too far", and no 15 s stalls.

---

## 2026-10-06 21:28–21:29 (pid 2212, user) — back and forth on the ramp below the entrance; spiral edge

- Sources (read only): journal session `1791313723-706465213` (707676–707733), `output/live-debug/{telemetry,live-debug}-20261006-212826.jsonl`. One down-arrow MOVE (BELOW, (81.2, −2278.2) → z 61.26) from the entrance; from 707702 to 707733 the character stayed within 2 yd of (69, −2220.5) turning back and forth (orientation 0.27 → 3.87 → 6.13 → …); user stopped it.
- Direct NavigationService replay with the real navmesh and the recorded positions reproduces it: continuity kept the player on the rim polygon that overhangs the ramp (z 93.5, `continuity_near` .7) while the route and the controller's own surface sample put him at ~76.8; the next waypoint (z 83.1 / 76.4) was "on another layer" and never passed. The controller's arrival also measured 3D distance to the request's final z (61.26): 15.9 yd to a waypoint ~1 yd away.
- Fixes: `_route_hint_z` interpolates the active route at the player (≤ 4 yd corridor) and the resolver prefers, among continuity-reachable floors, the one within 3 yd of it (`continuity_route`, .85); intermediate waypoint destinations carry their anchor's own `z`; `_on_next_leg` treats a waypoint as passed when the player is already within 2.5 yd of one of the next four legs on his floor (±6 yd). Replay: player z 78.6 → 76.9, waypoints advance 2 → 3 → 5 → 6 instead of staying at 2.
- User request "a spirálon … eléggé a szélén megy, jobb lenne ha bentebb menne": the native centered path now also pushes each point away from the nearest navmesh boundary (Detour `findDistanceToWall` + `moveAlongSurface`, up to 3 passes, stops when clearance stops improving) to `PATH_CENTER_MARGIN` = 2.5 yd; intermediate waypoints are taken at 1.5 yd instead of 2.5 (the larger radius cut each bend toward the drop). Spiral rim → bottom: median offset from the shortest path 1.5 → 2.5 yd, length 525 → 565 yd. DLL rebuilt (`native/bin/aipc_detour.dll`, previous kept as `aipc_detour.v3.bak`).
- Offline only; next user run: the ramp below the entrance, the spiral line (away from the drop), and no turning back to a passed waypoint. Full suite: 15 baseline failures.

---

## 2026-10-06 21:41–21:54 (pid 2212, user) — "Who Lurks in the Pit" completed; review and optimization required

- Sources (read only): journal session `1791313723-706465213` (708464–709220), `output/live-debug/{telemetry,live-debug}-20261006-214106*.jsonl` (three rotated files). User report: one cocoon skipped early, 4/5 reached, the last cocoon was above; the agent did not notice the arrow until the user moved the character a little; 5/5; a fall to the bottom; Hrun killed; the user started Ralia's ride; at the end the agent wanted to go back into the pit.
- **Outcome (user decision): the quest was completed, but the Z resolver + multi-floor cave flow is not finished — it must be reviewed, rethought and optimized.** Progress: 0/5 (708468) → 1/5 (708588) → 2/5 (708643) → 3/5 (708695) → 4/5 (708736) → 5/5 (708923) → Hrun 1/1 (709116) → Ride 1/1 (709215, user-operated ride). 160 MOVE, 37 SEEK, 20 DEFEND, 16 ACQUIRE_TARGET, 14 INSPECT, 13 LOOT, 6 OBJECT_USE; failures: SEEK 12, INSPECT 11, MOVE 10 (`ambiguous_player_layer` ×7), DEFEND 12, LOOT 7, VISUAL_APPROACH 3.
- Findings: (1) ABOVE from the pit bottom (z −4.9) resolved to −1.8 on the same floor (3 yd threshold) → "arrived" under the cocoon ledge (60.5); the second ABOVE from 44.6 chose 60.5 correctly. (2) The rim sweep hop (z 92.4) was "passed" by navigation but not marked by the planner (fresher gate) → 30 instant MOVEs in 4 s, and again 708984–708998. (3) Mid-route ambiguity failed seven MOVEs immediately. (4) Barrow spider target GUIDs change during combat (…C54D3F → …454D3F, …C54CFE → …454CFE): DEFEND restarts with IDENTITY_UNCERTAIN (~2 s each). (5) COMBAT_STARTED interrupts cancelled combat VISUAL_APPROACH and MOVEs proposed during combat (churn). (6) Two `input_blocked` safety stops (keyboard focus / game menu; user interaction) switched to MANUAL. (7) Ride objective (`raw_type` monster, Ralia 156929): TARGET ok, VISUAL_APPROACH lost, then dot MOVE flip-flop at the 15 yd stop radius, INSPECT failures, BELOW move `no_layer_matching_floor_cue` ×3, WAIT — never interacted. (8) After landing, REACH_OBJECT to Ralia (156932) carried `z: 0.0` from `number(z) or 0.` → treated as a known height → a route back into the pit. (9) Full STATE completed 199 times from 4390 pages.
- Fixes (offline-tested): REACH_OBJECT keeps unknown height unknown (`z_known: False`, `floor_hint: SAME`); ABOVE/BELOW require one storey (`STOREY_YARDS` = 6) in filtering and scoring (replay: ABOVE now targets 45.6 from −4.9); `_sweep_hop_passed` records the hop in the sweep's `visited`; mid-route ambiguity tolerated for 4 s (`AMBIGUOUS_ROUTE_GRACE_SECONDS`). Not fixed: DEFEND GUID swap, combat interrupt churn, ride/gossip interaction, dot flip-flop at the stop radius, loot failures, STATE assembly rate.
- Full suite: 15 baseline failures (2449 passed).

---

## 2026-10-06 22:0x — addon 0.9.58: full STATE assembly (offline analysis, installed, not yet live)

- Measured in the 21:41 run (pid 2212 sensor diagnostics + telemetry sequences): the addon produced ~30.7 FAST sequences/s (≈ 37 transport ticks/s, i.e. the client frame rate) and 1.06 STATE sequences/s; 26404 frames were captured for ≈ 30 600 ticks (~80–86 %); 4390 STATE pages for ~880 sequences (~5 pages captured of ~6); only 199 sequences completed (23 %). Each sequence was shown exactly one round (`round >= 1` and the snapshot's `monotonic_time` always changes), so a page lost to capture was never re-sent: 0.8^6 ≈ 0.26 explains the rate. A 100 % per-frame capture is not physically guaranteed: DWM shows at most one game frame per refresh.
- Change (both addon copies, `Transport.lua`, version 0.9.58): one STATE page every 4 packets (was 6) and every snapshot shown for at least two full rounds before re-encoding. Simulation (37 ticks/s, 80 % capture, 6 pages): complete snapshots 0.26/s → 0.60/s, median gap 2.9 → 1.5 s, p95 gap 11.7 → 3.2 s; captured FAST 24.7 → 22.2/s. Tests: `test_transport_multiplexes_three_fresh_fast_samples_per_state_page`, `test_every_snapshot_is_shown_twice_so_a_lost_page_comes_back`; full suite 15 baseline failures.
- Installed into `_retail_/Interface/AddOns/AIPlayerControllerExport` after checking it matched the previous 0.9.57 build; the client needs `/reload`. Next live check: `completed_full_states / state_pages` in `agent_status.json` (expect ≈ 1 completion per ~13 pages instead of ~22); if assembly stays < 95 %, hold each STATE page for two frames.

---

## 2026-10-06 22:10–22:16 (pid 2212, user, addon 0.9.58) — no-quest pickup between Private Cole and Henry Garrick

- Sources (read only): journal session `1791317345-710094182` (710181–710587), `output/live-debug/{telemetry,live-debug}-20261006-221011*.jsonl`. The addon session changed, so 0.9.58 was loaded: 3653 STATE pages / 229 complete snapshots (16 pages per snapshot vs 22 before; ≈ 75 % assembly, simulation 78 %).
- Done: turned in 55639 (710295), accepted and turned in 85678 (710297–710429). Then no quest: the API listed campaign "!" givers 58914 at (187, −2280) = Private Cole and 55196 at (267, −2339) = Henry Garrick (user). The agent targeted Lady Jaina from a hover next to Cole, VISUAL_APPROACH (one 30 s timeout) and INTERACT `no_response` for ~60 s, walked toward Henry Garrick, "arrived" at 8.5 yd (10 yd radius) — the reached pin is skipped for 300 s — and turned round 80 yd to Cole's pin; 68 INSPECT, 26 IDENTIFY seeks, 22 VISUAL_APPROACH, 19 TARGET; user stopped it.
- Telemetry shows the client's `softinteract` unit at the pin: Private Cole at 3.8–5.2 yd from (187, −2280), Quartermaster Richter (vendor) at 7.5–8.9 yd. NPC world positions are not exported (only the target's).
- Fixes (offline): API giver arrival 4 yd (was 10); within 6 yd a friendly `softinteract` NPC gets `INTERACT` with `activation_source: SOFT_INTERACT` (`INTERACTTARGET`, no hard-target identity, success = quest/gossip/vendor window; once per NPC per giver per 30 s; priority 104); after reaching a giver no other giver route for 10 s (`GIVER_LOCAL_SECONDS`, user: "25 s sok, legyen 10 s"), a drifted agent walks back to it; at an API pin a different soft-interact NPC makes the selected unit irrelevant (`soft_interact_giver_waiting`). Tests: `test_map_pois.py` (+3, one rewritten), `test_stale_friendly_target_20261005.py` (+1), `test_pit_layer_and_pins_20261005.py` (updated). Full suite: 15 baseline failures. Not live-validated; whether INTERACTTARGET always prefers the soft-interact unit over a different hard target must be confirmed live.

---

## 2026-10-07 11:06–11:08 (pid 15440, user, addon 0.9.59) — one cocoon, then a sweep-hop / search-cell ping-pong on the spiral

- Sources (read only): uploaded `telemetry-20261007-110601.jsonl` (131.8 s) and `agent_status.json`. Journal session `1791363480-756217315`; goal created at 756719.99; the user stopped the run at 756832.78 (`mode_changed`). Final state: mode STOPPED, executor disarmed, no held keys, so no FULL_AI process was left running. Character: Mklé, warrior 7, Hrun's Barrow (map 1409, instance 2175), quest "Who Lurks in the Pit" (55639).
- Progress: 0/5 → 1/5 at 756766.0 (`object_use_credit_verified`). Evidence: mouseover "Thick Cocoon", `SPELLCAST_SUCCEEDED` 321523, then "Freed Expedition Member". The first OBJECT_USE attempt ended `IDENTITY_UNCERTAIN` (756762.8). No further credit.
- 756771–756810: three SEEK_VISUAL_CUE runs ended `seek_visual_cue_sectors_exhausted` (TARGET_NOT_FOUND), so no cocoon was visible from the upper spiral. The area search walked cell (81, −2272) twice. Cells (59.8, −2263) and (102.2, −2263) were retired as off-floor.
- 756811–756832 (and a 38 yd variant before that): two MOVEs alternated every ~1.6 s, each ending `reach_arrival_verified`, while the player stayed in a 4 yd patch around (72–76, −2236…−2239) at z 67.9 (MMAP, confidence .95):
  - (A) zone-sweep hop 4/39 at (69.1, −2239.7), z 69.5, stop distance 6.
  - (B) quest-area cell 1:1 at (81, −2242). This cell lies over the pit hole. Its SAME-floor projection was (76.0, −2235.7), 8.06 yd from the cell, outside the 7.5 yd visit radius (30/4). The cell therefore never counted as visited (visits 0).
- Why the two never advanced:
  - The hop was not marked by the arrival either, because B's arrival took the player 8 yd away before the planner looked at the sweep again.
  - After A arrived, `world_arrived` (≤ 6 yd) made the location non-actionable, so the area SEEK won (utility 79.7 against the sweep's 67.7 with its distance penalty). After B arrived, the sweep offered hop 4 again.
  - The loop guard saw only `MOVEMENT_OSCILLATION:TURNLEFT:TURNRIGHT` ×3. The A/B alternation itself went undetected.
- Root cause of the never-marked hop. The same cause explains two 2026-10-06 findings: "8 instant MOVEs to the same rim hop" and "not marked by the planner (fresher gate)".
  - `zone_sweep_next` and `_search_player_z` tested freshness as `0 <= now − at <= 3`. Here `now` is the addon's `state.monotonic_time` (GetTime at sampling) and `at` is the Z resolver's fix time (agent clock at processing).
  - Live, the sample comes ~0.1 s before the fix (status: `monotonic_time` 756836.377 vs `fast_received_at` 756836.469). Every fix was therefore rejected, and the planner's position test never marked a hop.
- Fixes (offline-tested, `tests/test_sweep_cell_pingpong_20261007.py`, +5 tests):
  - Both freshness tests use a symmetric window, `|now − at| <= 3`.
  - `NavigationService.observe_verified_move` retires the zone-sweep hop of a verified arrival (`record_sweep_arrival`; only when the hop matches the current sweep within 1 yd).
  - It also retires the search cell of a verified arrival (`search_region_id` + `search_cell_id`), including when the route ended at the cell's same-floor projection.
  - Full suite: 33 baseline failures, 2494 passed, no new failure.
- Other measurements:
  - STATE assembly: 1197 pages, 82 complete snapshots (14.6 pages per snapshot, 0.77 Hz). The 0.9.58 run needed 16 pages per snapshot.
  - After STOP, one memory maintenance pass took 2061 ms for 256 rows. FULL_AI defers maintenance, so this is outside the control path. The DB is 139 MB, grows ≈ 214 MB/h and has a backlog of 47 545 rows, so it grows unbounded during long FULL_AI runs.
  - The binding inventory is still collecting (22 of 23 pages) and lists 22 catalog differences against the selected cache (`authoritative_for_input: false`). The selected cache file is named `pid-19664` while the selected PID is 15440. The control-binding preflight was ready with no mismatches.
- Open, not fixed:
  - No loop detection for alternating "successful" MOVEs.
  - The next user run must show the sweep advancing beyond hop 4 down the spiral to the cocoons.
  - SEEK sector exhaustion on the upper spiral.
  - Maintenance cost and DB growth.

---

## 2026-10-07 11:13–11:21 (pid 15440, user, addon 0.9.59, without b0f0d32) — 3/5 cocoons; quest credit and errors stuck behind the paged STATE

- Sources (read only): `_j_1.txt` + `telemetry-20261007-111331.jsonl` + `_j_2.txt`, one continuous telemetry run (mono 757176–757644), and `agent_status.json`. Goal created at 757168.65. The last agent decision was at 757578.1, after which the run was STOPPED; the user abandoned 55639 manually at 757603.8 with FULL_AI no longer running. Final state: no held keys, executor disarmed. The run did not yet contain b0f0d32.
- Progress: 0/5 → 1/5 (757247.0) → 2/5 (757457.9) → 3/5 (757482.6). Combat: two Barrow Spiders, both killed and looted; one `loot_ui_not_opened` (757364.4) was followed by a successful loot.
- Upper spiral (757247–757437):
  - The agent circled the rim and walked outside once (indoors=false 757312–757326).
  - All nine cells of area region 0 were retired at once at 757408.5 as off-floor.
  - 34 deduplicated FALL_STARTED events, mostly short ramp-edge hops; the resolver's `fall_count` stayed 0.
  - Eight `seek_visual_cue_sectors_exhausted` results and three `visual_track_lost` over the run.
- Lower floor (757483–757578): the zone sweep reached hop 18/38 (58.3, −2199.5, z 21.3) and alternated with search cell (81, −2212), both "arrived". This is the ping-pong fixed by b0f0d32.
- Cocoon 1 took 15 s and three attempts: two `STALE_OBSERVATION` results (757226.9, 757232.4) before the credit. The decision log does not reach back that far, so this stays open.
- **Root cause found in this run: the STATE assembly rate.**
  - 3348 STATE pages produced 108 complete snapshots (31 pages per snapshot; the 11:06 run needed 14.6).
  - `state_sequence` stayed unchanged for more than 5 s during 323 of 468 s, with a maximum of 30.3 s.
  - Every live FAST packet was a bounded variant without `quest_digest` or `ui_error` (reproduced with the Lua transport). Quest progress and UI errors therefore arrived only with the paged STATE.
  - Cocoon 2 credit: STATE was frozen from 757437.0 to 757457.9 (seq 1037 → 1057). OBJECT_USE failed `QUEST_CREDIT_NOT_RECEIVED` at 757456.7 (deadline plus the 10 s grace), 1.2 s before 2/5 arrived.
  - Cocoon 3: "You are too far away." at 757466.9 and 757467.9 became visible only at ~757471, so a second click went out first. The approach then followed (41.2 → 37.1, −2197) and the cocoon was credited.
- Fixes (offline-tested, e329869, addon 0.9.60; the addon must be installed and the client `/reload`ed):
  - Every FAST variant re-adds `quest_digest`/`quest_state_revision` and a fresh `ui_error` when the packet still fits (error first).
  - `QuestProgressVerifier` credits FAST digest progress for single-objective quests. `fast_digest_progress` needs a baseline and never treats a stale digest next to a newer snapshot as progress.
  - Accepted ids that reappear for an already active quest do not count as an acceptance.
  - OBJECT_USE credit grace raised to 25 s while no newer snapshot has arrived.
  - Tests: `tests/test_fast_quest_credit_20261007.py` (+9). Full suite: 33 baseline failures, 2503 passed.
- Open:
  - With 25 quests the digest does not fit at all, and with an error present the digest is dropped, so the single-strip FAST budget is the structural limit. User proposal: a wider top pixel strip carrying separate FAST and STATE lanes, masked out of YOLO.
  - STALE_OBSERVATION at cocoon 1.
  - Leaving the barrow during the area search.

---

## 2026-10-07 — addon 0.9.61: two-lane top pixel strip (offline-tested, not yet live)

- Why: in the 11:13 run (above), full FAST samples were 1.1–1.5 KB. The 850-byte single-strip budget therefore always fell back to a bounded variant. The STATE was also sent only on one rendered frame of every four, while the capture kept ~27 of up to 60 frames/s, so 3348 pages produced only 108 snapshots. User decision: one long strip along the top, masked out of YOLO.
- Layout (`AIPlayerControllerExport.lua`, `computePixelLayout`):
  - 32 rows of cells exactly 4 physical pixels square, starting at 12 px from the top-left.
  - The strip runs right up to `MinimapCluster:GetLeft()` − 8 px (a 220-unit reserve when the minimap position is unknown).
  - FAST lane: 224 columns (packet ≤ 1784 bytes). STATE lane: the remaining columns, between 64 and 224. A 1600×829 client gets 224 + 129 columns.
  - Re-laid out on `DISPLAY_SIZE_CHANGED`/`UI_SCALE_CHANGED`. With fewer than 240 columns (~1200 px wide clients) it falls back to the former single strip.
- Framing:
  - Each lane carries header (8 cells), marker byte 254, column count (2 bytes), length (2 bytes), payload and checksum. The STATE lane starts right after the FAST lane's columns.
  - A legacy length's high byte is at most 3, so old and new strips cannot be confused.
  - Only changed cells are redrawn, so a held STATE page costs nothing on its second frame.
- Transport (`Transport.lua`): `NextLanePackets` returns a FAST packet (the richest variant up to the lane budget) and a STATE page every frame, each page held for two frames (`STATE_PAGE_HOLD`). The single-strip `NextPacket` is unchanged.
- Python side:
  - `pixel_bridge._decode_lanes` returns both packets newline-joined. A torn STATE lane keeps the frame's FAST packet.
  - `PacketAssembler.feed`/`feed_lanes` feeds FAST first, so a snapshot completed in the same frame merges it; one bad lane does not discard the other.
  - The page bound was raised to 4096 bytes. The sensor reports `two_lane_frames`.
  - The YOLO `addon_hud` hard mask is now the full-width top band of max(18 % of height, 148 px).
- Tests: `tests/test_two_lane_strip_20261007.py` (+7; the addon's own drawing code is rasterised and decoded). Full suite: 33 baseline failures, 2510 passed.
- Next user run: install the addon and `/reload`. Then check in `agent_status.json` `sensor_diagnostics…two_lane_frames > 0`, `completed_full_states / state_pages` (it was 108/3348) and `completed_full_state_hz`, and watch the client FPS with the wider strip.

---

## 2026-10-07 12:06–12:17 (pid 15440, user, addon 0.9.61 two-lane strip, with b0f0d32 + e329869) — all five cocoons; health 0, cast-time and empty-corpse defects

- Sources (read only): `telemetry-20261007-120632{.1,}.jsonl` (complete: from 8 s after goal creation at 760352.2 to the last status sample at 761026.0, no gap longer than 5 s) and `agent_status.json`. The user stopped FULL_AI at 760964.3 (`mode_changed`) and abandoned 55639 manually at ~760977. The user walked to the last cocoon by hand.
- Transport (0.9.61) live:
  - 21 965 of 21 975 captured frames were two-lane, and all of them decoded.
  - 717 complete snapshots, ~1.12 per second (0.23 per second before). 717 of the addon's 805 snapshot sequences completed (25 % before).
  - Longest `state_sequence` hold: 3.1 s (30 s before). Events missing from the log: 27 of 1079 (27 % before). ~29.5 fresh FAST packets per second.
  - `quest_digest` arrives on FAST.
  - Side effects: agent tick median 15 ms (5.8 ms in the 11:06 run's sample); memory DB growth 347 MB/h.
- Progress: accepted 760378.8 → 1/5 760413.6 → 2/5 760525.5 → 3/5 760558.1 → 4/5 760817.3 → 5/5 760954.2. The second objective (Ralia) appeared at 5/5.
- User report: falls were corrected well. MOVE got stuck repeatedly, and LOOT and MOVE went back and forth when entering and leaving combat. At two cocoons the mouse was on the cocoon and OBJECT_USE was proposed, but nothing happened.
- Findings and fixes (offline-tested, `tests/test_cocoon_loot_health_20261007.py` +6, addon 0.9.62):
  - **Health was 0 on every FAST packet.** 12.1 returns a secret `UnitHealth("player")` and `safeNumber` turned it into 0, so the agent saw 0 % health all run (the defensive-spell rule fired). Fix: `optionalNumber` in `readFastState`, and `normalize` treats 0 health of a living player as unknown.
  - **Cocoon 4.** At 760792 "You are too far away." → approach. From 760812.1 the cocoon was hovered for 2.4 s before the cast started; the right-click apparently did nothing and the 2 s F7 fallback started it. OBJECT_USE then failed `quest_credit_not_received` at 760815.4 while `is_casting` was true; the credit came at 760817.3. Fix: the skill keeps waiting while its cast runs (`CAST_GRACE_SECONDS` 6 s).
  - **Cocoon 5.** The FAST digest credited it (760952.7). The snapshot still read 4/5, so a second OBJECT_USE right-clicked the freed prisoner ("Invalid target", SPELLCAST_FAILED ×2). Fix: `ObjectInteractionFlow.just_credited` holds the under-cursor use for 3 s at the same cursor point.
  - **Loot (corrected after the user's review and the decision log `live-debug-20261007-120632.jsonl`).** Barrow Spiderlings are lootable; `lootable=false` only means already looted or too far away, so the empty-corpse rule was withdrawn. The real cause: when combat ended, the suspended MOVE (`Megszakított, még mindig érvényes részfeladat kontrollált folytatása`) was injected as the *preferred* proposal and bypassed ranking. The dead target's LOOT (priority 85) also lost to the quest-dot and zone MOVEs (84–92). The agent walked off, and the later LOOT had no corpse position (Retail gives a world position only for the selected target), so `move_to_entity` returned None and the LOOT failed with `corpse_not_found` (7×) and went back and forth. Fixes: the supervisor resume waits while a LOOT, a LOOT approach or an OBJECT_USE is proposed (resume window 180 s); out of combat the dead target's LOOT is priority 107.
  - **Cocoon 3.** OBJECT_USE (760538.8) spent ~7 s of its budget waiting for the character to stop and the hover to settle, then failed `quest_credit_not_received` ~1.5 s after the right-click. Fix: a sent click always gets 5 s (`POST_CLICK_SECONDS`, covers the 2 s F7 fallback and its cast).
  - Barrow Spiderlings appear under two GUIDs that differ in one bit (…0000461B1F / …0000C61B1F). At 760778 they appeared as the mouseover and the soft-interact unit at the same time, so they are probably pairs of distinct units; GUIDs are not merged.
  - Full suite: 33 baseline failures, 2516 passed.
- Open:
  - Why the right-click on cocoon 4 did not start the use.
  - Agent tick cost and memory DB growth with ~5× more snapshots.
