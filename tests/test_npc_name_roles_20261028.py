"""Unlisted name prefixes and definite roles resolve to current TALK actors."""
from copy import deepcopy

import pytest

from test_reference_support_20261008 import raw_db
from wowbot.agent.conversation_actors import conversation_actors
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.quest_semantics import (npc_name_candidate_matches,
    speak_target_matches, unique_npc_name_candidates)
from wowbot.agent.reference_catalog import ReferenceCatalog
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, objective_npc_entries
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider


BAZENTUS, OTHER, RIFTWARDEN = 193464, 9003, 9004


@pytest.mark.parametrize("subject,name,expected", [
    ("Bazentus", "Forgemaster Bazentus", True),
    ("Zarenth", "Runesage Zarenth", True),  # no Runesage title whitelist
    ("the Forgemaster", "Forgemaster Bazentus", True),
    ("the High Forgemaster", "High Forgemaster Bazentus", True),
    ("Bazentus", "Forgemaster Bazentusson", False),
    ("Bazentus", "Forgemaster Bazen", False),
    ("the Forgemaster", "Forgemastery Apprentice", False),
    ("Left and Right", "Left Shark", False),
    ("Left and Right", "Someone Right", False),
    ("Left and Right", "Right", True),
    ("Captain", "Captain Someone", False),
])
def test_lexical_candidates_use_full_words_and_preserve_group_boundaries(subject, name, expected):
    assert npc_name_candidate_matches(subject, name) is expected


def test_distinct_full_names_are_ambiguous_but_static_variants_are_not():
    first = {"entry": 1, "name": "Runesage Zarenth"}
    variant = {"entry": 2, "name": "Runesage Zarenth"}
    other = {"entry": 3, "name": "Warden Zarenth"}
    assert unique_npc_name_candidates("Zarenth", [first, variant]) == [first, variant]
    assert unique_npc_name_candidates("Zarenth", [first, other]) == []
    exact = {"entry": 4, "name": "Zarenth"}
    assert unique_npc_name_candidates("Zarenth", [first, other, exact]) == [exact]


def test_a_generic_role_does_not_prefer_an_unrelated_npc_named_like_the_role():
    assert unique_npc_name_candidates("the Forgemaster", [
        {"entry": 1, "name": "Forgemaster"},
        {"entry": 2, "name": "Forgemaster Bazentus"}]) == []


@pytest.fixture
def provider(raw_db):
    import sqlite3
    with sqlite3.connect(raw_db) as db:
        db.executescript('''
            ALTER TABLE creature_template ADD COLUMN subname TEXT;
            ALTER TABLE creature_template ADD COLUMN TitleAlt TEXT;
            ALTER TABLE creature_template ADD COLUMN VerifiedBuild INTEGER;
            INSERT INTO creature_template VALUES
              (193464,'Forgemaster Bazentus','Obsidian Forgemaster',NULL,69497),
              (9003,'Forgemaster Durn','Blackrock Forgemaster',NULL,66384),
              (9004,'Halor','Riftwarden',NULL,69933),
              (9005,'Runesage Zarenth',NULL,NULL,69497),
              (9006,'Runesage Zarenth',NULL,NULL,69933),
              (9007,'Forgemaster',NULL,NULL,69497);
            UPDATE quest_objectives SET Type=0,ObjectID=999999 WHERE ID=700;
        ''')
    before = raw_db.read_bytes()
    catalogue = ReferenceCatalog(raw_db)
    value = TDBKnowledgeProvider(catalogue)
    yield value
    catalogue.close()
    assert raw_db.read_bytes() == before  # catalogue is never modified by resolution


def reference(provider, description):
    # A different objective description is a different cached quest context.
    value = deepcopy(provider.catalog.quest(7))
    value["objectives"][0]["description"] = description
    original = provider.catalog.quest
    provider.catalog.quest = lambda q: deepcopy(value)
    try:
        provider.quest.cache_clear()
        return provider.quest(7)
    finally:
        provider.catalog.quest = original


def guid(entry):
    return f"Creature-0-1-2444-1-{entry}-00001"


def state(provider, description, entries=(BAZENTUS,), *, distance=2.):
    record = reference(provider, description)
    return {"session_id": "name-role", "monotonic_time": 100., "map_id": 2022,
        "orientation": 0., "is_in_combat": False, "server_mode": {"active": True},
        "target": False, "mouseover": False, "quest_ui": {"open": False},
        "soft_targets_sample_time": 100.,
        "soft_targets": [{"guid": guid(entries[0]), "source_unit": "softinteract"}] if entries else [],
        "player_world_position": {"x": 0., "y": 0., "z": 100., "z_known": True, "instance_id": 2444},
        "active_quests": [{"quest_id": 7, "is_complete": False, "objectives": [
            {"description": "0/1 "+description, "current": 0, "required": 1, "is_complete": False}]}],
        "reference_knowledge": {"quests": {"7": record}},
        "packet_entities": {guid(entry): {"guid": guid(entry), "entry_id": entry,
            "kind": "CREATURE", "map_id": 2444, "info": {"npc_flags": 1},
            "position": {"x": distance, "y": 0., "z": 100., "source": "PACKET_CREATE_MOVEMENT"}}
            for entry in entries}}


def test_unknown_prefix_is_resolved_from_tdb_without_extending_the_title_list(provider):
    assert {r["entry"] for r in provider.creatures_addressed("Zarenth")} == {9005, 9006}
    live = state(provider, "Speak with Zarenth", (9005,), distance=30.)
    proposal = ServerNpcInteractionPolicy().propose(live)[0]
    assert proposal.skill == "MOVE" and proposal.parameters["server_entity_guid"] == guid(9005)


def test_named_bazentus_still_uses_the_actual_guid_and_exact_recipient(provider):
    live = state(provider, "Speak with Bazentus")
    proposal = ServerNpcInteractionPolicy().propose(live)[0]
    assert proposal.skill == "INTERACT" and proposal.parameters["soft_guid"] == guid(BAZENTUS)
    live["soft_targets"][0]["guid"] = guid(OTHER)
    assert not any(p.skill == "INTERACT" for p in ServerNpcInteractionPolicy().propose(live))


@pytest.mark.parametrize("description,entry", [
    ("Speak with the Forgemaster", BAZENTUS),
    ("Speak with the Obsidian Forgemaster", BAZENTUS),
    ("Speak with the Riftwarden", RIFTWARDEN),
])
def test_roles_use_current_actors_and_their_own_tdb_subtitles(provider, description, entry):
    live = state(provider, description, (entry,))
    assert [r["entry"] for r in conversation_actors(live, 7)] == [entry]
    proposal = ServerNpcInteractionPolicy().propose(live)[0]
    assert proposal.skill == "INTERACT" and proposal.parameters["npc_id"] == entry


def test_global_forgemaster_candidates_are_not_static_approach_targets(provider):
    record = reference(provider, "Speak with the Forgemaster")["objectives"][0]
    assert record["credit_action"] == "TALK" and record["talk_creatures"] == []
    assert {r["entry"] for r in record["talk_actor_candidates"]} == {BAZENTUS, OTHER, 9007}
    assert not record["named_creatures"]


def test_two_present_forgemasters_remain_ambiguous_instead_of_picking_the_closest(provider):
    live = state(provider, "Speak with the Forgemaster", (BAZENTUS, OTHER))
    assert conversation_actors(live, 7) == []
    assert objective_npc_entries(live) == {}
    assert ServerNpcInteractionPolicy().propose(live) == []


def test_explicit_quest_actor_relation_disambiguates_the_two_present_forgemasters(provider):
    live = state(provider, "Speak with the Forgemaster", (BAZENTUS, OTHER))
    live["reference_knowledge"]["quests"]["7"]["quest_roles"].append(
        {"npc_id": BAZENTUS, "name": "Forgemaster Bazentus", "role": "QUEST_ENDER"})
    assert [r["entry"] for r in conversation_actors(live, 7)] == [BAZENTUS]


@pytest.mark.parametrize("description", ["Speak with the Forgemaster", "Speak with Bazentus"])
def test_name_matching_does_not_repair_a_contradictory_explicit_npc_id(provider, description):
    live = state(provider, description)
    objective = live["active_quests"][0]["objectives"][0]
    objective["target_entity"] = {"npc_id": OTHER}
    assert conversation_actors(live, 7) == []
    assert not speak_target_matches(objective, {"guid": guid(BAZENTUS), "npc_id": BAZENTUS,
        "name": "Forgemaster Bazentus", "attackable": False})
    assert str(BAZENTUS) not in objective_npc_entries(live)
    assert not any(p.parameters.get("npc_id") == BAZENTUS for p in ServerNpcInteractionPolicy().propose(live))


def test_a_template_named_forgemaster_does_not_bypass_role_ambiguity(provider):
    live = state(provider, "Speak with the Forgemaster", (9007, BAZENTUS))
    assert conversation_actors(live, 7) == []
    assert objective_npc_entries(live) == {}


@pytest.mark.parametrize("change", ["removed", "wrong_map", "done", "not_talkable", "wrong_guid_entry"])
def test_role_candidates_do_not_override_current_server_evidence(provider, change):
    live = state(provider, "Speak with the Forgemaster")
    unit = live["packet_entities"][guid(BAZENTUS)]
    if change == "removed": unit["removed"] = True
    elif change == "wrong_map": unit["map_id"] = 2175
    elif change == "done": live["active_quests"][0]["objectives"][0]["is_complete"] = True
    elif change == "not_talkable": unit["info"]["npc_flags"] = 0
    else: unit["entry_id"] = OTHER
    assert conversation_actors(live, 7) == []


def test_resolved_role_can_select_an_actual_quest_gossip_row(provider):
    live = state(provider, "Speak with the Forgemaster")
    option = {"id": 91, "name": "(Quest) I am ready.", "quest_label_prepend": True,
        "available": True, "x": .1, "y": .3}
    live["quest_ui"] = {"open": True, "npc_guid": guid(BAZENTUS),
        "action": "GOSSIP_OPTION_SELECT", "gossip_options": [option], "gossip_option": option}
    proposal = QuestDialogPlanningPolicy._talk_gossip(live, True)
    assert proposal is not None and proposal.parameters["target_guid"] == guid(BAZENTUS)
    assert proposal.parameters["gossip_option_id"] == 91


def test_newest_entry_revision_wins_even_when_only_the_old_name_matched(tmp_path):
    import sqlite3
    from types import SimpleNamespace
    from wowbot.agent.reference_world_sqlite import WorldSqliteReference
    import threading

    path = tmp_path / "versions.sqlite3"
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE creature_template(entry INTEGER,name TEXT,subname TEXT,VerifiedBuild INTEGER);
        INSERT INTO creature_template VALUES(1,'Runesage Zarenth','Riftwarden',66384),
        (1,'Renamed NPC','Different role',-69933),
        (2,'Runesage Zarenth',NULL,69497);''')
    raw = WorldSqliteReference(db, threading.RLock(), path, {"creature_template"})
    value = TDBKnowledgeProvider(SimpleNamespace(raw=raw))
    try:
        assert value.creatures_addressed("Zarenth") == [{"entry": 2, "name": "Runesage Zarenth"}]
        assert value.creatures_addressed("the Riftwarden") == []
    finally:
        db.close()


def test_an_old_exact_name_cannot_hide_two_distinct_current_partial_matches(tmp_path):
    import sqlite3
    import threading
    from types import SimpleNamespace
    from wowbot.agent.reference_world_sqlite import WorldSqliteReference

    path = tmp_path / "renamed.sqlite3"
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE creature_template(entry INTEGER,name TEXT,VerifiedBuild INTEGER);
        INSERT INTO creature_template VALUES(1,'Zarenth',66384),
        (1,'Warden Zarenth',-69933),(2,'Runesage Zarenth',69497);''')
    raw = WorldSqliteReference(db, threading.RLock(), path, {"creature_template"})
    value = TDBKnowledgeProvider(SimpleNamespace(raw=raw))
    try:
        assert value.creatures_addressed("Zarenth") == []
        assert {r["name"] for r in value.creature_name_candidates("Zarenth")} == {
            "Warden Zarenth", "Runesage Zarenth"}
    finally:
        db.close()
