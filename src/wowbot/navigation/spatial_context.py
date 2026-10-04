from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wowbot.navigation.local_world_bridge import NavigationLocalWorldView
from wowbot.vision.models import MapPoint, MarkerObservation, NavigationVisionObservation


@dataclass(frozen=True, slots=True)
class SpatialMarker:
    marker_type: str
    position: tuple[float, float]
    confidence: float
    relation: str | None = None
    bearing_degrees: float | None = None
    source: str = "minimap"

    def to_dict(self) -> dict[str, Any]:
        return {
            "marker_type": self.marker_type,
            "position": {"x": self.position[0], "y": self.position[1]},
            "confidence": self.confidence,
            "relation": self.relation,
            "bearing_degrees": self.bearing_degrees,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class NavigationSpatialContext:
    """Read-only cross-view context; never assigns a 3D entity to a map marker.

    Screen-space entities stay untouched. Minimap/world-map markers are exposed
    as separate spatial hints with their native coordinates. No target selection,
    route planning, obstacle promotion, or movement is performed here.
    """

    observed_at: float
    local_world: NavigationLocalWorldView
    minimap_player: tuple[float, float] | None = None
    minimap_markers: tuple[SpatialMarker, ...] = ()
    world_map_player: tuple[float, float] | None = None
    world_map_markers: tuple[SpatialMarker, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def has_cross_view_context(self) -> bool:
        return bool(self.minimap_markers or self.world_map_markers or self.minimap_player or self.world_map_player)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at,
            "minimap_player": _point_dict(self.minimap_player),
            "minimap_markers": [m.to_dict() for m in self.minimap_markers],
            "world_map_player": _point_dict(self.world_map_player),
            "world_map_markers": [m.to_dict() for m in self.world_map_markers],
            "notes": list(self.notes),
            "has_cross_view_context": self.has_cross_view_context,
            "entity_count": self.local_world.actionable_entity_count,
            "candidate_obstacle_count": self.local_world.candidate_obstacle_count,
        }


class NavigationSpatialContextBuilder:
    """Build cross-view context without inventing entity↔marker associations."""

    def build(self, observation: NavigationVisionObservation, local_world: NavigationLocalWorldView) -> NavigationSpatialContext:
        minimap_player = None
        minimap_markers: list[SpatialMarker] = []
        world_map_player = None
        world_map_markers: list[SpatialMarker] = []

        if observation.minimap is not None:
            minimap_player = _point_tuple(observation.minimap.player_marker)
            for marker in observation.minimap.markers:
                minimap_markers.append(_marker(marker, "minimap"))

        if observation.world_map is not None:
            if observation.world_map.player_marker is not None:
                world_map_player = _point_tuple(observation.world_map.player_marker)
            for marker in observation.world_map.markers:
                world_map_markers.append(_marker(marker, "world_map"))

        notes: list[str] = []
        if minimap_markers or world_map_markers:
            notes.append("markers_exposed_without_entity_association")
        if not (minimap_markers or world_map_markers):
            notes.append("no_map_markers_present")

        return NavigationSpatialContext(
            observed_at=observation.observed_at,
            local_world=local_world,
            minimap_player=minimap_player,
            minimap_markers=tuple(minimap_markers),
            world_map_player=world_map_player,
            world_map_markers=tuple(world_map_markers),
            notes=tuple(notes),
        )


def _marker(marker: MarkerObservation, source: str) -> SpatialMarker:
    return SpatialMarker(
        marker_type=marker.marker_type,
        position=(float(marker.position.x), float(marker.position.y)),
        confidence=marker.confidence,
        relation=marker.relation,
        bearing_degrees=marker.bearing_degrees,
        source=source,
    )


def _point_tuple(point: MapPoint) -> tuple[float, float]:
    return float(point.x), float(point.y)


def _point_dict(point: tuple[float, float] | None) -> dict[str, float] | None:
    if point is None:
        return None
    return {"x": point[0], "y": point[1]}
