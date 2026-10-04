import pytest

from wowbot.navigation.models import ArrivalCondition, DestinationIntent, DestinationKind
from wowbot.vision.models import MapPoint, NavigationVisionObservation, WorldMapObservation, MarkerObservation


def test_destination_requires_position_or_zone():
    with pytest.raises(ValueError):
        DestinationIntent(DestinationKind.POINT, None, "test", ArrivalCondition("POINT"))


def test_world_map_observation_is_structured():
    obs = WorldMapObservation(1000, 800, MapPoint(500, 400), markers=(MarkerObservation("QUEST", MapPoint(600, 410), 0.95),), observed_at=10.0)
    nav = NavigationVisionObservation(world_map=obs, observed_at=10.0)
    assert nav.world_map is not None
    assert nav.world_map.markers[0].marker_type == "QUEST"
