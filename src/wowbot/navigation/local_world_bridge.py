from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wowbot.vision.local_world import LocalEntity, LocalWorldModel
from wowbot.vision.models import WorldPosition


@dataclass(frozen=True, slots=True)
class NavigationLocalEntity:
    """An immutable navigation-facing copy of one fused visual entity."""

    entity_type: str
    screen_center: tuple[float, float]
    confidence: float
    relation: str | None = None
    class_name: str | None = None
    class_color: str | None = None
    track_id: int | None = None
    relation_changed: bool = False
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "screen_center": {"x": self.screen_center[0], "y": self.screen_center[1]},
            "confidence": self.confidence,
            "relation": self.relation,
            "class_name": self.class_name,
            "class_color": self.class_color,
            "track_id": self.track_id,
            "relation_changed": self.relation_changed,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class NavigationLocalWorldView:
    observed_at: float
    source: str
    player_world_position: WorldPosition | None
    position_confidence: float
    entities: tuple[NavigationLocalEntity, ...] = ()
    candidate_obstacles: tuple[NavigationLocalEntity, ...] = ()
    world_map_present: bool = False
    minimap_present: bool = False
    addon_facts_present: bool = False
    confidence: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def actionable_entity_count(self) -> int:
        return len(self.entities)

    @property
    def candidate_obstacle_count(self) -> int:
        return len(self.candidate_obstacles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at,
            "source": self.source,
            "player_world_position": None if self.player_world_position is None else {
                "x": self.player_world_position.x,
                "y": self.player_world_position.y,
                "z": self.player_world_position.z,
            },
            "position_confidence": self.position_confidence,
            "entities": [entity.to_dict() for entity in self.entities],
            "candidate_obstacles": [entity.to_dict() for entity in self.candidate_obstacles],
            "actionable_entity_count": self.actionable_entity_count,
            "candidate_obstacle_count": self.candidate_obstacle_count,
            "world_map_present": self.world_map_present,
            "minimap_present": self.minimap_present,
            "addon_facts_present": self.addon_facts_present,
            "confidence": self.confidence,
            "notes": list(self.notes),
        }


class NavigationWorldBridge:
    """Copies fused observations without classification, promotion, or planning."""

    def from_local_world(self, world: LocalWorldModel) -> NavigationLocalWorldView:
        return NavigationLocalWorldView(
            observed_at=world.observed_at,
            source=world.source,
            player_world_position=world.player_world_position,
            position_confidence=world.position_confidence,
            entities=tuple(self._copy_entity(entity) for entity in world.entities),
            candidate_obstacles=tuple(self._copy_entity(entity) for entity in world.candidate_obstacles),
            world_map_present=world.world_map_present,
            minimap_present=world.minimap_present,
            addon_facts_present=world.addon_facts_present,
            confidence=world.confidence,
            notes=world.notes,
        )

    @staticmethod
    def _copy_entity(entity: LocalEntity) -> NavigationLocalEntity:
        return NavigationLocalEntity(
            entity_type=entity.entity_type,
            screen_center=entity.screen_center,
            confidence=entity.confidence,
            relation=entity.relation,
            class_name=entity.class_name,
            class_color=entity.class_color,
            track_id=entity.track_id,
            relation_changed=entity.relation_changed,
            evidence=entity.evidence,
        )
