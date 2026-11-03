import hashlib,json,shutil,struct,zipfile
from pathlib import Path
from collections import Counter

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent
checkpoint=root/'docs/reform/rev4-20261029/applied-progress-evidence'
for old,new in (('current-source.zip','baseline.zip'),('current-files.json','baseline.json')):
    shutil.copyfile(checkpoint/old,work/new)
sha=lambda data:hashlib.sha256(data).hexdigest()
with zipfile.ZipFile(work/'baseline.zip') as z:
    for row in json.loads((work/'baseline.json').read_text())['files']:
        assert sha(z.read(row['path']))==row['sha256']
sources=[]
revision='f439120b1f8c4f5a5c3fc0deb6aa01bf971e4fdf'
for name,relative in (('MapBuilder.cpp','src/tools/mmaps_generator/MapBuilder.cpp'),
                     ('TrinityDetourNavMesh.h','dep/recastnavigation/Detour/Include/DetourNavMesh.h')):
    data=(work/name).read_bytes()
    sources.append({'file':name,'sha256':sha(data),'bytes':len(data),
                    'url':f'https://raw.githubusercontent.com/TrinityCore/TrinityCore/{revision}/{relative}'})
(work/'primary-sources.json').write_text(json.dumps(sources,indent=2)+'\n')
with zipfile.ZipFile(Path(r'C:/Users/<user>/Downloads/mmaps.zip')) as z:
    headers=[]
    for name in ('0000.mmap','2175.mmap','2444.mmap'):
        b=z.read(name)
        headers.append({'member':name,'bytes':len(b),'sha256':sha(b),'hex':b.hex(),
                        'signed_max_polys':struct.unpack_from('<i',b,32)[0]})
(work/'header-evidence.json').write_text(json.dumps(headers,indent=2)+'\n')
reports=[]
for pid in ('10152','6856','5408','7592','12912'):
    path=root/'output/agent'/('pid-'+pid)/'agent_status.json'
    data=path.read_bytes();status=json.loads(data)
    pkt=status.get('packet_telemetry') or {}
    navigation=status.get('navigation') or {}
    provider=pkt.get('session_provider') or {}
    result=status.get('result') or {}
    reports.append({'file':path.relative_to(root).as_posix(),'source_sha256':sha(data),
        'mode':status.get('mode'),'last_result':{k:result.get(k) for k in ('skill','outcome','reason','failure_type','purpose')},
        'navmesh':navigation.get('navmesh'),
        'packet':{k:pkt.get(k) for k in ('status','received','rejected','dropped','coalesced',
             'delivery_losses','delivery_loss_reason','delivery','context_status','last_error')},
        'provider':{k:provider.get(k) for k in ('state','source','reason','capture_epoch','packet_rebaseline_required')}})
(work/'live-status-evidence.json').write_text(json.dumps(reports,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print('baseline and bounded non-secret live evidence saved')
