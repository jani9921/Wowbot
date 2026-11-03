"""Server-side creature facts from Retail 70448 Ymir captures (offline).

The hex payloads are real creature records from the 2026-10-19 13:23 Ymir
dump (Exile's Reach, map 2175). They contain no player data. Passing these
tests is offline evidence only, not live validation of agent behaviour.
"""
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Observation
from wowbot.agent.runtime_packet_source import RuntimePacketSource
from wowbot.agent.world import WorldModel
from wowbot.packetio.context import addon_entity_guid
from wowbot.packetio.forwarder import EventPolicy
from wowbot.packetio.inbox import PacketEventInbox
from wowbot.packetio.ipc import canonical, envelope
from wowbot.packetio.opcodes_12_1 import FAMILY_OPCODES, REVIEWED_OPCODES
from wowbot.packetio.pkt import OpcodeManifest, PktEventDecoder, PktV31StreamParser
from wowbot.packetio.validation import normalize_event, verified_semantics
from test_packet_codecs import packed_guid


# Spline flags 0x912000 (one point), 0x0 (stop) and 0x2012000 (other layout).
OMM_ONE_POINT = bytes.fromhex(
    "e7ff64fd5586150140ac9ce00fe5162085ecc700000020910000000000d102000000000000000000ff0001"
    "000040d5afc3427f660ec5100f2ec00010000000f31fc442304a0ec5ea831fc0")
OMM_STOP = bytes.fromhex(
    "e7ff64fd5586150140ac9ce00fe5162058edc7000000000000000000000000000000000000000000ff0000"
    "00000010483cc7427b640ec5448f3bc0")
OMM_OTHER_LAYOUT = bytes.fromhex(
    "e7fff7fd5586150180ac95e00fe516208701c800000020010200000000ee03000000000000000000ff0000"
    "00000fe0853b640bf01008000100004064154943129e00c56ecb9a420330000000f2dd4c43862c00c51f389b42")
# Captain Garrick (245394): QuestGiverStatus JourneyQuest (0x10000000, "!").
QGS_GARRICK = bytes.fromhex("e7ff9a395386150180a4efe00fe516200000001000000000")
QGS_MULTIPLE = bytes.fromhex(
    "06000000e7ff9a39d3861501402099e00fe516200000000000000000e7fe9a39d3861501af96e00fe51620"
    "0000000000000000e7ff9a395386150180e09de00fe516200000000000000000e7ff9a395386150180a4ef"
    "e00fe516200000001000000000e7ff9a3953861501402899e00fe516200000000000000000efff9a395301"
    "861501c02099e00fe516200000000000000000")
GARRICK = "Creature-0-1465-2175-71046-245394-000053399A"


def records(name, body, *, build=70448, timestamp=1000.):
    opcodes = {**REVIEWED_OPCODES, **FAMILY_OPCODES[70340]}
    header = b"PKT"+struct.pack("<HBI", 0x301, 0x15, build)+b"enUS"+bytes(40)+struct.pack("<IIi", 1000, 1, 0)
    packet = struct.pack("<I", opcodes[name])+body
    raw = header+struct.pack("<IiIii", 0x47534D53, 1, 2, 8, len(packet))+struct.pack("<d", timestamp*1000)+packet
    parser = PktV31StreamParser()
    return parser, parser.feed(raw)[0]


def semantic(name, body, *, build=70448, timestamp=1000.):
    parser, record = records(name, body, build=build, timestamp=timestamp)
    decoder = PktEventDecoder(selected_pid=77, header=parser.header,
                              manifest=OpcodeManifest.reviewed(build))
    decoder.capture_epoch = 'd'*32  # frames share the synthetic worker with packet_codecs
    return [e for e in decoder.decode_all(record) if e.semantic_status == "CONFIRMED"]


def creature_guid(entry=156800, counter=0xD3399A, map_id=2175, kind=8):
    high = (kind << 58) | (1465 << 42) | (map_id << 29) | (entry << 6)
    return high, (71046 << 40) | counter


def monster_move(*, entry=156800, map_id=2175, kind=8, x=1., y=2., z=3., transport=False,
                 destination=None, move_time=1000):
    """WPP V12 SMSG_ON_MONSTER_MOVE: mover, MovementMonsterSpline, Position."""
    high, low = creature_guid(entry, map_id=map_id, kind=kind)
    spline = struct.pack("<IIBiIIB", 7, 0, 0, 0, move_time, 0, 0)
    spline += (b"\x01\x00\x05" if transport else b"\x00\x00")+b"\xff"   # TransportGUID, VehicleSeat -1
    points = 1 if destination else 0
    spline += (points << 16).to_bytes(4, "big")+b"\x00"                    # PointsCount(16) .. flags
    if destination:
        spline += struct.pack("<3f", *destination)
    return packed_guid(low, high)+spline+b"\x00"+struct.pack("<3f", x, y, z)


@pytest.mark.parametrize("body", [OMM_ONE_POINT, OMM_STOP, OMM_OTHER_LAYOUT])
def test_real_monster_moves_decode_trailing_world_position(body):
    (event,) = semantic("SMSG_ON_MONSTER_MOVE", body)
    assert event.event_type == "ENTITY_POSITION"
    assert event.provenance["payload_layout"] == "RETAIL_70448_CAPTURE_VERIFIED_V1"
    payload = event.payload
    guid = addon_entity_guid(payload["entity_guid"])
    assert guid.startswith("Creature-0-1465-2175-") and int(guid.split("-")[5]) == payload["entry_id"]
    assert payload["x"] == struct.unpack("<3f", body[-12:])[0] and abs(payload["z"]) < 1000
    value = EventPolicy().prepare(event)
    assert value is not None and verified_semantics(value)


def test_real_quest_giver_status_marks_garrick_available():
    (event,) = semantic("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK)
    assert addon_entity_guid(event.payload["entity_guid"]) == GARRICK
    assert event.payload["status_flags"] == 0x10000000 and event.payload["entry_id"] == 245394
    assert event.payload["quest_available"] is True and event.payload["reward_ready"] is False
    assert event.payload["trivial_available"] is False and event.payload["future_quest"] is False


def test_real_quest_giver_status_multiple_emits_one_fact_per_giver():
    events = semantic("SMSG_QUEST_GIVER_STATUS_MULTIPLE", QGS_MULTIPLE)
    assert len(events) == 6 and len({e.event_id for e in events}) == 6
    available = [addon_entity_guid(e.payload["entity_guid"]) for e in events if e.payload["quest_available"]]
    assert available == [GARRICK]


@pytest.mark.parametrize("flags, field", [(0x2000, "quest_incomplete"), (0x20000, "quest_incomplete"),
    (0x40000000000, "reward_ready"), (0x400000000000, "reward_ready"),
    (0x100000, "reward_ready"), (0x400000, "quest_available"), (0x100000000, "quest_available"),
    (0x40, "trivial_available"), (0x2, "future_quest")])
def test_quest_giver_bits_follow_trinitycore_groups(flags, field):
    body = QGS_GARRICK[:-8]+struct.pack("<Q", flags)
    (event,) = semantic("SMSG_QUEST_GIVER_STATUS", body)
    flags_set = {k for k in ("quest_available", "reward_ready", "quest_incomplete", "trivial_available",
                             "future_quest")
                 if event.payload[k]}
    assert flags_set == {field}


@pytest.mark.parametrize("name, body", [
    ("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK+b"\x00"),          # unreviewed trailing byte
    ("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK[:-1]),             # truncated
    ("SMSG_QUEST_GIVER_STATUS_MULTIPLE", QGS_MULTIPLE[:-3]),
    ("SMSG_QUEST_GIVER_STATUS_MULTIPLE", struct.pack("<I", 5000)),
    ("SMSG_ON_MONSTER_MOVE", OMM_STOP[:30]),
    ("SMSG_ON_MONSTER_MOVE", OMM_STOP+b"\x00"),                 # unreviewed trailing byte
    ("SMSG_ON_MONSTER_MOVE", monster_move(kind=2)),            # player mover: personal data
    ("SMSG_ON_MONSTER_MOVE", monster_move(kind=10)),           # pet: owner unknown
    ("SMSG_ON_MONSTER_MOVE", monster_move(transport=True)),    # transport-relative position
    ("SMSG_ON_MONSTER_MOVE", monster_move(x=0., y=0., z=0.)),
    ("SMSG_ON_MONSTER_MOVE", monster_move(x=float("nan"))),
])
def test_malformed_or_out_of_scope_records_are_never_entity_facts(name, body):
    assert semantic(name, body) == []


def test_12_1_0_family_does_not_know_12_1_5_only_opcodes():
    manifest = OpcodeManifest.reviewed(69587)
    assert manifest.name("SERVER_TO_CLIENT", FAMILY_OPCODES[70340]["SMSG_ON_MONSTER_MOVE"]) is None
    assert semantic("SMSG_ON_MONSTER_MOVE", OMM_STOP, build=69587) == []


def test_validation_rejects_player_entities_and_borrowed_layouts():
    (event,) = semantic("SMSG_ON_MONSTER_MOVE", OMM_STOP)
    value = event.to_dict()
    player = dict(value, payload={**value["payload"], "entity_guid": "08"+"0"*30})
    with pytest.raises(ValueError):
        normalize_event(player)
    borrowed = dict(value, provenance={**value["provenance"], "payload_layout": "WPP_12_1_REVIEWED_PREFIX_V1"})
    assert not verified_semantics(normalize_event(borrowed))
    movement = dict(value, event_type="MOVEMENT_UPDATE")
    assert not verified_semantics(normalize_event(movement))


def addon(**changes):
    return {"session_id": "live-s", "character_guid": "Player-1465-00001234", "game_build": "70448",
        "frame_id": "addon:9", "timestamp": 9., "monotonic_time": 9., "map_id": 1409,
        "phase": "world", "player_present": True, "orientation": .25,
        "player_world_position": {"coordinate_space": "WORLD_YARDS", "x": 1., "y": 2., "z": 3.,
                                  "instance_id": 2175, "source": "ADDON", "z_known": True},
        "active_quests": [], **changes}


@pytest.fixture
def bridge(tmp_path):
    world = WorldModel()
    world.ingest(Observation.create(addon(), 9.))
    clock = SimpleNamespace(now=10., wall=1000.)
    inbox = PacketEventInbox(77, port=0, autostart=False, clock=lambda: clock.now,
                             wall_clock=lambda: clock.wall)
    adapter = RuntimePacketSource(77, tmp_path, source=inbox, wall_clock=lambda: 999.)
    adapter.observations(None, world, 10.)
    yield SimpleNamespace(world=world, inbox=inbox, adapter=adapter, clock=clock,
                          path=tmp_path/"packet_endpoint.json")
    adapter.close()


def deliver(fixture, *events):
    descriptor = json.loads(fixture.path.read_text())
    for event in events:
        assert fixture.inbox.ingest_datagram(canonical(envelope(event.to_dict(), descriptor)))
    observations = fixture.adapter.observations(None, fixture.world, fixture.clock.now)
    for observation in observations:
        fixture.world.ingest(observation)
    return observations


def test_world_model_keys_server_entities_by_addon_guid(bridge):
    before_events = len(bridge.world.events)
    deliver(bridge, *semantic("SMSG_QUEST_GIVER_STATUS_MULTIPLE", QGS_MULTIPLE),
            *semantic("SMSG_ON_MONSTER_MOVE", OMM_ONE_POINT))
    entities = bridge.world.state["packet_entities"]
    assert entities[GARRICK]["quest_giver"]["quest_available"] is True
    assert entities[GARRICK]["kind"] == "CREATURE" and entities[GARRICK]["entry_id"] == 245394
    mover = next(e for e in entities.values() if "position" in e)
    assert mover["position"]["source"] == "PACKET_MONSTER_MOVE_ORIGIN" and mover["position"]["age"] == 0.
    assert mover["map_id"] == 2175
    assert len(bridge.world.events) == before_events  # facts, not derived agent events
    assert bridge.world.state["player_world_position"]["source"] == "ADDON"


def test_nearby_walkers_coalesce_to_latest_position(bridge):
    first = semantic("SMSG_ON_MONSTER_MOVE", monster_move(x=1.), timestamp=999.5)
    second = semantic("SMSG_ON_MONSTER_MOVE", monster_move(x=4.), timestamp=999.8)
    observations = deliver(bridge, *first, *second)
    assert len(observations) == 1 and bridge.inbox.coalesced == 1
    (entity,) = bridge.world.state["packet_entities"].values()
    assert entity["position"]["x"] == 4.


def test_other_map_entities_are_ignored(bridge):
    deliver(bridge, *semantic("SMSG_ON_MONSTER_MOVE", monster_move(map_id=0)))
    assert "packet_entities" not in bridge.world.state


def test_ui_map_step_keeps_and_world_map_change_clears_entities(bridge):
    deliver(bridge, *semantic("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK))
    bridge.world.ingest(Observation.create(addon(frame_id="addon:10", map_id=1726, timestamp=9.5,
                                                 monotonic_time=9.5), 9.5))
    assert GARRICK in bridge.world.state["packet_entities"]
    moved = addon(frame_id="addon:11", timestamp=9.6, monotonic_time=9.6, player_world_position={
        **addon()["player_world_position"], "instance_id": 0})
    bridge.world.ingest(Observation.create(moved, 9.6))
    assert "packet_entities" not in bridge.world.state


def test_position_ages_out_before_quest_giver_status(bridge):
    deliver(bridge, *semantic("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK),
            *semantic("SMSG_ON_MONSTER_MOVE", monster_move(entry=245394, map_id=2175)))
    bridge.world.ingest(Observation.create(addon(frame_id="addon:311", timestamp=311.,
                                                 monotonic_time=311.), 311.))
    entities = bridge.world.state["packet_entities"]
    assert "quest_giver" in entities[GARRICK] and entities[GARRICK]["quest_giver"]["age"] == 301.
    mover = addon_entity_guid("{:016X}{:016X}".format(*creature_guid(245394)))
    assert "position" not in entities.get(mover, {})


def test_one_point_spline_destination_drives_a_position_estimate(bridge):
    (event,) = semantic("SMSG_ON_MONSTER_MOVE", monster_move(x=1., destination=(11., 2., 3.), move_time=2000))
    assert event.payload["destination_x"] == 11. and event.payload["move_time_ms"] == 2000
    deliver(bridge, event)
    bridge.world.ingest(Observation.create(addon(frame_id="addon:11", timestamp=11., monotonic_time=11.), 11.))
    (entity,) = bridge.world.state["packet_entities"].values()
    estimate = entity["position"]["estimate"]
    assert estimate["x"] == 6. and estimate["progress"] == .5 and estimate["arrived"] is False


def test_real_monster_move_destination_is_the_first_spline_point():
    (event,) = semantic("SMSG_ON_MONSTER_MOVE", OMM_ONE_POINT)
    first = struct.unpack_from("<3f", OMM_ONE_POINT, 16+30)  # mover GUID is 16 bytes here
    assert (event.payload["destination_x"], event.payload["destination_y"]) == first[:2]
    assert "destination_x" not in semantic("SMSG_ON_MONSTER_MOVE", OMM_STOP)[0].payload


# --- SMSG_UPDATE_OBJECT (real creature/vehicle/game-object-only records) ---

UPDATES = {name: bytes.fromhex(value["payload_hex"]) for name, value in json.loads(
    (Path(__file__).parent/"fixtures"/"ymir_70448_update_object.json").read_text())["records"].items()}


def decoder(build=70448):
    parser, _ = records("SMSG_UPDATE_OBJECT", b"", build=build)
    return PktEventDecoder(selected_pid=77, header=parser.header, manifest=OpcodeManifest.reviewed(build))


def update_events(value, name, body):
    _, record = records(name, body)
    return [e for e in value.decode_all(record) if e.semantic_status == "CONFIRMED"]


def test_real_update_object_creates_carry_entry_position_and_flags():
    events = update_events(decoder(), "SMSG_UPDATE_OBJECT", UPDATES["create_door_vehicle_creatures"])
    created = {e.payload["entry_id"]: e.payload for e in events if e.event_type == "ENTITY_CREATED"}
    door = created[335718]   # Doodad_6DU_HighmaulRaid_Door_ThroneRoom001
    assert door["object_kind"] == "GAMEOBJECT" and door["position_source"] == "STATIONARY"
    assert (round(door["x"], 1), round(door["y"], 1), round(door["z"], 1)) == (767.0, -1569.5, 426.8)
    assert door["go_flags"] == 0x20 and door["go_type"] == 0 and door["world_map_id"] == 2175
    vehicle = created[161265]  # Jrokgar
    assert vehicle["object_kind"] == "UNIT" and vehicle["position_source"] == "MOVEMENT"
    assert addon_entity_guid(vehicle["entity_guid"]).startswith("Vehicle-0-1465-2175-")
    assert all(e.provenance["payload_layout"] == "RETAIL_70448_CAPTURE_VERIFIED_V1" for e in events)
    assert all(verified_semantics(EventPolicy().prepare(e)) for e in events)


def test_values_update_needs_the_create_fragments_first():
    value = decoder()
    assert update_events(value, "SMSG_UPDATE_OBJECT", UPDATES["values_153266"]) == []
    # The respawned Killclaw (...FDF7) is another GUID: its fragments do not
    # unlock the values update of the first one (...FCB6).
    respawn = update_events(value, "SMSG_UPDATE_OBJECT", UPDATES["create_153266"])
    assert [e.payload["entry_id"] for e in respawn] == [153266]   # Killclaw the Terrible
    assert update_events(value, "SMSG_UPDATE_OBJECT", UPDATES["values_153266"]) == []
    created = update_events(value, "SMSG_UPDATE_OBJECT", UPDATES["create_door_vehicle_creatures"])
    first = next(e.payload["entity_guid"] for e in created if e.payload["entry_id"] == 153266)
    (flags,) = update_events(value, "SMSG_UPDATE_OBJECT", UPDATES["values_153266"])
    assert flags.event_type == "ENTITY_FLAGS" and flags.payload["dynamic_flags"] == 0
    assert flags.payload["entity_guid"] == first


def test_real_out_of_range_removal():
    (event,) = update_events(decoder(), "SMSG_UPDATE_OBJECT", UPDATES["removed_out_of_range"])
    assert event.event_type == "ENTITY_REMOVED" and event.payload["removal"] == "OUT_OF_RANGE"
    assert event.payload["entry_id"] == 160433


@pytest.mark.parametrize("body", [UPDATES["create_153266"][:-1], UPDATES["create_153266"]+b"\x00",
                                  UPDATES["removed_out_of_range"][:-2]])
def test_truncated_or_padded_update_object_yields_no_fact(body):
    assert update_events(decoder(), "SMSG_UPDATE_OBJECT", body) == []


def test_player_removal_never_becomes_an_entity_fact():
    high, low = (2 << 58) | (1465 << 42), 0x0B57527D
    body = struct.pack("<HI", 2175, 0)+b"\xc0"+struct.pack("<hI", 0, 1)+packed_guid(low, high)+struct.pack("<I", 0)
    assert update_events(decoder(), "SMSG_UPDATE_OBJECT", body) == []


def test_world_model_tracks_creation_order_and_removal(bridge):
    deliver(bridge, *semantic("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK))
    deliver(bridge, *update_events(decoder(), "SMSG_UPDATE_OBJECT", UPDATES["create_door_vehicle_creatures"]))
    entities = bridge.world.state["packet_entities"]
    assert next(iter(entities)) == GARRICK   # server "!" giver first, then nearest
    door = next(e for e in entities.values() if e["entry_id"] == 335718)
    assert door["position"]["source"] == "PACKET_CREATE_STATIONARY" and door["info"]["go_flags"] == 0x20
    distances = [e["distance"] for e in entities.values() if "distance" in e]
    assert distances == sorted(distances)
    created = update_events(decoder(), "SMSG_UPDATE_OBJECT", UPDATES["create_153266"])
    deliver(bridge, *created)
    removal = struct.pack("<HI", 2175, 0)+b"\xc0"+struct.pack("<hI", 1, 1)
    high, low = (int(created[0].payload["entity_guid"][:16], 16), int(created[0].payload["entity_guid"][16:], 16))
    deliver(bridge, *update_events(decoder(), "SMSG_UPDATE_OBJECT", removal+packed_guid(low, high)+struct.pack("<I", 0)))
    killclaw = addon_entity_guid(created[0].payload["entity_guid"])
    assert bridge.world.state["packet_entities"][killclaw]["removed"]["reason"] == "DESTROYED"


def test_entity_facts_wait_while_the_addon_context_settles(tmp_path):
    """Live 2026-10-21 10:57:06: the source context opened from the newest
    payload while the merged addon state was incomplete; the snapshot replay
    (the rib cage holding Professor Cogcatcher among it) was dropped."""
    world = WorldModel()
    clock = SimpleNamespace(now=10., wall=1000.)
    inbox = PacketEventInbox(77, port=0, autostart=False, clock=lambda: clock.now,
                             wall_clock=lambda: clock.wall)
    adapter = RuntimePacketSource(77, tmp_path, source=inbox, wall_clock=lambda: 999.)
    adapter.observations(addon(), world, 10.)              # the payload opens the context
    descriptor = json.loads((tmp_path/"packet_endpoint.json").read_text())
    for event in semantic("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK):
        assert inbox.ingest_datagram(canonical(envelope(event.to_dict(), descriptor)))
    for observation in adapter.observations(addon(), world, 10.):
        world.ingest(observation)
    assert not world.state.get("packet_entities")           # held, not applied yet
    world.ingest(Observation.create(addon(), 10.))           # the merged addon state is complete
    for event in semantic("SMSG_ON_MONSTER_MOVE", OMM_ONE_POINT):
        assert inbox.ingest_datagram(canonical(envelope(event.to_dict(), descriptor)))
    for observation in adapter.observations(None, world, 10.5):
        world.ingest(observation)
    assert world.state["packet_entities"][GARRICK]["quest_giver"]["quest_available"] is True
    adapter.close()
