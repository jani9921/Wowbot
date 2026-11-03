# REV4 P1-E–P9 — bekötött működés és ellenőrzési kapuk

2026-10-30, Europe/Budapest. Aktív munkamappa: a felhasználó által kijelölt `projekt`.

**A P1-E–P9 kódos integrációs kör OFFLINE_TESTED. A teljes REV4 elfogadása PARTIAL; új LIVE_VALIDATED állítás nincs.** A meglévő működésre épülő bekötések elkészültek; a hiányzó provider-/role-lefedettség és az élő kapuk külön szerepelnek. Ez nem jelenti minden class/spec, questmechanika vagy packetmező támogatását.

A közös AutonomousAgent → WorldModel/query → Planner → aktív skill → végrehajtó → verifier lánc megmaradt. A navigáció, a skill-owner, a resource lease és a dispatcher nem kapott párhuzamos versenytársat. Az asszisztens nem indított WoW-ot, Ymir-t, capture-t vagy FULL_AI-t, és nem küldött kliensinputot.

**Aktuális kiegészítés:** a felhasználó 0.9.79 betöltési hibája javítva 0.9.80-ban;
a valódi Lua 5.1/LuaJIT fordítás és teljes TOC-betöltési próba most már a regresszió része.
Az új addon telepítve, felhasználói /reload és sikeres élő betöltés visszaigazolása nyitott.
Az asszisztens nem indított játékot/capture-t és nem küldött inputot; a felhasználó elindította a játékot.
Öt NPC cast-opcode adatútja is bekötve, a hiányzó interruptibility/hazard adatok UNKNOWN állapotúak.
Részletek és források: [P7 packet casts és addonhiba](P7_PACKET_CASTS.md).
Az általános százalékbecslést felváltotta a konkrét provider-/elfogadásikapu-nyilvántartás:
[saját HP-baseline, resource/profile adatút és valódi pixeltransport-próba](P3_PROVIDER_CLOSURE.md).
Elkészült a saját natív questslot-prefix és a stream-GAP utáni cache-öröklés
javítása is: [P2/P3 native questlog](P2_P3_NATIVE_QUESTLOG.md). A slot nem
helyettesíti a questdefiníciót vagy a UI-objective igazolt storage-kapcsolatát.
Az ezt követő [natív questdefiníció-bekötés](P3_SERVER_QUEST_DEFINITIONS.md)
elkészült: exact/egyértelmű objective-kötés, storage-lekérdezés és közös
runtime/helykeresési POI-query. A teljes progress/CREATE/inventory paritás
továbbra is nyitott. Gyors és közepes packet-lane azonos korszakvédelmet használ.
Közös Python/natív [MMAP/Detour formátumellenőrzés](P1E_MMAP_FORMATS.md) is
elkészült; hibás adat és verzióeltérés nem lesz bizonyított NO_ROUTE.
Saját CREATE → UnitData remainder → PlayerData QuestLog prefix is bekötve:
[kezdeti 175 questslot](P3_OWN_CREATE_QUESTLOG.md). A fennmaradó own-player/
inventory és tartós natív progress-paritás továbbra is nyitott.
Saját inventory CREATE és bounded read-only fogyasztó:
[P3 native inventory](P3_NATIVE_INVENTORY.md). Az ismeretlen VALUES minta
érvénytelenít; carried/UI-slot, retained state és teljes paritás továbbra is nyitott.
[A gyakori item-/container VALUES](P3_NATIVE_INVENTORY_DELTAS.md) most már
olvasható; a mezők külön eredetidőt tartanak, az ismeretlen maszk továbbra is
érvénytelenít. Az [önálló Active root VALUES](P3_NATIVE_INVENTORY_ROOTS.md) is
olvasható, slotonkénti eredetidővel és invalidation barrierrel; vegyes prefix,
carried/UI-slot, retained collection és teljes paritás még nyitott.
P9-ben a [tartós epizód-proof kapu](P9_PERSISTED_EPISODE_PROOFS.md) is szigorúbb:
valóban mentett evidence, eredeti idő/scope és tartós forrásgyökér-dedup kell;
a régi policy és eltérő környezeti verzió nem újrafelhasználható. Ez nem a teljes
történeti import/retained-replay lineage migrációjának lezárása.
Az új [hitelesített IPC-kézbesítési sorszám](P2_PACKET_DELIVERY.md) a helyi
delta-kiesést is láthatóvá teszi: a szigorú mód packet-baseline-t kér, a régi
migrációs mód pedig eldobja a natív mezőket és megtartja a pozitív snapshot-
helyreállítást. Retained TTL/progress-watermark és teljes parity továbbra is nyitott.
Az [ismeretlen saját questfrissítések](P3_QUEST_LOG_INVALIDATION.md) most már
explicit UNKNOWN/invalidation eseményt adnak. Questlog és inventory-root
mezőnkénti barrierrel védi a régi teljes collectiont; egyetlen új slot nem
teszi ismertté a régi többit. Retained teljesparitás továbbra sincs lezárva.
A felhasználó átadta a [hiányzó fájlszintű migrációs mellékletet](MIGRATION_SUPPLEMENT_REVIEW.md).
Az első [Target/Ability/Facing extraction](P7_COMBAT_EXTRACTION.md) elkészült:
egy canonical combat implementáció, azonos régi reexportok, tiltott agent/core
függőség tesztelve. A teljes nagy CombatSkill/Travel/Quest felelősségbontást
az eddigi szerződésbekötések nem helyettesítik; ez külön nyitott kódmunka.
Bekötött [valódi decoder-progress és alkalmazási watermark](P2_APPLIED_PACKET_PROGRESS.md):
a kontroll csak a ténylegesen redukált saját collection-eseményeket igazolja.
Nem frissít UI-t, nem ad inputjogot és nem hosszabbít mező-TTL-t. A per-field
retained lifecycle és warm collection baseline továbbra is külön kódos kapu.
A felhasználói mai logokból két regressziót is javítottunk:
[szabályos signed MMAP-kapacitás és realm→instance login](P2_LIVE_SESSION_NAVMESH_FIXES.md).
A korábban kizárólag same-connection szabályt explicit saját ActivePlayer-
bizonyíték egészíti ki; az új session nem örököl régi cache-t. A rögzített
capture visszaolvasása sikeres, új élő FULL_AI-elfogadás továbbra sincs.

A hosszabb felhasználói próbában a natív session/gap-helyreállítás és a map-0
útvonal már megjelent. Egy [Charge/range átadási hiba](P7_COMBAT_RANGE_HANDOFF.md)
offline javítva: mozgási átmenet alatt nem zárja le 0.14 s után a harcot,
és üres addon targetpozíció esetén a meglévő exact szerverpozíciót használja.
A többi ráfordulási/dialog hiba nincs ettől lezárva.

A [range/facing follow-up](P7_RANGE_FACING_FOLLOWUP.md) a sustained támadási
távot külön kezeli a mobility openerétől, a három tiszta entity-pose helper
egy canonical implementációba került, és a végső facinghez GUID/map/reason
vizsgálat és bounded terminal diagnostics tartozik. Ez nem a teljes mozgó
entity-goal/floor migráció és nem minden élő facing-hiba igazolt javítása.

Az [exact server-pose javítás](P5_ENTITY_POSE_PRECEDENCE.md) a nem üres addon
unit-pozíció mellett is a GUID-hoz tartozó szerver XYZ-t használja. Az addon
UNIT_POSITION magassága UNKNOWN, a saját mozgáscsomagos helymeghatározás
tervezés előtti bekötése külön következő feladat.

A [grounded own first-fix](P5_POSITION_BEFORE_ROUTE.md) most már a route-query
előtt történik: a meglévő helyben fordítás utáni mozgáscsomagot várja, és a
medium lane az eredeti célt/időkeretet folytatja. Ez nem teljes flight/vehicle
first-fix vagy M0 entity-route migráció; az új élő próba még nyitott.

A [közös M0 entity route/handoff](P5_DOMAIN_NAVIGATION_HANDOFF.md) elkészült:
combat/interact/loot/LOS typed NavigationRequest, FAST → medium kérés ugyanabban
az attemptben, mozgó GUID-cél és corridor-szétválasztás, nested deadline/stop/
failure diagnostics. A FAST own-Z nézet közös packet projekciója is megvan.
A szinkron main-query és hosszú számítás utáni dispatch-forráskor a következő
P4-audit konkrét nyitott pontja; teljes felelősség-/provider-migráció még nincs.

A [lassú route-query utáni friss saját minta](P5_ROUTE_FEEDBACK.md) (a Codex-átadás
WIP-je) Claude-dal lezárva:
- 15 fókuszteszt és 4098 passed / 2 skipped / 10 változatlan deselection.
- Javítva: újracímkézett minta, a horgony-tolerancia alsó határa, 0/None határ.
- Csak offline; nem globális dispatch/ACK-rendszer és nem aszinkron worker.

A [vizuális agent kivezetése](P4_VISUAL_RETIREMENT_AUDIT.md) elkezdődött, de még
nincs kész:
- A belépési pontokat auditáltuk. Az `AUTO_START` eddig LEGACY_VISION-ban,
  packet inbox nélkül indult; most explicit SERVER, a GUI-launcherek is.
- A `MapPoint` és a `WorldPosition` a közös `wowbot/coordinates.py`-ba került.
- A SERVER-ben még legyártott, utólag szűrt vizuális javaslatok listája és a
  kivezetési sorrend a dokumentumban van.
- 5b: SERVER-ben már egyetlen tervezőág sem gyárt
  SEEK/INSPECT/OPEN_MAP/VISUAL_APPROACH/REACQUIRE javaslatot; ezt szerkezeti
  teszt őrzi.
- Hibajavítás: a soha meg nem nyíló térkép miatt SERVER-ben a TDB-fallback
  sosem kapcsolt be, most bekapcsol.
- 4111 passed / 2 skipped / 10 változatlan deselection.
- 2026-10-31:
  - 5c: SERVER-ben nincs hover-célzás. Hover helyett kulcsos út vagy azonnali,
    típusos hiba jön (`pointer_acquisition_retired`).
  - 5d: a launcherekből kikerültek a halott vizuális alapértékek.
  - 5e: a SERVER út egyetlen `wowbot.vision` modult sem tölt be. A nem
    vizuális értékek kiköltöztek, re-export marad.
  - A legacy vizuális kód tényleges törlése felhasználói jóváhagyásra vár.

[Megtartott natív kollekciók](P3_RETAINED_COLLECTIONS.md), 2026-10-31:
- A questlog- és inventory-mezőóra friss APPLIED-tanúlánccal aktuális marad,
  így a CREATE-baseline nem lesz 2 mp után UNKNOWN.
- Ez bérlet, nem TTL-emelés.
- A DECODE_GAP élre vált.
- Hátravan: warm bootstrap és consumer-paritás.

[Harc előtti regenerálódás](P7_PRE_PULL_REGENERATION.md), 2026-10-31:
- Hiszterézises REST (45/90 %) új pull előtt, szerver-HP-ból; a kanonikus M0
  REST skill végzi.
- A védekezést nem tiltja.
- Nincs pihenés/pull ciklus.
- Az étel és a harci defenzívek még nincsenek kész.

[10-28-as élő escort-hibák](P8_LIVE_1028_FOLLOWUP.md):
- A megszakított kísérlet nem quest-hiba. Emiatt indult el korábban a
  POI-repülés; ez javítva.
- A leadás alatti forgás nyitott; élő adat kell hozzá.

P3 folytatás: a korrelált saját loginhoz és ismert UnitData-fragmenthez kötött HP/max-HP
delta is eljut a közös mezőfeloldóba. Frissebb FAST felülírhat régebbi packetet,
késve érkező régi STATE nem fiatalítja meg a HP-t. A teljes saját player-baseline továbbra
sem COMPLETE. A következő körben a saját HP **CREATE-baseline-ja**, típusos
resource- és profil-prefix is elkészült; ez még nem teljes own-player-paritás.
Részletek: [saját HP és forrásidő](P3_OWN_HEALTH.md), [provider-kiegészítés](P3_PROVIDER_CLOSURE.md).

## 1. Fázisonkénti eredmény

| Fázis | Tényleges bekötés | Elfogadási határ |
|---|---|---|
| P1-E — geometria | GeometryResult és a meglévő két MMAP loader közös v16/v7 map/tile format-ellenőrzése. A WorldGeometryService, GlobalNavigator és walk-cost query megőrzi a kész/részleges/nincs út/hiányzó adat/verzió-/adathiba állapotot. Typed READY-re is érvényes a koordináta-/költség-/mapellenőrzés. | Ismeretlen dataset revision UNKNOWN marad; formátumellenőrzés nem teljes geometriai szemantikai validáció. VMAP függőleges felszín nem horizontális LOS. Élő útvonal/recovery/arrival újrapróbálás nyitott. |
| P2 — session | A SessionContextProvider kezeli a selected PID-et, dokumentált OS-folyamat-élettartamot/buildet, karakter-GUID-ot, capture-korszakot, world/mapot és baseline/gap állapotot. A korrelált normalizált login-baseline addon nélkül is létrehozza az identitást. A RuntimePacketSource és WorldPacketReducer ugyanazt fogyasztja. | Az OS-metadata és új login-packet útvonal offline tesztelt, élőben újrapróbálandó. A baseline saját identitás/map, nem teljes questlog/inventory/HP. Ezekre megjelölt addon-migrációs forrás marad. |
| P3 — authority/teljesség | A FieldSourceResolver mezőnként választ és kezeli az ellentmondást. A packet objective-POI teljes geometriája külön scoped queryn olvasható. A quest/inventory producer és fogyasztók COMPLETE/PARTIAL/UNKNOWN lefedettséget kezelnek; FAST quest-revision nem igazol régi STATE-listát. | Nincs találgatott teljes packet questlog-/inventory-/own-health baseline. A teljes consumer-paritás és az addon mezőnkénti karcsúsítása nem zárható le. Ebben a körben addonmező nem lett törölve. |
| P4 — server runtime | A SERVER profil nem konstruál Search/VisualApproach skillt, perceptiont, detektort, trackert, vizuális adatgyűjtőt vagy recognition-workert. A közös koordináták külön modulban vannak. Teljes konstruktor/status/close és a valódi PixelSensor/dekóder/reassembly/buffer → WorldModel STATE/FAST lánc importtiltó subprocess-próbán átmegy. | A képet adó OS hívás szintetikus BGRA-forrás, az executor inputmentes. A tényleges Windows GDI/DXGI és élő szerveres lánc külön live-kapu. Detektorok explicit legacy profilban elérhetők. |
| P5 — Travel | Az immutable TravelRequest tartja az eredeti célt a horizon/landing/ground folytatásokon át. A TripPlan/TripLeg/TransitionSystem/TripExecutor a meglévő NavigationService fölött követ. Érkezéshez friss, helyes map/XY, ismert cél esetén helyes szint, szükség szerint touchdown/facing kell. A zónakeresési hop LEG_COMPLETE, nem végső célérkezés. | A tényleges mozgási/mount/flight átmeneteket a meglévő kontrollerek végzik. A teljes vegyes út és barlang/tető/leesés próba még nincs újravalidálva. |
| P6 — idő/kockázat | A RouteScore külön ETA-, harc-, átmenet-, bizonytalanság- és várható recovery-másodperceket ad. Automatikus repülés mellett csak bizonyított MMAP-korridor versenyez gyalogos alternatívaként. A DangerMap megtartja az eredetet, sample-időt, mapot és Z-t. | Speed/fight/transition értékek deklarált becslések, nem élőn illesztett paraméterek. Régi/másik szintű hostile nem lesz friss harci költség. DangerMap-pontszám nem másodperc. |
| P7 — Combat | Tényleges karakter/actionbar adatokból CharacterProfile készül. A meglévő AbilityRuleEngine/CombatSkill CombatArbitratorral választ a már jogosult képességek között. Exact GUID/cast/spell, frissesség, interruptible, deadline és actual bar/binding számít; kritikus túlélés előre kerülhet. Profilváltás nem örökít régi lokális cooldown-becslést. | Teljes enemy-cast/hazard/CC/talent packet-provider és minden class/spec/tank/healer/PvP szerep nincs megvalósítva. Ismeretlen cast nem jogosít megszakításra; természetes castvég nem interrupt-siker. Első live-kapu a használt solo karakterprofil. |
| P8 — mechanikák | Egy MechanicResolver a meglévő osztályozót használja. MechanicContract és QuestExecutionGraph jeleníti meg a belső lépéseket és várt bizonyítékot a meglévő QuestGraph/runtime mellett. QuestTargetContext szétválasztja a fizikai actor/object/spell-target és technikai credit ID szerepét; a közös skill identity kapu fogyasztja. | Explicit élő questkapcsolat felülírhat statikus actorlistát, generikus sárga jel nem. Csak explicit követési mód kap támogatott escort playbookot. A mechanikák reprezentatív élő questpróbái hátravannak. |
| P9 — LLM/tanulás | Szigorú aipc.llm-plan.v1 séma, scoped readonly referenciák/eszközök, ismert jelölt-/skill-/objective-/item-/evidence-ID, aszinkron válasz, bounded cache és újravalidálás. Tanulható epizódhoz sikeres goal-verifier és összekötött action/előtte/utána/evidence kell. Manual/session-határ kizárja. Kijelölt verifier-evidence manifestek a közös writerrel SQLite-ba kerülnek. | LLM nélkül a szokásos planner működik. Régi, bizonyíték nélküli minták megmaradnak, de nem újrafelhasználhatók. A teljes történeti TDB/import/memory lineage migráció, élő kalibráció és hosszú összehasonlítás nincs lezárva. |

## 2. Fontos részletek és regressziójavítások

- Saját GUID korrelált CMSG_PLAYER_LOGIN és SMSG_LOGIN_VERIFY_WORLD alapján keletkezik. Külön instance-kapcsolatnál ezen felül pontos GUID/map/sorrend szerinti ThisIsYou ActivePlayer CREATE szükséges. Build/opcode/layout allowlist, selected PID, OS-élettartam és lokális IPC-hitelesítés külön ellenőrzés. Nem került be játékállapot-memóriaolvasó, injektálás vagy kulcskinyerés. A rögzített Ymir EXE nem változott.
- Meleg replay saját identitást és aktuális mapot ad; nem fiatalít meg régi mozgást, HP-t, inventoryt vagy quest-creditet. Verified cosmetic-map kapcsolat megtartja az addon navigációs instance-át. Valódi mapváltás után packet receipt nem frissíti az addon UI-t.
- Objective-POI aktuális objective/world szerint szűrt. Többpontos alakzat keresési terület, poligoncsúcs nem bizonyított objektum. Z=0 nem automatikusan valós padló. A status nem másol minden tickben teljes poligonokat.
- Részleges questlista pozitív tagjai frissülhetnek; kimaradók nem lesznek ABSENT és nem kapnak új sample-időt. Hibás listaalakra egy külön COMPLETE címke sem elég. Hiányos/elöregedett inventory nem jogosít bag-coordinate itemhasználatra; hiányos lista vendor iteminputra sem.
- Az első teljes regresszió hét hibát talált: keresési spiral/fall-off hop téves final-arrival kapuja; régi LOS-provider total_cost neve; UNRESOLVED playbook által elfedett canonical horizon; általános normalizált POI és pontos TDB-jelölt sorrendje; runtime modulméret-kapu. Ezek javítva, a régi tesztek benne maradtak a végső zöld körben. A vision-composition külön helperbe került.
- RouteScore csak automatikus módválasztást befolyásol; explicit flight kérés jelentése megmarad. Rövid földi alternatíva csak igazolt járható korridorral versenyezhet.
- Az LLM nem kap tetszőleges SQL-/fájl-/hálózat-/inputeszközt. Readonly snapshot bounded, játékos-entitások nem céljelöltek. A válasz felhasználás előtt az aktuális scoped referenciákkal egyezik.

## 3. Addon és telepítési állapot

Mindkét csomag azonos: addon/AIPlayerControllerExport és addon/AIPlayerControllerExport-12.1.0. Új verzió **0.9.80-12.1.0**, Interface **120100**. A snapshot collection_coverage és objective-szintű objectives_coverage mezőket küld; API-hiba/hozzáférhetetlenség nem üres, teljes lista. Hiányos cached collection legfeljebb másodpercenként passzívan újraolvasódik. Snapshot- és FAST-mezők nem lettek elvéve, sávgeometria ebben a körben nem változott.

Teljes Lua-források Lua 5.1/LuaJIT/Lua 5.4 compile-only módban ellenőrizve, és teljes TOC betöltve hamis API-val. **A 0.9.80 bemásolva a játék meglévő AddOns mappájába**, előtte a hibás telepített négy fájl külön elmentve. Az asszisztens /reload-ot nem küldött; a felhasználó kapott erre utasítást. Sikeres élő betöltési visszaigazolás még nincs.

## 4. Ellenőrzés és mérés

| Ellenőrzés | Eredmény |
|---|---|
| Végső kijelölt regresszió | **4083 passed, 2 skipped, 10 deselected; 326 modul; 211.81 s; exit 0** |
| Natív slot/session/sajátállapot/policy célzott kör | **117 passed, 2.25 s**, átfed a végső körrel; nem összeadandó |
| Teljes Python AST | 560 source + 635 tests Python-fájl; 634 test_*.py és egy teszthelper; 0 szintaktikai hiba |
| Lua | Mindkét csomag teljes Lua-fájljai compile-only zöldek; két csomag byte-egyezése külön ellenőrizve |
| IPC | A kijelölt regresszió valós localhost UDP-próbái zöldek |
| Élő kliensinput | 0; nem indult WoW/Ymir/FULL_AI |

A 10 kizárás az előző P1-D release pontos változatlan szűrője; új kizárás nincs. Két skip: hiányzó opcionális Garrick-detektor és Exile's Reach raster kép. Ez **326 kijelölt modul eredménye**, nem a teljes 634 modulos teszttár hibamentességének állítása. Az új tesztmodulok mind benne vannak.

Korábbi, a resource-/profil-kiegészítés ELŐTTI mérés: három váltakozó szintetikus futás, 220 mért ingest/belief ciklus/futás, minden tizedikben snapshot, azonos kicsi legacy workload. Az új provider-körrel nem lett újramérve:

| Verzió | Mediánok mediánja | p95-ek mediánja |
|---|---:|---:|
| P1-D baseline | 0.91175 ms | 1.66820 ms |
| Korábbi P1-E–P9, NPC cast- és HP-projectionnel | 1.14520 ms | 2.34480 ms |

Növekmény kb. 0.23345 ms medián és 0.67660 ms p95. Nem élő FPS-mérés, nem route-speed/fight kalibráció, nem a SERVER profil teljes játékmenet alatti gyorsulásának állítása. A korábbi mérési körök külön megmaradtak.

## 5. Nyitott megvalósítási feladatok

Ezek **kód-/provider-hiányok**, nem pusztán még le nem futtatott élő tesztek:

1. Teljes packet own-player/questlog/inventory baseline és minden consumer paritása; csak ezután addonmezők törlése. Addig a megjelölt addonforrás kell.
2. Teljes buildspecifikus enemy-cast/hazard/CC/talent provider és további class/spec/role kapuk. Ismeretlen információt a mostani szerződés nem tölt ki.
3. Teljes történeti SQLite/TDB/import lineage migráció. Most kijelölt verifier-evidence manifestek tartósulnak, a hiányzó történeti eredet UNKNOWN.
4. Nem támogatott questmechanikák konkrét handlerei, a bináris geometria minden verzió-/adatkülönbségének pontos diagnosztikája. Szerződés/playbook önmagában nem teljes handler.
   A megtalált fájlszintű melléklet szerinti nagy CombatSkill/NavigationService/
   quest special-case felelősségbontás és teljes import-boundary lezárás is
   valódi kódmunka; az első combat extraction nem a teljes csomag vége.
5. Élőn illesztett utazási/harc-/recovery-kalibráció és hosszú összehasonlító mérés. A mostani default súlyok becslések.

A történeti V4/Design követelmények nem változtak automatikusan teljesítettre. A coverage ledger mind a **203 számozott sorát** és korábbi bizonyítékait megőrzi.

## 6. Felhasználói élő próbák sorrendje

1. **P2:** selected PID/build, hideg belépés, már futó capture melletti GUI-újraindítás; addon reload/loading/reconnect/mapváltás. Figyelendő: provider state/source/coverage, local_ui_ready és streamfrissesség. Régi packetből ne legyen új karakter-/input-authority.
2. **P3/P4:** 0.9.80 betöltés/pixelstrip, több quest/inventoryváltozás, FAST/STATE revision eltérés; SERVER profilban nincs YOLO/perception. Ismeretlen lista ne töröljön questet és ne kattintson régi bag-slotra.
3. **P5/P6:** séta/mount/steady/skyriding/vegyes út, barlang/spirál/nagy Z/tető/leszállás/leesés, cancel/combat. Eredeti cél megmarad; köztes hop nem végső siker. RouteScore összetevők követhetők.
4. **P7:** tényleges karakter/bar/binding, két mozgó cél, range/facing/resource/túlélés. Interrupt csak exact cast-adattal, külön bizonyított megszakítással fogadható el.
5. **P8:** talk→duel, item→hatás→credit, vehicle/visszaülés, explicit escort, scene/conversation, több objective/felvétel/leadás. Fizikai szereplő és technikai credit ID külön, siker saját verifierből.
6. **P9:** először LLM nélkül, majd adviserrel ugyanaz a támogatott lánc; stale/hibás terv, MANUAL és sessioncsere. Csak bizonyított és kézzel meg nem szakított epizód tanulható.

Minden próbáról trace és tényleges eredmény kerül a LIVE_VALIDATION.md-be. A felhasználó a live operátor; a lista nem engedély automatikus kliensvezérlés indítására.

## 7. Mentés és reprodukció

Az [evidence könyvtár](p1e-p9-evidence/) tartalmazza a **P1-E előtti, már P1-D-t tartalmazó** scoped baseline-t, az új forrás/test/addon állapotot, byte-hasheket, unified diffet, pontos parancsot/kizárásokat, JUnit/logeredményeket, benchmarkot és AST/coverage ellenőrzést. Memóriaadatbázis, képek, telemetria, auth/session anyag és játékállapot nincs a mentésben. Ez forrás/addon checkpoint, nem teljes felhasználói adat-/konfigurációmentés.

A jelenlegi checkpoint nem írja felül a baseline-t. A runtime Ymir backend hash-ellenőrzése olvasás; az EXE nem módosult.
