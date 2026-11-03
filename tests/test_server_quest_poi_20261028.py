"""Numeric server POIs through the real decoder, IPC boundary and quest resolver."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import struct

import pytest

from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import decoded
from wowbot.agent.models import Observation
from wowbot.agent.quest_poi_evidence import server_turnin_poi
from wowbot.agent.turnin_resolver import TurnInResolver
from wowbot.packetio.quest_poi import decode_quest_pois
from wowbot.packetio.validation import normalize_event, verified_semantics


def payload(*, quest=65793, empty=False, z=313):
    blobs = [] if empty else [(-1,0,[(1792,31,z)]),(2,423376,[(1876,322,0),(1925,660,0)])]
    data = struct.pack('<IIiI',1,1,quest,len(blobs))
    for objective, oid, points in blobs:
        # BlobIndex intentionally repeats: group identity is not BlobIndex alone.
        data += struct.pack('<12iI',0,objective,oid,0,2444,2022,0,0,0,0,0,0,len(points))
        data += b''.join(struct.pack('<hhh',*point) for point in points)+b'\x00'
    return data


def event(**kwargs):
    return decoded('SMSG_QUEST_POI_QUERY_RESPONSE',payload(**kwargs),build=70575)[-1]


def test_reviewed_70575_packet_preserves_xyz_and_separate_objective_groups():
    value = event()
    assert value.event_type == 'QUEST_POI_UPDATE' and verified_semantics(value.to_dict())
    safe = normalize_event(value.to_dict())
    blobs = safe['payload']['blobs']
    assert blobs[0]['objective_index'] == -1 and blobs[0]['points'] == [{'x':1792,'y':31,'z':313}]
    assert blobs[1]['objective_id'] == 423376 and blobs[1]['group_index'] != blobs[0]['group_index']
    assert blobs[1]['blob_index'] == blobs[0]['blob_index'] == 0


@pytest.mark.parametrize('bad', [payload()[:-1],payload()+b'\x00',b'\xff'*8])
def test_incomplete_oversized_or_trailing_payload_emits_no_partial_semantics(bad):
    values = decoded('SMSG_QUEST_POI_QUERY_RESPONSE',bad,build=70575)
    assert not any(value.event_type == 'QUEST_POI_UPDATE' for value in values)


def test_poi_payload_is_not_promoted_on_an_uncaptured_opcode_family():
    assert all(value.event_type != 'QUEST_POI_UPDATE' for value in
               decoded('SMSG_QUEST_POI_QUERY_RESPONSE',payload(),build=69587))


def test_nested_unknown_text_is_removed_and_coordinate_types_are_checked():
    original = event().to_dict()
    original['payload']['blobs'][0]['chat'] = 'must not be forwarded'
    original['payload']['blobs'][0]['points'][0]['unreviewed'] = 'text'
    safe = normalize_event(original)
    assert 'chat' not in safe['payload']['blobs'][0]
    assert 'unreviewed' not in safe['payload']['blobs'][0]['points'][0]
    original['payload']['blobs'][0]['points'][0]['z'] = True
    with pytest.raises(ValueError): normalize_event(original)


def scene(**changes):
    return addon(game_build='70575',frame_id='poi:9',map_id=2022,
        player_world_position={'x':1792.,'y':31.,'z':128.,'z_observed':True,'z_known':True,
            'coordinate_space':'WORLD_YARDS','instance_id':2444},
        active_quests=[{'quest_id':65793,'is_complete':True,'objectives':[]}],**changes)


def ready(bridge):
    bridge.world.ingest(Observation.create(scene(),9.))
    bridge.adapter.observations(None,bridge.world,10.)


def newer(bridge, **changes):
    at = bridge.__dict__.get('_poi_test_at',10.)+.2
    bridge.__dict__['_poi_test_at'] = at
    value = scene()
    value.update(frame_id=f'poi:{at}',monotonic_time=at,timestamp=at,**changes)
    bridge.world.ingest(Observation.create(value,at))


def test_actual_bridge_projects_server_poi_without_granting_input_freshness(bridge):
    ready(bridge)
    deliver(bridge,event())
    assert bridge.world.last_received == 9.
    assert bridge.world.addon_state.get('packet_quest_pois') is None
    assert bridge.world.state['player_world_position']['z'] == 128.
    newer(bridge)
    result = TurnInResolver().locate(SimpleNamespace(quest_id=65793,known_locations=[]),bridge.world.state)
    assert result.location['z'] == 313. and result.location['knowledge_priority'] == 'SERVER_POI'
    assert not result.location.get('server_entity_guid') and result.entity_guid is None
    assert result.evidence == ('current_server_turnin_poi',)


def test_an_empty_new_snapshot_clears_the_old_turnin_point(bridge):
    ready(bridge);deliver(bridge,event());deliver(bridge,event(empty=True));newer(bridge)
    assert server_turnin_poi(bridge.world.state,65793) is None


@pytest.mark.parametrize('change',[{'session_id':'new'},{'game_build':'70448'},
                                    {'character_guid':'Player-1602-00009999'},{'loading':True}])
def test_other_session_character_build_and_loading_cannot_reuse_pois(bridge,change):
    ready(bridge);deliver(bridge,event());newer(bridge,**change)
    assert not bridge.world.state.get('packet_quest_pois')


def test_removed_quest_cannot_resurrect_its_old_snapshot_after_reaccept(bridge):
    ready(bridge);deliver(bridge,event());newer(bridge,active_quests=[])
    newer(bridge)
    assert not bridge.world.state.get('packet_quest_pois')


def test_unverified_provenance_cannot_create_a_poi_destination(bridge):
    ready(bridge)
    value=event();deliver(bridge,replace(value,provenance={**value.provenance,'semantic_ground_truth':False}))
    newer(bridge)
    assert not bridge.world.state.get('packet_quest_pois')


def test_zero_z_polygons_incomplete_and_ambiguous_turnins_are_not_exact_height(bridge):
    ready(bridge);deliver(bridge,event(z=0));newer(bridge)
    point=server_turnin_poi(bridge.world.state,65793)
    assert point['z_known'] is False and 'z' not in point
    value=deepcopy(bridge.world.state)
    second=deepcopy(value['packet_quest_pois']['65793']['blobs'][0]);second['points'][0]['x']+=50
    value['packet_quest_pois']['65793']['blobs'].append(second)
    assert server_turnin_poi(value,65793) is None
    value=deepcopy(bridge.world.state);value['active_quests'][0]['is_complete']=False
    assert server_turnin_poi(value,65793) is None


def test_actual_server_ender_outranks_the_poi_and_the_static_reference(bridge):
    ready(bridge);deliver(bridge,event());newer(bridge)
    state=deepcopy(bridge.world.state)
    guid='Creature-0-1-2444-1-190740-00001'
    state['reference_knowledge']={'quests':{'65793':{'quest_roles':[
        {'npc_id':190740,'role':'QUEST_ENDER'}]}}}
    state['player_world_position'].update(z=313.)
    state['packet_entities']={guid:{'guid':guid,'entry_id':190740,'map_id':2444,'kind':'CREATURE',
        'info':{'npc_flags':3},'quest_giver':{'reward_ready':True,'sampled_at':10.},
        'position':{'x':1793.,'y':31.,'z':313.,'source':'PACKET_CREATE_MOVEMENT'}}}
    result=TurnInResolver().locate(SimpleNamespace(quest_id=65793,known_locations=[]),state)
    assert result.entity_guid == guid and result.location['knowledge_priority']=='SERVER_LIVE'
    assert result.location['x']==1793.


def test_a_selected_ender_of_another_quest_does_not_override_this_quests_server_poi(bridge):
    ready(bridge);deliver(bridge,event());newer(bridge)
    state=deepcopy(bridge.world.state)
    state['target']={'guid':'Creature-0-1-2444-1-999-00001','npc_id':999,
        'quest_role':'TURN_IN','quest_id':999,'attackable':False}
    result=TurnInResolver().locate(SimpleNamespace(quest_id=65793,known_locations=[]),state)
    assert result.location['knowledge_priority']=='SERVER_POI' and result.entity_guid is None


@pytest.mark.parametrize('change',['old','other_map','conditional','wrong_objective'])
def test_stale_wrong_map_and_unresolved_conditional_blobs_cannot_become_turnin_destinations(bridge,change):
    ready(bridge);deliver(bridge,event());newer(bridge)
    state=deepcopy(bridge.world.state)
    record=state['packet_quest_pois']['65793'];blob=record['blobs'][0]
    if change=='old':record['sampled_at']=-2000.
    elif change=='other_map':blob['world_map_id']=2175
    elif change=='conditional':blob['player_condition_id']=123
    else:blob['objective_index']=2
    assert server_turnin_poi(state,65793) is None


def test_a_poi_answered_during_the_loading_screen_survives_it(bridge):
    # Live 2026-10-31 08:00 (login): POI responses arrived 1.4 s before the
    # NEW_WORLD; wiping them during loading left only the TDB ender spawn.
    ready(bridge);deliver(bridge,event());newer(bridge,loading=True)
    assert not bridge.world.state.get('packet_quest_pois')            # hidden while loading
    newer(bridge)
    result = TurnInResolver().locate(SimpleNamespace(quest_id=65793,known_locations=[]),bridge.world.state)
    assert result.location['knowledge_priority'] == 'SERVER_POI' and result.location['z'] == 313.


def test_a_poi_answered_before_the_logins_new_world_survives_the_world_step(bridge):
    # Live 2026-10-31 09:40: POIs at +3.6 s, NEW_WORLD at +5.05 s; the world
    # step dropped every POI. A UI-map/world/phase step in one identity keeps them.
    ready(bridge);deliver(bridge,event())
    newer(bridge, map_id=2023, phase='other-phase',
          player_world_position={'x':1792.,'y':31.,'z':128.,'z_observed':True,'z_known':True,
                                 'coordinate_space':'WORLD_YARDS','instance_id':2444})
    assert '65793' in (bridge.world.state.get('packet_quest_pois') or {})


def test_a_continuity_step_keeps_the_identity_scoped_pois(bridge):
    # Live 2026-10-31 09:54: the login NEW_WORLD bumped the continuity
    # generation; discard_fields dropped every POI. Entities still go.
    from wowbot.agent.packet_continuity import discard_fields
    ready(bridge);deliver(bridge,event());newer(bridge)
    bridge.world.__dict__['_packet_entities'] = {'x': {}}
    discard_fields(bridge.world, bridge.world.state)
    assert '_packet_entities' not in bridge.world.__dict__
    newer(bridge)
    result = TurnInResolver().locate(SimpleNamespace(quest_id=65793,known_locations=[]),bridge.world.state)
    assert result.location['knowledge_priority'] == 'SERVER_POI'
    newer(bridge, character_guid='Player-1602-00009999')                 # another identity: dropped
    assert not bridge.world.state.get('packet_quest_pois')


def test_a_poi_answer_read_late_during_the_login_is_still_kept(bridge):
    # Live 2026-10-31 09:58: the agent read the queue late at login; 130
    # events older than 2 s were discarded, the POI answers among them.
    import json as _json
    from test_packet_agent_bridge import canonical, envelope
    ready(bridge)
    descriptor = _json.loads(bridge.path.read_text())
    assert bridge.inbox.ingest_datagram(canonical(envelope(event().to_dict(), descriptor)))
    late = bridge.adapter.observations(None, bridge.world, 25.)            # read 15 s after sampling
    assert len(late) == 1 and bridge.world.ingest(late[0])
    newer(bridge)
    result = TurnInResolver().locate(SimpleNamespace(quest_id=65793,known_locations=[]),bridge.world.state)
    assert result.location['knowledge_priority'] == 'SERVER_POI'


def test_motion_read_as_late_stays_stale(bridge):
    import json as _json
    from test_packet_agent_bridge import canonical, envelope
    ready(bridge)
    descriptor = _json.loads(bridge.path.read_text())
    assert bridge.inbox.ingest_datagram(canonical(envelope(decoded()[-1].to_dict(), descriptor)))
    assert bridge.adapter.observations(None, bridge.world, 25.) == ()
    assert bridge.adapter.stale_event_discards == 1


def test_the_poi_status_names_the_gate(bridge):
    assert bridge.world.query.quest_poi_status(65793, 10.) == 'no_poi_scope'
    ready(bridge);deliver(bridge,event())
    assert bridge.world.query.quest_poi_status(65793, 10.) == 'ok:2_blobs'
    assert bridge.world.query.quest_poi_status(1, 10.) == 'no_record:1_quests'
    assert bridge.world.query.quest_poi_status(65793, 2000.).startswith('age:')


def test_the_inbox_keeps_a_queued_poi_answer_while_motion_expires(tmp_path):
    # Live 2026-10-31 10:10: the inbox expired the login POI answers in its
    # queue after 2 s (the agent drained it late); no POI ever reached a model.
    import json as _json
    from wowbot.agent.runtime_packet_source import RuntimePacketSource
    from wowbot.agent.world import WorldModel
    from wowbot.packetio.inbox import PacketEventInbox
    from test_packet_agent_bridge import canonical, envelope
    clock = SimpleNamespace(now=10.)
    world = WorldModel()
    world.ingest(Observation.create(scene(), 9.))
    inbox = PacketEventInbox(77, port=0, autostart=False, clock=lambda: clock.now, wall_clock=lambda: 1000.)
    adapter = RuntimePacketSource(77, tmp_path, source=inbox, wall_clock=lambda: 999.)
    try:
        adapter.observations(None, world, 10.)
        descriptor = _json.loads((tmp_path/'packet_endpoint.json').read_text())
        for value in (event(), decoded()[-1]):
            assert inbox.ingest_datagram(canonical(envelope(value.to_dict(), descriptor)))
        clock.now = 25.
        observations = adapter.observations(None, world, 25.)
        kinds = [o.payload['packet_event']['event_type'] for o in observations]
        assert kinds == ['QUEST_POI_UPDATE'] and inbox.take_stale_counts() == (0, 0)
    finally:
        adapter.close()
