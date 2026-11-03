import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work = Path(__file__).parent
label, *modules = sys.argv[1:]
assert '/' not in label and '\\' not in label
assert modules and not (work/(label+'-command.json')).exists()
command = [sys.executable, '-B', '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider',
           '--basetemp', str(work/(label+'-temp')), '--junitxml', str(work/(label+'-junit.xml')), *modules]
env = dict(os.environ, PYTHONPATH=str(root/'src'), PYTHONIOENCODING='utf-8',
           AIPC_SEMANTIC_ENABLED='0', AIPC_REFERENCE_CATALOG=str(work/'no-reference.sqlite3'),
           TEMP=str(work), TMP=str(work))
(work/(label+'-command.json')).write_text(json.dumps(command,indent=2),encoding='utf-8')
start = time.monotonic()
with (work/(label+'.log')).open('w',encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
report = dict(exit_code=result.returncode, elapsed_seconds=time.monotonic()-start)
(work/(label+'-result.json')).write_text(json.dumps(report),encoding='utf-8')
print(json.dumps(report))
print((work/(label+'.log')).read_text(encoding='utf-8')[-14000:])
sys.exit(result.returncode)
