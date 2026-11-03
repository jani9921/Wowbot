"""User-run 20:43/20:46 menus and bounded alternatives after no credit.

The user chose the original ready row manually; that is not agent success.
"""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from wowbot.agent.gossip_topics import self_introduction_option
from wowbot.agent.gossip_trials import scope
from wowbot.agent.models import Goal, Outcome
from wowbot.agent.quest_attempt_memory import QuestAttemptMemory
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy as Policy
from wowbot.agent.quest_terminal import QuestTerminalProcessor
from wowbot.skills.quest_dialog import QuestDialogSkill
from wowbot.runtime import SkillStatus
from wowbot.verification.quest import QuestProgressVerifier
from test_m0_combat_loot_skills import active
from test_talk_ride_credits_20261021 import unit


def row(identifier, text, **extra):
    return {'id': identifier, 'name': text, 'icon': 132053, 'available': True,
            'x': .076338636591248, 'y': .79776402153781, **extra}


def live(actor=186183):
    name = 'Beastmaster Nuqut' if actor == 186183 else 'Ohn Seshteng'
    guid = f'Creature-0-1463-2444-79-{actor}-0000616829'
    objective = {'objective_id': 423460 if actor == 186183 else 423447,
                 'description': f'Speak to {name}', 'credit_action': 'TALK', 'mechanism': 'TALK',
                 'talk_creatures': [{'entry': actor, 'name': name}]}
    options = ([row(55228, 'I am Cxvcxjk. Will you be joining the caravan to the Khural?'),
                row(55230, "I'm looking for a lost companion.", icon=132060)] if actor == 186183 else
               [row(54838, 'I am Cxvcxjk. I will be joining your clan for the Khural.'),
                row(54839, "Are you of Clan Shikaar or Ohn'ir?")])
    return {'monotonic_time': 100., 'state_age': .3, 'session_id': 'test:player',
            'character_name': 'Cxvcxjk', 'map_id': 2023,
            'player_world_position': {'x': 0., 'y': 0., 'z': 91., 'instance_id': 2444},
            'packet_entities': {guid: unit(guid, 3., 0., 3)}, 'target': False,
            'active_quests': [{'quest_id': 65801, 'is_complete': False, 'objectives': [
                {'description': '0/1 '+objective['description'], 'current': 0, 'required': 1,
                 'is_complete': False, 'mechanism': 'TALK'}]}],
            'reference_knowledge': {'quests': {'65801': {'title': 'Making Introductions',
                'description': 'Introduce yourself to the members of my clan.', 'objectives': [objective]}}},
            'quest_ui': {'open': True, 'action': '', 'npc_guid': guid, 'quest_id': 0, 'gossip_options': options}}


def terminal(memory, state, proposal, *, action_id='trial:1', reason='expected_state_not_reached', no_click=False):
    skill = QuestDialogSkill()
    context = active('QUEST_DIALOG', proposal.parameters, state)
    begun = skill.begin(context, state)
    assert begun.status is SkillStatus.RUNNING
    assert skill.verify(context, state, 2.).status is SkillStatus.RUNNING
    assert skill.verify(context, state, 9.).status is SkillStatus.FAILURE
    attempt = replace(context.attempt, action_id=action_id, commands=() if no_click else tuple(begun.commands))
    domain = SimpleNamespace(attempt_memory=memory, credit_escalation=None)
    runtime = SimpleNamespace(record_failure=lambda **kw: None, record_success=lambda **kw: None)
    processor = QuestTerminalProcessor(QuestProgressVerifier(), runtime, domain)
    return processor.process(attempt, Outcome.FAILURE, reason, state, Goal.parse('Questelj', 1.), 9.)


@pytest.mark.parametrize('actor,expected', [(186183, 55228), (184595, 54838)])
def test_own_name_introduction_is_selected_and_only_credit_verifies_it(actor, expected):
    state = live(actor)
    proposal = Policy._talk_gossip(state, True)
    assert proposal.parameters['gossip_option_id'] == expected
    assert proposal.parameters['gossip_selection_basis'] == 'QUEST_SELF_INTRODUCTION'
    skill = QuestDialogSkill()
    context = active('QUEST_DIALOG', proposal.parameters, state)
    assert skill.begin(context, state).commands[0].kind == 'CLICK'
    closed = deepcopy(state)
    closed['quest_ui'] = {'open': False}
    assert skill.verify(context, closed, 2.).status is SkillStatus.RUNNING
    closed['active_quests'][0]['objectives'][0].update(current=1, is_complete=True)
    assert skill.verify(context, closed, 3.).status is SkillStatus.SUCCESS


@pytest.mark.parametrize('text', ['I am Cxvcxjk.', "I'm Cxvcxjk.", 'I\u2019m Cxvcxjk!', 'My name is Cxvcxjk.'])
def test_self_name_boundary_accepts_punctuation_and_contractions(text):
    state = live()
    state['quest_ui']['gossip_options'][0]['name'] = text
    assert Policy._talk_gossip(state, True).parameters['gossip_selection_basis'] == 'QUEST_SELF_INTRODUCTION'


@pytest.mark.parametrize('extra', [{'name': 'I am Anotherplayer.'}, {'name': 'I am Cxvcxjkz.'},
    {'cost': 1}, {'confirm': 'Confirm?'}, {'quest_id': 999}])
def test_self_introduction_does_not_guess_names_or_admit_unsafe_rows(extra):
    state = live()
    state['quest_ui']['gossip_options'][0].update(extra)
    refs = state['reference_knowledge']['quests']
    assert self_introduction_option([(65801, refs['65801']['objectives'][0])],
        state['quest_ui']['gossip_options'], refs, 'Cxvcxjk') is None


def test_ready_then_another_row_after_a_dispatched_click_has_no_credit():
    state, memory = live(), QuestAttemptMemory()
    state['quest_ui']['gossip_options'] = [row(1, 'Let us begin the journey.'), row(2, 'I am ready.')]
    first = Policy._talk_gossip(state, True, memory)
    assert first.parameters['gossip_option_id'] == 2
    assert first.parameters['gossip_selection_basis'] == 'BOUNDED_QUEST_GOSSIP_TRIAL'
    result = terminal(memory, state, first)
    event = next(data for name, data in result.events if name == 'QUEST_GOSSIP_TRIAL')
    assert event['option_id'] == '2' and not event['quest_credit']
    state['monotonic_time'] += 10
    state['quest_ui']['gossip_options'].reverse()
    state['quest_ui']['gossip_options'][0]['y'] = .6
    second = Policy._talk_gossip(state, True, memory)
    assert second.parameters['gossip_option_id'] == 1
    terminal(memory, state, second, action_id='trial:2')
    stopped = Policy._talk_gossip(state, True, memory)
    assert stopped.skill == 'WAIT' and stopped.parameters['reason'] == 'quest_gossip_options_exhausted'


@pytest.mark.parametrize('bad', ['no_click', 'identity_lost'])
def test_preflight_or_dispatch_problem_does_not_condemn_a_row(bad):
    state, memory = live(), QuestAttemptMemory()
    proposal = Policy._talk_gossip(state, True, memory)
    result = terminal(memory, state, proposal, no_click=bad == 'no_click',
                      reason='wrong_quest_ui' if bad == 'identity_lost' else 'expected_state_not_reached')
    assert not any(name == 'QUEST_GOSSIP_TRIAL' for name, _ in result.events)
    assert Policy._talk_gossip(state, True, memory).parameters['gossip_option_id'] == 55228


def test_a_price_or_confirmation_appearing_after_planning_stops_the_trial_click():
    state = live()
    state['quest_ui']['gossip_options'] = [row(1, 'First story.'), row(2, 'I am ready.')]
    proposal = Policy._talk_gossip(state, True, QuestAttemptMemory())
    state['quest_ui']['gossip_options'][1]['cost'] = 100
    context = active('QUEST_DIALOG', proposal.parameters, state)
    result = QuestDialogSkill().begin(context, state)
    assert result.status is SkillStatus.FAILURE and not result.commands


def test_no_credit_does_not_authorize_the_remaining_row_of_another_explicit_quest():
    state, memory = live(), QuestAttemptMemory()
    state['quest_ui']['gossip_options'] = [row(1, 'I am ready.'), row(2, 'Other quest.', quest_id=999)]
    first = Policy._talk_gossip(state, True, memory)
    terminal(memory, state, first)
    assert Policy._talk_gossip(state, True, memory).parameters['reason'] == 'quest_gossip_options_exhausted'


@pytest.mark.parametrize('change', ['session', 'instance', 'menu', 'progress'])
def test_real_context_changes_allow_new_trials_but_screen_coordinates_do_not(change):
    state = live()
    old = scope(state, 65801, state['quest_ui']['npc_guid'])
    state['quest_ui']['gossip_options'][0]['x'] = .12
    assert scope(state, 65801, state['quest_ui']['npc_guid']) == old
    if change == 'session': state['session_id'] = 'new:player'
    if change == 'instance': state['player_world_position']['instance_id'] = 1
    if change == 'menu': state['quest_ui']['gossip_options'][0]['name'] = 'Next stage'
    if change == 'progress': state['active_quests'][0]['objectives'][0]['current'] = 1
    assert scope(state, 65801, state['quest_ui']['npc_guid']) != old


def test_exploration_is_bounded_and_does_not_try_other_services():
    state, memory = live(), QuestAttemptMemory()
    state['quest_ui']['gossip_options'] = [row(i, f'Tell me story {i}.') for i in range(1, 6)]
    state['quest_ui']['gossip_options'] += [row(20, 'Purchase a service.', cost=100),
        row(21, 'Confirm a service.', confirm='Sure?'), row(22, 'Vendor', icon=132060)]
    for i in range(1, 5):
        proposal = Policy._talk_gossip(state, True, memory)
        assert proposal.parameters['gossip_option_id'] == i
        terminal(memory, state, proposal, action_id=f'trial:{i}')
    assert Policy._talk_gossip(state, True, memory).parameters['reason'] == 'quest_gossip_options_exhausted'


def test_exact_actor_is_required_before_trying_unmarked_rows():
    state = live()
    state['quest_ui']['npc_guid'] = 'Creature-0-1463-2444-79-999-0000616829'
    assert Policy._talk_gossip(state, True, QuestAttemptMemory()) is None


def test_one_row_for_the_quest_speaker_is_tried_even_when_the_objective_names_an_event():
    from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
    from wowbot.agent.quest_planning import QuestDomain
    actor = 185905
    def rows(query, params):
        if 'WHERE name=' in query:
            return [{'entry': actor, 'name': 'Alexstrasza the Life-Binder'}]
        if 'WHERE entry=' in query:
            return [{'name': 'Kill Credit: Ruby Oathstone Empowered [DNT]'}]
        return []
    catalog = SimpleNamespace(raw=SimpleNamespace(tables={'creature_template'}, rows=rows),
        quest=lambda _: {'quest_id': 65794, 'template': {'VerifiedBuild': 69497},
            'description': 'Speak with me when you are ready to bring the eggs.',
            'quest_roles': [{'npc_id': 193377, 'name': 'Alexstrasza the Life-Binder', 'role': 'QUEST_ENDER'}],
            'objectives': [{'objective_id': 423377, 'raw_type': 0, 'credit_object_id': 185906,
                            'description': 'Ruby Oathstone empowered'}]})
    ref = TDBKnowledgeProvider(catalog).quest(65794)
    assert ref['conversation_speakers'] == [{'entry': actor, 'name': 'Alexstrasza the Life-Binder'}]
    state = live()
    guid = 'Creature-0-1463-2444-47-185905-0000616818'
    state['active_quests'] = [{'quest_id': 65794, 'is_complete': False, 'objectives': [
        {'description': '0/1 Ruby Oathstone empowered', 'current': 0, 'required': 1, 'is_complete': False}]}]
    state['quest_ui'].update(npc_guid=guid, gossip_options=[row(55380, '|cFF0000FF(Quest)|r I am ready.',
                                                             quest_label_prepend=False)])
    state['quest_ui'].update(action='GOSSIP_OPTION_SELECT', gossip_option={
        k: v for k, v in state['quest_ui']['gossip_options'][0].items() if k not in {'icon', 'available'}})
    state['packet_entities'] = {guid: unit(guid, 3., 0., 3)}
    state['reference_knowledge'] = {'quests': {'65794': ref}}
    memory = QuestAttemptMemory()
    chosen = Policy._talk_gossip(state, True, memory)
    assert chosen.parameters['gossip_option_id'] == 55380
    assert chosen.parameters['gossip_selection_basis'] == 'SINGLE_ROW_OBJECTIVE_ACTOR'
    terminal(memory, state, chosen)
    assert Policy._talk_gossip(state, True, memory).parameters['reason'] == 'quest_gossip_options_exhausted'
    # A different NPC cannot inherit a matching speaker's permission.
    state['quest_ui']['npc_guid'] = live()['quest_ui']['npc_guid']
    assert Policy._talk_gossip(state, True, memory) is None


def test_shared_planner_enables_trials_without_a_second_controller():
    from wowbot.agent.models import Observation
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    state = live()
    state['quest_ui']['gossip_options'] = [row(1, 'Let us begin.'), row(2, 'I am ready.')]
    world = WorldModel()
    world.ingest(Observation.create(state, 100.))
    world.state.update(state)
    proposals = Planner(SkillRegistry()).candidates(Goal.parse('Questelj', 1.), world, 100.)
    assert proposals[0].skill == 'QUEST_DIALOG'
    assert proposals[0].parameters['gossip_option_id'] == 2
