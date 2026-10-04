from __future__ import annotations

from dataclasses import dataclass

from wowbot.vision.local_world import LocalWorldModel, build_local_world_model
from wowbot.vision.models import NavigationVisionObservation


@dataclass(frozen=True, slots=True)
class LocalWorldProjector:
    """Projects the shared fused observation into a read-only local world model."""

    def project(self, observation: NavigationVisionObservation) -> LocalWorldModel:
        return build_local_world_model(observation)
