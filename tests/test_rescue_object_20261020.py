"""Explorers in Peril (70122), The Waking Shores, live 2026-10-20 12:57-12:59.

"Professor Cogcatcher rescued" (TDB credit "Kill Credit: Rescue Cogcatcher
[DNT]", named creature 189053) arrived from the quest API as KILL.  The server
showed Cogcatcher at (3587.4, -2014.3, 11.3) and a "Protodragon Rib Cage"
(GOOBER 379137, dynamic flags 0x8000, no Activate) at (3588.1, -2014.3, 11.6),
0.76 yd away.  The agent searched for hostiles, came within 3.2 yd with the
cursor on Cogcatcher and never pressed Interact.
"""
import math

from wowbot.agent.models import Command
from wowbot.agent.packet_entity_facts import RESCUE_BASIS, rescue_objects, server_object_interactable
from wowbot.agent.rescue_object_planning import RescueObjectPolicy
from wowbot.runtime.skill_identity import check_command_identity
from wowbot.skills.object_use import ObjectUseSkill

COG = "Creature-0-3774-2444-5907-189053-00005025ED"
CAGE = "GameObject-0-3774-2444-5907-379137-00005025ED"
CHAIR = "GameObject-0-3774-2444-5907-381910-00005025EB"
DRAKE = "Creature-0-1465-2444-287632-193806-0000574990"


def unit(guid, entry, x, y, z, flags=0):
    return {"guid": guid, "kind": "CREATURE", "entry_id": entry, "map_id": 2444,
            "info": {"object_kind": "UNIT", "npc_flags": flags},
            "position": {"x": x, "y": y, "z": z, "source": "PACKET_CREATE_MOVEMENT", "age": 9.}}


def go(guid, entry, x, y, z, go_type, flags=0x8000):
    return {"guid": guid, "kind": "GAMEOBJECT", "entry_id": entry, "map_id": 2444,
            "info": {"object_kind": "GAMEOBJECT", "go_type": go_type, "quest_objective_id": 0},
            "dynamic_flags": {"value": flags},
            "position": {"x": x, "y": y, "z": z, "source": "PACKET_CREATE_STATIONARY", "age": 9.}}


def state(x=3560., y=-2000., z=11.3, facing=0., *, done=False, extra=(), soft=(), combat=False):
    entities = [unit(COG, 189053, 3587.4, -2014.3, 11.3), go(CAGE, 379137, 3588.1, -2014.3, 11.6, 10),
                *extra]
    return {"monotonic_time": 100., "map_id": 2022, "orientation": facing, "is_in_combat": combat,
            "soft_targets": list(soft), "soft_targets_sample_time": 99.9,
            "player_world_position": {"x": x, "y": y, "z": z, "z_observed": True, "instance_id": 2444,
                                      "coordinate_space": "WORLD_YARDS"},
            "active_quests": [{"quest_id": 70122, "is_complete": False, "title": "Explorers in Peril",
                               "objectives": [
                {"description": f"{int(done)}/1 Professor Cogcatcher rescued", "is_complete": done,
                 "raw_type": "monster", "type": "KILL"},
                {"description": "0/1 Archivist Rellid rescued", "is_complete": False,
                 "raw_type": "monster", "type": "KILL"}]}],
            "reference_knowledge": {"quests": {"70122": {"objectives": [
                {"objective_id": 429852, "credit_kind": "CREATURE_CREDIT", "credit_object_id": 194139,
                 "description": "Professor Cogcatcher rescued",
                 "named_creatures": [{"entry": 189053, "name": "Professor Cogcatcher"}]},
                {"objective_id": 429853, "credit_kind": "CREATURE_CREDIT", "credit_object_id": 194138,
                 "description": "Archivist Rellid rescued",
                 "named_creatures": [{"entry": 189055, "name": "Archivist Rellid"}]}]}}},
            "packet_entities": {item["guid"]: item for item in entities}}


def test_the_cage_holding_a_rescue_npc_is_the_object_to_use():
    objects = rescue_objects(state())
    assert [item["guid"] for item in objects] == [CAGE]
    assert objects[0]["objective_id"] == "70122:0" and objects[0]["rescue_npc_guid"] == COG
    assert rescue_objects(state(done=True)) == []                  # credited: nothing to free
    far = state(extra=())
    far["packet_entities"][CAGE]["position"]["x"] = 3595.          # not holding him
    assert rescue_objects(far) == []
    # A chair (type 7) beside him is no rescue object.
    chair = state()
    chair["packet_entities"][CAGE]["info"]["go_type"] = 7
    assert rescue_objects(chair) == []


def test_walk_to_the_cage_then_face_it_and_press_interact():
    policy = RescueObjectPolicy()
    walk = policy.propose(state())
    assert walk[0].skill == "MOVE" and walk[0].parameters["server_entity_guid"] == CAGE
    assert walk[0].parameters["face_on_arrival"] is True and walk[0].parameters["z"] == 11.6
    # 12:58:38: 3.2 yd away, now facing the cage.
    x, y = 3584.9, -2013.9
    facing = math.atan2(-2014.3-y, 3588.1-x)
    press = policy.propose(state(x, y, facing=facing))
    assert press[0].skill == "OBJECT_USE"
    params = press[0].parameters
    assert params["activation_source"] == "INTERACT_KEY_PACKET" and params["object_guid"] == CAGE
    assert params["server_use_basis"] == RESCUE_BASIS and params["quest_ids"] == ["70122"]
    assert policy.propose(state(x, y, facing=facing)) == []         # one press per attempt
    # Fighting, or a unit as the F7 recipient: no press.
    assert RescueObjectPolicy().propose(state(x, y, facing=facing, combat=True)) == []
    npc = [{"source_unit": "softinteract", "unit_type": "CREATURE", "guid": COG}]
    assert RescueObjectPolicy().propose(state(x, y, facing=facing, soft=npc)) == []


def test_the_rescue_basis_passes_the_use_and_identity_gates_without_activate():
    x, y = 3584.9, -2013.9
    live = state(x, y)
    assert not server_object_interactable(live, CAGE)               # no Activate flag
    assert server_object_interactable(live, CAGE, RESCUE_BASIS)
    params = {"activation_source": "INTERACT_KEY_PACKET", "binding": "INTERACTTARGET",
              "server_use_basis": RESCUE_BASIS, "object_guid": CAGE, "object_id": 379137}
    assert ObjectUseSkill.packet_object_usable(params, live)
    press = (Command("BIND", "INTERACTTARGET"),)
    assert check_command_identity("OBJECT_USE", params, {"guid": CAGE, "object_id": 379137}, live, press, 100.)
    # Cogcatcher freed and gone: the cage is no longer a rescue object.
    freed = state(x, y)
    freed["packet_entities"][COG]["removed"] = {"reason": "DESTROYED", "age": .2}
    assert not ObjectUseSkill.packet_object_usable(params, freed)
    assert not check_command_identity("OBJECT_USE", params, {"guid": CAGE, "object_id": 379137},
                                      freed, press, 100.)


def test_without_server_data_nothing_is_proposed():
    live = state()
    live["packet_entities"] = {}
    assert RescueObjectPolicy().propose(live) == []
