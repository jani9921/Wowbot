import json
from pathlib import Path
import pytest
from adapters.telemetry_packets import PacketAssembler, normalize


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addon" / "AIPlayerControllerExport"


def test_legacy_c_map_position_cannot_make_unitposition_zero_z_authoritative():
    state = normalize({
        "player_world_position": {
            "source": "C_MAP_PLAYER_WORLD_POS", "x": 209.7, "y": -2268.7,
            "z": 0, "z_known": True, "z_source": "UNIT_POSITION"},
    })

    position = state["player_world_position"]
    assert position["z_known"] is False
    assert position["z_observed"] is False
    assert position["z_source"] == "LEGACY_UNIT_POSITION_Z_REJECTED"


@pytest.mark.parametrize("is_open", [False, True])
def test_fast_map_context_is_projected_to_canonical_top_level_state(is_open):
    state = normalize({
        # Deliberately contradictory stale full-state value: the compact
        # map_context sample is the current control-lane ground truth.
        "world_map_open": not is_open,
        "map_context": {"world_map_open": is_open},
    })

    assert state["world_map_open"] is is_open


def test_newer_fast_map_context_overrides_previous_full_map_visibility():
    assembler = PacketAssembler()
    full = {
        "monotonic_time": 1, "character_name": "Test",
        "world_map_open": True, "map_context": {"world_map_open": True},
    }
    fast = {
        "monotonic_time": 2,
        "map_context": {"world_map_open": False},
    }

    first = assembler.feed(
        "AIPC5|session|1|0|1|STATE|" + json.dumps(full), now=1.)
    closed = assembler.feed(
        "AIPC5|session|2|0|1|FAST|" + json.dumps(fast), now=1.1)

    assert first["world_map_open"] is True
    assert closed["world_map_open"] is False
    assert closed["map_context"]["world_map_open"] is False


def lua_runtime():
    lupa = pytest.importorskip("lupa")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
        now = 1
        function GetTime() return now end
        function GetServerTime() return 1000+math.floor(now) end
        function issecretvalue(v) return type(v)=="table" and rawget(v,"secret")==true end
        function canaccessvalue(v) return not issecretvalue(v) end
        ns = {}
    ''')
    lua.execute((ADDON / "Transport.lua").read_text(encoding="utf-8"), "AIPlayerControllerExport", lua.globals().ns)
    return lua


def test_lua_json_secret_unicode_booleans_and_pipe():
    lua = lua_runtime()
    raw = lua.eval('ns.EncodeJSON({text="Árvíztűrő|\\n\\\"", no=false, yes=true, hidden={secret=true}})')
    assert json.loads(raw) == {"text": 'Árvíztűrő|\n"', "no": False, "yes": True, "hidden": None}


def test_actual_lua_packets_reassemble_unicode_and_do_not_truncate():
    lua = lua_runtime()
    lua.execute('data={monotonic_time=1,timestamp=1001,character_guid="Player-1",character_name="Árvíztűrő",player_present=true,active_quests={{quest_id=1,objectives={{description=string.rep("ő|",1200),current=1}}}},actionbar={},events={},inventory={items={}}}')
    assembler = PacketAssembler()
    state = None
    for i in range(60):
        packet = lua.eval("ns.NextPacket(data)")
        assert len(packet.encode("utf-8")) <= 1000
        result = assembler.feed(packet, i*.05)
        if result:
            state = result
    assert state["active_quests"][0]["objectives"][0]["description"] == "ő|"*1200
    assert state["actionbar"] == [] and state["inventory"]["items"] == []
    # Frozen snapshot is repeated for recovery, but its sequence cannot keep it fresh.
    assert assembler.last_full == 1 and assembler.last_fast == 1


def test_fast_packet_carries_motion_feedback_for_closed_loop_steering():
    lua = lua_runtime()
    lua.execute('data={monotonic_time=1,timestamp=1001,character_name="Test",position={x=.5,y=.5},orientation=0,movement={speed=7,moving=true,falling=false,swimming=false}}')
    packet = lua.eval("ns.NextPacket(data)")
    assert "|FAST|" in packet
    body = json.loads(packet.split("|", 6)[6])
    assert body["movement"] == {"speed": 7, "moving": True,
                                  "falling": False, "swimming": False}


def test_fast_packet_carries_compact_world_map_context() -> None:
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=1,timestamp=1001,map_id=2175,
        map_context={player_map_id=2175,displayed_map_id=1409,
            active_map_id=1409,parent_map_id=13,map_name="Exile's Reach",
            parent_map_name="Eastern Kingdoms",world_map_open=true}}''')
    body = json.loads(lua.eval("ns.NextPacket(data)").split("|", 6)[6])
    assert body["map_context"]["active_map_id"] == 1409
    assert body["map_context"]["parent_map_id"] == 13
    assert body["map_context"]["world_map_open"] is True


def test_transport_multiplexes_three_fresh_fast_samples_per_state_page():
    """0.9.58: one STATE page per four packets (was six), see Transport.lua."""
    lua = lua_runtime()
    lua.execute('''state={monotonic_time=1,timestamp=1001,character_name="Test"}
                   fast={monotonic_time=2,timestamp=1002,orientation=1.25,
                         movement={speed=7,moving=true}}''')
    packets = [lua.eval("ns.NextPacket(state, fast)") for _ in range(32)]
    assert sum("|FAST|" in packet for packet in packets) == 24
    assert sum("|STATE|" in packet or "|STATE_Z|" in packet for packet in packets) == 8
    fast_body = json.loads(packets[0].split("|", 6)[6])
    assert fast_body["telemetry_lane"] == "FAST_STATE"
    assert fast_body["fast_sample_time"] == 2
    assert fast_body["orientation"] == 1.25


def test_oversized_inspection_data_cannot_starve_fast_control_lane():
    lua = lua_runtime()
    lua.execute('''state={monotonic_time=1,timestamp=1001,character_name="Test"}
                   fast={monotonic_time=2,timestamp=1002,orientation=.5,
                         movement={speed=7,moving=true},
                         mouseover={guid=string.rep("g",900),name=string.rep("n",900)},
                         map_mouseover={tooltip=string.rep("tooltip",400)}}''')
    packet = lua.eval("ns.NextPacket(state, fast)")
    assert "|FAST|" in packet
    assert len(packet.encode("utf-8")) <= 1000
    body = json.loads(packet.split("|", 6)[6])
    assert body["movement"]["moving"] is True
    assert body["telemetry_lane"] == "FAST_STATE"


def test_fast_packet_carries_same_space_player_and_target_world_positions():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=1,timestamp=1001,character_name="Test",
        player_world_position={x=100,y=200,z=3,instance_id=2175,
            source="UNIT_POSITION",coordinate_space="WORLD_YARDS"},
        target={guid="Creature-1",world_position={x=112,y=203,z=3,instance_id=2175,
            source="UNIT_POSITION",coordinate_space="WORLD_YARDS"}}}''')
    body = json.loads(lua.eval("ns.NextPacket(data)").split("|", 6)[6])
    assert body["player_world_position"]["coordinate_space"] == "WORLD_YARDS"
    assert body["target"]["guid"] == "Creature-1"
    assert body["target"]["world_position"]["x"] == 112
    assert body["target"]["world_position"]["instance_id"] == 2175


def test_fast_packet_carries_current_inspection_ground_truth():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=2,timestamp=1002,character_name="Test",
        mouseover={guid="Creature-1",name="Lady Jaina Proudmoore",npc_id=166824,
            unit_type="NPC",is_attackable=false,is_dead=false},
        cursor_position={nx=.4914,ny=.6164},map_mouseover=false}''')
    packet = lua.eval("ns.NextPacket(data)")
    assert "|FAST|" in packet
    assert len(packet.encode("utf-8")) <= 1000
    body = json.loads(packet.split("|", 6)[6])
    assert body["mouseover"]["guid"] == "Creature-1"
    assert body["cursor_position"] == {"nx": .4914, "ny": .6164}
    assert body["mouseover_sample_time"] == 2


def test_fast_packet_carries_open_quest_dialog_action_and_click_point():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=2,timestamp=1002,character_name="Test",
        quest_ui={open=true,action="ACCEPT",x=.0346,y=.4475,quest_id=55122}}''')
    body = json.loads(lua.eval("ns.NextPacket(data)").split("|", 6)[6])
    assert body["quest_ui"] == {
        "open": True, "action": "ACCEPT", "x": .0346, "y": .4475, "quest_id": 55122}


def test_fast_packet_carries_exact_extra_action_identity_without_guessing_a_key():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=2,timestamp=1002,character_name="Test",
        extra_action={visible=true,usable=true,action="EXTRAACTIONBUTTON1",
            action_type="item",action_id=12345,binding_primary="F"}}''')
    body = json.loads(lua.eval("ns.NextPacket(data)").split("|", 6)[6])
    assert body["extra_action"] == {"visible": True, "usable": True,
                                    "action": "EXTRAACTIONBUTTON1",
                                    "action_type": "item", "action_id": 12345}


def test_long_fast_payload_preserves_open_quest_dialog_control_state():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=2,timestamp=1002,character_name="Test",
        player_world_position={x=1,y=2,z=3,instance_id=2175,coordinate_space="WORLD_YARDS"},
        mouseover={guid="Creature-1",name=string.rep("n",700)},
        cursor_position={nx=.5,ny=.5},
        quest_ui={open=true,action="ACCEPT",x=.0346,y=.4475,quest_id=55122}}''')
    body = json.loads(lua.eval("ns.NextPacket(data)").split("|", 6)[6])
    assert body["quest_ui"]["open"] is True
    assert body["quest_ui"]["action"] == "ACCEPT"


def test_long_npcodex_tooltip_never_evicts_mouseover_guid_from_fast_lane():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=2,timestamp=1002,character_name="Test",
        player_world_position={x=-451.4,y=-2614.2,z=0,instance_id=2175,
            source="UNIT_POSITION",coordinate_space="WORLD_YARDS"},
        movement={speed=0,moving=false,falling=false,swimming=false},
        target=false,
        mouseover={guid="Creature-0-4234-2175-9499-156626-000021EEC5",
            name="Lady Jaina Proudmoore",npc_id=156626,unit_type="NPC",
            is_attackable=false,is_dead=false,identity_source="WOW_API_MOUSEOVER",
            tooltip=string.rep("NPCodex descriptive tooltip ",120),
            tooltip_data={raw_type=2,is_unit=true,
                unit_name="Lady Jaina Proudmoore",
                unit_guid="Creature-0-4234-2175-9499-156626-000021EEC5"}},
        cursor_position={nx=.5068306,ny=.5962099},map_mouseover=false,
        quest_digest={{id=55122,complete=false,done=0,need=6}}}''')
    packet = lua.eval("ns.NextPacket(data)")
    assert "|FAST|" in packet
    assert len(packet.encode("utf-8")) <= 1000
    body = json.loads(packet.split("|", 6)[6])
    assert body["mouseover"]["guid"].endswith("156626-000021EEC5")
    assert body["mouseover"]["name"] == "Lady Jaina Proudmoore"
    assert body["cursor_position"] == {"nx": .5068306, "ny": .5962099}


def test_field_rich_fast_packet_never_evicts_inspection_identity_and_cursor():
    """Regression for the 2026-09-11 live Jaina hover.

    The visually correct hover was present on screen, but the field-rich FAST
    sample crossed the 850-byte body limit and the old final fallback removed
    mouseover and cursor together.  INSPECT then timed out while a later full
    STATE eventually supplied the GUID.
    """
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=152714.048,timestamp=1789100286,
        map_id=1409,position={x=.42,y=.51},
        player_world_position={x=-451.4,y=-2614.2,z=0,instance_id=2175,
            source="UNIT_POSITION",coordinate_space="WORLD_YARDS"},
        orientation=5.91,health=100,max_health=100,is_dead=false,is_ghost=false,
        is_in_combat=false,is_mounted=false,is_casting=false,player_present=true,
        movement={speed=0,moving=false,falling=false,swimming=false},
        target={guid="Creature-0-3109-2175-145635-156626-000022EF4C",
            name="Lady Jaina Proudmoore",npc_id=156626,health=100,max_health=100,
            attackable=false,dead=false,
            world_position={x=-445,y=-2610,z=0,instance_id=2175,
                source="UNIT_POSITION",coordinate_space="WORLD_YARDS"}},
        mouseover={guid="Creature-0-3109-2175-145635-156626-000022EF4C",
            name="Lady Jaina Proudmoore",npc_id=156626,unit_type="NPC",
            structured_unit=true,is_attackable=false,is_dead=false,
            quest_role="QUEST_GIVER",quest_role_source="QUEST_GREETING_API",
            identity_source="WOW_API_MOUSEOVER",
            tooltip="Lady Jaina Proudmoore ~ Level 10",
            tooltip_data={raw_type=2,is_unit=true,unit_name="Lady Jaina Proudmoore",
                unit_guid="Creature-0-3109-2175-145635-156626-000022EF4C"}},
        cursor_position={nx=.5787796,ny=.5874636,x=1002.0,y=635.0},
        map_mouseover=false,
        quest_ui={open=false,action=false,x=0,y=0,quest_id=false},
        quest_digest={{id=55122,complete=false,done=0,need=6}},
        quest_state_revision=string.rep("r",180),
        ui_error=string.rep("ordinary but verbose runtime state ",10)}''')
    packet = lua.eval("ns.NextPacket(data)")
    assert "|FAST|" in packet
    body = json.loads(packet.split("|", 6)[6])
    assert len(packet.split("|", 6)[6].encode("utf-8")) <= 850
    assert body["mouseover"]["guid"].endswith("156626-000022EF4C")
    assert body["mouseover"]["name"] == "Lady Jaina Proudmoore"
    assert body["cursor_position"] == {"nx": .5787796, "ny": .5874636}
    assert body["movement"]["moving"] is False


def test_field_rich_combat_fast_packet_preserves_survival_and_rotation_facts():
    """A hostile identity must not evict combat/actionbar control telemetry."""
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=663820.446,timestamp=1790590610,
        map_id=1409,orientation=2.44,health=210,max_health=380,
        is_dead=false,is_ghost=false,is_in_combat=true,is_casting=false,
        player_present=true,input_blocked=false,loading=false,
        movement={speed=0,moving=false,falling=false,swimming=false},
        target={guid="Creature-0-4245-2175-18655-151091-00003A3DF9",
            name="Geolord Grek'og",npc_id=151091,health=700,max_health=900,
            attackable=true,dead=false,
            world_position={x=19.9,y=-2512,z=0,instance_id=2175,
                source="UNIT_POSITION",coordinate_space="WORLD_YARDS"}},
        mouseover={guid="Creature-0-4245-2175-18655-151091-00003A3DF9",
            name="Geolord Grek'og",npc_id=151091,unit_type="NPC",
            structured_unit=true,is_attackable=true,is_dead=false,
            quest_related=true,quest_id=55186,
            identity_source="WOW_API_MOUSEOVER",
            tooltip=string.rep("field rich hostile tooltip ",100)},
        cursor_position={nx=.47,ny=.53},
        quest_digest={{id=55186,complete=false,done=0,need=1}},
        quest_state_revision=string.rep("r",180),
        ui_error=string.rep("verbose retained client error ",20),
        actionbar_fast={{100,true,false,0},{1464,false,true,0},
            {23922,true,true,0},{1715,false,true,0}}}''')
    packet = lua.eval("ns.NextPacket(data)")
    assert "|FAST|" in packet
    body = json.loads(packet.split("|", 6)[6])
    assert len(packet.split("|", 6)[6].encode("utf-8")) <= 850
    assert body["is_in_combat"] is True
    assert body["is_dead"] is False
    assert body["health"] == 210
    assert body["target"]["guid"].endswith("151091-00003A3DF9")
    assert body["target"]["attackable"] is True
    assert body["actionbar_fast"][2] == [23922, True, True, 0]


def test_fast_packet_preserves_structured_world_tooltip_identity_fallback():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=2,timestamp=1002,character_name="Test",
        mouseover={guid="Creature-0-1-2-3-156626-4",npc_id=156626,unit_type="NPC",
            identity_source="TOOLTIP_PRIMARY_DATA",tooltip="Lady Jaina Proudmoore",
            tooltip_data={raw_type=2,guid="Creature-0-1-2-3-156626-4",
                unit_guid="Creature-0-1-2-3-156626-4"}},
        cursor_position={nx=.4558,ny=.6326},map_mouseover=false}''')
    body = json.loads(lua.eval("ns.NextPacket(data)").split("|", 6)[6])
    assert body["mouseover"]["identity_source"] == "TOOLTIP_PRIMARY_DATA"
    assert body["mouseover"]["tooltip_text"] == "Lady Jaina Proudmoore"
    assert body["mouseover"]["tooltip_data"]["unit_guid"].endswith("156626-4")


def test_compact_fast_packet_preserves_quest_related_mouseover_handoff():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=2,timestamp=1002,
        mouseover={guid="Creature-0-1-2-3-161133-4",npc_id=161133,
            name="Coastal Albatross",unit_type="NPC",is_attackable=true,
            quest_related=true,quest_id=55174,tooltip=string.rep("verbose tooltip ",100)},
        cursor_position={nx=.77,ny=.61},ui_error=string.rep("verbose state ",100),
        actionbar_fast={{id=100,is_usable=true,is_harmful=true,cooldown_remaining=0}}}''')
    body = json.loads(lua.eval("ns.NextPacket(data)").split("|", 6)[6])
    assert body["mouseover"]["guid"].endswith("161133-4")
    assert body["mouseover"]["quest_related"] is True
    assert body["mouseover"]["quest_id"] == 55174
    assert body["cursor_position"] == {"nx": .77, "ny": .61}


def test_field_rich_fast_packet_keeps_structured_quest_object_name_with_cursor():
    """Live 19:47: a cocoon change event arrived ~12 s after the hover.
    Its short structured name must travel with the FAST cursor instead."""
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=701592.234,timestamp=1791308841,
        map_id=1409,orientation=5.9,player_present=true,
        player_world_position={x=81.47,y=-2277.03,instance_id=2175},
        movement={speed=0,moving=false,indoors=true},
        map_context={active_map_id=1409,parent_map_id=2175,
            map_name=string.rep("Long cave name ",30)},
        mouseover={quest_related=true,quest_id=55639,
            tooltip=string.rep("Thick Cocoon ~ Who Lurks in the Pit ",30),
            tooltip_data={raw_type=21,guid="",unit_guid="",object_id=0,
                unit_name="Thick Cocoon"}},
        cursor_position={nx=.57909,ny=.51900},
        quest_digest={{id=55639,complete=false,done=0,need=5}},
        quest_state_revision=string.rep("revision",70),
        actionbar_fast={{100,true,false,0},{1464,false,true,0}}}''')
    packet = lua.eval("ns.NextPacket(data)")
    assert "|FAST|" in packet
    body = json.loads(packet.split("|", 6)[6])
    assert len(packet.split("|", 6)[6].encode("utf-8")) <= 850
    assert body["mouseover"]["name"] == "Thick Cocoon"
    assert body["mouseover"]["quest_id"] == 55639
    assert body["cursor_position"] == {"nx": .57909, "ny": .519}
    assert body["player_world_position"]["x"] == 81.47


def test_fast_packet_preserves_structured_unit_name_when_guid_is_unavailable():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=2,timestamp=1002,character_name="Test",
        mouseover={name="Lady Jaina Proudmoore",unit_type="UNIT",structured_unit=true,
            identity_source="TOOLTIP_PRIMARY_DATA",tooltip="Lady Jaina Proudmoore ~ Level 10",
            tooltip_data={raw_type=2,is_unit=true,unit_name="Lady Jaina Proudmoore"}},
        cursor_position={nx=.58,ny=.60},map_mouseover=false}''')
    body = json.loads(lua.eval("ns.NextPacket(data)").split("|", 6)[6])
    assert "guid" not in body["mouseover"]
    assert body["mouseover"]["structured_unit"] is True
    assert body["mouseover"]["tooltip_data"]["is_unit"] is True
    assert body["mouseover"]["tooltip_data"]["unit_name"] == "Lady Jaina Proudmoore"


def test_fast_inspection_state_overlays_slow_full_snapshot():
    assembler = PacketAssembler()
    assert assembler.feed('AIPC5|s|1|0|1|STATE|{"monotonic_time":1,"character_guid":"Player-1","active_quests":[{"quest_id":1}],"mouseover":false,"cursor_position":{"nx":0.1,"ny":0.1}}', 1)
    result = assembler.feed('AIPC5|s|2|0|1|FAST|{"monotonic_time":2,"mouseover":{"guid":"Creature-1","name":"Jaina"},"mouseover_sample_time":2,"cursor_position":{"nx":0.49,"ny":0.62},"cursor_sample_time":2}', 2)
    assert result["mouseover"]["guid"] == "Creature-1"
    assert result["cursor_position"] == {"nx": .49, "ny": .62}
    assert result["character_guid"] == "Player-1"
    assert "active_quests" not in result  # bounded delta; WorldModel owns merge


def test_fast_quest_digest_exposes_acceptance_without_copying_full_snapshot():
    assembler = PacketAssembler()
    assembler.feed(
        'AIPC5|s|1|0|1|STATE|{"monotonic_time":1,"character_guid":"Player-1",'
        '"active_quests":[]}', 1)
    result = assembler.feed(
        'AIPC5|s|2|0|1|FAST|{"monotonic_time":2,"quest_state_revision":"rev2",'
        '"quest_digest":[{"id":56775,"complete":false,"done":0,"need":1}]}', 2)
    assert result["accepted_quest_ids"] == [56775]
    assert result["active_quests"][0]["quest_id"] == 56775
    assert result["active_quests"][0]["source"] == "FAST_QUEST_DIGEST"


def test_compact_fast_preserves_target_state_and_explicit_missing_position():
    lua = lua_runtime()
    lua.execute('''data={monotonic_time=2,timestamp=1002,
        player_world_position={x=-446.9,y=-2612.7,coordinate_space="WORLD_YARDS"},
        target={guid="Creature-Jaina",name="Lady Jaina Proudmoore",npc_id=156626,
            attackable=false,dead=false,screen_position={padding=string.rep("x",900)}}}''')
    packet = lua.eval("ns.NextPacket(data)")
    assert "|FAST|" in packet
    body = json.loads(packet.split("|", 6)[6])
    assert body["target"]["name"] == "Lady Jaina Proudmoore"
    assert body["target"]["attackable"] is False
    assert body["target"]["dead"] is False
    assert body["target"]["world_position"] is False
    assert body["target_sample_time"] == 2
    assembler = PacketAssembler()
    session = packet.split("|")[1]
    assembler.feed(f'AIPC5|{session}|0|0|1|STATE|{{"monotonic_time":1,"target":false}}', 1)
    result = assembler.feed(packet, 2)
    assert result["target_is_attackable"] is False
    assert result["current_target"] == "Lady Jaina Proudmoore"


def test_dropped_page_recovered_from_second_round():
    lua = lua_runtime()
    lua.execute('data={monotonic_time=1,timestamp=1001,character_name="Test",text=string.rep("abc",800)}')
    assembler = PacketAssembler()
    dropped = False
    result = None
    for i in range(35):
        packet = lua.eval("ns.NextPacket(data)")
        if "|1|1|" in packet and "|STATE|" in packet and not dropped:
            dropped = True
            continue
        result = assembler.feed(packet, i*.05) or result
    assert dropped and result["text"] == "abc"*800


def test_incomplete_snapshot_never_publishes():
    assembler = PacketAssembler()
    assert assembler.feed('AIPC5|s|1|0|2|STATE|{"position":', 1) is None
    assert assembler.feed('AIPC5|s|1|0|1|FAST|{"timestamp":1}', 2) is None
    assert assembler.full is None


def test_conflicting_pages_fail_and_session_resets():
    assembler = PacketAssembler()
    assembler.feed('AIPC5|s|1|0|2|STATE|{"a":', 1)
    with pytest.raises(ValueError): assembler.feed('AIPC5|s|1|0|2|STATE|{"b":', 1.1)
    result = assembler.feed('AIPC5|s|2|0|1|STATE|{"timestamp":1,"character_guid":"one"}', 2)
    assert result["session_id"] == "s:one"
    assert assembler.feed('AIPC5|new|1|0|1|FAST|{"timestamp":3}', 3) is None
    assert assembler.full is None


def test_fast_updates_target_without_carrying_old_identity():
    assembler = PacketAssembler()
    assembler.feed('AIPC5|s|1|0|1|STATE|{"monotonic_time":1,"target":{"guid":"old"}}', 1)
    result = assembler.feed('AIPC5|s|1|0|1|FAST|{"monotonic_time":2,"target":false}', 2)
    assert result["target"] is False and result["current_target"] is None
    assert result["state_age"] >= 1


@pytest.mark.parametrize("packet", ['AIPC5|s|-1|0|1|FAST|{}', 'AIPC5|s|1|0|200|STATE|{}',
                                     'AIPC5|s|1|3|1|STATE|{}', 'AIPC5|s|1|0|1|AI|{}'])
def test_invalid_packet_bounds(packet):
    with pytest.raises(ValueError): PacketAssembler().feed(packet)


_MOCK_WOW_API = '''
        frames={}; tickers={}; SlashCmdList={}
        function CreateFrame(_,name)
            local f={shown=false}
            function f:SetScript(event,callback) self[event]=callback end
            function f:RegisterEvent() end
            function f:Show() self.shown=true end
            function f:Hide() self.shown=false end
            function f:IsShown() return self.shown end
            function f:IsVisible() return self.shown end
            function f:GetEffectiveScale() return 1 end
            function f:CreateFontString() return CreateFrame() end
            function f:CreateTexture() return CreateFrame() end
            function f:SetText(text) self.textValue=text end
            setmetatable(f,{__index=function(_,k) if k:match("^Set") then return function() end end end})
            frames[#frames+1]=f
            if name then _G[name]=f end
            return f
        end
        UIParent=CreateFrame()
        C_Timer={NewTicker=function(interval,callback)
            local t={interval=interval,callback=callback,Cancel=function() end}
            tickers[#tickers+1]=t; return t
        end}
        function UnitExists(unit) return unit=="player" or unit=="target" end
        function UnitGUID(unit) return unit=="player" and "Player-1" or "Creature-0-0-0-0-42-0000000001" end
        function UnitName(unit) return unit=="player" and "Test" or "Boar" end
        function UnitIsPlayer(unit) return unit=="player" end
        function UnitCanAttack() return {secret=true} end
        function UnitHealth() return 100 end
        function UnitHealthMax() return 100 end
        function UnitPosition(unit)
            if unit=="player" then return 100,200,3,2175 end
            return 112,203,3,2175
        end
        function UnitIsDead() return false end
        function UnitIsGhost() return false end
        function GetBuildInfo() return "12.1.0","12345" end
        function GetPlayerFacing() return 0 end
        function GetCursorPosition() return 100,100 end
        function GetScreenWidth() return 1920 end
        function GetScreenHeight() return 1080 end
        function GetZoneText() return "Exile's Reach" end
        function GetSubZoneText() return "Beach" end
        function debugstack() return "mock stack" end
        C_Map={GetBestMapForUnit=function() return 1609 end,GetPlayerMapPosition=function() return {x=.5,y=.5} end}
        function GetActionInfo(slot) if slot==1 then return "spell",123 end end
        function GetBindingKey() return "1" end
        C_Spell={GetSpellName=function() return "Attack" end,IsSpellHarmful=function() return true end}
        C_ActionBar={IsUsableAction=function() return true,false end,GetActionCooldown=function() return {startTime=0,duration=0} end,
                     IsActionInRange=function() return true end}
        C_QuestLog={GetNumQuestLogEntries=function() return 1 end,
                    GetInfo=function() return {questID=42,title="Boars"} end,
                    GetQuestObjectives=function() return {{text="Re-Sizer v9.0.1 tested on Wandering Boars",type="monster",numFulfilled=0,numRequired=3}} end,
                    ReadyForTurnIn=function() return false end}
        function GetQuestLogSpecialItemInfo() return "|Hitem:170557::::::::|h[Re-Sizer v9.0.1]|h" end
        C_Container={GetContainerNumSlots=function(bag) return bag==0 and 1 or 0 end,
                     GetContainerNumFreeSlots=function() return 0 end,
                     GetContainerItemInfo=function() return {itemID=1,stackCount=1} end}
        function GetItemInfo() return "Item",nil,1,2,nil,"Trade",nil,200,nil,nil,12 end
    '''


def _load_main_addon(extra=""):
    lua = lua_runtime()
    lua.execute(_MOCK_WOW_API)
    if extra:
        lua.execute(extra)
    lua.execute((ADDON / "Bindings.lua").read_text(encoding="utf-8"), "AIPlayerControllerExport", lua.globals().ns)
    lua.execute((ADDON / "AIPlayerControllerExport.lua").read_text(encoding="utf-8"), "AIPlayerControllerExport", lua.globals().ns)
    lua.execute('frames[2].OnEvent(frames[2],"PLAYER_LOGIN")')
    return lua


def test_main_addon_loads_and_exports_under_mocked_wow_api():
    lua = _load_main_addon()
    # TRANSPORT_INTERVAL raised 2026-09-14 from 0.025 (40 Hz) to 1/60 (60 Hz)
    # to match the DXGI capture backend's live-measured refresh-rate ceiling.
    assert lua.eval("tickers[2].interval") == pytest.approx(1 / 60)
    result = json.loads(lua.eval("ns.EncodeJSON(AIPlayerControllerExportDB.latest)"))
    assert result["game_version"] == "12.1.0"
    assert result["protocol_version"] == "AIPC5"
    assert "attackable" not in result["target"]  # secret is UNKNOWN, never friendly false.
    assert result["actionbar"][0]["is_harmful"] is True
    assert result["inventory"]["items"][0]["max_stack"] == 200
    assert result["inventory"]["items"][0]["sell_price"] == 12
    assert result["active_quests"][0]["objectives"][0]["raw_type"] == "monster"
    assert result["active_quests"][0]["objectives"][0]["type"] == "USE_ITEM"
    assert result["active_quests"][0]["objectives"][0]["item_id"] == 170557
    assert result["active_quests"][0]["objectives"][0]["type_source"] == "QUEST_SPECIAL_ITEM_NAME_MATCH"
    assert result["player_world_position"]["coordinate_space"] == "WORLD_YARDS"
    assert result["player_world_position"]["instance_id"] == 2175
    assert result["target"]["world_position"]["x"] == 112
    assert result["events"][0]["event_type"] == "ADDON_READY"
    # A delayed callback is still executable without a live client.
    lua.execute('now=2; tickers[1].callback(); tickers[2].callback()')
    assert lua.eval("AIPlayerControllerExportDB.latest.monotonic_time") == 2
    assert lua.eval("AIPlayerControllerExportDB.latest.movement.moving") is False
    # PREPARED 2026-09-14, UNTESTED LIVE: combatHint's update path
    # (UNIT_SPELLCAST_SUCCEEDED) and its read path (readFastCombatHint,
    # exercised inside tickers[2].callback() via readFastState) both run
    # under real Lua execution without error. This does not confirm the
    # resulting fast payload's *content* reaches the pixel strip correctly
    # (readFastState's result is local to the ticker closure, not exported
    # for inspection here) -- see docs/LIVE_VALIDATION.md for what a live
    # test still needs to confirm.
    lua.execute('frames[2].OnEvent(frames[2],"UNIT_SPELLCAST_SUCCEEDED","player","cast-1",123)')
    lua.execute('now=3; tickers[1].callback(); tickers[2].callback()')
    lua.execute('frames[2].OnEvent(frames[2],"QUEST_ACCEPTED",42)')
    assert lua.eval("AIPlayerControllerExportDB.latest_event.payload.quest_id") == 42


def test_main_addon_exports_map_pois_from_map_apis():
    """User 2026-10-01: quest givers ("!"), dungeon/raid entrances, flight
    points and area POIs come from the map APIs with world positions."""
    lua = _load_main_addon('''
        function CreateVector2D(x,y) return {x=x,y=y} end
        C_Map.GetMapInfo=function(id)
            if id==1609 then return {mapID=1609,mapType=5,parentMapID=1409} end
            return {mapID=id,mapType=3,parentMapID=13}
        end
        C_Map.GetWorldPosFromMapPos=function(id,pos) return 2175,{x=1000*pos.x+id,y=2000*pos.y} end
        requested={}
        C_QuestLine={RequestQuestLinesForMap=function(id) requested[#requested+1]=id end,
            GetAvailableQuestLines=function(id)
                if id~=1409 then return {} end
                return {{questID=55122,questName="Murloc Mania",questLineID=7,x=.25,y=.5,isCampaign=true},
                        {questID=55122,questName="dup",x=.3,y=.3},
                        {questID=9,questName="hidden",x=.1,y=.1,isHidden=true},
                        {questID=10,questName="secret",x={secret=true},y=.1}}
            end}
        C_EncounterJournal={GetDungeonEntrancesForMap=function(id)
            if id~=1409 then return {} end
            return {{name="Darkmaul Citadel",atlasName="Dungeon",journalInstanceID=1234,areaPoiID=5,
                     position={GetXY=function() return .75,.25 end}}}
        end}
        C_TaxiMap={GetTaxiNodesForMap=function(id)
            return {{nodeID=99,name="Camp",atlasName="TaxiNode_Alliance",position={x=.5,y=.5}}}
        end}
        C_AreaPoiInfo={GetAreaPOIsForMap=function() return {77} end,
            GetAreaPOIInfo=function(id,poi) return {areaPoiID=poi,name="Cave",atlasName="CaveUnderground",position={x=.4,y=.6}} end}
    ''')
    pois = json.loads(lua.eval("ns.EncodeJSON(AIPlayerControllerExportDB.latest)"))["map_pois"]
    assert [q["quest_id"] for q in pois["available_quests"]] == [55122]
    quest = pois["available_quests"][0]
    assert quest["quest_name"] == "Murloc Mania" and quest["map_id"] == 1409
    assert quest["is_campaign"] is True and quest["source"] == "QUESTLINE_API"
    assert quest["world_position"] == pytest.approx(
        {"x": 1000 * .25 + 1409, "y": 1000., "instance_id": 2175, "ui_map_id": 1409,
         "coordinate_space": "WORLD_YARDS", "source": "C_MAP_WORLD_POS", "z_known": False})
    entrance = pois["dungeon_entrances"][0]
    assert entrance["name"] == "Darkmaul Citadel" and entrance["journal_instance_id"] == 1234
    assert (entrance["x"], entrance["y"]) == (.75, .25)
    # The micro map and its zone parent both report the same flight point.
    assert [n["node_id"] for n in pois["taxi_nodes"]] == [99]
    assert pois["area_pois"][0]["atlas_name"] == "CaveUnderground"
    assert sorted([lua.eval("requested[1]"), lua.eval("requested[2]")]) == [1409, 1609]
    # Cached for 5 s: no second quest-line request within the window.
    lua.execute('now=2; tickers[1].callback()')
    assert lua.eval("#requested") == 2


def test_malformed_array_shape_is_rejected():
    with pytest.raises(ValueError):
        PacketAssembler().feed('AIPC5|s|1|0|1|STATE|{"active_quests":"not-an-array"}', 1)


def test_compressed_lua_transport_preserves_full_snapshot():
    import base64
    import zlib
    lua = lua_runtime()
    lua.globals().mock_base64 = lambda text: base64.b64encode(zlib.compress(text.encode())).decode()
    lua.execute('''
        Enum={CompressionMethod={Zlib=1}}
        C_EncodingUtil={CompressString=function(text,method) assert(method==1); return text end,
                        EncodeBase64=function(text) return mock_base64(text) end}
        data={monotonic_time=1,timestamp=1001,character_name="Test",text=string.rep("árvíztűrő",1000)}
    ''')
    assembler = PacketAssembler()
    result = None
    for i in range(20):
        result = assembler.feed(lua.eval("ns.NextPacket(data)"), i*.05) or result
    assert result["text"] == "árvíztűrő"*1000
    assert result["state_encoding"] == "STATE_Z"


def test_compressed_bomb_and_trailing_data_rejected():
    import base64
    import zlib
    for data in (zlib.compress(b"a"*128001), zlib.compress(b"{}")+b"trailing"):
        packet = 'AIPC5|s|1|0|1|STATE_Z|'+base64.b64encode(data).decode()
        with pytest.raises(ValueError):
            PacketAssembler().feed(packet, 1)



def test_dead_units_report_whether_they_hold_loot():
    """Live 2026-10-02: an empty corpse opens nothing and shows no error."""
    lua = _load_main_addon('''
        function UnitIsDead(unit) return unit == "target" end
        function CanLootUnit(guid) return false, true end
    ''')
    lua.execute("now=5; tickers[1].callback()")
    state = json.loads(lua.eval("ns.EncodeJSON(AIPlayerControllerExportDB.latest)"))
    assert state["target"]["lootable"] is False
    lua2 = _load_main_addon('''
        function UnitIsDead(unit) return unit == "target" end
        function CanLootUnit(guid) return true, true end
    ''')
    lua2.execute("now=5; tickers[1].callback()")
    assert json.loads(lua2.eval("ns.EncodeJSON(AIPlayerControllerExportDB.latest)"))["target"]["lootable"] is True



def test_every_snapshot_is_shown_twice_so_a_lost_page_comes_back():
    """Live 2026-10-06: each ~6-page snapshot was shown once; with ~20 % of
    frames not captured only 23 % ever completed.  A changing snapshot is now
    re-encoded only after two full rounds."""
    lua = lua_runtime()
    lua.execute('data={monotonic_time=1,timestamp=1001,character_name="Test",text=string.rep("abc",800)}')
    seen = {}
    for i in range(200):
        lua.execute(f"data.monotonic_time={1+i*.01}")
        parts = lua.eval("ns.NextPacket(data)").split("|", 6)
        if parts[5] in {"STATE", "STATE_Z"}:
            seen.setdefault(parts[2], []).append(parts[3])
    finished = list(seen.values())[:-1]
    assert finished and all(len(pages) >= 2*len(set(pages)) for pages in finished)


@pytest.mark.parametrize("in_combat", [True, False])
def test_every_fast_variant_keeps_the_survival_minimum(in_combat):
    # Issue #72: medium FAST packets dropped is_in_combat/is_dead/health in
    # the first size reductions, so combat (and its end) arrived late.
    variants = set()
    for reps, name_len in ((0, 4), (0, 8), (40, 60), (160, 200), (1000, 400)):
        lua = lua_runtime()
        lua.execute(f'''data={{monotonic_time=663820.446,timestamp=1790590610,
            map_id=1409,orientation=2.44,health=210,max_health=380,
            is_dead=false,is_ghost=false,is_in_combat={str(in_combat).lower()},is_casting=false,
            player_present=true,input_blocked=false,loading=false,
            movement={{speed=0,moving=false,falling=false,swimming=false}},
            target={{guid="Creature-0-4245-2175-18655-151091-00003A3DF9",
                name=string.rep("N",{name_len}),npc_id=151091,health=700,max_health=900,
                attackable=true,dead=false}},
            mouseover={{guid="Creature-0-4245-2175-18655-151091-00003A3DF9",
                name=string.rep("M",{name_len}),npc_id=151091,unit_type="NPC",
                tooltip=string.rep("hostile tooltip ",{reps})}},
            cursor_position={{nx=.47,ny=.53}},
            quest_state_revision=string.rep("r",{reps}),
            ui_error=string.rep("e",{reps}),
            actionbar_fast={{{{100,true,false,0}},{{1464,false,true,0}}}}}}''')
        packet = lua.eval("ns.NextPacket(data)")
        assert "|FAST|" in packet
        text = packet.split("|", 6)[6]
        assert len(text.encode("utf-8")) <= 850
        body = json.loads(text)
        variants.add(frozenset(body))
        assert body.get("is_in_combat") is in_combat, (reps, name_len, sorted(body))
        assert body.get("is_dead") is False and body.get("is_ghost") is False
        assert body.get("input_blocked") is False
    assert len(variants) >= 2   # more than one size reduction exercised
