import json, os, subprocess, sys, time
from pathlib import Path
root=Path("C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt")
work=Path("C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-inventory-roots-20261030")
previous=json.loads(Path(r"C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1d-20261029/release-command.json").read_text(encoding="utf-8"))
modules=[arg for arg in previous['command'] if arg.startswith('tests/') and arg.endswith('.py')]
for path in sorted((root/"tests").glob("test_*2026103*.py")):
    name=path.relative_to(root).as_posix()
    if name not in modules: modules.append(name)
for name in ("test_geometry_query_contracts_20261029.py","test_session_bootstrap_20261029.py","test_field_sources_20261029.py"):
    item="tests/"+name
    if item not in modules:modules.append(item)
expr=previous["command"][-1]
command=[sys.executable,"-B","-m","pytest","-q","-p","no:cacheprovider","--basetemp",str(work/"pytest-combined-inventory-roots-1"),"--junitxml",str(work/"combined-inventory-roots-1-junit.xml"),*modules,"-k",expr]
env={**os.environ, "PYTHONPATH":str(root/"src"), "PYTHONIOENCODING":"utf-8","TEMP":str(work),"TMP":str(work),"AIPC_SEMANTIC_ENABLED":"0","AIPC_REFERENCE_CATALOG":str(work/"absent-reference.sqlite3")}
(work/"combined-inventory-roots-1-command.json").write_text(json.dumps({"command":command,"modules":modules,"baseline_filter_unchanged":True},indent=2),encoding="utf-8")
started=time.perf_counter()
with (work/"combined-inventory-roots-1.log").open("w",encoding="utf-8") as log:
    result=subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
report={"exit_code":result.returncode,"elapsed_seconds":time.perf_counter()-started,"modules":len(modules),"log":str(work/"combined-inventory-roots-1.log")}
(work/"combined-inventory-roots-1-result.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps(report))
print("\n".join((work/"combined-inventory-roots-1.log").read_text(encoding="utf-8").splitlines()[-100:]))
sys.exit(result.returncode)










