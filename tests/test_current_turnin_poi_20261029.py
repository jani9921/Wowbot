"""Current completed-quest pins outrank historical alternative ender spawns."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.quest_poi_evidence import current_turnin_poi
from wowbot.agent.turnin_resolver import TurnInResolver


def scene(qid=70185):
    return {'monotonic_time': 100., 'map_id': 2023,
        'player_world_position': {'coordinate_space': 'WORLD_YARDS', 'instance_id': 2444,
                                  'x': -358., 'y': 954.},
        'active_quests': [{'quest_id': qid, 'is_accepted': True, 'is_complete': True}],
        'quest_locations': [{'quest_id': qid, 'source': 'QUEST_POI', 'in_progress': True,
            'coordinate_space': 'NORMALIZED_MAP', 'x': .7574, 'y': .3169, 'map_id': 2023,
            'world_position': {'coordinate_space': 'WORLD_YARDS', 'instance_id': 2444,
                              'ui_map_id': 2023, 'x': -178., 'y': 1084., 'z_known': False}}],
        'reference_knowledge': {'quests': {str(qid): {'spawn_candidates': [{
            'role': 'QUEST_ENDER', 'world_map_id': 2444, 'x': 140., 'y': 358., 'z': 343.,
            'entry': 185882, 'entity_kind': 'CREATURE', 'spawn_id': 999}]}}}}


@pytest.mark.parametrize('qid', [70185, 90222])
def test_current_api_pin_wins_over_an_old_or_cheaper_static_ender(qid):
    resolver = TurnInResolver(travel_cost=lambda *a: pytest.fail('Do not rank static spawns'))
    current = scene(qid)
    before = deepcopy(current)
    resolved = resolver.locate(SimpleNamespace(quest_id=qid, known_locations=[]), current)
    assert resolved.location['x'] == -178. and resolved.location['y'] == 1084.
    assert resolved.location['knowledge_priority'] == 'QUEST_API_CURRENT'
    assert resolved.evidence == ('current_quest_api_turnin_poi',)
    assert not resolved.location['z_known'] and resolved.entity_guid is None
    assert current == before


def test_verified_packet_poi_remains_stronger_than_the_api_pin():
    current = scene()
    current['packet_quest_pois'] = {'70185': {'verified': True, 'sampled_at': 99.,
        'source': 'SMSG_QUEST_POI_QUERY_RESPONSE', 'blobs': [{
            'objective_index': -1, 'objective_id': 0, 'world_map_id': 2444, 'ui_map_id': 2023,
            'blob_index': 0, 'group_index': 0, 'points': [{'x': 700., 'y': 800., 'z': 300.}]}]}}
    point = current_turnin_poi(current, 70185)
    assert point['x'] == 700. and point['z'] == 300.
    assert point['knowledge_priority'] == 'SERVER_POI'


@pytest.mark.parametrize('bad', ['incomplete', 'unaccepted', 'task', 'other_quest', 'other_instance',
                                'no_conversion', 'old_memory', 'objective_role'])
def test_objective_task_memory_and_wrong_world_points_are_not_current_turnins(bad):
    current = scene()
    row = current['quest_locations'][0]
    if bad == 'incomplete': current['active_quests'][0]['is_complete'] = False
    if bad == 'unaccepted': current['active_quests'][0]['is_accepted'] = False
    if bad == 'task': row['source'] = 'TASK_QUEST_POI'
    if bad == 'other_quest': row['quest_id'] = 999
    if bad == 'other_instance': row['world_position']['instance_id'] = 42
    if bad == 'no_conversion': row.pop('world_position')
    if bad == 'old_memory': row['source'] = 'MEMORY'
    if bad == 'objective_role': row['role'] = 'OBJECTIVE'
    assert current_turnin_poi(current, 70185) is None


def test_same_instance_pin_across_a_ui_zone_edge_is_still_navigable():
    current = scene()
    current['quest_locations'][0]['world_position']['ui_map_id'] = 2024
    assert current_turnin_poi(current, 70185)['instance_id'] == 2444


def test_two_conflicting_current_pins_are_not_arbitrarily_selected():
    current = scene()
    second = deepcopy(current['quest_locations'][0])
    second['world_position']['x'] += 100.
    current['quest_locations'].append(second)
    assert current_turnin_poi(current, 70185) is None


@pytest.mark.parametrize('fast', [True, False])
def test_old_tdb_move_yields_once_to_current_api_pin(fast):
    current = scene()
    attempt = SimpleNamespace(started_at=90., proposal=SimpleNamespace(skill='MOVE', parameters={
        'quest_id': 70185, 'purpose': 'LOCATE_TURN_IN_REGION', 'x': 140., 'y': 358.,
        'knowledge_priority': 'PRIMARY_STATIC'}))
    result = movement_visual_interrupt(attempt, current, identity_only=fast)
    assert result['kind'] == 'QUEST_API_TURN_IN_POI_AVAILABLE'
    attempt.proposal.parameters.update(current_turnin_poi(current, 70185))
    assert movement_visual_interrupt(attempt, current, identity_only=fast) is None


def test_shared_turnin_planning_emits_the_current_point_as_a_search_move():
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy()
    record = SimpleNamespace(quest_id=70185, current_state='COMPLETED', known_locations=[])
    (proposal,) = policy.propose_turnins({'70185': record}, scene(), {})
    assert proposal.skill == 'MOVE' and proposal.parameters['purpose'] == 'LOCATE_TURN_IN_REGION'
    assert proposal.parameters['x'] == -178. and proposal.parameters['require_navmesh']
    assert not proposal.parameters.get('server_entity_guid')


def test_an_agreeing_static_height_preserves_vertical_flight_without_replacing_the_api_xy():
    from test_turnin_height_handoff_20261028 import completed_scene
    from test_short_layer_flight_20261027 import BridgeGeometry
    from wowbot.navigation.global_planner import GlobalNavigator
    from wowbot.navigation.contracts import NavigationRequest
    current = completed_scene()
    point = TurnInResolver().locate(SimpleNamespace(quest_id=65793, known_locations=[]), current).location
    assert (point['x'], point['y']) == (1792., 31.)
    assert point['knowledge_priority'] == 'QUEST_API_CURRENT'
    assert point['z'] == 313. and point['z_estimated'] is True
    current['player_world_position'].update(x=point['x'], y=point['y'], z=85., z_observed=True)
    request = NavigationRequest('upper', 'one-owner', 'MOVE_TO_LOCATION',
        {**point, 'flight': True, 'flight_style': 'STEADY'})
    route = GlobalNavigator(navmesh=BridgeGeometry()).plan(request, current, 10.)
    assert route.regions[0]['route_source'] == 'FLIGHT_PLAN'
    assert route.anchors[-1]['flight_plan']['landing']['z'] == 313.
