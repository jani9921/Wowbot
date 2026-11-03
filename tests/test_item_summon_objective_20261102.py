"""It's Alive! regression: original actor != summoned boarding-credit actor.

Synthetic DB2/TDB rows reproduce the observed data, without client input or
accessing any installed catalogue/memory database.
"""
from copy import deepcopy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from test_itemeffect_supplement_20261027 import builder
from wowbot.agent.models import Attempt, Goal, Observation, Prediction
from wowbot.agent.quest_item_knowledge import annotate_items
from wowbot.agent.quest_model import QuestModel
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from wowbot.agent.world import WorldModel
from wowbot.quests.client_supplement import ClientSupplement
from wowbot.quests.item_target_conditions import spell_target_entries
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills.quest_item import UseItemSkill
from wowbot.skills.target import TargetSkill


GUID = 'Creature-0-1-0-1-42381-0000000001'
CONDITION = dict(SourceTypeOrReferenceId=13, SourceEntry=79436, SourceGroup=2,
                 SourceId=0, ElseGroup=0, ConditionTypeOrReference=31,
                 ConditionTarget=0, ConditionValue1=3, ConditionValue2=42381,
                 ConditionValue3=0, ConditionStringValue1='', NegativeCondition=0,
                 ScriptName='')


class Raw:
    tables = {'conditions'}

    def __init__(self, rows):
        self.values = rows

    def rows(self, sql, parameters):
        assert parameters == (79436,) and 'SourceTypeOrReferenceId=13' in sql
        return deepcopy(self.values[:2])


def targets(rows):
    provider = TDBKnowledgeProvider(SimpleNamespace(raw=Raw(rows)))
    return lambda spell: spell_target_entries(provider, spell)


@pytest.fixture
def supplement(tmp_path):
    path = tmp_path/'supplement.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(builder.SCHEMA)
        db.execute('PRAGMA user_version=1')
        db.execute("INSERT INTO items VALUES (57954,'Harvest Watcher Heart','',0)")
        db.execute('INSERT INTO item_effects VALUES (12174,79436,0,0,0,0,10000,1149,0,0)')
        db.execute('INSERT INTO item_effect_links VALUES (11606,57954,12174)')
        db.execute('INSERT INTO spell_effects VALUES (78943,79436,0,77,0,0,0,0,25,0)')
        db.execute('INSERT INTO spell_effects VALUES (78944,79436,0,28,0,0,42601,0,46,0)')
        for key, index in ((78943, 0), (78944, 1)):
            db.execute('INSERT INTO db2_rows VALUES (?,?,?)',
                       ('SpellEffect', key, json.dumps({'EffectIndex': index})))
    return ClientSupplement(path)


def reference(supplement, conditions=None):
    result = {'quest_id': 26257, 'items': {'start_item_id': 57954}, 'objectives': [
        {'objective_id': 256435, 'order': 0, 'raw_type': 0,
         'credit_kind': 'CREATURE_CREDIT', 'credit_object_id': 42601,
         'credit_name': 'Overloaded Harvest Golem',
         'description': 'Overloaded Harvest Golem enabled',
         'named_creatures': [{'entry': 42381, 'name': 'Overloaded Harvest Golem'}]},
        {'objective_id': 256436, 'order': 1, 'raw_type': 0,
         'credit_kind': 'CREATURE_CREDIT', 'credit_object_id': 42342,
         'credit_name': 'Energized Harvest Reaper', 'description': 'Reapers slain'},
    ]}
    annotate_items(result, supplement, spell_targets=targets(
        [CONDITION] if conditions is None else conditions))
    return {'quests': {'26257': result}}


def state(supplement, *, distance=2., selected=False):
    point = {'x': distance, 'y': 0., 'z': 20., 'source': 'PACKET_CREATE_MOVEMENT', 'age': 0.}
    return {'session_id': 'test:golem', 'frame_id': 'golem:1', 'timestamp': 10.,
            'monotonic_time': 10., 'player_present': True, 'world_map_open': False,
            'map_id': 52, 'orientation': 0.,
            'player_world_position': {'x': 0., 'y': 0., 'z': 20., 'instance_id': 0,
                                      'z_known': True, 'z_observed': True,
                                      'coordinate_space': 'WORLD_YARDS'},
            'active_quests': [{'quest_id': 26257, 'is_complete': False,
                'special_item': {'item_id': 57954}, 'objectives': [
                    {'type': 'KILL', 'raw_type': 'monster', 'current': 0, 'required': 1,
                     'description': '0/1 Overloaded Harvest Golem enabled'},
                    {'type': 'KILL', 'raw_type': 'monster', 'current': 25, 'required': 25,
                     'is_complete': True, 'description': '25/25 Reapers slain'}]}],
            'reference_knowledge': reference(supplement),
            'inventory': {'items': [{'item_id': 57954, 'bag': 2, 'slot': 4}]},
            'packet_entities': {GUID: {'guid': GUID, 'entry_id': 42381, 'kind': 'CREATURE',
                                      'map_id': 0, 'position': point}},
            'target': ({'guid': GUID, 'npc_id': 42381, 'attackable': False, 'dead': False}
                       if selected else False), 'target_sample_time': 10.,
            'server_mode': {'selected': True, 'active': True, 'enabled': True},
            'actionbar': [{'action': 'ACTIONBUTTON7', 'kind': 'item', 'id': 57954,
                           'is_usable': True, 'in_range': True, 'cooldown_remaining': 0.}]}


def world(value):
    result = WorldModel()
    now = value['monotonic_time']
    result.ingest(Observation.create(value, now))
    result.ingest(Observation.create({'session_id': value['session_id'],
        'reference_knowledge': value['reference_knowledge']}, now, source='REFERENCE_MEMORY'))
    return result


class Bindings:
    def contains(self, action):
        return action in {'ACTIONBUTTON7', 'TARGETNEARESTFRIEND', 'TARGETNEARESTENEMY',
                          'MOVEFORWARD', 'TURNLEFT', 'TURNRIGHT'}


def running(proposal, value):
    prediction = Prediction('p', 'use', 'credit', 10., 5., 'obs')
    attempt = Attempt('use', proposal, value, 'obs', 10., 15., (), prediction)
    return ActiveSkillRuntime().start(intent=Intent(proposal.skill, proposal.parameters,
        proposal.parameters.get('guid'), '26257:0'), attempt=attempt, now=10., before_snapshot=value)


def test_summon_relation_binds_original_subject_not_new_vehicle(supplement):
    value = state(supplement)
    use = supplement.item(57954)['uses'][0]
    assert use['summoned_creatures'] == [{'entry': 42601, 'effect_mask': 2}]
    assert use['credit_links'] == []  # summon metadata never fabricates earned credit
    model = world(value).quest_model
    objective = model.records[26257].objectives[0]
    assert objective.type == 'USE_ITEM_ON_TARGET'
    assert objective.target_entity['npc_id'] == 42381
    assert objective.current_count == 0
    assert model.records[26257].objectives[1].type == 'KILL'
    model.apply_reference_knowledge({})
    assert objective.type == 'KILL' and objective.target_object is None


@pytest.mark.parametrize('change', [
    {'SourceGroup': 1}, {'NegativeCondition': 1}, {'ConditionTarget': 1},
    {'ConditionTypeOrReference': -7}, {'ElseGroup': 1}, {'SourceId': 1},
    {'ScriptName': 'unknown'}, {'ConditionValue3': 9},
])
def test_unproven_or_wrong_effect_conditions_never_enable_item_branch(supplement, change):
    ref = reference(supplement, [{**CONDITION, **change}])
    assert ref['quests']['26257']['objectives'][0]['item_uses'] == []


def test_no_condition_or_alternative_targets_are_not_guessed(supplement):
    for rows in ([], [CONDITION, {**CONDITION, 'ConditionValue2': 999}]):
        assert reference(supplement, rows)['quests']['26257']['objectives'][0]['item_uses'] == []


@pytest.mark.parametrize('distance,selected,expected', [(12., False, 'MOVE'),
                                                     (2., False, 'TARGET'),
                                                     (2., True, 'ASSIST')])
def test_real_domain_and_registry_move_select_then_use_without_vision(supplement, distance, selected, expected):
    value = state(supplement, distance=distance, selected=selected)
    model = world(value)
    candidates = QuestDomain().propose(model, Goal.parse('Questelj', 10.))
    chosen = next(p for p in candidates if p.skill == expected and p.parameters.get('item_id') == 57954)
    assert chosen.parameters.get('guid', chosen.parameters.get('server_entity_guid')) == GUID
    assert SkillRegistry(bindings=Bindings()).available(chosen, model)
    assert not [p for p in candidates if p.skill in {'SEEK_VISUAL_CUE', 'VISUAL_APPROACH', 'COMBAT'}]
    if expected == 'TARGET':
        active = running(chosen, value)
        assert TargetSkill().begin(active, value).commands[0].binding == 'TARGETNEARESTFRIEND'
    if expected == 'ASSIST':
        skill = UseItemSkill(Bindings())
        active = running(chosen, value)
        assert skill.begin(active, value).commands[0].binding == 'ACTIONBUTTON7'
        assert skill.verify(active, value, 10.5).status is SkillStatus.RUNNING
        changed = deepcopy(value)
        changed['active_quests'][0]['objectives'][0]['current'] = 1
        assert skill.verify(active, changed, 10.6).status is SkillStatus.SUCCESS


@pytest.mark.parametrize('invalid', ['removed', 'wrong_world', 'dead', 'wrong_entry'])
def test_invalid_actor_is_not_acquired_as_the_item_subject(supplement, invalid):
    value = state(supplement)
    unit = value['packet_entities'][GUID]
    if invalid == 'removed': unit['removed'] = True
    elif invalid == 'wrong_world': unit['map_id'] = 2444
    elif invalid == 'dead': unit['dead'] = True
    else: unit['entry_id'] = 42601
    candidates = QuestDomain().propose(world(value), Goal.parse('Questelj', 10.))
    assert not [p for p in candidates if p.parameters.get('item_id') == 57954
                and p.skill in {'TARGET', 'USE_ON_TARGET', 'ASSIST'}]


def test_without_an_item_binding_the_visible_bag_button_is_used(supplement):
    value = state(supplement, selected=True)
    value['actionbar'] = []
    domain = QuestDomain()
    candidates = domain.propose(world(value), Goal.parse('Questelj', 10.))
    assert any(p.skill == 'OPEN_BAGS' for p in candidates)
    value['bags_open'] = True
    value['inventory']['items'][0].update(x=.7, y=.3, coordinate_space='CLIENT_BOTTOM_LEFT')
    candidates = domain.propose(world(value), Goal.parse('Questelj', 10.))
    use = next(p for p in candidates if p.skill == 'ASSIST')
    assert use.parameters['activation_source'] == 'INVENTORY_COORDINATE'
    active = running(use, value)
    result = UseItemSkill(Bindings()).begin(active, value)
    assert result.status is SkillStatus.RUNNING
    assert [(c.kind, c.button, c.x, c.y) for c in result.commands] == [('CLICK', 'RIGHT', .7, .3)]


def test_wrong_selection_cannot_use_the_item_or_claim_target_success(supplement):
    value = state(supplement)
    candidate = next(p for p in QuestDomain().propose(world(value), Goal.parse('Questelj', 10.))
                     if p.skill == 'TARGET')
    active = running(candidate, value)
    skill = TargetSkill()
    assert skill.begin(active, value).status is SkillStatus.RUNNING
    changed = deepcopy(value)
    changed['target'] = {'guid': 'Creature-0-1-0-1-42342-0000000002',
                         'npc_id': 42342, 'name': 'Energized Harvest Reaper', 'attackable': True}
    changed['target_sample_time'] = 10.5
    assert skill.verify(active, changed, 10.5).status is not SkillStatus.SUCCESS
    candidates = QuestDomain().propose(world(changed), Goal.parse('Questelj', 10.))
    assert not [p for p in candidates if p.skill in {'ASSIST', 'USE_ON_TARGET'}]


def test_item_recipient_relation_is_never_a_kill_instruction(supplement):
    from wowbot.agent.packet_entity_facts import kill_objective_entries
    value = state(supplement)
    assert not kill_objective_entries(value)


def test_after_a_friendly_tab_miss_enemy_tab_is_still_guid_checked(supplement):
    value = state(supplement)
    domain = QuestDomain()
    first = next(p for p in domain.propose(world(value), Goal.parse('Questelj', 10.))
                 if p.skill == 'TARGET')
    domain.note_object_interaction_result({'skill': 'TARGET', 'outcome': 'FAILURE'}, value,
                                         first.parameters)
    value['monotonic_time'] = value['timestamp'] = 15.
    candidates = domain.propose(world(value), Goal.parse('Questelj', 15.))
    chosen = next(p for p in candidates if p.skill == 'TARGET')
    assert chosen.parameters['activation_source'] == 'TAB_SERVER_GUID'
    assert chosen.parameters['guid'] == GUID
    assert TargetSkill().commands_for(Intent('TARGET', chosen.parameters))[0].binding == 'TARGETNEARESTENEMY'


def feigning(supplement, *, selected=True, feign=True):
    """Live 2026-11-03 08:15: the inert golem read dead in the client target
    frame; the server showed it alive (4378/4378) with UNIT_FLAG2_FEIGN_DEATH."""
    value = state(supplement, distance=2., selected=selected)
    value['packet_entities'][GUID]['unit'] = {'health': 4378, 'max_health': 4378,
                                              'unit_flags2': 0x801 if feign else 0x800}
    if selected:
        value['target'] = {**value['target'], 'dead': True}
    return value


def test_live_1103_a_feign_death_golem_is_a_live_item_subject(supplement):
    value = feigning(supplement)
    model = world(value)
    candidates = QuestDomain().propose(model, Goal.parse('Questelj', 10.))
    chosen = next(p for p in candidates if p.skill == 'ASSIST' and p.parameters.get('item_id') == 57954)
    assert SkillRegistry(bindings=Bindings()).available(chosen, model)
    skill = UseItemSkill(Bindings())
    assert skill.begin(running(chosen, value), value).commands[0].binding == 'ACTIONBUTTON7'


def test_a_really_dead_unit_without_the_server_feign_flag_stays_refused(supplement):
    value = feigning(supplement, feign=False)
    value['packet_entities'][GUID]['unit']['health'] = 0
    model = world(value)
    candidates = QuestDomain().propose(model, Goal.parse('Questelj', 10.))
    assert not [p for p in candidates if p.skill in {'ASSIST', 'USE_ON_TARGET'} and p.parameters.get('item_id') == 57954]


def test_user_1103_an_item_whose_spell_allows_a_dead_target_is_used_on_a_corpse(supplement):
    """User 2026-11-03: some quests use the item on a dead NPC/mob.  The spell's
    own SPELL_ATTR2_ALLOW_DEAD_TARGET (DB2 SpellMisc) permits it."""
    value = feigning(supplement, feign=False)
    value['packet_entities'][GUID]['unit']['health'] = 0
    value['reference_knowledge'] = reference(supplement)
    for objective in value['reference_knowledge']['quests']['26257']['objectives']:
        for use in objective.get('item_uses') or ():
            use['can_target_dead'] = True
    items = value['reference_knowledge']['quests']['26257'].get('items') or {}
    for profile in (items.get('use_profiles') or {}).values():
        for use in profile.get('uses') or ():
            use['can_target_dead'] = True
    model = world(value)
    candidates = QuestDomain().propose(model, Goal.parse('Questelj', 10.))
    chosen = next(p for p in candidates if p.skill in {'ASSIST', 'USE_ON_TARGET'} and p.parameters.get('item_id') == 57954)
    assert SkillRegistry(bindings=Bindings()).available(chosen, model)
