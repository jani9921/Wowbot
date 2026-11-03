import json, shutil, subprocess, sys
from pathlib import Path
from xml.etree import ElementTree as ET

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent
label='combined-entity-pose-1'
result=json.loads((work/(label+'-result.json')).read_text())
assert result['exit_code']==0
suite=ET.parse(work/(label+'-junit.xml')).getroot()
assert not suite.findall('.//failure') and not suite.findall('.//error')
skipped=len(suite.findall('.//skipped'));passed=len(suite.findall('.//testcase'))-skipped
summary=f'{passed} passed, {skipped} skipped, 10 unchanged deselections, {result["modules"]} modules, exit 0'
base=root/'docs/reform/rev4-20261029'
report='''# REV4 P5/P7 — exact server pose és ismeretlen addon-Z

2026-10-30. A felhasználó pontosítása: Retail addonból nincs használható Z;
a saját world XYZ mozgáscsomagokból érkezik. Offline javítás a kijelölt
`projekt` mappában; új élő elfogadás nincs.

A selected-target megközelítés korábban csak üres addon-pozíció mellett
használta a szerver actorját. Most a meglévő exact GUID / azonos instance /
nem removed / megfelelő kind ellenőrzésű szerverpozíció kap elsőbbséget
akkor is, ha az addon ad nem üres XY-t és hamis z_known / Z=0 értéket.
A kiválasztás és a friss target-azonosság továbbra is addon/UI bizonyíték;
a szerverpozíció nem választ targetet és nem engedélyez F7-et vagy spellt.
A mozgó server recipient ugyanazon reachen frissíti XYZ/layer értékeit.

Az addon-normalizáló minden UNIT_POSITION eredetű target/mouseover/soft-target/
visible-unit magasságot UNKNOWN-ként kezel, a használható XY-t és GUID-ot
megtartja. Az érkező szerver valós Z=0 értéke megmarad. Szerver hiányában
a navigation fallback és controller sem gyárt z=0 / layer_z=0 magasságot.
Az eredeti Observationt a navigáció nem írja át.

A saját álló karakter utolsó szervermagasságának meglévő megtartása és a
HEIGHT_PROBE_TURN változatlan: a korábbi ugrást a 2026-10-28-as mérés után
helyben fordítás váltotta fel. Külön nyitott sorrendi hiba: a typed route
tervezése a controller probe-ja előtt is lefuthat vagy elbukhat. Ez a
checkpoint önmagában még nem a tervezés előtti pozíciószerzés javítása.
A move_to_entity meglévő M0 ága továbbra is közvetlen controller reach;
a require_navmesh jelző jelenléte nem bizonyít tényleges typed MMAP route-ot.
Ennek medium-lane handoffja külön migrációs munka.

Célzott kör: 141 pass. Kijelölt regresszió: **SUMMARY**.
A korábbi tíz deselection változatlan; nem a teljes teszttár futtatása.
Az első célzott parancs egy nem létező modult nevezett meg, ezért ott nem
futott teszt; javított modullistával a két célzott kör 74 / 141 pass lett.
203 számozott coverage-sor változatlan. Addon/Ymir nem módosult.

[Forrás/diff/JUnit/parancs checkpoint](entity-pose-precedence-evidence/verification.json).
Az asszisztens nem indított játékot/capture-t/FULL_AI-t, nem küldött inputot,
nem módosított éles adatbázist. A tizenegy korábbi facing-hiba, teljes Travel/
Combat/Quest migráció és retained-provider paritás továbbra sincs lezárva.
'''.replace('SUMMARY',summary)
(base/'P5_ENTITY_POSE_PRECEDENCE.md').write_text(report,encoding='utf-8')
for name,heading,entry in (
 ('docs/CURRENT_SOURCE_COVERAGE.md','# Current-source coverage ledger\n\n',
  '''2026-10-30 REV4 exact server-pose priority — **OFFLINE_TESTED / full
ownership migration PARTIAL**. Exact scoped server actor XYZ wins over nonempty
addon UnitPosition; numeric Retail addon unit Z remains UNKNOWN. No fabricated
zero layer, selected-target/F7/spell authority unchanged; moving recipient
updates the same reach. Existing own stationary height/probe is preserved,
but pre-route acquisition and M0 typed-route handoff remain separate gaps.
Selected regression: **SUMMARY**. 203 numbered rows unchanged, addon/Ymir
unchanged, no assistant live input/capture/database writes or live acceptance.
See [pose fix/checkpoint](reform/rev4-20261029/P5_ENTITY_POSE_PRECEDENCE.md).

'''),
 ('docs/LIVE_VALIDATION.md','# Live validation evidence and unresolved issues\n\n',
  '''## 2026-10-30 — server pose / addon Z (offline)

Exact scoped server XYZ now wins over a nonempty selected-unit addon point.
UNIT_POSITION height is unknown for all addon recipient forms; real server
Z=0 is preserved. Moving recipient pose follows the same GUID/reach. No
guessed ground layer, target selection, F7 readiness or spell range permission.
Own stationary height/probe remains, pre-route acquisition is a separate gap.
Targeted: 141 pass; selected regression **SUMMARY**, no new live acceptance.
No assistant game/capture/FULL_AI/input/live DB changes; addon/Ymir unchanged.
[Details/checkpoint](reform/rev4-20261029/P5_ENTITY_POSE_PRECEDENCE.md).

''')):
    p=root/name;s=p.read_text(encoding='utf-8-sig');assert heading in s
    p.write_text(s.replace(heading,heading+entry.replace('SUMMARY',summary),1),encoding='utf-8')
for name in ('P1E_P9_IMPLEMENTATION.md','ATVETEL_ES_ATALLASI_TERV.md'):
    p=base/name;s=p.read_text(encoding='utf-8-sig')
    s=s.replace('4015 passed',f'{passed} passed')
    p.write_text(s,encoding='utf-8')
p=base/'P1E_P9_IMPLEMENTATION.md';s=p.read_text(encoding='utf-8')
needle='P3 folytatás: a korrelált saját loginhoz'
assert needle in s
s=s.replace(needle,'''Az [exact server-pose javítás](P5_ENTITY_POSE_PRECEDENCE.md) a nem üres addon
unit-pozíció mellett is a GUID-hoz tartozó szerver XYZ-t használja. Az addon
UNIT_POSITION magassága UNKNOWN, a saját mozgáscsomagos helymeghatározás
tervezés előtti bekötése külön következő feladat.

'''+needle,1);p.write_text(s,encoding='utf-8')
subprocess.run([sys.executable,'-B',str(work/'verify_closure.py')],check=True)
template=(work.parent/'rev4-range-facing-20261030/save_followup_checkpoint.py').read_text(encoding='utf-8')
template=template.replace('range-facing-followup-evidence','entity-pose-precedence-evidence')
template=template.replace('P7_RANGE_FACING_FOLLOWUP.md','P5_ENTITY_POSE_PRECEDENCE.md')
template=template.replace('combined-range-facing-final',label)
template=template.replace('save_followup_checkpoint.py','save_pose_checkpoint.py')
start=template.index("for name in ('combined-entity-pose-1.log'")
end=template.index("verification.update(",start)
template=template[:start]+'''for name in ('combined-entity-pose-1.log','combined-entity-pose-1-junit.xml',
 'pose-test-1.log','pose-test-1-result.json','pose-test-2.log','pose-test-2-junit.xml',
 'pose-test-2-command.json','pose-test-2-result.json','pose-test-3.log','pose-test-3-junit.xml',
 'pose-test-3-command.json','pose-test-3-result.json','run_targeted.py','finish_pose.py'):
    shutil.copyfile(work/name,target/name)
write_json('pose-policy.json',{'exact_same_world_server_pose_precedes_addon':True,
 'addon_unitposition_z_unknown':True,'server_numeric_zero_z_preserved':True,
 'recipient_identity_authority_unchanged':True,'moving_recipient_same_reach':True,
 'pre_route_own_position_acquisition_complete':False,'M0_entity_typed_route_handoff_complete':False,
 'new_live_acceptance':False,'assistant_live_input':False,'live_database_write':False})
'''+template[end:]
(work/'save_pose_checkpoint.py').write_text(template,encoding='utf-8')
subprocess.run([sys.executable,'-B',str(work/'save_pose_checkpoint.py')],check=True)
