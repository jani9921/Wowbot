"""Read-only recorded entity projection probe; no runtime, transport or input."""
import json,time
from pathlib import Path
from types import SimpleNamespace
from wowbot.agent.world_packet_reducer import _remember_entity,_project_entities
from wowbot.packetio.validation import ENTITY_EVENTS

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
status=json.loads((root/'output/agent/pid-7784/agent_status.json').read_text(encoding='utf-8-sig'))
player=status['world']['player']
context={'selected_pid':7784,'session_id':status['world']['session_id'],
         'character_guid':player['character_guid'],'game_build':70575,'instance_id':0,'map_id':425,'phase':None}
model=SimpleNamespace(addon_state={},session_context_provider=SimpleNamespace(expected=lambda pid:context))
guid='Creature-0-1469-0-29720-50039-000064B73E'
at=1346152.7092977
wall=at+time.time()-time.monotonic()
with (root/'output/agent/ymir-bootstrap/ymir_events.jsonl').open('rb') as source:
    for line in source:
        try:e=json.loads(line)
        except ValueError:continue
        if (e.get('selected_pid')!=7784 or e.get('event_type') not in ENTITY_EVENTS
                or e.get('semantic_status')!='CONFIRMED' or e['timestamp']>wall):continue
        _remember_entity(model,e['event_type'],e['payload'],e['timestamp'],context)
state={'player_world_position':{'x':-8793.3515625,'y':-204.46118164062,'instance_id':0}}
_project_entities(model,state,wall)
raw=model.__dict__.get('_packet_entities') or {}
projected=state.get('packet_entities') or {}
result={'at':at,'world_timestamp':wall,'known_entities':len(raw),'projected_entities':len(projected),
        'expected_in_raw':guid in raw,'expected_in_projection':guid in projected,
        'expected_position':(raw.get(guid) or {}).get('position'),
        'expected_removed':(raw.get(guid) or {}).get('removed'),
        'active_quest_givers':sum(bool(e.get('quest_giver',{}).get('quest_available') or e.get('quest_giver',{}).get('reward_ready')) for e in raw.values())}
Path(__file__).with_name('facing-projection-probe.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
