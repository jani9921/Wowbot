"""Objective mechanisms read ahead from TDB + client DB2 (user 2026-10-26:
prepare for quest kinds instead of rewriting mechanics after each live run).
The runtime query source and the census index source must agree."""
import sqlite3
import sys
from pathlib import Path

import pytest

from wowbot.quests.objective_mechanics import (COVERAGE, Db2IndexFacts, TdbIndexFacts, TdbQueryFacts, classify,
                                               credit_spells, objective_facts, text_hint)


def facts(**values):
    return {"type": 0, **values}


@pytest.mark.parametrize("given, expected", [
    # live 2026-10-26: Blacktalons (66078), Kavia's scope, Edress, the whelp
    (facts(gossip_actor=True, credit_sources=True), "GOSSIP_ACTOR"),
    (facts(gossip_actor=True, credit_casters=["GAMEOBJECT", "UNKNOWN"]), "CREDIT_OBJECT"),
    (facts(gossip_actor=True, spawned=True), "TALK"),
    (facts(spellclick=True, vehicle=True), "SPELLCLICK_VEHICLE"),
    (facts(spellclick=True), "SPELLCLICK"),
    (facts(credit_casters=["CREATURE"]), "VEHICLE_ABILITY"),
    (facts(credit_casters=["UNKNOWN"], quest_items=True), "USE_ITEM"),
    (facts(mount_credit=True, proxy=True, gossip_actor=True, credit_sources=True), "MOUNT"),
    (facts(ride_credit=True), "SPELLCLICK_VEHICLE"),
    (facts(talk_credit=True, spawned=True), "TALK"),
    (facts(credit_sources=True), "KILL"),
    (facts(spawned=True), "KILL"),
    (facts(proxy=True), "PROXY_UNKNOWN"),
    # a technical credit filled by real creatures' KillCredit ("Harpies and
    # cohorts slain"); a stray gossip flag on one of them is no duel
    (facts(proxy=True, gossip_actor=True, credit_sources=True), "KILL"),
    (facts(named_credit=True), "KILL"),                   # a named creature the TDB never spawned
    (facts(), "UNRESOLVED"),
    ({"type": 14, "vendor_buy": True}, "COLLECT_VENDOR"),
    ({"type": 1, "item_sources": {"CREATURE", "VENDOR"}}, "COLLECT_DROP"),
    ({"type": 1, "item_sources": {"GAMEOBJECT"}}, "COLLECT_OBJECT"),
    ({"type": 1, "item_sources": {"CONTAINER"}}, "COLLECT_CONTAINER"),
    ({"type": 1, "item_sources": set()}, "COLLECT_OTHER"),
    ({"type": 2}, "OBJECT_USE"), ({"type": 15}, "PROGRESS_BAR"), ({"type": 19}, "AREA_TRIGGER"),
    ({"type": 14}, "CRITERIA_TREE"), ({"type": 11}, "PET_BATTLE"), ({"type": 99}, "OTHER"),
])
def test_classify(given, expected):
    assert classify(given)["mechanism"] == expected
    assert expected in COVERAGE


@pytest.mark.parametrize("text, expected", [
    ("Talk to Marithos", "TALK"), ("0/1 Huk Huk the Hozen Chieftain confronted", "TALK"),
    ("Dance Party Started", "EMOTE"), ("Arrive at the meeting", "ARRIVE"),
    ("Memory of Erasure witnessed", "WITNESS"), ("Collector used on live Oozelings", "USE_ITEM"),
    ("Open the escape pod", "INTERACT"), ("Convoy protected", "ESCORT"), ("Harpies slain", "KILL"),
    ("", None), ("Tyrhold Trial", None),
])
def test_text_hints(text, expected):
    assert text_hint(text) == expected


def test_text_hints_only_replace_unknown_sources():
    assert classify(facts(proxy=True, description="Dance Party Started")) == {
        "mechanism": "EMOTE", "tags": ["FROM_TEXT", "PROXY_CREDIT"]}
    assert classify(facts(spawned=True, description="Dance Party Started"))["mechanism"] == "KILL"
    assert classify(facts(named_credit=True))["tags"] == ["NO_TDB_SPAWN"]


@pytest.fixture
def world_db(tmp_path):
    path = tmp_path / "world.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE creature_template (entry, name, npcflag, VehicleId, ScriptName, KillCredit1, KillCredit2);
        CREATE TABLE creature (guid, id);
        CREATE TABLE npc_spellclick_spells (npc_entry, spell_id);
        CREATE TABLE creature_template_gossip (CreatureID, MenuID);
        CREATE TABLE conversation_actors (ConversationId, CreatureId);
        CREATE TABLE gameobject_template (entry, type, name, Data0, Data10);
        CREATE TABLE creature_template_spell (CreatureID, "Index", Spell);
        CREATE TABLE creature_questitem (CreatureEntry, ItemId);
        CREATE TABLE gameobject_questitem (GameObjectEntry, ItemId);
        CREATE TABLE npc_vendor (entry, item);
        CREATE TABLE creature_loot_template (Entry, ItemType, Item);
        CREATE TABLE item_loot_template (Entry, ItemType, Item);
        CREATE TABLE quest_template (ID, LogTitle, LogDescription, QuestDescription, Expansion, StartItem,
                                     ItemDrop1, ItemDrop2, ItemDrop3, ItemDrop4);
        CREATE TABLE quest_template_addon (ID, SourceSpellID, ScriptName);
        CREATE TABLE quest_objectives (ID, QuestID, Type, "Order", ObjectID, Description);
        INSERT INTO creature_template VALUES
            (187158, 'Blacktalon Avenger', 0, 0, '', 0, 0),
            (187187, 'Blacktalon Avenger', 1, 0, '', 187158, 0),
            (189507, 'Talonstalker Kavia', 3, 0, '', 0, 0),
            (191503, 'Kill Credit: Ride Any Dragonriding Mount [DNT]', 0, 0, '', 0, 0),
            (200001, 'Ruby Whelpling', 16777216, 7, '', 0, 0),
            (200002, 'Wild Boar', 0, 0, '', 0, 0);
        INSERT INTO creature VALUES (1, 187187), (2, 189507), (3, 200001), (4, 200002);
        INSERT INTO npc_spellclick_spells VALUES (200001, 4444);
        INSERT INTO creature_template_gossip VALUES (189507, 1);
        INSERT INTO gameobject_template VALUES (376824, 22, 'Scouting Scope', 309772, 0);
        INSERT INTO creature_loot_template VALUES (200002, 0, 900);
        INSERT INTO item_loot_template VALUES (800, 0, 901);
        INSERT INTO quest_template VALUES
            (66078, 'Sharp Practice', '', '', 9, 0, 0, 0, 0, 0),
            (66048, 'Best Plans and Intentions', '', '', 9, 0, 0, 0, 0, 0),
            (70061, 'Training Wings', '', '', 9, 0, 0, 0, 0, 0);
        INSERT INTO quest_objectives VALUES
            (1, 66078, 0, 0, 187158, 'Blacktalon tested'),
            (2, 66048, 0, 0, 189507, 'Talonstalker Kavia consulted'),
            (3, 70061, 0, 0, 200001, 'Ruby Whelpling chosen'),
            (4, 70061, 1, 1, 900, 'Boar hide'),
            (5, 70061, 1, 2, 901, 'Spare part'),
            (6, 70061, 0, 3, 191503, 'Hop on a dragonriding mount');
    """)
    db.commit()
    db.close()
    return path


@pytest.fixture
def client_db(tmp_path):
    path = tmp_path / "client.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE spell_effects (id INTEGER PRIMARY KEY, spell_id, effect, aura, trigger_spell,
                                    difficulty_id, misc1, misc2);
        INSERT INTO spell_effects VALUES (1, 309772, 90, 0, 0, 0, 189507, 0),
                                         (2, 500, 64, 0, 309772, 0, 0, 0);
    """)
    db.commit()
    db.close()
    return path


def test_query_and_index_sources_agree(world_db, client_db):
    connection = sqlite3.connect(world_db)
    connection.row_factory = sqlite3.Row
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    query = TdbQueryFacts(lambda sql, args=(): [dict(row) for row in connection.execute(sql, args)], tables)
    index = TdbIndexFacts(sqlite3.connect(world_db))
    db2 = Db2IndexFacts(sqlite3.connect(client_db))
    assert credit_spells(db2, 189507) == {309772, 500}                      # one trigger hop
    expected = {187158: "GOSSIP_ACTOR", 189507: "CREDIT_OBJECT", 200001: "SPELLCLICK_VEHICLE", 191503: "MOUNT"}
    for entry, mechanism in expected.items():
        for source in (query, index):
            assert classify(objective_facts(source, db2, kind=0, credit_entry=entry))["mechanism"] == mechanism
    for item, mechanism in ((900, "COLLECT_DROP"), (901, "COLLECT_CONTAINER"), (902, "COLLECT_OTHER")):
        for source in (query, index):
            assert classify(objective_facts(source, db2, kind=1, credit_entry=item))["mechanism"] == mechanism


def test_census_tool_writes_the_report(world_db, client_db, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import quest_mechanics_census
    report, data = tmp_path / "QUEST_MECHANICS.md", tmp_path / "quest_mechanics.json"
    assert quest_mechanics_census.main(["--tdb", str(world_db), "--catalog", str(client_db),
                                        "--report", str(report), "--json", str(data)]) == 0
    text = report.read_text(encoding="utf-8")
    assert "| `GOSSIP_ACTOR` | PARTIAL |" in text and "| `CREDIT_OBJECT` | LIVE |" in text
    assert "66078 Sharp Practice — Blacktalon tested" in text
