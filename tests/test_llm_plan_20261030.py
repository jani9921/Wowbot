from copy import deepcopy
import pytest
from wowbot.llm_plan import LLMPlan
from wowbot.agent.reasoner import OllamaReasoner
from wowbot.agent.advisory_tools import AdvisoryReadTools
from wowbot.agent.world import WorldModel
from wowbot.agent.models import Observation


def context():
    return {'scope_token': 'scope-1', 'allowed_refs': {'entities': ['npc-1'], 'objectives': ['7:0'],
            'items': ['100'], 'evidence': ['obs-1']}, 'allowed_evidence': ['obs-1'],
            'candidates': [{'id': 'move-1', 'skill': 'MOVE'}, {'id': 'talk-1', 'skill': 'TALK'}]}


def plan():
    return {'schema': 'aipc.llm-plan.v1', 'context_token': 'scope-1', 'steps': [
        {'id': 'approach', 'capability': 'MOVE', 'candidate_id': 'move-1', 'actor_ref': 'npc-1',
         'objective_ref': '7:0', 'evidence_refs': ['obs-1'], 'depends_on': []},
        {'id': 'talk', 'capability': 'TALK', 'candidate_id': 'talk-1', 'actor_ref': 'npc-1',
         'evidence_refs': ['obs-1'], 'depends_on': ['approach']}]}


def test_bounded_reference_plan_roundtrips_and_revalidates_against_current_scope():
    current = context()
    validated = LLMPlan.validate(plan(), current)
    assert validated.revalidate(current)
    current['scope_token'] = 'new-session'
    assert not validated.revalidate(current)


@pytest.mark.parametrize('change', [
    {'actor_ref': 'invented'}, {'item_ref': 'unknown-item'}, {'objective_ref': '8:0'},
    {'x': 100., 'y': 200.}, {'capability': 'RUN_PYTHON'}, {'depends_on': ['talk']},
    {'candidate_id': 'talk-1'}, {'evidence_refs': ['invented']}])
def test_invented_identity_direct_input_and_cycle_are_rejected(change):
    value = plan()
    value['steps'][0].update(change)
    with pytest.raises(ValueError):
        LLMPlan.validate(value, context())


def test_invalid_plan_cannot_still_select_its_candidate():
    value = plan()
    value['steps'][0]['command'] = 'CLICK'
    normalized = OllamaReasoner._normalize({'candidate_id': 'move-1', 'plan': value}, context())
    assert normalized['candidate_id'] is None and normalized['plan_error'] == 'plan_schema_or_scope_rejected'


def test_read_tools_are_snapshot_queries_and_accept_no_arbitrary_sql_or_mutation():
    world = WorldModel()
    payload = {'session_id': 's', 'frame_id': 'one', 'target': {'guid': 'npc-1', 'name': 'Guide'},
               'active_quests': [{'quest_id': 7, 'title': 'Talk', 'objectives': [{'description': 'Speak with Guide'}]}]}
    world.ingest(Observation.create(payload, 10.))
    tools = AdvisoryReadTools(world, 10.)
    result = tools.call({'tool': 'quest', 'ref': '7'})
    result['title'] = 'changed'
    assert world.state['active_quests'][0]['title'] == 'Talk'
    with pytest.raises(ValueError):
        tools.call({'tool': 'sql', 'ref': 'DELETE FROM observations'})
    with pytest.raises(ValueError):
        tools.call({'tool': 'entity', 'ref': 'invented'})
    assert 'npc-1' in tools.context()['allowed_refs']['entities']
