"""Minimized user-run failure replay; simulated continuation is offline only."""
from copy import deepcopy
import json
import math
from pathlib import Path

from wowbot.agent.models import Attempt, Goal, Observation, Prediction
from wowbot.agent.planner import Planner
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills.quest_item import UseItemSkill


def fixture():
    return json.loads((Path(__file__).parent/'fixtures/vineyard_directed_item_20261028.json').read_text(encoding='utf-8'))


def world(value):
    result = WorldModel()
    result.ingest(Observation.create(value, value['monotonic_time']))
    result.quest_model.apply_reference_knowledge(value['reference_knowledge'])
    return result


def test_recorded_zero_credit_frame_now_reaches_fire_through_shared_planner():
    data = fixture()
    assert data['provenance']['live_result'].startswith('UNVALIDATED_FIX')
    value = data['state']
    current = world(value)
    objective = current.quest_model.records[26391].objectives[0]
    assert objective.type == 'USE_ITEM_ON_TARGET' and objective.current_count == 0
    proposals = Planner(SkillRegistry()).candidates(Goal.parse('Questelj', value['monotonic_time']),
                                                  current, value['monotonic_time'])
    proposal = proposals[0]
    assert proposal.skill == 'MOVE'
    assert proposal.parameters['purpose'] == 'DIRECTED_QUEST_ITEM'
    assert proposal.parameters['item_id'] == 58362
    assert proposal.parameters['server_entity_guid'] in value['packet_entities']
    assert proposal.parameters['face_on_arrival'] and proposal.parameters['require_navmesh']
    assert not any(p.skill in {'COMBAT','TARGET','OBJECT_USE'} for p in proposals)


def test_simulated_arrival_uses_recorded_bag_button_once_and_requires_real_credit():
    value = deepcopy(fixture()['state'])
    now = value['monotonic_time']
    current = world(value)
    domain = QuestDomain()
    plans = []
    domain._propose_objectives(current, current.state, now, current.quest_model.records,
                               '26391', '26391:0', False, plans)
    move = plans[0].parameters
    # This pose/readiness is simulated. It is never labelled a live outcome.
    value['player_world_position'].update(x=move['x']-4., y=move['y'], z=move['z'], sample_time=now)
    value['orientation'] = 0.
    value['movement'] = {'moving':False, 'speed':0.}
    value.update(is_in_combat=False, is_mounted=False, is_casting=False, is_channeling=False, bags_open=True)
    value['quest_item_target'] = {'guid':None, 'sample_time':now, 'items':[{
        'quest_id':26391,'item_id':58362,'is_usable':True,'cooldown_remaining':0.,'in_range':None}]}
    current = world(value)
    plans = []
    domain._propose_objectives(current, current.state, now, current.quest_model.records,
                               '26391', '26391:0', False, plans)
    proposal, = plans
    assert proposal.skill == 'USE_ON_TARGET'
    assert proposal.parameters['activation_source'] == 'INVENTORY_COORDINATE'
    assert not proposal.parameters['target_required']
    attempt = Attempt('recorded', proposal, deepcopy(value), 'obs', now, now+8, (),
                      Prediction('p','recorded','credit',now,now+8,'obs'))
    active = ActiveSkillRuntime().start(intent=Intent('USE_ON_TARGET',proposal.parameters,
        objective_ref='26391:0'), attempt=attempt, now=now, before_snapshot=deepcopy(value))
    skill = UseItemSkill()
    result = skill.begin(active, value)
    assert result.status is SkillStatus.RUNNING
    item, = value['inventory']['items']
    command, = result.commands
    assert (command.kind,command.button,command.x,command.y) == ('CLICK','RIGHT',item['x'],item['y'])
    assert skill.verify(active,value,now+6).status is SkillStatus.RUNNING
    value['active_quests'][0]['objectives'][0]['current'] = 1
    result = skill.verify(active,value,now+6.5)
    assert result.status is SkillStatus.SUCCESS and result.evidence == ('objective_changed:26391:0',)
