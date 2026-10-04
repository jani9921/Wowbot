from __future__ import annotations

from dataclasses import dataclass
import math

from .models import MapPoint


@dataclass(frozen=True, slots=True)
class MinimapGeometry:
    """Screen-space geometry for the user's circular minimap.

    Defaults preserve the already working Retail observation geometry.
    Geometry is deliberately configurable so a UI scale/resolution change
    does not require changing detector logic.
    """

    center_x_fraction: float = 0.921
    center_y_fraction: float = 0.174
    radius_fraction: float = 0.088

    def center(self, width: int, height: int) -> MapPoint:
        return MapPoint(round(width * self.center_x_fraction), round(height * self.center_y_fraction))

    def radius(self, width: int, height: int) -> float:
        return height * self.radius_fraction


@dataclass(frozen=True, slots=True)
class MapCorrespondence:
    minimap_local: MapPoint
    world_map: MapPoint
    validated: bool = False


@dataclass(frozen=True, slots=True)
class CandidateMapTransform:
    """Evidence-derived similarity transform; never trusted by construction."""
    a: float
    b: float
    tx: float
    ty: float
    rmse: float
    correspondences: int
    validation_samples: int
    trusted: bool

    def project(self, local: MapPoint) -> MapPoint | None:
        if not self.trusted:
            return None
        return MapPoint(self.a*local.x-self.b*local.y+self.tx,
                        self.b*local.x+self.a*local.y+self.ty)


class MinimapMapTransformCalibrator:
    """correspondence → candidate transform → validation → trusted transform."""

    def __init__(self, *, maximum_rmse: float = .015, minimum_samples: int = 3):
        self.maximum_rmse = float(maximum_rmse)
        self.minimum_samples = int(minimum_samples)
        self.correspondences: list[MapCorrespondence] = []

    def add(self, correspondence: MapCorrespondence) -> None:
        self.correspondences.append(correspondence)

    def estimate(self) -> CandidateMapTransform | None:
        samples = self.correspondences
        if len(samples) < self.minimum_samples:
            return None
        import numpy as np
        rows, targets = [], []
        for item in samples:
            x, y = item.minimap_local.x, item.minimap_local.y
            rows.extend(((x, -y, 1., 0.), (y, x, 0., 1.)))
            targets.extend((item.world_map.x, item.world_map.y))
        a, b, tx, ty = np.linalg.lstsq(np.asarray(rows), np.asarray(targets), rcond=None)[0]
        errors = []
        for item in samples:
            px = a*item.minimap_local.x-b*item.minimap_local.y+tx
            py = b*item.minimap_local.x+a*item.minimap_local.y+ty
            errors.append((px-item.world_map.x)**2+(py-item.world_map.y)**2)
        rmse = math.sqrt(sum(errors)/len(errors))
        validation = sum(1 for item in samples if item.validated)
        trusted = validation >= self.minimum_samples and rmse <= self.maximum_rmse
        return CandidateMapTransform(float(a), float(b), float(tx), float(ty), rmse,
                                     len(samples), validation, trusted)
