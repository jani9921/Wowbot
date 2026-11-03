"""Realm/instance login proof and relogin lifecycle; no client or auth access."""
from dataclasses import replace
import struct

import pytest

from wowbot.packetio.opcodes_12_1 import FAMILY_OPCODES
from wowbot.packetio.pkt import PktV31StreamParser
from wowbot.packetio.validation import normalize_event,verified_semantics
from wowbot.session_context import ProcessIdentity,SessionContextProvider
from test_packet_codecs import packed_guid,pkt_bytes
from test_session_bootstrap_20261029 import session_events
from test_own_create_quest_log_20261030 import create_payload
from test_unit_fields_20261027 import bits
from test_packet_delivery_20261030 import native


def public_create(*,you=True,low=0x1234,object_type=7,map_id=2175,duplicates=False):
    movement=bits([(int(i==4 and you),1) for i in range(21)])+struct.pack('<I',0)
    fields=b'\0\xff'  # no private field fragment requested or needed for identity
    block=bytes((2,))+packed_guid(low=low)+bytes((object_type,))+movement+struct.pack('<I',len(fields))+fields
    if duplicates:block*=2
    return struct.pack('<HI',map_id,2 if duplicates else 1)+b'\0'+struct.pack('<I',len(block))+block


def cross_connection(*,body=None,at=1000.1,connection=2,record_number=2):
    decoder,verify=session_events(build=70575,connection=2)
    assert len(decoder.decode_all(verify))==1  # another connection alone is not own identity
    create=replace(verify,opcode=FAMILY_OPCODES[70340]['SMSG_UPDATE_OBJECT'],
                   payload=public_create() if body is None else body,
                   record_number=record_number,timestamp=at,connection_index=connection)
    return decoder,verify,create


def test_instance_connection_requires_matching_login_world_and_public_own_active_create():
    decoder,verify,create=cross_connection(body=create_payload())
    events=decoder.decode_all(create)
    baseline=next(e for e in events if e.event_type=='SESSION_BASELINE')
    assert events[1] is baseline  # precedes every native own field in this record
    assert baseline.payload['character_guid']=='Player-1602-00001234'
    assert baseline.payload['sequence']==2 and baseline.timestamp==1000.1
    assert baseline.provenance['payload_layout']=='WPP_12_1_SESSION_REVIEWED_V2'
    assert baseline.provenance['opcode_name']=='SMSG_UPDATE_OBJECT'
    assert verified_semantics(normalize_event(baseline.to_dict()))
    assert decoder._verified_player_guids=={2:'Player-1602-00001234'}
    assert any(e.event_type=='OWN_QUEST_LOG_UPDATE' for e in events)
    assert 'PRIVATE_NAME_SENTINEL' not in str([e.to_dict() for e in events])
    provider=SessionContextProvider(ProcessIdentity(77,'0000000000000001',70575))
    assert provider.accept_baseline(baseline.to_dict())
    assert provider.expected(77)['instance_id']==2175


@pytest.mark.parametrize('body',[
    public_create(you=False),public_create(low=0x9999),public_create(object_type=6),
    public_create(map_id=99),public_create(duplicates=True),public_create()[:-1],
])
def test_unproven_or_ambiguous_public_creates_cannot_bind_an_instance_connection(body,monkeypatch):
    from wowbot.packetio import own_create_quest_log
    monkeypatch.setattr(own_create_quest_log,'read_create_slots',lambda *a,**k:pytest.fail('unproved private prefix read'))
    decoder,verify,create=cross_connection(body=body)
    events=decoder.decode_all(create)
    assert not any(e.event_type.startswith('OWN_') or e.event_type=='SESSION_BASELINE' for e in events)
    assert decoder._verified_player_guids=={}


@pytest.mark.parametrize('changes',[{'at':1061.},{'at':999.},{'connection':3},{'record_number':1}])
def test_old_wrong_connection_or_reordered_identity_proof_is_rejected(changes):
    decoder,verify,create=cross_connection(**changes)
    assert not any(e.event_type=='SESSION_BASELINE' for e in decoder.decode_all(create))
    assert decoder._verified_player_guids=={}


def test_own_active_create_without_a_login_or_world_verification_cannot_guess_a_baseline():
    decoder,verify=session_events(build=70575,connection=2)
    create=replace(verify,opcode=FAMILY_OPCODES[70340]['SMSG_UPDATE_OBJECT'],payload=public_create(),record_number=2)
    assert not any(e.event_type=='SESSION_BASELINE' for e in decoder.decode_all(create))
    decoder._handshake.intent=None
    decoder.decode_all(verify)
    assert not any(e.event_type=='SESSION_BASELINE' for e in decoder.decode_all(create))


def test_duplicate_world_verification_after_a_binding_does_not_manufacture_another_session():
    decoder,verify,create=cross_connection()
    assert any(e.event_type=='SESSION_BASELINE' for e in decoder.decode_all(create))
    assert not any(e.event_type=='SESSION_BASELINE' for e in decoder.decode_all(replace(verify,record_number=3)))


@pytest.mark.parametrize('low',[0x1234,0x9999])
def test_relogin_rotates_epoch_and_discards_previous_connection_ownership_fragments_and_faults(low):
    decoder,verify=session_events(build=70575)
    baseline=decoder.decode_all(verify)[-1]
    old_epoch=decoder.capture_epoch
    decoder._owned_items[1]={'old-item':'old-owner'}
    decoder.entity_fragments['old-entity']=(3,)
    decoder.collection_decode_failures=3
    login=PktV31StreamParser().feed(pkt_bytes('CMSG_PLAYER_LOGIN',
        packed_guid(low=low)+struct.pack('<fB',500.,0),build=70575))[0]
    login=replace(login,record_number=100,timestamp=1001.)
    assert len(decoder.decode_all(login))==1
    assert decoder.capture_epoch!=old_epoch and decoder._verified_player_guids=={}
    assert decoder._owned_items=={} and decoder.entity_fragments=={}
    assert decoder.collection_decode_failures==0
    newer=decoder.decode_all(replace(verify,record_number=101,timestamp=1001.1))[-1]
    assert newer.event_type=='SESSION_BASELINE'
    assert newer.payload['character_guid']==f'Player-1602-{low:08X}'
    provider=SessionContextProvider(ProcessIdentity(77,'0000000000000001',70575))
    assert provider.accept_baseline(baseline.to_dict())
    before=provider.continuity_generation
    assert provider.accept_baseline(newer.to_dict())
    assert provider.continuity_generation>before
    assert not provider.accept_baseline(baseline.to_dict())


def test_instance_layout_cannot_be_claimed_by_an_unreviewed_family_or_wrong_opcode():
    decoder,verify,create=cross_connection()
    event=next(e for e in decoder.decode_all(create) if e.event_type=='SESSION_BASELINE').to_dict()
    for changes in ({'game_build':69587},{'opcode_name':'SMSG_LOGIN_VERIFY_WORLD'}):
        with pytest.raises(ValueError):
            normalize_event({**event,'provenance':{**event['provenance'],**changes}})


def test_correlated_instance_baseline_repairs_identity_after_loss_but_not_old_collection_data(native):
    native.provider.require_packet_baseline('test_delivery_gap')
    native.adapter.observations(None,native.world,10.)
    assert native.provider.expected(77) is None
    decoder,verify,create=cross_connection(at=1000.)
    baseline=next(e for e in decoder.decode_all(create) if e.event_type=='SESSION_BASELINE')
    native.feed(baseline)
    assert native.provider.expected(77) is not None
    assert native.provider.capture_epoch==decoder.capture_epoch
    assert native.world.query.owned_item_count(12345,10.)['status']=='UNKNOWN'
    assert native.world.query.quest_presence(55639,10.)['state']=='UNKNOWN'


def test_bridge_relogin_resets_replay_and_progress_even_without_rotating_the_file(tmp_path,monkeypatch):
    from wowbot.packetio import ymir_bridge as module,process_identity,stream_progress
    from wowbot.packetio.forwarder import SnapshotReplayForwarder
    from test_packet_entities import records,monster_move
    decoder,verify=session_events(build=70575)
    login=PktV31StreamParser().feed(pkt_bytes('CMSG_PLAYER_LOGIN',
        packed_guid()+struct.pack('<fB',500.,0),build=70575))[0]
    entity=replace(records('SMSG_ON_MONSTER_MOVE',monster_move(),build=70575)[1],record_number=2)
    class Follower:
        def __init__(self,path):self.parser=type('Parser',(),{'header':decoder.header})()
        def snapshot(self):return {'fixture':True}
        def records(self,stop):
            yield login
            yield verify
            yield entity
            yield replace(login,record_number=3,timestamp=1001.)
            yield replace(verify,record_number=4,timestamp=1001.)
    class UDP:
        def __init__(self):self.sent=0;self.events=[];self.progress=[]
        def context_id(self):return None
        def emit(self,event):self.events.append(event);self.sent+=1;return True
        def emit_progress(self,value):self.progress.append(value);self.sent+=1;return True
        def close(self):pass
    class Replay(SnapshotReplayForwarder):
        resets=0
        def reset_capture(self):
            self.resets+=1
            super().reset_capture()
    udp=UDP();replay=Replay(udp)
    monkeypatch.setattr(module,'UdpJsonForwarder',lambda **kwargs:udp)
    monkeypatch.setattr(module,'SnapshotReplayForwarder',lambda value:replay)
    monkeypatch.setattr(module,'PktFileFollower',Follower)
    monkeypatch.setattr(process_identity,'selected_process_identity',lambda pid:
        ProcessIdentity(77,'0000000000000001',70575))
    real=stream_progress.CaptureProgress
    monkeypatch.setattr(stream_progress,'CaptureProgress',lambda:real(interval=0.))
    path=tmp_path/'capture.pkt';path.write_bytes(b'fixture')
    bridge=module.YmirAgentBridge(executable=tmp_path/'not-started.exe',output=tmp_path,
                                  selected_pid=77,endpoint_path=tmp_path/'endpoint.json')
    bridge._stream(path)
    assert bridge.process is None and bridge.snapshot()['error'] is None
    baselines=[e for e in udp.events if e.event_type=='SESSION_BASELINE']
    assert len(baselines)==2 and baselines[0].payload['capture_epoch']!=baselines[1].payload['capture_epoch']
    assert replay.resets==2 and replay.snapshot.entities=={} and replay.quest_pois.events=={}
    assert replay.session_baseline==baselines[-1]
    assert [p['record_number'] for p in udp.progress]==[1,2,4]
    assert all(p['decode_failures']==0 for p in udp.progress)
