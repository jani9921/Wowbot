"""Received progress is not applied game state, freshness or input authority."""
from dataclasses import replace
import json
import struct

import pytest

from wowbot.agent.observation_ingestion import ObservationIngestion
from wowbot.packetio.ipc import canonical,envelope
from wowbot.packetio.stream_progress import SCHEMA,CaptureProgress,normalize
from test_packet_delivery_20261030 import native,SENDER
from test_native_inventory_20261030 import events
from test_native_inventory_delta_20261030 import delta_payload
from test_session_bootstrap_20261029 import session_events


def value(native, *, record=100, at=10., **changes):
    return {'schema':SCHEMA,'selected_pid':77,'game_build':70575,
        'process_generation':native.provider.process.generation,
        'capture_epoch':native.decoder.capture_epoch,'timestamp':1000.+at-10.,
        'record_number':record,'decode_failures':0,**changes}


def control(native, *, record=100, at=10., poll=True, ingest=True, **changes):
    native.inbox._clock=lambda:at
    native.inbox._wall_clock=lambda:1000.+at-10.
    descriptor=json.loads(native.adapter.path.read_text())
    if native.context_id!=descriptor['context']['context_id']:
        native.context_id,native.sequence=descriptor['context']['context_id'],0
    native.sequence+=1
    raw=envelope(value(native,record=record,at=at,**changes),descriptor,
                 stream={'sender_id':SENDER,'sequence':native.sequence})
    assert native.inbox.ingest_datagram(canonical(raw))
    if not poll:return ()
    observations=native.adapter.observations(None,native.world,at)
    if ingest:
        for obs in observations:native.world.ingest(obs)
    return observations


def test_progress_requires_actual_world_records_and_preserves_original_capture_time():
    decoder,record=session_events(build=70575)
    witness=CaptureProgress(clock=lambda:2000.,interval=0.)
    assert witness.note(replace(record,record_number=0,connection_index=999),decoder) is None
    assert witness.note(record,decoder) is None  # login intent has not been verified
    decoder.decode_all(record)
    result=witness.note(replace(record,record_number=2),decoder)
    assert result['timestamp']==record.timestamp==1000. and result['record_number']==2
    assert result['decode_failures']==0
    assert set(result)=={'schema','selected_pid','timestamp','capture_epoch','process_generation',
                         'game_build','record_number','decode_failures'}
    assert witness.note(replace(record,record_number=3,connection_index=999),decoder) is None


@pytest.mark.parametrize('changes',[{'raw_payload':'private'},{'record_number':True},
    {'game_build':1},{'capture_epoch':'invalid'},{'timestamp':float('nan')},
    {'process_generation':'not-a-process-lifetime'},{'decode_failures':-1}])
def test_progress_rejects_unknown_private_or_unreviewed_fields(native,changes):
    with pytest.raises(ValueError):normalize(value(native,**changes))


def test_authenticated_progress_is_only_applied_after_the_model_consumes_its_observation(native):
    before=native.world.last_received
    latest=native.world.latest
    observations=control(native,ingest=False)
    assert len(observations)==1 and observations[0].source=='PACKET_PROGRESS'
    assert native.world.query.packet_stream_progress(10.)['status']=='UNKNOWN'
    result=ObservationIngestion.ingest(native.world,None,observations)
    assert result.durable==()
    state=native.world.query.packet_stream_progress(10.)
    assert state['status']=='APPLIED' and state['collection_events_checked']>=3
    assert state['record_number']==100 and state['sample_time']==10.
    state['record_number']=999
    assert native.world.query.packet_stream_progress(10.)['record_number']==100
    assert native.world.last_received==before and native.world.latest is latest
    assert not any(e.event_type in {'QUEST_ACCEPTED','QUEST_COMPLETED','LOOT_RECEIVED'}
                   for e in native.world.event_records)


def test_reordered_application_cannot_claim_that_missing_collection_delta_was_processed(native):
    changed=events(delta_payload(quantity=11),native.decoder)[1][-1]
    native.feed(changed,poll=False)
    observations=control(native,ingest=False)
    assert [o.source for o in observations]==['PACKET_TELEMETRY','PACKET_PROGRESS']
    assert native.world.ingest(observations[1])
    assert native.world.query.packet_stream_progress(10.)['status']=='UNAPPLIED'
    assert native.world.ingest(observations[0])
    assert native.world.query.owned_item_count(12345,10.)['count']==11
    control(native,record=101)
    assert native.world.query.packet_stream_progress(10.)['status']=='UNAPPLIED'


def test_ordered_deferred_batch_accepts_delta_before_its_watermark(native):
    changed=events(delta_payload(quantity=11),native.decoder)[1][-1]
    native.feed(changed,poll=False)
    observations=control(native,ingest=False)
    assert ObservationIngestion.ingest(native.world,None,observations).durable==()
    assert native.world.query.packet_stream_progress(10.)['status']=='APPLIED'
    assert native.world.query.owned_item_count(12345,10.)['count']==11


def test_controls_coalesce_without_overtaking_unconsumed_semantic_deltas(native):
    control(native,record=100,poll=False)
    changed=events(delta_payload(quantity=11),native.decoder)[1][-1]
    native.feed(changed,poll=False)
    control(native,record=101,poll=False)
    assert native.inbox.diagnostics()['queued_progress']==1
    observations=native.adapter.observations(None,native.world,10.)
    assert [o.source for o in observations]==['PACKET_TELEMETRY','PACKET_PROGRESS']
    ObservationIngestion.ingest(native.world,None,observations)
    assert native.world.query.packet_stream_progress(10.)['status']=='APPLIED'
    assert native.world.query.packet_stream_progress(10.)['record_number']==101


@pytest.mark.parametrize('changes',[{'capture_epoch':'b'*32},{'game_build':70448},
    {'process_generation':'0000000000000002'}])
def test_wrong_capture_build_or_process_progress_does_not_establish_a_watermark(native,changes):
    control(native,**changes)
    assert native.world.query.packet_stream_progress(10.)['status']=='UNKNOWN'


def test_deferred_pre_gap_progress_cannot_reestablish_the_new_generation(native):
    observations=control(native,ingest=False)
    native.provider.invalidate('stream_gap')
    assert native.provider.accept_baseline(native.baseline.to_dict())
    assert native.world.ingest(observations[0]) is False
    assert native.world.query.packet_stream_progress(10.)['status']=='UNKNOWN'


def test_decoder_failure_drops_native_baselines_without_exporting_the_failed_bytes(native):
    record=session_events(build=70575)[1]
    from wowbot.packetio.opcodes_12_1 import FAMILY_OPCODES
    broken=replace(record,opcode=FAMILY_OPCODES[70340]['SMSG_UPDATE_OBJECT'],payload=b'PRIVATE_INVALID')
    records=native.decoder.decode_all(broken)
    assert len(records)==1 and records[0].event_type=='PACKET_OPCODE_OBSERVED'
    assert native.decoder.collection_decode_failures==1
    assert native.decoder._owned_items=={} and native.decoder.entity_fragments=={}
    assert 'PRIVATE_INVALID' not in str(records[0].to_dict())
    control(native,decode_failures=1)
    assert native.world.query.packet_stream_progress(10.)['status']=='DECODE_GAP'
    assert native.world.query.owned_item_count(12345,10.)['status']=='UNKNOWN'
    assert native.world.query.quest_presence(123456,10.)['state']=='UNKNOWN'
    assert native.world.last_received==9.1


def test_only_a_fresh_applied_chain_leases_native_fields_never_ui_freshness(native):
    # REV4 retained collections (2026-10-31): an expired witness extends
    # nothing; a fresh, chained APPLIED witness proves that no own collection
    # change was missed since the 10.0 baseline, so those field clocks stay
    # current (the server sends VALUES only on change). UI freshness never.
    control(native)
    assert native.world.query.packet_stream_progress(12.1)['status']=='EXPIRED'
    assert native.world.query.owned_item_count(12345,12.1)['status']=='UNKNOWN'
    assert native.world.query.quest_presence(55639,12.1)['state']=='UNKNOWN'
    control(native,record=101,at=12.1)
    assert native.world.query.packet_stream_progress(12.1)['status']=='APPLIED'
    assert native.world.query.owned_item_count(12345,12.1)['count']==7
    assert native.world.query.quest_presence(55639,12.1)['state']=='PRESENT'
    assert native.world.query.owned_item_count(12345,14.2)['status']=='UNKNOWN'   # the witness aged out
    assert native.world.last_received==9.1


def test_receding_record_or_codec_counter_never_becomes_newer_applied_progress(native):
    control(native)
    control(native,record=99)
    assert native.world.query.packet_stream_progress(10.)['status']=='UNAPPLIED'


def test_removed_provider_or_invalid_query_clock_cannot_preserve_a_progress_witness(native):
    control(native)
    for now in (True,float('nan'),None):
        assert native.world.query.packet_stream_progress(now)['status']=='UNKNOWN'
    native.world.session_context_provider=None
    assert native.world.query.packet_stream_progress(10.)['status']=='UNKNOWN'


def test_bridge_follows_real_decoder_progress_and_resets_on_rotated_header(tmp_path,monkeypatch):
    from wowbot.packetio import ymir_bridge as module, process_identity, stream_progress
    from wowbot.packetio.pkt import PktV31StreamParser
    from wowbot.session_context import ProcessIdentity
    from test_packet_codecs import pkt_bytes,packed_guid
    decoder,verification=session_events(build=70575)
    login=PktV31StreamParser().feed(pkt_bytes('CMSG_PLAYER_LOGIN',
        packed_guid()+struct.pack('<fB',500.,0),build=70575))[0]
    from test_native_inventory_20261030 import item_payload
    from wowbot.packetio.opcodes_12_1 import FAMILY_OPCODES
    item=replace(verification,record_number=2,opcode=FAMILY_OPCODES[70340]['SMSG_UPDATE_OBJECT'],payload=item_payload())
    class Follower:
        def __init__(self,path):self.parser=type('Parser',(),{'header':decoder.header})()
        def snapshot(self):return {'fixture':True}
        def records(self,stop):
            yield login
            yield verification
            yield item
            self.parser.header=replace(decoder.header)
            yield login
            yield verification
    class UDP:
        def __init__(self,**kwargs):self.sent=0;self.progress=[]
        def context_id(self):return None
        def emit(self,event):self.sent+=1;return True
        def emit_progress(self,value):self.progress.append(value);self.sent+=1;return True
        def close(self):pass
    udp=UDP()
    monkeypatch.setattr(module,'UdpJsonForwarder',lambda **kwargs:udp)
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
    assert [p['record_number'] for p in udp.progress]==[1,2,1]
    assert len({p['capture_epoch'] for p in udp.progress})==2
    assert all(p['timestamp']==1000. for p in udp.progress)


def test_real_forwarder_signs_progress_in_the_same_sequence_and_rejects_wrong_scope(native):
    from wowbot.packetio.forwarder import UdpJsonForwarder
    from wowbot.packetio.ipc import verify
    descriptor=json.loads(native.adapter.path.read_text())
    class Socket:
        def __init__(self):self.sent=[]
        def sendto(self,data,address):self.sent.append(json.loads(data))
        def close(self):pass
    forwarder=UdpJsonForwarder(descriptor_path=native.adapter.path,
                              process_generation=native.provider.process.generation)
    forwarder.socket.close()
    forwarder.socket=Socket()
    forwarder._current_descriptor=lambda:descriptor
    try:
        assert forwarder.emit_progress(value(native))
        sent=forwarder.socket.sent[0]
        assert sent['stream']['sequence']==1 and verify(sent,descriptor)['schema']==SCHEMA
        for changes in ({'selected_pid':88},{'game_build':70448},
                        {'process_generation':'2'},{'timestamp':1.},{'raw_secret':'blocked'}):
            assert not forwarder.emit_progress(value(native,**changes))
        assert len(forwarder.socket.sent)==1
        descriptor['context']={**descriptor['context'],'bootstrap':True}
        assert not forwarder.emit_progress(value(native))
    finally:
        forwarder.close()
