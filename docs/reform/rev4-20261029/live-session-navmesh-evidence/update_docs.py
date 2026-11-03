from pathlib import Path
root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent
def update(relative,before,after):
    path=root/relative
    value=path.read_text(encoding='utf-8-sig')
    assert before in value,relative
    path.write_text(value.replace(before,after,1),encoding='utf-8')

report='docs/reform/rev4-20261029/P2_LIVE_SESSION_NAVMESH_FIXES.md'
update(report,'A széles regresszió eredménye a checkpointban kerül rögzítésre.',
'''A végső kijelölt regresszió **3984 passed, 2 skipped, 10 változatlan
deselection, 322 modul, exit 0**, pytest 296.70 s / runner 301.02 s.
Mind az 552 source és 631 test Python-fájl AST-je érvényes; a teljes 630
testmodulból a kijelölt 322 futott. A számozott 203 coverage-sor megmaradt.

[Forrás/diff/parancs/JUnit/fejléc/capture-probe checkpoint](live-session-navmesh-evidence/verification.json).
A korábbi három checkpoint összes artifact- és forrás-ZIP-hashe is ellenőrizve.''')
coverage='''2026-10-30 REV4 live-log regression fixes — **OFFLINE_TESTED / full migration
PARTIAL**. User-operated morning/afternoon runs exposed a valid signed Trinity
maxPolys capacity rejected by the new format gate and realm/instance login
connections split across indices. The exact reviewed capacity is accepted
without relaxing other format checks. Different-connection session binding
requires exact pending login GUID, world/map/order and public ThisIsYou
ActivePlayer CREATE; no guessed connection or private-player probe. Relogin
rotates epoch and drops replay/ownership/progress caches even within one file.
Recorded user capture replay reaches READY and reviewed own fields. Actual
saved-pose native routing on map 0 is READY; the map 2444 start remains outside
the ground mesh with unknown Z. Neither is a completed live quest. Selected
regression: **3984 passed, 2 skipped, 10 unchanged deselections, 322 modules,
exit 0**, 296.70 s pytest; 552 source + 631 test Python files parse, 203 numbered
rows unchanged. No assistant client/capture/FULL_AI/input/live DB actions;
addon/Ymir unchanged. Retained state, full provider parity, large Combat/Travel/
Quest ownership migration and new live acceptance remain open.
See [log fixes and checkpoint](reform/rev4-20261029/P2_LIVE_SESSION_NAVMESH_FIXES.md).

'''
update('docs/CURRENT_SOURCE_COVERAGE.md','# Current-source coverage ledger\n\n',
       '# Current-source coverage ledger\n\n'+coverage)
live='''## 2026-10-30 — user-run logs inspected; navmesh/session fixes offline-tested

Morning statuses showed working map 0 Detour routing; afternoon statuses
showed map_parameters_invalid after the new map header validation. The exact
reviewed Trinity signed capacity was incorrectly rejected; corrected with
all other format checks retained. A saved-pose real ZIP/native DLL query now
returns READY for the corpse approach. Map 2444 loads but its unknown-Z start
is not on the ground mesh; that travel case is not declared solved.

The captured realm login and instance-world verification use different
connections. Correlation now also requires the exact login GUID's public
ThisIsYou ActivePlayer create on the verified world connection/map, with
bounded time/order and no private-player probing. Same-file relogin rotates
epoch and clears ownership/fragments/replay/progress. A user capture decoded
offline reaches provider READY with own questlog/inventory/profile/health;
it is not a post-fix live FULL_AI acceptance. Session recovery does not revive
old collection fields or grant input/UI freshness.

Selected regression: **3984 passed, 2 skipped, 10 unchanged deselections**,
322 modules, 296.70 s pytest / 301.02 s runner, exit 0; 552 source + 631 test
Python files parse, all 203 numbered rows persist. No assistant game/capture/
FULL_AI/input/live memory DB changes. User owns live tests; older running
GUI/bridge processes may still contain pre-fix code. Addon/Ymir unchanged.
[Details and bounded evidence](reform/rev4-20261029/P2_LIVE_SESSION_NAVMESH_FIXES.md).

'''
update('docs/LIVE_VALIDATION.md','# Live validation evidence and unresolved issues\n\n',
       '# Live validation evidence and unresolved issues\n\n'+live)
base='docs/reform/rev4-20261029/'
update(base+'P1E_P9_IMPLEMENTATION.md',
       'A per-field\nretained lifecycle és warm collection baseline továbbra is külön kódos kapu.',
       '''A per-field
retained lifecycle és warm collection baseline továbbra is külön kódos kapu.
A felhasználói mai logokból két regressziót is javítottunk:
[szabályos signed MMAP-kapacitás és realm→instance login](P2_LIVE_SESSION_NAVMESH_FIXES.md).
A korábban kizárólag same-connection szabályt explicit saját ActivePlayer-
bizonyíték egészíti ki; az új session nem örököl régi cache-t. A rögzített
capture visszaolvasása sikeres, új élő FULL_AI-elfogadás továbbra sincs.''')
update(base+'P1E_P9_IMPLEMENTATION.md',
       '- Saját GUID csak azonos kapcsolaton korrelált CMSG_PLAYER_LOGIN és SMSG_LOGIN_VERIFY_WORLD alapján keletkezik.',
       '- Saját GUID korrelált CMSG_PLAYER_LOGIN és SMSG_LOGIN_VERIFY_WORLD alapján keletkezik. Külön instance-kapcsolatnál ezen felül pontos GUID/map/sorrend szerinti ThisIsYou ActivePlayer CREATE szükséges.')
for relative in (base+'P1E_P9_IMPLEMENTATION.md',base+'ATVETEL_ES_ATALLASI_TERV.md'):
    path=root/relative;value=path.read_text(encoding='utf-8-sig')
    value=value.replace('3956 passed','3984 passed').replace('321 modul','322 modul').replace('169.76 s','296.70 s')
    value=value.replace('551 source + 630 tests Python-fájl; 629 test_*.py','552 source + 631 tests Python-fájl; 630 test_*.py')
    value=value.replace('teljes 629 modulos','teljes 630 modulos')
    path.write_text(value,encoding='utf-8')
for relative in (base+'P1E_MMAP_FORMATS.md',base+'P2_APPLIED_PACKET_PROGRESS.md'):
    path=root/relative;value=path.read_text(encoding='utf-8-sig')
    first,rest=value.split('\n',1)
    note='\nKésőbbi mai korrekció: [élő logból javított MMAP/session regressziók](P2_LIVE_SESSION_NAVMESH_FIXES.md). A lentebbi mérés az akkori történeti checkpoint eredménye.\n'
    path.write_text(first+'\n'+note+rest,encoding='utf-8')
print('current reports updated; numbered requirement rows unchanged')
