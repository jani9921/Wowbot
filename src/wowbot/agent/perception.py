"""Reuse M7's candidate detector/tracker; CV labels remain hypotheses."""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
import math
import os
import threading
import time
import numpy as np
from wowbot.vision.world3d.scene import build_scene_roi
from wowbot.vision.world3d.tracking import WorldCandidateTracker
from wowbot.vision.world3d.v3 import World3DPerceptionV3
from wowbot.vision.world3d.v4 import HardExampleCollector
from wowbot.vision.world3d.components import WorldSceneExtractor, WorldCandidateDetector, SemanticFusion
from wowbot.vision.world3d.pipeline import World3DPipeline
from wowbot.vision.world3d.validation import validate_batch
from wowbot.vision.world3d.profiles import resolve_world3d_profile
from .visual_tracks import VisualTrackManager
from .runtime_scheduler import RateMeter, RuntimeCadenceScheduler
from .obstacle_perception import tag_obstacle_candidates
from .perception_pipeline import PerceptionPipeline
from wowbot.vision.minimap_perception import MinimapTracker, MinimapResolver
from wowbot.vision.world_map_calibration import estimate_world_map_canvas, legacy_world_map_rect
from wowbot.vision.world_map_perception import (
    MapContextResolver, MapMouseoverResolver, WorldMapResolver, WorldMapStateDetector,
)


def _minimap_marker_payload(marker, left, top, width, height, *, center=None, radius=None, signature=None, bbox=None,
                            heading=None):
    if center is None:
        center = type("Point", (), {"x": width/2-left, "y": height/2-top})()
    if radius is None:
        radius = min(width, height)/2
    dx = marker.position.x - center.x
    dy = marker.position.y - center.y
    payload = {"kind": "unknown_minimap_marker", "detector_kind": "unknown_minimap_marker",
            "semantic_type": "UNKNOWN", "belief": "CANDIDATE",
            "confidence": marker.confidence, "source": "MINIMAP_CV",
            "confirmed": False, "x": (marker.position.x+left)/width,
            "y": 1-(marker.position.y+top)/height, "bearing": marker.bearing_degrees,
            "appearance": {"color": marker.marker_color, "symbol": marker.symbol},
            "candidate_labels": list(marker.candidate_labels), "visual_evidence": list(marker.evidence),
            "local_position": {"dx": dx, "dy": dy, "distance": math.hypot(dx, dy),
                               "angle": (math.degrees(math.atan2(dx, -dy))+360.0) % 360.0,
                               "normalized_dx": dx/radius if radius else dx,
                               "normalized_dy": dy/radius if radius else dy},
            "coordinate_space": "MINIMAP_LOCAL", "player_local": {"x": 0.0, "y": 0.0},
            "inspectable": False}
    if heading is not None:
        payload["minimap_heading"] = {"degrees": heading.degrees, "confidence": heading.confidence,
                                      "source": "ADDON_PLAYER_ORIENTATION", "fact": False}
    if signature:
        payload["visual_signature"] = signature
    if bbox:
        payload["bbox"] = bbox
    return payload


class PerceptionWorker:
    # A complete AIPC5 telemetry snapshot is paged and live World3D processing
    # can transiently take more than two seconds under capture/debug load. Keep
    # the latest tracked projection no longer than the authoritative telemetry
    # freshness boundary; 0.75 s discarded valid observations before planning.
    RESULT_TTL_SECONDS = 3.0
    _INTERNAL_HISTORY_FIELDS = frozenset({
        "observations", "bbox_history", "appearance_history",
        "position_history", "confidence_history", "candidate_label_history",
    })

    def __init__(self, *, hard_example_directory=None, ocr=None, scheduler=None,
                 learned_detector=None, live_vision_monitor=None,
                 world3d_proposal_mode="HYBRID"):
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="aipc-vision")
        self.scheduler = scheduler or RuntimeCadenceScheduler()
        self.tracker = WorldCandidateTracker()
        if ocr is None:
            from wowbot.vision.world3d.ocr import TargetedOCR
            ocr = TargetedOCR(scheduler=self.scheduler)
        self.world3d = World3DPerceptionV3(
            ocr=ocr, learned_detector=learned_detector,
            proposal_mode=world3d_proposal_mode)
        self.scene_extractor = WorldSceneExtractor()
        self.world_candidate_detector = WorldCandidateDetector(self.world3d)
        self.semantic_fusion = SemanticFusion()
        # V2/V3/V4 remain detector/tracker/evidence layers.  The canonical
        # pipeline owns their one normalized local-world publication only.
        self.world3d_pipeline = World3DPipeline()
        self.world3d_batch = None
        self.hard_examples = HardExampleCollector(hard_example_directory)
        # An unmatched track used to be *shown* for its whole 1.2 s coast:
        # after a camera turn Live Vision trailed LOST_TEMPORARY boxes (live
        # 2026-09-30 20:22).  Shortening the coast itself made reappearing
        # subjects take new ids, so presentation and identity are separate:
        # shown for .3 s, associable (camera-compensated) for 1.5 s.
        self.visual_tracks = VisualTrackManager(
            lost_grace_seconds=float(os.environ.get("AIPC_VISUAL_TRACK_LOST_GRACE", "1.5")),
            present_grace_seconds=float(os.environ.get("AIPC_VISUAL_TRACK_PRESENT_GRACE", ".3")))
        self.minimap_tracker = MinimapTracker(self.visual_tracks)
        self.minimap_resolver = MinimapResolver()
        self.world_map_resolver = WorldMapResolver()
        self.world_map_state_detector = WorldMapStateDetector()
        self.map_context_resolver = MapContextResolver()
        self.map_mouseover_resolver = MapMouseoverResolver()
        self.pipeline = PerceptionPipeline(
            world3d=lambda *args: self._world_v2(*args),
            minimap=lambda *args: self._minimap(*args),
            world_map=lambda *args: self._world_map(*args),
            ui=lambda frame, at, geometry: [])
        self.lanes = {name: {"future": None, "next": 0., "at": 0., "items": [],
                             "status": "idle", "duration_ms": None}
                      for name in ("world", "minimap")}
        self.context = None
        self.epoch = 0
        self.hits = {}
        self.last_world_at = 0.
        self.projection_revision = 0
        self.projection_at = 0.
        self.status = "idle"
        self.diagnostics = {}
        self.rate_meters = {name: RateMeter(10.) for name in self.lanes}
        self._detector_duration_ms: float | None = None
        self._propagate_duration_ms: float | None = None
        # Keep scheduling robust to one-off OS/GPU/viewer stalls.  The former
        # last-sample controller turned a single 244-ms propagation spike into
        # a persistent ~2-Hz tracker even after frames were back at 8-9 ms.
        self._propagate_duration_window_ms: deque[float] = deque(maxlen=31)
        self.detector_rate = RateMeter(10.)
        self.tracker_rate = RateMeter(10.)
        # Capture provenance is created at submission time, not at result
        # publication time.  A completed worker can therefore never claim a
        # later screenshot as its source.
        self._capture_sequence = 0
        self._last_dropped_capture_key = None
        self._dropped_world_frames = 0
        self._canonical_dropped_frames = 0
        self.live_vision_monitor = live_vision_monitor
        # Fast tracking/view publication must not wait for the full semantic,
        # traversability and memory batch.  The canonical scene graph costs
        # ~40-60 ms on the live machine; running it at 12 Hz consumed most of
        # the control thread even though patch propagation itself costs ~5 ms.
        # Four rich evidence publications per second are sufficient while the
        # screen-space tracker has an independent 30 Hz contract.
        self.canonical_interval = 1. / 4.
        self.next_canonical_at = 0.
        self.canonical_rate = RateMeter(10.)
        self._last_canonical_ms: float | None = None
        # Visual signatures were computed on every detector refresh (~11 Hz
        # before the capture-driven YOLO feed).  The feed refreshes nearly
        # every frame, so keep the former identity-evidence cadence explicit.
        self.signature_interval = 1. / max(1., float(os.environ.get(
            "AIPC_VISUAL_SIGNATURE_HZ", "12")))
        self._next_signature_at = 0.
        self.context_reset_count = 0
        self._world_cycle_ms: deque[dict] = deque(maxlen=90)
        self._diagnostics_key = None
        self._diagnostics_at = -1e9
        self._live_items_key = None
        self._live_items_cache: list[dict] = []
        # Canonical evidence (scene quality, traversability, visual memory,
        # nameplates, hard examples) cost 24 ms offline and 82 ms live four
        # times a second on the pump thread; once YOLO boxes existed the
        # published rate fell from 50-60 Hz to 10-17 Hz (live 2026-09-30).
        # Live, it runs on its own single worker so it never blocks the pump.
        self._canonical_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="aipc-canonical")
        self._canonical_future = None
        self._canonical_lock = threading.Lock()
        self._canonical_overlay_cache: dict = {}
        self.async_canonical = os.environ.get("AIPC_CANONICAL_ASYNC", "1").strip() != "0"
        self.world_frame_driven = os.environ.get(
            "AIPC_WORLD3D_FRAME_DRIVEN", "1").strip() != "0"
        self._last_world_frame_key = None
        self._last_world_submit_at: float | None = None
        self._world_submit_periods_ms: deque[float] = deque(maxlen=90)
        self.ui_flag_debounce = max(0., float(os.environ.get(
            "AIPC_PERCEPTION_UI_FLAG_DEBOUNCE", "0.25")))
        self._ui_flags: dict[str, list] = {}
        self.ui_flag_raw_flips: dict[str, int] = {}
        self.context_reset_reasons: deque[dict] = deque(maxlen=64)
        # Cumulative per-field counts over the whole session.
        self.context_reset_fields: dict[str, int] = {}
        # Live runtime ownership: one background pump owns update(), while the
        # control/planner thread only replaces a latest-value request and reads
        # the latest projection.  This prevents 200-300 ms planner/SQLite ticks
        # from reducing a 30 Hz tracker to 3-12 Hz. Offline callers retain the
        # deterministic synchronous update() API.
        self._background_stop = threading.Event()
        self._background_wake = threading.Event()
        self._background_lock = threading.Lock()
        self._background_thread: threading.Thread | None = None
        self._background_frame_provider = None
        self._background_request: dict | None = None
        self._background_result: list[dict] = []
        self._background_error: str | None = None

    @property
    def background_active(self) -> bool:
        return self._background_thread is not None and self._background_thread.is_alive()

    def start_background(self, frame_provider, *, hz: float = 40.) -> None:
        """Start the single live perception owner over a latest-frame source."""
        if self.background_active:
            return
        self._background_frame_provider = frame_provider
        # The pump must sample faster than the 30 Hz tracker gate. At exactly
        # 60 Hz, collecting an async result on one tick and narrowly missing
        # the 33.3 ms gate on the next quantized publication to ~20-24 Hz.
        # 90 Hz gives the gate a third sampling point without queueing frames;
        # update() still submits detector/tracker work only when its own
        # cadence gate is due.
        self._background_interval = 1. / max(30., min(120., float(hz)))
        self._background_stop.clear()
        self._background_thread = threading.Thread(
            target=self._background_loop, name="aipc-perception-pump", daemon=True)
        self._background_thread.start()

    def submit_latest(self, *, allow=True, geometry=None, context=None,
                      world_map_open=False) -> list[dict]:
        """Replace live perception context without ever queueing stale work."""
        with self._background_lock:
            self._background_request = {
                "allow": allow, "geometry": dict(geometry or {}),
                "context": context, "world_map_open": world_map_open,
            }
            result = list(self._background_result)
        self._background_wake.set()
        return result

    def _background_loop(self) -> None:
        next_tick = time.monotonic()
        while not self._background_stop.is_set():
            now = time.monotonic()
            if now < next_tick:
                woken = self._background_wake.wait(min(next_tick-now, self._background_interval))
                self._background_wake.clear()
                # A finished vision job, a new capture frame or a new request
                # is served now; a plain timeout re-checks the tick deadline.
                if not woken:
                    continue
            with self._background_lock:
                request = dict(self._background_request or {})
            provider = self._background_frame_provider
            frame = provider() if callable(provider) else None
            if request and frame is not None:
                try:
                    result = self.update(frame, now, **request)
                    with self._background_lock:
                        self._background_result = result
                        self._background_error = None
                except Exception as error:  # passive perception must fail closed
                    with self._background_lock:
                        self._background_error = f"{type(error).__name__}:{error}"
            next_tick = max(next_tick + self._background_interval,
                            time.monotonic() + .001)

    def _robust_propagation_ms(self) -> float | None:
        if self._propagate_duration_window_ms:
            ordered = sorted(self._propagate_duration_window_ms)
            return float(ordered[len(ordered)//2])
        return self._propagate_duration_ms

    def _dynamic_interval(self, name: str, geometry: dict) -> float:
        lane = self.lanes[name]
        duration = (float(lane["duration_ms"])/1000
                    if lane.get("duration_ms") is not None else 0.)
        if name == "world":
            profile = resolve_world3d_profile(geometry)
            has_tracks = self._has_active_tracks()
            # Every context gets tracker/control feedback at a nominal 30 Hz.
            # World3DPerceptionV3 owns one continuous, single-in-flight
            # latest-frame detector stream; intermediate jobs propagate the
            # last boxes while inference is busy. Measured execution time
            # remains the hard lower bound, so slower hosts never accumulate a
            # stale frame queue.
            # Schedule active tracking with enough headroom to absorb the
            # periodic canonical/minimap publication ticks. The tracker-only
            # job costs about 0.6-1.0 ms; its 40 Hz admission is independent
            # from the 4 Hz canonical evidence layer and targets at least 30
            # completed projections per second under live scheduler jitter.
            active_schedule_hz = 45.
            desired = min(1./profile.tracker_hz,
                          1./active_schedule_hz if geometry.get("fast_visual_servo") else
                          1./active_schedule_hz if geometry.get("tooltip_probe") or has_tracks else 1./24)
            # A full V2 refresh can take 400-800 ms on the live CPU, while
            # propagation of its existing tracks is cheap.  Using the last
            # full-refresh cost as back-pressure delayed the *next tracker*
            # by another 500 ms; by then V3's detector deadline had elapsed,
            # so nearly every job became another full refresh.  During a
            # committed visual servo, schedule from the measured propagation
            # cost instead. V3 independently rate-limits heavy refreshes.
            # Once a real propagation cost exists, it is the scheduler cost
            # for every tracker tick. A slow periodic detector refresh must
            # not hold the complete lane at detector latency (live example:
            # 131 ms detector versus 4 ms propagation). V3 independently
            # decides when the next heavy refresh is due.
            robust_propagation_ms = self._robust_propagation_ms()
            if robust_propagation_ms is not None:
                # Compatibility for restored diagnostics and focused tests
                # which seed only the last measurement.
                duration = robust_propagation_ms/1000
        else:
            desired = .10 if geometry.get("visible") else .50
        # Never queue work faster than this CPU has demonstrated it can finish.
        return min(.50, max(desired, duration*1.10))

    @staticmethod
    def _stable_context_key(context, dimensions, allow, geometry):
        """Only reset temporal vision for a real scene/ROI transition.

        Cursor position and tooltip-probe state are per-frame attention hints.
        Including them in tracker identity invalidated every in-flight result
        while HOVER moved the cursor, exactly when fast confirmation mattered.
        """
        geometry = geometry or {}
        stable_geometry = tuple((name, geometry.get(name)) for name in (
            "visible", "center_x", "center_y", "radius_fraction",
            "world_map_open", "quest_ui_open", "gossip_open",
            # These alter projection/ROI semantics and must invalidate visual
            # tracks. Cursor/hover are deliberately absent: they are merely
            # active-perception hints and must not reset tracking.
            "ui_scale", "camera_zoom", "vehicle_camera"))
        return context, dimensions, bool(allow), stable_geometry

    _CONTEXT_PARTS = ("session_id", "character_guid", "map_id", "map_zoom_count")

    def _record_context_reset(self, previous, key, now) -> None:
        """Name the key components whose change reset all visual tracking.

        Each reset restarts detector association and public track identity
        (live 2026-09-30: 28 resets in about a minute), so the cause must be
        visible in diagnostics rather than inferred.
        """
        changed: list[str] = []
        if previous is None:
            changed.append("initial")
        else:
            old_context, old_dimensions, old_allow, old_geometry = previous
            context, dimensions, allow, geometry = key
            if old_context != context:
                if isinstance(old_context, tuple) and isinstance(context, tuple) \
                        and len(old_context) == len(context):
                    changed.extend(
                        (self._CONTEXT_PARTS[index] if index < len(self._CONTEXT_PARTS)
                         else f"context[{index}]")
                        for index, (old, new) in enumerate(zip(old_context, context))
                        if old != new)
                else:
                    changed.append("context")
            if old_dimensions != dimensions:
                changed.append(f"dimensions:{old_dimensions}->{dimensions}")
            if old_allow != allow:
                changed.append(f"allow:{old_allow}->{allow}")
            old_values = dict(old_geometry)
            changed.extend(f"{name}:{old_values.get(name)!r}->{value!r}"
                           for name, value in geometry if old_values.get(name) != value)
        self.context_reset_count += 1
        self.context_reset_reasons.append({
            "at": round(float(now), 3), "changed": changed,
            "payload_kind": getattr(self, "_last_payload_kind", None)})
        for item in changed:
            field = item.split(":", 1)[0]
            self.context_reset_fields[field] = self.context_reset_fields.get(field, 0) + 1

    @classmethod
    def _live_projection(cls, item: dict) -> dict:
        """Current track state only; temporal histories remain manager-owned."""
        return {key: value for key, value in item.items()
                if key not in cls._INTERNAL_HISTORY_FIELDS}

    @staticmethod
    def _fast_debug_overlay(items: list[dict], canonical_overlay: dict | None = None,
                            *, player_name: str | None = None) -> dict:
        """Current tracker boxes plus slower canonical geometry.

        The viewer is diagnostic-only and must never force the 30 Hz tracker
        through the complete canonical scene pipeline merely to draw a box.
        """
        canonical_overlay = canonical_overlay or {}
        tracks = []
        for item in items:
            bbox = item.get("bbox") or {}
            if not all(isinstance(bbox.get(key), (int, float))
                       for key in ("left", "top", "right", "bottom")):
                continue
            appearance = dict(item.get("appearance") or {})
            relations = item.get("visual_relations") or ()
            has_independent_anchor = any(
                isinstance(relation, dict)
                and str(relation.get("type") or "").upper() in {"ABOVE", "GROUP_MEMBER"}
                and str(relation.get("belief") or "").upper() == "SUPPORTED"
                for relation in relations)
            visual_group = (item.get("visual_group")
                            if isinstance(item.get("visual_group"), dict) else {})
            has_independent_anchor = bool(
                has_independent_anchor
                or str(visual_group.get("belief") or "").upper() == "SUPPORTED")
            self_player_name = (
                str(player_name or "").strip()
                if appearance.get("self_avatar_suppression_hint") and not has_independent_anchor
                else "")
            tracks.append({
                "track_id": item.get("track_id"), "bbox": dict(bbox),
                "detector_kind": item.get("detector_kind") or item.get("kind"),
                "appearance": appearance,
                "candidate_labels": list(item.get("candidate_labels") or ()),
                "lifecycle": item.get("lifecycle") or item.get("state") or "ACTIVE",
                "confidence": float(item.get("confidence") or 0.),
                "self_player_avatar": bool(self_player_name),
                "display_name": self_player_name or None,
            })
        return {
            "tracks": tracks,
            "traversability": list(canonical_overlay.get("traversability") or ()),
            "obstacles": list(canonical_overlay.get("obstacles") or ()),
            "entrances": list(canonical_overlay.get("entrances") or ()),
            "camera": dict(canonical_overlay.get("camera") or {}),
        }

    @staticmethod
    def _world(frame, at, geometry):
        raw, width, height = frame
        if len(raw) != width*height*4:
            return []
        if (geometry or {}).get("world_map_open"):
            from wowbot.vision.adapters.world_map import detect_world_map
            return detect_world_map(raw, width, height, observed_at=at).markers
        # Compatibility entry point for offline tools. Runtime uses the
        # stateful v2 method below.
        from wowbot.vision.world3d.candidates import detect_world_candidates
        return detect_world_candidates(raw, width, height, build_scene_roi(width, height))

    def _world_map(self, frame, at, geometry):
        raw, width, height = frame
        if len(raw) != width*height*4:
            return []
        return self.world_map_resolver.process(frame, at, geometry).markers

    def _world_v2(self, frame, at, geometry):
        raw, width, height = frame
        if (geometry or {}).get("world_map_open") or len(raw) != width*height*4:
            return self._world(frame, at, geometry)
        scene = self.scene_extractor.extract(frame)
        return self.world_candidate_detector.detect(
            frame, scene, observed_at=at, ui_hints=geometry)

    @staticmethod
    def _minimap(frame, at, geometry):
        if not geometry or not geometry.get("visible"):
            return []
        from wowbot.vision.adapters.minimap import detect_minimap
        from wowbot.vision.minimap_geometry import MinimapGeometry
        geom = MinimapGeometry(geometry["center_x"], geometry["center_y"], geometry["radius_fraction"])
        if not (0 < geom.center_x_fraction < 1 and 0 < geom.center_y_fraction < 1 and .01 < geom.radius_fraction < .3):
            return []
        raw, width, height = frame
        center, radius = geom.center(width, height), geom.radius(width, height)
        # Full pixel resolution, only unused surroundings cropped. Padding keeps
        # the circular edge context. Convert results back to client coordinates.
        left, top = max(0, math.floor(center.x-radius-8)), max(0, math.floor(center.y-radius-8))
        # Existing detectors use round-to-even for centroids: an even translation
        # preserves half-pixel rounding and target-vs-glyph distance thresholds.
        left, top = left-left % 2, top-top % 2
        right, bottom = min(width, math.ceil(center.x+radius+9)), min(height, math.ceil(center.y+radius+9))
        cw, ch = right-left, bottom-top
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
        crop = pixels[top:bottom, left:right].tobytes()
        local = MinimapGeometry((center.x-left)/cw, (center.y-top)/ch, radius/ch)
        obs = detect_minimap(crop, cw, ch, observed_at=at, geometry=local,
                             heading_degrees=geometry.get("player_orientation"))
        from wowbot.vision.visual_signature import build_visual_signature
        from wowbot.vision.world3d.models import PixelRect
        markers = list(obs.markers)
        from wowbot.vision.map_markers import get_learned_map_detector, merge_minimap_markers
        learned = get_learned_map_detector("MINIMAP")
        if learned is not None and learned.status == "ready":
            learned_markers, _ = learned.detect(
                np.ascontiguousarray(pixels[top:bottom, left:right, :3]))
            # Rim arrows legitimately sit outside the heuristic usable disc.
            limit = obs.center_radius_px * 1.08
            learned_markers = [
                marker for marker in learned_markers
                if math.hypot(marker.position.x-obs.player_marker.x,
                              marker.position.y-obs.player_marker.y) <= limit]
            markers = merge_minimap_markers(learned_markers, markers)
        result = []
        for marker in markers:
            local_rect = PixelRect(max(0, int(marker.position.x)-8), max(0, int(marker.position.y)-8),
                                   min(cw, int(marker.position.x)+9), min(ch, int(marker.position.y)+9))
            signature = build_visual_signature(crop, cw, ch, local_rect, kind=marker.marker_type,
                                               representation_space="MINIMAP")
            bbox = {"left": local_rect.left+left, "top": local_rect.top+top,
                    "right": local_rect.right+left, "bottom": local_rect.bottom+top,
                    "coordinate_space": "CLIENT_PIXELS"}
            result.append(_minimap_marker_payload(marker, left, top, width, height,
                                                  center=obs.player_marker, radius=obs.usable_radius_px,
                                                  signature=signature, bbox=bbox, heading=obs.heading))
        # Quest objective area (light-blue outline), user 2026-10-03.
        try:
            from wowbot.vision.minimap_quest_area import detect_quest_area
            bgr = pixels[top:bottom, left:right, :3]
            area = detect_quest_area(np.ascontiguousarray(bgr[..., ::-1]),
                                     (center.x-left, center.y-top), radius)
        except Exception:  # noqa: BLE001 -- an optional cue must not stop perception
            area = None
        # Selected-target marker (reaction-coloured dot in a gold crosshair).
        try:
            from wowbot.vision.minimap_target_marker import detect_target_markers
            target_markers = detect_target_markers(
                np.ascontiguousarray(pixels[top:bottom, left:right, 2::-1]),
                (center.x-left, center.y-top), radius)
        except Exception:  # noqa: BLE001 -- an optional cue must not stop perception
            target_markers = []
        if target_markers:
            result.append({
                "track_id": "minimap:target_marker", "kind": "minimap_target_marker",
                "detector_kind": "minimap_target_marker", "source": "MINIMAP_CV",
                "semantic_type": "UNKNOWN", "belief": "CANDIDATE", "confirmed": False,
                "confidence": .85, "inspectable": False,
                "x": center.x/width, "y": 1-center.y/height, "observed_at": at,
                "candidate_labels": ["selected_target_marker_like"],
                "minimap_radius_px": float(radius),
                "view_radius_yards": geometry.get("view_radius_yards"),
                "rotate_minimap": geometry.get("rotate_minimap"),
                "markers": target_markers})
        # Quest objective NPC dots (yellow), user 2026-10-04.
        try:
            from wowbot.vision.minimap_quest_dot import detect_quest_dots
            dots = detect_quest_dots(np.ascontiguousarray(pixels[top:bottom, left:right, 2::-1]),
                                     (center.x-left, center.y-top), radius)
        except Exception:  # noqa: BLE001 -- an optional cue must not stop perception
            dots = []
        if dots:
            result.append({
                "track_id": "minimap:quest_dots", "kind": "minimap_quest_dot",
                "detector_kind": "minimap_quest_dot", "source": "MINIMAP_CV",
                "semantic_type": "UNKNOWN", "belief": "CANDIDATE", "confirmed": False,
                "confidence": .8, "inspectable": False,
                "x": center.x/width, "y": 1-center.y/height, "observed_at": at,
                "candidate_labels": ["quest_objective_dot_like"],
                "minimap_radius_px": float(radius),
                "view_radius_yards": geometry.get("view_radius_yards"),
                "rotate_minimap": geometry.get("rotate_minimap"),
                "dots": dots})
        if area is not None:
            result.append({
                "track_id": "minimap:quest_area", "kind": "minimap_quest_area",
                "detector_kind": "minimap_quest_area", "source": "MINIMAP_CV",
                "semantic_type": "UNKNOWN", "belief": "CANDIDATE", "confirmed": False,
                "confidence": .85 if area["closed"] else .6, "inspectable": False,
                "x": center.x/width, "y": 1-center.y/height, "observed_at": at,
                "candidate_labels": ["quest_area_outline_like"],
                "minimap_radius_px": float(radius),
                "view_radius_yards": geometry.get("view_radius_yards"),
                "rotate_minimap": geometry.get("rotate_minimap"),
                "quest_area": area})
        return result

    @staticmethod
    def _timed(detector, frame, at, geometry, epoch, source_metadata, diagnostics_source=None):
        started_at = time.monotonic()
        start = time.perf_counter()
        items = detector(frame, at, geometry)
        elapsed = (time.perf_counter()-start)*1000
        # The next frame may already be running when this result is
        # post-processed, so the detector diagnostics travel with the result.
        diagnostics = dict(diagnostics_source()) if diagnostics_source is not None else {}
        geometry = {**geometry, "_started_at": started_at, "_finished_at": time.monotonic(),
                    "_detector_diagnostics": diagnostics}
        return epoch, at, items, elapsed, frame, source_metadata, geometry

    def _candidates(self, detected, width, height, at, raw=None):
        if at-self.last_world_at > 1.:
            self.hits.clear()
        # V3 already fuses the V2 detector with its high-rate patch tracker.
        # Keep the legacy tracker only for compatibility detectors which do
        # not provide stable IDs.
        tracked = tuple(detected) if detected and all(c.track_id is not None for c in detected) \
                  else self.tracker.update(detected)
        self.hits = {c.track_id: self.hits.get(c.track_id, 0)+1 for c in tracked}
        self.last_world_at = at
        result = []
        for c in tracked:
            stable = self.hits[c.track_id]
            inspectable = c.kind in {"unknown_subject_candidate", "unknown_subject_probe"} and stable >= 3
            if c.kind == "unknown_object_candidate":
                inspectable = stable >= 3 and c.confidence >= .60
            bbox = {"left": c.rect.left, "top": c.rect.top, "right": c.rect.right, "bottom": c.rect.bottom,
                    "coordinate_space": "CLIENT_PIXELS"}
            signature = None
            if raw is not None:
                from wowbot.vision.visual_signature import build_visual_signature
                signature = build_visual_signature(raw, width, height, c.rect, kind=c.kind,
                                                   relation=c.relation, class_name=c.class_name)
            result.append({"track_id": f"{self.epoch}:{c.track_id}", "kind": c.kind,
                           # The V3 tracker is the fast World3D identity
                           # authority. Keep its ID as explicit association
                           # evidence so the source-level manager never
                           # invents a second identity after a detector refresh.
                           "upstream_track_id": f"WORLD3D_V3:{c.track_id}",
                           "confidence": c.confidence, "stable_frames": stable,
                           "inspectable": inspectable, "x": (c.rect.left+c.rect.right)/2/width,
                           "y": 1-(c.rect.top+c.rect.bottom)/2/height,
                           "source": "UI_CV" if c.kind.startswith("unknown_ui_") else "WORLD3D",
                           "evidence": c.evidence, "confirmed": False,
                           "semantic_type": "UNKNOWN", "relation_hint": c.relation,
                           "belief": "SUPPORTED" if stable >= 3 else "CANDIDATE",
                           "appearance": dict(c.appearance), "candidate_labels": list(c.candidate_labels),
                           "evidence_roles": {"subject_shape": "PRIMARY",
                                              "nameplate": "SECONDARY" if "nameplate" in c.evidence else "ABSENT"},
                           "bbox": bbox,
                           "bbox_width_fraction": c.rect.width/width,
                           "bbox_height_fraction": c.rect.height/height,
                           "visual_signature": signature})
        return tag_obstacle_candidates(result)

    def _run_canonical(self, source_frame, context, items, width, height, at,
                       metadata, camera_motion, requested_at) -> bool:
        """One canonical World3D evidence batch (pump thread offline, own
        worker live).  Returns whether the batch validated."""
        started = time.perf_counter()
        with self._canonical_lock:
            batch = self.world3d_pipeline.observe(
                source_frame, context, items, build_scene_roi(width, height),
                observed_at=at, frame_id=metadata["frame_id"],
                client_id=metadata["client_id"], camera_motion=camera_motion)
        valid = validate_batch(batch).valid
        self.hard_examples.consider(source_frame[0], width, height, items, at)
        self.world3d_batch = batch
        self._last_canonical_ms = (time.perf_counter()-started)*1000
        self.canonical_rate.mark(requested_at)
        return valid

    def notify_new_frame(self) -> None:
        """Wake the background pump for a newly captured frame."""
        self._background_wake.set()

    def _cycle_summary(self) -> dict:
        """Median world-lane cycle parts (ms): where published Hz is lost."""
        now = time.monotonic()
        if now < getattr(self, "_cycle_summary_until", 0.):
            return self._cycle_summary_cache
        self._cycle_summary_until = now + .5
        summary = {}
        for key in ("queue", "process", "harvest_latency", "post"):
            values = sorted(float(row[key]) for row in self._world_cycle_ms
                            if row.get(key) is not None)
            if values:
                summary[key] = round(values[len(values)//2], 2)
        periods = sorted(self._world_submit_periods_ms)
        if periods:
            summary["submit_period"] = round(periods[len(periods)//2], 2)
        self._cycle_summary_cache = summary
        return summary

    def _debounced_ui_flag(self, name: str, raw: bool, now: float) -> bool:
        """Effective UI flag: a change counts only after it persists.

        Live 2026-09-30: during OPEN_MAP the requested ``world_map_open``
        flipped 28 times in ~4 s (19-250 ms apart).  Every flip reset all
        visual tracking, the feed tracker and the stable object layer.  A real
        map/dialog transition persists; a sub-``ui_flag_debounce`` flip does
        not reset perception (raw flips stay counted for diagnosis).
        """
        state = self._ui_flags.get(name)
        if state is None:
            self._ui_flags[name] = [raw, raw, now]
            return raw
        effective, candidate, since = state
        if raw != candidate:
            self.ui_flag_raw_flips[name] = self.ui_flag_raw_flips.get(name, 0) + 1
        if raw == effective:
            state[1], state[2] = raw, now
            return effective
        if raw != candidate:
            state[1], state[2] = raw, now
            return effective
        if now - since >= self.ui_flag_debounce:
            state[0] = raw
            return raw
        return effective

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
                                    if group:
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

    def _has_active_tracks(self) -> bool:
        """Cheap: current world items instead of a full track snapshot."""
        return any(item.get("source") in {"WORLD3D", "UI_CV"}
                   and (item.get("state") or item.get("lifecycle")) in {"ACTIVE", "REACQUIRE_CANDIDATE"}
                   for item in self.lanes["world"]["items"])

    def _live_items(self, now: float, allow: bool) -> list[dict]:
        # VisualTrackManager retains its bounded temporal histories for
        # association, reacquisition and diagnostics. The high-rate WorldModel
        # projection needs only the current track state; copying those histories
        # into every Observation made live status/state hundreds of KB larger.
        fresh = tuple(allow and now-lane["at"] <= self.RESULT_TTL_SECONDS
                      for lane in self.lanes.values())
        key = (tuple(lane["at"] for lane in self.lanes.values()),
               tuple(id(lane["items"]) for lane in self.lanes.values()), fresh)
        if key != self._live_items_key:
            self._live_items_key = key
            self._live_items_cache = [
                self._live_projection(item)
                for lane, keep in zip(self.lanes.values(), fresh) if keep
                for item in lane["items"]]
        # Callers may annotate the returned dicts; hand out shallow copies of
        # the cached projection (cheap) instead of re-projecting every tick.
        return [dict(item) for item in self._live_items_cache]

    def close(self):
        self._background_stop.set()
        self._background_wake.set()
        if self._background_thread is not None:
            self._background_thread.join(timeout=2.)
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.world3d.close()
        if self.live_vision_monitor is not None:
            self.live_vision_monitor.close()

    def rates(self, now: float) -> dict:
        return {"world_perception_hz": self.rate_meters["world"].hz(now),
                "world_detector_hz": self.detector_rate.hz(now),
                "world_tracker_hz": self.tracker_rate.hz(now),
                "minimap_perception_hz": self.rate_meters["minimap"].hz(now),
                **self.scheduler.rates(now)}

    def detector_ready(self, now: float) -> bool:
        """A configured learned detector has produced World3D refreshes."""
        if getattr(self.world3d.v2, "learned_detector", None) is None:
            return True
        if self.detector_rate.hz(now) > 0:
            self._detector_seen = True
        return bool(getattr(self, "_detector_seen", False))

    def ready_for_action(self, now: float) -> bool:
        """True only when the planner has a current world-surface result.

        Candidate count may legitimately be zero; readiness is about a recent
        completed observation, not about forcing a positive detection.
        """
        lane = self.lanes["world"]
        return (lane["status"] == "ready" and bool(lane["at"])
                and 0 <= now-lane["at"] <= self.RESULT_TTL_SECONDS)
