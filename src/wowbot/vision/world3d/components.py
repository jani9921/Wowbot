"""Named World3D stage contracts backed by the canonical implementation."""
from __future__ import annotations

from typing import Any

from .scene import build_scene_roi
from .v4 import VisionSemanticFusion


class WorldSceneExtractor:
    def extract(self, frame) -> Any:
        width, height = (frame[1], frame[2]) if isinstance(frame, tuple) else frame
        return build_scene_roi(int(width), int(height))


class WorldCandidateDetector:
    """Adapter around the one configured World3D detector authority."""

    def __init__(self, detector) -> None:
        self.detector = detector

    def detect(self, frame, scene, *, observed_at: float, ui_hints: dict | None = None):
        raw, width, height = frame
        return self.detector.process(raw, width, height, scene,
                                     observed_at=observed_at, ui_hints=ui_hints)


class SemanticFusion(VisionSemanticFusion):
    """Canonical name for evidence-only semantic hypothesis enrichment."""
