"""Routes around hostile elites, rares and mob clusters (user 2026-10-20).

"Csináld meg mind": PixelBuddy's path service avoids dangerous spawns; ours
uses TDB spawns + FactionTemplate.db2 hostility and the live server units.
"""
import math
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from wowbot.navigation.contracts import NavigationRequest
from wowbot.navigation.danger import DangerMap
from wowbot.navigation.global_planner import GlobalNavigator
from wowbot.navigation.spawn_threats import (ALLIANCE_TEMPLATE, HORDE_TEMPLATE, SpawnThreats,
                                             side_template)
from wowbot.world_geometry.faction_templates import FactionTemplate, FactionTemplates

MONSTER, BEAST, ALLIANCE_GUARD = 14, 7, 12
FACTIONS = FactionTemplates({
    1: FactionTemplate(1, 1, 3, 2, 12, (), ()),           # Human player
    2: FactionTemplate(2, 2, 5, 4, 10, (), ()),           # Orc player
    MONSTER: FactionTemplate(14, 14, 8, 0, 1, (), ()),
    BEAST: FactionTemplate(7, 7, 0, 0, 0, (), ()),
    ALLIANCE_GUARD: FactionTemplate(12, 72, 2, 2, 4, (), (72,)),
})
# entry: (faction, Classification, unit_flags, npcflag)
TEMPLATES = {100: (MONSTER, 0, 0, 0), 101: (MONSTER, 1, 0, 0), 102: (MONSTER, 4, 0, 0),
             103: (BEAST, 1, 0, 0), 104: (MONSTER, 1, 0x100, 0), 105: (MONSTER, 1, 0, 2),
             106: (MONSTER, 6, 0, 0), 107: (ALLIANCE_GUARD, 1, 0, 0), 108: (MONSTER, 1, 0, 0)}


@pytest.fixture
def threats(tmp_path):
    path = tmp_path / "tdb.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE creature_template (entry, faction, Classification, unit_flags, npcflag)")
    db.execute("CREATE TABLE creature (guid, id, map, position_x, position_y, position_z, wander_distance,"
               " unit_flags, npcflag)")
    db.executemany("INSERT INTO creature_template VALUES (?, ?, ?, ?, ?)",
                   [(entry, *values) for entry, values in TEMPLATES.items()])
    spawns = [(101, 100., 5.), (102, 200., -5.), (103, 300., 0.), (104, 400., 0.), (105, 500., 0.),
              (106, 600., 0.), (107, 700., 0.), (101, 100., 400.)]          # last one far off the way
    spawns += [(100, 800. + dx, dy) for dx, dy in ((0., 0.), (6., 3.), (3., -6.))]   # a camp of three
    spawns += [(100, 900., 0.)]                                                    # a lone mob
    db.executemany("INSERT INTO creature VALUES (?, ?, 1, ?, ?, 0, 0, NULL, NULL)",
                   [(k, npc, x, y) for k, (npc, x, y) in enumerate(spawns)])
    db.commit()
    db.close()
    return SpawnThreats(path, FACTIONS)


def kinds(entries):
    return sorted((entry["kind"], entry["entity_id"]) for entry in entries)


def test_only_attackable_hostile_elites_rares_and_camps_on_the_way(threats):
    entries = threats.dangers(1, (0., 0.), (1000., 0.), margin=50., race="Human")
    assert kinds(entries) == [("ELITE_SPAWN", "npc:101"), ("HOSTILE_CLUSTER", "npc:100"),
                              ("RARE_SPAWN", "npc:102")]
    camp = next(entry for entry in entries if entry["kind"] == "HOSTILE_CLUSTER")
    assert math.hypot(camp["x"]-803., camp["y"]+1.) < 1. and camp["radius"] > 10.


def test_the_opposite_side_s_guards_are_threats_and_single_mobs_on_request(threats):
    horde = threats.dangers(1, (0., 0.), (1000., 0.), margin=50., race="Orc", include_single=True)
    assert ("ELITE_SPAWN", "npc:107") in kinds(horde)
    assert ("HOSTILE_SPAWN", "npc:100") in kinds(horde)                  # the lone mob at 900
    assert side_template("Human") == ALLIANCE_TEMPLATE and side_template("Undead") == HORDE_TEMPLATE
    assert side_template("Pandaren") is None


def test_objective_creatures_are_exempt_and_live_units_replace_their_spawns(threats):
    assert ("ELITE_SPAWN", "npc:101") not in kinds(
        threats.dangers(1, (0., 0.), (1000., 0.), margin=50., race="Human", exempt_npc_ids={101}))
    live = threats.dangers(1, (0., 0.), (1000., 0.), margin=50., race="Human",
                           live_units=[(101, 120., 8., 0.), (108, 50., 2., 0.)])
    elites = [entry for entry in live if entry["kind"] == "ELITE_SPAWN"]
    assert sorted(round(entry["x"]) for entry in elites) == [50, 120]     # spawn at 100 replaced


def route_planner():
    def find_path(instance_id, start, end):
        return SimpleNamespace(anchors=({"x": start["x"], "y": start["y"], "z": 0.},
                                        {"x": end["x"], "y": end["y"], "z": 0.}), cost=0.,
                               tile_count=1, polygon_count=1)
    navmesh = SimpleNamespace(find_path=find_path, project_position=lambda *a, **k: {"z": 0.})
    return GlobalNavigator(navmesh=navmesh, walkable=lambda instance, point: {"z": 0.})


def plan(danger, **flags):
    request = NavigationRequest("r", "c", "MOVE_TO_LOCATION",
                                {"x": 200., "y": 0., "z": 0., "instance_id": 1, "coordinate_space": "WORLD_YARDS"},
                                **flags)
    state = {"player_world_position": {"x": 0., "y": 0., "z": 0., "instance_id": 1,
                                       "coordinate_space": "WORLD_YARDS"}}
    return route_planner().plan(request, state, 1., danger_map=danger)


def danger_with(kind):
    danger = DangerMap()
    danger.add(danger_id="d", kind=kind, x=100., y=0., radius=20., cost=8., confidence=.8,
               now=0., ttl=600., source="TDB_SPAWN", entity_id="npc:101")
    return danger


def test_a_trip_goes_around_an_elite_through_navmesh_legs():
    route = plan(danger_with("ELITE_SPAWN"))
    assert len(route.anchors) > 2
    assert min(math.hypot(point["x"]-100., point["y"]) for point in route.anchors) >= 20.
    assert route.regions[0]["danger_adapted"] is True


def test_combat_trips_and_single_mobs_keep_the_straight_route():
    assert len(plan(danger_with("ELITE_SPAWN"), allow_combat=True).anchors) == 2
    assert len(plan(danger_with("HOSTILE_SPAWN")).anchors) == 2
    assert len(plan(danger_with("HOSTILE_SPAWN"), avoid_combat=True).anchors) > 2


MAPS = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\dbc\enUS\FactionTemplate.db2")


@pytest.mark.skipif(not MAPS.is_file(), reason="client FactionTemplate.db2 not extracted")
def test_the_client_faction_templates_read_as_trinitycore_does():
    factions = FactionTemplates.load(MAPS)
    assert factions.hostile_to_player(14) and not factions.hostile_to_player(7)
    assert factions.hostile_to_player(2, ALLIANCE_TEMPLATE) and not factions.hostile_to_player(2, HORDE_TEMPLATE)
    assert factions.hostile_to_player(12, HORDE_TEMPLATE) and not factions.hostile_to_player(12, ALLIANCE_TEMPLATE)


# --- Ymir fills the learned TDB (user 2026-10-21) ---------------------------------

def packet(guid, kind, entry, x, y, *, dynamic=0, removed=False):
    return guid, {"guid": guid, "kind": kind, "entry_id": entry, "map_id": 1, "removed": removed,
                  "dynamic_flags": {"value": dynamic},
                  "position": {"x": x, "y": y, "z": 5., "source": "PACKET_CREATE"}}


def test_server_shown_creatures_and_objects_are_learned_once_per_guid(tmp_path):
    from wowbot.agent.learned_world import LearnedWorld, PacketSpawnLearner
    learned = LearnedWorld(tmp_path / "tdb_learned.sqlite3")
    learner = PacketSpawnLearner(learned)
    entities = dict([packet("Creature-1", "CREATURE", 101, 100., 5.),
                     packet("GameObject-1", "GAMEOBJECT", 500, 50., 50.),
                     packet("Creature-2", "CREATURE", 100, 10., 10., dynamic=0x4),     # our corpse
                     packet("Creature-3", "CREATURE", 100, 20., 20., removed=True),
                     packet("Player-1", "PLAYER", 0, 0., 0.)])
    learner.observe({"packet_entities": entities}, 1.)
    learner.observe({"packet_entities": entities}, 2.)                               # same GUIDs again
    learner.observe({"packet_entities": dict([packet("Creature-4", "CREATURE", 101, 103., 7.)])}, 3.)
    learner.flush(4., wait=True)
    creature = learned.spawns(1, "CREATURE", entry=101)
    assert len(creature) == 1 and creature[0]["seen_count"] == 2                  # 3.6 yd apart: one place
    assert creature[0]["location_kind"] == "SERVER_POSITION"
    assert len(learned.spawns(1, "GAMEOBJECT", entry=500)) == 1
    assert learned.spawns(1, "CREATURE", entry=100) == []
    learned.close()


def test_route_danger_reads_the_learned_tdb(threats, tmp_path):
    from wowbot.agent.learned_world import LearnedWorld
    learned = LearnedWorld(tmp_path / "learned.sqlite3")
    learned.record_spawns([("CREATURE", 108, None, {"x": 400., "y": 2., "z": 0., "instance_id": 1}, None, 1.),
                           ("CREATURE", 101, None, {"x": 105., "y": 4., "z": 0., "instance_id": 1}, None, 1.)],
                          source="YMIR_PACKET")
    learned.close()
    with_learned = SpawnThreats(threats.reference_path, FACTIONS, learned_path=tmp_path / "learned.sqlite3")
    elites = [entry for entry in with_learned.dangers(1, (0., 0.), (1000., 0.), margin=50., race="Human")
              if entry["kind"] == "ELITE_SPAWN"]
    # The learned 108 is new; the learned 101 near its TDB spawn adds nothing.
    assert sorted(entry["entity_id"] for entry in elites) == ["npc:101", "npc:108"]


def test_navigation_adds_spawn_and_live_threats_but_not_the_target_or_corpses(threats):
    from wowbot.navigation import NavigationService
    nav = NavigationService()
    nav._spawn_threats = threats
    request = NavigationRequest("r", "c", "MOVE_TO_LOCATION",
                                {"x": 1000., "y": 0., "instance_id": 1, "coordinate_space": "WORLD_YARDS",
                                 "npc_id": 102})
    state = {"race": "Human",
             "player_world_position": {"x": 0., "y": 0., "instance_id": 1, "coordinate_space": "WORLD_YARDS"},
             "packet_entities": dict([packet("Creature-9", "CREATURE", 108, 500., 3.),
                                      packet("Creature-8", "CREATURE", 108, 650., 0., dynamic=0x4)])}
    nav._observe_spawn_threats(request, state, 1.)
    found = {(entry["kind"], round(entry["x"])) for entry in nav._danger.snapshot(1.)}
    assert ("ELITE_SPAWN", 100) in found and ("ELITE_SPAWN", 500) in found
    assert ("ELITE_SPAWN", 650) not in found                                     # a corpse
    assert not any(kind == "RARE_SPAWN" for kind, _ in found)                    # the trip's own target
    combat = NavigationService()
    combat._spawn_threats = threats
    combat._observe_spawn_threats(NavigationRequest("r", "c", "MOVE_TO_LOCATION", request.destination,
                                                    allow_combat=True), state, 1.)
    assert combat._danger.snapshot(1.) == []
