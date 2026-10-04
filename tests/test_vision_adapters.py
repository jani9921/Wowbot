from __future__ import annotations

import numpy as np

from wowbot.vision.adapters.minimap import detect_minimap
from wowbot.vision.adapters.world_map import detect_world_map
from wowbot.vision.fusion.pipeline import PerceptionFusion


def bgra(width: int, height: int) -> np.ndarray:
    return np.zeros((height, width, 4), dtype=np.uint8)


def bytes_of(image: np.ndarray) -> bytes:
    return image.tobytes()


def test_world_map_adapter_detects_player_and_quest_marker() -> None:
    width, height = 300, 200
    image = bgra(width, height)
    # Player: a compact white component in the map ROI.
    image[80:86, 140:145, :3] = (200, 200, 200)
    # Quest: compact gold component away from the player.
    image[100:106, 180:186, :3] = (60, 170, 210)  # B, G, R

    observation = detect_world_map(bytes_of(image), width, height, zone="Elwynn", observed_at=123.0)

    assert observation.player_marker is not None
    assert observation.zone == "Elwynn"
    marker = next(marker for marker in observation.markers
                  if "gold_glyph_like" in marker.candidate_labels)
    assert marker.marker_type == "unknown_world_map_marker"
    assert marker.bbox is not None


def test_world_map_blue_objective_area_stays_unknown_and_keeps_geometry() -> None:
    width, height = 400, 300
    image = bgra(width, height)
    image[100:150, 150:230, :3] = (180, 90, 70)  # blue translucent-like B,G,R

    observation = detect_world_map(bytes_of(image), width, height)

    area = next(marker for marker in observation.markers
                if "blue_region_like" in marker.candidate_labels)
    assert area.marker_type == "unknown_world_map_area"
    assert area.bbox == (150, 100, 230, 150)
    assert "quest" not in area.marker_type.lower()


def test_minimap_adapter_detects_selected_target() -> None:
    width, height = 300, 200
    image = bgra(width, height)
    # Minimap center is approximately (276, 35) for this frame.
    image[32:37, 264:269, :3] = (0, 30, 230)  # red in B,G,R order

    observation = detect_minimap(bytes_of(image), width, height, observed_at=456.0)

    target = next(marker for marker in observation.markers if "selected_target_like" in marker.candidate_labels)
    assert target.position.x < observation.player_marker.x
    assert target.position.y < observation.player_marker.y
    assert target.confidence > 0.5


def test_fusion_preserves_source_observations() -> None:
    world_map = detect_world_map(bytes_of(bgra(120, 80)), 120, 80)
    minimap = detect_minimap(bytes_of(bgra(120, 80)), 120, 80)
    fused = PerceptionFusion().build(world_map=world_map, minimap=minimap, addon_facts={"map_id": 12}, observed_at=9.0)

    assert fused.world_map is world_map
    assert fused.minimap is minimap
    assert fused.addon_facts["map_id"] == 12
    assert fused.observed_at == 9.0
