import json

from test_agent_transport import lua_runtime
from wowbot.agent.parallel_view import control_view


def test_real_lua_transport_and_fast_projection_keep_exact_own_channel_identity():
    lua=lua_runtime()
    lua.execute('''data={monotonic_time=1,timestamp=1001,map_id=2022,
        player_present=true,is_casting=true,
        combat_hint={spell_id=22810,at=.5,channel_spell_id=375531,channel_at=1},
        movement={moving=false,indoors=false},actionbar={}}''')
    packet=lua.eval('ns.NextPacket(data)')
    body=json.loads(packet.split('|',6)[6])
    assert body['combat_hint']['channel_spell_id']==375531
    assert body['combat_hint']['channel_at']==1
    projected=control_view({},body,None,1.)
    assert projected['combat_hint']['channel_spell_id']==375531
    assert projected['is_casting'] is True
