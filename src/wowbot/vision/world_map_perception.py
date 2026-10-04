"""World-map state and evidence-resolution components."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from .adapters.world_map import detect_world_map


class WorldMapStateDetector:
    @staticmethod
    def detect(*, geometry: dict, observation=None) -> dict[str, Any]:
        return {"is_open": bool(geometry.get("world_map_open")),
                "map_context": geometry.get("map_context") or geometry.get("ui_map_id"),
                "zoom_level": geometry.get("map_zoom_level"),
                "player_marker": getattr(observation, "player_marker", None),
                "markers": tuple(getattr(observation, "markers", ()))}


_DEFAULT = object()


class WorldMapMarkerDetector:
    """Heuristic World Map detector, optionally refined by a learned model.

    The learned adapter (``map_markers.LearnedMapMarkerDetector``) is used
    only once its model is ready; until then, and whenever no model artifact
    is selected, the heuristic observation is returned unchanged.
    """

    def __init__(self, learned=_DEFAULT) -> None:
        self._learned = learned

    @property
    def learned(self):
        if self._learned is _DEFAULT:
            from .map_markers import get_learned_map_detector
            self._learned = get_learned_map_detector("WORLD_MAP")
        return self._learned

    def detect(self, frame, observed_at: float, geometry: dict):
        raw, width, height = frame
        observation = detect_world_map(raw, width, height,
                                       zone=geometry.get("map_context"), observed_at=observed_at)
        learned = self.learned
        if learned is None or learned.status != "ready":
            return observation
        from .map_markers import bgra_view, merge_world_map_markers, world_map_crop
        pixels = bgra_view(raw, width, height)
        crop, _, _ = world_map_crop(pixels, width, height)
        if crop.width < 16 or crop.height < 16:
            return observation
        bgr = np.ascontiguousarray(pixels[crop.top:crop.bottom, crop.left:crop.right, :3])
        markers, player = learned.detect(bgr, offset=(crop.left, crop.top))
        return replace(observation,
                       player_marker=player or observation.player_marker,
                       markers=tuple(merge_world_map_markers(markers, observation.markers)))


class MapContextResolver:
    @staticmethod
    def resolve(geometry: dict, telemetry: dict | None = None) -> dict[str, Any]:
        telemetry = telemetry or {}
        return {"ui_map_id": telemetry.get("ui_map_id", geometry.get("ui_map_id")),
                "instance_id": telemetry.get("instance_id", geometry.get("instance_id")),
                "zone": telemetry.get("zone", geometry.get("map_context")),
                "confidence": .95 if telemetry else .55}


class MapMouseoverResolver:
    @staticmethod
    def resolve(payload: dict | None) -> dict | None:
        if not payload:
            return None
        return {key: payload.get(key) for key in
                ("name", "quest_id", "npc_id", "ui_map_id", "map_x", "map_y", "observed_at")
                if payload.get(key) is not None}


class WorldMapResolver:
    def __init__(self, detector: WorldMapMarkerDetector | None = None) -> None:
        self.detector = detector or WorldMapMarkerDetector()

    def process(self, frame, observed_at: float, geometry: dict):
        return self.detector.detect(frame, observed_at, geometry)

    @staticmethod
    def open_map_request() -> dict[str, Any]:
        return {"operation": "OPEN_WORLD_MAP", "surface": "WORLD_MAP",
                "input_dispatched": False}

    @staticmethod
    def close_map_request() -> dict[str, Any]:
        return {"operation": "CLOSE_WORLD_MAP", "surface": "WORLD_MAP",
                "input_dispatched": False}

    @staticmethod
    def resolve_context(geometry: dict, telemetry: dict | None = None) -> dict[str, Any]:
        return MapContextResolver.resolve(geometry, telemetry)

    @staticmethod
    def select_best_map_evidence(markers) -> Any | None:
        def confidence(marker):
            return float(marker.get("confidence", 0) if isinstance(marker, dict)
                         else getattr(marker, "confidence", 0))
        return max(markers, key=confidence, default=None)

    def find_quest_location(self, markers, quest=None):
        return self.select_best_map_evidence(markers)

    def find_turnin_location(self, markers, quest=None):
        return self.select_best_map_evidence(markers)

    def find_parent_zone_location(self, markers, parent_map_id=None):
        matching = [marker for marker in markers
                    if parent_map_id is None or
                    (marker.get("parent_map_id") if isinstance(marker, dict) else
                     getattr(marker, "parent_map_id", None)) == parent_map_id]
        return self.select_best_map_evidence(matching)

    @staticmethod
    def resolve_wrong_zoom(state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("is_open") or state.get("expected_marker_visible"):
            return None
        if state.get("parent_map") is not None:
            return {"operation": "STEP_TO_PARENT_MAP", "target_map": state["parent_map"],
                    "input_dispatched": False}
        return {"operation": "ZOOM_IN_BOUNDED", "max_steps": 5,
                "input_dispatched": False}

    @staticmethod
    def resolve_map_mouseover(payload: dict | None) -> dict | None:
        return MapMouseoverResolver.resolve(payload)
