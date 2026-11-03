"""22:00 user-run Toward the City: already in front of Tomul, then WAIT.

The objective names a meeting place; same-quest prose names its speaker as
'me'. Neither POI arrival nor opening gossip counts as objective credit.
"""
from copy import deepcopy

import pytest

from wowbot.agent.conversation_actors import conversation_actors
from wowbot.agent.models import Goal, Observation
from wowbot.agent.packet_entity_facts import kill_objective_entries
from wowbot.agent.planner import Planner
from wowbot.agent.quest_attempt_memory import QuestAttemptMemory
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, objective_npc_entries
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from test_m0_combat_loot_skills import active
from test_travel_mode_20261020 import favorite_mount

GUID = 'Creature-0-1463-2444-79-185882-0000616836'
GIVER = 'Creature-0-1463-2444-79-185882-0000E16829'
DESCRIPTION = "When you are ready to leave, find me at the caravan. Don't keep us waiting."


def live(mounted=False):
    return {'session_id': 'caravan:player', 'monotonic_time': 100., 'state_age': .2,
        'map_id': 2023, 'orientation': 1.98, 'is_mounted': mounted,
        'player_world_position': {'instance_id': 2444, 'x': 224.176, 'y': 519.494,
                                  'z': 339.443, 'z_known': True, 'z_observed': True},
        'quest_text': {'quest_id': 65803, 'description': DESCRIPTION,
                       'giver_guid': GIVER, 'giver_name': 'Scout Tomul'},
        'active_quests': [{'quest_id': 65803, 'title': 'Toward the City', 'is_campaign': True,
            'is_complete': False, 'objectives': [{'description': '0/1 Meet with the caravan',
                'type': 'KILL', 'raw_type': 'monster', 'current': 0, 'required': 1, 'is_complete': False}]}],
        'reference_knowledge': {'quests': {'65803': {'description': None, 'quest_roles': [
            {'npc_id': 185882, 'name': 'Scout Tomul', 'role': 'QUEST_ENDER'}], 'objectives': [
                {'objective_id': 423553, 'description': 'Meet with the caravan',
                 'credit_object_id': 190702, 'credit_kind': 'CREATURE_CREDIT',
                 'credit_name': '[DNT] Kill Credit: Meet with the Caravan', 'mechanism': 'ARRIVE'}]}}},
        'packet_entities': {GUID: {'guid': GUID, 'entry_id': 185882, 'kind': 'CREATURE', 'map_id': 2444,
            'info': {'npc_flags': 1, 'sampled_at': 99.}, 'position': {'x': 223.609, 'y': 522.201,
                'z': 339.656, 'source': 'PACKET_CREATE_MOVEMENT', 'age': .2}}},
        'target': {'guid': GUID, 'npc_id': 185882, 'name': 'Scout Tomul', 'attackable': False, 'dead': False},
        'target_sample_time': 100., 'soft_targets_sample_time': 100.,
        'soft_targets': [{'source_unit': 'softinteract', 'guid': GUID}], 'quest_ui': {'open': False},
        'movement': {'indoors': False, 'moving': False, 'flying': False},
        'flight': {'advanced_flyable_area': True, 'can_glide': mounted},
        'actionbar': [favorite_mount()], 'server_mode': {'active': True}}


def test_the_current_quest_speaker_is_resolved_instead_of_an_npc_named_caravan():
    state = live()
    assert [a['entry'] for a in conversation_actors(state, 65803)] == [185882]
    assert objective_npc_entries(state) == {'185882': '65803'}
    (interact,) = ServerNpcInteractionPolicy().propose(state)
    assert interact.skill == 'INTERACT' and interact.parameters['soft_guid'] == GUID
    assert interact.parameters['quest_id'] == '65803'
    assert '185882' not in kill_objective_entries(state)
    assert state['reference_knowledge']['quests']['65803']['objectives'][0]['mechanism'] == 'ARRIVE'


def test_shared_planner_dismounts_then_interacts_instead_of_another_mount_or_wait():
    state = live(mounted=True)
    world = WorldModel()
    world.ingest(Observation.create(state, 100.))
    world.state.update(state)
    proposals = Planner(SkillRegistry()).candidates(Goal.parse('Questelj', 1.), world, 100.)
    assert proposals[0].skill == 'DISMOUNT'
    assert proposals[0].parameters['for_skill'] == 'INTERACT'
    assert any(p.skill == 'INTERACT' and p.parameters['soft_guid'] == GUID for p in proposals)


def test_recording_agent_runs_dismount_interact_and_the_owned_ready_row_in_order():
    from test_agent_core import agent
    bot, executor = agent('Questelj')
    state = live(mounted=True)
    bot.tick(state, 100.)
    assert bot.pending.proposal.skill == 'DISMOUNT'
    state = live(mounted=False)
    state.update(monotonic_time=101., target_sample_time=101., soft_targets_sample_time=101.)
    bot.tick(state, 101.)
    assert bot.pending.proposal.skill == 'INTERACT'
    assert executor.commands[-1].binding == 'INTERACTTARGET'
    option = {'id': 77, 'name': 'I am ready.', 'icon': 132053, 'available': True, 'x': .1, 'y': .7}
    state.update(monotonic_time=102., target_sample_time=102., soft_targets_sample_time=102.,
                 quest_ui={'open': True, 'npc_guid': GUID, 'gossip_options': [option]})
    bot.tick(state, 102.)
    assert bot.pending.proposal.skill == 'QUEST_DIALOG'
    assert bot.pending.proposal.parameters['target_guid'] == GUID
    assert executor.commands[-1].kind == 'CLICK'


def test_opened_speaker_can_select_ready_but_only_real_quest_progress_verifies_it():
    state = live()
    option = {'id': 77, 'name': 'I am ready.', 'icon': 132053, 'available': True, 'x': .1, 'y': .7}
    state['quest_ui'] = {'open': True, 'npc_guid': GUID, 'gossip_options': [option]}
    proposal = QuestDialogPlanningPolicy._talk_gossip(state, True, QuestAttemptMemory())
    assert proposal.parameters['target_guid'] == GUID
    assert proposal.parameters['gossip_option_id'] == 77
    skill = QuestDialogSkill()
    context = active('QUEST_DIALOG', proposal.parameters, state)
    assert [c.kind for c in skill.begin(context, state).commands] == ['CLICK']
    closed = deepcopy(state)
    closed['quest_ui'] = {'open': False}
    assert skill.verify(context, closed, 2.).status is SkillStatus.RUNNING
    closed['active_quests'][0]['objectives'][0].update(current=1, is_complete=True)
    assert skill.verify(context, closed, 3.).status is SkillStatus.SUCCESS


@pytest.mark.parametrize('bad', ['other_quest_text', 'no_speaker_instruction', 'other_place',
    'done', 'quest_done', 'removed', 'wrong_map', 'not_talkable', 'contradictory_guid_entry',
    'explicit_other_npc', 'explicit_other_guid', 'invalid_giver'])
def test_a_first_person_hint_does_not_override_missing_or_conflicting_current_evidence(bad):
    state = live()
    objective = state['active_quests'][0]['objectives'][0]
    unit = state['packet_entities'][GUID]
    if bad == 'other_quest_text': state['quest_text']['quest_id'] = 999
    if bad == 'no_speaker_instruction': state['quest_text']['description'] = 'Return to me after your task.'
    if bad == 'other_place': state['quest_text']['description'] = 'Find me at the forge.'
    if bad == 'done': objective['is_complete'] = True
    if bad == 'quest_done': state['active_quests'][0]['is_complete'] = True
    if bad == 'removed': unit['removed'] = True
    if bad == 'wrong_map': unit['map_id'] = 2175
    if bad == 'not_talkable': unit['info']['npc_flags'] = 0
    if bad == 'contradictory_guid_entry': unit['entry_id'] = 999
    if bad == 'explicit_other_npc': objective['target_entity'] = {'npc_id': 999}
    if bad == 'explicit_other_guid': objective['target_entity'] = {'guid': GIVER}
    if bad == 'invalid_giver': state['quest_text']['giver_guid'] = 'WORLD3D:185882'
    assert conversation_actors(state, 65803) == []
    assert '185882' not in objective_npc_entries(state)


def test_live_speaker_template_outranks_a_stale_static_role_but_never_transfers_its_guid():
    state = live()
    state['reference_knowledge']['quests']['65803']['quest_roles'] = [
        {'npc_id': 999, 'name': 'Old Scout', 'role': 'QUEST_ENDER'}]
    (interact,) = ServerNpcInteractionPolicy().propose(state)
    assert interact.parameters['soft_guid'] == GUID and GUID != GIVER
    state['soft_targets'][0]['guid'] = GIVER
    assert not any(p.skill == 'INTERACT' for p in ServerNpcInteractionPolicy().propose(state))


def test_static_speaker_requires_a_matching_place_clause_and_one_known_role_name():
    state = live()
    state.pop('quest_text')
    reference = state['reference_knowledge']['quests']['65803']
    reference['description'] = DESCRIPTION
    assert [a['entry'] for a in conversation_actors(state, 65803)] == [185882]
    reference['quest_roles'].append({'npc_id': 999, 'name': 'Another Speaker'})
    assert conversation_actors(state, 65803) == []


def test_after_the_meeting_credit_the_next_story_stage_does_not_restart_this_conversation():
    state = live()
    state['active_quests'][0]['objectives'][0]['description'] = '0/1 Listen to the Shikaar stories'
    assert conversation_actors(state, 65803) == []
