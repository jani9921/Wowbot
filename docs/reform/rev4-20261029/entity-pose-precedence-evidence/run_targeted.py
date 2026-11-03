import json,os,subprocess,sys,time
from pathlib import Path
work=Path(__file__).parent
root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
name=sys.argv[1]
modules=sys.argv[2:]
assert modules and not name.startswith('-')
env={**os.environ,'PYTHONPATH':str(root/'src'),'PYTHONIOENCODING':'utf-8',
     'TEMP':str(work),'TMP':str(work),'AIPC_SEMANTIC_ENABLED':'0',
     'AIPC_REFERENCE_CATALOG':str(work/'absent-reference.sqlite3')}
command=[sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',
    '--basetemp',str(work/(name+'-temp')),'--junitxml',str(work/(name+'-junit.xml')),*modules]
(work/(name+'-command.json')).write_text(json.dumps({'command':command},indent=2)+'\n')
start=time.monotonic()
with (work/(name+'.log')).open('w',encoding='utf-8') as out:
    result=subprocess.run(command,cwd=root,env=env,stdout=out,stderr=subprocess.STDOUT)
(work/(name+'-result.json')).write_text(json.dumps({'exit_code':result.returncode,
 'elapsed_seconds':time.monotonic()-start},indent=2)+'\n')
print((work/(name+'.log')).read_text(encoding='utf-8')[-7000:])
raise SystemExit(result.returncode)
