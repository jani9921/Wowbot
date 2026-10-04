from wowbot.navigation.local_world_bridge import NavigationWorldBridge
from wowbot.navigation.spatial_context import NavigationSpatialContextBuilder
from wowbot.vision.fusion.local import LocalWorldProjector
from wowbot.vision.models import MapPoint, MarkerObservation, MinimapObservation, NavigationVisionObservation, WorldObservation, WorldMapObservation


def _obs():
    world = WorldObservation(
        visible_entities=(
            {"entity_type": "NPC", "confidence": 0.9, "relation": "friendly", "screen_center": {"x": 100, "y": 120}},
            {"entity_type": "PLAYER", "confidence": 0.8, "relation": "friendly", "class_name": "mage", "class_color": "#69CCF0", "screen_center": {"x": 200, "y": 120}},
        ),
        obstacles=(),
        observed_at=20.0,
    )
    minimap = MinimapObservation(
        width=200, height=200, player_marker=MapPoint(100, 100),
        markers=(MarkerObservation("quest_direction", MapPoint(150, 70), 0.9, bearing_degrees=45),),
        observed_at=20.0, center_radius_px=80,
    )
    world_map = WorldMapObservation(
        width=500, height=400, player_marker=MapPoint(250, 200),
        markers=(MarkerObservation("quest_turn_in", MapPoint(310, 220), 0.8),),
        observed_at=20.0,
    )
    return NavigationVisionObservation(world_map=world_map, minimap=minimap, world=world, observed_at=20.0)


def test_spatial_context_exposes_map_markers_without_association():
    obs = _obs()
    local = LocalWorldProjector().project(obs)
    view = NavigationWorldBridge().from_local_world(local)
    ctx = NavigationSpatialContextBuilder().build(obs, view)
    assert ctx.minimap_player == (100.0, 100.0)
    assert ctx.world_map_player == (250.0, 200.0)
    assert [m.marker_type for m in ctx.minimap_markers] == ["quest_direction"]
    assert [m.marker_type for m in ctx.world_map_markers] == ["quest_turn_in"]
    assert "markers_exposed_without_entity_association" in ctx.notes
    assert len(ctx.local_world.entities) == 2


def test_spatial_context_never_promotes_or_relabels_entities():
    obs = _obs()
    local = LocalWorldProjector().project(obs)
    view = NavigationWorldBridge().from_local_world(local)
    ctx = NavigationSpatialContextBuilder().build(obs, view)
    assert [e.entity_type for e in ctx.local_world.entities] == ["NPC", "PLAYER"]
    assert all(e.relation in {"friendly"} for e in ctx.local_world.entities)
    assert all("entity_type" not in m.to_dict() for m in ctx.minimap_markers + ctx.world_map_markers)
