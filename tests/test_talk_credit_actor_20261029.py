"""TDB type 3 identifies the real talk recipient, without name heuristics."""
from copy import deepcopy

import pytest

from wowbot.agent.packet_entity_facts import kill_objective_relations
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, objective_npc_entries


def state():
    guid = 'Creature-0-1463-2444-79-185179-0000616833'
    return {
        'session_id': 'talk-test', 'monotonic_time': 100., 'orientation': 0., 'map_id': 2023,
        'soft_targets_sample_time': 100., 'movement': {'moving': False},
        'player_world_position': {'x': 0., 'y': 0., 'z': 10., 'z_observed': True, 'instance_id': 2444},
        'active_quests': [{'quest_id': 72429, 'is_accepted': True, 'is_complete': False, 'objectives': [
            {'description': '0/1 Keeper of Renown', 'raw_type': 'monster', 'type': 'KILL',
             'current': 0, 'required': 1, 'is_complete': False},
            {'description': '0/1 Renown Quartermaster', 'raw_type': 'monster', 'type': 'KILL',
             'current': 0, 'required': 1, 'is_complete': False}]}],
        'reference_knowledge': {'quests': {'72429': {'objectives': [
            {'order': 0, 'objective_id': 431950, 'raw_type': 3, 'credit_kind': 'TALK_CREDIT',
             'credit_object_id': 185179, 'description': 'Keeper of Renown', 'mechanism': 'TALK'},
            {'order': 1, 'objective_id': 431951, 'raw_type': 3, 'credit_kind': 'TALK_CREDIT',
             'credit_object_id': 196707, 'description': 'Renown Quartermaster', 'mechanism': 'TALK'}]}}},
        'packet_entities': {guid: {'guid': guid, 'entry_id': 185179, 'kind': 'CREATURE', 'map_id': 2444,
            'info': {'npc_flags': 3}, 'position': {'x': 3., 'y': 0., 'z': 10.}}},
        'soft_targets': [{'guid': guid, 'npc_id': 185179, 'source_unit': 'softinteract',
                          'is_attackable': False, 'is_dead': False}]}


def test_explicit_talk_credit_id_reaches_the_common_interaction_without_a_creature_name_list():
    current = state()
    assert objective_npc_entries(current) == {'185179': '72429', '196707': '72429'}
    assert kill_objective_relations(current) == {}
    proposal, = ServerNpcInteractionPolicy().propose(current)
    assert proposal.skill == 'INTERACT'
    assert proposal.parameters['npc_id'] == 185179
    assert proposal.parameters['soft_guid'] == current['soft_targets'][0]['guid']


@pytest.mark.parametrize('change', ['completed', 'quest_done', 'unaccepted', 'wrong_id', 'wrong_text'])
def test_talk_credit_does_not_override_completion_or_a_contradictory_objective_binding(change):
    current = state()
    quest = current['active_quests'][0]
    if change == 'completed': quest['objectives'][0]['is_complete'] = True
    elif change == 'quest_done': quest['is_complete'] = True
    elif change == 'unaccepted': quest['is_accepted'] = False
    elif change == 'wrong_id': quest['objectives'][0]['target_entity'] = {'npc_id': 999}
    else: quest['objectives'][0]['description'] = '0/1 Another person'
    assert '185179' not in objective_npc_entries(current)


def test_talk_credit_works_for_other_quest_and_npc_ids_and_blank_ordered_rows():
    current = state()
    current['active_quests'][0]['quest_id'] = 90001
    ref = current['reference_knowledge']['quests'].pop('72429')
    current['reference_knowledge']['quests']['90001'] = ref
    for row in ref['objectives']:
        row['credit_object_id'] += 100
        row['description'] = ''
    assert objective_npc_entries(current) == {'185279': '90001', '196807': '90001'}
