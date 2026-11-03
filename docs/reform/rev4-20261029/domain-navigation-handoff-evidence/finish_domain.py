import json,re,subprocess,sys
from pathlib import Path
from xml.etree import ElementTree as ET

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent;label='combined-domain-navigation-final'
result=json.loads((work/(label+'-result.json')).read_text())
assert result['exit_code']==0
suite=ET.parse(work/(label+'-junit.xml')).getroot()
assert not suite.findall('.//failure') and not suite.findall('.//error')
skipped=len(suite.findall('.//skipped'));passed=len(suite.findall('.//testcase'))-skipped
log=(work/(label+'.log')).read_text(encoding='utf-8')
seconds=re.search(r'\d+ passed, \d+ skipped, 10 deselected in ([\d.]+)s',log).group(1)
summary=f'{passed} passed, {skipped} skipped, 10 unchanged deselections, {result["modules"]} modules, exit 0'
base=root/'docs/reform/rev4-20261029'
report='''# REV4 P5/P7 — közös M0 entity route és medium handoff

2026-10-30. Aktív munkamappa a felhasználó által kijelölt `projekt`.
OFFLINE_TESTED; új élő elfogadás nincs.

## A ténylegesen cserélt futási út

A move_to_entity korábban require_navmesh jelző mellett is a közvetlen
controller.start ágat hívta. Most a selected/soft GUID, same-world pose,
fresh recipient és reachability ellenőrzés után egy NavigationRequest kerül
a meglévő GlobalNavigator → corridor → controller → TripExecutor láncra.
A szerverpozíciós ág bizonyított geometry route-ot igényel; hiányzó meshből
nem lesz közvetlen előresétálás. A legacy/cue szerződés közös API-n marad,
a korábbi explicit gyengébb direkt-fallbacket nem nevezzük MMAP-bizonyítéknak.

COMBAT/DEFEND, INTERACT/TALK és LOOT runtime-ja ugyanazt a canonical NavService-t
használja. FAST esetben a request a szolgáltatás egyetlen bounded pending
mezőjébe kerül, nincs query/input/új action. A gyors supervisor explicit medium
handoffot kér; a main runner friss scope/GUID/inputállapot/deadline mellett
tervez. Nem hívja újra a domén verifiert és nem fogyaszt második retry-t.
Az entity-local LOS utolsó route-lépése is ezt az ágat használja, legfeljebb
2.5 s eredeti időkerettel. A kiadott parancsot a meglévő dispatcher végzi;
nincs második skill, planner vagy input-owner.

A start/request és a Trip eredeti kezdőideje megmarad a pending/own-first-fix/
mozgó-cél replan között. A nested combat/interaction/loot eredeti attempt-
deadline-ja minden folytatás előtt ellenőrzött. Cancel/reset eldobja a pending
requestet; késői adat nem indítja újra. Hiányzó vagy változott identitás,
scopeváltás és tiltott inputállapot nem lesz új geometriaterv/jogosultság.

## Mozgó cél és megérkezés

Az entity_goal célazonossága a pinned GUID, kezdeti XYZ-je helypillanatkép.
Két yardnál nagyobb változás medium replant kér az aktuális, ugyanahhoz az
actorhoz tartozó pontra. A controller köztes útvonalpontját a target/recipient
követés nem írhatja felül; a végső facing az élő actorhoz igazodik. A Trip
az eredeti GUID-hoz tartozó aktuális pontot ellenőrzi. Statikus quest/forge-
corner célokra ez nem vonatkozik: azok eredeti végpontja megmarad.

Az új typed út egyik regressziója az ismert actor layer_z-jét direct legacy
anchor mellett None-ra cserélte; a régi emelet-teszt ezt megfogta. A végső
anchor most megtartja a valóban ismert célmagasságot (a Z=0 is valós érték
lehet), az ismeretlen addon-Z továbbra sem lesz 0. A másik nagy körbeli hiba
egy régi pozitív loot-fixture hiányzó coordinate_space jelölése volt; a
fixture WORLD_YARDS szerződést kapott, az eredeti F7-elvárás változatlan.
A korábbi direct-follow spy tesztjei az új typed/medium határt ellenőrzik;
nem lett teszt kizárva vagy assertion törölve a viselkedés elfedésére.

A nested megérkezés/failure most explicit fizikai movement-stopot kér a
diszkrét F7/cast előtt. Egy külön preserve_navigation jelzés biztosítja,
hogy a tervezési handoff miatti inputfelengedés ne törölje a saját pending
requestet. Rendes STOP/MANUAL továbbra is töröl. A navigation failure bounded
ok/facing/sample/probe részlete még a reset előtt megmarad és egyszer
SKILL_NAVIGATION_FAILURE_DETAIL eseményként naplózódik; nem teljes world /
corridor vagy nyers packet body kerül lemezre.

## Saját magasság és holttest

A FAST addon XY overlay eltakarhatta a már ismert szervermagasságot, így a
first-fix várás a friss packet ellenére timeoutolhatott. A medium és FAST
most ugyanazt a project_own_navigation implementációt használja. A megtartott
own Z csak változatlan közeli XY/scope mellett érvényes; eredeti packet-idő
nem frissül. Native continuity GAP-ben az örökölt packet-Z sem marad ismert.
Új process-memory reader, parser vagy capture backend nem került be.

A corpse-approach a same-GUID/same-world szerverpozíciót is felhasználja,
explicit allow_dead pozíciós opcióval. Ez nem lootjog: a meglévő dead/selected/
soft-recipient/loot-verifier szerződés marad. Egyszerű UNIT_DIED vagy egy
koordináta nem hoz létre owned-corpse/loot eligibility bizonyítékot.

## Ellenőrzés és nyitott kapuk

Domén/navigation célzott kör: 228 pass; a regressziójavítás külön 110 pass
(átfedő körök, nem összeadandók). A tényleges Python MMAP backend kétpolygonos
formátum-fixture-én is végigment az entity API. Más testek determinisztikus
geometry API tesztduplát használnak: egyik sem élő/native klienselfogadás.

Végső kijelölt regresszió: **SUMMARY**, PYTEST s pytest / RUNNER s runner.
560 source + 635 test Python-fájl AST-ellenőrzött; 203 számozott sor megmarad.
A 10 korábbi deselection változatlan, a teljes 634 modulos teszttár nem futott.
[Forrás/diff/parancs/JUnit checkpoint](domain-navigation-handoff-evidence/verification.json).

Az asszisztens nem indított WoW-ot/Ymir-t/capture-t/FULL_AI-t, nem küldött
kliensinputot és nem írt éles adatbázist. Addon/Ymir változatlan.

Nyitott: új élő entity/loot/route/facing próba; a korábbi 11 facing-hiba teljes
magyarázata; általános FAST route-requery audit; a main route-query továbbra
szinkron és cold mesh betöltés alatt az agent lock késleltetheti a vezérlést.
Külön P4-audit szükséges a hosszú számítás után közvetlenül kiadott command
forráskorának ellenőrzésére (a tick eleji freshness önmagában nem dispatch-
pillanatbeli bizonyíték). A nagy Combat/Travel/Quest felelősségbontás, retained
provider/collection paritás és teljes REV4 M0/M1 elfogadás továbbra is PARTIAL.
'''.replace('SUMMARY',summary).replace('PYTEST',seconds).replace('RUNNER',f'{result["elapsed_seconds"]:.2f}')
(base/'P5_DOMAIN_NAVIGATION_HANDOFF.md').write_text(report,encoding='utf-8')
for name,heading,entry in (
 ('docs/CURRENT_SOURCE_COVERAGE.md','# Current-source coverage ledger\n\n',
  '''2026-10-30 REV4 P5/P7 canonical entity approaches — **OFFLINE_TESTED / full
migration PARTIAL**. M0 combat/interaction/loot and final LOS now enter typed
shared navigation; server routes require geometry, FAST defers queries to the
same medium owner without another retry/action. Original deadline/goal/GUID
survives; moving entity goals replan without rewriting corridor anchors.
Physical release precedes arrival interaction; explicit handoff preserves only
its owned request. Bounded nested navigation failure details persist. FAST and
medium share one scoped own-Z projection, continuity GAP clears inherited Z;
corpse pose does not imply loot entitlement. Selected regression **SUMMARY**,
PYTEST s pytest; 560 source + 635 tests parse, 203 rows unchanged. Main-query
blocking, dispatch-time source freshness, full provider/domain migration and
live acceptance remain open. Addon/Ymir unchanged, no assistant client input/
capture/live DB writes. [Details](reform/rev4-20261029/P5_DOMAIN_NAVIGATION_HANDOFF.md).

'''),
 ('docs/LIVE_VALIDATION.md','# Live validation evidence and unresolved issues\n\n',
  '''## 2026-10-30 — shared M0 entity routing and medium handoff (offline)

Combat/interaction/loot + final LOS enter shared typed routing; FAST only
queues the same owned request and releases input for medium planning. Live
GUID pose, original clocks/budgets, separate corpse eligibility, route-anchor
preservation, known floor and final facing gates remain. FAST own-Z overlay
loss is fixed through the same canonical packet projection; GAP drops held Z.
Bounded nested failure details survive reset and physical release precedes
F7/cast. Existing positive legacy fixture now states WORLD_YARDS explicitly;
original loot expectation stays. Known layer regression was fixed in source.
Targeted 228 pass + regression-fix 110 pass overlap. Final selected regression
**SUMMARY**, PYTEST s pytest; 203 rows unchanged. No assistant game/capture/
FULL_AI/input/live DB changes; addon/Ymir unchanged, no new live acceptance.
Main synchronous route blocking and late dispatch freshness need the next P4
audit; general role/provider/domain migration and prior facing cases remain.
[Details/checkpoint](reform/rev4-20261029/P5_DOMAIN_NAVIGATION_HANDOFF.md).

''')):
    p=root/name;s=p.read_text(encoding='utf-8-sig');assert heading in s
    entry=entry.replace('SUMMARY',summary).replace('PYTEST',seconds)
    p.write_text(s.replace(heading,heading+entry,1),encoding='utf-8')
for name in ('P1E_P9_IMPLEMENTATION.md','ATVETEL_ES_ATALLASI_TERV.md'):
    p=base/name;s=p.read_text(encoding='utf-8-sig')
    s=s.replace('4057 passed',f'{passed} passed').replace('325 modul',f'{result["modules"]} modul')
    s=s.replace('176.38 s',seconds+' s')
    s=s.replace('558 source + 634 tests Python-fájl; 633 test_*.py',
                '560 source + 635 tests Python-fájl; 634 test_*.py')
    s=s.replace('teljes 633 modulos','teljes 634 modulos')
    s=re.sub(r'Ez \*\*\d+ kijelölt modul eredménye\*\*',f'Ez **{result["modules"]} kijelölt modul eredménye**',s)
    p.write_text(s,encoding='utf-8')
p=base/'P1E_P9_IMPLEMENTATION.md';s=p.read_text(encoding='utf-8')
needle='P3 folytatás: a korrelált saját loginhoz';assert needle in s
s=s.replace(needle,'''A [közös M0 entity route/handoff](P5_DOMAIN_NAVIGATION_HANDOFF.md) elkészült:
combat/interact/loot/LOS typed NavigationRequest, FAST → medium kérés ugyanabban
az attemptben, mozgó GUID-cél és corridor-szétválasztás, nested deadline/stop/
failure diagnostics. A FAST own-Z nézet közös packet projekciója is megvan.
A szinkron main-query és hosszú számítás utáni dispatch-forráskor a következő
P4-audit konkrét nyitott pontja; teljes felelősség-/provider-migráció még nincs.

'''+needle,1);p.write_text(s,encoding='utf-8')
subprocess.run([sys.executable,'-B',str(work/'verify_closure.py')],check=True)
template=(work.parent/'rev4-position-before-route-20261030/save_position_checkpoint.py').read_text(encoding='utf-8')
template=template.replace('position-before-route-evidence','domain-navigation-handoff-evidence')
template=template.replace('P5_POSITION_BEFORE_ROUTE.md','P5_DOMAIN_NAVIGATION_HANDOFF.md')
template=template.replace('combined-position-before-route-final',label)
template=template.replace('save_position_checkpoint.py','save_domain_checkpoint.py')
start=template.index("for name in ('combined-domain-navigation-final.log'")
end=template.index('verification.update(',start)
template=template[:start]+'''for name in ('combined-domain-navigation-final.log','combined-domain-navigation-final-junit.xml',
 'combined-domain-navigation-1.log','combined-domain-navigation-1-result.json',
 'domain-initial-1.log','domain-initial-2.log','domain-initial-3.log',
 'domain-final-targeted-1.log','domain-final-targeted-1-junit.xml','domain-final-targeted-1-result.json',
 'domain-final-targeted-2.log','domain-final-targeted-2-junit.xml','domain-final-targeted-2-command.json','domain-final-targeted-2-result.json',
 'domain-final-targeted-3.log','domain-final-targeted-3-junit.xml','domain-final-targeted-3-command.json','domain-final-targeted-3-result.json',
 'domain-regression-fixes-1.log','domain-regression-fixes-1-junit.xml',
 'domain-regression-fixes-1-command.json','domain-regression-fixes-1-result.json',
 'run_targeted.py','finish_domain.py'):
    shutil.copyfile(work/name,target/name)
write_json('handoff-policy.json',{'canonical_typed_entity_route':True,'fast_initial_route_query':False,
 'same_skill_action_retry_deadline':True,'moving_goal_is_pinned_guid':True,
 'corridor_anchor_not_overwritten_by_entity_follow':True,'nested_terminal_physical_stop':True,
 'handoff_preserves_owned_request':True,'bounded_nested_failure_detail':True,
 'own_navigation_projection_shared':True,'corpse_pose_proves_loot_eligibility':False,
 'general_fast_requery_audit_complete':False,'dispatch_time_freshness_audit_complete':False,
 'asynchronous_main_route_worker':False,'full_migration_complete':False,
 'new_live_acceptance':False,'assistant_live_input':False,'live_database_write':False})
'''+template[end:]
(work/'save_domain_checkpoint.py').write_text(template,encoding='utf-8')
subprocess.run([sys.executable,'-B',str(work/'save_domain_checkpoint.py')],check=True)
