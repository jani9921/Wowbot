import ast
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from xml.etree import ElementTree as ET

root = Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work = Path(__file__).parent
target = root/'docs/reform/rev4-20261029/golem-item-20261102-evidence'
assert not target.exists()
sha = lambda data: hashlib.sha256(data).hexdigest()
with zipfile.ZipFile(work/'before.zip') as archive:
    before = {name: archive.read(name) for name in archive.namelist()}
names = set(before)|{'src/wowbot/quests/item_target_conditions.py',
    'tests/test_item_summon_objective_20261102.py','docs/LIVE_TEST_FIXES_20261102_GOLEM_ITEM.md'}
after = {name: (root/name).read_bytes() for name in sorted(names)}
changes = []
patch = []
for name, data in after.items():
    old = before.get(name, b'')
    if name.endswith('.py'):
        ast.parse(data.decode('utf-8-sig'), filename=name)
    if old == data:
        continue
    changes.append({'path':name,'before_sha256':sha(old) if old else None,
                    'after_sha256':sha(data)})
    patch.extend(difflib.unified_diff(old.decode('utf-8-sig').splitlines(True),
        data.decode('utf-8-sig').splitlines(True), fromfile='before/'+name,tofile='after/'+name))
result = json.loads((work/'regression-final-result.json').read_text())
suite = ET.parse(work/'regression-final-junit.xml').getroot()
cases = suite.findall('.//testcase')
assert result['exit_code'] == 0 and not suite.findall('.//failure') and not suite.findall('.//error')
skips = len(suite.findall('.//skipped'))
target.mkdir(parents=True)
with zipfile.ZipFile(target/'changed-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for name, data in after.items():
        archive.writestr(name,data)
for name in ('before.json','before.zip','run_tests.py','regression-final-command.json',
             'regression-final-result.json','regression-final-junit.xml','regression-final.log',
             'catalogue-probe.json','live-summary.json','save_evidence.py'):
    shutil.copyfile(work/name,target/name)
(target/'changes.patch').write_text(''.join(patch),encoding='utf-8')
(target/'changes.json').write_text(json.dumps(changes,indent=2),encoding='utf-8')
summary={'status':'OFFLINE_TESTED','passed':len(cases)-skips,'skipped':skips,
         'test_modules':27,'new_live_acceptance':False,'live_client_input':False,
         'catalogue_read_only':True,'raw_packet_export':False,'vision_changes':False}
(target/'verification.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
hashes={p.name:sha(p.read_bytes()) for p in target.iterdir() if p.is_file()}
(target/'artifact-hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
assert all(sha((target/name).read_bytes()) == digest for name,digest in hashes.items())
print(json.dumps({'checkpoint':str(target),**summary,'changed_files':len(changes)}))
