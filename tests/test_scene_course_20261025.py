"""Skyriding courses and races from the live client scene plus the local DB2.

Live 20:46-20:47 (quest 68796, the Skytop Observatory race): the agent stood
on WAIT -- no hand binding knew the race.  The packets name everything that
is needed: SMSG_MOVE_ROOT on the start line, SMSG_PLAY_SCENE (package 3562),
SMSG_MOVE_UNROOT as the start; on 77345 the own client sent "Checkpoint"
per ring and "RaceComplete" at the target.  User 2026-10-25: the agent must
take the course from the DB2 catalog, not from a hand-written binding.
"""
import json
import struct
from types import SimpleNamespace

import pytest

from test_packet_agent_bridge import addon
from test_packet_codecs import packed_guid
from wowbot.agent.models import Observation
from wowbot.agent.runtime_packet_source import RuntimePacketSource
from wowbot.agent.skyriding_control import SkyridingControl
from wowbot.agent.world import WorldModel
from wowbot.navigation.flight_path import FlightPath
from wowbot.packetio.inbox import PacketEventInbox
from wowbot.packetio.ipc import canonical, envelope
from wowbot.packetio.opcodes_12_1 import FAMILY_OPCODES
from wowbot.packetio.pkt import OpcodeManifest, PktEventDecoder, PktV31StreamParser
from wowbot.quests.client_catalog import ClientCatalog
from wowbot.quests.scene_path_planning import SceneCoursePolicy

BUILD = 70575
START_LINE = {"x": 1821.45, "y": 46.16}                 # live, beside Celormu
PLAY_RACE = (struct.pack("<iiIi", 2985, 0x14, 1, 3562) + packed_guid(0, 0)
             + struct.pack("<ffffi", 0., 0., 0., 0., 0) + b"\x00")


def trigger(name, instance=1):
    raw = name.encode()
    return bytes((len(raw) << 2,)) + struct.pack("<I", instance) + raw


ROOT = packed_guid() + struct.pack("<i", 13)


def pkt(name, body, timestamp):
    direction = 0x47534D43 if name.startswith("CMSG_") else 0x47534D53
    header = b"PKT"+struct.pack("<HBI", 0x301, 0x15, BUILD)+b"enUS"+bytes(40)+struct.pack("<IIi", 1000, 1, 0)
    packet = struct.pack("<I", FAMILY_OPCODES[70340][name]) + body
    return header+struct.pack("<IiIii", direction, 1, 2, 8, len(packet))+struct.pack("<d", timestamp*1000)+packet


def events(name, body, timestamp=1000.):
    parser = PktV31StreamParser()
    record = parser.feed(pkt(name, body, timestamp))[0]
    decoder = PktEventDecoder(selected_pid=77, header=parser.header, manifest=OpcodeManifest.reviewed(BUILD))
    return decoder.decode_all(record)[1:]


def test_scene_root_and_trigger_packets_decode_to_allowlisted_events():
    (started,) = events("SMSG_PLAY_SCENE", PLAY_RACE)
    assert started.event_type == "SCENE_STARTED" and started.payload == {
        "scene_id": 2985, "playback_flags": 0x14, "scene_instance_id": 1, "package_id": 3562}
    (checkpoint,) = events("CMSG_SCENE_TRIGGER_EVENT", trigger("Checkpoint"))
    assert checkpoint.payload == {"scene_instance_id": 1, "scene_event": "CHECKPOINT"}
    assert events("CMSG_SCENE_TRIGGER_EVENT", trigger("Range Cancel")) == []     # other names never pass
    (root,) = events("SMSG_MOVE_ROOT", ROOT)
    assert root.event_type == "MOVEMENT_ROOT" and root.payload["rooted"] is True
    (unroot,) = events("SMSG_MOVE_UNROOT", ROOT)
    assert unroot.payload["rooted"] is False
    (ended,) = events("SMSG_CANCEL_SCENE", struct.pack("<I", 1))
    assert ended.payload == {"scene_instance_id": 1, "canceled": True}


@pytest.fixture
def race(tmp_path):
    world = WorldModel()
    point = {"coordinate_space": "WORLD_YARDS", **START_LINE, "z": 304., "instance_id": 2444,
             "source": "ADDON", "z_known": False}
    world.ingest(Observation.create(addon(game_build="70575", map_id=2022, player_world_position=point,
                                          is_mounted=True, active_quests=[{"quest_id": 68796, "objectives": [
                                              {"description": "0/1 Race to the Skytop Observatory"}]}]), 9.))
    inbox = PacketEventInbox(77, port=0, autostart=False, clock=lambda: 10., wall_clock=lambda: 1000.)
    adapter = RuntimePacketSource(77, tmp_path, source=inbox, wall_clock=lambda: 999.)
    adapter.observations(None, world, 10.)
    descriptor = json.loads((tmp_path/"packet_endpoint.json").read_text())
    clock = iter(999.1 + .05*n for n in range(1000))

    def deliver(name, body):
        for event in events(name, body, next(clock)):         # two equal packets are two events
            assert inbox.ingest_datagram(canonical(envelope(event.to_dict(), descriptor)))
        for observation in adapter.observations(None, world, 10.):
            world.ingest(observation)
        return world.state
    yield SimpleNamespace(world=world, deliver=deliver)
    adapter.close()


def test_the_race_course_comes_from_the_live_scene_and_the_db2(race):
    state = race.deliver("SMSG_MOVE_ROOT", ROOT)
    assert state["movement_rooted"]["rooted"] is True
    state = race.deliver("SMSG_PLAY_SCENE", PLAY_RACE)
    assert state["packet_scene"]["package_id"] == 3562 and state["packet_scene"]["active"] is True
    (move,) = SceneCoursePolicy().propose(state)
    reference = move.parameters["route_reference"]
    assert reference["path_id"] == 43699 and reference["selection"] == "ONLY_PATH_STARTING_AT_THE_SCENE_START"
    path = FlightPath.from_dict(move.parameters["flight_path"])
    assert len(path.waypoints) == 6 and path.landing["x"] == pytest.approx(2414., abs=1.)
    assert "server_scene" in move.evidence
    # Progress is the own client's ring triggers, ahead of any quest credit.
    race.deliver("CMSG_SCENE_TRIGGER_EVENT", trigger("Checkpoint"))
    state = race.deliver("CMSG_SCENE_TRIGGER_EVENT", trigger("Checkpoint"))
    assert state["route_counters"]["scene"]["checkpoints"] == 2
    assert path.progress(state, now=None) == 2
    state = race.deliver("CMSG_SCENE_TRIGGER_EVENT", trigger("RaceComplete"))
    assert path.arrival_confirmed(state) and SceneCoursePolicy().propose(state) == []
    state = race.deliver("SMSG_CANCEL_SCENE", struct.pack("<I", 1))
    assert state["packet_scene"]["active"] is False and "route_counters" not in state


def test_the_lessons_resolve_to_their_reviewed_routes_without_any_binding():
    catalog = ClientCatalog()
    for package, quest in ((3747, "65118"), (3748, "65120"), (3749, "65133"), (3978, "77345")):
        course, reason = catalog.scene_course(package, {"x": 1814.5, "y": 51.2})
        reviewed = catalog.courses()[quest]
        assert reason == "resolved" and course["selection"] == "ONLY_PATH_OF_THE_SCENE"
        flat = lambda rings: [value for ring in rings for value in ring[:3]]
        assert flat(course["rings"]) == pytest.approx(flat(reviewed["rings"]), abs=.01)


def test_a_cinematic_or_an_unknown_start_proposes_no_course():
    catalog = ClientCatalog()
    assert catalog.scene_course(1505, START_LINE)[1] == "unsupported_scene_mechanic"
    assert catalog.scene_course(3562, {"x": 0., "y": 0.}) == (None, "no_scene_path_near_start")
    state = {"packet_scene": {"active": True, "package_id": 1505, "start_position": START_LINE},
             "player_world_position": {**START_LINE, "instance_id": 2444}}
    assert SceneCoursePolicy().propose(state) == []


def test_the_rider_waits_on_the_start_line_and_takes_off_on_the_unroot():
    course, _ = ClientCatalog().scene_course(3562, START_LINE)
    from wowbot.quests.scene_path_planning import scene_course_path
    control = SkyridingControl(scene_course_path(course, 2444))
    state = {"is_mounted": True, "movement": {"flying": False}, "player_world_position": {**START_LINE, "z": 304.},
             "movement_rooted": {"rooted": True, "sampled_at": 100.}}
    for at in (100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5):
        assert control.assess(state, at) == ("MOVING", "skyriding_start_line_rooted")
        assert control.commands(state, at) == ()
    state["movement_rooted"] = {"rooted": False, "sampled_at": 106.6}
    assert control.assess(state, 106.7) == ("MOVING", "skyriding_takeoff")
    assert [c.binding for c in control.commands(state, 106.7)] == ["JUMP"]


@pytest.mark.parametrize("delivery", [.05, .45])
def test_the_skytop_race_is_flown_from_the_start_line_through_every_ring(delivery):
    import math
    from skyriding_sim import SkyridingSim
    from wowbot.quests.scene_path_planning import scene_course_path
    course, _ = ClientCatalog().scene_course(3562, START_LINE)
    path = scene_course_path(course, 2444)
    points = [*course["rings"], course["target"]]
    start = (START_LINE["x"], START_LINE["y"], 300.)
    facing = math.atan2(points[0][1]-start[1], points[0][0]-start[0]) % math.tau
    sim = SkyridingSim(start, facing, points, ground_z=90., delivery=delivery)
    control = SkyridingControl(path)
    verdict = "MOVING"
    while sim.t < 120. and verdict == "MOVING":
        state = sim.state("race", len(course["rings"]))
        verdict, reason = control.assess(state, sim.t)
        for command in control.commands(state, sim.t) if verdict == "MOVING" else ():
            sim.apply(command)
        sim.run_tick()
    assert sim.passed == len(points) and verdict == "ARRIVED", (verdict, reason, sim.passed, round(sim.t, 1))


CELORMU = bytes.fromhex("2042493180C1660001F81400005E5EEC")


def packed(raw):
    """Pack a 16-byte big-endian WowGuid128 hex as the client writes it."""
    high, low = int.from_bytes(raw[:8], "big"), int.from_bytes(raw[8:], "big")
    def part(value):
        mask = sum(1 << i for i in range(8) if value & (255 << (8*i)))
        return mask, bytes((value >> (8*i)) & 255 for i in range(8) if mask & (1 << i))
    lm, lb = part(low)
    hm, hb = part(high)
    return bytes((lm, hm)) + lb + hb


GOSSIP = packed(CELORMU) + struct.pack("<Ii", 29949, 107284) + b"\x00"


def test_the_gossip_row_that_started_the_race_is_decoded():
    (picked,) = events("CMSG_GOSSIP_SELECT_OPTION", GOSSIP)
    assert picked.event_type == "GOSSIP_SELECTED"
    assert picked.payload["entry_id"] == 198040 and picked.payload["gossip_option_id"] == 107284
    assert picked.payload["gossip_menu_id"] == 29949


def test_a_timed_out_race_is_started_again_at_its_starter(race):
    from wowbot.quests.scene_path_planning import SceneCourseRetryPolicy
    race.deliver("CMSG_GOSSIP_SELECT_OPTION", GOSSIP)
    state = race.deliver("SMSG_PLAY_SCENE", PLAY_RACE)
    starter = state["packet_scene"]["starter"]
    assert starter["entry_id"] == 198040 and starter["gossip_option_id"] == 107284
    race.deliver("CMSG_SCENE_TRIGGER_EVENT", trigger("Checkpoint"))
    state = race.deliver("SMSG_CANCEL_SCENE", struct.pack("<I", 1))
    failed = state["failed_scene_course"]
    assert failed["package_id"] == 3562 and failed["starter"]["guid"].startswith("Creature-")
    policy = SceneCourseRetryPolicy()
    npc = {"guid": failed["starter"]["guid"], "kind": "CREATURE", "entry_id": 198040,
           "position": {"x": 1830., "y": 46., "z": 313.4, "sampled_at": 10., "source": "PACKET_CREATE_STATIONARY",
                        "coordinate_space": "WORLD_YARDS"}, "map_id": 2444}
    far = {**state, "monotonic_time": 20., "packet_entities": {npc["guid"]: npc}}
    (move,) = policy.propose(far)
    assert move.skill == "MOVE" and move.parameters["purpose"] == "SCENE_COURSE_RETRY"
    beside = {**far, "player_world_position": {**far["player_world_position"], "x": 1828.},
              "soft_targets": [{"source_unit": "softinteract", "guid": npc["guid"]}]}
    (talk,) = policy.propose(beside)
    assert talk.skill == "INTERACT" and talk.parameters["soft_guid"] == npc["guid"]
    dialog = {**beside, "quest_ui": {"open": True, "gossip_options": [
                  {"id": 107781, "name": "Advanced", "x": .5, "y": .5},
                  {"id": 107284, "name": "Race", "x": .5, "y": .55}]},
              "target": {"guid": npc["guid"], "npc_id": 198040}}
    (pick,) = policy.propose(dialog)
    assert pick.skill == "QUEST_DIALOG" and pick.parameters["gossip_option_id"] == 107284
    assert pick.parameters["gossip_transition"] == "SCENE_START" and pick.parameters["y"] == .55


def test_a_finished_race_is_not_restarted_and_retries_are_bounded(race):
    from wowbot.quests.scene_path_planning import SceneCourseRetryPolicy, RETRY_LIMIT
    race.deliver("CMSG_GOSSIP_SELECT_OPTION", GOSSIP)
    race.deliver("SMSG_PLAY_SCENE", PLAY_RACE)
    race.deliver("CMSG_SCENE_TRIGGER_EVENT", trigger("RaceComplete"))
    state = race.deliver("SMSG_CANCEL_SCENE", struct.pack("<I", 1))
    assert "failed_scene_course" not in state
    policy = SceneCourseRetryPolicy()
    failed = {"package_id": 3562, "start_position": START_LINE, "ended_at": 10.,
              "starter": {"guid": "Creature-0-1-2444-1-198040-1", "entry_id": 198040, "gossip_option_id": 107284}}
    base = {"monotonic_time": 20., "player_world_position": {**START_LINE, "instance_id": 2444},
            "packet_entities": {"Creature-0-1-2444-1-198040-1": {
                "guid": "Creature-0-1-2444-1-198040-1", "entry_id": 198040, "kind": "CREATURE", "map_id": 2444,
                "position": {"x": 1900., "y": 46., "z": 313., "sampled_at": 10., "source": "PACKET_CREATE_STATIONARY"}}}}
    for instance in range(1, RETRY_LIMIT + 1):
        assert policy.propose({**base, "failed_scene_course": {**failed, "scene_instance_id": instance}})
    assert policy.propose({**base, "failed_scene_course": {**failed, "scene_instance_id": 99}}) == []


def test_a_restart_gossip_is_verified_by_the_new_scene():
    from test_talk_ride_credits_20261021 import state as talk_state
    from wowbot.verification.quest_dialog import QuestDialogVerifier
    target = {"guid": "Creature-0-1-2444-1-198040-1", "name": "Celormu", "attackable": False, "dead": False}
    ui = {"open": True, "action": "", "x": 0, "y": 0,
          "gossip_options": [{"id": 107284, "name": "Race", "available": True, "x": .12, "y": .6}]}
    before = talk_state(target=target, quest_ui=ui, quest_ui_open=True, state_age=.4,
                        packet_scene={"active": False, "scene_instance_id": 1})
    after = {**before, "packet_scene": {"active": True, "scene_instance_id": 2}}
    result = QuestDialogVerifier().evaluate(before, after, quest_id=None, action="GOSSIP_OPTION_SELECT",
                                            target_guid=target["guid"], gossip_option_id=107284,
                                            gossip_transition="SCENE_START")
    assert result.success
    assert not QuestDialogVerifier().evaluate(before, {**after, "packet_scene": before["packet_scene"]}, quest_id=None,
                                              action="GOSSIP_OPTION_SELECT", target_guid=target["guid"],
                                              gossip_option_id=107284, gossip_transition="SCENE_START").success
