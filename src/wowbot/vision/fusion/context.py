from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from wowbot.navigation.world_context import CoordinateMapper, MapIdentityResolver
from wowbot.vision.models import NavigationVisionObservation


@dataclass(slots=True)
class WorldContextFusion:
    identity: MapIdentityResolver
    coordinates: CoordinateMapper

    def enrich(self, observation: NavigationVisionObservation) -> NavigationVisionObservation:
        context = self.identity.resolve_from_facts(observation.addon_facts, coordinate_space="world")
        map_point = observation.world_map.player_marker if observation.world_map else None
        position = self.coordinates.player_position(
            context=context,
            map_point=map_point,
            addon_facts=observation.addon_facts,
        )
        confidence = context.confidence
        if position is not None and observation.addon_facts.get("world_position") is not None:
            confidence = max(confidence, 1.0)
        elif position is not None:
            confidence = min(confidence, 0.8)
        return NavigationVisionObservation(
            world_map=observation.world_map,
            minimap=observation.minimap,
            world=observation.world,
            addon_facts=dict(observation.addon_facts),
            observed_at=observation.observed_at,
            context_id=context.context_id,
            player_world_position=position,
            position_confidence=confidence,
        )
