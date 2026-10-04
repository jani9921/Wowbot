# World3D runtime optimization — 2026-09-25

## Implemented data path

```text
capture / fast tracking (target 60 Hz)
  -> cheap patch tracker + current overlay
  -> live viewer publication

canonical perception (12 Hz)
  -> evidence / belief / scene graph / memory

YOLO detector refresh (profile 5–8 Hz)
  -> separate process
  -> shared-memory BGR input
  -> TensorRT FP16
  -> 512 full scan / 640 foveal scan
  -> UNKNOWN-first observations
```

The planner, movement and semantic authority were not moved into the fast
loops. Detection remains evidence, not recognition.

## TensorRT engines

- `models/world3d_annotation_assist_combined_2794_v4.engine`: static 640x640 FP16
- `models/world3d_annotation_assist_combined_2794_v4_512.engine`: static 512x512 FP16
- portable fallback: `models/world3d_annotation_assist_combined_2794_v4.pt`

The runtime prefers the local 640 TensorRT engine when present. Every third
refresh is a global 512 scan; intermediate refreshes magnify the most valuable
tracked UNKNOWN cue at 640. An empty foveal scan forces immediate global
reacquisition. The full scan cadence prevents tunnel vision.

## Measurements on this host (RTX 2050)

| path | median |
|---|---:|
| PyTorch CUDA 640, process queue | 20.24 ms |
| TensorRT FP16 640, process queue | 14.42 ms |
| TensorRT FP16 640, shared memory | 9.08 ms |
| TensorRT FP16 512, shared memory | 10.25 ms |
| 4K viewer render to 1600x900, before | 29.08 ms |
| 4K viewer render to 1600x900, after | 7.35 ms |

Counts must still be evaluated against live scenes and the reviewed dataset;
latency improvement does not prove detector recall. The `.pt` fallback remains
available through `AIPC_WORLD3D_MODEL`.

## Relevant configuration

- `AIPC_WORLD3D_MODEL`: explicit model/engine override.
- `AIPC_WORLD3D_ADAPTIVE_SAMPLING=0`: disable foveated sampling.
- `AIPC_WORLD3D_FULL_SCAN_INTERVAL=3`: global reacquisition cadence.
- `AIPC_WORLD3D_FULL_SCAN_IMGSZ=640`: full scan engine size. The taller
  UI-masked scene introduced after the 2026-09-29 Jaina miss needs 640 to
  preserve small distant body/overhead-cue recall; 512 remains available as
  an explicit performance override.
- `AIPC_WORLD3D_FOVEAL_IMGSZ=640`: foveal engine size.
- `AIPC_YOLO_SHARED_MAX_WIDTH` / `AIPC_YOLO_SHARED_MAX_HEIGHT`: maximum detector ROI transport.
- `AIPC_LIVE_VISION_PREVIEW_WIDTH=1600` / `AIPC_LIVE_VISION_PREVIEW_HEIGHT=900`: viewer render ceiling.

## Validation boundary

This work is offline-tested and benchmarked. It is not yet live-validated as
proof of a completed quest or sustained client FPS. The user performs the live
run; logs and viewer rate counters are inspected afterward.

## Control-loop spike correction

The first live run after the vision optimizations still showed 600--800 ms
outliers even though capture, tracking and TensorRT inference medians were
healthy. The recorded database had accumulated enough rows that the synchronous
maintenance pass deleted 8,896 rows in one transaction. At the same time the
diagnostic status projection could rebuild the large WorldModel snapshot on
every World3D update.

Runtime maintenance is now incremental: at most 256 rows are removed per pass,
backlog never shortens the fixed 60-second cadence, and retention is completely
deferred while FULL_AI owns input. The former backlog calculation incorrectly
counted every authoritative observation as removable CV data; it now counts
only eligible derived rows. Maintenance latency is recorded explicitly. The
diagnostic WorldModel projection is cached
for one second; lightweight control fields remain current and the first
control-relevant World3D interrupt still bypasses the cache. Runtime latency
summaries now include p99 and maximum values so a later live run can distinguish
rare stalls from normal throughput.

High-frequency camera/position/World3D fields also remain queryable evidence but
no longer emit durable belief/contradiction lifecycle events for every changing
sample. The measured live session had produced 16,427 such redundant events and
17,153 event-to-observation relations in minutes.

Offline regression: **1773 passed, 4 skipped**. The Python agent must be
restarted before live validation; no addon update is required.

## Live-view resource isolation

A later live run isolated the remaining stalls to the optional LIVE VISION
window. Without changing detector semantics, opening that viewer caused
perception max latency of 613.98 ms and patch-tracker p95 of 263.79 ms. The
same gray/phase-correlation operations measured below 2 ms in isolation. The
spawned viewer process was inheriting OpenCV defaults of 12 CPU threads plus
OpenCL, competing with tracker and TensorRT scheduling.

The diagnostic viewer now uses one OpenCV worker, disables OpenCL and runs at
below-normal process priority on Windows. It remains a latest-frame consumer;
no viewer queue can back-pressure perception. Complete regression after this
change: **1774 passed, 4 skipped**. Live validation requires restarting the
Python agent so the viewer child process is recreated with these limits.

## Continuous latest-frame detector

The learned detector is no longer artificially limited to the profile's
8/10/12/15 Hz cadence. It now keeps exactly one inference in flight and, as
soon as that result is consumed, submits the newest available frame. Frames
that arrive while inference is busy are superseded rather than queued. This
keeps latency bounded and lets the TensorRT worker run at the rate supported by
the current scene and hardware. The canonical WorldModel publication lane
remains separately rate-limited; detector throughput therefore does not cause
high-frequency durable evidence churn.

`AIPC_WORLD3D_CONTINUOUS_DETECTOR=0` restores the former profile-limited
cadence for diagnosis or rollback. Runtime diagnostics now distinguish
`LATEST_FRAME_MAX_THROUGHPUT` from `PROFILE_LIMITED` and expose submissions,
completions, and busy-frame supersession counts.

An 8.78-second production-path replay using saved live WoW frames, a 40 Hz
source, the normal adaptive 512/640 TensorRT path, asynchronous process worker,
candidate fusion, and the existing evidence tracker measured:

| metric | result |
|---|---:|
| source calls | 36.55 Hz |
| completed detector refreshes | 36.32 Hz |
| asynchronous caller latency p50 / p95 | 2.94 / 4.97 ms |
| complete detector refresh latency p50 / p95 | 13.89 / 17.73 ms |
| submissions / completions | 319 / 319 |
| busy frames superseded | 1 |

This validates continuous detector throughput offline; it does not yet prove
live client FPS, detector recall, or quest completion. The existing evidence
tracker is deliberately retained: it also associates non-YOLO evidence and
survives the detector's alternating global/foveal coordinate spaces. Replacing
it with a YOLO-only tracker is a separate architectural change, not required
for fluid detector refresh. Focused regression: **90 passed**. Restart the
Python agent before user-operated live validation; no addon update is required
for this detector scheduling change.
