from wowbot.quests.mechanics import MechanicResolver, QuestTargetContext, QuestExecutionGraph, MechanicNodeState
from wowbot.runtime.skill_identity import check_command_identity
from wowbot.agent.models import Command
from wowbot.agent.quest_playbooks import horizon_for
from test_quest_playbook_runtime_20261027 import state, proposal


def test_mechanic_resolver_reuses_classifier_without_promoting_credit_proxy_to_actor():
    contract = MechanicResolver().resolve(7, '7:0', {'description': 'Speak with Left', 'type': 0},
        {'mechanism': 'GOSSIP_ACTOR', 'credit_object_id': 900, 'talk_creatures': [{'entry': 100}]})
    assert contract.mechanism == 'GOSSIP_ACTOR'
    assert contract.targets.credit_entries == (900,) and contract.targets.actor_entries == (100,)
    assert contract.targets.allows_physical_entry(900) is False


def test_internal_dag_keeps_verified_stages_and_does_not_invent_objective_completion():
    contract = MechanicResolver().resolve(7, '7:0', {'mechanism': 'GOSSIP_ACTOR'})
    nodes = QuestExecutionGraph().build(contract, verified_steps=('APPROACH', 'TALK'))
    assert [n.name for n in nodes] == ['APPROACH', 'TALK', 'DIALOG', 'FIGHT']
    assert nodes[2].state is MechanicNodeState.READY and nodes[3].state is MechanicNodeState.BLOCKED
    assert nodes[3].dependencies == (nodes[2].node_id,)
    assert contract.retry_cooldown_seconds <= 20.


def test_missing_mechanism_is_explicitly_unsupported_not_a_blind_kill():
    contract = MechanicResolver().resolve(7, '7:0', {'mechanism': 'UNKNOWN_SCRIPT'})
    nodes = QuestExecutionGraph().build(contract)
    assert nodes[0].state is MechanicNodeState.UNSUPPORTED


def test_existing_horizon_contains_dependency_and_verification_references():
    context, horizon = horizon_for(proposal('MOVE'), state('OBJECT_USE'))
    assert context.book.mechanism == 'OBJECT_USE'
    assert horizon and all(step['depends_on'] and step['expected_observation'] for step in horizon)


def test_every_guarded_entity_skill_rejects_explicit_wrong_physical_role_before_input():
    current = {'monotonic_time': 10., 'active_quests': [{'quest_id': 7, 'objectives': [
        {'objective_id': '7:0', 'description': 'Speak with Left', 'target_entity': {'npc_id': 100}}]}]}
    for skill in ('TALK', 'INTERACT', 'COMBAT', 'OBJECT_USE', 'USE_ON_TARGET'):
        check = check_command_identity(skill, {'quest_id': 7, 'objective_id': '7:0'},
            {'npc_id': 900}, current, (Command('BIND', 'INTERACTTARGET'),), 10.)
        assert not check and check.reason == 'QUEST_PHYSICAL_TARGET_ROLE_MISMATCH'


def test_specific_current_quest_dialog_overrides_stale_static_actor_relationship():
    from wowbot.agent.quest_target_context import physical_target_problem
    state = {'active_quests': [{'quest_id': 7, 'objectives': [
        {'objective_id': '7:0', 'description': 'Talk', 'target_entity': {'npc_id': 100}}]}],
        'quest_ui': {'open': True, 'quest_id': 7, 'npc_guid': 'actual-guid'}}
    assert physical_target_problem('TALK', {'quest_id': 7, 'objective_id': '7:0'},
                                   {'guid': 'actual-guid', 'npc_id': 200}, state) is None
