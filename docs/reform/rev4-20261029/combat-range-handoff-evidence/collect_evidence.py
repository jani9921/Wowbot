"""Bounded read-only trace queries; no AgentMemory writer or raw packet export."""
import collections,hashlib,json,sqlite3
from pathlib import Path

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent
database=root/'output/agent/profiles/<user>/agent_memory.sqlite3'
assert database.is_file()
samples=[];verifications=[];commands=[]
with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1) as db:
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA trusted_schema=OFF')
    for ident,at,payload in db.execute('SELECT id,at,payload FROM observations WHERE source=? AND at BETWEEN ? AND ? ORDER BY at',
                                      ('ADDON_TELEMETRY',1346192.8,1346193.6)):
        data=json.loads(payload)
        samples.append({'observation_id':ident,'received_at':at,'source_sample_time':data.get('monotonic_time'),
            'own_last_spell':data.get('combat_last_spell_id'),'own_last_cast_at':data.get('combat_last_cast_at'),
            'target_entry':(data.get('target') or {}).get('npc_id'),
            'target_world_position_available':isinstance((data.get('target') or {}).get('world_position'),dict),
            'actionbar_fast':data.get('actionbar_fast'),'orientation':data.get('orientation'),
            'is_in_combat':data.get('is_in_combat')})
    for ident,at,payload in db.execute('SELECT id,at,payload FROM observations WHERE source=? AND at BETWEEN ? AND ? ORDER BY at',
                                      ('AGENT_TRACE',1345720.,1346220.)):
        data=json.loads(payload);trace=data.get('trace') or {}
        if data.get('trace_type')=='VERIFICATION':
            verifications.append({'observation_id':ident,'at':at,**{k:trace.get(k) for k in
                ('action_id','skill','outcome','reason','baseline_observation_id','observed_observation_id')}})
        if data.get('trace_type') in {'ACTION_INTENT','ACTION_EXECUTED'} and 1346192.5<=at<=1346194.:
            commands.append({'at':at,'kind':data['trace_type'],'action_id':trace.get('action_id'),
                             'commands':trace.get('commands'),'skill':(trace.get('proposal') or {}).get('skill')})
counts=collections.Counter((r['skill'],r['outcome'],r['reason']) for r in verifications)
status_path=root/'output/agent/pid-7784/agent_status.json'
raw=status_path.read_bytes();status=json.loads(raw)
packet=status.get('packet_telemetry') or {};provider=packet.get('session_provider') or {}
result={'source_database':database.relative_to(root).as_posix(),'database_open_mode':'ro, query_only',
    'source_status':status_path.relative_to(root).as_posix(),'source_status_sha256':hashlib.sha256(raw).hexdigest(),
    'live_observed':{'mode':status.get('mode'),'navmesh_available':status.get('navigation',{}).get('navmesh',{}).get('available'),
        'navmesh_reason':status.get('navigation',{}).get('navmesh',{}).get('reason'),
        'provider_state':provider.get('state'),'provider_source':provider.get('source'),
        'delivery':packet.get('delivery'),'control_rates':status.get('loop_rates')},
    'charge_transition_samples':samples,'transition_action_commands':commands,'verifications':verifications,
    'verification_counts':[{'skill':k[0],'outcome':k[1],'reason':k[2],'count':v} for k,v in counts.items()],
    'operator_interventions_fully_known':False,'autonomous_quest_completion_claim':False,
    'raw_packet_or_private_identity_exported':False}
(work/'live-combat-evidence.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps({'samples':len(samples),'verifications':len(verifications),'counts':result['verification_counts']}))
