"""Read-only saved-pose geometry queries. No runtime/client/input construction."""
import json,time
from pathlib import Path
from wowbot.geometry_contracts import query_path
from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent
owner=TrinityMMapNavMesh(Path(r'C:/Users/<user>/Downloads/mmaps.zip'))
rows=[]
try:
    for pid in ('7592','12912'):
        status=json.loads((root/'output/agent'/('pid-'+pid)/'agent_status.json').read_text(encoding='utf-8-sig'))
        p=status['world']['player']['player_world_position']
        d=status['navigation']['trip']['original_destination']
        pose={k:p[k] for k in ('x','y','z','z_known','coordinate_space') if k in p}
        goal={k:d[k] for k in ('x','y','z','z_known','coordinate_space') if k in d}
        started=time.monotonic()
        result=query_path(owner,p['instance_id'],pose,goal)
        row={'saved_pid':int(pid),'world_map':p['instance_id'],'start':pose,'end':goal,
             'status':result.status.value,'reason':result.reason,
             'seconds':time.monotonic()-started,'diagnostics':dict(owner.last_diagnostics)}
        if result.value is not None:
            row['path_anchors']=list(result.value.anchors)
        rows.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
finally:
    owner.close()
    (work/'saved-pose-geometry-results.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
