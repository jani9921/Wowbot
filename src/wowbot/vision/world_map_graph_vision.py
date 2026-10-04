from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - exercised on minimal installations
    cv2 = None

from .models import DetectedFeature, FeatureType, MapPoint
from .opencv_backend import OpenCvComputeBackend, create_opencv_backend


@dataclass(frozen=True, slots=True)
class WorldMapGraphVisionConfig:
    """Conservative, calibration-first raster settings for a World Map."""
    roi_left: float = 0.045
    roi_top: float = 0.108
    roi_right: float = 0.955
    roi_bottom: float = 0.958
    # Exclude the optional top-left AIPC transport strip if it is present.
    exclude_left: float = 0.0
    exclude_top: float = 0.0
    exclude_right: float = 0.0
    exclude_bottom: float = 0.08
    tutorial_rect: tuple[int, int, int, int] | None = (470, 20, 720, 110)
    min_segment_length: float = 18.0
    max_segment_length: float = 140.0
    min_corridor_contrast: float = 2.0
    min_center_fraction: float = 0.55
    endpoint_cluster_radius: float = 20.0
    intersection_cluster_radius: float = 28.0
    min_intersection_support: int = 3
    max_segments: int = 120
    max_features: int = 160


@dataclass(frozen=True, slots=True)
class CorridorSegment:
    start: MapPoint
    end: MapPoint
    confidence: float
    contrast: float

    @property
    def length(self) -> float:
        return math.hypot(self.end.x - self.start.x, self.end.y - self.start.y)


class WorldMapGraphVision:
    """Turn one World Map raster into conservative corridor/intersection candidates.

    This is intentionally a proposal layer: it produces evidence-backed candidates,
    not an authoritative road network. Graph construction can later merge candidates
    across multiple observations or use addon/map metadata as stronger evidence.
    """

    def __init__(self, config: WorldMapGraphVisionConfig | None = None,
                 *, compute_backend: OpenCvComputeBackend | None = None) -> None:
        self.config = config or WorldMapGraphVisionConfig()
        self.compute_backend = compute_backend if compute_backend is not None else create_opencv_backend()

    @property
    def compute_diagnostics(self) -> dict:
        return (self.compute_backend.diagnostics() if self.compute_backend is not None
                else {"requested": "AUTO", "active": "NUMPY", "reason": "opencv_unavailable"})

    def extract(self, image: np.ndarray) -> tuple[DetectedFeature, ...]:
        rgb = _as_rgb(image)
        if cv2 is None:
            # Keep the graph-vision API usable on the project's declared
            # Pillow+NumPy dependency set. The conservative raster extractor
            # remains a candidate source; it does not claim graph authority.
            from .world_map_raster import WorldMapRasterFeatureExtractor
            return WorldMapRasterFeatureExtractor().extract(rgb)
        crop, origin = _crop(rgb, self.config)
        if crop.size == 0:
            return ()
        mask = self._candidate_line_mask(crop)
        segments = self._detect_segments(crop, mask)
        intersections = self._infer_intersections(segments)
        features: list[DetectedFeature] = []
        for idx, seg in enumerate(segments):
            center = MapPoint((seg.start.x + seg.end.x) / 2 + origin[0], (seg.start.y + seg.end.y) / 2 + origin[1])
            ftype = FeatureType.ROAD if seg.length >= 42 else FeatureType.PATH
            features.append(
                DetectedFeature(
                    ftype,
                    center,
                    min(0.92, max(0.35, seg.confidence)),
                    seg.length,
                    max(2.0, seg.length * 0.08),
                    {
                        "source": "world_map_graph_vision",
                        "candidate": "corridor",
                        "length": f"{seg.length:.1f}",
                        "contrast": f"{seg.contrast:.2f}",
                        "x1": f"{seg.start.x + origin[0]:.1f}",
                        "y1": f"{seg.start.y + origin[1]:.1f}",
                        "x2": f"{seg.end.x + origin[0]:.1f}",
                        "y2": f"{seg.end.y + origin[1]:.1f}",
                    },
                )
            )
            if idx + 1 >= self.config.max_segments:
                break
        for point, support, confidence in intersections:
            features.append(
                DetectedFeature(
                    FeatureType.INTERSECTION,
                    MapPoint(point.x + origin[0], point.y + origin[1]),
                    confidence,
                    metadata={
                        "source": "world_map_graph_vision",
                        "candidate": "junction",
                        "support": str(support),
                    },
                )
            )
        features = _dedupe(features, 16.0)
        features.sort(key=lambda f: (-f.confidence, f.feature_type.value, f.center.y, f.center.x))
        return tuple(features[: self.config.max_features])

    def _candidate_line_mask(self, crop: np.ndarray) -> np.ndarray:
        gray, h, s, v, edges, contrast = self.compute_backend.graph_line_primitives(crop)
        # Keep edges with some local contrast but suppress strongly saturated UI text.
        mask = (edges > 0) & (contrast >= 5) & (v < 235)
        yellow = (h >= 15) & (h <= 40) & (s >= 145) & (v >= 135)
        mask &= ~yellow

        # Keep the optional tutorial popup out of the candidate mask.
        if self.config.tutorial_rect:
            x0, y0, x1, y1 = self.config.tutorial_rect
            mask[max(0, y0):min(mask.shape[0], y1), max(0, x0):min(mask.shape[1], x1)] = False

        # Remove the configurable transport strip exclusion in ROI coordinates.
        hgt, wid = mask.shape
        ex0 = int(np.clip(self.config.exclude_left, 0, 1) * wid)
        ey0 = int(np.clip(self.config.exclude_top, 0, 1) * hgt)
        ex1 = int(np.clip(self.config.exclude_right, 0, 1) * wid)
        ey1 = int(np.clip(self.config.exclude_bottom, 0, 1) * hgt)
        if ex1 > ex0 and ey1 > ey0:
            mask[ey0:ey1, ex0:ex1] = False

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask_u8 = (mask.astype(np.uint8) * 255)
        mask_u8 = self.compute_backend.morphology_close(mask_u8, kernel)
        return mask_u8

    def _detect_segments(self, crop: np.ndarray, mask: np.ndarray) -> list[CorridorSegment]:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
        lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        detected = lsd.detect(mask)[0]
        if detected is None:
            return []
        segments: list[CorridorSegment] = []
        # OpenCV builds return either (N, 1, 4) or (N, 4).  Normalize both;
        # indexing [:, 0] turns the latter into scalars and crashes unpacking.
        for line in np.asarray(detected).reshape(-1, 4):
            x1, y1, x2, y2 = map(float, line)
            length = math.hypot(x2 - x1, y2 - y1)
            if length < self.config.min_segment_length or length > self.config.max_segment_length:
                continue
            angle = math.atan2(y2 - y1, x2 - x1)
            nx, ny = -math.sin(angle), math.cos(angle)
            contrasts: list[float] = []
            for t in np.linspace(0.15, 0.85, 6):
                x = x1 + (x2 - x1) * t
                y = y1 + (y2 - y1) * t
                xi, yi = int(round(x)), int(round(y))
                if not (5 <= xi < gray.shape[1] - 5 and 5 <= yi < gray.shape[0] - 5):
                    continue
                center = gray[yi, xi]
                sides: list[float] = []
                for off in (2.0, 4.0):
                    a = (int(round(x + nx * off)), int(round(y + ny * off)))
                    b = (int(round(x - nx * off)), int(round(y - ny * off)))
                    if 0 <= a[0] < gray.shape[1] and 0 <= a[1] < gray.shape[0]:
                        sides.append(float(gray[a[1], a[0]]))
                    if 0 <= b[0] < gray.shape[1] and 0 <= b[1] < gray.shape[0]:
                        sides.append(float(gray[b[1], b[0]]))
                if sides:
                    contrasts.append(float(center - np.mean(sides)))
            if len(contrasts) < 3:
                continue
            contrast = float(np.median(contrasts))
            center_fraction = float(np.mean(np.asarray(contrasts) >= self.config.min_corridor_contrast))
            if contrast < self.config.min_corridor_contrast or center_fraction < self.config.min_center_fraction:
                continue
            confidence = min(0.9, 0.42 + 0.003 * length + 0.04 * min(1.0, contrast / 12.0) + 0.08 * center_fraction)
            segments.append(CorridorSegment(MapPoint(x1, y1), MapPoint(x2, y2), confidence, contrast))
        segments.sort(key=lambda s: (s.confidence, s.length), reverse=True)
        return _dedupe_segments(segments, self.config.endpoint_cluster_radius)[: self.config.max_segments]

    def _infer_intersections(self, segments: list[CorridorSegment]) -> list[tuple[MapPoint, int, float]]:
        if len(segments) < 2:
            return []
        buckets: list[tuple[MapPoint, list[CorridorSegment]]] = []
        for seg in segments:
            for p in (seg.start, seg.end):
                hit = None
                for i, (center, members) in enumerate(buckets):
                    if math.hypot(p.x - center.x, p.y - center.y) <= self.config.intersection_cluster_radius:
                        hit = i
                        break
                if hit is None:
                    buckets.append((p, [seg]))
                else:
                    center, members = buckets[hit]
                    members.append(seg)
                    buckets[hit] = (MapPoint(float(np.mean([m.start.x for m in members] + [m.end.x for m in members])), float(np.mean([m.start.y for m in members] + [m.end.y for m in members]))), members)
        result: list[tuple[MapPoint, int, float]] = []
        for center, members in buckets:
            unique_angles: list[float] = []
            for seg in members:
                angle = math.atan2(seg.end.y - seg.start.y, seg.end.x - seg.start.x) % math.pi
                if all(abs(math.sin(angle - a)) > 0.28 for a in unique_angles):
                    unique_angles.append(angle)
            support = len(unique_angles)
            if support < self.config.min_intersection_support:
                continue
            confidence = min(0.9, 0.48 + 0.12 * min(3, support) + 0.03 * min(4, len(members)))
            result.append((center, support, confidence))
        return result[:30]


def _as_rgb(image: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("expected image array shaped (H,W,3) or (H,W,4)")
    return image[..., :3]


def _crop(image: np.ndarray, cfg: WorldMapGraphVisionConfig) -> tuple[np.ndarray, tuple[int, int]]:
    h, w, _ = image.shape
    x0 = int(np.clip(cfg.roi_left, 0, 1) * w)
    y0 = int(np.clip(cfg.roi_top, 0, 1) * h)
    x1 = int(np.clip(cfg.roi_right, 0, 1) * w)
    y1 = int(np.clip(cfg.roi_bottom, 0, 1) * h)
    return image[y0:y1, x0:x1], (x0, y0)


def _dedupe_segments(segments: Iterable[CorridorSegment], radius: float) -> list[CorridorSegment]:
    out: list[CorridorSegment] = []
    for seg in segments:
        mid = MapPoint((seg.start.x + seg.end.x) / 2, (seg.start.y + seg.end.y) / 2)
        if any(math.hypot(mid.x - ((s.start.x+s.end.x)/2), mid.y - ((s.start.y+s.end.y)/2)) < radius and abs(seg.length - s.length) < 16 for s in out):
            continue
        out.append(seg)
    return out


def _dedupe(features: list[DetectedFeature], radius: float) -> list[DetectedFeature]:
    out: list[DetectedFeature] = []
    for f in features:
        if any(f.feature_type == g.feature_type and math.hypot(f.center.x-g.center.x, f.center.y-g.center.y) < radius for g in out):
            continue
        out.append(f)
    return out
