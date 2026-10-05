"""BoT-SORT camera-motion compensation from the precomputed quarter-resolution gray frame.

Split out of tracking.py (2026-10-05); unchanged and re-exported there.
"""
from __future__ import annotations
from typing import Any
try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:  # pragma: no cover - installed package path
    from adapters.numpy_runtime import np


class _PrescaledTranslationGMC:
    """BoT-SORT global motion from the World3D quarter-resolution gray.

    Live 2026-09-30, with the capture-driven YOLO feed refreshing every frame:
    Ultralytics' sparse-optical-flow GMC cost 12.5 ms of a 19 ms refresh
    (full-frame BGR->gray of a strided view plus 400-corner Lucas-Kanade).
    V2 has already reduced the same anchor frame to a quarter-resolution
    luminance image, so a sub-pixel phase correlation on it gives the global
    camera translation for ~1 ms (synthetic shifts: p90 error 2.5 px).  A
    frame without that gray, or a weak correlation peak, uses the original
    Ultralytics estimator / identity exactly as before.

    Live 2026-09-30 (feed trace, PID 3324): during camera turns detections
    moved 20-100 px per frame while this estimator reported ~1 px, so every
    turn frame spawned fresh track ids and the old boxes coasted in place.
    The estimate now comes from ``camera_motion.WorldCameraMotion`` (two world
    crops beside the avatar).  Among its hypotheses (similarity, mean, either
    crop, identity) the one mapping the most previous high-score detections
    onto the current ones wins; BoT-SORT applies the resulting similarity
    warp to tracked *and* lost tracks.
    """

    def __init__(self, fallback: Any, *, min_response: float = .1) -> None:
        from .camera_motion import WorldCameraMotion
        self.fallback = fallback
        self.motion = WorldCameraMotion(min_response=min_response)
        self._pending: tuple[Any, int] | None = None
        self._previous: Any | None = None
        self._previous_boxes: Any = None
        self._fallback_active = False
        self.last_response: float | None = None
        # Shift at the image centre in client pixels (trace/diagnostics).
        self.last_warp: tuple[float, float] | None = None
        self.last_scale: float | None = None
        self.last_hypothesis: str | None = None
        self.last_detection_support: int | None = None

    @property
    def method(self):
        return self.fallback.method

    @property
    def downscale(self):
        return self.fallback.downscale

    @downscale.setter
    def downscale(self, value) -> None:
        self.fallback.downscale = value

    def set_frame(self, gray: Any, step: int) -> None:
        self._pending = (gray, max(1, int(step)))

    def reset_params(self) -> None:
        self._pending = self._previous = self._previous_boxes = None
        self._fallback_active = False
        self.fallback.reset_params()

    def apply(self, raw_frame: Any, detections: Any = None) -> Any:
        pending, self._pending = self._pending, None
        if pending is None:
            # Keep the fallback's previous frame coherent across mode switches.
            self._previous = self._previous_boxes = None
            if not self._fallback_active:
                self.fallback.reset_params()
                self._fallback_active = True
            return self.fallback.apply(raw_frame, detections)
        if self._fallback_active:
            self.fallback.reset_params()
            self._fallback_active = False
        from .camera_motion import select_by_detections
        gray, step = pending
        current = np.ascontiguousarray(gray, dtype=np.float32)
        boxes = None if detections is None else np.asarray(detections, dtype=np.float64).reshape(-1, 4)
        previous, self._previous = self._previous, current
        previous_boxes, self._previous_boxes = self._previous_boxes, boxes
        self.last_response = self.last_warp = self.last_scale = None
        self.last_hypothesis = self.last_detection_support = None
        if previous is None or previous.shape != current.shape or min(current.shape) < 16:
            return np.eye(2, 3)
        hypotheses = self.motion.hypotheses(previous, current)
        try:
            chosen, support = select_by_detections(hypotheses, previous_boxes, boxes, step)
        except Exception:  # noqa: BLE001 -- keep the image estimate, never identity
            chosen, support = hypotheses[0], -1
        responses = [crop[2] for crop in self.motion.last_crops if crop is not None]
        self.last_response = max(responses) if responses else None
        self.last_hypothesis, self.last_detection_support = chosen.name, support
        self.last_scale = float(chosen.scale)
        height, width = current.shape
        cx, cy = chosen.shift_at(width/2, height/2)
        self.last_warp = (float(cx*step), float(cy*step))
        return chosen.warp(step)
