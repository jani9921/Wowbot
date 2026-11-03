"""Real SQLite catalogue read-ahead remains conditional and readonly."""
import sqlite3
from types import SimpleNamespace

import pytest

from test_reference_support_20261008 import raw_db, state
from wowbot.agent.models import Goal, Observation
from wowbot.agent.quest_agenda import QuestAgenda
from wowbot.agent.spatial_memory import SpatialMemory
from wowbot.agent.world import WorldModel
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider


@pytest.fixture
def chain_memory(raw_db, tmp_path):
    with sqlite3.connect(raw_db) as db:
        db.executescript('''
            ALTER TABLE quest_template ADD COLUMN RewardNextQuest INTEGER DEFAULT 0;
            UPDATE quest_template SET RewardNextQuest=9 WHERE ID=7;
            INSERT INTO quest_template(ID,LogTitle,QuestDescription,AllowableRaces,RewardNextQuest)
                VALUES(9,'Follow-up from catalogue','Conditional future quest',1,0);
            INSERT INTO creature_queststarter VALUES(100,9,123);
        ''')
    memory = SpatialMemory(tmp_path / "profile", reference_path=raw_db)
    yield memory, raw_db
    memory.entities.close()
    memory.points.close()


def test_tdb_followup_is_prefetched_with_starter_location_but_not_a_live_offer(chain_memory):
    memory, path = chain_memory
    before = path.read_bytes()
    current = state()
    current.update(monotonic_time=10., player_present=True)
    current["reference_knowledge"] = memory.knowledge.snapshot(current, 10.)
    followups = current["reference_knowledge"]["quests"]["7"]["follow_up_candidates"]
    assert followups[0]["quest_id"] == 9
    assert followups[0]["availability"] == "REQUIRES_LIVE_AVAILABILITY"
    model = WorldModel()
    model.ingest(Observation.create(current, 10.))
    agenda = QuestAgenda()
    agenda.refresh(Goal.parse("Questelj", 1.), model, 10.)
    projected = {step["key"]: step for step in agenda.steps}
    future = projected["followup:7:9"]
    assert future["status"] == "BLOCKED" and future["npc_ids"] == ["100"]
    assert future["location"]["x"] == 20. and future["location"]["y"] == 30.
    assert "accept:9" not in projected and 9 not in model.quest_model.records
    assert path.read_bytes() == before


def test_followup_reads_are_cached_and_uncached_queries_obey_budget(chain_memory, monkeypatch):
    memory, _ = chain_memory
    knowledge = memory.knowledge
    reference = knowledge.tdb.quest(7)
    calls = []
    original = knowledge.tdb.quest_locations
    def counted(record, *args, **kwargs):
        calls.append(record["quest_id"])
        return original(record, *args, **kwargs)
    monkeypatch.setattr(knowledge.tdb, "quest_locations", counted)
    assert knowledge.followups(reference, state(), 10., [0]) == []
    budget = [1]
    first = knowledge.followups(reference, state(), 10., budget)
    assert first and budget == [0] and calls == [9]
    assert knowledge.followups(reference, state(), 11., [0]) == first
    assert calls == [9]
    other_phase = {**state(), "phase": 2}
    assert knowledge.followups(reference, other_phase, 11., [0]) == []


def test_gossip_offers_prefetch_objective_area_but_do_not_start_the_quest(chain_memory):
    memory, path = chain_memory
    current = state()
    current["active_quests"] = []
    current.update(monotonic_time=10., player_present=True, quest_ui={"open": True,
        "entries": [{"kind": "AVAILABLE", "quest_id": 7, "title": "Rescue"}]})
    before = path.read_bytes()
    current["reference_knowledge"] = memory.knowledge.snapshot(current, 10.)
    assert current["reference_knowledge"]["quests"]["7"]["live_status"] == "AVAILABLE_API"
    model = WorldModel()
    model.ingest(Observation.create(current, 10.))
    agenda = QuestAgenda()
    agenda.refresh(Goal.parse("Questelj", 1.), model, 10.)
    tasks = {step["key"]: step for step in agenda.steps}
    assert tasks["accept:7"]["status"] == "READY"
    future = tasks["future-work:7"]
    assert future["status"] == "BLOCKED" and future["location"]["x"] == 20.
    assert future["location"]["y"] == 30. and not model.quest_model.ready()
    assert path.read_bytes() == before


def test_many_close_objective_spawns_cannot_hide_the_known_far_ender():
    def spawns(instance, entry):
        if entry == 100:
            return [{"spawn_id": 1, "world_map_id": instance, "x": 500., "y": 0., "z": 10.}]
        return [{"spawn_id": i+10, "world_map_id": instance, "x": i+1., "y": 0., "z": 10.}
                for i in range(80)]
    provider = TDBKnowledgeProvider(SimpleNamespace(raw=None, spawn_candidates=spawns))
    reference = {"quest_roles": [{"npc_id": 100, "role": "QUEST_ENDER"}], "objectives": [
        {"raw_type": 0, "objective_id": 700, "named_creatures": [{"entry": 200, "name": "Mob"}]}]}
    rows = provider.quest_locations(reference, {"player_world_position": {"instance_id": 2175, "x": 0., "y": 0.}})
    assert len(rows) == 32
    assert any(row["entry"] == 100 and row["role"] == "QUEST_ENDER" for row in rows)
    assert sum(row["role"] == "OBJECTIVE" for row in rows) == 31
    assert max(row["x"] for row in rows if row["role"] == "OBJECTIVE") == 31.
