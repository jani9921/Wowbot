# REV4 P1-D — közös evidence és forráslánc

2026-10-29, Europe/Budapest. **A munkacsomag IMPLEMENTED / OFFLINE_TESTED; a teljes P1 továbbra is PARTIAL.**

Aktív projekt: a projekt nevű mappa. Az asszisztens nem indított játékot, capture-t vagy FULL_AI-t; élő questteljesítésre nincs új bizonyíték.

## Közös értékszerződés és bekötés

A wowbot.evidence_contracts modul tartalmazza a közös Evidence értéket, az immutable SourceLineage típust, a temporális érvényesség, az adat-teljesség és a packetirány jelöléseit. Nincs agent-, vision-, planner- vagy inputfüggése; a közös SessionContext típust használja.

A korábbi wowbot.agent.world_models.Evidence és wowbot.agent.world.Evidence import ugyanarra az osztályra mutat. A korábbi pozicionális konstruktorparaméterek, at/expires mezők és a frissességi metódusok megmaradtak. Az at továbbra is beérkezés; az observed_at a rendelkezésre álló monotonic mintavételi idő, ennek hiányában a kompatibilis korábbi beérkezési idő. A nyers forrás-timestamp külön megmarad, automatikus óraátváltás nélkül.

A WorldModel egyetlen evidence-tulajdonos marad. Az evidence_factory az Observationből és a már ismert, azonos mezőhöz tartozó előzményekből készít értéket, nem választ akciót vagy új provider-authorityt. A meglévő reducer-, belief-, snapshot- és WorldQuery utak az új szerződést használják.

A SourceLineage név szerint engedett metaadatokat őriz: producer, szülő- és gyökérmegfigyelések, eseményazonosító, irány, build/layout, forrás-timestamp és korrelációs bizonytalanság. A listák legfeljebb 64 azonosítót tartalmaznak; a csonkolt/hibás lánc nem lesz több független megerősítés. Az ismeretlen direction, phase és completeness ismeretlen marad. Egy üres lista önmagában nem állít COMPLETE lefedettséget.

A packet evidence a már hitelesített packet_contextból őrzi a PID/session/karakter/map/instance/phase/build és IPC-korszak azonosítóit. Kliens→szerver mozgásból nem lesz szerver ACK. Az addonból hiányzó PID-t vagy világkorszakot az adapter nem találja ki. A metaadatok tárolása nem helyettesíti az IPC-, frissességi és input-authority ellenőrzést.

## Javított hibák

1. A korábbi is_fresh és belief/snapshot szűrés csak a lejáratot nézte; a még be nem érkezett, jövőbeli rekord is frissnek számíthatott. A jövőbeli, hibás időablakú és nem véges időadat most nem használható aktuális bizonyítékként.
2. Azonos eredetű másolatokat csak egyező independence_group vont össze. A gyökér/szülő/esemény azonosítók alapján összefüggő komponens most egy szavazat. A részlegesen átfedő gyökérhalmaz és később érkező közös szülő sem ad mesterséges háromszoros támogatást. A közös képkocka WORLD3D_LOCAL_VIEW és CROSS_VIEW feldolgozásai is ugyanabba a csoportba tartoznak.
3. Azonos súlyú, azonos eredetű adatoknál a régi rekord maradhatott kiválasztva. A választás a meglévő tier és súly után a frissebb valódi mintát részesíti előnyben.
4. Késve beérkező származtatott adat újrakezdhette a TTL-t. A megadott mintavételi idő és az elérhető ismert szülők/gyökerek ideje megmarad; ismert eredetet későbbi másolási timestamp nem fiatalít meg. Hibás idő és bizonytalan korreláció öröklődik a gyermekre.

A packet saját pozíció/orientáció evidence TTL-je továbbra is 0.75 s, a flight evidence-é 1.5 s, de most a tényleges inbox-mintától számítva. Az adapter nem vonja le még egyszer a hálózati/továbbítási késést. A meglévő navigációs visszacsatolás, entitáséletciklus és addon/input liveness tulajdonosa változatlan.

## Lekérdezés és teljesítmény

A WorldQuery.evidence mezőnként tuple-ben adja az immutable rekordokat; alapból csak az érvényeseket, explicit kérésre az inaktívakat is. Az érték JSON-visszaolvasása külön másolat. A belief diagnosztika az evidence-hierarchiában csak az időt/teljességet teszi hozzá; részletes származási láncot a kiválasztott értéknél egyszer ad, legfeljebb 8 szülő/gyökér megjelenítésével és csonkolásjelzéssel. A teljes rekordok a közös queryn át elérhetők, így a státusz nem ismétli minden szavazatnál a teljes láncot.

Az első változat páronkénti komponens-összehasonlítása túl drága volt. Indexelt tokenek és union-find váltotta fel; az immutable időablak statikus érvényessége konstrukciókor számolódik. A 24 lehetséges sorrendű gyökérhíd-próba ellenőrzi az összevonás sorrendfüggetlenségét.

Három váltakozó, külön Python-folyamatban futó mérés, körönként 220 bemelegítés utáni szintetikus ingest/belief ciklus és minden tizedik ciklusban snapshot:

| Mérés | Medián | p95 |
|---|---:|---:|
| P1-D előtti mentés | 0.4605 ms | 0.7546 ms |
| Végső P1-D | 0.8858 ms | 1.5949 ms |

A gazdagabb ellenőrzés mért többlete ezen a kis adatúton kb. 0.43 ms medián és 0.84 ms p95. A kezdeti P1-D mediánja 1.2553 ms volt. A mért diagnosztikai snapshot eredeti mérete 53 887 byte, az első bővített kimeneté 125 025 byte, a kompakt végsőé 73 214 byte. Ez szintetikus lokális mérés, nem élő FPS- vagy végponttól végpontig tartó agentteljesítmény-garancia. A benchmark script és a nyers eredmények megmaradnak.

## Ellenőrzés

A javítás előtti hét kezdeti regresszió mind bukott. A bővített célzott kör 66 tesztje sikeres.

| Próba | Eredmény |
|---|---|
| Két új regressziós modul | **49 passed**: 7 lineage + 42 contract eset |
| Végső kombinált regresszió | **3543 passed, 2 skipped, 10 deselected**, **290 modul**, 125.47 s, exit 0 |
| Új tesztkizárás | **0**; a korábbi tízes lista változatlan |
| Szintaxis | **502 forrásmodul + 599 teszt-Python-fájl**, 0 parse-hiba |
| Addon | Mind a **8 baseline addonfájl változatlan** |
| Élő futás / kliensinput | Nem történt új asszisztens által indított futás vagy input |

A két skip hiányzó, opcionális live screenshot fixture miatt van: test_detector_on_the_live_garrick_capture és test_exile_reach_fixture_scans_fast_and_returns_candidates. Ezekhez nem gyártottunk helyettesítő élő bizonyítékot. A localhost UDP-t tartalmazó végső kör a sandboxon kívül futott. Egyes szűk futások lezárásakor a meglévő pyreadline3 Windows-handle üzenet megjelent; az exit-kód és a pytest eredmény külön megmaradt. A korábban ismert quest-drop és runtime-handoff tesztek a végső körben sikeresek.

## Nyitott kapuk

Ez az in-memory evidence-határ közös szerződése. A learned SQLite/import/reference provider teljes eredetláncának végigvezetése, az elveszett eredet visszaállítása és a források baseline/delta-életciklusa még nincs kész. Csak megadott vagy ténylegesen ismert előzményt használunk; hiányzó adatból nem lehet eredeti mintavételi időt bizonyítani. A gyökerek követése az adott mező meglévő, legfeljebb 20 rekordos evidence-előzménye és az explicit producer-metaadatok alapján működik.

A completeness jelenleg deklarált metaadat; nem történt minden üreslista-fogyasztó, per-field forrásprioritás, session/world invalidálás és coverage-scope átállítása. A Fact/Belief további közös szerződései, a typed geometry eredmények, az addonfüggetlen bootstrap és a későbbi REV4 fázisok külön kapuk. A közös evidence osztály megléte ezeket nem teljesíti. A korábbi sikeres P1-A/B/C javítások és a 203 számozott coverage-sor megmaradnak.

## Visszaállíthatóság

A P1-D előtti baseline.zip 1108 forrás-, teszt-, addon- és követési fájlt mentett a baseline.json byte-hasheivel együtt. Munkamappa és teljes teszt/benchmark kimenet:
C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1d-20261029.

A lezárt kis bizonyítékcsomag a dokumentum melletti p1d-evidence/ könyvtárban található: eredmény, parancs, teljes tesztkimenet, benchmark, hash-manifeszt és szöveges diff. A GUI következő indítása tölti be az új forrást. Új élő validáció nem történt.
