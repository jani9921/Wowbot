"""Learned episodes need persisted origins, not just plausible ID strings."""
import json
from types import SimpleNamespace

import pytest

from wowbot.agent.memory import AgentMemory
from wowbot.verified_episode import POLICY, manifest_ids, reusable_episode
from test_verified_episode_20261030 import proof, STATE


def episode(row, *, at=0.):
    return {'status':'SUCCESS','result':{'verified':True},'session':'s',
            'started_at':at,'ended_at':at+.2,'initial_state':STATE,
            'steps':[{'kind':'VERIFICATION','payload':row}]}


def finish(memory, row, *, at=0.):
    goal = SimpleNamespace(goal_id=f'g{at}', domain='QUEST')
    key = memory.start_episode(goal,'s',STATE,at)
    memory.record_episode_step(key,at+.1,'VERIFICATION',row)
    memory.finish_episode(key,STATE,at+.2,'SUCCESS',{'verified':True})


@pytest.mark.parametrize('async_writes',[False, True])
def test_manifest_query_waits_for_shared_writer_and_promotes_only_actual_saved_proof(tmp_path,async_writes):
    memory = AgentMemory(tmp_path/'memory.sqlite3',async_writes=async_writes)
    try:
        row = proof(memory)
        finish(memory,row)
        result = memory.task_patterns('QUEST')
        assert len(result)==1 and result[0]['provenance']['verification_policy']==POLICY
        saved = memory.evidence_manifests_by_id(manifest_ids(episode(row)))
        assert set(saved)==set(row['evidence_manifest_ids'])
        assert all('value' not in m and len(m['value_sha256'])==64 for m in saved.values())
    finally:
        memory.close()


def test_plausible_but_missing_or_unlinked_manifest_ids_cannot_promote(tmp_path):
    memory = AgentMemory(tmp_path/'memory.sqlite3')
    try:
        row = proof(memory)
        row['evidence_manifest_ids'] = ['invented-manifest']
        finish(memory,row)
        assert memory.task_patterns('QUEST')==[]
        valid = proof(memory,2,at=1.)
        valid['observed_observation_id']='invented-observation'
        valid['evidence'].append('invented-observation')
        finish(memory,valid,at=1.)
        assert memory.task_patterns('QUEST')==[]
    finally:
        memory.close()


@pytest.mark.parametrize('change',[
    ('context', {'session_id':'different','character_guid':STATE['character_guid'],'game_build':70575}),
    ('context', {'session_id':'s','character_guid':'Player-1-99','game_build':70575}),
    ('context', {'session_id':'s','character_guid':STATE['character_guid'],'game_build':70576}),
    ('observed_at',999.),
    ('received_at',999.),
    ('expires_at',-.1),
    ('lineage', {'root_observation_ids':['same'],'correlation_uncertain':True,'lineage_truncated':False}),
    ('lineage', {'root_observation_ids':[],'correlation_uncertain':False,'lineage_truncated':False}),
])
def test_saved_metadata_with_unknown_origin_time_or_wrong_scope_is_not_reusable(tmp_path,change):
    memory = AgentMemory(tmp_path/'memory.sqlite3')
    try:
        row = proof(memory)
        saved = memory.evidence_manifests_by_id(row['evidence_manifest_ids'])
        after = next(m for m in saved.values() if m['observation_id']==row['observed_observation_id'])
        after[change[0]]=change[1]
        assert not reusable_episode(episode(row),manifests=saved)[0]
    finally:
        memory.close()


def test_before_and_after_wrappers_over_the_same_source_do_not_verify_a_delta(tmp_path):
    memory = AgentMemory(tmp_path/'memory.sqlite3')
    try:
        row = proof(memory)
        saved = memory.evidence_manifests_by_id(row['evidence_manifest_ids'])
        before = next(m for m in saved.values() if m['observation_id']==row['baseline_observation_id'])
        after = next(m for m in saved.values() if m['observation_id']==row['observed_observation_id'])
        after['lineage']['root_observation_ids']=before['lineage']['root_observation_ids']
        assert reusable_episode(episode(row),manifests=saved)==(False,'verification_reuses_same_source_origin')
    finally:
        memory.close()


def test_new_wrapper_observation_ids_over_same_root_do_not_count_as_independent_trials(tmp_path):
    memory = AgentMemory(tmp_path/'memory.sqlite3')
    try:
        for i in range(3):
            finish(memory,proof(memory,i,at=float(i),root='same-original-signal'),at=float(i))
        result = memory.task_patterns('QUEST')
        assert len(result)==1 and result[0]['successes']==1
        assert 'same-original-signal' in result[0]['provenance']['source_root_observation_ids']
    finally:
        memory.close()


def test_old_policy_is_preserved_but_not_reused_and_current_version_must_match(tmp_path):
    memory = AgentMemory(tmp_path/'memory.sqlite3')
    try:
        for i in range(3):
            finish(memory,proof(memory,i,at=float(i)),at=float(i))
        patterns = memory.task_patterns('QUEST')
        assert patterns[0]['successes']==3 and patterns[0]['stage']=='SUPPORTED'
        assert memory.find_similar_task_patterns('QUEST',['MOVE'],STATE)['mode']=='REUSE_CANDIDATE'
        assert memory.find_similar_task_patterns('QUEST',['MOVE'],{**STATE,'game_build':70576})['mode']=='NO_REFERENCE'
        provenance = {**patterns[0]['provenance'],'verification_policy':'EVIDENCE_LINKED_V1'}
        with memory._tx() as db:
            db.execute('UPDATE task_patterns SET provenance=?',(json.dumps(provenance),))
        assert len(memory.task_patterns('QUEST'))==1
        assert memory.find_similar_task_patterns('QUEST',['MOVE'],STATE)['mode']=='NO_REFERENCE'
    finally:
        memory.close()


def test_source_dedup_survives_compaction_of_diagnostic_provenance_lists(tmp_path):
    memory = AgentMemory(tmp_path/'memory.sqlite3')
    try:
        finish(memory,proof(memory,1,root='old-root'))
        pattern = memory.task_patterns('QUEST')[0]
        trimmed = {**pattern['provenance'],'source_root_observation_ids':[], 'source_observation_ids':[]}
        with memory._tx() as db:
            db.execute('UPDATE task_patterns SET provenance=?',(json.dumps(trimmed),))
        finish(memory,proof(memory,2,at=1.,root='old-root'),at=1.)
        assert memory.task_patterns('QUEST')[0]['successes']==1
    finally:
        memory.close()


def test_invalid_stored_json_is_not_a_usable_evidence_manifest(tmp_path):
    memory = AgentMemory(tmp_path/'memory.sqlite3')
    try:
        row = proof(memory)
        with memory._tx() as db:
            db.execute('UPDATE evidence_manifests SET lineage=?',('{damaged',))
        finish(memory,row)
        assert memory.task_patterns('QUEST')==[]
    finally:
        memory.close()
