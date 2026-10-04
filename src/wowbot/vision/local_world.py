from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wowbot.vision.models import NavigationVisionObservation, WorldPosition


@dataclass(frozen=True, slots=True)
class LocalEntity:
    entity_type: str
    screen_center: tuple[float, float]
    confidence: float
    relation: str | None = None
    class_name: str | None = None
    class_color: str | None = None
    track_id: int | None = None
    relation_changed: bool = False
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class LocalWorldModel:
    """Read-only local world snapshot for downstream navigation consumers."""
    observed_at: float
    source: str
    player_world_position: WorldPosition | None
    position_confidence: float
    entities: tuple[LocalEntity, ...] = ()
    candidate_obstacles: tuple[LocalEntity, ...] = ()
    world_map_present: bool = False
    minimap_present: bool = False
    addon_facts_present: bool = False
    confidence: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_actionable_world(self) -> bool:
        return bool(self.entities or self.world_map_present or self.minimap_present)

    def highest_confidence_relation(self, relation: str) -> LocalEntity | None:
        matches = [e for e in self.entities if e.relation == relation]
        if not matches:
            return None
        return max(matches, key=lambda e: e.confidence)

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for entity in self.entities:
            result[entity.entity_type] = result.get(entity.entity_type, 0) + 1
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at,
            "source": self.source,
            "player_world_position": None if self.player_world_position is None else {
                "x": self.player_world_position.x, "y": self.player_world_position.y, "z": self.player_world_position.z
            },
            "position_confidence": self.position_confidence,
            "entities": [
                {
                    "entity_type": e.entity_type,
                    "screen_center": {"x": e.screen_center[0], "y": e.screen_center[1]},
                    "confidence": e.confidence,
                    "relation": e.relation,
                    "class_name": e.class_name,
                    "class_color": e.class_color,
                    "track_id": e.track_id,
                    "relation_changed": e.relation_changed,
                    "evidence": e.evidence,
                }
                for e in self.entities
            ],
            "candidate_obstacles": [
                {
                    "entity_type": e.entity_type,
                    "screen_center": {"x": e.screen_center[0], "y": e.screen_center[1]},
                    "confidence": e.confidence,
                    "track_id": e.track_id,
                    "evidence": e.evidence,
                }
                for e in self.candidate_obstacles
            ],
            "entity_counts": self.counts(),
            "candidate_obstacle_count": len(self.candidate_obstacles),
            "world_map_present": self.world_map_present,
            "minimap_present": self.minimap_present,
            "addon_facts_present": self.addon_facts_present,
            "confidence": self.confidence,
            "has_actionable_world": self.has_actionable_world,
            "notes": list(self.notes),
        }


def build_local_world_model(observation: NavigationVisionObservation) -> LocalWorldModel:
    world = observation.world
    entities: list[LocalEntity] = []
    candidate_obstacles: list[LocalEntity] = []
    if world is not None:
        for raw in world.visible_entities:
            entity = _to_entity(raw)
            if entity.entity_type == "OBSTACLE_CANDIDATE":
                candidate_obstacles.append(entity)
            elif entity.entity_type not in {"VISUAL_CANDIDATE", "UNKNOWN"}:
                entities.append(entity)

    source = "fusion"
    confidence_parts: list[float] = []
    if entities:
        confidence_parts.append(sum(e.confidence for e in entities) / len(entities))
    if observation.position_confidence > 0.0:
        confidence_parts.append(observation.position_confidence)
    if observation.minimap is not None:
        confidence_parts.append(0.75)
    if observation.world_map is not None:
        confidence_parts.append(0.75)
    confidence = sum(confidence_parts) / len(confidence_parts) if confidence_parts else 0.0

    notes: list[str] = []
    if candidate_obstacles:
        notes.append("obstacle_candidates_present_but_unproven")
    if world is None:
        notes.append("no_world_observation")

    return LocalWorldModel(
        observed_at=observation.observed_at,
        source=source,
        player_world_position=observation.player_world_position,
        position_confidence=observation.position_confidence,
        entities=tuple(entities),
        candidate_obstacles=tuple(candidate_obstacles),
        world_map_present=observation.world_map is not None,
        minimap_present=observation.minimap is not None,
        addon_facts_present=bool(observation.addon_facts),
        confidence=max(0.0, min(1.0, confidence)),
        notes=tuple(notes),
    )


def _to_entity(raw: dict[str, Any]) -> LocalEntity:
    center = raw.get("screen_center") or {}
    return LocalEntity(
        entity_type=str(raw.get("entity_type", "UNKNOWN")),
        screen_center=(float(center.get("x", 0.0)), float(center.get("y", 0.0))),
        confidence=float(raw.get("confidence", 0.0)),
        relation=raw.get("relation"),
        class_name=raw.get("class_name"),
        class_color=raw.get("class_color"),
        track_id=raw.get("track_id"),
        relation_changed=bool(raw.get("relation_changed", False)),
        evidence=str(raw.get("evidence", "")),
    )
