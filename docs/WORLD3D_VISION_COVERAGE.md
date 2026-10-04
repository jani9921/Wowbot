# World3D Vision coverage ledger

Source: `wow_agent_world3d_vision_complete_design_spec.txt` (2026-09-17).
This ledger separates implementation, offline tests, and live proof.  A design
section is **not** live-validated merely because it has a class or test.

Status vocabulary: **IMPLEMENTED/OFFLINE** = present and covered by automated
tests; **PARTIAL** = useful existing adapter or interface but needs more
evidence/model work; **LIVE PENDING** = needs a user-operated Retail run.

| Sections | Status | Concrete authority / remaining boundary |
|---|---|---|
| 1–3 | IMPLEMENTED/OFFLINE | `world3d.pipeline.World3DPipeline` is a perception-only publishing authority; it imports no planner, skill, executor, or navigation controller. |
| 4–6 | IMPLEMENTED/OFFLINE | `World3DObservationBatch`, explicit spaces, canonical `build_scene_roi`; ROI remains profile-configurable. |
| 7–8 | IMPLEMENTED/OFFLINE | Type and role taxonomies remain separate. `SemanticEvidenceFusion` applies source reliability, freshness, debounce and hysteresis; raw CV is never fact while tooltip/addon ground truth may confirm identity or role. |
| 9–16 | PARTIAL | V2/V3 supply generic subject/symbol/object/nameplate evidence; overhead relation/probe, action-target hints and targeted OCR remain. UNKNOWN-first corpse/object/interact cue mappings are tested. Production recall, health/cast-state accuracy and the rejected training corpus still need better data/live calibration. |
| 17–22 | IMPLEMENTED/OFFLINE | Local geometry branch publishes lower-view traversability sectors, obstacle evidence, context-gated entrance hints, and static landmarks. It is belief only, never a collision/nav map. |
| 23–27 | IMPLEMENTED/OFFLINE | Global assignment, short-gap occlusion, bounded retired-track memory and conservative long-gap visual re-identification use appearance/scale/position with ambiguity rejection. Only visual continuity is retained; semantics remain UNKNOWN. |
| 28–31 | IMPLEMENTED/OFFLINE | V3 patch/global motion feeds explicit camera and ego-motion evidence; entity residual motion is kept separate. Yaw/pitch telemetry calibration is LIVE PENDING. |
| 32–35 | IMPLEMENTED/OFFLINE | Scale buckets/trends and camera-relative bearing; no fake world-meter result is emitted. |
| 36–39 | IMPLEMENTED/OFFLINE | Interaction-ready is evidence only; local scan can produce negative evidence. Facing/search coverage needs live calibration. |
| 40–46 | IMPLEMENTED/OFFLINE | Read-only identity-probe/local-scan request API, tooltip/OCR handoff, interaction evidence, and visual-servo measurements are exposed. Requests do not move the cursor or player. |
| 47–54 | IMPLEMENTED/OFFLINE | Scene-change evidence, brightness/contrast/blur/UI-occlusion/visibility diagnostics, explicit effective-confidence factors, source-specific fusion, accept/retain hysteresis, debounce and per-field FRESH/STALE/EXPIRED policies have direct tests. Live threshold calibration remains separate. |
| 55–61 | PARTIAL | Existing visual signatures and bounded hard-example collector retained. A model-neutral learned-detector adapter, strict YOLO dataset auditor, training gate, UNKNOWN-first mapping and additive detector fallback are IMPLEMENTED/OFFLINE. The supplied Wowpedia dataset failed audit (full-frame label collapse and split leakage), so no production model is asserted as trained or promoted. See `WORLD3D_LEARNED_DETECTOR.md`. |
| 62–70 | IMPLEMENTED/OFFLINE | V3 separates expensive detector refresh from high-rate patch propagation; PerceptionWorker has backpressure, context invalidation and UI/modal ROI handling. Vehicle/zoom/pitch live scenarios remain pending. |
| 71–73 | IMPLEMENTED/OFFLINE | One profile resolver drives the existing worker cadence, V3 detector cadence and crop-only OCR ranking/budget for COMBAT, QUEST_SEARCH and NAVIGATION without adding an input or perception authority. |
| 74–80 | IMPLEMENTED/OFFLINE | LocalWorldView projection, typed candidate/entrance/interactable queries and non-authoritative visual retention locks. |
| 81–86 | IMPLEMENTED/OFFLINE | Termination events, ACTIVE→DEAD/CORPSE continuity, no-credit role penalty, range/facing/LOS/target-lost feedback and cross-view source ordering are belief-only and directly tested. Selected-PID event accuracy remains live-pending. |
| 87–90 | IMPLEMENTED/OFFLINE | Validator handles typed lifecycle events; replay emits every named record; `World3DDebugRenderer` and `tools/world3d_replay.py` render a graphical, input-free overlay. |
| 91–92 | IMPLEMENTED/OFFLINE | Unit/integration tests cover ROI, tracking, occlusion, scale trend, bearing, obstacle sectors, entrance evidence, negative scan and WorldModel publication. |
| 93–94 | LIVE PENDING | Stationary/approach/occlusion/camera-turn/door/collision Retail scenarios and their measurements are still required. |
| 95–96 | IMPLEMENTED/OFFLINE | Existing V2/V3/V4 are adapters beneath the canonical pipeline; no competing second detector loop was introduced. |
| 97–98 | IMPLEMENTED/OFFLINE | Frame → ROI → V3 detector/tracker → manager → geometry → semantic evidence → batch → diagnostics flow, with context-aware scheduling. |
| 99–103 | PARTIAL | Core invariants are enforced and tested; full success requires the LIVE PENDING scenarios plus iterated detector calibration, not a code-only declaration. |

## 2026-09-21 M4.8Z obstacle acceptance record

- `tests/test_v5_m4_obstacle_acceptance.py` now executes every named OBS-A
  through OBS-J scenario against production traversability, progress, stuck,
  local-planning, danger-memory and ActivePerception components.
- Unknown collision becomes blocked from repeated geometry/motion evidence
  without acquiring a semantic object class. Dynamic blockers decay, narrow
  doorways retain their centre corridor, and a one-frame false positive never
  reaches confirmed blockage.
- Cliff/drop evidence now produces typed `DROP_OR_CLIFF` stuck context. Its
  recovery ladder cannot select `JUMP_FORWARD`; it records danger and requests
  a bounded alternative/local replan instead.
- Focused obstacle/navigation regression: **44 passed**. Complete offline
  regression: **1097 passed, 2 skipped in 44.99 seconds**. Retail calibration
  and live OBS replay remain pending.

## 2026-09-17 implementation record

- Added `World3DObservationBatch` and explicit `ScreenPoint`/`BearingEstimate`
  contracts.
- Added canonical `World3DPipeline` after the existing V2/V3/V4 stack rather
  than replacing it.
- Added batch validation, local geometry, traversability/obstacle/entrance and
  landmark evidence, read-only query/probe API, and WorldModel projection.
- Changed source-local visual loss to require both missed observations and
  elapsed-time grace.
- Offline regression: `55 passed` for World3D, perception, visual tracking,
  runtime and WorldModel focused suites. No client input was sent.

## 2026-09-21 learned-detector record

- Added the model-neutral `LearnedDetectorBackend` contract and optional
  `UltralyticsYoloBackend`.
- Learned output is mapped to UNKNOWN visual candidate/evidence and cannot
  establish NPC/MOB/hostility truth.
- V2 consumes learned proposals additively; cheap detectors remain active and
  model failure is not a perception single point of failure.
- Added a strict dataset audit/training gate and direct regressions.
- The supplied 6,159-image Wowpedia-derived dataset is **not training-ready**:
  all 6,155 boxes cover the full image, train equals val, test is absent, and
  duplicate stems exist. Existing weights from that dataset are not promoted.
- Focused learned-detector + V2/pipeline regression: `30 passed`.
- Complete offline regression after integration: `1073 passed, 2 skipped in
  38.66s`; the unsafe dataset training launch was refused before training.

## 2026-09-23 perception-fusion closure record

- Conservative long-gap visual re-identification now requires three comparable
  appearance dimensions, compatible scale and position, and an unambiguous
  best score. Feature-poor or tied observations receive a new UNKNOWN track.
- Scene quality emits brightness, contrast, blur, UI-occlusion, visibility and
  explicit confidence factors plus non-authoritative scene-change evidence.
- Cross-sensor semantics use source reliability, temporal debounce,
  accept/retain hysteresis and field freshness. Strong tooltip/addon evidence
  can override weak map priors; appearance stays `fact: false`.
- Track termination, death/corpse continuity and scoped quest, interaction and
  combat feedback are evidence only and never execute movement or input.
- One context profile controls the existing worker/V3/OCR schedule. A typed
  deterministic replay and graphical renderer were added without decision
  authority.
- Complete offline regression: **1535 passed, 3 skipped in 65.44 seconds**.

Subsequent World Map hierarchy/resolver and engine-projection work did not
change these World3D classifications; repository-wide regression is now
**1554 passed, 3 skipped in 54.45 seconds**.
  No WoW input was sent and no live gate was closed.
