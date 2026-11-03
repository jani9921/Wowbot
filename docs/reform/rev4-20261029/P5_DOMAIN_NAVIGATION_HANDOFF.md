# REV4 P5/P7 — közös M0 entity route és medium handoff

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

Végső kijelölt regresszió: **4083 passed, 2 skipped, 10 unchanged deselections, 326 modules, exit 0**, 211.81 s pytest / 214.51 s runner.
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
