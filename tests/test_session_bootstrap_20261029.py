"""Cold/warm session contracts with framed WPP payloads; no game input."""
from dataclasses import replace
import json
import struct

import pytest

from wowbot.agent.models import Observation
from wowbot.agent.runtime_packet_source import RuntimePacketSource
from wowbot.agent.world import WorldModel
from wowbot.packetio.inbox import PacketEventInbox
from wowbot.packetio.ipc import canonical, envelope
from wowbot.packetio.pkt import OpcodeManifest, PktEventDecoder, PktV31StreamParser
from wowbot.packetio.validation import normalize_event, verified_semantics
from wowbot.session_context import BaselineState, ProcessIdentity, SessionContextProvider
from test_packet_codecs import packed_guid, pkt_bytes, decoded
from test_packet_agent_bridge import addon


def session_events(*, build=69587, connection=1, malformed=False):
    parser = PktV31StreamParser()
    login = parser.feed(pkt_bytes('CMSG_PLAYER_LOGIN', packed_guid()+struct.pack('<fB', 500., 0), build=build))[0]
    decoder = PktEventDecoder(selected_pid=77, header=parser.header, manifest=OpcodeManifest.reviewed(build),
                              process_generation='0000000000000001')
    assert len(decoder.decode_all(login)) == 1  # intent is not world identity
    raw = pkt_bytes('SMSG_LOGIN_VERIFY_WORLD', struct.pack('<iffffI', 2175, 1., 2., 3., .5, 0), build=build)
    record = PktV31StreamParser().feed(raw)[0]
    record = replace(record, record_number=1, connection_index=connection,
                     payload=record.payload[:-1] if malformed else record.payload)
    return decoder, record


@pytest.mark.parametrize('build', [69587, 70448, 70575])
def test_reviewed_login_requires_same_connection_server_world_and_exact_body(build):
    decoder, record = session_events(build=build)
    event = decoder.decode_all(record)[-1]
    assert event.event_type == 'SESSION_BASELINE' and verified_semantics(normalize_event(event.to_dict()))
    assert event.payload['character_guid'] == 'Player-1602-00001234'
    assert event.payload['world_map_id'] == 2175
    assert set(event.payload) == {'character_guid', 'world_map_id', 'capture_epoch', 'sequence', 'process_generation'}


@pytest.mark.parametrize('kwargs', [{'connection': 2}, {'malformed': True}])
def test_incomplete_or_different_connection_never_creates_baseline(kwargs):
    decoder, record = session_events(**kwargs)
    assert len(decoder.decode_all(record)) == 1


def test_late_capture_cannot_guess_own_guid_from_other_events():
    decoder, record = session_events()
    cold = PktEventDecoder(selected_pid=77, header=decoder.header, manifest=decoder.manifest)
    assert len(cold.decode_all(record)) == 1


def test_bootstrap_to_real_world_without_addon_and_without_input_authority(tmp_path):
    provider = SessionContextProvider(ProcessIdentity(77, '0000000000000001'))
    inbox = PacketEventInbox(77, port=0, autostart=False, clock=lambda: 10., wall_clock=lambda: 1000.)
    world = WorldModel(session_context_provider=provider)
    source = RuntimePacketSource(77, tmp_path, source=inbox, session_provider=provider, wall_clock=lambda: 999.)
    try:
        assert source.observations(None, world, 10.) == ()
        assert source.context['bootstrap'] is True
        decoder, record = session_events()
        baseline = decoder.decode_all(record)[-1]
        descriptor = json.loads(source.path.read_text())
        assert inbox.ingest_datagram(canonical(envelope(baseline.to_dict(), descriptor)))
        assert source.observations(None, world, 10.) == ()
        assert provider.state is BaselineState.READY and provider.source == 'PACKET_BASELINE'
        assert provider.context.world.ui_map_id is None and provider.context.world.phase is None
        descriptor = json.loads(source.path.read_text())
        assert 'bootstrap' not in descriptor['context']
        # One producer owns the baseline and following movement packets.
        move = decoder.decode_all(PktV31StreamParser().feed(pkt_bytes())[0])[-1]
        assert inbox.ingest_datagram(canonical(envelope(move.to_dict(), descriptor)))
        observations = source.observations(None, world, 10.)
        assert len(observations) == 1 and world.ingest(observations[0])
        assert world.state['player_world_position']['instance_id'] == 2175
        assert world.state['player_world_position']['z'] == 31.75
        assert world.latest is None and not world.fresh(10.)  # no addon/UI authority invented
    finally:
        source.close()


def test_addon_session_is_explicit_migration_and_identity_conflict_revokes():
    provider = SessionContextProvider(ProcessIdentity(77, '0000000000000001'))
    provider.observe_addon(addon())
    assert provider.source == 'ADDON_MIGRATION'
    decoder, record = session_events()
    event = decoder.decode_all(record)[-1]
    assert provider.accept_baseline(event.to_dict())
    assert provider.context.identity.session_id == 'live-s'
    provider.observe_addon(addon(character_guid='Player-1602-00009999'))
    assert provider.expected(77) is None and provider.state is BaselineState.MISMATCH


def test_gap_is_not_repaired_by_an_addon_relabel_and_wrong_pid_or_old_revision_is_rejected():
    provider = SessionContextProvider(ProcessIdentity(77, '0000000000000001'))
    decoder, record = session_events()
    event = decoder.decode_all(record)[-1]
    assert not provider.accept_baseline(replace(event, selected_pid=88).to_dict())
    assert provider.accept_baseline(event.to_dict())
    provider.invalidate('stream_gap')
    provider.observe_addon(addon())
    assert provider.expected(77) is None
    assert provider.accept_baseline(event.to_dict())
    old = replace(event, payload={**event.payload, 'sequence': 0})
    assert not provider.accept_baseline(old.to_dict())


def test_warm_identity_replay_has_no_movement_or_other_baseline_claims():
    from wowbot.packetio.forwarder import SnapshotReplayForwarder
    decoder, record = session_events()
    event = decoder.decode_all(record)[-1]
    class Sink:
        context = None
        events = []
        def context_id(self): return self.context
        def emit(self, value): self.events.append(value); return True
        def close(self): pass
    sink = Sink()
    replay = SnapshotReplayForwarder(sink, wall_clock=lambda: 2000.)
    replay.emit(event)
    sink.events.clear()
    sink.context = 'new-runtime'
    replay.flush()
    assert len(sink.events) == 1
    baseline = sink.events[0]
    assert baseline.event_type == 'SESSION_BASELINE' and baseline.timestamp == 2000.
    assert baseline.payload == event.payload and not {'x', 'y', 'z'} & baseline.payload.keys()
    provider = SessionContextProvider(ProcessIdentity(77, '0000000000000001'))
    assert provider.accept_baseline(baseline.to_dict())
    assert provider.diagnostics()['coverage']['inventory'] == 'UNKNOWN'


def test_process_reuse_build_mismatch_and_map_transition_need_new_authority():
    decoder, record = session_events()
    baseline = decoder.decode_all(record)[-1]
    reused = SessionContextProvider(ProcessIdentity(77, '0000000000000002'))
    assert not reused.accept_baseline(baseline.to_dict())
    wrong_build = SessionContextProvider(ProcessIdentity(77, '0000000000000001', 70575))
    assert not wrong_build.accept_baseline(baseline.to_dict())
    provider = SessionContextProvider(ProcessIdentity(77, '0000000000000001'),
        maps_compatible=lambda a, b: a == b or {a, b} == {2444, 2534})
    provider.observe_addon(addon(player_world_position={'instance_id': 2444}))
    value = replace(baseline, payload={**baseline.payload, 'world_map_id': 2534})
    assert provider.accept_baseline(value.to_dict())
    assert provider.context.world.instance_id == 2444  # verified cosmetic mapping, not guessed aliasing
    change = decoded('SMSG_NEW_WORLD', struct.pack('<iffffiiI', 1, 1., 2., 3., .5, 0, 0, 0))[-1].to_dict()
    change['sampled_at_monotonic'] = 10.
    assert provider.advance_world(change)
    assert provider.context.world.instance_id == 1 and provider.local_ui_ready is False
    provider.observe_addon(addon(monotonic_time=11., player_world_position={'instance_id': 2444}))
    assert provider.local_ui_ready is False
    provider.observe_addon(addon(monotonic_time=11., player_world_position={'instance_id': 1}))
    assert provider.local_ui_ready is True


@pytest.mark.parametrize('text,expected', [('12.1.5.70575', 70575), ('12, 1, 0, 69587', 69587)])
def test_executable_version_parsing_uses_exact_reviewed_build(text, expected):
    from wowbot.packetio.process_identity import retail_build
    assert retail_build(text) == expected


@pytest.mark.parametrize('text', ['12.1.5.70576', '11.2.7.64632', 'unknown', '12.1.5'])
def test_executable_version_never_uses_a_nearby_build(text):
    from wowbot.packetio.process_identity import retail_build
    with pytest.raises(ValueError):
        retail_build(text)
