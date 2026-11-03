import ast, difflib, hashlib, json, re, shutil, zipfile
from pathlib import Path
from xml.etree import ElementTree

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent
target=root/'docs/reform/rev4-20261029/mmap-format-evidence'
assert not target.exists(), 'keep previous checkpoints intact'
sha=lambda data:hashlib.sha256(data).hexdigest()
baseline=json.loads((work/'baseline.json').read_text(encoding='utf-8'))
with zipfile.ZipFile(work/'baseline.zip') as z:
    before={r['path']:z.read(r['path']) for r in baseline['files']}
for row in baseline['files']: assert sha(before[row['path']])==row['sha256']
names=set(before)
for directory in ('src','tests'):
    names.update(p.relative_to(root).as_posix() for p in (root/directory).rglob('*.py'))
names.add('docs/reform/rev4-20261029/P1E_MMAP_FORMATS.md')
after={name:(root/name).read_bytes() for name in sorted(names) if (root/name).is_file()}
numbered=lambda data:[s for s in data.decode('utf-8-sig').splitlines() if s.startswith(('| V4-','| DESIGN-'))]
assert len(numbered(after['docs/CURRENT_SOURCE_COVERAGE.md']))==203
assert numbered(before['docs/CURRENT_SOURCE_COVERAGE.md'])==numbered(after['docs/CURRENT_SOURCE_COVERAGE.md'])
for name,data in after.items():
    if name.endswith('.py'): ast.parse(data.decode('utf-8-sig'),filename=name)
result=json.loads((work/'combined-geometry-1-result.json').read_text())
command=json.loads((work/'combined-geometry-1-command.json').read_text())
original=json.loads(Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1d-20261029/release-command.json').read_text())
assert result['exit_code']==0 and command['command'][-1]==original['command'][-1]
suite=ElementTree.parse(work/'combined-geometry-1-junit.xml').getroot()
cases=suite.findall('.//testcase')
assert not suite.findall('.//failure') and not suite.findall('.//error')
skipped=len(suite.findall('.//skipped'))
passed=len(cases)-skipped
assert f'{passed} passed, {skipped} skipped, 10 deselected' in (work/'combined-geometry-1.log').read_text()
assert all(p.relative_to(root).as_posix() in command['modules'] for p in (root/'tests').glob('test_*2026103*.py'))
verification=json.loads((work/'source-verification.json').read_text())
changes,patch=[],[]
for name in sorted(set(before)|set(after)):
    old,new=before.get(name),after.get(name)
    if old==new:continue
    changes.append({'path':name,'status':'ADDED' if old is None else 'REMOVED' if new is None else 'MODIFIED',
                    'before_sha256':sha(old) if old is not None else None,
                    'after_sha256':sha(new) if new is not None else None})
    patch.extend(difflib.unified_diff((old or b'').decode('utf-8-sig').splitlines(True),
        (new or b'').decode('utf-8-sig').splitlines(True),fromfile='before/'+name,tofile='after/'+name))
target.mkdir(parents=True)
def write_json(name,value):
    (target/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for name in ('baseline.zip','baseline.json','source-verification.json','run_combined.py','verify_closure.py',
             'save_geometry_checkpoint.py','combined-geometry-1-command.json','combined-geometry-1-result.json'):
    shutil.copyfile(work/name,target/name)
with zipfile.ZipFile(target/'current-source.zip','w',zipfile.ZIP_DEFLATED) as z:
    for name,data in after.items():z.writestr(name,data)
write_json('current-files.json',{'files':[{'path':n,'sha256':sha(v),'bytes':len(v)} for n,v in after.items()]})
write_json('changes.json',{'files':changes,'modified':sum(c['status']=='MODIFIED' for c in changes),
                        'added':sum(c['status']=='ADDED' for c in changes),'removed':sum(c['status']=='REMOVED' for c in changes)})
(target/'changes.patch').write_text(''.join(patch),encoding='utf-8')
for name in ('combined-geometry-1.log','combined-geometry-1-junit.xml',
             'format-test-1.log','format-test-1-junit.xml','MMapDefines.h','primary-format-source.json'):
    shutil.copyfile(work/name,target/name)
references=[
    'native/recastnavigation/Detour/Include/DetourNavMesh.h',
    'native/recastnavigation/Detour/Source/DetourNavMesh.cpp']
write_json('reviewed-layout.json',{'files':[{'path':n,'sha256':sha((root/n).read_bytes())} for n in references],
    'scope':'Trinity MMAP v16 and Detour v7 map/tile headers and section sizes',
    'static_primary_source':json.loads((work/'primary-format-source.json').read_text()),
    'live_validated':False})
verification.update({'selected_regression':{'passed':passed,'skipped':skipped,'unchanged_deselections':10,
    'modules':result['modules'],'exit_code':0,'seconds':result['elapsed_seconds']},
    'source_archive_files':len(after),'numbered_rows_unchanged':203,
    'scope':'source/tests/addon/static references/reports only; no live memory/PKT/user configuration',
    'full_test_repository_claim':False,'new_live_acceptance':False,'client_input':False})
write_json('verification.json',verification)
write_json('artifact-hashes.json',{'files':[{'path':p.relative_to(target).as_posix(),'bytes':p.stat().st_size,
    'sha256':sha(p.read_bytes())} for p in sorted(target.rglob('*')) if p.is_file()]})
print(json.dumps({'checkpoint':str(target),'changes':len(changes),**verification},ensure_ascii=False))

