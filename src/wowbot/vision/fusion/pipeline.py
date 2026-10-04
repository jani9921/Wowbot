from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from wowbot.vision.models import NavigationVisionObservation, WorldMapObservation, MinimapObservation, WorldObservation
from wowbot.vision.world3d.models import WorldFrameObservation
from wowbot.vision.world3d.normalization import world_frame_to_observation


@dataclass(frozen=True, slots=True)
class PerceptionFusion:
    """Deterministic merger of independently sourced observations."""

    def build(
        self,
        *,
        world_map: Optional[WorldMapObservation] = None,
        minimap: Optional[MinimapObservation] = None,
        world: Optional[WorldObservation] = None,
        addon_facts: Optional[dict[str, object]] = None,
        observed_at: float = 0.0,
    ) -> NavigationVisionObservation:
        return NavigationVisionObservation(
            world_map=world_map,
            minimap=minimap,
            world=world,
            addon_facts=dict(addon_facts or {}),
            observed_at=observed_at,
        )

    def build_from_world3d(
        self,
        frame: WorldFrameObservation,
        *,
        world_map: Optional[WorldMapObservation] = None,
        minimap: Optional[MinimapObservation] = None,
        addon_facts: Optional[dict[str, object]] = None,
    ) -> NavigationVisionObservation:
        """Feed a normalized WorldFrameObservation through the same fusion path."""
        world = world_frame_to_observation(frame)
        return self.build(
            world_map=world_map,
            minimap=minimap,
            world=world,
            addon_facts=addon_facts,
            observed_at=frame.observed_at,
        )
