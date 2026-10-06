# Multi-resolution, layer-aware navigation and world model: design backlog

Status (2026-10-03): **steps 1-3 of the revised order (§9) implemented,
offline-tested, not yet live-validated** — see §12.  Originally discussed with the user on 2026-10-01. User priority:
character/unit recognition and questing come first; this whole document
(including the Live Vision route view) comes after.** The user
explicitly asked to discuss first and to come back to this later. Nothing here
is implemented or validated. Units: WoW world coordinates are yards
(1 yd ≈ 0.914 m).

## 1. Current state (code facts, 2026-10-01)

- **mmap** (`navigation/mmap_navmesh.py`):
  - TrinityCore tiles per ADT grid (533.33 yd); LRU cache of 96 tiles.
  - A **single-level A\*** over every polygon in a 2D "corridor" of tiles
    along the start→goal line (+padding); the last 3 corridor graphs are
    cached.
  - Long routes therefore visit many polygons. A real detour outside the
    straight corridor gives `no_polygon_path`.
- `NavPolygon` already holds `key=(tileKey, polyIndex)`, 3D vertices,
  `neighbours` and `flags` (ground/steep/water/magma). The search graph is
  3D-layered, not a 2D grid.
- `project_position` returns every stacked height at an x,y and flags
  `surface_layer_ambiguous`; an active-route z hint keeps the layer.
- **maps** (terrain height/liquid) are used for z hints.
- **vmaps** are configured but `NOT_IMPLEMENTED` (no collision/LoS queries).
- `navigation/transition_resolver.py` has `FIND_CAVE_ENTRANCE` and
  `CHANGE_FLOOR`; they are proposed after repeated local blockage.
- The addon exports `IsIndoors`, the subzone, the uiMapID (many caves have a
  child map), player `UnitPosition` with z, quest POIs
  (`C_QuestLog.GetQuestsOnMap`, `C_TaskQuest.GetQuestsOnMap`, **points
  only**) and `C_QuestLog.GetNextWaypoint` (+ text).

## 2. Hierarchical navmesh (user proposal, agreed direction)

Not graphical LOD, but navigation graphs at several resolutions:

| Level | Content | Typical range |
|---|---|---|
| 0 | full Detour polygons | ≤ ~100–150 yd around the player |
| 1 | clusters (~64 yd cells) with portals between them and precomputed intra-cluster costs | zone |
| 2 | ADT-tile connectivity, islands / reachability | map |

- Plan coarse (level 2 → level 1), then refine only the next ~100–150 yd at
  level 0. Replan locally while moving (HPA\*-like; paths a few % longer
  than optimal).
- The upper levels are static per map: build them offline once, cache on
  disk (or lazily per tile; open question).
- **Clusters must be layer-aware** (see §4): a cave under a hill is a
  different cluster from the hill; the entrance is a portal between them.

## 3. Tile-based multi-resolution world model (user proposal)

`World → Zone → Tile → Navmesh → Local detailed collision`, streamed by rings
around the player:

- near: full polygons + (later) vmap collision;
- mid: cluster graph;
- far: ADT connectivity + terrain only.

Geometry LOD (LOD0 ≤50 m … LOD3 500–2000 m, terrain beyond) is useful for a
3D world model / visualisation, much less for decisions.

Memory: keep detailed levels as numpy arrays, not per-polygon Python objects.

## 4. Layered navigation: same x,y, several walkable z (user)

Example column: bridge/hill top Z=120, tunnel/cave Z=85, valley floor Z=60.

Roles:
- **MMAP** decides where one can walk. The TrinityCore mmap was generated
  with vmap collision baked in.
- **VMAP** gives walls, ceilings and line of sight (ranged combat, why a
  target is not visible), indoor detection, and fall/jump decisions.
- **MAP** gives terrain heights. It is used for the "covered" test and as an
  outdoor ground reference, never as the walkability authority.

Agreed principles, with the assistant's refinements:
1. **No parallel NavNode structure.** Extend the existing polygon graph
   (polyRef = tile+poly, neighbours, flags, 3D vertices) with derived
   attributes.
2. **No global numbered `layerId`.** Layers connect continuously (ramps,
   slopes), so that is ill-defined. Instead store:
   - the polyRef (identity: "where am I");
   - a semantic label per polygon: SURFACE / COVERED (under terrain:
     poly z ≪ terrain z, later also a vmap ceiling) / BRIDGE;
   - a **region id** = connected component of polygons with the same label.
     The cave is one region and the hill another; their boundary is the
     entrance portal. This is the meaningful "layerId" for level 1.
3. **Track the character's own polygon continuously.** Only allow moves to
   adjacent polygons (Detour corridor style), so noisy or missing z can
   never teleport the agent from the cave onto the surface. Missing z must
   be explicit "layer unknown", never "nearest surface".
4. **Remove the 2D leak points**, the real danger. Found in code:
   - `mmap_navmesh._nearest_polygon(use_vertical=False)` picks endpoint
     polygons by horizontal distance only when z is unknown. With stacked
     layers this is effectively arbitrary (bridge instead of cave floor).
     This is the highest risk.
   - Arrival, search-coverage and roaming cells use 2D distance: standing on
     a bridge above the target would count as arrived.
   - The danger map, `global_planner` distance estimates and memories (quest
     locations, visited points) are x,y only.

## 5. Caves / tunnels: going down and coming back up (user case: a spider cave)

- **Entrance detection from data:** polygons whose height is well below the
  terrain (e.g. >3 yd) are COVERED. Where COVERED polygons connect to
  uncovered ones is the entrance, computed purely from MAP+MMAP, with no
  vision and no DB.
- **Which layer is the target on.** The user requires DB-Z to be fallback
  only. Order:
  1. Blizzard waypoint (`GetNextWaypoint` + text, e.g. "Enter the cave"),
     which usually leads to the entrance first;
  2. the quest POI is on a cave child map, or the uiMapID changes on entry;
  3. the mmap shows a COVERED layer under the POI x,y;
  4. own memory (visited before);
  5. **DB spawn z — fallback only.**
  - If still unsure: navigate to the computed entrance (a certain point),
    then search below.
- **Going down / up:** put the destination on the chosen layer's polygon;
  A\* passes the entrance ramp by itself. Leaving uses the same path in
  reverse.
- **Confirmation in play:** `IsIndoors` turns true, the uiMapID/subzone
  changes and the minimap goes indoor.
- **Execution risks inside:**
  - camera collision changes the view;
  - darkness weakens YOLO;
  - narrow passages need vmap + the visual local world;
  - water needs swimming (currently excluded by the mmap filter);
  - jumping down is possible, up only via the ramp.
- **Requested first experiment** (no FULL_AI): the user walks into the
  spider cave and out while logging runs. Then check the waypoint text,
  uiMapID/`IsIndoors` changes, the COVERED boundary from MAP vs MMAP, and
  layers under the POI. Quest name/ID to be supplied by the user.

## 6. Visualisation (discussed; not started)

- **A) Top-down inset in Live Vision:** player, nearby navmesh polygons
  (coloured by label/region), the MOVE route polyline, next waypoint and
  destination, tile/ring boundaries. Exact (world coordinates only); doubles
  as the debug view of the hierarchy. Recommended first.
- **B) Route drawn onto the game image:** approximate. The camera pose is
  unknown in Retail; follow-camera assumption; the addon could export
  `GetCameraZoom`. Route line only; the navmesh projected on the image would
  be clutter.
- Data path: the route lives in the agent process while Live Vision is fed by
  the World3D process, so a small latest-only nav-overlay channel at
  1–2 Hz is needed.

## 7. Proposed order (when resumed)

1. **Measure:** route compute time, polygons visited,
   `no_polygon_path`/`supported_stuck` rates. Cheap.
2. **Layer safety:** current-polygon tracking, z-aware endpoint selection,
   3D/region-aware arrival, explicit "layer unknown".
3. **Labels + regions:** SURFACE/COVERED/BRIDGE and entrance portals; spider
   cave experiment.
4. **HPA\*:** level 1/2 graphs for map 2175 (Exile's Reach), offline cache,
   tile rings.
5. **Top-down Live Vision inset.**
6. **VMAP:** LoS/ceiling queries near the player.
7. **Geometry LOD** for a 3D world model, only if visualisation needs it.

## 8. Open questions for the user

- Offline build of the upper levels vs. lazy per tile?
- VMAP in the first round or later?
- Inset vs. projected route vs. both?
- Priority relative to gameplay fixes (turn-in, combat range/follow)?

## 9. Assistant's alternative (preferred): native Detour instead of Python HPA\*

- TrinityCore mmaps *are* Recast/Detour tiles, and the TrinityCore server
  itself paths with Detour (`PathGenerator`). We currently run a hand-written
  Python imitation.
- Native Detour already provides what §2/§4 want:
  - 3D-extent `findNearestPoly`, so stacked layers are not mixed;
  - `dtPathCorridor` / `moveAlongSurface`, which is exactly "track the own
    polygon continuously, move only to neighbours", robust to the known
    false client Z=0 (see `MMAP_NAVIGATION.md`);
  - query filters with area costs (water, steep) and sliced pathfinding;
  - C++ speed: a 2 km polygon-level route takes milliseconds, so a
    hierarchical navmesh is probably unnecessary or much later.
- Cost: a compiled Detour DLL or Python binding on Windows (zlib licence). A
  one-time build, far less risk than a home-made HPA\*.
- Keep from the user's plan:
  - the mmap/vmap/map roles;
  - SURFACE/COVERED/BRIDGE labels and regions for cave entrances;
  - removing the 2D leak points;
  - tile rings if memory becomes tight.
- Extra idea: **footprint memory**. Remember actually traversed polygons
  (the measured-anchors groundwork exists) and prefer proven-walkable ones
  where the mmap disagrees with reality (slopes, doors).
- Revised order:
  1. measure;
  2. native Detour + corridor tracking;
  3. 2D leak fixes;
  4. labels/regions + spider cave experiment;
  5. top-down inset;
  6. vmap;
  7. hierarchical navmesh only if the measurements require it.

## 10. Label and entrance recognition (discussed 2026-10-01)

1. **Per-polygon label from MAP+MMAP.** Δ = terrainZ − polyZ, measured at the
   polygon vertices (min/max), not only the centroid:
   - SURFACE: |Δ| ≤ ~2 yd;
   - COVERED: Δ > ~3–4 yd;
   - ELEVATED: Δ < −3 yd;
   - WATER from mmap area flags.
   - A neighbour majority filter removes noise.
   - A MAP terrain hole gives no height: take the label from neighbours; the
     hole itself is "opening" evidence, since cave mouths cut terrain holes.
2. **Regions:** flood-fill connected polygons with the same label; merge tiny
   regions.
3. **Entrances:** cluster navmesh edges between SURFACE and COVERED
   polygons. Store centre, inward direction and width.
   - Extra evidence: a nearby terrain hole, a narrow neck, inward slope.
   - ELEVATED↔SURFACE boundaries are bridge ends, stairs and building doors.
   - A COVERED region with no surface link is unreachable on foot.
4. **Pitfalls:**
   - Overhangs are COVERED but not caves. Use region size/enclosure and
     `IsIndoors` false, and label them UNDERCUT.
   - WMO interiors at terrain level have Δ≈0 but are indoors. They need a
     VMAP ceiling raycast or `IsIndoors`.
   - A bridge over water is ELEVATED above WATER.
   - Thresholds are tuned per map.
5. **Live confirmation and learning:**
   - signals: `IsIndoors` flips, subzone/uiMapID change, indoor minimap,
     darkness/opening in the image, camera pulled in by a ceiling;
   - the point where `IsIndoors` actually flips is stored as a **verified
     entrance** and overrides the computed one;
   - the layer comes from the tracked polygon, not the client Z (false Z=0).
6. **Validation with the spider cave:** compute labels and entrance for map
   2175 and visualise them. The user walks down and up while logging. Then
   measure the `IsIndoors` flip vs the computed entrance (yd error) and the
   false-region count.

## 11. Route view in Live Vision (user requirement: "I must at least see the route it follows")

Minimal version, independent of §2–§10:
- **Top-down inset (bottom-right, ~220×220 px):**
  - heading-up (rotates with the game view);
  - player arrow, MOVE route polyline with waypoint dots, the next
    waypoint highlighted, the destination;
  - text: purpose (quest area / turn-in / quest-giver search) and remaining
    distance;
  - auto-zoom to the next 60–100 yd.
- **On-image bearing arrow (bottom centre)** toward the next waypoint
  relative to the player's facing, e.g. "WP 12 yd, 35° right". Exact: it
  needs only player position and facing, no camera model.
- A ground-projected route line on the image comes later (approximate
  camera).
- Data path: the agent sends a small latest-only nav-overlay packet
  (~2 Hz) to the Live Vision monitor; the monitor draws the freshest one
  (≤1 s) on each frame. Perception rates are not affected.

### 11b. "GPS line on the ground" (user request, discussed 2026-10-01)

Draw the upcoming MOVE route onto the game image like a car-navigation AR
line.
- **Route:** navmesh anchors in 3D (with Z), so the line follows hills and
  slopes.
- **Camera model, estimated without an addon change:**
  - yaw ≈ player facing (the follow camera stays behind while walking);
  - distance from the own avatar box height (screen-anchored box,
    h_px ≈ f·H_avatar/d);
  - pitch from the avatar's feet position on screen (bottom of the avatar
    box);
  - FOV: WoW default (later the `cameraFov` CVar / `GetCameraZoom` via
    the addon).
- **Self-correction:** the avatar's feet must sit at the start of the line.
  The drift while walking refines pitch/yaw online.
- **Accuracy:** good for the next ~20–40 yd, fades with distance. When the
  user mouse-looks (camera not following: the avatar is off its usual screen
  spot / seen sideways), hide the line and show "kamera nem követ".
- Keep the exact top-down inset alongside: if the two disagree, the camera
  estimate is wrong, not the route.
- **Order:**
  1. inset + bearing arrow (exact);
  2. ground line with the camera estimate and self-correction.


## 12. Progress (2026-10-03)

1. **Measured** (`tools/bench_navmesh.py`, Exile's Reach 2175, real mmaps): 329 tiles, 429 769 walkable
   polygons; 2.65 % of walkable x,y bins have stacked layers > 4 yd apart.  Python router inside one
   connected area: cold 0.8-1.5 s, warm 0.2-0.5 s per route (50-1000 yd), 100 % found.
2. **Native Detour**: `native/detour_shim` (flat C API) over recastnavigation v1.6.0 built with
   `DT_POLYREF64` (TrinityCore tiles have 16-byte link records), static MSVC runtime →
   `native/bin/aipc_detour.dll`; `navigation/detour_native.py` (ctypes, ABI check).  All 329 tiles load
   in 1.0 s; routes 0.17-1.7 ms (≈1000× faster), paths 0-3.5 % shorter.  `TrinityMMapNavMesh.find_path`
   uses it first; without the DLL (or `AIPC_NATIVE_DETOUR=0`) the Python router remains.
3. **2D leak fixes**: endpoints are found in a 3D box (an endpoint without Z takes the start's height and
   is flagged `endpoint_layer: assumed_start_height`); arrival adds the vertical excess over 2 yd between
   the navmesh-projected player and the route anchor's polygon height (`layer_z`); surface projection
   keeps the previous layer when there is no route hint (continuity, 15 yd) and uses native 3D nearest.

4. **Labels / regions / entrances** (`navigation/surface_labels.py`, `tools/build_surface_labels.py`):
   2175 in 27 s — 73 % SURFACE, 11 % COVERED, 16 % ELEVATED; regions; COVERED regions are CAVE only when
   ≥ 300 yd² and ≥ 8 yd under the terrain (median) with a surface link, else UNDERCUT / ISOLATED;
   97 caves and 144 entrances map-wide (6 caves around the Exile's Reach island).  Output:
   `output/navigation/surface_labels_2175.json` + top-down PNG (`--around X Y HALF` zoom).
   `navigation/entrance_verification.py` appends IsIndoors flips (ENTER/EXIT with the positions around
   the flip) to `<profile>/verified_entrances.jsonl`; `tools/compare_entrances.py` reports the distance to
   the nearest computed entrance.  Fixed: the navigation context read `is_indoors`, the addon exports
   `movement.indoors`.  **Pending:** the user's spider-cave walk (which cave is it?), then using labels in
   destination-layer selection (cave POI → target the CAVE region) and the §11 top-down inset.
5. **Destination layer + own layer (2026-10-05, Hrun's pit, offline-tested; descent live-confirmed):**
   `NavigationService.lower_layer_point` (deepest reachable walkable point ≥ 15 yd under the POI surface,
   35 yd radius, unreachable pockets skipped), used by the quest planner on a text cue, a minimap
   "objective below" cue or 25 s rim search without progress.  Own-layer tracking (§4.3) seeds a new
   route's start height (estimated, so the start-layer probe still runs).  Minimap rule (user): inside the
   blue area = in the zone; yellow objective dot = same space; grey dot with a down/up arrow = the
   objective is lower/higher.  Kill objectives show no dots.
6. **§11 route view, step 1 (2026-10-05, offline):** `NavigationService.overlay_snapshot` → runtime ~4 Hz → LIVE VISION's own latest-only queue → `diagnostics/navigation_overlay.py`: heading-up top-down inset (route, next waypoint, zone-sweep hops, destination; colour = height vs the tracked own layer) and a bearing line ("WP 14 yd, 34° jobbra, ↓4 yd"). Step 2 (ground line, §11b) still open.  Zone sweep: `zone_sweep_next` walks the multi-floor zone in 15 yd hops, down then up.
Rebuild the DLL: `cmake -S native/detour_shim -B native/detour_shim/build -G "Visual Studio 17 2022" -A x64`
then `cmake --build native/detour_shim/build --config Release`.

## 13. Z resolver (2026-10-06, user design "WOW Z-COORDINATE RESOLVER TERV")

Retail exports no player height, so one component owns every height:
`navigation/z_resolver.py` (`ZResolver`, `ResolvedPosition`: x, y, z, confidence,
source, reachable, path_length, alternatives, evidence).

- **Own layer** (`observe_player`, every observation): candidates = the navmesh layers
  under the player's X/Y (`walkable_heights_at`, native Detour `queryPolygons` +
  `getPolyHeight` in `aipc_detour.dll` since 2026-10-06, Python tile parser as the
  fallback).  Continuity: the height may change by at most 1.2 x horizontal travel +
  2.5 yd (slope + step/jump); a new FALL_ENDED event moves the player to the highest
  layer ≥ 1.5 yd below; no layer within reach = `continuity_broken` (confidence 0.4);
  first fix with several layers = route anchor / terrain hint, confidence 0.5,
  alternatives kept.  The route projection uses the resolved layer as its hint; new
  routes start on it (estimated, so the Torgok/Wrathion start-layer probe still runs).
- **Target height** (`resolve_target`, destinations without Z, e.g. a minimap dot or a
  quest POI): candidates = layers at X/Y + walkable polygon centres within 8 yd
  (`walkable_points_near`); score +80 navmesh, +50 VMAP floor (a collision surface
  at the polygon), −80 VMAP surface < 2 yd above (no headroom), +30 within 10 yd of
  the player's layer, −50 more than 60 yd away, floor cue (SAME yellow dot ±8 yd:
  +20/−20; BELOW/ABOVE arrow or lower-layer text: +20/−50), and for up to 8
  candidates a Detour path from the own layer: +100 reachable / −100 not, −40 long
  detour (> 3x straight + 40 yd).  Confidence = score / 280.  Below 0.6 the MOVE walks
  only the first 30 yd of the route and resolves again (§12 of the user design).
  After a fall a resolver-chosen target is resolved again from the new layer.
- **VMAP** (`world_geometry/vmaps.py`, `TrinityVMaps`): reads TrinityCore `VMAP_4.E`
  tiles (`vmaps/<map>/<map>_<tx>_<ty>.vmtile`, model spawns) and models (`<name>.vmo`,
  group vertices/triangles) and intersects one vertical ray with every triangle
  (numpy, both faces, internal frame `(mid−x, mid−y, z)`, `R = Rz(rot.y)·Ry(rot.x)·Rx(rot.z)`).
  Validated on Hrun's pit: VMAP surfaces match the navmesh layers within 0.1–0.6 yd;
  ~1 ms per query after the first model load.
- Zone sweep: after a fall the downward sweep treats hops above the landing as passed.

Measured (Hrun's pit, the 2026-10-06 fall): fall detected 86.9 → 74.9; the yellow
cocoon dot (76.8, −2264.0) resolved to a reachable ledge at 66.6 (4.8 yd from the dot,
path 52.8 yd, VMAP floor, confidence 0.86) instead of the rim (94.8) the old
"shortest reachable layer" chose.  Open: a first fix inside a cave without history
picks by terrain (the rim) with confidence 0.5.

The user-operated 11:56 cave run credited the first cocoon (1/5), then exposed
another edge case: a real lower polygon was 4.5 yd from the sampled X/Y while
the exact column contained only an upper rim polygon. Nearby continuity now
searches 5 yd; if no reachable floor is found it keeps the last tracked height
as an uncertain hypothesis (0.4) and a required 3D route fails closed. An old
upper alternative can converge only from an ambiguous *first fix*, never from
a broken tracked floor or a pending fall. The controller also confirms a wall
after 4 s of fresh, nearly stationary world positions despite tiny per-frame
distance improvements, provided forward input and running telemetry persist.
Real-telemetry/navmesh replay is offline evidence; the second cocoon and wall
stop still need user-operated live validation.

## 14. Generic multi-floor quest routing (2026-10-06, offline only)

The cocoon run exposed a general failure mode: identical map X/Y can refer to
different walkable floors, while a minimap objective marker has no stable ID.
The correction stays inside the common quest planner and NavigationService:

- A yellow dot is a same-space location hypothesis, never object identity.
  `QuestDotFocus` commits to one quest-associated world point through brief
  occlusion, then performs a bounded local visual/hover search. A new dot is
  selected only after credit/context changes or that search budget expires;
  the old point is not retried in an endless back-and-forth loop.
- A located ABOVE/BELOW marker requires two **different fresh capture samples**
  and an unambiguous quest association. Its direction constrains the navmesh
  target layer; it does not authorize a straight-line move, a guessed Z, or an
  immediate blind downward sweep. A same-space dot for the active quest wins
  over an unrelated floor arrow.
- The arrow is relative to the **player's** current floor. At a stacked start
  column it still cannot identify that floor by itself: an upper player at
  z≈95 and a lower player at z≈40 could both see a BELOW objective (at z≈61
  and z≈−2 respectively). The 2026-10-06 outdoor-start probe therefore also
  requires a current boolean `movement.indoors == false` from the addon, the
  terrain-matching upper navmesh layer, a reachable VMAP-backed target, and a
  ≤2 s arrow sample. This only raises the upper-layer hypothesis to 0.7 for a
  25 yd / 45 s bounded route; the lower alternative remains. A unique layer
  reached continuously confirms it; contradiction or budget expiry stops the
  route. Missing/unknown indoor telemetry continues to fail closed. This is
  offline-tested, not a live-validated player Z measurement.
- The one Z resolver retains alternative player floors on an ambiguous first
  fix; repeated samples at the same stacked X/Y do not magically raise its
  confidence. Target candidates preserve same-height but disconnected pockets
  and require a complete Detour route. Zone-sweep hops and 3D search cells are
  visited only after a fresh, nearby player-layer fix matches their Z.
- A completed quest's known-Z turn-in point is not "arrived" from X/Y alone.
  A reached route retains its resolved floor for the subsequent bounded NPC
  search, preventing a visit to that same X/Y on another floor from counting.
  Search-cell MOVE retries keep the cell Z; a same-X/Y different-Z position
  does not mark it reached. The local turn-in search stops after 120 seconds
  and waits for new quest, map, target-identity or floor evidence instead of
  indefinitely replaying the same cells.

Still open: when the client gives no height or floor cue for a turn-in or
objective, the correct floor cannot be inferred from X/Y alone. Starting in a
stacked area without movement history remains ambiguous and fails closed for
required routes except for the bounded outdoor probe above; entrance/exit
verification and a live, credit-confirmed
multi-floor quest are needed before this can be called autonomous cave
questing. The surface-label cave graph is diagnostic, not yet an authoritative
route-layer selector. User manual movement in the source run is not agent
success evidence.
