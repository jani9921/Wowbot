"""A same-character reconnect/gap cannot retain a native field baseline."""
from dataclasses import replace
import json

from wowbot.agent.models import Observation
from wowbot.agent.runtime_packet_source import RuntimePacketSource
from wowbot.agent.world import WorldModel
from wowbot.packetio.inbox import PacketEventInbox
from wowbot.packetio.ipc import canonical, envelope
from wowbot.session_context import ProcessIdentity, SessionContextProvider
from test_native_quest_log_20261030 import quest_event, slot
from test_own_baseline_20261030 import create_payload
from test_own_health_packets_20261030 import own_event, own_payload
from test_packet_agent_bridge import addon, bridge, deliver
from test_session_bootstrap_20261029 import session_events


def connected(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575',health=100,max_health=100),9.1))
    bridge.adapter.observations(None,bridge.world,10.)
    provider = SessionContextProvider(ProcessIdentity(77,'0000000000000001'))
    provider.observe_addon(bridge.world.addon_state)
    decoder, verification = session_events(build=70575)
    baseline = decoder.decode_all(verification)[-1]
    assert provider.accept_baseline(baseline.to_dict())
    bridge.world.session_context_provider = provider
    _, record = own_event()
    event = decoder.decode_all(replace(record,payload=create_payload()))[-1]
    deliver(bridge,event)
    return provider,decoder,baseline,record


def test_same_epoch_gap_evicts_native_baseline_even_when_identity_and_map_are_unchanged(bridge):
    provider,decoder,baseline,record = connected(bridge)
    assert bridge.world.state['packet_own_health']['coverage'] == 'COMPLETE'
    old_scope = provider.context.entity_scope()
    generation = provider.continuity_generation
    provider.invalidate('stream_gap')
    assert provider.accept_baseline(baseline.to_dict())
    assert provider.context.entity_scope() == old_scope
    assert provider.continuity_generation > generation
    # Read-only queries stop considering old packet evidence immediately,
    # even before the next projection has evicted its cached values.
    assert bridge.world.query.field_resolution('health',10.).value == 100
    assert bridge.world.belief('health',10.)['value'] == 100
    values = decoder.decode_all(replace(record,payload=own_payload(health=60)))[-1]
    deliver(bridge,values)
    assert bridge.world.state['health'] == 60
    assert bridge.world.state['packet_own_health']['coverage'] == 'PARTIAL'
    assert provider.diagnostics()['coverage']['own_health'] == 'PARTIAL'
    assert bridge.world.last_received == 9.1


def test_quest_membership_is_unknown_after_gap_without_waiting_for_its_ttl(bridge):
    provider,decoder,baseline,_ = connected(bridge)
    _,record = quest_event([slot(i,55639 if i == 3 else 0) for i in range(175)])
    deliver(bridge,decoder.decode_all(record)[-1])
    assert bridge.world.query.quest_presence(88719,10.)['state'] == 'ABSENT'
    provider.invalidate('stream_gap')
    assert provider.accept_baseline(baseline.to_dict())
    assert bridge.world.query.quest_presence(55639,10.)['state'] == 'UNKNOWN'
    assert bridge.world.query.quest_presence(88719,10.)['state'] == 'UNKNOWN'
    bridge.world._rebuild_state()
    assert '_packet_quest_log' not in bridge.world.__dict__
    assert 'packet_quest_log' not in bridge.world.state


def test_ui_map_only_change_does_not_invalidate_current_native_baseline(bridge):
    provider,_,_,_ = connected(bridge)
    generation = provider.continuity_generation
    provider.observe_addon({**bridge.world.addon_state,'map_id':1410})
    assert provider.continuity_generation == generation
    assert bridge.world.query.field_resolution('health',10.).value == 40


def test_baseline_replay_without_gap_preserves_generation_and_field_coverage(bridge):
    provider,_,baseline,_ = connected(bridge)
    generation = provider.continuity_generation
    assert provider.accept_baseline(baseline.to_dict())
    assert provider.continuity_generation == generation
    assert provider.diagnostics()['coverage']['own_health'] == 'COMPLETE'
    assert bridge.world.query.field_resolution('health',10.).value == 40


def test_reducer_also_rejects_a_foreign_epoch_after_the_adapter_boundary(bridge):
    _,_,_,_ = connected(bridge)
    other,record = own_event(health=60)
    event = other.decode_all(record)[-1]
    descriptor = json.loads(bridge.path.read_text())
    assert bridge.inbox.ingest_datagram(canonical(envelope(event.to_dict(),descriptor)))
    observations = bridge.adapter.observations(None,bridge.world,10.)
    assert len(observations) == 1
    assert not bridge.world.ingest(observations[0])
    assert bridge.world.state['health'] == 40


def test_other_capture_epoch_cannot_reuse_the_current_authenticated_endpoint(tmp_path):
    provider = SessionContextProvider(ProcessIdentity(77,'0000000000000001'))
    inbox = PacketEventInbox(77,port=0,autostart=False,clock=lambda:10.,wall_clock=lambda:1000.)
    world = WorldModel(session_context_provider=provider)
    adapter = RuntimePacketSource(77,tmp_path,source=inbox,session_provider=provider,wall_clock=lambda:999.)
    try:
        adapter.observations(None,world,10.)
        decoder,record = session_events(build=70575)
        baseline = decoder.decode_all(record)[-1]
        descriptor = json.loads(adapter.path.read_text())
        assert inbox.ingest_datagram(canonical(envelope(baseline.to_dict(),descriptor)))
        assert adapter.observations(None,world,10.) == ()
        other,record = own_event()
        event = other.decode_all(record)[-1]
        assert event.provenance['capture_epoch'] != decoder.capture_epoch
        descriptor = json.loads(adapter.path.read_text())
        assert inbox.ingest_datagram(canonical(envelope(event.to_dict(),descriptor)))
        assert adapter.observations(None,world,10.) == ()
        assert adapter.wrong_context_discards == 1
        assert adapter.diagnostics()['capture_epoch_error'] == 'capture_epoch_mismatch'
        old_source,missing_record = own_event(health=61)
        missing = old_source.decode_all(missing_record)[-1]
        missing = replace(missing,provenance={k:v for k,v in missing.provenance.items() if k != 'capture_epoch'})
        assert inbox.ingest_datagram(canonical(envelope(missing.to_dict(),descriptor)))
        assert adapter.observations(None,world,10.) == ()
        assert adapter.diagnostics()['status'] == 'source_restart_required'
        assert adapter.diagnostics()['source_restart_required']
        diagnostic = old_source.decode(missing_record)
        assert inbox.ingest_datagram(canonical(envelope(diagnostic.to_dict(),descriptor)))
        assert len(adapter.observations(None,world,10.)) == 1
        assert adapter.diagnostics()['source_restart_required']  # opaque traffic is not recovery
        _,native = own_event()
        current = decoder.decode_all(replace(native,payload=create_payload()))[-1]
        assert inbox.ingest_datagram(canonical(envelope(current.to_dict(),descriptor)))
        assert len(adapter.observations(None,world,10.)) == 1
        assert adapter.diagnostics()['capture_epoch_error'] is None
        assert not world.fresh(10.)
    finally:
        adapter.close()
