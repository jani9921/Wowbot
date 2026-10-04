from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import math
from typing import Iterable

import numpy as np

from .models import DetectedFeature, FeatureType, MapPoint
from .opencv_backend import OpenCvComputeBackend, create_opencv_backend

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None


@dataclass(frozen=True, slots=True)
class WorldMapRasterConfig:
    """Calibration-first World Map raster profile.

    Coordinates are relative to the full screenshot. The default profile matches the
    12.1.5 Exile's Reach World Map screenshot supplied for the M7.3 calibration run.
    The detector remains deliberately conservative: it produces feature candidates,
    not authoritative route topology.
    """

    roi_left: float = 0.045
    roi_top: float = 0.108
    roi_right: float = 0.955
    roi_bottom: float = 0.958
    # Fixed exclusion for a future top-left AIPC strip. This is relative to the map ROI.
    exclude_left: float = 0.0
    exclude_top: float = 0.0
    exclude_right: float = 0.0
    exclude_bottom: float = 0.075
    downsample_width: int = 900
    min_component_area_ratio: float = 0.000015
    max_component_area_ratio: float = 0.06
    max_components: int = 180
    corridor_min_line_length: int = 22
    corridor_max_line_gap: int = 9
    hough_threshold: int = 24
    junction_radius_px: int = 11
    junction_branch_min: int = 3
    min_corridor_elongation: float = 2.4
    max_feature_count: int = 80


class WorldMapRasterFeatureExtractor:
    """Extract conservative road/path/intersection candidates from a World Map image."""

    def __init__(self, config: WorldMapRasterConfig | None = None,
                 *, compute_backend: OpenCvComputeBackend | None = None) -> None:
        self.config = config or WorldMapRasterConfig()
        self.compute_backend = compute_backend if compute_backend is not None else create_opencv_backend()

    @property
    def compute_diagnostics(self) -> dict:
        return (self.compute_backend.diagnostics() if self.compute_backend is not None
                else {"requested": "AUTO", "active": "NUMPY", "reason": "opencv_unavailable"})

    def extract(self, image: np.ndarray) -> tuple[DetectedFeature, ...]:
        rgb = _as_rgb(image)
        cropped, origin = _crop_roi_with_origin(rgb, self.config)
        if cropped.size == 0:
            return ()
        scale = 1.0
        work = cropped
        if self.config.downsample_width and cropped.shape[1] > self.config.downsample_width:
            scale = self.config.downsample_width / cropped.shape[1]
            new_h = max(1, int(round(cropped.shape[0] * scale)))
            if cv2 is not None:
                work = self.compute_backend.resize(
                    cropped, (self.config.downsample_width, new_h), interpolation=cv2.INTER_AREA)
            else:
                work = cropped[::max(1, int(round(1 / scale))), ::max(1, int(round(1 / scale)))]

        mask = self._corridor_mask(work)
        mask = _apply_exclusion_mask(mask, self.config)
        features = self._extract_corridors(mask, scale, origin, cropped.shape[1], cropped.shape[0])
        features.extend(self._detect_intersections(mask, scale, origin))
        features = _dedupe_features(features)
        features.sort(key=lambda f: (-f.confidence, f.feature_type.value, f.center.y, f.center.x))
        return tuple(features[: self.config.max_feature_count])

    def _corridor_mask(self, rgb: np.ndarray) -> np.ndarray:
        if cv2 is not None:
            # Roads in the supplied map are thin, locally contrasting corridors. Use
            # Canny + a mild morphological close, then reject extremely dense texture.
            _gray, closed, contrast = self.compute_backend.raster_corridor_primitives(rgb)
            # Avoid a pure edge map being interpreted as roads by requiring local
            # luminance contrast around edge pixels.
            return (closed > 0) & (contrast >= 8)
        return _fallback_edge_mask(rgb)

    def _extract_corridors(self, mask: np.ndarray, scale: float, origin: tuple[int, int], full_w: int, full_h: int) -> list[DetectedFeature]:
        h, w = mask.shape
        features: list[DetectedFeature] = []
        min_area = max(6, int(h * w * self.config.min_component_area_ratio))
        max_area = max(min_area, int(h * w * self.config.max_component_area_ratio))
        if cv2 is not None:
            num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
            indices = range(1, num)
            indices = sorted(indices, key=lambda i: int(stats[i, cv2.CC_STAT_AREA]), reverse=True)[: self.config.max_components]
            for i in indices:
                area = int(stats[i, cv2.CC_STAT_AREA])
                if area < min_area or area > max_area:
                    continue
                x, y, bw, bh = (int(stats[i, j]) for j in range(4))
                elongation = max(bw, bh) / max(1, min(bw, bh))
                if elongation < self.config.min_corridor_elongation:
                    continue
                cx, cy = map(float, centroids[i])
                confidence = min(0.9, 0.40 + 0.20 * min(1.0, elongation / 8.0) + 0.20 * min(1.0, area / max(40, max(bw, bh) * 2)))
                feature_type = FeatureType.ROAD if elongation >= 3.5 else FeatureType.PATH
                ox, oy = origin
                features.append(DetectedFeature(feature_type, MapPoint((cx / scale) + ox, (cy / scale) + oy), confidence, bw / scale, bh / scale, {"source": "world_map_raster", "candidate": "true", "elongation": f"{elongation:.2f}"}))
            return features

        for comp in _components(mask, max_components=self.config.max_components):
            area = len(comp)
            if area < min_area or area > max_area:
                continue
            ys = np.fromiter((p[0] for p in comp), dtype=np.float32)
            xs = np.fromiter((p[1] for p in comp), dtype=np.float32)
            bw = float(xs.max() - xs.min() + 1)
            bh = float(ys.max() - ys.min() + 1)
            elongation = max(bw, bh) / max(1.0, min(bw, bh))
            if elongation < self.config.min_corridor_elongation:
                continue
            ox, oy = origin
            cx, cy = float(xs.mean()), float(ys.mean())
            feature_type = FeatureType.ROAD if elongation >= 3.5 else FeatureType.PATH
            confidence = min(0.9, 0.4 + 0.2 * min(1.0, elongation / 8.0))
            features.append(DetectedFeature(feature_type, MapPoint((cx / scale) + ox, (cy / scale) + oy), confidence, bw / scale, bh / scale, {"source": "world_map_raster", "candidate": "true"}))
        return features

    def _detect_intersections(self, mask: np.ndarray, scale: float, origin: tuple[int, int]) -> list[DetectedFeature]:
        if cv2 is None:
            return _fallback_intersections(mask, scale, origin, self.config.junction_radius_px)
        radius = max(4, self.config.junction_radius_px)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
        density = cv2.filter2D(mask.astype(np.uint8), -1, kernel, borderType=cv2.BORDER_CONSTANT)
        ys, xs = np.where(density >= max(12, int(kernel.sum() * 0.16)))
        picked: list[tuple[int, int]] = []
        for x, y in zip(xs.tolist(), ys.tolist()):
            if any((x - px) ** 2 + (y - py) ** 2 < (radius * 2) ** 2 for px, py in picked):
                continue
            patch = mask[max(0, y-radius):min(mask.shape[0], y+radius+1), max(0, x-radius):min(mask.shape[1], x+radius+1)]
            branches = _branch_count_fast(patch)
            if branches >= self.config.junction_branch_min:
                picked.append((x, y))
        ox, oy = origin
        return [DetectedFeature(FeatureType.INTERSECTION, MapPoint(x / scale + ox, y / scale + oy), min(0.95, 0.56 + 0.08 * branches), metadata={"source": "world_map_raster", "candidate": "true", "branches": str(branches)}) for x, y in picked[:40] for branches in [_branch_count_fast(mask[max(0, y-radius):min(mask.shape[0], y+radius+1), max(0, x-radius):min(mask.shape[1], x+radius+1)])]]


def _as_rgb(image: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("expected image array shaped (H,W,3) or (H,W,4)")
    return image[..., :3]


def _crop_roi_with_origin(image: np.ndarray, cfg: WorldMapRasterConfig) -> tuple[np.ndarray, tuple[int, int]]:
    h, w, _ = image.shape
    x0 = int(np.clip(cfg.roi_left, 0, 1) * w)
    y0 = int(np.clip(cfg.roi_top, 0, 1) * h)
    x1 = int(np.clip(cfg.roi_right, 0, 1) * w)
    y1 = int(np.clip(cfg.roi_bottom, 0, 1) * h)
    return image[y0:y1, x0:x1], (x0, y0)


def _apply_exclusion_mask(mask: np.ndarray, cfg: WorldMapRasterConfig) -> np.ndarray:
    out = mask.copy()
    h, w = out.shape
    x0 = int(np.clip(cfg.exclude_left, 0, 1) * w)
    y0 = int(np.clip(cfg.exclude_top, 0, 1) * h)
    x1 = int(np.clip(cfg.exclude_right, 0, 1) * w)
    y1 = int(np.clip(cfg.exclude_bottom, 0, 1) * h)
    if x1 > x0 and y1 > y0:
        out[y0:y1, x0:x1] = False
    return out


def _branch_count_fast(patch: np.ndarray) -> int:
    if patch.size == 0:
        return 0
    h, w = patch.shape
    cy, cx = h // 2, w // 2
    if not patch[cy, cx]:
        ys, xs = np.where(patch)
        if len(xs) == 0:
            return 0
        cy, cx = int(ys[len(ys)//2]), int(xs[len(xs)//2])
    radius = max(2, min(h, w) // 3)
    dirs = ((-1,0),(0,1),(1,0),(0,-1),(-1,1),(1,1),(1,-1),(-1,-1))
    occupied = []
    for dy, dx in dirs:
        y = int(np.clip(cy + dy * radius, 0, h - 1)); x = int(np.clip(cx + dx * radius, 0, w - 1))
        occupied.append(bool(patch[y, x]))
    return sum(occupied)


def _fallback_edge_mask(rgb: np.ndarray) -> np.ndarray:
    gray = (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]).astype(np.float32)
    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    return (gx + gy) > np.percentile(gx + gy, 82)


def _fallback_intersections(mask: np.ndarray, scale: float, origin: tuple[int, int], radius: int) -> list[DetectedFeature]:
    """Conservative NumPy-only junction proposals when OpenCV is unavailable."""
    if mask.size == 0 or not bool(mask.any()):
        return []
    radius = max(3, int(radius))
    h, w = mask.shape
    ox, oy = origin
    candidates: list[tuple[int, int, int]] = []
    step = max(2, radius // 2)
    for y in range(radius, h - radius, step):
        for x in range(radius, w - radius, step):
            patch = mask[y - radius:y + radius + 1, x - radius:x + radius + 1]
            if float(patch.mean()) < 0.10:
                continue
            branches = _branch_count_fast(patch)
            if branches >= 3:
                candidates.append((x, y, branches))
    picked: list[tuple[int, int, int]] = []
    for x, y, branches in candidates:
        if any((x - px) ** 2 + (y - py) ** 2 < (radius * 2) ** 2 for px, py, _ in picked):
            continue
        picked.append((x, y, branches))
    return [
        DetectedFeature(
            FeatureType.INTERSECTION,
            MapPoint(x / scale + ox, y / scale + oy),
            min(0.80, 0.48 + 0.06 * branches),
            metadata={"source": "world_map_raster_numpy", "candidate": "true", "branches": str(branches)},
        )
        for x, y, branches in picked[:40]
    ]


def _components(mask: np.ndarray, *, max_components: int) -> list[list[tuple[int, int]]]:
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    comps: list[list[tuple[int, int]]] = []
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            q = deque([(y, x)]); seen[y, x] = True; comp = []
            while q and len(comp) < 100000:
                cy, cx = q.popleft(); comp.append((cy, cx))
                for dy, dx in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True; q.append((ny, nx))
            comps.append(comp)
    comps.sort(key=len, reverse=True)
    return comps[:max_components]


def _dedupe_features(features: list[DetectedFeature]) -> list[DetectedFeature]:
    out: list[DetectedFeature] = []
    for f in features:
        if any(g.feature_type == f.feature_type and math.hypot(g.center.x-f.center.x, g.center.y-f.center.y) < 14 for g in out):
            continue
        out.append(f)
    return out
