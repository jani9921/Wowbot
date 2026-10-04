# Runtime FAST-lane performance

Status: offline fixed; next selected-PID confirmation remains live-open.

## Live evidence (2026-09-21, PID 12400)

The apparent addon drop was a consumer backlog, not an exporter slowdown:

- pixelstrip source FAST rate: about **34 Hz**;
- sensor published-update rate: about **34.6 Hz**;
- main runtime/control rate: about **4--5 Hz**;
- control tick: commonly **82--207 ms**, p95 about **521 ms**;
- diagnostic status JSON: about **0.89 MB** after the earlier baseline fix;
- memory DB: about **200 MB**, growing at the sampled rate of about
  **1262 MB/hour**;
- `WORLD3D_LOCAL_VIEW`: 765 rows, average about **179 KB**, total about
  **130.7 MB** of the observation payloads.

## Implemented changes

1. The canonical WorldModel still ingests every observation immediately, but
   its large read-only diagnostic JSON projection is rebuilt at most every
   250 ms. Control/result fields remain live on every tick. A newly published
   `WORLD3D` or `WORLD3D_LOCAL_VIEW` observation forces an immediate refresh,
   preserving event/debug visibility.
2. `WORLD3D_LOCAL_VIEW` is classified as derived CV data by retention policy.
   It can now be removed by the existing bounded observation consolidation;
   addon telemetry and normalized events are not reclassified as CV.
3. Direct tests cover snapshot throttling, live control-field updates,
   immediate World3D projection, derived local-view consolidation and addon
   telemetry preservation.

## Acceptance

- Offline suite: **1068 passed, 2 skipped in 37.89 seconds**.
- Live-open: run the same FULL_AI scenario and confirm that
  `fast_control_hz`/`addon_fast_state_hz` no longer collapse while
  `sensor_diagnostics.source.source_fast_hz` remains healthy.
- The old database file is not automatically vacuumed or destructively
  rewritten by this patch. Consolidation bounds live rows; physical file-space
  reclamation is a separate maintenance operation.
