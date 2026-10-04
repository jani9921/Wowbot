from pathlib import Path
import tempfile

from wowbot.vision.map_mouseover import classify_tooltip, normalize_map_mouseover
from wowbot.vision.world_point_memory import WorldPointMemory


def test_tooltip_semantics():
    assert classify_tooltip("Turn in quest: A Test") == "QUEST_TURN_IN"
    assert classify_tooltip("Available quest: A Test") == "QUEST_GIVER"
    assert classify_tooltip("Quest objective") == "QUEST_RELATED"
    assert classify_tooltip("") == "UNKNOWN"


def test_world_map_mouseover_normalizes_and_persists_point():
    raw = {
        "surface": "WORLD_MAP", "semantic_type": "QUEST_TURN_IN", "map_id": 1409,
        "x": 0.423, "y": 0.671, "tooltip": "Turn in quest: Test",
        "unit": {"name": "Test NPC", "npc_id": 171997, "guid": "Creature-A"},
    }
    mouse = normalize_map_mouseover(raw)
    assert mouse is not None and mouse.x == 0.423
    with tempfile.TemporaryDirectory() as td:
        memory = WorldPointMemory(Path(td) / "world_points.sqlite3")
        key = memory.record(mouse, name="Test NPC", npc_id=171997, observed_at=1.0)
        assert key is not None
        rows = memory.points(1409)
        assert rows[0]["npc_id"] == 171997
        assert rows[0]["semantic_type"] == "QUEST_TURN_IN"
        memory.close()


def test_minimap_is_not_promoted_to_global_map_point():
    mouse = normalize_map_mouseover({"surface": "MINIMAP", "semantic_type": "QUEST_GIVER", "map_id": 1409, "local_x": .8, "local_y": .2})
    with tempfile.TemporaryDirectory() as td:
        memory = WorldPointMemory(Path(td) / "world_points.sqlite3")
        assert memory.record(mouse) is None
        memory.close()


def test_world_point_memory_age_gate():
    mouse = normalize_map_mouseover({"surface": "WORLD_MAP", "semantic_type": "QUEST_GIVER",
                                     "map_id": 1409, "x": .2, "y": .3, "tooltip": "Available quest"})
    with tempfile.TemporaryDirectory() as td:
        memory = WorldPointMemory(Path(td) / "world_points.sqlite3")
        memory.record(mouse, observed_at=10)
        assert memory.points(1409, as_of=20, max_age=20)
        assert memory.points(1409, as_of=100, max_age=20) == []
        memory.close()
