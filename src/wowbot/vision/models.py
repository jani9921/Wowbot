from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional


class FeatureType(StrEnum):
    ROAD = "ROAD"
    PATH = "PATH"
    INTERSECTION = "INTERSECTION"
    BRIDGE = "BRIDGE"
    ENTRANCE = "ENTRANCE"
    BLOCKED_REGION = "BLOCKED_REGION"
    POI = "POI"
    ZONE_BOUNDARY = "ZONE_BOUNDARY"


@dataclass(frozen=True, slots=True)
class MapPoint: 
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class WorldPosition:
    x: float
    y: float
    z: float = 0.0


@dataclass(frozen=True, slots=True)
class DetectedFeature:
    feature_type: FeatureType
    center: MapPoint
    confidence: float
    width: float = 0.0
    height: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class MarkerObservation:
    marker_type: str
    position: MapPoint
    confidence: float
    label: Optional[str] = None
    marker_color: Optional[str] = None
    relation: Optional[str] = None
    symbol: Optional[str] = None
    bearing_degrees: Optional[float] = None
    candidate_labels: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    bbox: Optional[tuple[int, int, int, int]] = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class MapMarker:
    """Surface-neutral tracked marker; appearance is not semantic meaning."""
    marker_id: str
    track_id: str
    surface: str
    belief: str
    confidence: float
    position: Optional[dict[str, float | str]] = None
    local_position: Optional[dict[str, float | str]] = None
    world_position_if_proven: Optional[dict[str, float | int | str]] = None
    bbox: Optional[dict[str, float | int | str]] = None
    visual_signature: Optional[dict[str, object]] = None
    candidate_labels: tuple[str, ...] = ()
    entity_candidates: tuple[dict[str, object], ...] = ()
    quest_candidates: tuple[dict[str, object], ...] = ()
    evidence: tuple[object, ...] = ()
    lifecycle: str = "TENTATIVE"
    semantic_type: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.surface not in {"MINIMAP", "WORLD_MAP"}:
            raise ValueError("MapMarker surface must be MINIMAP or WORLD_MAP")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        if self.surface == "MINIMAP" and self.world_position_if_proven is not None:
            proof = self.world_position_if_proven.get("transform_status")
            if proof != "TRUSTED":
                raise ValueError("minimap world position requires a TRUSTED transform")

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "MapMarker":
        source = str(payload.get("source") or "")
        surface = "MINIMAP" if source == "MINIMAP_CV" else "WORLD_MAP"
        track_id = str(payload.get("track_id") or payload.get("marker_id") or "")
        raw_evidence = payload.get("visual_evidence") or payload.get("evidence") or ()
        evidence = (raw_evidence,) if isinstance(raw_evidence, str) else tuple(raw_evidence)
        return cls(
            marker_id=str(payload.get("marker_id") or track_id), track_id=track_id,
            surface=surface, belief=str(payload.get("belief") or "UNKNOWN"),
            confidence=float(payload.get("confidence") or 0.),
            position=payload.get("position") if isinstance(payload.get("position"), dict) else None,
            local_position=payload.get("local_position") if isinstance(payload.get("local_position"), dict) else None,
            world_position_if_proven=(payload.get("world_position_if_proven")
                                      if isinstance(payload.get("world_position_if_proven"), dict) else None),
            bbox=payload.get("bbox") if isinstance(payload.get("bbox"), dict) else None,
            visual_signature=(payload.get("visual_signature")
                              if isinstance(payload.get("visual_signature"), dict) else None),
            candidate_labels=tuple(payload.get("candidate_labels") or ()),
            entity_candidates=tuple(payload.get("entity_candidates") or ()),
            quest_candidates=tuple(payload.get("quest_candidates") or ()),
            evidence=evidence,
            lifecycle=str(payload.get("lifecycle") or payload.get("track_state") or "TENTATIVE"),
            semantic_type=str(payload.get("semantic_type") or "UNKNOWN"),
        )


@dataclass(frozen=True, slots=True)
class HeadingObservation:
    degrees: float
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class WorldMapObservation:
    width: int
    height: int
    player_marker: Optional[MapPoint]
    markers: tuple[MarkerObservation, ...] = ()
    features: tuple[DetectedFeature, ...] = ()
    zone: Optional[str] = None
    observed_at: float = 0.0


@dataclass(frozen=True, slots=True)
class MinimapObservation:
    width: int
    height: int
    player_marker: MapPoint
    heading: Optional[HeadingObservation] = None
    markers: tuple[MarkerObservation, ...] = ()
    features: tuple[DetectedFeature, ...] = ()
    observed_at: float = 0.0
    center_radius_px: float = 0.0
    usable_radius_px: float = 0.0

    def marker_relative(self, marker: MarkerObservation) -> tuple[float, float]:
        """Return marker position relative to player in minimap pixels."""
        return (
            float(marker.position.x - self.player_marker.x),
            float(marker.position.y - self.player_marker.y),
        )

    def marker_normalized(self, marker: MarkerObservation) -> tuple[float, float]:
        """Return relative marker position normalized by minimap radius."""
        radius = self.center_radius_px
        if radius <= 0.0:
            return self.marker_relative(marker)
        dx, dy = self.marker_relative(marker)
        return dx / radius, dy / radius

    def marker_distance_px(self, marker: MarkerObservation) -> float:
        dx, dy = self.marker_relative(marker)
        return (dx * dx + dy * dy) ** 0.5


@dataclass(frozen=True, slots=True)
class WorldObservation:
    visible_entities: tuple[dict[str, object], ...] = ()
    obstacles: tuple[DetectedFeature, ...] = ()
    observed_at: float = 0.0


@dataclass(frozen=True, slots=True)
class NavigationVisionObservation:
    world_map: Optional[WorldMapObservation] = None
    minimap: Optional[MinimapObservation] = None
    world: Optional[WorldObservation] = None
    addon_facts: dict[str, object] = field(default_factory=dict)
    observed_at: float = 0.0
    context_id: Optional[str] = None
    player_world_position: Optional[WorldPosition] = None
    position_confidence: float = 0.0
