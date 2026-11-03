"""General objective-place + known giver trial; no required prose phrase."""
from copy import deepcopy

import pytest

from wowbot.agent.conversation_actors import conversation_actors
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.quest_attempt_memory import QuestAttemptMemory
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy as Dialog
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from test_quest_meeting_speaker_20261028 import live, GUID
from test_gossip_trials_20261028 import terminal


def situation():
    state = live()
    state['quest_text']['description'] = ''   # No 'find me', readiness, or NPC name in the objective.
    state['player_world_position']['coordinate_space'] = 'WORLD_YARDS'
    state['quest_locations'] = [{'quest_id': 65803, 'map_id': 2023, 'source': 'QUEST_POI',
        'in_progress': True, 'world_position': {'coordinate_space': 'WORLD_YARDS', 'instance_id': 2444,
            'ui_map_id': 2023, 'x': 224., 'y': 522., 'z_known': False}}]
    return state


def reference(state):
    return state['reference_knowledge']['quests']['65803']


@pytest.mark.parametrize('mechanism', ['ARRIVE', 'TRAVEL_TO', 'REACH_AREA', 'UNKNOWN'])
def test_known_giver_at_current_point_is_a_trial_without_a_prose_rule(mechanism):
    state = situation()
    reference(state)['objectives'][0]['mechanism'] = mechanism
    assert [a['entry'] for a in conversation_actors(state, 65803)] == [185882]
    (proposal,) = ServerNpcInteractionPolicy().propose(state)
    assert proposal.skill == 'INTERACT' and proposal.parameters['soft_guid'] == GUID
    assert proposal.parameters['quest_id'] == '65803'


def test_other_quest_ids_use_the_same_rule_without_id_specific_scripts():
    state = situation()
    state['quest_text']['quest_id'] = 700001
    state['active_quests'][0]['quest_id'] = 700001
    state['quest_locations'][0]['quest_id'] = 700001
    state['reference_knowledge']['quests'] = {'700001': reference(state)}
    assert [a['entry'] for a in conversation_actors(state, 700001)] == [185882]


def test_an_arrival_without_a_talk_clause_can_open_the_known_giver_window():
    state = situation()
    state['active_quests'][0]['objectives'][0]['description'] = '0/1 Reach this location'
    reference(state)['objectives'][0]['description'] = 'Reach this location'
    assert [a['entry'] for a in conversation_actors(state, 65803)] == [185882]


def test_static_current_objective_point_and_known_unique_role_are_sufficient():
    state = situation()
    state.pop('quest_text')
    state.pop('quest_locations')
    reference(state)['pois'] = [{'poi_id': '65803:0:1', 'objective_id': 423553,
        'objective_index': 0, 'world_map_id': 2444, 'ui_map_id': 2023,
        'points': [{'x': 224., 'y': 522., 'z': 340.}]}]
    assert [a['entry'] for a in conversation_actors(state, 65803)] == [185882]


@pytest.mark.parametrize('bad', ['no_location', 'far_player', 'far_npc', 'wrong_floor',
    'wrong_world', 'wrong_ui_map', 'two_live_points', 'turnin_only', 'unaccepted_task',
    'other_objective_point', 'other_quest_point', 'no_quest_identity', 'explicit_other_npc'])
def test_current_location_and_known_actor_identity_are_both_required(bad):
    state = situation()
    point = state['quest_locations'][0]['world_position']
    if bad == 'no_location': state['quest_locations'] = []
    if bad == 'far_player': state['player_world_position']['x'] += 50
    if bad == 'far_npc': state['packet_entities'][GUID]['position']['x'] += 50
    if bad == 'wrong_floor': point.update(z=380., z_known=True)
    if bad == 'wrong_world': point['instance_id'] = 2175
    if bad == 'wrong_ui_map': state['quest_locations'][0]['map_id'] = 1409
    if bad == 'two_live_points':
        other = deepcopy(state['quest_locations'][0]);other['world_position']['x'] += 3
        state['quest_locations'].append(other)
    if bad == 'turnin_only': state['quest_locations'][0]['role'] = 'TURN_IN'
    if bad == 'unaccepted_task': state['quest_locations'][0]['source'] = 'TASK_QUEST_POI'
    if bad == 'other_objective_point': state['quest_locations'][0]['objective_id'] = 999
    if bad == 'other_quest_point': state['quest_locations'][0]['quest_id'] = 999
    if bad == 'no_quest_identity':
        state.pop('quest_text');reference(state)['quest_roles'] = []
    if bad == 'explicit_other_npc':
        state['active_quests'][0]['objectives'][0]['target_entity'] = {'npc_id': 999}
    assert conversation_actors(state, 65803) == []


@pytest.mark.parametrize('mechanism', ['KILL', 'COLLECT', 'USE_ITEM', 'CREDIT_OBJECT', 'WITNESS', 'ESCORT'])
def test_existing_combat_collect_use_and_scripted_event_handlers_are_not_replaced(mechanism):
    state = situation()
    reference(state)['objectives'][0]['mechanism'] = mechanism
    assert conversation_actors(state, 65803) == []


def test_broad_blue_polygon_is_not_a_local_npc_meeting_point():
    state = situation()
    reference(state)['pois'] = [{'poi_id': '65803:0:1', 'objective_id': 423553,
        'objective_index': 0, 'world_map_id': 2444, 'ui_map_id': 2023,
        'points': [{'x': 224., 'y': 522.}, {'x': 260., 'y': 522.}, {'x': 260., 'y': 550.}]}]
    assert conversation_actors(state, 65803) == []


def test_a_multi_point_group_without_objective_rows_is_not_reduced_to_its_api_centre():
    state = situation()
    state['active_quests'][0]['objectives'][0]['type'] = 'REACH_AREA'
    reference(state)['objectives'] = []
    reference(state)['pois'] = [{'poi_id': '65803:0:1', 'objective_index': 0,
        'world_map_id': 2444, 'ui_map_id': 2023,
        'points': [{'x': 224., 'y': 522.}, {'x': 260., 'y': 522.}, {'x': 260., 'y': 550.}]}]
    assert conversation_actors(state, 65803) == []


def test_normalized_map_coordinates_without_a_world_conversion_are_not_a_local_point():
    state = situation()
    state['quest_locations'][0].pop('world_position')
    state['quest_locations'][0].update(x=.5, y=.5, coordinate_space='NORMALIZED_MAP')
    assert conversation_actors(state, 65803) == []


def test_contextual_trial_uses_existing_option_memory_and_never_equates_opening_with_credit():
    state, memory = situation(), QuestAttemptMemory()
    option = {'id': 77, 'name': 'I am ready.', 'icon': 132053, 'available': True, 'x': .1, 'y': .7}
    state['quest_ui'] = {'open': True, 'npc_guid': GUID, 'gossip_options': [option]}
    proposal = Dialog._talk_gossip(state, True, memory)
    assert proposal.parameters['gossip_trial'] is True
    terminal(memory, state, proposal)
    blocked = Dialog._talk_gossip(state, True, memory)
    assert blocked.parameters['reason'] == 'quest_gossip_options_exhausted'


def test_a_paid_single_row_is_not_an_ordinary_contextual_chat_trial():
    state = situation()
    state['quest_ui'] = {'open': True, 'npc_guid': GUID, 'gossip_options': [
        {'id': 77, 'name': 'I am ready.', 'icon': 132053, 'available': True, 'x': .1, 'y': .7, 'cost': 100}]}
    assert Dialog._talk_gossip(state, True, QuestAttemptMemory()) is None


def test_shared_planner_uses_the_contextual_trial_without_hover_or_new_owners():
    state = situation()
    state['is_mounted'] = True
    state['flight']['can_glide'] = True
    world = WorldModel()
    world.ingest(Observation.create(state, 100.))
    world.state.update(state)
    proposals = Planner(SkillRegistry()).candidates(Goal.parse('Questelj', 1.), world, 100.)
    assert proposals[0].skill == 'DISMOUNT'
    assert any(p.skill == 'INTERACT' and p.parameters['soft_guid'] == GUID for p in proposals)
