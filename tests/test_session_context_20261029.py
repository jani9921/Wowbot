"""Context transitions through the real packet bridge; no capture or game input."""
import json
from types import SimpleNamespace

import pytest

from test_packet_entities import (
    GARRICK, OMM_ONE_POINT, QGS_GARRICK, addon, bridge, deliver, semantic,
)
from wowbot.agent.models import Observation
from wowbot.agent.runtime_packet_source import RuntimePacketSource
from wowbot.agent.world import WorldModel
from wowbot.packetio.inbox import PacketEventInbox
from wowbot.packetio.ipc import canonical, envelope


def test_phase_transition_invalidates_entities_without_resurrecting_them(bridge):
    deliver(bridge, *semantic("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK))
    assert GARRICK in bridge.world.state["packet_entities"]
    bridge.world.ingest(Observation.create(addon(frame_id="phase:new", phase="new-phase"), 10.1))
    assert not bridge.world.state.get("packet_entities")
    bridge.world.ingest(Observation.create(addon(frame_id="phase:back"), 10.2))
    assert not bridge.world.state.get("packet_entities")


def test_ui_map_transition_preserves_entities_in_the_same_world(bridge):
    deliver(bridge, *semantic("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK))
    before = bridge.world.state["packet_entities"][GARRICK]
    bridge.world.ingest(Observation.create(addon(frame_id="map:view", map_id=84), 10.1))
    after = bridge.world.state["packet_entities"][GARRICK]
    assert after["quest_giver"]["quest_available"] is True
    assert after["quest_giver"]["sampled_at"] == before["quest_giver"]["sampled_at"]
    assert after["quest_giver"]["age"] == pytest.approx(.1)
    assert bridge.world.state["map_id"] == 84


@pytest.fixture
def opening_bridge(tmp_path):
    """Source sees the newest payload before the WorldModel has merged it."""
    world = WorldModel()
    clock = SimpleNamespace(now=10., wall=1000.)
    inbox = PacketEventInbox(77, port=0, autostart=False, clock=lambda: clock.now,
                             wall_clock=lambda: clock.wall)
    adapter = RuntimePacketSource(77, tmp_path, source=inbox, wall_clock=lambda: 999.)
    adapter.observations(addon(), world, 10.)
    yield SimpleNamespace(world=world, inbox=inbox, adapter=adapter, clock=clock,
                          path=tmp_path/"packet_endpoint.json")
    adapter.close()


@pytest.mark.parametrize("change, accepted", [
    ({"session_id": "next-session"}, False),
    ({"phase": "new-phase"}, False),
    ({"phase": None}, False),
    ({"phase": 0}, False),
    ({}, True),
    ({"map_id": 84}, True),
])
def test_pending_entity_requires_the_same_session_and_phase(opening_bridge, change, accepted):
    fixture = opening_bridge
    descriptor = json.loads(fixture.path.read_text())
    for event in semantic("SMSG_QUEST_GIVER_STATUS", QGS_GARRICK):
        assert fixture.inbox.ingest_datagram(canonical(envelope(event.to_dict(), descriptor)))
    observations = fixture.adapter.observations(addon(), fixture.world, 10.)
    assert len(observations) == 1
    assert not fixture.world.ingest(observations[0])
    assert not fixture.world.state.get("packet_entities")
    fixture.world.ingest(Observation.create(addon(frame_id="context:ready", **change), 10.1))
    fixture.clock.now = 10.5
    fixture.adapter.observations(None, fixture.world, fixture.clock.now)
    deliver(fixture, *semantic("SMSG_ON_MONSTER_MOVE", OMM_ONE_POINT))
    entities = fixture.world.state.get("packet_entities") or {}
    assert (GARRICK in entities) is accepted
    if accepted:
        assert entities[GARRICK]["quest_giver"]["sampled_at"] == 10.
