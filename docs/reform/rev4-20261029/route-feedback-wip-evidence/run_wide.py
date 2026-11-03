"""4083-checkpoint module list + original -k filter, plus new 2026103* modules (Claude, 2026-10-30)."""
import glob, json, os, subprocess, sys, time
from pathlib import Path

work = Path(__file__).parent
root = Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
name = sys.argv[1]
base = json.loads((root / 'docs/reform/rev4-20261029/domain-navigation-handoff-evidence/'
                   'combined-domain-navigation-final-command.json').read_text(encoding='utf-8'))['command']
modules = [x for x in base if str(x).startswith('tests')]
k = [base[i + 1] for i, x in enumerate(base) if x == '-k'][-1]
extra = sorted(Path(p).relative_to(root).as_posix() for p in glob.glob(str(root / 'tests/test_*2026103*.py')))
added = [m for m in extra if m not in modules]
modules += added
env = {**os.environ, 'PYTHONPATH': str(root / 'src'), 'PYTHONIOENCODING': 'utf-8', 'TEMP': str(work), 'TMP': str(work),
       'AIPC_SEMANTIC_ENABLED': '0', 'AIPC_REFERENCE_CATALOG': str(work / 'absent-reference.sqlite3')}
command = [sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--basetemp', str(work / (name + '-temp')),
           '--junitxml', str(work / (name + '-junit.xml')), '-k', k, *modules]
(work / (name + '-command.json')).write_text(json.dumps({'command': command, 'added_modules': added}, indent=2) + '\n')
start = time.monotonic()
with (work / (name + '.log')).open('w', encoding='utf-8') as out:
    result = subprocess.run(command, cwd=root, env=env, stdout=out, stderr=subprocess.STDOUT)
(work / (name + '-result.json')).write_text(json.dumps({'exit_code': result.returncode, 'modules': len(modules),
                                                        'added_modules': added,
                                                        'elapsed_seconds': time.monotonic() - start}, indent=2) + '\n')
print('added', added)
print((work / (name + '.log')).read_text(encoding='utf-8')[-3000:])
raise SystemExit(result.returncode)
