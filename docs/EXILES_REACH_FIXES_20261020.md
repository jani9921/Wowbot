# Exile's Reach — 2026-10-20 javítások

## Állapot

A 17:20 körül indított tesztek Exile's Reach szakaszának hat feltárt
problémájára készültek általános javítások. A későbbi Dragon Isles szakasz
nem része ennek a munkának. Nincsenek beégetett Exile's Reach quest-ID-k.

OFFLINE_TESTED: 1027 kiválasztott regressziós teszt sikeres.
Két valódi telemetria-állapot külön, input nélküli visszajátszása is sikeres.
Python- és Lua-szintaxis, valamint az addon két példányának egyezése rendben.
Post-fix LIVE_VALIDATED: még nincs; új élő tesztet a felhasználó indít.

## Javítások

1. Harc alatt csak a közös Supervisor-kapu által megengedett jelöltek
   kerülhetnek tovább. Az elérhetőség, cooldown és rangsorolás megmaradt.
   A quest-MOVE -> harci megszakítás -> ugyanaz a MOVE kör megszűnik.
   A bemenet nélküli WAIT nem vált ki újabb harci megszakítást.
2. Az F7 nem általános támadógomb. Ha másik NPC/objektum a címzett,
   a facing-próba ismert, engedélyezett támadó képességet használ; az
   autoattack a meglévő igazolt hover/jobbkattintás útjára térhet át.
   Az ID/GUID-ellenőrzés változatlanul kötelező.
3. A régi loot-képernyőpont nem írhatja felül a hulla ismert szerverhelyét
   vagy a nem-lootolható állapotot. Igazolt saját hullához 100 yardig
   kérhető MMAP-megközelítés; az általános keresési sugár 40 yard marad.
   Ez a megközelítés megelőzi a megszakított questút folytatását.
4. A felhasználó pontosítása szerinti leadási lánc:

   Quest POI MOVE -> megfelelő szerveres leadó ismertté válik ->
   kanonikus áttervezés az NPC GUID/XYZ helyére -> megközelítés/facing ->
   pontos, friss F7-címzett -> INTERACT -> quest UI -> igazolt leadás.

   A szerveres útvonalat sem új, sem eltűnő vizuális track-ID nem téríti el.
   Nem kell előtte INSPECT vagy hard TARGET. A FAST vezérlés csak megállítja
   a mozgási engedély megújítását és átad a meglévő fő futtatónak.
   Másik címzett, régi minta, rossz irány vagy igazolt eltérő szint esetén
   nincs F7. TDB/learned ender-ID esetén a már megérkezett szerveres helyet
   nem korlátozza a régi, 150 yardos általános markerkeresési sugár.

   A régi leadó-ID nem merev tiltás: egy kész quest és egy szerveres
   leadásjelölt esetén az új NPC elsőbbséget kap a régi spawn helyével
   szemben akkor is, ha a korábbi NPC még jelen van. Ez csak jelölt:
   a QuestGiverStatus GUID-ot és státuszt ad, Quest ID-t nem. A questablak
   igazolja a questet, a tényleges esemény/receipt pedig a leadást.
   Több ismeretlen marker vagy több kész quest nem kapcsolható össze
   találgatással. Puszta marker nem írja át a TDB-t. A szerver explicit
   nincs-leadás jelzése megelőzi a régi, csak pozícióra alapuló céljelöltet.
5. Szellemként nincs élő karakterhez tartozó átjárókeresés. A meglévő
   navigáció validált MMAP-kitérőt tervezhet, legfeljebb háromszor új
   előrehaladási bizonyíték nélkül; utána várakozik. Valós elmozdulás vagy
   új hulla/karakterkontextus újra engedélyezhet helyreállítást.
   A halálesemény nem íródik minden ciklusban új halálként.
6. Addon 0.9.69: legfeljebb nyolc tényleges QUEST_TURNED_IN igazolás
   megmarad a változó eseménylistától függetlenül; FAST-on legfeljebb négy
   továbbítható. Az új elfogadás törli ugyanannak a questnek a régi
   igazolását. Azonos session/karakter, helyes quest, új sorszám és
   megfelelő idő kell. Eltűnés, abandon vagy régi igazolás nem siker.

## Módosított felelősségi helyek

- Planner / PlanningOrchestrator / Supervisor: javaslatengedélyezés,
  rangsorolás és megszakítás; nem küldenek közvetlen inputot.
- CombatSkill: biztonságos támadási fallback, a közös GUID-kapu mögött.
- CombatPlanning / ServerLootPolicy: hullaállapot és megközelítés.
- TurnInResolver / QuestLocationPlanning / ServerNpcInteractionPolicy:
  szerveres leadóazonosság, célhely és interakciós készültség.
- NavigationSituation / RecoveryPlanner: szellem-kompatibilis helyreállítás.
- Addon / AIPC5 adapter / WorldAddonReducer / QuestDialogVerifier:
  tartós, de sessionhöz kötött leadási visszaigazolás.

## Ellenőrzés és bevezetés

Az új regressziók a tests/test_exiles_reach_live_fixes_20261020.py fájlban
vannak. A régi offscreen-facing teszt már ismert támadó képességet vár
igazolatlan F7 helyett. A tágabb kör agent/runtime, M0/M1, harc, loot,
interakció, párhuzamos futtatás, navigáció, szervercélok és leadás tesztjeit
is lefedi; nem a teljes repó minden hardveres/élő elfogadási tesztje.

A rögzített állapotok input nélküli ellenőrzése:

- Ogre Brute mellett a katapult volt az F7 címzettje: az új facing-próba
  ACTIONBUTTON1, nem INTERACTTARGET.
- A 44,635 yardra lévő igazolt saját hulla: pontos szerveres MOVE,
  nem a régi tooltip-képernyőpont hoverezése.

A projekt nem Git-munkapéldány. A felülírt fájlok eredeti példányai a
munka során készített work/exiles_reach_fixes_20261020/original mappában
vannak az asszisztens munkakönyvtárában. A projektbe csak a kiválasztott,
hash-ellenőrzött módosítások kerülnek, futási adatok/adatbázisok nélkül.

GUI/runtime teljes újraindítás és az addon frissítése + /reload szükséges.
A telepített WoW addonpéldányt ez a kódjavítás nem módosítja automatikusan.
Élő bizonyíték és fennmaradó kockázatok: LIVE_VALIDATION.md.
