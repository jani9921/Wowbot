"""Own height and turn-in NPC position from the server (user 2026-10-20).

"Do we know the NPC position at the turn-in once we are closer? And our own
x,y,z from the server too."  Offline evidence only.
"""
from types import SimpleNamespace

from wowbot.agent.models import Observation
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.agent.turnin_resolver import TurnInResolver
from test_packet_agent_bridge import addon, bridge, deliver  # noqa: F401  (pytest fixture)
from test_packet_codecs import decoded


def test_own_server_height_is_an_observation_while_standing_there(bridge):
    deliver(bridge, decoded()[-1])                       # own movement packet: 10.5, -20.25, z 31.75
    standing = addon(frame_id="addon:11", timestamp=11., monotonic_time=11.,
                     player_world_position={"coordinate_space": "WORLD_YARDS", "x": 10.6, "y": -20.2,
                                            "instance_id": 2175, "source": "ADDON", "z_known": False})
    bridge.world.ingest(Observation.create(standing, 11.))
    position = bridge.world.state["player_world_position"]
    assert position["z"] == 31.75 and position["z_observed"] is True
    assert position["z_source"] == "PACKET_CLIENT_MOVEMENT_HELD" and position["source"] == "ADDON"
    moved = addon(frame_id="addon:12", timestamp=12., monotonic_time=12.,
                  player_world_position={"coordinate_space": "WORLD_YARDS", "x": 14., "y": -20.2,
                                         "instance_id": 2175, "source": "ADDON", "z_known": False})
    bridge.world.ingest(Observation.create(moved, 12.))
    assert bridge.world.state["player_world_position"].get("z_observed") is not True


def test_fresh_own_packet_position_is_observed_for_the_z_resolver(bridge):
    deliver(bridge, decoded()[-1])
    position = bridge.world.state["player_world_position"]
    assert position["source"] == "PACKET_CLIENT_MOVEMENT" and position["z_observed"] is True


HENRY = "Creature-0-3768-2175-23933-156859-000055F3E4"


def turn_in_state(**changes):
    henry = {"guid": HENRY, "kind": "CREATURE", "entry_id": 156859, "map_id": 2175,
             "info": {"object_kind": "UNIT", "npc_flags": 3},
             "position": {"x": 40., "y": 0., "z": 10., "source": "PACKET_CREATE_MOVEMENT", "age": 20.}}
    return {"monotonic_time": 100., "map_id": 1409, "orientation": 0., "soft_targets": [],
            "player_world_position": {"x": 0., "y": 0., "z": 10., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "active_quests": [{"quest_id": 55881, "is_complete": True, "objectives": []}],
            "reference_knowledge": {"quests": {"55881": {"quest_roles": [
                {"npc_id": 156859, "quest_id": 55881, "role": "QUEST_ENDER"}]}}},
            "packet_entities": {HENRY: henry}, **changes}


def test_turn_in_uses_the_enders_server_position_without_a_yellow_marker():
    resolution = TurnInResolver().locate(SimpleNamespace(quest_id="55881", known_locations=()), turn_in_state())
    assert resolution.entity_guid == HENRY and resolution.location["x"] == 40.
    # The server says this unit has only an in-progress quest for us: not ours.
    busy = turn_in_state()
    busy["packet_entities"][HENRY]["quest_giver"] = {"quest_available": False, "reward_ready": False,
                                                     "quest_incomplete": True, "age": 1.}
    other = TurnInResolver().locate(SimpleNamespace(quest_id="55881", known_locations=()), busy)
    assert other.entity_guid is None


def test_finished_quest_walks_up_to_its_ender_and_presses_f7_on_a_soft_match():
    (move,) = ServerNpcInteractionPolicy().propose(turn_in_state())
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == HENRY
    soft = [{"source_unit": "softinteract", "unit_type": "NPC", "guid": HENRY}]
    close = turn_in_state(soft_targets=soft, player_world_position={
        "x": 37., "y": 0., "z": 10., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"})
    (press,) = ServerNpcInteractionPolicy().propose(close)
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == HENRY


def test_nearby_server_quest_giver_is_walked_up_to_and_f7_needs_its_guid():
    giver = turn_in_state(active_quests=[])
    giver["packet_entities"][HENRY]["quest_giver"] = {"quest_available": True, "reward_ready": False,
                                                      "quest_incomplete": False, "age": 2.}
    giver["packet_entities"][HENRY]["position"]["x"] = 20.
    (move,) = ServerNpcInteractionPolicy().propose(giver)
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == HENRY
    other_soft = [{"source_unit": "softinteract", "unit_type": "NPC", "guid": "Creature-0-1-2175-1-154300-1"}]
    close = {**giver, "soft_targets": other_soft, "player_world_position": {
        "x": 17., "y": 0., "z": 10., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}
    assert ServerNpcInteractionPolicy().propose(close) == []      # a vendor beside him: no F7
    mine = {**close, "soft_targets": [{"source_unit": "softinteract", "unit_type": "NPC", "guid": HENRY}]}
    (press,) = ServerNpcInteractionPolicy().propose(mine)
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == HENRY


def test_far_side_giver_is_left_to_the_campaign_first_policy():
    far = turn_in_state(active_quests=[])
    far["packet_entities"][HENRY]["quest_giver"] = {"quest_available": True, "age": 2.}
    far["packet_entities"][HENRY]["position"]["x"] = 60.
    assert ServerNpcInteractionPolicy().propose(far) == []


RICHTER = "Creature-0-1465-2175-71046-156800-0000D3399A"


def repair_state(**changes):
    """Repair Yourself (85678), live 2026-10-20 10:09-10:11: TDB objective 455347
    is a creature credit on 156800; the server flags of Quartermaster Richter
    were 0x1280 (vendor, food vendor, repair -- no gossip)."""
    richter = {"guid": RICHTER, "kind": "CREATURE", "entry_id": 156800, "map_id": 2175,
               "info": {"object_kind": "UNIT", "npc_flags": 0x1280},
               "position": {"x": 20., "y": 0., "z": 10., "source": "PACKET_CREATE_MOVEMENT", "age": 30.}}
    return {"monotonic_time": 100., "map_id": 1409, "orientation": 0., "soft_targets": [],
            "player_world_position": {"x": 0., "y": 0., "z": 10., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "active_quests": [{"quest_id": 85678, "is_complete": False, "objectives": [
                {"objective_id": "85678:0", "description": "0/1 Speak With Quartermaster Richter to Repair All Items",
                 "is_complete": False}]}],
            "reference_knowledge": {"quests": {"85678": {"objectives": [
                {"objective_id": 455347, "credit_kind": "CREATURE_CREDIT", "credit_object_id": 156800,
                 "description": "Speak With Quartermaster Richter to Repair All Items"}]}}},
            "packet_entities": {RICHTER: richter}, **changes}


def test_a_repair_vendor_objective_npc_is_walked_up_to_and_f7_opens_his_shop():
    policy = ServerNpcInteractionPolicy()
    walk = policy.propose(repair_state())
    assert walk[0].skill == "MOVE" and walk[0].parameters["server_entity_guid"] == RICHTER
    assert walk[0].parameters["x"] == 20.
    soft = [{"source_unit": "softinteract", "guid": RICHTER, "unit_type": "CREATURE"}]
    press = policy.propose(repair_state(soft_targets=soft, player_world_position={
        "x": 17.5, "y": 0., "z": 10., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}))
    assert press[0].skill == "INTERACT" and press[0].parameters["activation_source"] == "SOFT_INTERACT"
    # His shop is open: the REPAIR click owns the next step, no second F7.
    shop = repair_state(monotonic_time=106., soft_targets=soft, vendor_ui={"open": True},
                        player_world_position={"x": 17.5, "y": 0., "z": 10., "instance_id": 2175,
                                               "coordinate_space": "WORLD_YARDS"})
    assert policy.propose(shop) == []
    # A hostile/no-interaction unit with the same credit is never walked into.
    mob = repair_state()
    mob["packet_entities"][RICHTER]["info"]["npc_flags"] = 0
    assert ServerNpcInteractionPolicy().propose(mob) == []


def test_the_new_world_landing_point_is_our_observed_height_until_we_move(bridge):
    """Live 2026-10-27 15:45:40: SMSG_NEW_WORLD put the player on the citadel
    wall; without an own movement packet the height stayed unknown and a
    route was planned on the courtyard 44 yd below."""
    import struct
    deliver(bridge, decoded("SMSG_NEW_WORLD", struct.pack("<iffffiiI", 2175, 1.2, 2.3, 260.25, 1.5, -1, 0, 0))[-1])
    standing = addon(frame_id="addon:11", timestamp=11., monotonic_time=11.,
                     player_world_position={"coordinate_space": "WORLD_YARDS", "x": 2.4, "y": 3.1,
                                            "instance_id": 2175, "source": "ADDON", "z_known": False})
    bridge.world.ingest(Observation.create(standing, 11.))
    position = bridge.world.state["player_world_position"]
    assert position["z"] == 260.25 and position["z_observed"] is True     # 1.4 yd jitter still held
    moved = addon(frame_id="addon:12", timestamp=12., monotonic_time=12.,
                  player_world_position={"coordinate_space": "WORLD_YARDS", "x": 9., "y": 3.1,
                                         "instance_id": 2175, "source": "ADDON", "z_known": False})
    bridge.world.ingest(Observation.create(moved, 12.))
    assert bridge.world.state["player_world_position"].get("z_observed") is not True
