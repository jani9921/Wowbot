from wowbot.navigation.world_context import CoordinateBounds, CoordinateMapper, MapIdentityResolver
from wowbot.vision.models import MapPoint


def test_semantic_context_does_not_depend_on_map_id():
    resolver = MapIdentityResolver()
    a = resolver.resolve(map_id=10, zone="Elwynn Forest", continent="Eastern Kingdoms")
    b = resolver.resolve(map_id=42, zone="Elwynn Forest", continent="Eastern Kingdoms")
    assert a.context_id == b.context_id
    assert a.client_map_id == "10"
    assert b.client_map_id == "42"


def test_context_uses_map_id_only_as_fallback():
    resolver = MapIdentityResolver()
    ctx = resolver.resolve(map_id=99)
    assert ctx.context_id.startswith("wc:map-99:")
    assert ctx.confidence == 0.25


def test_exact_addon_position_wins_over_map_pixels():
    resolver = MapIdentityResolver()
    context = resolver.resolve(zone="Elwynn Forest")
    mapper = CoordinateMapper({context.context_id: CoordinateBounds(0, 100, 0, 100, 0, 1000, 0, 1000)})
    pos = mapper.player_position(
        context=context,
        map_point=MapPoint(10, 10),
        addon_facts={"world_position": {"x": 123.0, "y": 456.0, "z": 7.0}},
    )
    assert pos is not None
    assert (pos.x, pos.y, pos.z) == (123.0, 456.0, 7.0)


def test_subzone_does_not_fragment_context_identity():
    resolver = MapIdentityResolver()
    a = resolver.resolve(map_id=10, continent="Eastern Kingdoms", zone="Elwynn Forest", subzone="Goldshire")
    b = resolver.resolve(map_id=42, continent="Eastern Kingdoms", zone="Elwynn Forest", subzone="Northshire")
    assert a.context_id == b.context_id


def test_pixel_mapping_is_deterministic():
    resolver = MapIdentityResolver()
    context = resolver.resolve(zone="Elwynn Forest")
    mapper = CoordinateMapper({context.context_id: CoordinateBounds(0, 100, 0, 200, 0, 1000, 0, 2000)})
    pos = mapper.map_point(context, MapPoint(50, 100))
    assert pos is not None
    assert (pos.x, pos.y) == (500.0, 1000.0)
