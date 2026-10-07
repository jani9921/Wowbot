"""Issue #93: distance to WORLD_YARDS goals was computed from the normalized
UI-map position (same spot -> ~223 instead of 0)."""
from wowbot.agent.destination_distance import arrived, long_move, scaled_distance
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel

STATE = {"map_id": 1, "position": {"x": .5, "y": .5},
         "player_world_position": {"x": 100., "y": 200., "instance_id": 1,
                                   "coordinate_space": "WORLD_YARDS"}}


def _yards(x, y, instance=1, **extra):
    return {"x": x, "y": y, "instance_id": instance, "map_id": 1,
            "coordinate_space": "WORLD_YARDS", **extra}


def test_world_yards_goal_is_measured_in_yards_on_the_same_instance():
    assert scaled_distance(STATE, _yards(100., 200.)) == 0.
    assert arrived(STATE, _yards(103., 200.))
    assert not arrived(STATE, _yards(110., 200.))
    assert arrived(STATE, _yards(107., 200., stop_distance=8.))
    assert long_move(STATE, _yards(150., 200.)) and not long_move(STATE, _yards(120., 200.))


def test_other_or_missing_instance_fails_closed():
    assert scaled_distance(STATE, _yards(100., 200., instance=2)) is None
    assert not arrived(STATE, _yards(100., 200., instance=2))
    assert scaled_distance({**STATE, "player_world_position": {}}, _yards(100., 200.)) is None


def test_normalized_goal_keeps_map_units():
    assert abs(scaled_distance(STATE, {"x": .502, "y": .5, "map_id": 1}) - .002) < 1e-9
    assert arrived(STATE, {"x": .502, "y": .5, "map_id": 1})
    assert scaled_distance(STATE, {"x": .5, "y": .5, "map_id": 2}) is None


def test_world_model_distance_uses_the_destination_space():
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "s", "timestamp": 1., "frame_id": "f",
                                     "monotonic_time": 1., **STATE}, 1.))
    assert world.distance(_yards(100., 200.)) == 0.
    assert world.distance({"x": .5, "y": .5, "map_id": 1}) == 0.
