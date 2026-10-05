"""Learned World Map / minimap marker vocabulary, crops and adapter.

One shared module for both map surfaces:

* the YOLO class table and the *appearance* labels each class publishes,
* crop geometry (World Map canvas, minimap square) shared by the dataset
  collector, the review/export tools and runtime inference,
* weak review proposals derived from addon facts (projected quest POIs,
  waypoints, map mouseover) and from the existing heuristic detectors,
* :class:`LearnedMapMarkerDetector`, the optional runtime adapter.

Learned output is appearance evidence only, exactly like World3D: a box of
class ``quest_available`` becomes an UNKNOWN map marker carrying the
``quest_available_like`` candidate label.  Quest semantics still require the
addon (map mouseover tooltip, quest log, POI API).  Without a model file the
adapter is absent and the heuristic detectors behave exactly as before.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import threading
from typing import Any, Iterable, Sequence

import numpy as np

from .models import MapPoint, MarkerObservation
from .world_map_calibration import (WorldMapCalibration, estimate_world_map_canvas,
                                    legacy_world_map_rect)


MAP_MARKER_YOLO_CLASSES: tuple[str, ...] = (
    "quest_available",             # yellow "!" quest offer
    "quest_available_repeatable",  # blue "!" daily / weekly offer
    "quest_available_special",     # campaign / important / legendary "!" variants
    "quest_turn_in",               # yellow "?" turn-in
    "quest_turn_in_repeatable",    # blue "?" turn-in
    "quest_objective_pin",         # active-quest POI / super-tracked pin
    "quest_area",                  # blue (hatched) objective region
    "quest_edge_arrow",            # minimap rim arrow toward a tracked objective
    "player_arrow",                # the player's own arrow
    # Minimap objective dots and their floor (user 2026-10-05, Hrun's pit).
    # Appended so existing label files keep their class ids.
    "objective_dot_same_space",    # yellow dot: in the same space (cave/building/floor) as us
    "objective_dot_other_space",   # grey dot: inside a space we are not in
    "objective_dot_below",         # grey dot with a down arrow: lower than us
    "objective_dot_above",         # grey dot with an up arrow: higher than us
)
MAP_MARKER_CLASS_TITLES: tuple[str, ...] = (
    "Quest offer ! (yellow)",
    "Repeatable offer ! (blue)",
    "Campaign/important !",
    "Turn-in ? (yellow)",
    "Repeatable turn-in ? (blue)",
    "Active quest pin / POI",
    "Quest area (blue region)",
    "Minimap edge arrow",
    "Player arrow",
    "Objective dot, same space (yellow)",
    "Objective dot, other space (grey)",
    "Objective dot below (grey, down arrow)",
    "Objective dot above (grey, up arrow)",
)
QUEST_MARKER_CLASSES = frozenset(name for name in MAP_MARKER_YOLO_CLASSES if name != "player_arrow")

# Appearance labels consumed by existing planners.  ``blue_region_like`` keeps
# QuestLocationPlanner's search-region seeding working for learned areas,
# ``*_symbol_like`` matches the heuristic minimap vocabulary.
CLASS_APPEARANCE_LABELS: dict[str, tuple[str, ...]] = {
    "quest_available": ("quest_available_like", "exclamation_symbol_like"),
    "quest_available_repeatable": ("quest_available_like", "repeatable_like",
                                   "exclamation_symbol_like"),
    "quest_available_special": ("quest_available_like", "campaign_like",
                                "exclamation_symbol_like"),
    "quest_turn_in": ("quest_turn_in_like", "question_symbol_like"),
    "quest_turn_in_repeatable": ("quest_turn_in_like", "repeatable_like",
                                 "question_symbol_like"),
    "quest_objective_pin": ("quest_objective_pin_like",),
    "quest_area": ("quest_area_like", "blue_region_like"),
    "quest_edge_arrow": ("quest_edge_arrow_like", "direction_arrow_like"),
    "player_arrow": ("player_arrow_like",),
    "objective_dot_same_space": ("quest_objective_dot_like", "same_space_like"),
    "objective_dot_other_space": ("quest_objective_dot_like", "other_space_like"),
    "objective_dot_below": ("quest_objective_dot_like", "other_space_like", "objective_below_like"),
    "objective_dot_above": ("quest_objective_dot_like", "other_space_like", "objective_above_like"),
}

SURFACES = ("WORLD_MAP", "MINIMAP")
DEFAULT_MODEL_NAMES = {"WORLD_MAP": "world_map_markers.pt", "MINIMAP": "minimap_markers.pt"}
MODEL_ENV = {"WORLD_MAP": "AIPC_WORLD_MAP_MODEL", "MINIMAP": "AIPC_MINIMAP_MODEL"}


@dataclass(frozen=True, slots=True)
class CropRect:
    left: int
    top: int
    right: int
    bottom: int
    source: str

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def to_dict(self) -> dict:
        return {"left": self.left, "top": self.top, "right": self.right,
                "bottom": self.bottom, "source": self.source,
                "coordinate_space": "CLIENT_PIXELS"}


def world_map_crop(pixels, width: int, height: int) -> tuple[CropRect, WorldMapCalibration, bool]:
    """Crop rectangle for a World Map frame plus the canvas calibration.

    Returns ``(crop, canvas, estimated)``.  ``estimated`` is False when the
    full-screen canvas estimator did not recognise the layout and the legacy
    constant frame was used (projections are then unverified).
    """
    canvas = estimate_world_map_canvas(pixels)
    estimated = canvas is not None
    if canvas is None:
        canvas = legacy_world_map_rect(width, height)
    crop = CropRect(max(0, canvas.left_px), max(0, canvas.top_px),
                    min(width, canvas.right_px), min(height, canvas.bottom_px),
                    "CANVAS_ESTIMATE" if estimated else "LEGACY_CONSTANTS")
    return crop, canvas, estimated


def minimap_crop(geometry: dict | None, width: int, height: int,
                 *, padding: int = 8) -> CropRect | None:
    """Square crop around the addon-reported minimap disc (client pixels)."""
    geometry = geometry or {}
    try:
        cx = float(geometry["center_x"]) * width
        cy = float(geometry["center_y"]) * height
        radius = float(geometry["radius_fraction"]) * height
    except (KeyError, TypeError, ValueError):
        return None
    if not geometry.get("visible", True) or not (0 < cx < width and 0 < cy < height):
        return None
    if not 4 <= radius <= height * .3:
        return None
    left, top = max(0, math.floor(cx - radius - padding)), max(0, math.floor(cy - radius - padding))
    right = min(width, math.ceil(cx + radius + padding + 1))
    bottom = min(height, math.ceil(cy + radius + padding + 1))
    if right - left < 16 or bottom - top < 16:
        return None
    return CropRect(left, top, right, bottom, "ADDON_MINIMAP_GEOMETRY")


def bgra_view(raw: bytes, width: int, height: int):
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)


def default_marker_size(surface: str, crop: CropRect) -> int:
    """Typical icon box edge in crop pixels, used only for review proposals."""
    if surface == "MINIMAP":
        return max(8, round(crop.width * .085))
    return max(10, round(crop.width * .022))


def _box(center_x: float, center_y: float, size: float, crop: CropRect) -> dict | None:
    half = size / 2
    left, top = max(0, round(center_x - half)), max(0, round(center_y - half))
    right, bottom = min(crop.width, round(center_x + half)), min(crop.height, round(center_y + half))
    if right - left < 3 or bottom - top < 3:
        return None
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _proposal(class_name: str, box: dict | None, confidence: float, source: str,
              **extra) -> dict | None:
    if box is None:
        return None
    return {"class_id": MAP_MARKER_YOLO_CLASSES.index(class_name), "class_name": class_name,
            **box, "confidence": round(float(confidence), 4), "status": "PROPOSED",
            "source": source, **extra}


def world_map_proposals(*, crop: CropRect, canvas: WorldMapCalibration, canvas_estimated: bool,
                        state: dict, player_pixel: MapPoint | None,
                        heuristic_markers: Iterable[MarkerObservation] = (),
                        cursor_pixel: tuple[float, float] | None = None,
                        tolerance_px: float | None = None) -> tuple[list[dict], dict]:
    """Weak review proposals for one World Map crop (crop-relative pixels).

    Addon POIs are projected through the canvas only when the projection is
    *verified*: the addon player position, projected the same way, lands on
    the visually detected player arrow.  That check rejects zoomed/panned
    maps and non-full-screen layouts without any extra client facts.
    """
    size = default_marker_size("WORLD_MAP", crop)
    tolerance = tolerance_px if tolerance_px is not None else max(4., size * .6)
    proposals: list[dict] = []
    displayed = state.get("displayed_map_id") or state.get("map_id")
    position = state.get("position") or {}
    verification = {"canvas_estimated": canvas_estimated, "projection_verified": False,
                    "player_error_px": None, "displayed_map_id": displayed}
    px, py = position.get("x"), position.get("y")
    if canvas_estimated and player_pixel is not None and isinstance(px, (int, float)) \
            and isinstance(py, (int, float)):
        ex, ey = canvas.map_to_pixel(float(px), float(py))
        error = math.hypot(ex - player_pixel.x, ey - player_pixel.y)
        verification["player_error_px"] = round(error, 2)
        verification["projection_verified"] = error <= tolerance
    if player_pixel is not None:
        proposals.append(_proposal("player_arrow", _box(player_pixel.x - crop.left,
                                                        player_pixel.y - crop.top, size, crop),
                                   .9, "HEURISTIC_PLAYER_ARROW"))
    if verification["projection_verified"]:
        quests = {str(q.get("quest_id")): q for q in state.get("quests") or []
                  if isinstance(q, dict)}
        for location in state.get("quest_locations") or []:
            if not isinstance(location, dict):
                continue
            x, y = location.get("x"), location.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            if displayed is not None and location.get("map_id") not in (None, displayed):
                continue
            quest = quests.get(str(location.get("quest_id"))) or {}
            # A ready-for-turn-in quest's POI is its turn-in pin; otherwise
            # it is the active objective pin/area.
            name = "quest_turn_in" if quest.get("is_complete") else "quest_objective_pin"
            cx, cy = canvas.map_to_pixel(float(x), float(y))
            proposals.append(_proposal(name, _box(cx - crop.left, cy - crop.top, size, crop), .6,
                                       "ADDON_QUEST_POI_PROJECTED",
                                       quest_id=location.get("quest_id"),
                                       poi_source=location.get("source")))
        for quest in quests.values():
            waypoint = quest.get("waypoint") or {}
            x, y = waypoint.get("x"), waypoint.get("y")
            if (not isinstance(x, (int, float)) or not isinstance(y, (int, float))
                    or waypoint.get("map_id") not in (None, displayed)):
                continue
            cx, cy = canvas.map_to_pixel(float(x), float(y))
            proposals.append(_proposal("quest_objective_pin",
                                       _box(cx - crop.left, cy - crop.top, size, crop), .5,
                                       "ADDON_QUEST_WAYPOINT_PROJECTED",
                                       quest_id=quest.get("quest_id")))
    mouseover = state.get("map_mouseover") or {}
    if (cursor_pixel is not None and mouseover.get("surface") == "WORLD_MAP"
            and mouseover.get("semantic_type") in {"QUEST_GIVER", "QUEST_TURN_IN", "QUEST_RELATED"}):
        name = {"QUEST_GIVER": "quest_available", "QUEST_TURN_IN": "quest_turn_in",
                "QUEST_RELATED": "quest_objective_pin"}[mouseover["semantic_type"]]
        proposals.append(_proposal(name, _box(cursor_pixel[0] - crop.left,
                                              cursor_pixel[1] - crop.top, size, crop),
                                   .7, "ADDON_MAP_MOUSEOVER_TOOLTIP",
                                   tooltip=str(mouseover.get("tooltip") or "")[:160]))
    for marker in heuristic_markers:
        if "blue_region_like" in (marker.candidate_labels or ()) and marker.bbox:
            left, top, right, bottom = marker.bbox
            box = {"left": max(0, left - crop.left), "top": max(0, top - crop.top),
                   "right": min(crop.width, right - crop.left),
                   "bottom": min(crop.height, bottom - crop.top)}
            if box["right"] - box["left"] >= 4 and box["bottom"] - box["top"] >= 4:
                proposals.append(_proposal("quest_area", box, marker.confidence * .5,
                                           "HEURISTIC_BLUE_REGION"))
    return [item for item in proposals if item is not None], verification


def minimap_proposals(*, crop: CropRect, markers: Iterable[MarkerObservation]) -> list[dict]:
    """Review proposals from the heuristic minimap detector (crop pixels)."""
    size = default_marker_size("MINIMAP", crop)
    mapping = (("exclamation_symbol_like", "quest_available"),
               ("question_symbol_like", "quest_turn_in"),
               ("gold_direction_like", "quest_edge_arrow"),
               ("blue_region_like", "quest_area"))
    result = []
    for marker in markers:
        labels = set(marker.candidate_labels or ())
        name = next((cls for label, cls in mapping if label in labels), None)
        if name is None:
            continue
        if marker.bbox and name == "quest_area":
            left, top, right, bottom = marker.bbox
            box = {"left": max(0, left), "top": max(0, top),
                   "right": min(crop.width, right), "bottom": min(crop.height, bottom)}
        else:
            box = _box(marker.position.x, marker.position.y, size, crop)
        result.append(_proposal(name, box, marker.confidence * .6,
                                "HEURISTIC_MINIMAP_" + sorted(labels)[0].upper()))
    return [item for item in result if item is not None]


def fast_world_map_hints(bgr_crop, *, reference_width: float = 665.
                         ) -> tuple[MapPoint | None, list[MarkerObservation]]:
    """OpenCV version of the heuristic player-arrow / blue-area rules.

    The pure-Python component labelling in ``adapters.world_map`` can hold the
    GIL for hundreds of ms on a full-resolution map; dataset collection runs
    beside the live agent, so it uses native connected components instead.
    Thresholds follow the adapter; size limits scale with the canvas width
    (the adapter limits were tuned on ~665 px wide canvases).
    """
    import cv2
    crop = np.asarray(bgr_crop)
    if crop.ndim != 3 or crop.shape[0] < 8 or crop.shape[1] < 8:
        return None, []
    blue, green, red = (crop[:, :, index].astype(np.int16) for index in range(3))
    spread = np.maximum(np.maximum(red, green), blue) - np.minimum(np.minimum(red, green), blue)
    white = ((red > 175) & (green > 175) & (blue > 165) & (spread < 65)).astype(np.uint8)
    scale = max(.5, crop.shape[1] / reference_width)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(white, connectivity=8)
    player, best = None, 0
    for index in range(1, count):
        _, _, box_w, box_h, area = (int(value) for value in stats[index])
        if (2 <= box_w <= 20 * scale and 3 <= box_h <= 28 * scale
                and 3 <= area <= 150 * scale * scale and area > best):
            best = area
            player = MapPoint(round(float(centroids[index][0])), round(float(centroids[index][1])))
    blue_mask = ((blue > 85) & (blue * 100 > red * 118) & (blue * 100 > green * 108)
                 & (blue - red > 22)).astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(blue_mask, connectivity=8)
    frame_area = crop.shape[0] * crop.shape[1]
    areas = []
    for index in range(1, count):
        left, top, box_w, box_h, area = (int(value) for value in stats[index])
        if area < max(40, int(frame_area * .00035)) or box_w < 8 or box_h < 8:
            continue
        if box_w * box_h > frame_area * .35 or area / max(1, box_w * box_h) < .10:
            continue
        areas.append(MarkerObservation(
            "unknown_world_map_area",
            MapPoint(round(float(centroids[index][0])), round(float(centroids[index][1]))),
            min(.92, .48 + min(.30, area / frame_area * 8.)),
            candidate_labels=("blue_region_like",),
            evidence=("appearance_only", "blue_region_like", "area_geometry"),
            bbox=(left, top, left + box_w, top + box_h)))
    areas.sort(key=lambda marker: marker.confidence, reverse=True)
    return player, areas[:4]


def map_yolo_line(class_id: int, left: float, top: float, right: float, bottom: float,
                  width: int, height: int) -> str:
    if not 0 <= class_id < len(MAP_MARKER_YOLO_CLASSES):
        raise ValueError("invalid class id")
    left, right = max(0., min(width, left)), max(0., min(width, right))
    top, bottom = max(0., min(height, top)), max(0., min(height, bottom))
    if width < 1 or height < 1 or right - left < 1 or bottom - top < 1:
        raise ValueError("invalid image or box dimensions")
    return (f"{class_id} {(left + right) / (2. * width):.6f} {(top + bottom) / (2. * height):.6f} "
            f"{(right - left) / width:.6f} {(bottom - top) / height:.6f}")


class LearnedMapMarkerDetector:
    """Runtime adapter: crop -> UNKNOWN map markers with appearance labels.

    ``backend`` follows world3d.learned_detector.LearnedDetectorBackend (any
    object with ``predict(bgr, confidence=, iou=)``).  Detections whose label
    is not in the map vocabulary are ignored instead of guessed.
    """

    def __init__(self, backend, *, surface: str, confidence: float = .35,
                 iou: float = .45, max_markers: int = 24) -> None:
        if surface not in SURFACES:
            raise ValueError(surface)
        self.backend = backend
        self.surface = surface
        self.confidence = float(confidence)
        self.iou = float(iou)
        self.max_markers = max(1, int(max_markers))
        self.last_error: str | None = None

    @property
    def status(self) -> str:
        return str(getattr(self.backend, "status", "ready"))

    def detect(self, bgr_crop, *, offset: tuple[int, int] = (0, 0)
               ) -> tuple[list[MarkerObservation], MapPoint | None]:
        try:
            detections = self.backend.predict(bgr_crop, confidence=self.confidence, iou=self.iou)
        except Exception as error:  # learned evidence is optional
            self.last_error = f"{type(error).__name__}:{error}"
            return [], None
        ox, oy = offset
        markers: list[MarkerObservation] = []
        player: tuple[float, MapPoint] | None = None
        for detection in detections:
            label = str(detection.label)
            if label not in CLASS_APPEARANCE_LABELS:
                continue
            left, top = round(detection.left) + ox, round(detection.top) + oy
            right, bottom = round(detection.right) + ox, round(detection.bottom) + oy
            center = MapPoint(round((left + right) / 2), round((top + bottom) / 2))
            confidence = max(0., min(1., float(detection.confidence)))
            if label == "player_arrow":
                if player is None or confidence > player[0]:
                    player = (confidence, center)
                continue
            if self.surface == "MINIMAP":
                marker_type = "unknown_minimap_marker"
            else:
                marker_type = ("unknown_world_map_area" if label == "quest_area"
                               else "unknown_world_map_marker")
            appearance = CLASS_APPEARANCE_LABELS[label]
            markers.append(MarkerObservation(
                marker_type, center, confidence,
                marker_color=("blue" if "repeatable" in label else "yellow"
                              if label.startswith("quest_available") or label.startswith("quest_turn_in")
                              else None),
                candidate_labels=appearance + ("learned_map_marker_like",),
                evidence=("appearance_only", "learned_detector", appearance[0]),
                bbox=(left, top, right, bottom)))
        markers.sort(key=lambda marker: marker.confidence, reverse=True)
        return markers[:self.max_markers], (player[1] if player else None)


def merge_world_map_markers(learned: Sequence[MarkerObservation],
                            heuristic: Sequence[MarkerObservation]) -> list[MarkerObservation]:
    """Learned markers replace the noisy gold-glyph blobs.

    Heuristic blue areas are kept unless a learned area already covers their
    centre, so QuestLocationPlanner keeps its proven region source.
    """
    areas = [marker for marker in learned if marker.marker_type == "unknown_world_map_area"
             and marker.bbox]
    kept = []
    for marker in heuristic:
        if "blue_region_like" not in (marker.candidate_labels or ()):
            continue
        if any(a.bbox[0] <= marker.position.x <= a.bbox[2] and a.bbox[1] <= marker.position.y <= a.bbox[3]
               for a in areas):
            continue
        kept.append(marker)
    return [*learned, *kept]


def merge_minimap_markers(learned: Sequence[MarkerObservation],
                          heuristic: Sequence[MarkerObservation],
                          *, radius_px: float = 5.) -> list[MarkerObservation]:
    """Keep proven heuristic minimap markers; learned duplicates are dropped."""
    result = list(heuristic)
    for marker in learned:
        if any(math.hypot(marker.position.x - other.position.x,
                          marker.position.y - other.position.y) <= radius_px
               for other in heuristic):
            continue
        result.append(marker)
    return result


def _models_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "models"


def runtime_model_path(surface: str) -> Path | None:
    """Explicit env path wins; otherwise the default artifact when present."""
    if os.environ.get("AIPC_MAP_MARKER_MODEL", "1").strip().lower() in {"0", "false", "no", "off"}:
        return None
    configured = os.environ.get(MODEL_ENV[surface], "").strip()
    if configured:
        return Path(configured).expanduser()
    path = _models_dir() / DEFAULT_MODEL_NAMES[surface]
    return path if path.is_file() else None


_DETECTORS: dict[str, LearnedMapMarkerDetector | None] = {}
_DETECTOR_ERRORS: dict[str, str] = {}
_LOCK = threading.Lock()


def get_learned_map_detector(surface: str) -> LearnedMapMarkerDetector | None:
    """Process-wide lazily built detector, or None when no model is selected."""
    with _LOCK:
        if surface in _DETECTORS:
            return _DETECTORS[surface]
        detector = None
        path = runtime_model_path(surface)
        if path is not None:
            try:
                from .world3d.learned_detector import UltralyticsYoloBackend
                device_env = os.environ.get("AIPC_MAP_MARKER_MODEL_DEVICE", "auto").strip().lower()
                device: Any = int(device_env) if device_env.isdigit() else device_env
                backend = UltralyticsYoloBackend(
                    path, device=device,
                    image_size=int(os.environ.get(
                        "AIPC_WORLD_MAP_MODEL_IMGSZ" if surface == "WORLD_MAP"
                        else "AIPC_MINIMAP_MODEL_IMGSZ", "960" if surface == "WORLD_MAP" else "320")),
                    max_detections=40, warmup_in_background=True)
                detector = LearnedMapMarkerDetector(
                    backend, surface=surface,
                    confidence=float(os.environ.get("AIPC_MAP_MARKER_CONFIDENCE", ".35")))
            except Exception as error:  # surfaced in diagnostics, heuristics keep running
                _DETECTOR_ERRORS[surface] = f"{type(error).__name__}:{error}"
                detector = None
        _DETECTORS[surface] = detector
        return detector


def learned_map_detector_diagnostics() -> dict:
    return {surface: {"model": str(runtime_model_path(surface) or ""),
                      "status": (_DETECTORS[surface].status if _DETECTORS.get(surface)
                                 else "disabled" if surface in _DETECTORS else "not_loaded"),
                      "error": _DETECTOR_ERRORS.get(surface)
                      or (_DETECTORS[surface].last_error if _DETECTORS.get(surface) else None)}
            for surface in SURFACES}


def reset_learned_map_detectors() -> None:
    """Test/diagnostic hook: forget cached detectors."""
    with _LOCK:
        _DETECTORS.clear()
        _DETECTOR_ERRORS.clear()
