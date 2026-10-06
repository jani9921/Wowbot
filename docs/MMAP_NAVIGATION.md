# TrinityCore mmap navigation

## Contract

`navigation/mmap_navmesh.py` is a read-only global-route source for the one
canonical `NavigationService`. It has no input backend, movement loop,
WorldModel write access, active-skill lifecycle, or semantic recognition
authority.

An mmap route is eligible only when:

- the player position is addon-confirmed `WORLD_YARDS`;
- the destination is explicitly `WORLD_YARDS`;
- both endpoints have the same `instance_id`;
- the source contains `<instance_id>.mmap` and the necessary `.mmtile` files;
- both endpoints associate with a connected walkable polygon corridor.

Otherwise `GlobalPlanner` retains its previous measured/direct route behavior.
Map pixels and normalized map coordinates are never converted or guessed.

## Runtime configuration

The GUI field **TrinityCore mmap mappa vagy mmaps.zip** accepts either:

- the original `mmaps.zip`; or
- an extracted directory containing `.mmap` and `.mmtile` files.

Headless use may set `WOWBOT_MMAP_PATH`. The source is lazy: only tiles along
the requested route plus a one-tile margin are decompressed and parsed. Large
archives must not be copied into Git. Runtime diagnostics are visible at
`navigation.navmesh`.

For the supplied Retail 12.1 data, Exile's Reach uses `instance_id=2175`.

## Coordinate convention

TrinityCore/Detour stores WoW world coordinates in `Y,Z,X` order. The adapter
performs the explicit reversible conversion:

```text
WoW (X,Y,Z) → Detour (Y,Z,X)
Detour (X,Y,Z) → WoW (Z,X,Y)
```

File-grid selection uses TrinityCore's 533.333-yard grid. Cross-tile portals
are joined by overlapping collinear boundary intervals; exact endpoint
identity is not assumed because adjacent tiles can contain T-junctions.

The default walking filter accepts `NAV_GROUND=1` and
`NAV_GROUND_STEEP=2`. It excludes `NAV_WATER=4` unless a future explicit
swimming capability opts in, and never silently accepts
`NAV_MAGMA_SLIME=8` as ordinary walking terrain.

## Layering

```text
verified WORLD_YARDS goal
  → Trinity mmap polygon A*
  → GlobalRoute anchors
  → PathCorridor
  → LocalPlanner (live traversability/danger/obstacles)
  → ReachMovementController
  → one CommandDispatcher
```

The navmesh models static geometry. World3D traversability remains responsible
for moving entities, temporary/phased obstacles and local free-space changes.
No route is proof of arrival; telemetry and the normal arrival verifier remain
authoritative.

## Evidence (2026-09-21)

- Supplied archive: `C:\Users\benei\Downloads\mmaps.zip`, 6,182,217,370 bytes,
  28,619 entries.
- Map 2175: one `.mmap` header and 329 `.mmtile` files.
- Wrapper format observed: Trinity mmap v7, Detour ABI v16, Detour mesh v7.
- Real tile `2175_32_36.mmtile` parsed successfully.
- Same-tile real-data route: 9 loaded tiles, 35,300 polygons, 7 route
  polygons in the all-flags format probe; the final land-only funnel emits
  only the geometrically necessary corners (2 anchors on the verified short
  route).
- Cross-tile, land-only real-data route from `(-451.4,-2614.2)` to
  `(-550,-2614)` succeeded across 12 tiles and 14 route polygons, reduced by
  corridor funneling to 6 movement anchors. The farther
  `(-600,-2614)` probe correctly had no land-only polygon path; the earlier
  all-flags prototype reached it only by accepting water and was rejected.
- `tests/test_mmap_navmesh.py` covers binary parsing, polygon routing,
  coordinate-space/instance gates and absence of input authority.

This is offline evidence. Selected-PID movement over the route and obstacle
replanning remain `LIVE_OPEN` and must be recorded in `LIVE_VALIDATION.md`.

## MAPS / VMAPS composition (2026-09-23)

The canonical navigation boundary now constructs a read-only
`WorldGeometryService` when an mmap path is configured. It discovers the
TrinityCore Retail data at `WOWBOT_WORLD_DATA_PATH`, or at the local default
`C:\Program Files (x86)\World of Warcraft\_retail_`.

- **MAPS** supplies terrain height, holes, liquid type and liquid surface
  evidence through the official `MAPS` v10 / `MHGT` / `MLIQ` layout. Terrain
  height is a layer-selection hint for X/Y-only endpoints; it does not create
  routes or own movement.
- **MMAPS** remains the only global path authority and supplies the walkable
  corridor and its surface Z.
- **VMAPS** is discovered and reported, but LOS/collision queries remain
  fail-closed as `NOT_IMPLEMENTED` until the official collision tree reader is
  integrated. File presence is never reported as a successful LOS result.

At the user-reported map-2175 start position `(80.88, -2271.34)`, real
`2175_31_36.map` data returns terrain Z `98.18`, agreeing with the upper mmap
surface and disproving the client-exported false Z=0 layer.


## See also

- `docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md`: design backlog for the
  hierarchical, layer-aware navmesh, caves and tunnels, and the Live Vision
  route view. Discussed 2026-10-01, not started.
