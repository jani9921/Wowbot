"""Regressions for the real 16:42 / 17:00 hand-ins below Ruby Lifeshrine."""
from types import SimpleNamespace
import time

from test_server_quest_poi_20261028 import event, scene, ready, newer
from test_packet_agent_bridge import bridge, deliver
from test_travel_mode_20261020 import CAPABLE, favorite_mount
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.tdb_locations import role_region
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.agent.turnin_resolver import TurnInResolver
from wowbot.packetio.forwarder import SnapshotReplayForwarder
from wowbot.packetio.quest_poi_snapshot import QuestPoiSnapshot


def completed_scene():
    s = scene()
    s.update(monotonic_time=10., movement={'indoors': False, 'flying': False, 'falling': False},
        is_mounted=False, flight={'advanced_flyable_area': True}, mount_capability=CAPABLE,
        actionbar=[favorite_mount()])
    s['player_world_position'].update(x=1815., y=437., z=85.)
    s['quest_locations'] = [{'quest_id': 65793, 'map_id': 2022, 'source': 'QUEST_POI',
        'x': .5795, 'y': .673, 'world_position': {'x': 1792., 'y': 31., 'z_known': False,
        'instance_id': 2444, 'ui_map_id': 2022, 'coordinate_space': 'WORLD_YARDS'}}]
    s['reference_knowledge'] = {'quests': {'65793': {'pois': [
        {'poi_id': '65793:0:0', 'objective_index': -1, 'objective_id': 0,
         'world_map_id': 2444, 'ui_map_id': 2022, 'points': [{'x':1792, 'y':31, 'z':313}]}],
        'learned': [{'kind':'HINT_OUTCOME', 'hint_id':'poi:65793:0:0', 'outcome':'FAILURE',
            'reason': reason, 'observed_at':time.time()} for reason in
            ['skyriding_not_mounted', 'required_navmesh_route_unavailable']]}}}
    return s


def test_execution_failures_do_not_blacklist_the_known_upper_turnin():
    s = completed_scene()
    record = SimpleNamespace(quest_id=65793, current_state='COMPLETED', known_locations=[])
    resolved = TurnInResolver().locate(record,s)
    assert resolved.location['z'] == 313. and resolved.location['knowledge_priority'] == 'QUEST_API_CURRENT'
    assert resolved.location['z_knowledge_priority'] == 'PRIMARY_STATIC'
    # Genuine target-rejection failures still retain the existing suppression.
    for row in s['reference_knowledge']['quests']['65793']['learned']:
        row['reason'] = 'wrong_target_identity'
    assert role_region(s,65793,'QUEST_ENDER') is None


def test_canonical_turnin_owns_the_route_and_does_not_compete_with_the_2d_pin():
    s = completed_scene()
    world = SimpleNamespace(state=s, session_id=s['session_id'],
        query=SimpleNamespace(remembered_locations=lambda *a: []))
    record = SimpleNamespace(quest_id=65793,current_state='COMPLETED',known_locations=[])
    policy = QuestLocationPlanningPolicy()
    turnins = policy.propose_turnins({65793:record},s,{})
    proposals = turnins + policy.propose_known_locations(world,
        owned_turnins={str(p.parameters['quest_id']) for p in turnins})
    assert len(proposals) == 1 and proposals[0].parameters['z'] == 313.
    flown = TravelModePolicy().apply(proposals,SimpleNamespace(parameters={}),world,10.)
    assert {p.skill for p in flown} == {'MOUNT','MOVE'}
    move = next(p for p in flown if p.skill == 'MOVE')
    assert move.parameters['flight'] is True and move.parameters['z'] == 313.


def test_login_poi_is_replayed_once_the_receiver_exists_with_its_original_age():
    sent = []
    receiver = SimpleNamespace(context=None, context_id=lambda: receiver.context,
        emit=lambda e: bool(receiver.context) and not sent.append(e), close=lambda: None)
    clock = [1000.]
    sink = SnapshotReplayForwarder(receiver,wall_clock=lambda:clock[0])
    assert not sink.emit(event())
    clock[0] = 1020.;receiver.context = 'selected-player-context'
    sink.flush()
    assert len(sent) == 1 and sent[0].event_type == 'QUEST_POI_UPDATE'
    assert sent[0].timestamp == 1020. and sent[0].payload['capture_timestamp'] == 1000.
    sink.flush();assert len(sent) == 1
    receiver.context = 'next-context';clock[0] = 2801.
    sink.flush();assert len(sent) == 1


def test_replayed_poi_keeps_source_age_and_cannot_refresh_player_or_input_authority(bridge):
    from dataclasses import replace
    ready(bridge)
    cache = QuestPoiSnapshot();cache.note(replace(event(),timestamp=980.))
    replay = cache.replay(65793,1000.)
    deliver(bridge,replay)
    assert bridge.world.last_received == 9.
    newer(bridge)
    record = bridge.world.state['packet_quest_pois']['65793']
    assert record['sampled_at'] == -10.
    assert bridge.world.last_received == bridge.world.state['monotonic_time']
    assert bridge.world.state['player_world_position']['z'] == 128.
    assert TurnInResolver().locate(SimpleNamespace(quest_id=65793,known_locations=[]),
        bridge.world.state).location['z'] == 313.


def test_new_map_and_unverified_poi_cannot_replay_old_geometry():
    from dataclasses import replace
    cache = QuestPoiSnapshot();cache.note(event())
    cache.note(replace(event(),event_type='MAP_CHANGED',payload={'world_map_id':2534}))
    assert cache.replay(65793,1000.) is None
    cache.note(replace(event(),provenance={**event().provenance,'semantic_ground_truth':False}))
    assert cache.replay(65793,1000.) is None


def test_a_running_2d_route_yields_once_to_the_new_server_height(bridge):
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    ready(bridge);deliver(bridge,event());newer(bridge)
    old = SimpleNamespace(started_at=10.,proposal=SimpleNamespace(skill='MOVE',parameters={
        'quest_id':65793,'purpose':'LOCATE_TURN_IN_REGION','x':1792.,'y':31.,'z_known':False}))
    for fast in [True,False]:
        assert movement_visual_interrupt(old,bridge.world.state,identity_only=fast)['kind'] == 'SERVER_TURN_IN_POI_AVAILABLE'
    point = TurnInResolver().locate(SimpleNamespace(quest_id=65793,known_locations=[]),bridge.world.state).location
    old.proposal.parameters.update(point)
    assert movement_visual_interrupt(old,bridge.world.state,identity_only=True) is None


def test_a_poi_received_before_addon_state_waits_for_the_same_context(bridge):
    from wowbot.agent.models import Observation
    from wowbot.agent.world import WorldModel
    ready(bridge)
    first = deliver(bridge,event())
    following = deliver(bridge,event(quest=999))
    late = WorldModel()
    assert not late.ingest(first)
    assert late.__dict__.get('_packet_pending')
    late.ingest(Observation.create(scene(),10.1))
    late.ingest(following)
    assert late.state['packet_quest_pois']['65793']['blobs'][0]['points'][0]['z'] == 313
    assert late.last_received == 10.1
