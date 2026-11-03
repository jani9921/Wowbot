# Claude átadás — REV4 agentreform, 2026-10-30

## 0. Ezt olvasd először

**A teljes reform NINCS kész. A jelenlegi munkamappa már tartalmaz a legutolsó nagy zöld teszt UTÁNI, befejezetlen módosításokat is.** Ne nevezd a teljes jelenlegi forrást 4083 teszttel ellenőrzöttnek.

**A felhasználó legújabb, közvetlen iránya: az agentből fokozatosan ki kell vezetni minden vizuális felismerést és a rá épülő viselkedést.** Nem kér kamera utáni vizuális track-ID javítást, YOLO-/OCR-/tracker-fejlesztést. Ezt a projekt `AGENTS.md` is rögzíti. A mostani GUID- és útvonalmunka szerveres identitásról szól, nem kamera utáni képi követésről.

A felhasználó átadást kért, mert Codex kerete fogy. Új funkcionális kódolást az átadás készítésekor már nem folytattam; a WIP állapotot külön mentjük. Az élő tesztet a felhasználó kezeli, az asszisztens logot vizsgál. Ne indíts automatikusan WoW-ot/Ymir-t/FULL_AI-t és ne vedd át a kliensinputot.

### A valódi projektmappa

```text
C:\Users\<user>\Documents\ChatGPT\ai_visual_bot_midnight claude\ai_visual_bot_midnight 1.2\projekt
```

**Közvetlenül ebben dolgozz.** Nem az `uj-mappa-*`, nem az export/GitHub másolat, és nem a Codex alapértelmezett munkakönyvtára a fő projekt.

Az alábbi másik mappában csak a mi scratch munkáink és futtatóink vannak:

```text
C:\Users\<user>\Documents\ChatGPT\ai_visual_bot_midnight 1.2\_work
```

Nincs szükség vak átmásolásra vagy rollbackre. A kész módosítások már a `projekt` forrásában vannak. A másik chat korábbi forrása nem tekinthető automatikusan frissebbnek.

## 1. Mely dokumentumok mérvadók?

1. `AGENTS.md`, benne a legfrissebb felhasználói iránnyal.
2. `wow_agent_FINAL_M0_M1_master_prompt_v4.txt`: V4 0–100.
3. `wow_agent_complete_functional_design_spec.txt`: Design 1–102.
4. `docs/CURRENT_SOURCE_COVERAGE.md`: mind a **203 számozott sor** megmarad.
5. `docs/reform/rev4-20261029/P1E_P9_IMPLEMENTATION.md`: aktuális integrációs állapot és nyitott kapuk.
6. `docs/reform/rev4-20261029/ATVETEL_ES_ATALLASI_TERV.md`: az eleje aktuális, a későbbi régi átvételi részek történetiek.
7. `docs/reform/rev4-20261029/input/SRC_MIGRACIOS_TERV_20261029_HU.md`: a felhasználó utólag átadott, 747 soros tényleges forrásmigrációs melléklete.
8. `docs/reform/rev4-20261029/MIGRATION_SUPPLEMENT_REVIEW.md`: a melléklet M0–M8 és a reform P0–P9 számozásának megfeleltetése. Nem ugyanazok, mint a master M0/M1 elfogadási szintek.
9. `docs/reform/rev4-20261029/input/STATUSZ_ES_TULELES_KIEGESZITES_20261030_HU.md`: HP, pihenés/étel, defenzívek követelményei. Az elején lévő régi tesztszám történeti; a képességeket nem szabad ettől késznek tekinteni.
10. `docs/LIVE_VALIDATION.md`: tényleges élő bizonyítékok és nyitott hibák.

Az eredeti ZIP-dokumentumok és a mellékletek külön hash-pinnelt `input/` és manifest állományokban megvannak. Az eredeti ZIP hiánylistáját ne írd át: akkor tényleg hiányzott a később megtalált fájl. A `plan-evidence.json` nem került elő.

Ne állíts új százalékot megérzésből. A korábbi 70/80% becslés nem bizonyíték. Package létrehozása vagy adapter bekötése nem a teljes felelősségmigráció.

## 2. Legfrissebb felhasználói termékirány: a vizuális agent kivezetése

A korábbi „őrizd meg a működő detektorokat” irányt az agent működésére vonatkozóan a felhasználó most felülírta. Fokozatos kiváltást és kivezetést kér.

### A kívánt irány

- Szerveres, ellenőrzött szemantikai események, GUID/NPC-/object-ID és strukturált állapot vezesse az agentet.
- Ne javíts tovább kamera utáni képi ReID-t, bbox-smoothingot, YOLO/OCR-t vagy vizuális targetkeresést a reform feladataként.
- A production belépési pontokban a SERVER összetétel legyen egyértelmű; a maradék vizuális fallbackek ne kapcsolódjanak vissza csendben.
- Auditáld és váltsd ki a `SEEK_VISUAL_CUE`, `VISUAL_APPROACH`, képi hover-acquisition, vision/tracker/perception worker, vizuális loot/cellakeresés és kapcsolódó GUI/config/import ágakat, majd távolítsd el a kiváltott kódot és függőségeket.
- Jelenleg SERVER profilban már nincs YOLO/perception konstrukció, de például `AutonomousAgent(..., runtime_profile=None)` még LEGACY_VISION alapértékre esik. Az összes launcher/BAT/GUI/default tényleges bekötését külön auditálni kell.
- A vision csomagból importált puszta értéktípusokat, például `WorldPosition`, előbb közös spatial/geometry szerződésbe kell mozgatni. A navigációt ne törd el a könyvtár mechanikus törlésével.

### Ami ettől még kellhet

Az addon **strukturált helyi UI-adata** és a pixelstrip mint telemetria-szállítás nem ugyanaz, mint a world-képfelismerés. Selected target, soft recipient, actionbar/range/readiness, quest/gossip/reward UI és UI-koordináták még kérhetnek addonforrást. Ezeket csak ellenőrzött paritás után szabad törölni. Az addon csíkjának színrács-dekódolását ne azonosítsd a YOLO/OCR/trackeres világfelismeréssel.

A GUID identitást bizonyít; nem ad önmagában jogosultságot tetszőleges játékfolyamat-írásra, protected API-ra vagy közvetlen célszelekcióra. Input továbbra is a meglévő, igazolt binding/UI/végrehajtó úton megy.

Ezt a kivezetést **még nem implementáltuk teljesen**. Az új irány átadáskor lett egyértelműen rögzítve; nem kezdtünk most nagy fájltörlésbe. Datasetet, képet, modellt, felhasználói DB-t vagy futási adatot nem töröltünk.

## 3. Ellenőrzött állapot: kész checkpoint és jelenlegi WIP

| Állapot | Mit jelent? |
|---|---|
| Utolsó nagy zöld kör | **4083 passed, 2 skipped, 10 változatlan deselection; 326 modul; exit 0.** Pytest 211.81 s, runner 214.51 s. |
| Hozzá tartozó forrás | `docs/reform/rev4-20261029/domain-navigation-handoff-evidence/current-source.zip` |
| Hash/diff/parancs/JUnit | Ugyanott `current-files.json`, `changes.patch`, `changes.json`, `artifact-hashes.json`, `verification.json`, `combined-domain-navigation-final-*`. |
| Akkori teljes AST | 560 source + 635 test Python-fájl, 634 testmodul; 203 számozott coverage-sor. Nem a teljes 634 modul futott. |
| Későbbi WIP | Route feedback + projected endpoint/arrival finomítás, részletesen lent. Ez már a jelenlegi src-ben van. |
| WIP jelenlegi ellenőrzése | **117 passed**, 2.55 s, exit 0, meglévő kapcsolódó tesztek. **Új célzott WIP-tesztek még nem készültek, teljes széles kör még nem futott erre az állapotra.** |
| WIP AST | 561 source + 635 test Python-fájl szintaktikailag érvényes; 203 sor megmaradt. |
| Élő elfogadás | Az új javításokra nincs új elfogadott live quest/combat/route proof. |

A WIP külön mentése: `docs/reform/rev4-20261029/route-feedback-wip-evidence/`. **Ne keverd a 4083-as kész checkpointtal.** Az átadáskori tényleges forrás, patch és reprodukció ott lesz.

A két skip: hiányzó opcionális Garrick-detektor és Exile's Reach raster kép. A tíz kizárás a régi P1-D pontos változatlan filtere; nem új hibákat rejtettünk el. A lista a mentett pytest command JSON utolsó `-k` értékében ellenőrizhető. Új kizárással ne tedd zölddé a reformot.

## 4. Ami a reformból ténylegesen megvan

### P0/P1 — alap, közös szerződések és függőségek

- Scoped, visszaellenőrizhető source/test/addon baseline és checkpointok, hash-ek és patch-ek.
- Explicit navigation query/cost portok: példányhoz kötött lekérdezések, a korábbi globális route-cost oracle helyett.
- Session identity és változó world/map scope külön szerződések.
- Közös evidence értékek, source/received timestamp, lineage/eredet és forrásgyökér-egyeztetés; a származtatott vagy visszajátszott adat nem lesz új élő bizonyíték.
- Mezőnkénti forráspolitika: nem elég általánosan azt mondani, hogy „a packet mindig felülír mindent”. A selected target és UI helyi kliensállapot; entity XYZ lehet szerveradat.
- 203 történeti coverage-sor megmaradt. A teljes importgráf-takarítás és minden régi felelősség kiváltása még nincs lezárva.

Dokumentumok: `P1A_QUERY_ISOLATION.md`, `P1B_SESSION_CONTEXT.md`, `P1C_NAVIGATION_QUERIES.md`, `P1D_EVIDENCE_LINEAGE.md`.

### P2/P3 — session, folytonosság, natív adatok

- Kiválasztott PID/process generation/build alapú session-provider; független saját login/world kapcsolat bizonyítása.
- A realm és instance connection eltérhet. Cross-connection bindinghez exact pending login GUID, map/order/time és publikus `ActivePlayer` + `ThisIsYou` CREATE bizonyíték kell. Nem találgatjuk a connectiont és nem olvasunk ismeretlen saját private prefixet.
- Új login ugyanabban a PKT-fájlban is új capture epochot és cache-resetet okoz. Header/file rotation is kezelt.
- Hitelesített V2 helyi IPC + delivery sequence. Valódi rés, overflow, queued expiry vagy sender/context csere folytonossági hibát és native invalidálást/rebaseline-t okozhat; normál high-rate coalescing nem automatikusan adatvesztés.
- `aipc.packet-progress.v1` valódi dekóder-record progress és WorldModel applied-watermark. Csak igazolt saját connection és ténylegesen alkalmazott collection-esemény számít. Timer/heartbeat nem bizonyít feldolgozott adatot.
- Own HP/max HP CREATE/VALUES, power/resource/profile prefixek és megfelelő field-clocks.
- Own questlog-prefix, 175 slot / 24 counter; saját CREATE/VALUES. Questdefiníció és exact/egyértelmű objective storage-kötés. Nem ordinalból vagy credit ID-ból találunk ki fizikai NPC-t.
- Item/container CREATE/VALUES és Active root slot frissítések, saját ownership/map/context, slot/field külön idő és invalidation barrier. Darabszám lower-bound lehet; UI bag-slot címzést nem gyártunk a natív indexből.
- Unknown saját maszk/prefix/outer decode gap invalidál; régi teljes collection nem maradhat kész csak egy új slot miatt.
- Egységes saját navigation projection a medium és FAST nézetre. Új addon XY nem törli a helyben álló karakter igazolt szervermagasságát; GAP-ben örökölt packet-Z nem marad ismert.

**Hiány:** teljes retained quest/inventory collection lifecycle, warm baseline/replay, minden consumer paritása. A natív rövid TTL-eket nem szabad egyszerűen megemelni. A decoder progress nem hosszabbítja automatikusan a mezők frissességét és nem ad inputjogot.

Dokumentumok: `P2_PACKET_DELIVERY.md`, `P2_APPLIED_PACKET_PROGRESS.md`, `P2_LIVE_SESSION_NAVMESH_FIXES.md`, `P2_P3_NATIVE_QUESTLOG.md`, `P3_OWN_*`, `P3_NATIVE_INVENTORY*.md`, `P3_QUEST_LOG_INVALIDATION.md`, `P3_SERVER_QUEST_DEFINITIONS.md`, `P3_PROVIDER_CLOSURE.md`.

### P4 — runtime összetétel és addon

- SERVER összetételben nincs world vision/tracker/perception worker-konstrukció; a legacy visual út külön megmaradt, ezt kell most fokozatosan kivezetni.
- Az addon 0.9.79 Lua 5.1 upvalue-limit betöltési hibáját namespace helperes bontás javította 0.9.80-ban. Két addoncsomag byte-azonos; korábban Lua 5.1/LuaJIT/5.4 fordítás és TOC fake-API load futott.
- Támogatott UI/FAST struktúrák, field-források és authority gate-ek megmaradtak; a pixelstripet paritás nélkül nem töröltük.
- **Még auditálandó:** tick eleji freshness után hosszú számítás alatt megöregedő frame és dispatch-pillanat. Az általános dispatcher nem kapott ebben a körben teljes új frissességi/ACK-tranzakciós rendszert.

### P5/P6 — navigáció és utazás

- Közös Python/natív MMAP/Detour formátumellenőrzés, ERROR és NO_ROUTE jelentésének szétválasztása.
- A szabályos Trinity signed `maxPolys = -2147483648` kapacitás elfogadása; nem engedünk minden negatív headerértéket. Valós map-0, 2175 és 2444 headerrel ellenőrizve.
- TravelRequest/TripPlan/TripExecutor, eredeti cél és köztes leg/horizon/ground-handoff elválasztása. Egy leg vége nem automatikus végső érkezés.
- Meglévő MMAP/VMAP/flight/steady/skyriding/walk–flight–walk elemek újrahasználata. Nem új navigációs brain.
- RouteScore deklarált seconds/ETA/veszély/átmenet összetevők és ground/flight összevetés; a súlyok még heurisztikusak, nem élőn kalibráltak.
- Addon UNIT_POSITION Z ismeretlen, akkor is, ha numerikus 0/nonzero és régi `z_known=True`. A valódi szerver Z=0 megmarad. Exact same-GUID, same-world entity pose megelőzi a nem üres addon unitpozíciót.
- Saját pozíció/Z hiányánál grounded MMAP request előbb a meglévő 0.06 s helyben fordító probe-ot kéri, és mozgáscsomagra vár a tervezés előtt. A régi ugrást korábbi mérés után ez váltotta fel. Maximum 3 s / eredeti rövidebb budget; nincs előresétálás vagy megérkezés az ismeretlen Z-ből.
- Állva a megfigyelt own height azonos scope/közeli változatlan XY mellett megmarad. Nem kell állandóan újra ugrálni/fordulni.

**Legutolsó kész nagy munka, 4083-as checkpoint:**

- `move_to_entity` mindkét korábbi közvetlen controller-ágát typed `NavigationRequest` váltotta. A szerverág tényleges geometriát igényel; a jelző jelenléte önmagában már nem helyettesíti a route queryt.
- COMBAT/DEFEND, INTERACT/TALK és LOOT azonos NavService-n megy; az utolsó LOS route-lépés is.
- FAST ugyanazon owned requestet sorba teszi, felengedi a mozgást és medium handoffot kér. Nem futtatja még egyszer a domén verifiert, nem fogyaszt plusz retry-t, nem indít másik actiont.
- Medium aktuális GUID/scope/inputállapot/deadline ellenőrzéssel tervez. Eredeti request/Trip kezdőidő és aktív attempt budget megmarad. LOS route cap 2.5 s.
- Mozgó entity goal az eredeti GUID-ot jelenti, kezdeti XYZ-je pillanatkép. Nagyobb elmozdulás medium replant kér; köztes corridor anchor nem követheti közvetlenül a mobot. Statikus forge-corner cél nem válik mozgó céllá.
- Nested megérkezés/failure fizikailag felengedi a mozgást a F7/cast előtt. `preserve_navigation` csak a handoffra tartja meg a saját pending requestet; rendes STOP/MANUAL eldobja.
- `SKILL_NAVIGATION_FAILURE_DETAIL` / `NAVIGATION_FAILURE_DETAIL` bounded ok/facing/sample/probe nyomot őriz, teljes world/corridor ismételt másolása nélkül.
- Loot-approach same-GUID server corpse pose-t is használ `allow_dead=True` helyadatként. Ez nem saját lootjog vagy automatikus lootsiker.

Dokumentumok: `P1E_MMAP_FORMATS.md`, `P5_ENTITY_POSE_PRECEDENCE.md`, `P5_POSITION_BEFORE_ROUTE.md`, `P5_DOMAIN_NAVIGATION_HANDOFF.md`.

### P7 — combat

- Valódi Target/Ability/catalog/arbitrator/GUID/number/facing implementációk canonical helyre költöztek; a régi modulok ugyanazokat az objektumokat reexportálják.
- `combat/target/system.py`, `combat/ability/contracts.py`, `combat/ability/evaluator.py`, `combat/ability/catalog.py`, `combat/contracts.py`, `combat/arbitrator.py`, `combat/target/facing.py`.
- A core külön subprocessben is működik tiltott agent/skills/navigation/vision/input importok mellett; 27 költöztetett deklaráció AST-egyezését ellenőriztük.
- A saját új Charge utáni mozgás rövid, eredeti cast-időhöz kötött settle-t kap, hogy az első késő range-frissítés előtt ne bukjon el 0.14 s alatt. Ez nem általános WAIT és nem range/cast engedély.
- Charge max range nem lesz a sustained melee rotáció desired range-je. Közel a mobhoz nem kell Charge-ra várni, ha valódi nem-movement harmful spell in-range. Ismert ranged envelope külön megmarad.
- Három tiszta entity-pose helper `entity_spatial.py`-ban, régi azonos reexportok; végső facing `navigation/facing_geometry.py`-ban, exact GUID/map/reason ellenőrzéssel.
- Öt enemy cast opcode adatútja és exact cast identity alapú interrupt/critical survival arbitráció részben megvan. UNKNOWN interruptibility nem enged interruptot.

**Hiány:** a nagy `skills/combat.py` tényleges vékony FSM-re bontása; a teljes rotation/positioning/reaction/CC/defensive jelöltkészlet, profilfüggő túlélés/étel/regen, aura/talent/hazard/channel szolgáltatók és használt solo karakter teljesebb kezelése. A CombatController és CombatSkill külön ability engine állapotának teljes konszolidálása sem lezárt. Dungeon/raid/PvP nem cél az M0/M1 kapuk előtt.

Dokumentumok: `P7_COMBAT_EXTRACTION.md`, `P7_PACKET_CASTS.md`, `P7_COMBAT_RANGE_HANDOFF.md`, `P7_RANGE_FACING_FOLLOWUP.md`.

### P8 — questmechanikák

- Közös mechanic classifier/resolver, TargetContext: technikai credit ID és tényleges fizikai actor külön.
- Belső graph/readiness/lépés/horizon és verifier-trial bekötések, támogatott existing handler/skill utak.
- **Nem teljes:** minden special-case felszámolása, minden playbookhoz konkrét végrehajtó/verifikáló ág, conditional/recovery-edge graph executor, teljes lookahead/agenda és unsupported mechanikák.
- Az objective-régió/POI/TDB/live entity/UI információkat mezőszemantika szerint kell használni. „A szerver tudja” nem jelenti minden kapcsolat ténylegesen dekódolt jelenlétét.

### P9 — advisor, memória és proof

- Opcionális, read-only aszinkron helyi adviser szigorú ismert referenciákkal; nem input-owner és nem kötelező a determinisztikus M0/M1-hez.
- Tartós epizód-proof: ténylegesen mentett before/after evidence manifest, eredeti idő/scope, külön forrásgyökerek és tartós dedup; MANUAL/session break után nem tanulható sikeres epizód.
- Régi V1/historikus adat megmarad, de hiányzó eredetből nem lesz újrafelhasználható pozitív proof.
- **Hiány:** teljes történeti SQLite/TDB/import lineage, minden skill verifier-manifest lefedettsége, retained replay/warm state és teljes domain-/import-boundary lezárás.

Dokumentum: `P9_PERSISTED_EPISODE_PROOFS.md` és a teljes `P1E_P9_IMPLEMENTATION.md`.

## 5. A befejezetlen WIP pontosan

Scratch:

```text
C:\Users\<user>\Documents\ChatGPT\ai_visual_bot_midnight 1.2\_work\rev4-route-feedback-20261030
```

Baseline-ja a 4083-as kész checkpoint. Az új változások már az éles forrásmappában vannak, de élő agentet nem indítottunk rájuk.

### WIP módosítások

1. Új `navigation/route_feedback.py`: immutable post-query visszajelzési feltétel. 0.6 s-nál hosszabb tervezés után friss, a számítás végét követő saját mintát kér. Scope/vehicle/death/ghost változást vizsgál; a várás legfeljebb 2 s, eredeti budget továbbra is érvényes.
2. `NavigationService.start_request` és `local_plan` időmérése `_planning_clock` / `time.perf_counter` alapján; a tényleges régi implementáció `_start_request` / `_local_plan` néven ugyanott van. Nincs második navigator. Lassú eredmény után nincs azonnali parancs a régi frame-ből.
3. `resume_owned_route` READY/WAITING/REPLAN/typed failure kezelése. Közben >2 yd saját elmozdulás, megfigyelt Z-váltás vagy új ismert magasság replant kér. Normalizált térképnél külön .003 távolsági skála.
4. A normál movement runner is ugyanazt a resume API-t használja. FAST `movement_route_plan_pending` jelzéssel mediumot kér; ez a `ParallelControl.drives` feltételeiben is szerepel.
5. `entity_goal.anchor_tolerance`: projected endpoint eltérését levonja az entity interaction bandből. Nem szeretnénk a projektált végpontnál még egy teljes 3.5 yd sugarat hozzáadni és túl messze megállni. A start_request korábbi, második arrival-radius felülírása megszűnt.
6. Corridor/waypoint azonosító a routed entity controller-key része: új útvonalon ne maradjon a régi végpont megérkezési bizonyítéka csak azért, mert a GUID azonos.
7. Kicsi, <2 yd targetmozgás is replant kérhet, ha az előző controller már ARRIVED, de a tényleges actor kikerült a kívánt távolságból.
8. Explicit typed request timeout minden owned requestnél ellenőrzött, nem csak entity_goal esetén; a default nélküli legacy szerződést nem alakítottuk át korlátlan új budgetté.
9. Bounded `route_feedback` diagnosztika a movement és nested failure nyomban; post-plan timeout STALE_OBSERVATION, scopeváltás WRONG_MAP_CONTEXT.

### Ezt kell legelőször ellenőrizni

**Ne folytasd vakon úgy, mintha ez kész lenne.** A meglévő kapcsolódó kör 117 pass, de kifejezetten ezekhez a WIP mechanizmusokhoz még nincs új tesztmodul és nincs új széles regresszió.

Készíts célzott próbát legalább ezekre:

- Lassú első query után nincs mozgási command régi vagy csak újracímkézett mintából; valóban frissebb forrás kell.
- `_planning_clock` injektált hamis órával tesztelhető; ne hosszú sleep-pel teszteld a teljes ágat.
- Meleg/gyors query nem okoz felesleges megállást. A küszöb körüli értékek is számítanak.
- Lassú local replan se adjon azonnal régi commandot.
- Eredeti request/attempt/LOS deadline nem hosszabbodik meg a számítástól és feedback-várástól.
- Scope/PID/map/vehicle/death/ghost váltás, loading/input-block, cancel/reset és késői packet ne élesszen vissza régi útvonalat.
- Saját XY és megfigyelt Z elmozdulása újratervezést kér; FAST nem végezhet nehéz queryt.
- Projected endpoint + interaction band: ténylegesen elég közel álljon meg; ne legyen hamis arrival, új jitter vagy nagy objektumba futás. Known Z=0, ismeretlen Z, offset endpoint és stop radius 0/None határok is kellenek.
- Mozgó target <2 yd elmozdulása a reach szélén ne hagyja örök Trip RUNNING/ARRIVED ciklusban; élő facing és ugyanaz a GUID maradjon.
- Új corridor/waypoint resetelje a régi arrival-proofot, de az eredeti action/request/trip budget ne induljon újra.
- Legacy/cue és a még meglévő flight/vehicle/ground handoff regressziók, mielőtt a vizuális legacy utat kiváltod.

**Fontos határ:** a WIP nem teljes globális dispatch-frame/frissesség rendszer és nem aszinkron route-worker. Az agent lock alatti cold mesh query továbbra is blokkolhatja a főciklust. Ne állíts ebből folyamatos 30 Hz-es élő vezérlést.

A `FreshnessGate.evaluate` állapotot módosít (recovery confirmation), ezért ne hívd meg még egyszer ugyanarra a megfigyelésre dispatch előtt és gondold, hogy ezzel megoldottad a frissességet. A commandot előállító skill FSM sok helyen már dispatch előtt módosul; egy később eldobott command nem tekinthető végrehajtottnak. Ezeket a közös execution/ACK határon kell rendesen rendezni.

## 6. Javasolt következő munkasorrend Claude-nak

1. Olvasd el ezt, az aktuális AGENTS-et és az érintett master/supplement részeket.
2. Auditáld a WIP patch-et a 4083-as baseline ellen; fejezd be és teszteld a fenti konkrét feedback/arrival ágakat. Tudatos döntéssel javítsd/korrigáld, ne vak rollbackkel vagy további foltozással.
3. Futtasd a meglévő célzott kört, az új fókuszteszteket, majd a kijelölt széles kört az eredeti tíz kizárás változtatása nélkül. AST, 203 coverage-sor és hash-ek.
4. A legfrissebb felhasználói irány szerint tedd egyértelművé az összes production SERVER belépési pontot. Írd össze a ténylegesen futó vizuális fallbackeket és szükséges szerver/UI kiváltásukat; utána inkrementálisan vezesd ki őket. **Ne tölts időt vizuális track-ID folytonosság fejlesztésére.**
5. Teljes retained/native collection lifecycle + warm bootstrap és consumer parity. Invalidation/progress/field-clock kapuval, nem TTL-emeléssel vagy hibás „complete” listákkal.
6. A forrásmelléklet szerinti tényleges CombatSkill és NavigationService felelősségbontás. Jelenleg a nagy service a pending/feedback kezeléstől még nagyobb is lett; közös facade mögé tényleges komponensek kellenek, nem üres új Manager rétegek.
7. Használt solo karakter: közös arbitrator, rotation/positioning/defensive/survival/étel/regen/talent/cast szolgáltatók. Hiányzó adat UNKNOWN. Pihenés és védelmek nem tekinthetők késznek csak a HP-providerből.
8. Questmechanika graph: valódi feltételek, recovery-edge-ek, még hiányzó konkrét handler/verifier utak; teljes agenda/horizon és régi special-case kiváltása.
9. P9 történeti lineage, verifier-proof lefedettség, teljes consumer/import boundary és majd felhasználói live elfogadási kapuk.

## 7. Tesztfuttatás és mentések

A telepített Pythonhoz `py -3.13 -B` működött. A mi runnereink `PYTHONPATH=projekt/src`, UTF-8, külön TEMP/TMP, `AIPC_SEMANTIC_ENABLED=0`, nem létező temp reference SQLite és `pytest -p no:cacheprovider --basetemp ... --junitxml ...` beállításokkal futottak. Éles DB-t nem adunk a teszteknek.

Utolsó kész scratch:

```text
C:\Users\<user>\Documents\ChatGPT\ai_visual_bot_midnight 1.2\_work\rev4-domain-navigation-handoff-20261030
```

Jelenlegi WIP meglévő regressziója:

```powershell
py -3.13 -B "C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-route-feedback-20261030/run_targeted.py" claude-existing-feedback-1 tests/test_domain_navigation_handoff_20261030.py tests/test_position_before_route_20261030.py tests/test_navigation_service.py tests/test_movement_skill_runner.py tests/test_route_start_corner_20261004.py tests/test_parallel_control.py tests/test_trip_lifecycle_20261030.py
```

Az új fókuszteszteket ezután külön add hozzá; a fenti parancs csak a már meglévő 117-es kört reprodukálja.

A régi teljes runner a scratch-en kívüli P1-D command JSON-ra is hivatkozik. Helyben megvan, de másik gépre nem önmagában hordozható. Az átadási WIP evidence könyvtárba kerülő `run_handoff_regression.py` a projektben mentett 4083-as modullistából és az eredeti filterből indul, és a 2026103* új teszteket is hozzáveszi:

```powershell
py -3.13 -B "C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/reform/rev4-20261029/route-feedback-wip-evidence/run_handoff_regression.py"
```

Ez külön temp munkakönyvtárba ment parancsot, logot, eredményt és JUnitot. Nem futtattuk most új teljes körként. Új tesztfájlokat szükség esetén `--module tests/...py` argumentummal is hozzáadhatsz. A teljes teszttár továbbra sem azonos a kijelölt körrel.

Minden checkpoint source/tests/addon/static dokumentumokra korlátozott. Nem teljes felhasználói konfiguráció-/adatmentés. Nincs benne éles memória, screenshot gyűjtemény, dataset vagy raw PKT. A munkaprojektben az átvételkor nem volt `.git`; a mentéseket ne keverd az export/GitHub repositoryval.

## 8. Élő hibakeresés és még nem bizonyított javítások

A 2026-10-30-i hosszabb, vizsgált futás: `output/agent/pid-7784`, a fájlok szerinti kb. 17:04–17:12. Előző hasznosak: pid-12912, pid-7592, pid-5408, pid-6856, pid-10152. Ezek régi PID-ek; **nem input-authority azonosítók**.

A hosszabb futásban pozitív native session/READY és map-0 route bizonyíték volt. Kilenc target-death és nyolc loot verifikáció is szerepelt, de kézi beavatkozás határai nem teljesen ismertek: ez nem teljes autonóm quest-proof.

11 mozgási/facing failure, két COMBAT out_of_range, két route endpoint-envelope, quest dialog/identity eset is volt. A Charge/range és route/adatút hibákat offline javítottuk, de **mind a 11 facing-hiba okát és élő javulását nem bizonyítottuk**. Az új bounded diagnostics csak friss GUI/agent újraindítás utáni futásokban jelenik meg.

A map-0 valódi mentett-pose MMAP-query működött; 2444-en az akkori, ismeretlen Z-s kezdőpont nem volt ground meshen. Ez nem bizonyítja az összes flight/start/landing/Z-eset megoldását. Néhány régi PKT-fájlt a runtime/felhasználói takarítás eltüntetett, a korábbi offline probe eredményei a scratch és evidence könyvtárakban megmaradtak.

Az éles memória csak olvasáshoz:

```text
projekt/output/agent/profiles/<user>/agent_memory.sqlite3
```

Ha logot olvasol belőle: SQLite `mode=ro`, **uri=True**, `PRAGMA query_only=ON`, lehetőleg bounded idő/id lekérdezések. Ne nyisd meg AgentMemory writerként. Fő táblák: `observations` (id/session/at/source/correlation/payload/recorded_order), `journal` (id/session/at/kind/payload). A payload szerkezetet ténylegesen nézd meg, ne feltételezz új oszlopokat.

## 9. Fontos invariánsok és érintetlen dolgok

- Egy AutonomousAgent / WorldModel / planner / ActiveSkillRuntime / NavService / dispatcher / verifier lánc. Nincs külön quest/fishing/mining brain vagy második aktív skill.
- GUID/NPC-/object-ID célazonosság. A vizuális track ID nem lehet célazonosság vagy inputengedély; most a vizuális út kivezetése a feladat.
- Saját XYZ saját movement feedbackből származhat; addonból nincs megbízható Z. `0` lehet valós szervermagasság, a hiányzó érték nem 0. CMSG mozgásfeedback nem automatikus szerver-ACK.
- Bindingot nem találgatunk; selected PID és a hozzá tartozó igazolt cache mérvadó.
- Addon/telemetria/UI inputigény paritás nélkül nem törölhető. A vizuális legacy kivezetés nem jogosít raw packet/secret/privát adat exportjára vagy tetszőleges memóriaolvasásra.
- Pin változatlan:

```text
runtime/ymir/ymir_retail_12.1.5.70575_PORT_CANDIDATE_V3.exe
SHA-256: 77cc8a63b94ee52c47090290a69f3d6fa3db3995ded3c7534c886c85dcbec6b9
```

- A két addoncsomag azonos, Interface 120100. A mostani kódolás során nem másoltunk új addont a játékba és nem módosítottunk Ymir binárist.
- A korábbi screen-space `navigation/facing.py` FaceController byte-változatlan; a matematikai új segéd külön `facing_geometry.py`. Régebben egy kezdeti fájlnévütközést korrigáltunk a checkpointból; ne írd újra véletlenül a megmaradt modult.
- Egy régi input nélküli offline replay, szintetikus IPC vagy valós formátumú testtile nem kész élő quest. Minden új sikerállítást a tényleges bizonyítékhoz köss.

**Átadás vége:** először a WIP feedback/arrival kaput zárd tesztekkel, majd a szerveres reformot és a vizuális út tényleges kivezetését folytasd. A 4083-as checkpoint a legutolsó nagy zöld alap, nem a teljes mai WIP automatikus igazolása.
