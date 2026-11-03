"""Producer epochs scope delivery/coalescing; common records share evidence."""
import json
import struct

from wowbot.agent.models import Observation
from wowbot.evidence_contracts import independent_evidence
from wowbot.packetio.ipc import canonical, envelope
from wowbot.packetio.pkt import OpcodeManifest, PktEventDecoder, PktV31StreamParser
from test_packet_agent_bridge import addon, bridge
from test_packet_codecs import pkt_bytes
from test_packet_continuity_20261030 import connected
from test_packet_entities import records, OMM_STOP


def event(epoch, *, name='CMSG_MOVE_HEARTBEAT', body=None, build=69587, timestamp=1000.):
    parser=PktV31StreamParser()
    record=parser.feed(pkt_bytes(name,body,build=build,timestamp=timestamp))[0]
    decoder=PktEventDecoder(selected_pid=77,header=parser.header,manifest=OpcodeManifest.reviewed(build))
    decoder.capture_epoch=epoch
    return decoder.decode_all(record)[-1]


def queue(bridge, value):
    descriptor=json.loads(bridge.path.read_text())
    assert bridge.inbox.ingest_datagram(canonical(envelope(value.to_dict(),descriptor)))


def test_same_record_has_separate_delivery_ids_but_one_semantic_evidence_root():
    first,second=event('a'*32),event('b'*32)
    assert first.event_id != second.event_id
    assert first.provenance['semantic_record_id'] == second.provenance['semantic_record_id']
    assert event('a'*32).event_id == first.event_id


def test_epoch_coalescing_does_not_drop_another_workers_latest_sample(bridge):
    for epoch in ('a'*32,'b'*32):
        queue(bridge,event(epoch,timestamp=999.8))
        queue(bridge,event(epoch,timestamp=999.9))
    assert len(bridge.inbox.peek_movement()) == 2
    rows=bridge.inbox.poll()
    assert len(rows)==2
    assert {r['provenance']['capture_epoch'] for r in rows} == {'a'*32,'b'*32}
    assert all(r['timestamp']==999.9 for r in rows)


def test_same_frame_from_two_workers_is_not_independent_support(bridge):
    queue(bridge,event('a'*32))
    queue(bridge,event('b'*32))
    observations=bridge.adapter.observations(None,bridge.world,10.)
    assert len(observations)==2
    for value in observations: assert bridge.world.ingest(value)
    facts=[e for e in bridge.world.evidence['player_world_position'] if e.source=='PACKET_TELEMETRY']
    assert len(facts)==1 and len(independent_evidence(facts))==1
    assert len([o for o in bridge.world.history if o.source=='PACKET_TELEMETRY'])==2


def test_fast_lane_rejects_foreign_epoch_and_still_sees_current_worker(bridge):
    provider,decoder,_,_=connected(bridge)
    queue(bridge,event('b'*32,build=70575))
    assert not bridge.adapter.peek_own_movement(bridge.world,10.)
    assert '_packet_last_own' not in bridge.world.__dict__
    bridge.inbox._clock=lambda:10.05
    bridge.inbox._wall_clock=lambda:1000.05
    record=PktV31StreamParser().feed(pkt_bytes(build=70575,timestamp=1000.05))[0]
    current=decoder.decode_all(record)[-1]
    queue(bridge,current)
    assert bridge.adapter.peek_own_movement(bridge.world,10.05)
    assert bridge.world.__dict__['_packet_last_own']['sampled_at']==10.05
    assert len(bridge.inbox.poll())==2  # peek never consumes the medium lane
    assert provider.capture_epoch==current.provenance['capture_epoch']


def test_foreign_map_barrier_does_not_erase_current_movement(bridge):
    queue(bridge,event('a'*32))
    body=struct.pack('<iffffiiI',2175,1.,2.,3.,0.,0,0,0)
    queue(bridge,event('b'*32,name='SMSG_NEW_WORLD',body=body))
    assert len(bridge.inbox.peek_movement())==1
    queue(bridge,event('a'*32,name='SMSG_NEW_WORLD',body=body))
    assert bridge.inbox.peek_movement()==[]


def test_foreign_entity_removal_is_not_a_lifecycle_barrier_for_current_worker(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70448'),9.1))
    bridge.adapter.observations(None,bridge.world,10.)
    parser,record=records('SMSG_ON_MONSTER_MOVE',OMM_STOP)
    first=PktEventDecoder(selected_pid=77,header=parser.header,manifest=OpcodeManifest.reviewed(70448))
    first.capture_epoch='a'*32
    position=first.decode_all(record)[-1]
    # A normalized removal from another producer cannot wipe this producer's
    # state mailbox. The reducer will independently enforce its active epoch.
    from wowbot.packetio.models import AgentPacketEvent
    removed=AgentPacketEvent.create(pid=77,flow_id=position.flow_id,direction='SERVER_TO_CLIENT',
        event_type='ENTITY_REMOVED',timestamp=1000.,semantic_status='CONFIRMED',opcode=position.opcode,
        payload={k:v for k,v in position.payload.items() if k in {'entity_guid','entry_id'}}|{'removal':'DESTROYED'},
        provenance={**position.provenance,'capture_epoch':'b'*32})
    queue(bridge,position)
    queue(bridge,removed)
    assert len(bridge.inbox.poll())==2
