from types import SimpleNamespace
import pytest
from wowbot.agent.memory import AgentMemory
from wowbot.agent.world import WorldModel
from wowbot.agent.models import Observation
from wowbot.verified_episode import reusable_episode


STATE = {'character_guid':'Player-1-1','game_build':70575,'map_id':1}


def proof(memory, index=1, *, at=0., root=None):
    world = WorldModel()
    observations = []
    for label, offset in (('b',.01),('o',.02)):
        obs = Observation.create({**STATE,'session_id':'s','frame_id':f'{label}{index}',
            'target':{'guid':'npc-1','health':100 if label=='b' else 50},
            **({'provenance':{'root_observation_ids':[root]}} if label=='o' and root else {})},at+offset)
        world.ingest(obs)
        observations.append(obs.observation_id)
    ids = memory.persist_evidence_manifests(world.query.evidence('target',at+.03,include_inactive=True))
    return {'verification_id':f'v{index}','action_id':f'a{index}','skill':'MOVE','outcome':'SUCCESS',
            'observed_at':at+.1,'baseline_observation_id':observations[0],
            'observed_observation_id':observations[1],'evidence':observations,'evidence_manifest_ids':ids}


def test_success_label_ack_and_manual_intervention_cannot_promote_reusable_episode(tmp_path):
    memory = AgentMemory(tmp_path/'memory.sqlite3')
    try:
        goal = SimpleNamespace(goal_id='g', domain='QUEST')
        for index in range(3):
            episode = memory.start_episode(goal, 's', STATE, float(index))
            memory.record_episode_step(episode, index+.1, 'VERIFICATION', proof(memory,index,at=float(index)))
            if index == 1:
                memory.record_episode_step(episode, index+.15, 'MANUAL_BOUNDARY', {})
            memory.finish_episode(episode, STATE, index+.2, 'SUCCESS', {'verified': index != 0})
        patterns = memory.task_patterns('QUEST')
        assert len(patterns) == 1 and patterns[0]['successes'] == 1
        assert patterns[0]['stage'] == 'EPISODIC'
        assert not reusable_episode({'status': 'SUCCESS', 'result': {'verified': True},
                    'steps': [{'kind': 'VERIFICATION', 'payload': {'outcome': 'SUCCESS'}}]})[0]
    finally:
        memory.close()


def test_replay_of_same_observation_does_not_count_as_repeated_verified_trial(tmp_path):
    memory = AgentMemory(tmp_path/'memory.sqlite3')
    try:
        verified = proof(memory)
        for index in range(3):
            goal = SimpleNamespace(goal_id=str(index), domain='QUEST')
            episode = memory.start_episode(goal, 's', STATE, float(index))
            memory.record_episode_step(episode, index+.1, 'VERIFICATION', verified)
            memory.finish_episode(episode, STATE, index+.2, 'SUCCESS', {'verified': True})
        assert memory.task_patterns('QUEST')[0]['successes'] == 1
    finally:
        memory.close()


@pytest.mark.parametrize('async_writes', [False, True])
def test_sqlite_evidence_manifest_keeps_roots_and_real_time_without_persisting_packet_body(tmp_path, async_writes):
    memory = AgentMemory(tmp_path/'memory.sqlite3', async_writes=async_writes)
    try:
        world = WorldModel()
        obs = Observation.create({'session_id': 's', 'frame_id': 'frame-1', 'target': {'guid': 'npc-1'},
            'provenance': {'root_observation_ids': ['original-packet'], 'observed_at_monotonic': 9.}}, 10.)
        world.ingest(obs)
        entries = world.query.evidence('target', 10.)
        assert entries
        memory.persist_evidence_manifests(entries)
        memory.persist_evidence_manifests(entries)
        rows = memory.evidence_manifests(obs.observation_id)
        assert len(rows) == 1 and rows[0]['observed_at'] == 9. and rows[0]['received_at'] == 10.
        assert rows[0]['lineage']['root_observation_ids'] == ['original-packet']
        assert len(rows[0]['value_sha256']) == 64 and 'value' not in rows[0]
    finally:
        memory.close()
