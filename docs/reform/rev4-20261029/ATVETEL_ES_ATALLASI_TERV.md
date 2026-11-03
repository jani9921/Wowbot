# REV4 átvétel és végrehajtható átállási terv

Dátum: 2026-10-29, Europe/Budapest.
Célprojekt: C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt.
Állapot 2026-10-30: **P0 részben ellenőrizve; P1-A/B/C/D és a P1-E–P9 integrációs kör offline tesztelve; a teljes REV4 elfogadása PARTIAL**.

Aktuális eredmény: [P1-E–P9 bekötés, hiányzó képességek és élő kapuk](P1E_P9_IMPLEMENTATION.md).
Végső kijelölt regresszió: 4083 passed, 2 skipped, 10 változatlan deselection, 326 modul, exit 0.
Mind a 203 számozott coverage-sor megmaradt. A teljes packet baseline-/consumer-paritás,
cast/hazard/talent és role-lefedettség, történeti import-lineage és élő kalibráció nincs
teljesnek jelölve. A felhasználói 0.9.79 betöltési hiba Lua 5.1 upvalue-limit volt;
a javított 0.9.80 telepítve, user-reload és sikeres betöltés visszaigazolása még nyitott.
Az általános százalékbecslés helyett konkrét lezárt és nyitott kapukat követünk.
A korábban hiányzó `SRC_MIGRACIOS_TERV_20261029_HU.md` most megérkezett;
[byte-pontos átvétel és a fázisok összevetése](MIGRATION_SUPPLEMENT_REVIEW.md).
Az eredeti ZIP hiánylistája az akkori állapotot őrzi. A közös szerződések
bekötése nem a teljes felelősségbontás készsége; az első canonical
[combat Target/Ability/Facing extraction](P7_COMBAT_EXTRACTION.md) elkészült.
Saját CREATE kezdeti questslotok [bekötve](P3_OWN_CREATE_QUESTLOG.md); inventory,
tartós natív állapot és teljes objective-progress továbbra is külön nyitott kapu.
Inventory CREATE saját item/count/container/root adatút és read-only fogyasztó
[elkészült](P3_NATIVE_INVENTORY.md); a teljes inventory VALUES-/UI-slot-paritás még nem.
A [gyakori item-/container-delták](P3_NATIVE_INVENTORY_DELTAS.md) elkészültek;
friss darabszám, durability és táskaslot külön órával, ismeretlen maszkra érvénytelenítés.
A [saját Active root-slot delták](P3_NATIVE_INVENTORY_ROOTS.md) is elkészültek;
a vegyes prefixek, retained collections és teljes carried/UI-slot paritás még nem.
A [P9 epizód-proof kapu](P9_PERSISTED_EPISODE_PROOFS.md) tényleges tartós
bizonyítékot és eredeti forrásgyökeret követel meg; a teljes történeti lineage
migráció ettől még nyitott.
A [helyi IPC-kézbesítés folytonossága](P2_PACKET_DELIVERY.md) is ellenőrzött:
sorszámrés és valódi mailbox-kiesés natív field-invalidálást/rebaseline-t okoz;
retained-state életjel és teljes parity még nem készült el.
A [questlog- és root-collection invalidálása](P3_QUEST_LOG_INVALIDATION.md)
mezőnként megőrzi az újabb bizonyítékot, az ismeretlenné vált régi tagokat
eldobja. A teljes progress/retained-state/consumer paritás még nem kész.
A [valódi decoder-progress alkalmazási kapuja](P2_APPLIED_PACKET_PROGRESS.md)
is bekötött; megérkezett kontroll nem jelent feldolgozott collection-deltát,
nem hosszabbít sample-TTL-t. A retained lifecycle és warm-baseline még nyitott.
Közös Python/natív formátumellenőrzés és pontos geometriai hibakódok:
[P1-E MMAP/Detour](P1E_MMAP_FORMATS.md). Verzió-/adathiba nem bizonyít NO_ROUTE-ot.
A saját HP CREATE-baseline, resource/profile prefix és a valódi dekóderrel végzett
SERVER pixeltransport-próba elkészült: [P3/P4 provider-kiegészítés](P3_PROVIDER_CLOSURE.md).
Saját questlog slotok és a reprodukált folytonossági cache-hiba javítása:
[P2/P3 native questlog](P2_P3_NATIVE_QUESTLOG.md). A teljes questdefiníció-/objective-
és inventory-paritás továbbra sem teljes.
Natív questdefiníció, exact objective–POI kötés és a gyors/közepes packet-lane
korszakvédelme: [P3 server quest definitions](P3_SERVER_QUEST_DEFINITIONS.md).
Rejtett UI-soroknál nincs ordinalból kitalált storage-/POI-kapcsolat; a
technikai credit ID nem válik fizikai célazonossággá. Az addon még nem karcsúsítható
teljesen, a saját CREATE-chain/progress/inventory paritás nyitott.
Új P7 packet-cast adatút és részletes határai:
[P7 casts / addon fix](P7_PACKET_CASTS.md).
P3 kiegészítésként a [saját HP-delta és field sample-time](P3_OWN_HEALTH.md) is bekötve;
a teljes own-player/questlog/inventory baseline nincs teljesnek jelölve.

Történeti utókövetés: az első kódos munkacsomag elkészült, lásd [P1-A eredmény és nyitott kapuk](P1A_QUERY_ISOLATION.md).
Elkészült a közös session/world értékszerződés és a packet-hatókörök javítása is: [P1-B eredmény és még hiányzó session-provider](P1B_SESSION_CONTEXT.md). Az addonfüggetlen bootstrap ettől még nem készült el.
Az explicit navigációs query-portok is be vannak kötve; a korábban nyitott quest-drop referenciahiba offline javítva: [P1-C eredmény és hátralévő Evidence/geometry kapuk](P1C_NAVIGATION_QUERIES.md).
A közös in-memory evidence/idő/forráslánc szerződés is be van kötve: [P1-D eredmény, mért költség és nyitott lineage/authority kapuk](P1D_EVIDENCE_LINEAGE.md). A teljes SQLite/import eredetlánc és a typed geometry-válaszok továbbra is hátravannak.
Az alábbi 1–9. fejezet az átvételkori, kódmódosítás előtti állapotot és tervezést rögzíti; az eredeti 498 modulos baseline megmarad.

## 1. Az átvétel eredménye

A REV4 alkalmas irány a meglévő agent fokozatos rendezéséhez. A közös világállapot, tervezés, végrehajtás és visszaellenőrzés megmarad; a Travel, Combat és questmechanikák felelőssége szétválik. A meglévő MMAP/Detour, repülésvezérlők, DB2-katalógus, questgráf és ability evaluator felhasználható.

A mostani körben a dokumentumokat vizsgáltam, az agent Python/Lua kódját és konfigurációját nem alakítottam át. A csomagban idézett korábbi felhasználói döntéseket és felszólításokat a dokumentum történeti tartalmaként kezeltem; ezekből nem indítottam automatikusan új agentet, addontelepítést vagy funkciótörlést. A közvetlen kérés most az átvétel és a jelenlegi kóddal való összevetés volt.

A no-vision cél és a TDB opcionális háttértudásként kezelése a REV4 javasolt célállapota. Ez eltér a munkamappa és a projekt jelenlegi, régebbi specifikációkra hivatkozó AGENTS.md-jétől. Megvalósítás előtt egy rövid, egységes működési specifikációban kell rögzíteni az új termékcélt és a megtartott invariánsokat. A történeti coverage-sorok ettől nem válnak teljesítetté, és a capture/input jogosultságok nem bővülnek.

## 2. Függetlenül ellenőrzött alapállapot

| Ellenőrzés | Most kapott eredmény | Mit igazol? |
|---|---|---|
| Átadott ZIP | 4 Markdown + 1 CSV; SHA-256 az input-manifest.json-ban | A vizsgált dokumentumcsomag azonosítható |
| Jelenlegi src | 498 Python-fájl, 104 128 sor | Egyezik a leltár darabszámával és sorszámaival |
| AST-parse | 498/498, 0 szintaktikai hiba | Szintaxis; nem minden függvény helyessége |
| Helyi src (2).zip | SHA-256: a224a6d781fb5529bd5c62785cb3233a0ab29725488b59f5b54eda2c1d33f9af | Egyezik az audit által megnevezett forrásarchívummal |
| Aktuális src vs. forrásarchívum | 498/498 byte-ra egyezik; 0 új/hiányzó/eltérő modul | A csomag konkrét forráshivatkozásai ugyanarra a verzióra vonatkoznak |
| Addon snapshotmezők | 84; név szerint 0 eltérés a melléklethez képest | A vizsgált snapshot-konstruktor leltára helyes |
| FAST producermezők | 42; név szerint 0 eltérés | A readFastState producer leltára helyes; a transport teljességét nem bizonyítja |
| Packet allowlist | 22 eseménytípus | A normalizált felület mérete; nem 22 teljesen kész képesség |
| Elérhető tesztmodulok | 591 test_*.py a tests gyökerében | A helyi projektben rendelkezésre állnak a ZIP-auditból hiányzó tesztek |
| Most futtatott célzott kör | **138 passed, 10.84 s, exit 0**, 10 modul | A felsorolt meglévő offline szerződések jelenlegi alapállapota |
| Kliensinput | 0 parancscsoport a külön határpróbákban | A próbák nem vezérelték a WoW-ot |

A pytest után a helyi pyreadline3 lezárója Windows handle-hibát írt ki; a pytest eredménye 138 passed, a folyamat exit-kódja 0 volt. A teljes kimenetrészlet a targeted-tests.json-ban megmaradt.

A korábbi 2908 passed / 1 skipped / 10 baseline-kizárás eredmény a projekt ledgerében korábbi munkaként szerepel. Ezt ebben a körben nem futtattam újra, és nem adom hozzá a 138-hoz. Most nem történt új élő quest-, repülés-, harc- vagy talentvalidáció.

Az importgráf 196 bejövő agent.models-hivatkozásáról és a 32 modulos SCC-ről szóló számok az átadott audit állításai; ezeket külön importgráf-algoritmussal most nem számoltam újra. A teljes forrásazonosságot viszont ellenőriztem. Nem történt a 498 modul minden függvényének kézi soronkénti auditja.

## 3. A fő állítások összevetése a kóddal

| Megállapítás | Kód és ellenőrzés | Következmény |
|---|---|---|
| A navigációs költség-oracle globális | agent/engine.py:84 állítja a tdb_locations.route_cost_oracle változót; tdb_locations.py:207 ezt olvassa. Két valódi AutonomousAgent-konstruktorral, input nélküli végrehajtóval reprodukálva: a második példány felülírja az első kötését. | P1: explicit példányhoz kötött TravelCostPort. A bizonyított hatókör egy Python-folyamat két példánya; ez nem bizonyít külön OS-folyamatok közötti globális szivárgást. |
| A packet bootstrap addonfüggő | packetio/context.py:16–38; runtime_packet_source.py:70–78; world.py:360–428. Hiányzó kontextusra a tiszta függvény waiting_for_addon_context eredményt ad. | A bootstrapmezők törlése előtt független session- és world-kontextus kell. |
| A statikus objective-régió előre kerülhet | objective_locator.py:29–40: objective_region a target_location előtt. Két rendelkezésre álló jelölt mellett offline próbában TDB_SPAWN lett az eredmény. | A mezőnkénti forrásfeloldás valós viselkedést változtat; nem puszta átnevezés. Ez nem önmagában egy adott élő félrenavigálás bizonyítása. |
| Az objective-POI teljesebb a belső tárolóban, mint a publikált nézet | world_packet_reducer.py:705–713 csak objective_index=-1 / objective_id=0 blobokat vetít ki. | Objective-szintű query API kell; nem szükséges minden poligont minden tickben a statusba másolni. |
| A danger provenance elveszhet | danger.py:50–65 fix ADDON_TELEMETRY címkét ír. A PACKET_ENTITY eredettel beadott szintetikus hostile-ból is ez lett. | Forráslánc megőrzése a riskmodell előtt. A jelenlegi DangerMap tovább használható. |
| A repülési integráció már létezik | global_planner.py → flight_travel.py → flight_trip.py; 18 meglévő integrációs teszteset a mostani zöld körben. | Ezt kell általános leg-életciklus köré rendezni; nem újra bekötni. A zöld offline teszt nem teljes élő utazás. |
| A no-vision végállapot még nem szerkezeti tulajdonság | runtime.py:362 hívja a perception phase-t; engine.py vizuális végrehajtókat konstruál; target_manager.py és skills/combat.py vizuális fogyasztókat tartalmaz. | A server-mode inputszűrés és a teljes runtime-függetlenség külön feladat. A phase üresen visszatérhet, ha nincs perception/frame; a hívás léte nem bizonyít minden live futásban aktív YOLO-terhelést. |
| Questgráf és mechanikaosztályozó már van | quest_graph.py objective/quest függőségeket és readiness-t számol; quests/objective_mechanics.py már TDB/DB2-osztályozó, amelyet a tdb_knowledge fogyaszt. | A belső mechanikalépések gráfjával kell kiegészíteni, a questláncot megőrizve. |
| A harci magok részben készen vannak | TargetManager, AbilityRuleEngine, CombatSkill és CombatVerifier létezik; a kis combat_ability_catalog három Warrior-defaultot tartalmaz. | Ebből nem következik teljes class/spec-, interrupt-, tank-, healer- vagy PvP-támogatás. |
| Már létezik input-dispatcher és erőforrásbérlet | execution/command_dispatch.py, resource_arbiter.py, agent/parallel_control.py. A dispatcher LOCAL_ACK eredménye kifejezetten nem világállapot-siker. | Az új modulok ezt az útvonalat használják; ne keletkezzen párhuzamos input authority. |

A boundary-probe-results.json és a baseline_probes.py megőrzi a négy szűk határpróba eredményét és reprodukcióját. A próba azt ellenőrzi, hogy a felsorolt jelenlegi viselkedések reprodukálhatók; nem azt, hogy a hibák már javítva vannak.

## 4. A REV4 pontosítandó részei

1. **Hiányzó mellékletek.** Az architektúraterv utolsó sora a SRC_MIGRACIOS_TERV_20261029_HU.md fájlra hivatkozik, de az nincs a ZIP-ben. A mezőmellékletben említett plan-evidence.json sincs a csomagban. A mély audit migrációs táblája és a tényleges forrás alapján a kezdő munkacsomag ettől még meghatározható.
2. **Egyetlen ütemezés.** A dokumentumok T0–T8, packet P0–P6, combat C0–C6 és későbbi migrációs P0–P9 jelöléseket is használnak. Az alábbi tervben kizárólag a mély audit P0–P9 migrációs sorát használjuk.
3. **Állapottulajdon, nem általános forrásranglista.** A PACKET=world truth rövidítés mellett kötelező megőrizni a CMSG/SMSG irányt és a szerverkorrekciót. A megfigyelt kliensmozgás nem automatikus szerver-ACK; a GOSSIP_SELECTED nem quest-credit; a QUEST_COMPLETED nem bizonyított leadás.
4. **Session és térképkontextus.** A kiválasztott folyamat/karakter/capture-korszak identitását és a változó map/instance/phase kontextust külön kell modellezni. Ismeretlen phase nem helyettesíthető kitalált alapértékkel.
5. **Párhuzamosság.** Egy aktív feladat-/skill-owner mellett kompatibilis mozgási és akciócsatornák átfedhetnek. A REV4 CombatArbitrator ne vezessen új inputvégrehajtót a meglévő dispatcher mellé. A preemption, bérlet-visszavonás és folytatás legyen tesztelhető.
6. **Költségek mértékegysége.** A DangerMap geometria+veszély pontja nem másodperc. ETA, várható harcidő, átmenet és bizonytalansági büntetés csak deklarált átváltással legyen összehasonlítható. Az első súlyok heurisztikák, nem mérések.
7. **WAIT és retry külön fogalom.** A hibás próbák ideiglenes kizárása legfeljebb 20 s. Igazolt cooldown, hosszabb valódi esemény vagy tartós forráshiány más szemantika. Ismeretlen input/célazonosságot egy lejáró timer nem javít meg. Minden várakozáshoz kell ok, várt bizonyíték és újraértékelési feltétel.
8. **Fokozatos combat-lefedettség.** Első körben a ténylegesen használt karakterprofil és solo questharc legyen teljesebb. A tank/healer/dungeon/raid/arena/BG felelősségek külön képességkapuk; nem érdemes minden tervezett osztályt üres vázként előre létrehozni.
9. **A migráció visszaállíthatósága.** A jelenlegi projekt gyökerében nincs .git bejegyzés. A meglévő src (2).zip csak a Python-forrást védi, nem teljes addon/config/native/binding állapotot. A kódmódosítás előtt teljes szükséges alapállapot-manifest és visszaállítható patch/snapshot kell; az export repositoryt és a munka-projektet nem lehet automatikusan azonosnak tekinteni.

## 5. Egységes végrehajtási sorrend

| Fázis | Konkrét kimenet és tulajdonos | Következő kapu | Mostani állapot |
|---|---|---|---|
| **P0 – baseline** | Composition root, aktuális forrás/config/provider-képességek, teszt- és trace-jegyzék | Reprodukálható állapot, védett források, ismert hibák elkülönítve | **RÉSZBEN**: forrásazonosság, mezőleltár, 138 célzott teszt és határpróbák megvannak; teljes konfigurációs/élő trace-kapu nincs meg |
| **P1 – szerződések és függőségek** | Közös session/evidence/geometry/cost típusok; példányhoz kötött query portok | Két agent nem oszt meg mutable oracle-t; régi API-k kompatibilisek | TERV |
| **P2 – session/bootstrap** | Egy SessionContextProvider, packet és addon közös ellenőrzött kontextusfogyasztással | Meleg/hideg indulás, reconnect, rossz PID/build/map, streamrés; hiányból nem lesz authority | TERV |
| **P3 – mezőnkénti forrásfeloldás** | Evidence/query réteg és kategóriánkénti teljesség; átmeneti kettős forrás ellenőrzése | Live/reference ellentmondások, FAST/STATE elkülönítés, minden consumer áttér, csak utána addonmező-törlés | TERV |
| **P4 – vizuális runtime-függések kivezetése** | Composition root és GUID-alapú cél-/recovery-fogyasztók; tiszta közös koordinátatípusok | Detektor/tracker/VLM nélkül indul és tesztelhető a teljes támogatott lánc; pixeltransport külön protokolldekóderként működik | TERV |
| **P5 – egységes Travel** | Meglévő navigáció fölött cél- és arrival-szerződés, leg-alapú TripPlan, TransitionSystem | Ground/ride/steady/skyriding/mixed út; ugyanaz az eredeti request; végső floor és érkezés igazolt | TERV; meglévő részfunkciók megőrzendők |
| **P6 – idő és kockázat** | DangerMapre épülő RouteScore és ground/flight/mixed jelölt-összehasonlítás | Verziózott geometria és friss hostile/floor/adatbizalom; költségkomponensek magyarázhatók | TERV |
| **P7 – rendezett Combat** | Meglévő ability/target/FSM adapterek; karakterprofil, arbitrator, cast/hazard provider, fokozatos role-lefedettség | Exact target/cast, hatótáv/facing/bar/binding, megfelelő megszakítási eredmény; class/spec szerint külön próba | TERV |
| **P8 – questmechanikák** | Meglévő classifier + QuestGraph mellé MechanicContract, QuestTargetContext, belső execution graph | Talk→duel, item→hatás→credit, vehicle, escort, scene és több objective saját bizonyítékkal | TERV |
| **P9 – tanulás, LLM, takarítás** | Feltételesen újrafelhasználható epizódok, olvasó eszközök, sémás LLM-terv, maradó legacy kivezetése | Hibás/lejárt LLM-terv nem fut; ismert mechanika LLM nélkül is működik; hosszú user-live összehasonlítás | TERV |

A fázisok részfeladatai előkészíthetők, de a forráskiváltás és a végrehajtás csak a saját kapujuk után kapcsolható át. A P7 nem minden class, szerep és játékmód egyetlen óriási átírása. A P8 sem függ attól, hogy az összes raid/PvP-role elkészüljön.

## 6. Az első kódos munkacsomag: P1-A

**Cél:** megszüntetni a példányok közötti globális navigációs költségfüggést, a mai quest- és mozgási viselkedés megőrzésével.

- A composition root állítsa össze az egy agenthez tartozó navigációs query-portokat.
- A TDB-helyválasztó és a rá épülő fogyasztók explicit, példányhoz kötött cost/query függést kapjanak.
- Callable ne kerüljön szerializálható WorldModel-state-be, journalba vagy SQLite-ba.
- A már WorldModelhez dinamikusan csatolt oracle-ok átmeneti compatibility facade mögött maradhatnak, később egyenként kiválthatók.
- A meglévő legközelebbi/járható spawnválasztás, TDB nélküli UNKNOWN és MMAP nélküli viselkedés ne változzon meg véletlenül.
- A regresszióban két agent eltérő költségfüggvényt és külön kontextust kapjon; a második létrehozása, resetje és bezárása ne módosítsa az első lekérdezését.
- Az első patch ne mozgasson át teljes package-eket, ne vezessen be második navigátort és ne kapcsoljon új inpututat.

**Érintett jelenlegi határ:** engine.py → tdb_locations.py → objective/spawn/location fogyasztók. A végleges fájllistát a hívók teljes keresése rögzíti a patch előtt.

**Elfogadás:** az izolációs regresszió és a meglévő helyválasztó/navigációs/quest-tesztek zöldek; nincs modulglobális példánymetódus; a korábbi trace ugyanazt a támogatott célválasztást adja. P1-A önmagában nem készíti el az addonfüggetlen bootstrappet.

## 7. A tizenkét migrációs regressziós kapu

| Kapu | Meglévő támpont | További bizonyíték |
|---|---|---|
| Session/PID/context | test_packet_agent_bridge.py most futtatva | Addon nélküli cold/warm bootstrap és több capture-korszak |
| Input/STOP/MANUAL | test_parallel_control.py most futtatva | Az új adapterek és transitionök megszakítása, lease-feloldás |
| WorldModel frissesség | test_fast_lane_freshness_20261004.py most futtatva | Teljességi és forrásválasztási új mezőtesztek |
| Célazonosság | test_target_manager.py most futtatva | Teljes GUID-alapú életciklus vision nélkül; candidate ≠ selected |
| Ground/floor | test_navigation_contracts.py és danger/reachability most futtatva | Barlang/híd/spirál/esés felhasználói trace és live |
| Flight | test_flight_travel_integration_20261029.py most futtatva | Teljes user-live takeoff→cruise→landing→interact |
| Mixed Trip | Ugyanazon meglévő integrációs modul most futtatva | Általános leg-állapot és preemption/recovery szerződés |
| Route risk | test_navigation_danger_reachability.py most futtatva | ETA/combat/transition közös skála, 3D floor és hibás/stale threat |
| Combat alap | A projektben több meglévő combat-teszt van | Új class/spec/profile/arbitrator külön köre; ezek ebben a 138-as körben nem teljesen futottak |
| Cast/hazard | A mai 22-es allowlistből a teljes új adatút hiányzik | Parser→schema→reducer→consumer→konkrét cast eredmény; ez nem zöld kapu |
| Questmechanika | sparring_gossip és quest_transition_hold most futtatva | 20–30 reprezentatív összetett trace; a kézi siker elkülönítése |
| Több agent izolációja | Mostani szűk konstruktorpróba reprodukálja a globális felülírást | P1 javítása után ténylegesen izolált query/state/lease regresszió |

Az Unwelcome Outsider a questmechanika-baseline egyik ismert nyitott példája: az automatikus „Let's spar.” kattintás és az utána hiányzó visszaigazolás külön eseménysor; a felhasználó későbbi MANUAL próbája nem autonóm siker. A pontos live okot a jelen átvételi kör nem állítja megoldottnak.

## 8. Célkontraktusok minimális tartalma

- **SessionIdentity / WorldContext:** kiválasztott PID és folyamatpéldány, saját karakter, capture/session-korszak, build/layout; map/instance/phase és revision külön, unknown állapottal.
- **Evidence:** alany és mező, forrás/esemény/leszármazási lánc, irány, megfigyelési és beérkezési idő, teljesség, kontextus, validity/invalidation.
- **TravelRequest:** célreferencia/régió, koordinátatér, eredeti goal/correlation, engedélyezett képességek és célfüggő arrival.
- **TripLeg / Transition:** precondition → action request → expected evidence → verify → timeout/recovery; köztes pont nem végső érkezés.
- **CombatCandidate:** pontos GUID/cast/spell/bar-revision, alkalmasság, határidő, ütköző erőforrás, költség, várható visszaigazolás.
- **QuestTargetContext:** nav/entity/interaction/spell/credit/search szerepek külön; a fizikai NPC és a technikai credit entry ne mosódjon össze.
- **MechanicContract:** előfeltétel, engedélyezett meglévő capability, sikerjel, hibahatókör, korlátos helyreállítás és alternatíva.
- **LLMPlan:** csak megadott actor/objective/item/evidence referenciák; ellenőrizhető lépések és függőségek; aszinkron és újraellenőrzött, közvetlen input nélkül.

Ezek a szerződések a meglévő képességek közé kerülnek. Késznek az a határ számít, amelynek az éles bekötése és az eredményellenőrzése is igazolt; az osztályváz vagy a sikeres input-ACK nem elég.

## 9. A jelen csomag mellékletei

- input/: az eredeti öt dokumentum változatlan másolata.
- input-manifest.json: eredeti ZIP és dokumentumhashek.
- current-source-baseline.json: a teljes 498 modulos aktuális hashleltár és összevetés.
- field-and-package-comparison.json: 84/42 mező- és 22 esemény-ellenőrzés, csomaghivatkozások.
- targeted-tests.json: a mostani célzott tesztparancs, eredmény és kimenetrészlet.
- baseline_probes.py, boundary-probe-results.json: a jelenlegi négy szűk határviselkedés input nélküli reprodukciója.
- gate-test-map.json: kiválasztott meglévő regressziós támpontok; a jelenlét nem teljes kapulefedettség.
