"""Server counters must reach the shared world without borrowing input authority."""
from dataclasses import replace
import struct

import pytest

from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import decoded, packed_guid
from wowbot.agent.models import Observation


def credit(count=1, *, quest=55639, object_id=182800):
    payload = packed_guid() + struct.pack("<iiHHI", quest, object_id, count, 8, 0)
    return decoded("SMSG_QUEST_UPDATE_ADD_CREDIT", payload)[-1]


def test_real_packet_bridge_projects_counters_without_refreshing_addon_authority(bridge):
    deliver(bridge, credit(3))
    row = bridge.world.state["packet_quest_credits"]["55639"]["182800"]
    assert row == {"count": 3, "required": 8, "sampled_at": 10.}
    assert bridge.world.last_received == 9.
    assert bridge.world.addon_state.get("packet_quest_credits") is None
    bridge.world.ingest(Observation.create(addon(frame_id="addon:10.2", monotonic_time=10.2, timestamp=10.2), 10.2))
    assert bridge.world.state["packet_quest_credits"]["55639"]["182800"] == row


@pytest.mark.parametrize("change", [{"session_id": "other"}, {"character_guid": "Player-1602-9999"},
                                    {"game_build": "69588"}, {"loading": True}, {"active_quests": []}])
def test_context_change_or_removed_quest_cannot_reuse_old_counters(bridge, change):
    deliver(bridge, credit(8))
    bridge.world.ingest(Observation.create(addon(frame_id="context:changed", **change), 10.2))
    assert not bridge.world.state.get("packet_quest_credits")
    bridge.world.ingest(Observation.create(addon(frame_id="context:back"), 10.3))
    assert not bridge.world.state.get("packet_quest_credits")


def test_other_quest_unverified_build_and_expired_samples_cannot_confirm_a_route(bridge):
    deliver(bridge, credit(8, quest=999))
    assert not bridge.world.state.get("packet_quest_credits")
    value = credit(8)
    deliver(bridge, replace(value, provenance={**value.provenance, "game_build": 69214}))
    assert not bridge.world.state.get("packet_quest_credits")
    deliver(bridge, credit(7))
    bridge.world.ingest(Observation.create(addon(frame_id="addon:1000", monotonic_time=1000., timestamp=1000.), 1000.))
    assert not bridge.world.state.get("packet_quest_credits")
