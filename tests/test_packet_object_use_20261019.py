"""Server-identified quest objects (Ymir) for OBJECT_USE (offline).

Live 2026-10-19 15:23-15:25 (Purge the Totems, 0/5): the agent stood within
1 yd of three Harpy Totems out of combat but had no hover/soft identity, so
it never used one. The only F7 (15:25:10.62) started SPELL_START 22810 next to
an attacking Harpy Snatcher; SPELL_FAILURE followed 0.26 s later. The server
reported the totems with quest objective 389809 and dynamic flags 0xc204
(0x4 = Activate) while the quest was active; 0x8200 while it was not.
"""
import math
from types import SimpleNamespace

from wowbot.agent.models import Command
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.packet_entity_facts import objective_objects
from wowbot.runtime.skill_identity import check_command_identity
from wowbot.skills.object_use import ObjectUseSkill

TOTEM = "GameObject-0-1465-2175-71046-327146-0000D3399A"
OTHER_TOTEM = "GameObject-0-1465-2175-71046-327146-0053399A00"
CAMPFIRE = "GameObject-0-1465-2175-71046-342365-000055F3E4"


def go(guid, x, y, z=150., flags=0xC204, objective=389809):
    return {"guid": guid, "kind": "GAMEOBJECT", "entry_id": int(guid.split("-")[5]), "map_id": 2175,
            "info": {"object_kind": "GAMEOBJECT", "quest_objective_id": objective, "go_type": 10},
            "dynamic_flags": {"value": flags},
            "position": {"x": x, "y": y, "z": z, "source": "PACKET_CREATE_STATIONARY", "age": 5.}}


def state(*objects, facing=0., combat=False, soft=(), x=0., y=0., z=150.):
    return {"monotonic_time": 100., "map_id": 1409, "is_in_combat": combat, "orientation": facing,
            "soft_targets": list(soft), "soft_targets_sample_time": 99.9,
            "player_world_position": {"x": x, "y": y, "z": z, "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "active_quests": [{"quest_id": 55881, "is_complete": False, "objectives": [
                {"objective_id": "55881:0", "type": "INTERACT", "raw_type": "object",
                 "current": 0, "required": 5, "is_complete": False}]}],
            "reference_knowledge": {"quests": {"55881": {"objectives": [
                {"objective_id": 389809, "credit_kind": "GAMEOBJECT", "credit_object_id": 327146,
                 "object_template": {"object_id": 327146, "name": "Harpy Totem"}, "order": 0}]}}},
            "packet_entities": {item["guid"]: item for item in objects}}


def test_quest_objects_come_from_objective_id_and_activate_flag():
    live = state(go(TOTEM, 3., 0.), go(OTHER_TOTEM, 30., 0., flags=0x8200),
                 go(CAMPFIRE, 2., 2., flags=0x8200, objective=395317))
    objects = {item["guid"]: item["usable"] for item in objective_objects(live, 55881)}
    assert objects == {TOTEM: True, OTHER_TOTEM: False}


def test_nearest_usable_server_object_is_the_use_spot():
    flow = ObjectInteractionFlow()
    live = state(go(TOTEM, 30., 0.), go(OTHER_TOTEM, 3., 0., flags=0x8200))
    spot, known = flow.packet_use_spot(live, 55881, 150.)
    assert known is True and spot["guid"] == TOTEM and spot["distance"] == 30.
    nothing, known = flow.packet_use_spot(state(go(TOTEM, 3., 0., flags=0x8200)), 55881, 150.)
    assert nothing is None and known is True      # server shows none usable: no TDB guess
    off, known = flow.packet_use_spot(state(), 55881, 150.)
    assert off is None and known is False         # Ymir off: the TDB flow applies


def test_interact_key_needs_range_facing_peace_and_a_clear_recipient():
    flow = ObjectInteractionFlow()
    def ready(live):
        spot, _known = flow.packet_use_spot(live, 55881, 150.)
        return flow.packet_interact_ready(live, spot, 150.)
    assert ready(state(go(TOTEM, 2., 0.))) == "READY"
    assert ready(state(go(TOTEM, 2., 0.), combat=True)) == "IN_COMBAT"
    assert ready(state(go(TOTEM, 2., 0.), facing=math.pi)) == "NOT_FACING"
    assert ready(state(go(TOTEM, 10., 0.))) == "OUT_OF_RANGE"
    corpse = {"source_unit": "softinteract", "unit_type": "CREATURE", "guid": "Creature-0-1-2175-1-152571-1"}
    assert ready(state(go(TOTEM, 2., 0.), soft=[corpse])) == "UNIT_SOFT_TARGET"
    assert ready(state(go(TOTEM, 2., 0.), go(CAMPFIRE, 1., 0., flags=0x8200, objective=0))) \
        == "OTHER_OBJECT_NEARER"


def _proposal_state(live):
    return SimpleNamespace(intent=SimpleNamespace(parameters={
        "activation_source": "INTERACT_KEY_PACKET", "binding": "INTERACTTARGET",
        "object_guid": TOTEM, "object_id": 327146, "quest_ids": [55881]}, objective_ref="55881:0"))


def test_server_identity_authorizes_the_interact_press():
    params = {"activation_source": "INTERACT_KEY_PACKET", "binding": "INTERACTTARGET",
              "object_guid": TOTEM, "object_id": 327146}
    wanted = {"guid": TOTEM, "object_id": 327146}
    press = (Command("BIND", "INTERACTTARGET"),)
    live = state(go(TOTEM, 2., 0.))
    assert ObjectUseSkill.packet_object_usable(params, live) is True
    assert check_command_identity("OBJECT_USE", params, wanted, live, press, 100.)
    stale = {**live, "soft_targets_sample_time": 90.}
    assert not check_command_identity("OBJECT_USE", params, wanted, stale, press, 100.)
    other = state(go(TOTEM, 2., 0.), soft=[{"source_unit": "softinteract", "unit_type": "GAMEOBJECT",
                                             "guid": CAMPFIRE}])
    assert not check_command_identity("OBJECT_USE", params, wanted, other, press, 100.)
    used = state(go(TOTEM, 2., 0., flags=0x8200))   # Activate gone: burned / not ours
    assert not ObjectUseSkill.packet_object_usable(params, used)
    assert not check_command_identity("OBJECT_USE", params, wanted, used, press, 100.)
    assert not ObjectUseSkill.packet_object_usable(params, state(go(TOTEM, 2., 0.), combat=True))


def test_skill_begin_sends_one_interact_press():
    from wowbot.runtime import SkillStatus
    skill = ObjectUseSkill()
    active = SimpleNamespace(intent=SimpleNamespace(parameters={
        "activation_source": "INTERACT_KEY_PACKET", "binding": "INTERACTTARGET",
        "object_guid": TOTEM, "object_id": 327146, "quest_ids": [55881]},
        objective_ref="55881:0", target_ref=None), skill_type="OBJECT_USE",
        skill_context={}, started_at=100., phase=None, before_snapshot={})
    result = skill.begin(active, state(go(TOTEM, 2., 0.)))
    assert result.status is SkillStatus.RUNNING
    assert [(c.kind, c.binding) for c in result.commands] == [("BIND", "INTERACTTARGET")]
    blocked = skill.begin(SimpleNamespace(**{**active.__dict__, "skill_context": {}}),
                          state(go(TOTEM, 2., 0.), combat=True))
    assert blocked.status is not SkillStatus.RUNNING and not blocked.commands


class _FakeForwarder:
    def __init__(self):
        self.context, self.sent = None, []

    def context_id(self):
        return self.context

    def emit(self, event):
        if self.context is None:
            return False                 # no runtime context yet: dropped like UDP
        self.sent.append(event)
        return True

    def close(self):
        pass


def test_login_creates_are_replayed_to_a_late_runtime_context():
    from test_packet_entities import UPDATES, decoder, update_events
    from wowbot.packetio.forwarder import SnapshotReplayForwarder
    fake = _FakeForwarder()
    sink = SnapshotReplayForwarder(fake, wall_clock=lambda: 2000.)
    creates = update_events(decoder(), "SMSG_UPDATE_OBJECT", UPDATES["create_door_vehicle_creatures"])
    for event in creates:
        assert sink.emit(event) is False         # login burst before the context exists
    later = update_events(decoder(), "SMSG_UPDATE_OBJECT", UPDATES["removed_out_of_range"])
    fake.context = "ctx-1"
    sink.emit(later[0])
    replayed = [e for e in fake.sent if e.event_type == "ENTITY_CREATED"]
    assert len(replayed) == len(creates) and all(e.timestamp == 2000. for e in replayed)
    door = next(e for e in replayed if e.payload["entry_id"] == 335718)
    assert door.payload["position_source"] == "STATIONARY"
    count = len(fake.sent)
    sink.emit(later[0])
    assert len(fake.sent) == count+1             # same context: no second replay


def test_replayed_spline_is_settled_at_its_current_point():
    from wowbot.packetio.forwarder import EntitySnapshot
    from test_packet_entities import monster_move, semantic
    (move,) = semantic("SMSG_ON_MONSTER_MOVE", monster_move(x=0., destination=(10., 2., 3.), move_time=2000),
                       timestamp=1000.)
    snapshot = EntitySnapshot()
    snapshot.note(move)
    (half,) = snapshot.replay(1001.)
    assert half.payload["x"] == 5. and half.payload["move_time_ms"] == 1000
    (done,) = snapshot.replay(1003.)
    assert done.payload["x"] == 10. and "destination_x" not in done.payload


def test_backlog_older_than_an_open_context_is_restamped_not_dropped(tmp_path):
    """Live 2026-10-20 08:16: the stream started at PID binding and read the
    PKT from its first record while the runtime context was already open
    (08:16:46); the 08:16:01 login creates were dropped one by one and the
    agent never learned where the five Harpy Totems were."""
    from wowbot.agent.models import Observation
    from wowbot.agent.runtime_packet_source import RuntimePacketSource
    from wowbot.agent.world import WorldModel
    from wowbot.packetio.forwarder import EventPolicy, SnapshotReplayForwarder, UdpJsonForwarder
    from wowbot.packetio.inbox import PacketEventInbox
    from test_packet_entities import UPDATES, addon, decoder, update_events
    world = WorldModel()
    world.ingest(Observation.create(addon(), 9.))
    inbox = PacketEventInbox(77, port=0, autostart=False, clock=lambda: 10., wall_clock=lambda: 1000.)
    adapter = RuntimePacketSource(77, tmp_path, source=inbox, wall_clock=lambda: 999.)
    adapter.observations(None, world, 10.)                       # context open first
    try:
        sink = SnapshotReplayForwarder(UdpJsonForwarder(policy=EventPolicy(),
                                       descriptor_path=tmp_path/"packet_endpoint.json"),
                                       wall_clock=lambda: 1000.)
        old = [event.__class__.create(pid=77, flow_id=event.flow_id, direction=event.direction,
                                      event_type=event.event_type, timestamp=950.,
                                      semantic_status=event.semantic_status, opcode=event.opcode,
                                      payload=event.payload, provenance=event.provenance)
               for event in update_events(decoder(), "SMSG_UPDATE_OBJECT",
                                          UPDATES["create_door_vehicle_creatures"])]
        assert all(sink.emit(event) for event in old)
        inbox.socket.settimeout(.2)
        while True:
            try:
                raw, address = inbox.socket.recvfrom(65535)
            except OSError:
                break
            inbox.ingest_datagram(raw, address)
        for observation in adapter.observations(None, world, 10.):
            world.ingest(observation)
        entities = world.state["packet_entities"]
        assert len(entities) == len(old)
        door = next(e for e in entities.values() if e["entry_id"] == 335718)
        assert door["position"]["source"] == "PACKET_CREATE_STATIONARY"
    finally:
        adapter.close()


def test_pit_cocoons_below_the_rim_are_a_3d_move_target_not_dropped():
    """Live 2026-10-20 09:27 (Who Lurks in the Pit): all five Thick Cocoons
    were 34-100 yd below the rim (player z 94.9, observed); the same-floor
    filter dropped them and only the visual search ran."""
    flow = ObjectInteractionFlow()
    cocoons = {f"GameObject-0-1465-2175-71046-339568-000{i}53399A": z for i, z in enumerate((60.4, -0.7, -5.9))}
    live = state(*(go(guid, 80.5+i, -2279.5, z=z, objective=391939) for i, (guid, z) in enumerate(cocoons.items())),
                 x=86.3, y=-2248.7, z=94.9)
    live["reference_knowledge"]["quests"]["55881"]["objectives"][0].update(
        objective_id=391939, credit_object_id=339568, object_template={"object_id": 339568, "name": "Thick Cocoon"})
    spot, known = flow.packet_use_spot(live, 55881, 94.9)
    assert known is True and spot["z"] == 60.4          # the top spiral level first
    assert flow.packet_interact_ready(live, spot, 94.9) in {"OUT_OF_RANGE", "OTHER_FLOOR"}   # walk there
