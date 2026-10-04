from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel


def _state(frame, **extra):
    return {"session_id": "s", "frame_id": frame, "timestamp": frame,
            "map_id": 1, "position": {"x": .5, "y": .5}, "orientation": 0,
            "player_present": True, "active_quests": [], **extra}


def test_ui_open_close_transitions_are_first_class_events():
    world = WorldModel()
    world.ingest(Observation.create(_state(1, world_map_open=False), 1))
    world.ingest(Observation.create(_state(2, world_map_open=True), 2))
    world.ingest(Observation.create(_state(3, world_map_open=False), 3))
    events = [(item.event_type, item.payload) for item in world.event_records
              if item.event_type in {"UI_OPENED", "UI_CLOSED"}]
    assert events[0][0] == "UI_OPENED" and events[0][1]["ui_state"] == "WORLD_MAP"
    assert events[1][0] == "UI_CLOSED" and events[1][1]["ui_state"] == "WORLD_MAP"
