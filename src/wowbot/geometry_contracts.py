"""Common read-only geometry results; missing data never proves clear space."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
import math
from typing import Any, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class GeometryPath:
    """Compatibility value for providers using the legacy total_cost name."""
    anchors: tuple[dict, ...]
    cost: float
    tile_count: int
    polygon_count: int


class GeometryStatus(StrEnum):
    READY = "READY"
    NO_ROUTE = "NO_ROUTE"
    PARTIAL = "PARTIAL"
    MISSING_DATA = "MISSING_DATA"
    UNSUPPORTED = "UNSUPPORTED"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    INVALID_INPUT = "INVALID_INPUT"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class GeometryResult(Generic[T]):
    status: GeometryStatus
    value: T | None = None
    reason: str = "unknown_geometry"
    world_map_id: int | None = None
    revision: str | int | None = None
    provider: str = "UNKNOWN"

    def __post_init__(self):
        if not isinstance(self.status, GeometryStatus):
            raise ValueError("explicit geometry status required")
        if (self.status is GeometryStatus.READY) != (self.value is not None):
            raise ValueError("only a ready result can contain actionable geometry")

    @property
    def ready(self) -> bool:
        return self.status is GeometryStatus.READY

    def diagnostic(self) -> dict:
        return {"status": self.status.value, "reason": self.reason, "world_map_id": self.world_map_id,
                "revision": self.revision, "provider": self.provider}


def _endpoint(point):
    if not isinstance(point, Mapping) or point.get("coordinate_space") not in (None, "WORLD_YARDS"):
        return False
    if any(type(point.get(axis)) not in {int, float} or not math.isfinite(point[axis]) for axis in ("x", "y")):
        return False
    return point.get("z_known") is False or "z" not in point or (
        type(point["z"]) in {int, float} and math.isfinite(point["z"]))


def _failure(diagnostics):
    reason = str(diagnostics.get("reason") or "unclassified_geometry_result")
    if diagnostics.get('geometry_status') in {'ERROR','VERSION_MISMATCH','MISSING_DATA'}:
        return GeometryStatus(diagnostics['geometry_status']), reason
    if diagnostics.get("partial") is True:
        return GeometryStatus.PARTIAL, reason
    if reason in {"map_header_missing", "no_route_tiles", "tile_missing", "missing_tile"}:
        return GeometryStatus.MISSING_DATA, reason
    if reason in {"unsupported_version", "tile_version_mismatch", "geometry_version_mismatch"}:
        return GeometryStatus.VERSION_MISMATCH, reason
    if reason in {"invalid_world_endpoint", "invalid_world_map"}:
        return GeometryStatus.INVALID_INPUT, reason
    if reason in {"endpoint_not_on_mesh", "no_polygon_path", "walking_segment_grade_rejected", "route_blocked", 'walking_flags_excluded'}:
        return GeometryStatus.NO_ROUTE, reason
    return GeometryStatus.UNKNOWN, reason


def _checked_path(path):
    anchors = getattr(path, 'anchors', None)
    cost = getattr(path, 'cost', getattr(path, 'total_cost', None))
    if (not isinstance(anchors, (list, tuple)) or not anchors
            or type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0
            or not all(_endpoint(point) for point in anchors)):
        return None
    if hasattr(path, 'cost'):
        return path
    return GeometryPath(tuple(dict(p) for p in anchors), float(cost),
                        getattr(path, 'tile_count', 0), getattr(path, 'polygon_count', 0))


def query_path(provider, world_map_id: int, start: Mapping[str, Any], destination: Mapping[str, Any],
               *, allow_typed: bool = True) -> GeometryResult:
    """Adapt existing geometry providers without a second router or executor.

    A provider may supply its own typed result. Legacy diagnostics describe
    only this synchronous call; a previous successful status cannot make a
    None/empty/partial path usable. No clearance/LOS is inferred from VMAP Z.
    """
    name = type(provider).__name__ if provider is not None else "NONE"
    revision = getattr(provider, "revision", None)
    if type(revision) not in {str, int}:
        revision = None
    if type(world_map_id) is not int or world_map_id < 0 or not _endpoint(start) or not _endpoint(destination):
        return GeometryResult(GeometryStatus.INVALID_INPUT, reason="invalid_world_endpoint", provider=name)
    if any(type(point.get('instance_id', world_map_id)) is not int
           or point.get("instance_id", world_map_id) != world_map_id for point in (start, destination)):
        return GeometryResult(GeometryStatus.INVALID_INPUT, reason="world_map_mismatch", world_map_id=world_map_id,
                              revision=revision, provider=name)
    typed = getattr(provider, "query_path", None)
    if allow_typed and callable(typed):
        try:
            result = typed(world_map_id, start, destination)
        except (OSError, ValueError, TypeError, RuntimeError):
            return GeometryResult(GeometryStatus.ERROR, reason="geometry_query_failed", world_map_id=world_map_id,
                                  revision=revision, provider=name)
        if isinstance(result, GeometryResult):
            if result.world_map_id is not None and (type(result.world_map_id) is not int
                                                    or result.world_map_id != world_map_id):
                return GeometryResult(GeometryStatus.ERROR, reason='geometry_result_world_map_mismatch',
                                      world_map_id=world_map_id, revision=revision, provider=name)
            if not result.ready:
                return result
            checked = _checked_path(result.value)
            if checked is not None:
                return replace(result, value=checked)
            return GeometryResult(GeometryStatus.ERROR, reason='invalid_path_result', world_map_id=world_map_id,
                                  revision=revision, provider=name)
        return GeometryResult(GeometryStatus.ERROR, reason="invalid_geometry_contract", world_map_id=world_map_id,
                              revision=revision, provider=name)
    find = getattr(provider, "find_path", None)
    if not callable(find):
        return GeometryResult(GeometryStatus.UNSUPPORTED, reason="path_query_unavailable", world_map_id=world_map_id,
                              revision=revision, provider=name)
    try:
        path = find(world_map_id, dict(start), dict(destination))
    except (OSError, ValueError, TypeError, RuntimeError):
        return GeometryResult(GeometryStatus.ERROR, reason="geometry_query_failed", world_map_id=world_map_id,
                              revision=revision, provider=name)
    diagnostics = getattr(provider, "last_diagnostics", {})
    diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
    if path is not None and not diagnostics.get("partial") and getattr(path, "anchors", None):
        checked = _checked_path(path)
        if checked is not None:
            return GeometryResult(GeometryStatus.READY, checked, "route_found", world_map_id, revision, name)
        return GeometryResult(GeometryStatus.ERROR, reason="invalid_path_result", world_map_id=world_map_id,
                              revision=revision, provider=name)
    status, reason = _failure(diagnostics)
    return GeometryResult(status, reason=reason, world_map_id=world_map_id, revision=revision, provider=name)
