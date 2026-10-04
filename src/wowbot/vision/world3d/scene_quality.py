"""Stateful World3D scene-change and visual-condition evidence.

This module measures pixels only.  It cannot recognize an NPC, declare a
teleport, invalidate the WorldModel, or issue input.  Consumers may use its
bounded observations to downweight unreliable visual evidence or request a
supervisor-level context refresh.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

try:  # repository and installed-package execution
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:  # pragma: no cover
    import numpy as np

from .models import WorldSceneROI


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True, slots=True)
class SceneConditionObservation:
    brightness: float
    contrast: float
    motion_blur_estimate: float
    ui_occlusion_fraction: float
    scene_visibility_quality: float
    confidence_multiplier: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "brightness": round(self.brightness, 4),
            "contrast": round(self.contrast, 4),
            "motion_blur_estimate": round(self.motion_blur_estimate, 4),
            "ui_occlusion_fraction": round(self.ui_occlusion_fraction, 4),
            "scene_visibility_quality": round(self.scene_visibility_quality, 4),
            "confidence_multiplier": round(self.confidence_multiplier, 4),
            "source": "WORLD3D_PIXEL_CONDITIONS",
            "fact": False,
        }


class SceneQualityAnalyzer:
    """Compute bounded diagnostics and detect large visual discontinuities."""

    def __init__(self, *, scene_change_threshold: float = .34) -> None:
        self.scene_change_threshold = _clamp(scene_change_threshold)
        self._previous_sample = None
        self._previous_shape: tuple[int, int] | None = None

    def reset(self) -> None:
        self._previous_sample = None
        self._previous_shape = None

    def observe(self, frame: tuple[bytes, int, int] | None, scene: WorldSceneROI,
                *, observed_at: float, camera_state: dict[str, Any] | None = None
                ) -> tuple[SceneConditionObservation, dict[str, Any] | None]:
        patch = self._patch(frame, scene)
        occlusion = self._ui_occlusion_fraction(scene)
        if patch is None or not patch.size:
            quality = SceneConditionObservation(0., 0., 1., occlusion, 0., .20)
            return quality, None

        gray = (patch[:, :, 0].astype(np.float32)*.114
                + patch[:, :, 1].astype(np.float32)*.587
                + patch[:, :, 2].astype(np.float32)*.299)
        brightness = _clamp(float(np.mean(gray))/255.)
        contrast = _clamp(float(np.std(gray))/72.)
        # Mean first derivative is a stable CPU-cheap sharpness proxy.  Low
        # local gradient means likely blur/feature poverty, not a semantic
        # statement about the scene.
        gx = float(np.mean(np.abs(np.diff(gray, axis=1)))) if gray.shape[1] > 1 else 0.
        gy = float(np.mean(np.abs(np.diff(gray, axis=0)))) if gray.shape[0] > 1 else 0.
        sharpness = _clamp((gx+gy)/36.)
        motion_blur = _clamp(1.-sharpness)
        exposure = _clamp(min(brightness/.18 if brightness else 0.,
                              (1.-brightness)/.12 if brightness < 1. else 0.))
        visibility = _clamp(.30*exposure + .34*contrast + .26*sharpness
                            + .10*(1.-occlusion))
        # Never erase visual evidence solely because quality is poor; make
        # the penalty explicit and leave final fusion to the WorldModel.
        multiplier = .20 + .80*visibility
        condition = SceneConditionObservation(
            brightness, contrast, motion_blur, occlusion, visibility, multiplier)

        sample = self._sample(gray)
        scene_change = None
        if self._previous_sample is not None:
            if self._previous_shape != sample.shape:
                scene_change = self._event(observed_at, 1., "VIEWPORT_GEOMETRY_CHANGED",
                                           camera_state)
            else:
                delta = _clamp(float(np.mean(np.abs(sample-self._previous_sample)))/255.)
                if delta >= self.scene_change_threshold:
                    scene_change = self._event(observed_at, delta, "LARGE_PIXEL_DELTA",
                                               camera_state)
        self._previous_sample = sample
        self._previous_shape = sample.shape
        return condition, scene_change

    @staticmethod
    def _patch(frame: tuple[bytes, int, int] | None, scene: WorldSceneROI):
        if not frame:
            return None
        raw, width, height = frame
        if width < 1 or height < 1 or len(raw) != width*height*4:
            return None
        array = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
        rect = scene.rect
        return array[max(0, rect.top):min(height, rect.bottom),
                     max(0, rect.left):min(width, rect.right), :3]

    @staticmethod
    def _sample(gray):
        sy = max(1, int(math.ceil(gray.shape[0]/64)))
        sx = max(1, int(math.ceil(gray.shape[1]/64)))
        return gray[::sy, ::sx].copy()

    @staticmethod
    def _ui_occlusion_fraction(scene: WorldSceneROI) -> float:
        roi = scene.rect
        area = max(1, roi.width*roi.height)
        covered = 0
        for excluded in scene.excluded_rects:
            width = max(0, min(roi.right, excluded.right)-max(roi.left, excluded.left))
            height = max(0, min(roi.bottom, excluded.bottom)-max(roi.top, excluded.top))
            covered += width*height
        return _clamp(covered/area)

    @staticmethod
    def _event(observed_at: float, magnitude: float, reason: str,
               camera_state: dict[str, Any] | None) -> dict[str, Any]:
        camera_state = camera_state or {}
        return {
            "event_type": "SCENE_CHANGE_OBSERVED",
            "timestamp_monotonic": float(observed_at),
            "reason": reason,
            "change_magnitude": round(_clamp(magnitude), 4),
            "camera_state": camera_state.get("state", "UNKNOWN"),
            "camera_motion_confidence": _clamp(camera_state.get("confidence", 0.) or 0.),
            "suggested_effect": "CONTEXT_INVALIDATION_CANDIDATE",
            "source": "WORLD3D_SCENE_CHANGE_DETECTOR",
            "fact": False,
        }

