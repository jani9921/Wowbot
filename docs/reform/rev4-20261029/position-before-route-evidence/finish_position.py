import json, re, subprocess, sys
from pathlib import Path
from xml.etree import ElementTree as ET

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent;label='combined-position-before-route-final'
result=json.loads((work/(label+'-result.json')).read_text())
assert result['exit_code']==0
suite=ET.parse(work/(label+'-junit.xml')).getroot()
assert not suite.findall('.//failure') and not suite.findall('.//error')
skipped=len(suite.findall('.//skipped'));passed=len(suite.findall('.//testcase'))-skipped
log=(work/(label+'.log')).read_text(encoding='utf-8')
seconds=re.search(r'\d+ passed, \d+ skipped, 10 deselected in ([\d.]+)s',log).group(1)
summary=f'{passed} passed, {skipped} skipped, 10 unchanged deselections, {result["modules"]} modules, exit 0'
base=root/'docs/reform/rev4-20261029'
report='''# REV4 P5 — saját pozíció kérése a grounded 3D route előtt

2026-10-30. Felhasználói pontosítás: addonból nincs saját Z, állva nem
feltétlenül érkezik saját mozgáscsomag; ezért volt a korábbi ugrás.
A meglévő kód a 2026-10-28-as mounted mérés óta egy 0.06 s helyben
fordítást használ HEIGHT_PROBE_TURN néven. Ez a mód megmaradt.

A sorrendi hiba valós volt: start_request már navmesh/Z-tervezést futtatott,
míg a probe csak a későbbi controller.command része volt. Hibás/ambiguous
rétegből a route már előtte elbukhatott, így a probe nem futhatott le.

Most a live packet-lane-nel rendelkező, grounded, MMAP-ot igénylő world
request hiányzó saját megfigyelt magasságnál először pozíciót kér. Ugyanaz
a NavigationService és ReachMovementController marad az egyetlen owner.
A pending rész nem hív globális/lokális útvonaltervezést és nem állít
megérkezést; egy bound turn commandot javasol, utána nem küld előremenetet.
A binding hiánya nem válik kitalált billentyűvé. Az érkező koordinátát a
meglévő own packet reducer/projector adja; nincs memory-reader vagy új parser.

A gyors lane a használható own pozíciónál leengedi a mozgási lease-t és
movement_position_acquired_pending okkal medium handoffot kér. Nem hív
nehéz route queryt. A MovementSkillRunner medium lépése ugyanazt a requestet,
eredeti célt és kezdőidőt folytatja a megfigyelt Z-ből. A lokális query-út is
blokkolva van a first fix előtt; a controller observe sem rejt route queryt
az új pending fázis mögé.

A várás maximum 3 s vagy az eredeti rövidebb request budgetje. Az ismételt
same-request start nem indít új órát. TIMEOUT itt POSITION_UNCERTAIN,
kontextusváltás WRONG_MAP_CONTEXT; dialog/cast/combat/death/fall/vehicle
átmenet megszakít. Cancel/reset eldobja a pending requestet; késői packet
önmagában nem indítja újra. Az álló helyzetben megtartott megfigyelt own
Z nem vált ki új probe-ot. Vision/legacy, már repülő és vehicle ágak saját
meglévő szerződése változatlan; ez még nem minden flight/vehicle first-fix
és nem a közvetlen M0 move_to_entity typed-route migrációja.

A position_acquisition snapshot a controller resetje után is bounded módon
megőrzi az utolsó frissítő command-JAVASLATOT, eredeti időt, acquired Z-t /
forrást, tervezési eredményt vagy valódi hibát. Sikertelen mozgásnál bekerül
a NAVIGATION_FAILURE_DETAIL eseménybe. A javaslat nem állítja, hogy a fizikai
input ténylegesen lement; az a meglévő dispatcher/executor nyomából igazolandó.
Nincs teljes world/corridor/packet body másolás vagy tickenkénti DB-írás.

Célzott végső kör: 112 pass; további flight/travel regresszió: 71 pass
(átfedő körök, nem összeadandók). Kijelölt regresszió: **SUMMARY**, PYTEST s
pytest / RUNNER s runner. A 10 korábbi deselection változatlan, nem teljes
teszttár-futtatás. 558 source és 634 test Python-fájl AST-ellenőrzött,
203 számozott coverage-sor változatlan.

[Forrás/diff/JUnit/parancs checkpoint](position-before-route-evidence/verification.json).
Az előző exact server-pose checkpoint megmaradt. Addon/Ymir változatlan;
az asszisztens nem indított játékot/capture-t/FULL_AI-t, nem küldött kliens-
inputot és nem írt éles DB-t. A jelenlegi javítás OFFLINE_TESTED. Új élő
probe/quest elfogadás, a korábbi 11 facing-hiba teljes magyarázata, a nagy
Combat/Travel/Quest felelősségmigráció és retained-provider paritás nyitott.
'''.replace('SUMMARY',summary).replace('PYTEST',seconds).replace('RUNNER',f'{result["elapsed_seconds"]:.2f}')
(base/'P5_POSITION_BEFORE_ROUTE.md').write_text(report,encoding='utf-8')
for name,heading,entry in (
 ('docs/CURRENT_SOURCE_COVERAGE.md','# Current-source coverage ledger\n\n',
  '''2026-10-30 REV4 P5 own-position acquisition before grounded 3D routing —
**OFFLINE_TESTED / full migration PARTIAL**. A live packet-assisted MMAP
request with unknown own height first proposes the existing bound 0.06 s
turn and awaits real own movement feedback. No route query, forward command
or arrival before that fix; FAST yields planning to the same medium owner.
Original trip/goal/deadline survives; pending budget <=3 s, scope/identity/
input transitions stop it, cancel cannot silently rearm. Bounded proposal/
acquisition/failure details survive controller reset and enter terminal logs.
Selected regression **SUMMARY**, PYTEST s pytest; 558 source + 634 tests
parse, all 203 rows preserved. Targeted 112 pass and flight/travel 71 pass
overlap. Addon/Ymir unchanged, no assistant client input/capture/live DB writes
or new live acceptance. Direct M0 entity typed routing and full provider/
domain migration remain open. [Details](reform/rev4-20261029/P5_POSITION_BEFORE_ROUTE.md).

'''),
 ('docs/LIVE_VALIDATION.md','# Live validation evidence and unresolved issues\n\n',
  '''## 2026-10-30 — grounded own first-fix before routing (offline)

The user's reminder about the old jump exposed ordering: typed planning could
fail before the existing HEIGHT_PROBE_TURN ran. The same owner now requests
the first measured own height before its grounded packet-assisted MMAP route,
awaits feedback without forward/arrival, then FAST hands route work to medium.
Same goal/request/deadline, <=3 s budget, no guessed key or Z=0, context/input
transitions stop; reset/cancel prevents late rearming. Bounded command-
proposal/acquired-Z/plan/failure diagnostics survive controller reset.
Selected regression **SUMMARY**, PYTEST s pytest. Targeted 112 pass plus
71 flight/travel pass overlap; no new live proof of probe/quest completion.
558 source + 634 tests parse, 203 rows preserved. Addon/Ymir unchanged, no
assistant game/capture/FULL_AI/input/live DB changes. Broader entity/flight
first-fix and the full migration remain open.
[Details/checkpoint](reform/rev4-20261029/P5_POSITION_BEFORE_ROUTE.md).

''')):
    p=root/name;s=p.read_text(encoding='utf-8-sig');assert heading in s
    entry=entry.replace('SUMMARY',summary).replace('PYTEST',seconds)
    p.write_text(s.replace(heading,heading+entry,1),encoding='utf-8')
for name in ('P1E_P9_IMPLEMENTATION.md','ATVETEL_ES_ATALLASI_TERV.md'):
    p=base/name;s=p.read_text(encoding='utf-8-sig')
    s=s.replace('4029 passed',f'{passed} passed').replace('324 modul','325 modul')
    s=s.replace('163.87 s',seconds+' s')
    s=s.replace('557 source + 633 tests Python-fájl; 632 test_*.py',
                '558 source + 634 tests Python-fájl; 633 test_*.py')
    s=s.replace('teljes 632 modulos','teljes 633 modulos')
    p.write_text(s,encoding='utf-8')
p=base/'P1E_P9_IMPLEMENTATION.md';s=p.read_text(encoding='utf-8')
needle='P3 folytatás: a korrelált saját loginhoz';assert needle in s
s=s.replace(needle,'''A [grounded own first-fix](P5_POSITION_BEFORE_ROUTE.md) most már a route-query
előtt történik: a meglévő helyben fordítás utáni mozgáscsomagot várja, és a
medium lane az eredeti célt/időkeretet folytatja. Ez nem teljes flight/vehicle
first-fix vagy M0 entity-route migráció; az új élő próba még nyitott.

'''+needle,1);p.write_text(s,encoding='utf-8')
subprocess.run([sys.executable,'-B',str(work/'verify_closure.py')],check=True)
template=(work.parent/'rev4-entity-pose-precedence-20261030/save_pose_checkpoint.py').read_text(encoding='utf-8')
template=template.replace('entity-pose-precedence-evidence','position-before-route-evidence')
template=template.replace('P5_ENTITY_POSE_PRECEDENCE.md','P5_POSITION_BEFORE_ROUTE.md')
template=template.replace('combined-entity-pose-1',label).replace('save_pose_checkpoint.py','save_position_checkpoint.py')
start=template.index("for name in ('combined-position-before-route-final.log'")
end=template.index('verification.update(',start)
template=template[:start]+'''for name in ('combined-position-before-route-final.log','combined-position-before-route-final-junit.xml',
 'combined-position-before-route-1.log','combined-position-before-route-1-result.json',
 'position-test-1.log','position-test-1-junit.xml','position-test-1-command.json','position-test-1-result.json',
 'position-test-2.log','position-test-2-junit.xml','position-test-2-command.json','position-test-2-result.json',
 'position-flight-1.log','position-flight-1-junit.xml','position-flight-1-command.json','position-flight-1-result.json',
 'run_targeted.py','finish_position.py'):
    shutil.copyfile(work/name,target/name)
write_json('position-policy.json',{'grounded_packet_assisted_first_fix_precedes_route':True,
 'existing_single_controller_probe':True,'no_forward_before_fix':True,'fast_planning_query':False,
 'same_original_request_goal_deadline':True,'probe_wait_max_seconds':3,
 'cancel_does_not_rearm':True,'bounded_terminal_probe_trace':True,
 'all_flight_vehicle_first_fix_complete':False,'M0_entity_typed_route_handoff_complete':False,
 'new_live_acceptance':False,'assistant_live_input':False,'live_database_write':False})
'''+template[end:]
(work/'save_position_checkpoint.py').write_text(template,encoding='utf-8')
subprocess.run([sys.executable,'-B',str(work/'save_position_checkpoint.py')],check=True)
