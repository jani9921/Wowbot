"""Authenticated delivery gaps invalidate baselines; never operate a client."""
import json
import struct
from collections import deque
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Observation
from wowbot.agent.runtime_packet_source import RuntimePacketSource
from wowbot.agent.world import WorldModel
from wowbot.packetio.forwarder import UdpJsonForwarder
from wowbot.packetio.inbox import PacketEventInbox
from wowbot.packetio.ipc import canonical, envelope, verify
from wowbot.session_context import BaselineState, ProcessIdentity, SessionContextProvider
from test_packet_telemetry import context, event
from test_packet_agent_bridge import addon, bridge
from test_packet_codecs import decoded
from test_session_bootstrap_20261029 import session_events
from test_native_inventory_20261030 import (events, item_payload, create_payload, full_player_tail,
                                          deliver_native, ready)
from test_native_inventory_delta_20261030 import delta_payload

SENDER = 'a'*32


@pytest.fixture
def inbox():
    value = PacketEventInbox(77,port=0,autostart=False,clock=lambda:10.,wall_clock=lambda:1000.)
    value.configure(context())
    yield value
    value.close()


def send(inbox, value, sequence, *, sender=SENDER):
    descriptor = inbox._descriptor
    return inbox.ingest_datagram(canonical(envelope(value.to_dict(),descriptor,
        stream={'sender_id':sender,'sequence':sequence})))


def test_stream_stamp_is_authenticated_and_not_a_semantic_payload(inbox):
    original = event().to_dict()
    value = envelope(original,inbox._descriptor,stream={'sender_id':SENDER,'sequence':1})
    assert verify(value,inbox._descriptor)==original
    value['stream']['sequence']=2
    assert not inbox.ingest_datagram(canonical(value))
    assert inbox.delivery_status()['state']=='UNSEEN'
    assert send(inbox,event(),1)
    row = inbox.poll()[0]
    assert 'sequence' not in row['payload'] and 'ipc_key' not in json.dumps(inbox.diagnostics())


@pytest.mark.parametrize('value',[{'sender_id':'bad','sequence':1}, {'sender_id':SENDER,'sequence':True},
    {'sender_id':SENDER,'sequence':0}, {'sender_id':SENDER,'sequence':2**63},
    {'sender_id':SENDER,'sequence':1,'extra':1}])
def test_invalid_local_stream_stamps_cannot_be_signed(value,inbox):
    with pytest.raises(ValueError):
        envelope(event().to_dict(),inbox._descriptor,stream=value)


def test_sequenced_coalescing_is_lossless_and_duplicates_cannot_rewind_it(inbox):
    for i in range(1,51):
        assert send(inbox,event(timestamp=1000.+i*.001),i)
    assert not send(inbox,event(timestamp=1000.001),1)
    status = inbox.delivery_status()
    assert status['state']=='CONTIGUOUS' and status['sequence']==50 and status['loss_generation']==0
    assert len(inbox.poll())==1 and inbox.coalesced==49


def test_gap_is_sticky_and_late_missing_packet_cannot_repair_old_baselines(inbox):
    assert send(inbox,event(),1)
    assert send(inbox,event(timestamp=1000.002),3)
    assert not send(inbox,event(timestamp=1000.001),2)
    assert send(inbox,event(timestamp=1000.003),4)
    assert inbox.delivery_status()['state']=='GAP'
    assert inbox.delivery_status()['last_loss']=='sequence_gap'
    before = inbox.delivery_status()['loss_generation']
    inbox.configure(context(context_id='new'))
    assert send(inbox,event(timestamp=1000.004),1)
    assert inbox.delivery_status()['state']=='CONTIGUOUS'
    assert inbox.delivery_status()['loss_generation']==before


def test_first_missing_sequence_sender_switch_and_legacy_mode_have_explicit_status(inbox):
    assert send(inbox,event(),2)
    assert inbox.delivery_status()['state']=='GAP'
    inbox.configure(context(context_id='new'))
    assert send(inbox,event(),1)
    assert send(inbox,event(timestamp=1000.001),1,sender='b'*32)
    assert inbox.delivery_status()['last_loss']=='sender_changed'
    assert not send(inbox,event(timestamp=1000.002),2)
    inbox.configure(context(context_id='legacy'))
    assert inbox.ingest_datagram(canonical(envelope(event().to_dict(),inbox._descriptor)))
    assert inbox.delivery_status()['state']=='UNSEQUENCED'


def test_queue_overflow_and_expiry_are_delivery_losses_not_silent_partial_state():
    inbox = PacketEventInbox(77,port=0,max_queue=1,autostart=False,clock=lambda:10.,wall_clock=lambda:1000.)
    try:
        inbox.configure(context())
        assert send(inbox,event('QUEST_COMPLETED',body={'quest_id':1}),1)
        assert send(inbox,event('QUEST_COMPLETED',body={'quest_id':2}),2)
        assert inbox.delivery_status()['last_loss']=='event_mailbox_overflow'
        inbox._clock=lambda:12.1
        assert inbox.poll()==[]
        assert inbox.delivery_status()['last_loss']=='queued_sample_expired'
    finally:
        inbox.close()


def test_legacy_loss_discards_old_native_fields_but_accepts_new_positive_events(bridge):
    ready(bridge)
    decoder = deliver_native(bridge,item_payload())
    assert bridge.world.query.owned_item_count(12345,10.)['count']==7
    bridge.inbox.queue=deque(maxlen=1)
    descriptor = json.loads(bridge.adapter.path.read_text())
    _, values = events(item_payload(qty=8),decoder)
    changed = next(e for e in values if e.event_type=='OWN_ITEM_UPDATE')
    assert bridge.inbox.ingest_datagram(canonical(envelope(changed.to_dict(),descriptor)))
    latest = decoded('SMSG_QUEST_UPDATE_COMPLETE',struct.pack('<I',55639)+b'\x80',build=70575)[-1]
    assert bridge.inbox.ingest_datagram(canonical(envelope(latest.to_dict(),descriptor)))
    observations = bridge.adapter.observations(None,bridge.world,10.)
    assert len(observations)==1 and bridge.world.ingest(observations[0])
    assert bridge.world.query.owned_item_count(12345,10.)['status']=='UNKNOWN'
    assert bridge.adapter.error is None and bridge.adapter.delivery_losses==1


@pytest.fixture
def native(tmp_path):
    provider = SessionContextProvider(ProcessIdentity(77,'0000000000000001',70575))
    world = WorldModel(session_context_provider=provider)
    world.ingest(Observation.create(addon(game_build='70575'),9.1))
    inbox = PacketEventInbox(77,port=0,autostart=False,clock=lambda:10.,wall_clock=lambda:1000.)
    adapter = RuntimePacketSource(77,tmp_path,source=inbox,session_provider=provider,wall_clock=lambda:999.)
    adapter.observations(None,world,10.)
    state = SimpleNamespace(provider=provider,world=world,inbox=inbox,adapter=adapter,
                            sequence=0,context_id=None)
    def feed(value, *, skip=0, poll=True):
        descriptor = json.loads(adapter.path.read_text())
        if descriptor['context']['context_id']!=state.context_id:
            state.context_id, state.sequence = descriptor['context']['context_id'], 0
        state.sequence+=1+skip
        assert inbox.ingest_datagram(canonical(envelope(value.to_dict(),descriptor,
            stream={'sender_id':SENDER,'sequence':state.sequence})))
        if poll:
            for obs in adapter.observations(None,world,10.):world.ingest(obs)
    state.feed=feed
    decoder, record = session_events(build=70575)
    baseline = decoder.decode_all(record)[-1]
    state.decoder, state.baseline = decoder, baseline
    feed(baseline)
    for packet in (create_payload(player_tail=full_player_tail()),item_payload()):
        _, values = events(packet,decoder)
        for value in values:
            if value.event_type.startswith('OWN_'):feed(value)
    assert world.query.owned_item_count(12345,10.)['count']==7
    assert world.query.quest_presence(123456,10.)['state']=='ABSENT'
    yield state
    adapter.close()


@pytest.mark.parametrize('fast',[False,True])
def test_delivery_gap_revokes_native_baselines_and_addon_cannot_repair_it(native,fast):
    value = events(delta_payload(quantity=11),native.decoder)[1][-1]
    native.feed(value,skip=1,poll=False)
    if fast:
        assert native.adapter.peek_own_movement(native.world,10.) is False
    else:
        assert native.adapter.observations(None,native.world,10.)==()
    assert native.provider.state is BaselineState.GAP
    assert not native.world.fresh(10.)  # the existing input gate is revoked immediately
    assert native.provider.diagnostics()['packet_rebaseline_required']
    assert native.world.query.owned_item_count(12345,10.)['status']=='UNKNOWN'
    assert native.world.query.quest_presence(123456,10.)['state']=='UNKNOWN'
    native.provider.observe_addon(native.world.addon_state)
    assert native.provider.state is BaselineState.GAP
    assert native.adapter.context['bootstrap'] is True
    assert native.world.last_received==9.1
    # A fresh identity replay restores identity, not old inventory/quest state.
    native.feed(native.baseline)
    assert native.provider.state is BaselineState.READY
    assert native.world.query.owned_item_count(12345,10.)['status']=='UNKNOWN'
    assert native.world.query.quest_presence(123456,10.)['state']=='UNKNOWN'
    native.feed(events(delta_payload(quantity=12),native.decoder)[1][-1])
    assert native.world.query.owned_item_count(12345,10.)['status']=='UNKNOWN'
    native.feed(events(item_payload(qty=13),native.decoder)[1][-1])
    assert native.world.query.owned_item_count(12345,10.)['count']==13
    assert native.adapter.diagnostics()['delivery_losses']>0


def test_forwarder_signs_every_attempt_and_resets_sequence_only_for_new_context(tmp_path):
    decoder, record = session_events(build=70575)
    value = decoder.decode_all(record)[-1]
    descriptor = {'context':context(game_build=70575),'host':'127.0.0.1','port':12345,'ipc_key':'x'*40}
    class Socket:
        def __init__(self):self.sent=[]
        def sendto(self,data,address):self.sent.append(json.loads(data))
        def close(self):pass
    forwarder = UdpJsonForwarder(descriptor_path=tmp_path/'endpoint.json')
    forwarder.socket.close()
    forwarder.socket=Socket()
    forwarder._current_descriptor=lambda:descriptor
    try:
        assert forwarder.emit(value) and forwarder.emit(value)
        assert [v['stream']['sequence'] for v in forwarder.socket.sent]==[1,2]
        assert all(v['schema']=='aipc.packet-envelope.v2' for v in forwarder.socket.sent)
        for sent in forwarder.socket.sent:assert verify(sent,descriptor)['event_id']==value.event_id
        descriptor['context']={**descriptor['context'],'context_id':'new'}
        assert forwarder.emit(value)
        assert forwarder.socket.sent[-1]['stream']['sequence']==1
    finally:
        forwarder.close()


def test_an_expired_newest_position_or_entity_sample_is_stale_not_a_delivery_gap():
    """Live 2026-10-31 (logins): 182 expired positions were each a delivery
    loss; every loss re-baselined the session and dropped its whole batch, the
    login's quest POI answers with it.  Discrete events still make a gap."""
    inbox = PacketEventInbox(77,port=0,autostart=False,clock=lambda:10.,wall_clock=lambda:1000.)
    try:
        inbox.configure(context())
        motion = decoded()[-1]                                              # own MOVEMENT_UPDATE
        assert motion.event_type == 'MOVEMENT_UPDATE'
        assert send(inbox,motion,1)
        inbox._clock=lambda:12.1
        assert inbox.poll()==[]
        assert inbox.delivery_status()['state']!='GAP' and inbox.take_stale_counts()[0]==1
        assert send(inbox,event('QUEST_COMPLETED',body={'quest_id':1}),2)
        inbox._clock=lambda:14.3
        assert inbox.poll()==[]
        assert inbox.delivery_status()['last_loss']=='queued_sample_expired'
    finally:
        inbox.close()
