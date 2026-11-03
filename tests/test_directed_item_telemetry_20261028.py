"""Actual Lua readers/transport retain self-item facts with no selected unit."""
import json
import pytest

from adapters.telemetry_packets import PacketAssembler
from test_agent_transport import lua_runtime
from test_fast_world_position import LIVE_LIKE_FAST
from test_quest_item_fast_evidence_20261018 import readers
from wowbot.agent.quest_tool_resolver import QuestToolResolver


def test_public_item_reader_reports_usability_and_cooldown_without_a_target():
    lua, api = readers()
    lua.execute("C_Item.IsItemInRange=function() return nil end")
    proof = api.item(lua.globals().quests, None, 10.)
    assert proof.guid is None
    assert proof["items"][1].item_id == 170557
    assert proof["items"][1].is_usable is True
    assert proof["items"][1].in_range is None
    assert proof["items"][1].cooldown_remaining == 0


@pytest.mark.parametrize("replacement", ["return nil", "error('restricted')", "return {secret=true}"])
def test_self_item_does_not_guess_restricted_usability(replacement):
    lua, api = readers()
    lua.execute("C_Item.IsUsableItem=function() " + replacement + " end")
    assert api.item(lua.globals().quests, None, 10.)["items"][1].is_usable is None


def test_actual_bounded_fast_roundtrip_without_target_keeps_item_but_cannot_authorize_f7():
    lua = lua_runtime()
    lua.execute("fast=" + LIVE_LIKE_FAST)
    lua.execute('''fast.target=nil; fast.interact_guid=false
        fast.quest_item_target={items={{quest_id=56034,item_id=170557,
            is_usable=true,cooldown_remaining=0}}}''')
    result, _ = lua.eval("ns.NextLanePackets({character_name='Test',monotonic_time=1},fast,850,850)")
    assert result and len(result.split("|", 6)[6].encode()) <= 850
    raw = json.loads(result.split("|", 6)[6])
    assert raw["quest_item_target"] == [[56034, 170557, -1, 1, 0]]
    session = result.split("|", 6)[1]
    assembler = PacketAssembler()
    assembler.feed(f'AIPC5|{session}|0|0|1|STATE|{{"monotonic_time":1}}', 1.)
    value = assembler.feed(result, 1.1)
    assert value["quest_item_target"]["guid"] is None
    now = value["quest_item_target"]["sample_time"]
    assert QuestToolResolver.self_ready(QuestToolResolver.self_state(value, 170557, [56034], now=now))
    assert QuestToolResolver.self_state(value, 170557, [56034], now=now+1) is None
    assert not QuestToolResolver.can_interact(value, 170557, "other", [56034], now=now)
