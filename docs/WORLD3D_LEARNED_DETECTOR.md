# World3D learned detector and dataset gate

Status: **runtime-integrated/offline-tested; selected-PID live validation is
still open**. The trained v1 model is admitted as optional visual evidence,
not promoted to semantic or input authority. This distinction is intentional
and required by V5 M4.16.

## Runtime candidate model (2026-09-26)

The GUI runtime now loads
`models/world3d_annotation_assist_combined_2794_v4.engine` through the existing
model-neutral `LearnedWorldDetector` boundary, with the 512 engine used for
global scans and the portable v4 PyTorch checkpoint retained as fallback. The
model was fine-tuned from the prior v3 checkpoint on 2,794 reviewed frames /
4,136 boxes and early-stopped at epoch 120 with epoch 20 as the best checkpoint.
On the same held-out 108-image Exile's Reach test split used for regression,
v4 measured precision 0.396, recall 0.452, mAP50 0.404 and mAP50-95 0.140.
Creature and quest-object AP improved while corpse AP regressed materially;
unseen Dragonflight review also exposed substantial domain shift. These are
offline measurements, not claims of selected-PID live accuracy.

Runtime intentionally differs from the annotation-assist preview:

- the runtime subject-class gate is 0.15, while the raw backend remains lower
  so rejected weak outputs stay observable in diagnostics;
- production per-class gates are 0.08--0.35, with strict per-class budgets;
- weak-data classes use stricter per-class thresholds;
- per-class and total detection budgets prevent box floods;
- the model loads and performs CUDA/CPU warm-up in a background thread;
- until warm-up completes, existing cheap CV continues without learned output;
- warmed RTX 2050 measurement was about 107--122 ms per learned refresh at
  640 px input; the fast tracker remains on its independent high-rate lane.

Every result remains an `UNKNOWN` visual candidate. Live accuracy, temporal
behavior, active-perception ranking and end-to-end effect are not yet claimed.
The model path can be overridden with `AIPC_WORLD3D_MODEL`; confidence, device,
input size and candidate budgets have corresponding `AIPC_WORLD3D_MODEL_*`
environment settings in `learned_detector.py`.

The live launcher uses `AIPC_WORLD3D_PROPOSAL_MODE=YOLO_ONLY`: legacy colour,
component and generic sliding-window OpenCV detectors cannot create runtime
boxes. OpenCV remains an implementation detail for camera compensation,
appearance measurements and frame-to-frame propagation of YOLO anchors. This
keeps the learned view sparse without sacrificing the fast tracker.

`START_AGENT.bat` enables the input-free `LiveVisionMonitor`. It consumes the
same completed frame and canonical tracks already used by perception; it owns
neither a second capture nor a second inference loop. Its Windows HighGUI
message pump runs in a separate spawned process so it cannot deadlock the
Tkinter GUI or pause telemetry. A size-one latest-frame mailbox drops display
updates under load instead of applying back-pressure to the agent. Press `Q`
or `Esc` in the monitor window to close only the visualization. Set
`AIPC_LIVE_VISION=0` before launching by another entry point to keep the
monitor disabled.

## Existing Wowpedia dataset audit (2026-09-21)

Audited source:

`C:\Users\<user>\Documents\ChatGPT\ai_visual_bot_midnight claude\ai_visual_bot_midnight 1.2\datasets\wowpedia_mobs_npc`

Observed facts:

- 6,159 image files / 6,155 unique stems;
- 6,155 label files and 6,155 boxes;
- every box is class `2` and covers the complete image (`1.0 x 1.0`);
- `train` and `val` both point at the same `images` directory (6,159-file
  leakage);
- no held-out test split;
- four duplicate image stems;
- the source includes close-up subjects as well as multi-character scenes,
  objects and quest scenes, all labeled as one full-frame `npc_body`.

Therefore this dataset is **not detector-training-ready**. A model trained on
it learns that the complete WoW image is an NPC and its validation metrics are
not independent. The existing `yolo11n_wow.pt` from that source is not approved
for live promotion.

Reproduce the audit:

```powershell
python tools/audit_world3d_yolo_dataset.py "C:\Users\<user>\Documents\ChatGPT\ai_visual_bot_midnight claude\ai_visual_bot_midnight 1.2\datasets\wowpedia_mobs_npc"
```

The command returns a non-zero status until full-frame collapse, split leakage,
missing test split and duplicate stems are corrected.

## Useful data already available

The selected V5 project currently contains 14,710 real client screenshots and
945 addon-confirmed visual crops. The confirmed crop metadata includes GUID,
name, NPC ID, attackable/dead state, source track, bounding box and mouseover
association distance. This is useful for a candidate classifier/re-ranker, but
the crops alone are not full-frame object-detection labels.

For YOLO detection, retain or reconstruct the complete source frame and record
a tight reviewed bounding box. A candidate detector's own box is a weak label,
not unquestionable ground truth.

## Initial generic taxonomy

Training labels may contain convenient visual categories, but runtime output
remains evidence:

- `humanoid_unit_like`
- `creature_unit_like`
- `corpse_like`
- `quest_object_outline_like`
- `world_object_like`
- `overhead_symbol_like`
- `entrance_or_door_like`

Foliage, rocks, torches, empty terrain and ordinary UI are reviewed empty
frames (hard negatives), not an object class. The outline class may legally
have zero positive examples in an early dataset revision; it must not be
fabricated from non-outline footage.

NPC versus hostile/neutral mob is not derived from body appearance alone.
Mouseover/target/addon confirmation establishes game semantics downstream.

## Required capture and split protocol

1. Capture complete real-game frames at supported resolutions/UI scales.
2. Include outdoor, indoor, night, weather, near/far camera and partial
   occlusion cases.
3. Draw tight boxes around every in-scope subject; include empty/hard-negative
   frames containing foliage, rocks, torches, UI and player character.
   The controlled player/avatar and its mount are background, not unit labels.
   An empty review is valid only after visually checking the full-resolution
   frame; a missing bootstrap proposal is never proof that the frame is empty.
   Ignore an instance only when both of its visible dimensions are below 12
   pixels or it is not visually separable from the background. Apply this rule
   consistently rather than silently treating missed, learnable units as
   negatives.
4. Group frames by capture session and entity identity before splitting. Never
   put adjacent frames or the same identity sequence into both train and val.
5. Keep disjoint `train`, `val` and `test` sets. Test remains untouched until
   final evaluation.
6. Mine false positives and false negatives from deterministic replay, review
   them, then add them to a later dataset revision.
7. Version the dataset manifest, model artifact, training arguments and held-out
   metrics together.

Gameplay video can be converted into an **unlabelled review pool** without
pretending that sampled frames are ground truth:

```powershell
python tools/prepare_world3d_video_dataset.py `
  --video "C:\path\part1.mp4" `
  --video "C:\path\part2.mp4" `
  --out "datasets\world3d_video_v1" `
  --interval-seconds 3
```

The tool records source video, absolute source frame, timestamp, dimensions and
content hash, and removes low-change samples. It intentionally creates no YOLO
label files and no train/val/test split. Annotation comes first; leakage-safe
grouped splitting comes after review.

## Semi-automatic review

The existing World3D V3 pipeline can pre-populate review proposals without
promoting them to ground truth:

```powershell
python tools/propose_world3d_annotations.py datasets/world3d_gameplay_video_v1
python tools/review_world3d_annotations.py datasets/world3d_gameplay_video_v1
```

Or launch both with `START_WORLD3D_ANNOTATOR.bat`. Yellow boxes are machine
proposals; green boxes are explicitly accepted. Controls:

- mouse click selects; dragging empty space draws a new accepted box;
- `0`-`6` assigns the active visual class and accepts the selected box;
- `Space` toggles proposal acceptance; `A` accepts every displayed proposal;
- `D` removes the selected proposal;
- `S` writes only accepted boxes; `R` explicitly saves a reviewed empty frame;
- `N`/`P` navigate and `Q` exits.

The proposal generator writes JSON only. YOLO `.txt` labels appear only after
`S` or `R`, preserving the distinction between candidate evidence and reviewed
ground truth.

## Runtime integration contract

`LearnedWorldDetector` accepts a model-neutral backend. The optional
`UltralyticsYoloBackend` is lazy-loaded, while tests can inject a deterministic
backend. V2 runs it additively beside existing cheap detectors; a model failure
falls back without stopping perception.

All learned results become `unknown_subject_candidate`,
`unknown_object_candidate`, `unknown_symbol_candidate`, or
`unknown_scene_candidate`. The original learned label and confidence are kept
under appearance evidence with `semantic_status=UNCONFIRMED`. The adapter owns
no target, planner, movement, input, interaction or combat authority.

Training is gated by `tools/train_world3d_yolo.py`. Passing the structural
audit permits offline training only. Promotion additionally requires held-out
replay, false-positive/false-negative review, latency measurement, temporal
tracking checks and user-operated selected-PID live validation.
