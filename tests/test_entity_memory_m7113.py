from pathlib import Path
import tempfile

from wowbot.vision.entity_memory import EntityMemory


def test_same_npc_id_aggregates_different_guid_instances():
    with tempfile.TemporaryDirectory() as tmp:
        memory = EntityMemory(Path(tmp) / "entities.sqlite3")
        a = {"unit_type": "NPC", "npc_id": 171997, "guid": "Creature-0-3768-2175-11502-171997-00001BBB8C", "name": "Woodlands Watcher"}
        b = {"unit_type": "NPC", "npc_id": 171997, "guid": "Creature-0-3768-2175-11502-171997-00001A6030", "name": "Woodlands Watcher"}
        assert memory.record_mouseover(a, map_id=1409, map_x=.4, map_y=.5, zone="Z", observed_at=1) == "npc:171997"
        assert memory.record_mouseover(b, map_id=1409, map_x=.41, map_y=.51, zone="Z", observed_at=2) == "npc:171997"
        summary = memory.summary("npc:171997")
        assert summary["seen_count"] == 2
        with memory._connect() as conn:
            rows = conn.execute("SELECT guid FROM entity_guids WHERE identity_key=? ORDER BY guid", ("npc:171997",)).fetchall()
        assert sorted(r[0] for r in rows) == sorted([a["guid"], b["guid"]])
        memory.close()


def test_guid_fallback_does_not_override_confirmed_npc_id():
    with tempfile.TemporaryDirectory() as tmp:
        memory = EntityMemory(Path(tmp) / "entities.sqlite3")
        entity = {"unit_type": "NPC", "npc_id": 171997, "guid": "Creature-0-1-2-3-171997-ABC"}
        assert memory.identity_key(entity) == "npc:171997"
        memory.close()
