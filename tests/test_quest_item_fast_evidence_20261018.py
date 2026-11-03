"""Actual Lua public-item readers and bounded FAST -> canonical evidence."""
import json

import pytest

from adapters.telemetry_packets import PacketAssembler, normalize
from test_agent_transport import ADDON, lua_runtime
from test_fast_world_position import LIVE_LIKE_FAST
from test_item_use_no_combat_20261004 import BOAR
from wowbot.agent.models import Observation
from wowbot.agent.parallel_view import control_view
from wowbot.agent.world import WorldModel


def packet(seq, kind, value):
    return f"AIPC5|test|{seq}|0|1|{kind}|" + json.dumps(value)


def test_bounded_lua_keeps_item_range_and_interact_recipient_with_movement():
    lua = lua_runtime()
    lua.execute("fast=" + LIVE_LIKE_FAST)
    lua.execute('''fast.interact_guid=fast.target.guid
        fast.soft_targets={{source_unit="softinteract",guid=fast.target.guid,
            name=string.rep("long presentation ",20),npc_id=156626}}
        fast.quest_item_target={guid=fast.target.guid,items={{quest_id=56034,item_id=170557,
            in_range=true,is_usable=true,cooldown_remaining=0}}}''')
    result, _ = lua.eval("ns.NextLanePackets({character_name='Test',monotonic_time=1},fast,850,850)")
    assert result is not None and len(result.encode()) <= 1000
    raw = json.loads(result.split("|", 6)[6])
    assert len(result.split("|", 6)[6].encode()) <= 850
    assert raw["interact_guid"] == raw["target"]["guid"]
    assert raw["quest_item_target"] == [[56034, 170557, 1, 1, 0]]
    assert raw["player_world_position"]["instance_id"] == 2175
    assert raw["mouseover"]["guid"] and raw["cursor_position"]
    assembler = PacketAssembler()
    session = result.split("|", 6)[1]
    assembler.feed(packet(0, "STATE", {"character_name": "Test", "monotonic_time": 1.}).replace(
        "AIPC5|test|", f"AIPC5|{session}|"), 1.)
    parsed = assembler.feed(result, 1.1)
    assert parsed["quest_item_target"]["guid"] == raw["target"]["guid"]
    assert parsed["quest_item_target"]["items"][0]["in_range"] is True
    assert parsed["soft_targets_sample_time"] == raw["monotonic_time"]


@pytest.mark.parametrize("in_range", [-1, 0, 1])
def test_compact_item_bool_preserves_unknown_false_and_true(in_range):
    assembler = PacketAssembler()
    assembler.feed(packet(1, "STATE", {"character_name": "Test", "monotonic_time": 1.}), 1.)
    parsed = assembler.feed(packet(2, "FAST", {"monotonic_time": 2., "target": BOAR,
        "interact_guid": False, "quest_item_target": [[56034, 170557, in_range, -1, -1]]}), 2.)
    item = parsed["quest_item_target"]["items"][0]
    assert item["in_range"] is {-1: None, 0: False, 1: True}[in_range]
    assert item["is_usable"] is None and item["cooldown_remaining"] is None
    assert parsed["quest_item_target"]["sample_time"] == 2.
    assert parsed["soft_targets"] == [] and parsed["soft_targets_sample_time"] == 2.


def test_conflicting_recipient_reads_do_not_authorize_f7():
    parsed = normalize({"monotonic_time": 1., "interact_guid": BOAR["guid"],
                        "soft_targets": [{"source_unit": "softinteract", "guid": "other"}]})
    assert parsed["soft_targets"] == [] and parsed["soft_targets_sample_time"] is None


def test_fast_omission_clears_old_item_proof_in_world_and_parallel_projection():
    proof = {"guid": BOAR["guid"], "sample_time": 1., "items": []}
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "s", "timestamp": 1., "monotonic_time": 1.,
                                    "target": BOAR, "quest_item_target": proof}, 1.))
    delta = {"session_id": "s", "timestamp": 2., "monotonic_time": 2., "transport_kind": "FAST",
             "target": BOAR}
    projected = control_view(world.state, delta, None, 2.)
    assert projected["quest_item_target"] is None
    world.ingest(Observation.create(delta, 2.))
    assert world.state["quest_item_target"] is None


def readers():
    lua = lua_runtime()
    source = (ADDON / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    helpers = source[source.index("local function bool"):source.index("local function unitExists")]
    chunk = source[source.index("local function readInteractGuid"):source.index("local function readNameplates")]
    api = lua.execute(helpers + chunk + "\nreturn {item=readQuestItemTarget,recipient=readInteractGuid}")
    lua.execute('''quests={{quest_id=56034,special_item={item_id=170557}}}
        target={guid="boar"}
        C_Item={IsItemInRange=function(id,token) assert(id==170557 and token=="target"); return true end,
            IsUsableItem=function() return true end,
            GetItemCooldown=function() return 0,0,true end}
        function UnitGUID() return "boar" end''')
    lua.execute("function UnitExists() return false end")
    return lua, api


def test_actual_lua_readers_use_public_item_id_target_and_cooldown():
    lua, api = readers()
    proof = api.item(lua.globals().quests, lua.globals().target, 10.)
    assert proof.guid == "boar" and proof.sample_time == 10.
    assert proof["items"][1].in_range is True and proof["items"][1].is_usable is True
    assert proof["items"][1].cooldown_remaining == 0
    assert api.recipient() == "boar"
    lua.execute("C_Item.GetItemCooldown=function() return 9,5,true end")
    assert api.item(lua.globals().quests, lua.globals().target, 10.)["items"][1].cooldown_remaining == 4


@pytest.mark.parametrize("replacement", ["return nil", "error('restricted')", "return {secret=true}"])
def test_unavailable_or_secret_item_range_and_recipient_remain_unknown(replacement):
    lua, api = readers()
    lua.execute("C_Item.IsItemInRange=function() " + replacement + " end")
    assert api.item(lua.globals().quests, lua.globals().target, 10.)["items"][1].in_range is None
    lua.execute("function UnitGUID() " + replacement + " end")
    recipient = api.recipient()
    assert recipient is (False if replacement == "return nil" else None)


def test_present_soft_unit_without_public_guid_is_unknown_not_empty():
    lua, api = readers()
    lua.execute("function UnitGUID() return nil end; function UnitExists() return true end")
    assert api.recipient() is None


@pytest.mark.parametrize("count", [1, 4])
@pytest.mark.parametrize("combat", [False, True])
def test_item_proof_still_fits_bounded_packet_without_losing_survival(count, combat):
    lua = lua_runtime()
    lua.execute("fast=" + LIVE_LIKE_FAST)
    lua.execute('''fast.interact_guid=fast.target.guid;fast.bags_open=false
        fast.quest_item_target={guid=fast.target.guid,items={}}
        fast.health=80;fast.max_health=100;fast.is_dead=false;fast.is_ghost=false''')
    lua.globals().fast.is_in_combat = combat
    lua.execute(f'''for i=1,{count} do fast.quest_item_target.items[i]={{quest_id=56033+i,
        item_id=170556+i,in_range=true,is_usable=true,cooldown_remaining=0}} end''')
    encoded, _ = lua.eval("ns.NextLanePackets({monotonic_time=1},fast,850,850)")
    assert encoded is not None
    body = json.loads(encoded.split("|", 6)[6])
    assert len(encoded.split("|", 6)[6].encode()) <= 850
    assert body["interact_guid"] == body["target"]["guid"]
    assert body["quest_item_target"][0][1] == 170557
    assert body["is_dead"] is False and body["is_ghost"] is False
    assert body["is_in_combat"] is combat
    assert body["bags_open"] is False and body["player_world_position"]
    if combat:
        assert body["health"] == 80 and body["max_health"] == 100
        assert body["actionbar_fast"]
