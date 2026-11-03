# REV4 P1-C — navigációs query-portok és gyűjtős forrásazonosság

2026-10-29, Europe/Budapest. **A munkacsomag IMPLEMENTED / OFFLINE_TESTED; a teljes P1 továbbra is PARTIAL.**
Aktív munkamappa: a projekt nevű mappa. Nem indult játék, capture vagy FULL_AI; az élő validáció továbbra is a felhasználó feladata.

## Navigációs függőségek

A WorldModelhez dinamikusan csatolt hat navigációs callback megszűnt: layer_oracle, zone_sweep, player_layer, hostile_units, walk_cost és flight_departure_walk. A Planner a saját példánya függőségeit kapja a composition roottól; a WorldModel adatot és evidence-et tartalmaz.

A közös wowbot.query_ports modul öt további callable protokollt és egy immutable NavigationQueryPorts értéket vezet be. A már meglévő TravelCostPort külön explicit paraméterként kompatibilis marad. Az új közös modul kizárólag standard-library importokat használ, agentfüggése nincs.

Bekötött utak:

- a játékos feloldott szintje a questhely és questobjektum kiválasztásánál;
- alsó szintű pont és a barlangi/spirális területbejárás következő pontja;
- veszélyes mobok és útvonalköltség a biztonságos feltámadási helyhez;
- a repülés előtti, geometriával igazolt gyalogos kijutás nyílt ég alá.

A Planner session-resetje megtartja a saját query-bundle-t, az új QuestDomain és TravelModePolicy is ezt kapja. A planning snapshotnak nem kell szolgáltatáshivatkozásokat vagy a modell rejtett attribútumaiban élő navigációt átadnia. A régi függvények továbbra is hívhatók; query nélkül a régi WorldModel-attribútumok nem biztosítanak implicit hozzáférést.

A barlangi sweep állapota és a geometriacache a meglévő NavigationService tulajdona marad. A portok nem indítanak mozgást és nem írnak a WorldModel állapotába; a sweep lekérdezése továbbra is figyelembe veszi a már megfigyelt haladást. Ez a határ nem teszi tiszta, állapotmentes függvénnyé a navigációt.

A kész vagy átmenetileg elérhetetlen sweep nem indul újra az alsó szintű támponttól. A hiányzó játékosmagasság None marad, a 0 magasság érvényes érték. Az ismert geometriamagasság továbbra is z_observed=False becslési jelölést kap. Egy hibázó felszállásihely-lekérdezés nem állítja le a Plannert és nem gyárt igazolatlan repülési szakaszt.

## A korábbról nyitott quest-drop hiba javítása

A P1-A és P1-B körben még bukó ambivalens referencia-objective teszt oka két eltérő item→mob párosítás volt. Az egyik hiányos, leírás nélküli statikus listából sorszám szerint rendelt forrást az első látható itemhez. A másik egy kész item után a megmaradt itemre is átadhatta az előző forrását.

Most a discovery, a SPELLCLICK-felismerés és a combat ugyanazt a collect_creature_sources párosítót használja. A kill-relációépítő külön itempárosítási ága megszűnt.

- A pontos objective-ID és az egyedi leírásegyezés továbbra is használható hiányos referencialistánál.
- A sorszámos, üres leírású illesztéshez az item-listák teljes, egyedi sorrendi fedése szükséges; a már kész látható itemek is beleszámítanak az ellenőrzésbe.
- Az egyetlen látható item és egyetlen üres referencia-item sor továbbra is összerendelhető, akkor is, ha a régi katalógus nem tárol order mezőt. Ez nem ír felül explicit ID-ütközést vagy duplikált ID-t.
- A régi, csak a szülő objective-ben tárolt item-ID egyértelmű egyitemes esetben megmarad keresési támpontnak, item_id_explicit=False jelöléssel. Ez nem jogosít SPELLCLICK/F7 interakcióra. Élő SPELLCLICK jelzés mellett nem válik kill-jogosultsággá sem.
- Az explicit per-source item-ID-t, a nem ölős mechanikákat, a kész countert és a kiválasztott cél GUID/entry/range ellenőrzéseit a javítás nem kerüli meg.

A reference_objectives opcionális allow_ordinal paramétere kompatibilis; más fogyasztók alapértelmezett forráspolitikáját ez a kör nem rendezte át. A teljes mezőnkénti source authority továbbra is külön migráció.

## Ellenőrzés

| Próba | Eredmény |
|---|---|
| Kezdeti navigációs határpróba | **3 failed** a javítás előtt |
| Új navigációs regressziók | **17 passed**: két owner, eltérő szintek, snapshot, session-reset, feltámadás, felszállási gyaloglás, unknown/0, hibázó geometria, szerializáció |
| Új forráspárosítási regressziók | **13 passed**: részleges/teljes listák, kész item, ID/szöveg, duplikáció, régi szülőadat és F7-korlát |
| Szűk forrás/query/legacy kör | **125 passed** |
| Végső kombinált kör | **3366 passed, 1 skipped, 10 deselected**, **267 modul**, 100.55 s, exit 0 |
| Új tesztkizárás | **0**; a korábbi tízes lista változatlan |
| Szintaxis | **500 forrásmodul + 597 teszt-Python-fájl**, 0 parse-hiba |
| Addon | Mind a **8 baseline addonfájl változatlan** |
| Élő viselkedés | Nem volt új élő validáció; az offline eredmény nem valódi questteljesítés |

Az öt régi tesztfájl beállításait explicit query-átadásra migráltam; a barlangi közelítés, a soft-interact cocoon és a szellem repülési viselkedésének elvárásai megmaradtak. A localhost UDP-t is tartalmazó végső kör a sandboxon kívül futott. A korábbi Windows pyreadline3 lezáróüzenet egyes szűk futásoknál továbbra is megjelenhetett; az exit-kód és a pytest eredmény külön rögzített.

A korábbi ismert bukás most sikeres:
test_quest_drop_combat_handoff_20261028.py::test_ambiguous_blank_reference_rows_do_not_pick_a_collect_objective_by_index.
A P1-A/P1-B jelentések történeti bukása megmarad; ez a munkacsomag zárja le a hibát **offline**.

## Hátralévő kapuk és bizonyíték

A legacy dict/None geometriaválaszok még nem különböztetik meg egységesen a hiányzó tile-t, ismeretlen geometriát, részleges útvonalat és eltérő geometria-revíziót. A közös Evidence/source-lineage szerződés, az addonfüggetlen SessionContextProvider és baseline/delta életciklus, valamint a mezőnkénti forrásfeloldás még nincs kész. A későbbi runtime/no-vision, TripPlan, combat- és questmechanika-fázisok sem teljesültek ettől. A 203 számozott coverage-sor és a korábbi élő minősítések megmaradnak.

A P1-C előtti baseline.zip **1106** forrás-, teszt-, addon- és követési fájlt mentett, a P1-A/P1-B javításokkal együtt. Teljes mentés és tesztkimenet:
C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1c-20261029.
A p1c-evidence/ könyvtárban a kis eredménycsomag, hash-manifeszt és szöveges diff található. A navigációs algoritmus/service, WorldModel, session-context, IPC/build/parser és addon változatlansága ellenőrzött.

A friss forrást a GUI következő indítása tölti be. Az asszisztens nem indított és nem hagyott hátra FULL_AI-t.
