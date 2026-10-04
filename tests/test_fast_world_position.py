"""FAST world position (live 2026-10-02).

All 1083 logged FAST states came from the bounded transport variants, which
carried no ``player_world_position``.  Movement then saw a 1-3 s old position
from the paged STATE and failed MOVE as "stuck" while the character ran.
"""
import json

from adapters.telemetry_packets import PacketAssembler
from wowbot.agent.movement_controller import MovementPhase, ReachMovementController
from test_agent_transport import lua_runtime
from test_agent_core import state

LIVE_LIKE_FAST = '''{monotonic_time=356196.771,timestamp=1790963400,character_name="Test",
    map_id=1409,orientation=0.57191348075867,
    map_context={active_map_id=1409,parent_map_id=1726,player_map_id=1409,map_name="Exile's Reach",
        parent_map_name="The Maelstrom",world_map_open=false},
    position={x=0.60339450836182,y=0.79846882820129},
    player_world_position={x=-405.73272705078,y=-2604.6123046875,instance_id=2175,ui_map_id=1409,
        coordinate_space="WORLD_YARDS",source="C_MAP_PLAYER_WORLD_POS",z_known=false,
        z_source="NAVMESH_XY_PROJECTION_REQUIRED"},
    movement={speed=7,moving=true,falling=false,swimming=false},
    target={guid="Creature-0-3896-2175-13447-156626-00003F9726",name="Lady Jaina Proudmoore",
        npc_id=156626,attackable=false,dead=false,
        world_position={x=-437.1,y=-2611.0,instance_id=2175,coordinate_space="WORLD_YARDS"}},
    mouseover={guid="Creature-0-3896-2175-13447-156627-00003F9727",name="Quartermaster Richter",
        npc_id=156627,unit_type="NPC",is_attackable=false,is_dead=false,
        identity_source="WOW_API_MOUSEOVER",tooltip=string.rep("NPCodex descriptive tooltip ",40)},
    cursor_position={nx=0.48042701537695,ny=0.31789475287942},
    quest_ui={open=false,action="",x=0,y=0,quest_id=0},
    extra_action={visible=false,usable=false,action="",action_type="",action_id=0},
    quest_digest={{id=55122,complete=false,done=0,need=6}},
    actionbar_fast={{slot=1,usable=true,cooldown=0},{slot=2,usable=true,cooldown=0},{slot=3,usable=false,cooldown=0}},
    player_present=true,loading=false,input_blocked=false}'''


def _fast_body(lua, sample):
    lua.execute(f"state={{monotonic_time=1,timestamp=1001,character_name='Test'}}; fast={sample}")
    packet = lua.eval("ns.NextPacket(state, fast)")
    assert "|FAST|" in packet and len(packet.encode("utf-8")) <= 1000
    body = packet.split("|", 6)[6]
    assert len(body.encode("utf-8")) <= 850
    return json.loads(body)


def test_bounded_fast_packet_keeps_the_world_position():
    body = _fast_body(lua_runtime(), LIVE_LIKE_FAST)
    assert "falling" not in body["movement"]          # a bounded variant was needed
    assert body["player_world_position"] == {
        "x": -405.73, "y": -2604.61, "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}
    assert body["mouseover"]["name"] == "Quartermaster Richter"
    assert not any(key.endswith("_sample_time") for key in body)


def test_bounded_combat_and_edge_packets_keep_the_world_position():
    lua = lua_runtime()
    combat = LIVE_LIKE_FAST.replace("player_present=true", "player_present=true,is_in_combat=true,"
                                    "health=80,max_health=100")
    combat = combat.replace('name="Quartermaster Richter"', 'name=string.rep("R",90)')
    body = _fast_body(lua, combat)
    assert body["player_world_position"]["x"] == -405.73
    edge = LIVE_LIKE_FAST.replace('name="Quartermaster Richter"', 'name=string.rep("R",95)')
    edge = edge.replace("quest_digest=", "map_mouseover={tooltip=string.rep('t',500)},quest_digest=")
    assert _fast_body(lua, edge)["player_world_position"]["instance_id"] == 2175


def _packet(seq, kind, body):
    return f"AIPC5|s|{seq}|0|1|{kind}|{json.dumps(body)}"


def test_assembler_restores_sample_times_and_stamps_position_measurements():
    assembler = PacketAssembler()
    full = assembler.feed(_packet(1, "STATE", {
        "monotonic_time": 10., "character_name": "Test", "map_id": 1409,
        "player_world_position": {"x": 1., "y": 2., "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"}}), 10.)
    assert full["player_world_position"]["sample_time"] == 10.
    fast = assembler.feed(_packet(2, "FAST", {
        "monotonic_time": 11.5, "map_id": 1409, "mouseover": False, "target": False,
        "player_world_position": {"x": -405.73, "y": -2604.61, "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"}}), 11.5)
    for key in ("target_sample_time", "mouseover_sample_time", "cursor_sample_time"):
        assert fast[key] == 11.5
    assert fast["player_world_position"] == {
        "x": -405.73, "y": -2604.61, "instance_id": 2175, "coordinate_space": "WORLD_YARDS",
        "source": "C_MAP_PLAYER_WORLD_POS", "ui_map_id": 1409, "z_known": False,
        "z_source": "NAVMESH_XY_PROJECTION_REQUIRED", "sample_time": 11.5}
    # A FAST packet without a position leaves the old measurement marked old.
    stale = assembler.feed(_packet(3, "FAST", {"monotonic_time": 12., "map_id": 1409}), 12.)
    assert "player_world_position" not in stale


DESTINATION = {"x": 0., "y": 100., "instance_id": 2175, "coordinate_space": "WORLD_YARDS",
               "stop_distance": 4.}


def _world_state(at, y, sample_time, *, moving=True):
    return state(at, orientation=math_pi_half(), movement={"speed": 7. if moving else 0., "moving": moving},
                 player_world_position={"x": 0., "y": y, "instance_id": 2175,
                                        "coordinate_space": "WORLD_YARDS", "sample_time": sample_time})


def math_pi_half():
    import math
    return math.pi / 2


def _run(samples):
    controller = ReachMovementController()
    first = samples[0]
    controller.start(DESTINATION, _world_state(*first), "o0", first[0])
    controller.command(_world_state(*first), "o0", first[0])
    results = []
    for index, sample in enumerate(samples[1:], 1):
        result = controller.observe(_world_state(*sample), f"o{index}", sample[0])
        results.append(result)
        if result.terminal:
            break
        controller.command(_world_state(*sample), f"o{index}", sample[0])
    return controller, results


def test_running_with_slow_position_updates_is_not_stuck():
    """30 Hz observations, position measured every 1.5 s, running 7 yd/s."""
    samples = []
    for index in range(0, 300):                       # 10 s
        at = 1. + index / 30.
        measured = 1. + 1.5 * int((at - 1.) // 1.5)   # the last position measurement
        samples.append((at, (measured - 1.) * 7., measured))
    controller, results = _run(samples)
    assert not any(r.phase in {MovementPhase.CANDIDATE_STUCK, MovementPhase.SUPPORTED_STUCK}
                   for r in results)
    assert any(r.reason == "reach_progress_observed" for r in results)
    assert any(r.reason == "awaiting_fresh_position_sample" for r in results)


def test_wall_contact_with_fresh_measurements_is_still_stuck():
    samples = [(1. + index / 30., 0., 1. + index / 30.) for index in range(0, 200)]
    _controller, results = _run(samples)
    assert results[-1].phase == MovementPhase.SUPPORTED_STUCK
    assert results[-1].reason == "supported_stuck"
