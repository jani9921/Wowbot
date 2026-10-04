"""DESIGN-013 wiring: WorldQuery.player() exposes moving/vehicle/subzone."""
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel


def _state(**overrides):
    value = {"session_id": "player-state-session", "frame_id": 1, "timestamp": 1.,
              "map_id": 1609, "is_dead": False, "is_in_combat": False,
              "position": {"x": .5, "y": .5}, "active_quests": []}
    value.update(overrides)
    return value


def test_player_projection_reports_moving_vehicle_and_subzone():
    world = WorldModel()
    world.ingest(Observation.create(
        _state(is_moving=True, in_vehicle=True, subzone_name="Goldshire"), 1.))
    player = world.query.player()
    assert player["moving"] is True
    assert player["vehicle"] is True
    assert player["subzone"] == "Goldshire"


def test_player_projection_defaults_moving_and_vehicle_false_when_absent():
    world = WorldModel()
    world.ingest(Observation.create(_state(), 1.))
    player = world.query.player()
    assert player["moving"] is False
    assert player["vehicle"] is False
    assert player["subzone"] is None


def test_player_projection_does_not_expose_agent_control_mode():
    # DESIGN-013: control_mode is deliberately excluded -- it is agent-level
    # control authority (AutonomousAgent.mode), not perceived world state.
    world = WorldModel()
    world.ingest(Observation.create(_state(), 1.))
    assert "control_mode" not in world.query.player()
