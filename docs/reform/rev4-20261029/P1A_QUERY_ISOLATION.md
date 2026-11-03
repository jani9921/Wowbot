# REV4 P1-A — példányhoz kötött útvonalköltség-lekérdezés

2026-10-29, Europe/Budapest. **ELKÉSZÜLT / OFFLINE_TESTED a P1-A hatókörében.**
A teljes P1 továbbra is részleges; a session/bootstrap, mezőnkénti forrásfeloldás és további query-portok külön feladatok.

## Mi változott?

A tdb_locations modulból megszűnt a route_cost_oracle globális változó. Korábban minden AutonomousAgent-konstruktor a saját NavigationService.walk_cost metódusával felülírta azt. Egy Python-folyamat két példánya így az utolsó agent becslőjét használhatta.

A közös wowbot.query_ports.TravelCostPort kisméretű, csak olvasó szerződés. Az AutonomousAgent composition root a saját navigációs metódusát adja át a Plannernek és a QuestExecutionRuntime-nak. A függés konstruktorokon és opcionális keyword paramétereken halad tovább.

Bekötött utak:

- ObjectiveLocator és a quest runtime helyfeloldása;
- leadási hely és az aktuális leadási POI magasságtámpontjának keresése;
- API-n felvehető questhez tartozó helyválasztás;
- questagenda: munka, leadás, felvétel és feltételes folytatás;
- jármű felszállási helyére visszatérés;
- beszélgetési actor és szerver-NPC keresése;
- a mozgás közben megjelenő objective-NPC közös handoffja, a gyors és közepes vezérlési ágban is.

A Planner session-resetje és a quest runtime újraépítése megtartja az adott példány függését. A port a policy/runtime objektumokban él, nem a WorldModel szerializált állapotában, célkoordinátában, agenda-kimenetben vagy SQLite-ban.

A régi függvényhívások továbbra is működnek explicit provider nélkül: ekkor a korábbi, provider nélküli geometriai sorrendet használják. Nem vesznek át egy másik agenttől implicit navigációt. Egy adatot leíró legacy helper tehát nem kap automatikus szolgáltatás-hozzáférést pusztán attól, hogy ugyanabban a processzben létezik agent.

Az elérhető út szerinti rangsorolás, a floor-első sorrend, a legfeljebb öt vizsgált jelölt, az ismeretlen/hibázó geometria visszaesési viselkedése és a normál agent helytervezési útjai megmaradnak. Ebben az ütemben az objective- és TDB-források prioritását nem rendeztük át.

## Ellenőrzés

| Próba | Eredmény |
|---|---|
| Új regresszió a javítás előtt | A három kezdeti eset reprodukálta a globális felülírást, a reset utáni rossz választást és az implicit provider-kölcsönzést |
| Új izolációs modul a javítás után | **11 passed**: két példány, session-reset, runtime/leadás/felvétel/agenda/jármű fogyasztók, szerializáció, geometriai fallback |
| Scope/table adapterek + izoláció | **19 passed**; a két korábbi test-double fogadja az új opcionális query paramétert, az elvárt viselkedés változatlan |
| Végső kombinált regresszió | **3162 passed, 1 failed, 1 skipped, 10 deselected**, 250 modul, 150.84 s |
| Új tesztkizárás | **0**; a korábbi tízes lista változatlan |
| Szintaxis | **499 forrásmodul + 593 teszt-Python-fájl**, 0 parse-hiba |
| Globális oracle-hivatkozás a src-ben | **0** |
| Addonváltozás | **0**, a mentett hashleltár alapján |
| Élő teszt / WoW-input | Nem történt új élő teszt vagy asszisztens által indított kliensvezérlés |

A végső kombinált parancs exit-kódja 1, tehát az egész tesztkör nem nevezhető teljesen zöldnek. Az egyetlen megmaradt bukás:

test_quest_drop_combat_handoff_20261028.py::test_ambiguous_blank_reference_rows_do_not_pick_a_collect_objective_by_index

Ugyanez a teszt a P1-A előtti, külön kibontott forrásmentésen is ugyanazzal a hibás 990401 → 990201:0 kapcsolattal bukik. A bizonyíték a prechange-drop.log és prechange-drop-result.json. Ez az üres/ambivalens referencia-objective-k összerendelésének meglévő hibája; ebben a munkacsomagban nem változtattuk meg és nem rejtettük tesztkizárás mögé.

A kiválasztott körben nem maradt új regresszió. Az offline eredmények nem igazolnak teljesített élő questet, és az Unwelcome Outsider párbajindítási elakadása továbbra is külön nyitott ügy.

## Következő határ

A P1 további részeiben a WorldModelhez dinamikusan csatolt többi geometriakérdés és a SessionIdentity/WorldContext szerződés rendezendő. Ezután jön az addonfüggő packet-bootstrap és a mezőnkénti source authority. A vizuális modulok kivezetése, az általános TripPlan és a Combat/questmechanika átszervezése a későbbi fázisokban marad.

## Visszaállíthatóság és bizonyítékok

A módosítás előtt készült baseline.zip 1101 forrás-, teszt-, addon- és kapcsolódó követési fájlt őriz; a baseline.json byte-hashekkel azonosítja őket. Az új fájlok és a módosított fájlok régi/új hash-e a change-manifest.json-ban, a szöveges módosítás a changes.diff-ben szerepel.

A mentés helye: C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1a-20261029.
A projektben elérhető kis bizonyítékcsomag: p1a-evidence/ a jelen dokumentum mellett. A teljes mentést és az ideiglenes tesztadatokat nem másoltam az agent működési könyvtárai közé.

Az aktív projekt továbbra is a projekt nevű mappa. Az új bekötést a GUI következő indítása tölti be. A felhasználó vezeti az élő teszteket; az asszisztens a naplókat ellenőrzi.
