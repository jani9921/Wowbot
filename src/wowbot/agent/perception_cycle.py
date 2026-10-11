"""PerceptionWorker.update(): one perception cycle over the newest frame.

Split out of perception.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import time
import numpy as np
from wowbot.vision.world3d.tracking import WorldCandidateTracker
from wowbot.vision.world3d.profiles import resolve_world3d_profile
from wowbot.vision.world_map_calibration import estimate_world_map_canvas, legacy_world_map_rect


class PerceptionCycleMixin:
    """Methods of PerceptionWorker (perception.py); moved verbatim."""

    def update(self, frame, now, *, allow=True, geometry=None, context=None, world_map_open=False):
        world_map_open = self._debounced_ui_flag("world_map_open", bool(world_map_open), now)
        geometry = {**(geometry or {}), "world_map_open": world_map_open}
        for flag in ("quest_ui_open", "gossip_open"):
            if flag in geometry:
                geometry[flag] = self._debounced_ui_flag(flag, bool(geometry[flag]), now)
        geometry["world3d_profile"] = resolve_world3d_profile(geometry).to_dict()
        dimensions = frame[1:] if frame else None
        key = self._stable_context_key(context, dimensions, allow, geometry)
        # A missing capture is not evidence that the visual context changed.
        # Preserve the last completed projection through sparse paged-addon
        # intervals; its TTL still prevents stale observations from surviving.
        self._last_payload_kind = geometry.get("payload_kind")
        if frame is not None and key != self.context:
            self._record_context_reset(self.context, key, now)
            self.context, self.epoch = key, self.epoch+1
            self.tracker = WorldCandidateTracker()
            self.world3d.reset()
            with self._canonical_lock:
                self.world3d_pipeline.invalidate("capture_context_or_roi_changed")
            self.world3d_batch = None
            self.next_canonical_at = 0.
            self._next_signature_at = 0.
            self._canonical_dropped_frames = 0
            self._propagate_duration_window_ms.clear()
            self.visual_tracks.reset()
            self.hits.clear()
            for lane in self.lanes.values():
                lane["items"], lane["next"] = [], 0.
        world_processor = self.pipeline.process_world_map if world_map_open else self.pipeline.process_world3d
        for name, detector in (("world", world_processor), ("minimap", self.pipeline.process_minimap)):
            lane = self.lanes[name]
            interval = self._dynamic_interval(name, geometry)
            future = lane["future"]
            enabled = allow and (name == "world" or not world_map_open)

            def submit_if_due(name=name, lane=lane, detector=detector,
                              interval=interval, enabled=enabled):
                gate_due = False
                if frame and enabled and lane["future"] is None:
                    if name == "minimap":
                        gate_due = self.scheduler.should_run_minimap(
                            now, interval=interval, enabled=not world_map_open)
                    elif world_map_open:
                        gate_due = self.scheduler.should_run_map(now, interval=interval)
                    elif self.world_frame_driven:
                        # The capture is the clock: process every new frame
                        # as soon as the previous job finished.  A 22-33 ms
                        # time gate plus coarse waits/GIL delays published
                        # only ~14 Hz live although a cycle cost ~15 ms.
                        gate_due = (id(frame[0]) != self._last_world_frame_key
                                    and self.scheduler.should_run_world3d(now, interval=0.))
                    else:
                        gate_due = self.scheduler.should_run_world3d(now, interval=interval)
                if not (frame and enabled and lane["future"] is None and gate_due):
                    return
                # One in-flight frame per lane: never accumulate a stale queue.
                self._capture_sequence += 1
                source_client_id = str(geometry.get("client_id") or geometry.get("session_id") or "offline:unbound")
                source_metadata = {
                    "frame_id": f"capture:{self.epoch}:{self._capture_sequence}",
                    "client_id": source_client_id,
                }
                dropped_frames = self._dropped_world_frames if name == "world" else 0
                submitted_geometry = {**dict(geometry or {}),
                                      "dropped_frames": dropped_frames,
                                      "client_id": source_client_id}
                if name == "world":
                    self._dropped_world_frames = 0
                    # The submitted frame is not a superseded one.
                    self._last_dropped_capture_key = id(frame[0])
                    self._last_world_frame_key = id(frame[0])
                    submitted_at = time.monotonic()
                    if self._last_world_submit_at is not None:
                        self._world_submit_periods_ms.append(
                            (submitted_at-self._last_world_submit_at)*1000)
                    self._last_world_submit_at = submitted_at
                lane["future"] = self.pool.submit(
                    self._timed, detector, frame, now, submitted_geometry,
                    self.epoch, source_metadata,
                    (lambda: self.world3d.last_diagnostics) if name == "world" else None)
                lane["next"] = now+interval
                lane["submitted_at"] = time.monotonic()
                if self.background_active:
                    # Harvest as soon as the job finishes, not on the next
                    # coarse timer tick (median 12-14 ms late offline).
                    lane["future"].add_done_callback(
                        lambda _future: self._background_wake.set())

            if future and future.done():
                harvested_at = time.monotonic()
                lane["future"] = None
                try:
                    result = future.result()
                except Exception as error:
                    result = None
                    lane["status"], lane["items"] = f"vision_error:{type(error).__name__}", []
                # Pipelining: V3 on the next frame (pool thread, mostly native
                # code) overlaps this frame's track/fusion/overlay work
                # instead of waiting for it (live 2026-09-30: 2.6 ms V3 but
                # only ~21 Hz published).
                submit_if_due()
            else:
                result = None
            if result is not None:
                post_started = time.perf_counter()
                try:
                    epoch, at, items, elapsed, source_frame, source_metadata, source_context = result
                    source_context = dict(source_context)
                    detector_snapshot = source_context.pop("_detector_diagnostics", None) or {}
                    source_context.pop("_started_at", None)
                    source_context.pop("_finished_at", None)
                    lane["duration_ms"] = round(elapsed, 2)
                    was_refresh = False
                    source_is_world_map = bool(source_context.get("world_map_open"))
                    if name == "world":
                        # World Map shares the outer worker lane, but it is not
                        # a World3D detector refresh or tracker publication.
                        # Counting its intentional ~2-Hz cadence made healthy
                        # map activity look like a collapsed World3D tracker.
                        if not source_is_world_map:
                            detector_diag = detector_snapshot.get("detector") or {}
                            was_refresh = bool(detector_diag.get("refreshed"))
                            if was_refresh:
                                self._detector_duration_ms = round(elapsed, 2)
                            else:
                                self._propagate_duration_ms = round(elapsed, 2)
                                self._propagate_duration_window_ms.append(float(elapsed))
                    if epoch == self.epoch and source_frame:
                        if name == "world" and source_is_world_map:
                            width, height = dimensions
                            # Map-local coordinates use the estimated visible
                            # canvas (live 2026-10-01: the fixed frame was ~4%
                            # off vertically on the full-screen map); the
                            # legacy constants remain the fallback.
                            canvas = None
                            if len(source_frame[0]) == width*height*4:
                                canvas = estimate_world_map_canvas(
                                    np.frombuffer(source_frame[0], dtype=np.uint8)
                                    .reshape(height, width, 4), stride=4)
                            canvas = canvas or legacy_world_map_rect(width, height)
                            map_left, map_right = canvas.left_px, canvas.right_px
                            map_top, map_bottom = canvas.top_px, canvas.bottom_px
                            map_width = max(1, map_right-map_left)
                            map_height = max(1, map_bottom-map_top)
                            raw_items = [{"kind": "unknown_map_marker", "detector_kind": m.marker_type,
                                          "semantic_type": "UNKNOWN", "belief": "CANDIDATE",
                                          "candidate_labels": list(m.candidate_labels or ("visual_marker_like",)),
                                          "visual_evidence": list(m.evidence or ("appearance_only",)),
                                          "position": {"x": m.position.x/width, "y": m.position.y/height,
                                                       "coordinate_space": "WORLD_MAP_SCREEN_NORMALIZED"},
                                          "map_local_position": {
                                              "x": max(0., min(1., (m.position.x-map_left)/map_width)),
                                              "y": max(0., min(1., (m.position.y-map_top)/map_height)),
                                              "coordinate_space": "NORMALIZED_MAP"},
                                          "inspectable": True, "confidence": m.confidence,
                                          "x": m.position.x/width, "y": 1-m.position.y/height,
                                          "source": "WORLD_MAP_CV", "confirmed": False,
                                          **({"bbox": {"left": m.bbox[0], "top": m.bbox[1],
                                                       "right": m.bbox[2], "bottom": m.bbox[3]},
                                              "bbox_width_fraction": (m.bbox[2]-m.bbox[0])/width,
                                              "bbox_height_fraction": (m.bbox[3]-m.bbox[1])/height}
                                             if m.bbox else {}),
                                          **({"map_local_bounds": {
                                              "left": max(0., min(1., (m.bbox[0]-map_left)/map_width)),
                                              "top": max(0., min(1., (m.bbox[1]-map_top)/map_height)),
                                              "right": max(0., min(1., (m.bbox[2]-map_left)/map_width)),
                                              "bottom": max(0., min(1., (m.bbox[3]-map_top)/map_height)),
                                              "coordinate_space": "NORMALIZED_MAP"}}
                                             if m.bbox else {})}
                                         for m in items]
                            lane["items"] = self.visual_tracks.update("WORLD_MAP_CV", raw_items, at)
                        else:
                            if name == "world" and not source_is_world_map:
                                # Tracker-only publications are intentionally
                                # more frequent than canonical evidence. Carry
                                # their dropped-frame provenance forward until
                                # the next canonical batch instead of losing it
                                # when a 30 Hz tracker job is harvested.
                                self._canonical_dropped_frames += int(
                                    source_context.get("dropped_frames", 0) or 0)
                            canonical_due = bool(
                                name == "world" and not source_is_world_map
                                and at >= self.next_canonical_at)
                            # Visual signatures are durable identity evidence,
                            # not a 60 Hz steering primitive. Compute them on
                            # detector refresh/canonical ticks only.
                            signature_due = canonical_due or (
                                was_refresh and at >= self._next_signature_at)
                            if signature_due:
                                self._next_signature_at = at + self.signature_interval
                            signature_raw = source_frame[0] if signature_due else None
                            raw_items = self._candidates(
                                items, *dimensions, at, raw=signature_raw) if name == "world" else items
                            source = "WORLD_MAP_CV" if name == "world" and source_is_world_map else "WORLD3D" if name == "world" else "MINIMAP_CV"
                            if name == "world" and not source_is_world_map:
                                lane["items"] = []
                                for item_source in ("WORLD3D", "UI_CV"):
                                    group = [item for item in raw_items if item.get("source") == item_source]
                                    # Issue #105: an empty result still ages
                                    # this source's active tracks.
                                    if group or self.visual_tracks.tracks.get(item_source):
                                        lane["items"].extend(self.visual_tracks.update(item_source, group, at))
                            else:
                                lane["items"] = (self.minimap_tracker.update_markers(raw_items, at)
                                                 if name == "minimap"
                                                 else self.visual_tracks.update(source, raw_items, at))
                            if name == "world":
                                lane["items"] = self.semantic_fusion.enrich(lane["items"])
                                canonical_ms = 0.0
                                # Publish the canonical World3D batch after
                                # both existing temporal layers and V4 have
                                # finished. It is evidence-only; no planner or
                                # movement dependency enters this module.
                                run_async = self.async_canonical and self.background_active
                                if (not source_is_world_map and canonical_due and run_async
                                        and self._canonical_future is not None
                                        and not self._canonical_future.done()):
                                    canonical_due = False  # previous batch still running
                                if not source_is_world_map and canonical_due:
                                    width, height = dimensions
                                    tracker_diag = detector_snapshot.get("tracker") or {}
                                    canonical_context = {
                                        **source_context,
                                        "dropped_frames": self._canonical_dropped_frames,
                                    }
                                    job = (source_frame, canonical_context, list(lane["items"]),
                                           width, height, at, dict(source_metadata),
                                           tracker_diag.get("camera_motion_px") or {}, now)
                                    if run_async:
                                        self._canonical_future = self._canonical_pool.submit(
                                            self._run_canonical, *job)
                                    else:
                                        if not self._run_canonical(*job):
                                            lane["status"] = "world3d_batch_invalid"
                                        canonical_ms = self._last_canonical_ms or 0.
                                    self.next_canonical_at = at + self.canonical_interval
                                    self._canonical_dropped_frames = 0
                                if not source_is_world_map and self.live_vision_monitor is not None:
                                    if self._canonical_lock.acquire(blocking=False):
                                        try:
                                            self._canonical_overlay_cache = self.world3d_pipeline.debug_overlay()
                                        finally:
                                            self._canonical_lock.release()
                                    canonical_overlay = self._canonical_overlay_cache
                                    self.live_vision_monitor.publish(
                                        source_frame,
                                        self._fast_debug_overlay(
                                            lane["items"], canonical_overlay,
                                            player_name=source_context.get("character_name")),
                                        # The viewer header needs only the
                                        # device; pickling the full V3
                                        # diagnostics per frame cost main-
                                        # process GIL time (live 2026-09-30).
                                        diagnostics={"detector": {"learned_detector": {
                                            "device": ((detector_snapshot.get("detector") or {})
                                                       .get("learned_detector") or {}).get("device")}}},
                                        frame_id=source_metadata["frame_id"],
                                        processing_latency_ms=elapsed + canonical_ms,
                                    )
                        lane["at"], lane["status"] = at, "ready"
                        if name == "world" and not source_is_world_map:
                            self.projection_revision += 1
                            self.projection_at = at
                            # A detector refresh still anchors and publishes a
                            # tracked frame.  Count it in tracker throughput as
                            # well as detector throughput; the former code
                            # incorrectly reported only propagation-only ticks.
                            self.tracker_rate.mark(now)
                            if was_refresh:
                                self.detector_rate.mark(now)
                        self.rate_meters[name].mark(now)
                except Exception as error:
                    lane["status"], lane["items"] = f"vision_error:{type(error).__name__}", []
                if name == "world":
                    context = result[6] if isinstance(result, tuple) and len(result) > 6 else {}
                    submitted = lane.get("previous_submitted_at")
                    self._world_cycle_ms.append({
                        "queue": ((context.get("_started_at")-submitted)*1000
                                  if submitted is not None and context.get("_started_at") else None),
                        "process": result[3] if isinstance(result, tuple) else None,
                        "harvest_latency": ((harvested_at-context["_finished_at"])*1000
                                            if context.get("_finished_at") else None),
                        "post": (time.perf_counter()-post_started)*1000,
                    })
            else:
                submit_if_due()
            lane["previous_submitted_at"] = lane.get("submitted_at")
            if frame and enabled and lane["future"] is not None and name == "world":
                # A single worker slot intentionally drops superseded frames
                # instead of queuing stale vision.  Count each physical input
                # frame once and attach the count to the next published batch.
                capture_key = id(frame[0])
                if capture_key != self._last_dropped_capture_key:
                    self._dropped_world_frames += 1
                    self._last_dropped_capture_key = capture_key
        # Diagnostics copy every track (with histories) and resolve UI
        # surfaces.  Rebuilding them on every pump wake (>100/s) grew with the
        # number of tracks and cut the published rate from 40-50 Hz to 14-17
        # Hz live (2026-09-30); refresh on new results, at most 10 Hz.
        diagnostics_key = (self.projection_revision, tuple(lane["at"] for lane in self.lanes.values()))
        if (self.diagnostics and diagnostics_key == self._diagnostics_key
                and now - self._diagnostics_at < .5) or now - self._diagnostics_at < .1:
            return self._live_items(now, allow)
        self._diagnostics_key, self._diagnostics_at = diagnostics_key, now
        self.diagnostics = {name: {"status": lane["status"], "duration_ms": lane["duration_ms"],
                                  "age_ms": round(max(0, now-lane["at"])*1000, 2) if lane["at"] else None,
                                  "candidates": len(lane["items"]), "in_flight": lane["future"] is not None,
                                  "scheduled_interval_ms": round(self._dynamic_interval(name, geometry)*1000, 2),
                                  "actual_hz": self.rate_meters[name].hz(now)}
                            for name, lane in self.lanes.items()}
        self.diagnostics["world"].update(
            detector_hz=self.detector_rate.hz(now),
            tracker_hz=self.tracker_rate.hz(now),
            tracker_target_hz=(0. if world_map_open else 40. if (geometry.get("fast_visual_servo") or
                                      geometry.get("tooltip_probe") or
                                      self._has_active_tracks()) else 30.),
            active_surface=("WORLD_MAP" if world_map_open else "WORLD3D"),
            background_active=self.background_active,
            background_error=self._background_error,
            detector_duration_ms=self._detector_duration_ms,
            propagate_duration_ms=self._propagate_duration_ms,
            propagate_scheduler_ms=(round(self._robust_propagation_ms(), 2)
                                    if self._robust_propagation_ms() is not None else None),
            propagate_scheduler_samples=len(self._propagate_duration_window_ms),
            canonical_hz=self.canonical_rate.hz(now),
            canonical_target_hz=round(1. / self.canonical_interval, 2),
            canonical_duration_ms=(round(self._last_canonical_ms, 2)
                                   if self._last_canonical_ms is not None else None),
            cycle_ms=self._cycle_summary(),
            context_resets=self.context_reset_count,
            context_reset_fields=dict(self.context_reset_fields),
            ui_flag_raw_flips=dict(self.ui_flag_raw_flips),
            context_reset_reasons=list(self.context_reset_reasons))
        self.diagnostics["tracks"] = self.visual_tracks.snapshot()
        self.diagnostics["world3d_v3_v4"] = dict(self.world3d.last_diagnostics)
        self.diagnostics["surface_state"] = {
            "world_map": self.world_map_state_detector.detect(
                geometry=geometry, observation=None),
            "map_context": self.map_context_resolver.resolve(geometry),
            "best_minimap_quest_cue": self.minimap_resolver.best_quest_cue(
                self.lanes["minimap"]["items"]),
        }
        # Keep high-rate GUI/status output bounded. The complete batch is held
        # on ``world3d_batch`` for the runtime publication path and replay,
        # while diagnostics carries only a compact health summary.
        self.diagnostics["world3d_batch"] = ({
            "frame_id": self.world3d_batch.frame_id,
            "tracks": len(self.world3d_batch.entity_tracks),
            "obstacles": len(self.world3d_batch.obstacles),
            "entrances": len(self.world3d_batch.entrances),
            "latency_ms": round(self.world3d_batch.processing_latency_ms, 3),
            "status": "ready"}
            if self.world3d_batch is not None else None)
        self.diagnostics["hard_examples"] = self.hard_examples.diagnostics()
        self.diagnostics["stable_objects"] = self.visual_tracks.stable_objects.diagnostics()
        self.status = ";".join(f"{name}:{lane['status']}" for name, lane in self.lanes.items())
        return self._live_items(now, allow)
