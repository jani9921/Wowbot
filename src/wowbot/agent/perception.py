"""Reuse M7's candidate detector/tracker; CV labels remain hypotheses."""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
import os
import threading
from wowbot.vision.world3d.tracking import WorldCandidateTracker
from wowbot.vision.world3d.v3 import World3DPerceptionV3
from wowbot.vision.world3d.v4 import HardExampleCollector
from wowbot.vision.world3d.components import WorldSceneExtractor, WorldCandidateDetector, SemanticFusion
from wowbot.vision.world3d.pipeline import World3DPipeline
from .visual_tracks import VisualTrackManager
from .runtime_scheduler import RateMeter, RuntimeCadenceScheduler
from .perception_pipeline import PerceptionPipeline
from wowbot.vision.minimap_perception import MinimapTracker, MinimapResolver
from wowbot.vision.world_map_perception import (
    MapContextResolver, MapMouseoverResolver, WorldMapResolver, WorldMapStateDetector,
)
from .perception_background import PerceptionBackgroundMixin
from .perception_context import PerceptionContextMixin
from .perception_sources import PerceptionSourcesMixin, _minimap_marker_payload  # noqa: F401  (re-exported)
from .perception_cycle import PerceptionCycleMixin



class PerceptionWorker(PerceptionCycleMixin, PerceptionSourcesMixin, PerceptionContextMixin, PerceptionBackgroundMixin):
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

    _CONTEXT_PARTS = ("session_id", "character_guid", "map_id", "map_zoom_count")

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
