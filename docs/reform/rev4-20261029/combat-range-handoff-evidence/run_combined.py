import json,os,subprocess,sys,time
from pathlib import Path
root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent
label=sys.argv[1] if len(sys.argv)>1 else 'combined-live-regression-1'
assert label.startswith('combined-') and '/' not in label and '\\' not in label
previous=json.loads(Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1d-20261029/release-command.json').read_text(encoding='utf-8'))
modules=[a for a in previous['command'] if a.startswith('tests/') and a.endswith('.py')]
for path in sorted((root/'tests').glob('test_*2026103*.py')):
    name=path.relative_to(root).as_posix()
    if name not in modules:modules.append(name)
for name in ('test_geometry_query_contracts_20261029.py','test_session_bootstrap_20261029.py','test_field_sources_20261029.py'):
    item='tests/'+name
    if item not in modules:modules.append(item)
command=[sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--basetemp',str(work/(label+'-temp')),
         '--junitxml',str(work/(label+'-junit.xml')),*modules,'-k',previous['command'][-1]]
env={**os.environ,'PYTHONPATH':str(root/'src'),'PYTHONIOENCODING':'utf-8','TEMP':str(work),'TMP':str(work),
     'AIPC_SEMANTIC_ENABLED':'0','AIPC_REFERENCE_CATALOG':str(work/'absent-reference.sqlite3')}
(work/(label+'-command.json')).write_text(json.dumps({'command':command,'modules':modules,'baseline_filter_unchanged':True},indent=2),encoding='utf-8')
started=time.monotonic()
with (work/(label+'.log')).open('w',encoding='utf-8') as log:
    result=subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
report={'exit_code':result.returncode,'elapsed_seconds':time.monotonic()-started,'modules':len(modules)}
(work/(label+'-result.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
print('\n'.join((work/(label+'.log')).read_text(encoding='utf-8').splitlines()[-100:]))
raise SystemExit(result.returncode)
