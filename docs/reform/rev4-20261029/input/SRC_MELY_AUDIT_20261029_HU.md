# WoW agent — mélyebb forrásaudit és migrációs korrekciók

**2026. október 29. · Alap: a felhasználó által feltöltött `src (2).zip`.**

> **Bizonyítékszintek:** `FORRÁSBAN IGAZOLT` = konkrét forráshely vagy AST/import elemzés; `TERVEZETT` = még nem implementált cél; `NYITOTT` = forrásból nem igazolható vagy még nem végigkövetett viselkedés. A dokumentum nem állítja, hogy teljes live vagy regressziós funkcionális audit zajlott volna. A ZIP csak a `src` mappát tartalmazza; sem a teljes addon Lua producer, sem a tesztek, sem a nagy adatbázisok, sem az élő packetküldő/native implementáció nem volt ebben a csomagban.

## 0. Mit ellenőriztem most ténylegesen?

- **498 Python-forrás, 104 128 sor**; a feltöltött ZIP-ből kibontott állapotban **mind a 498 fájlt AST-szinten sikerült parse-olni**; szintaktikai hiba nem volt. Ez NEM jelenti az importálhatóság vagy működés tesztjét.
- Teljes forrásfa alapján statikus importgráf, csomagközi hivatkozások, erősen összefüggő importcsoportok, legnagyobb függvények és méreteloszlás.
- A döntő adat-/vezérlési csomópontok forrása, osztály- és függvényhatárai, a kritikus kezdeményező/consumer kapcsolatok. A felülvizsgált vonalak: `AgentRuntime.step` → `AutonomousAgent.tick` → `WorldModel.ingest` / `WorldPacketReducer`, `PlanningOrchestrator` / `AutonomousLoop` → `ActiveSkillRuntime` / `CommandDispatcher` → `InputExecutor`; Travel `NavigationService.start_request` → `GlobalNavigator.plan` → MMAP / FlightTrip → Movement; Combat `CombatController` / `TargetManager` / `AbilityRuleEngine` → `CombatSkill`; Quest `QuestModel` / `QuestGraph` / `QuestDomain` → skills / verifikáció.
- **NEM**: minden függvény kézi soronkénti szemléje; sem live WoW-kliens; sem tesztek futtatása (nincsenek a ZIP-ben); sem a teljes Ymir producer és addon Lua szemantikájának ellenőrzése. A nagy grafikus/képalkotó részeket inventorizáltam és a rendszerhez való kapcsolódásukat vizsgáltam, nem teljes CV-modellenként auditáltam.

## 1. Mennyiségi eredmény és miért veszélyes a mechanikus MOVE

| Terület | Fájl | Sor |
|---|---:|---:|
| `wowbot/agent` | 242 | 56 826 |
| `wowbot/navigation` | 52 | 10 918 |
| `wowbot/skills` | 31 | 5 686 |
| `wowbot/quests` | 9 | 1 790 |
| `wowbot/runtime` | 22 | 3 416 |
| `wowbot/verification` | 11 | 1 217 |
| **Minden Python-forrás, nem csak wowbot** | **498** | **104 128** |

A `navigation/service.py` 2 589 soros. A statikusan kinyert főbb túlméretes egységek: `agent/quest_objective_planning.py::_propose_objectives` **482 sor**, `agent/skill_availability.py::available` **456**, `agent/engine.py::tick` **437**, `agent/skill_verification.py::verify` **404**, `agent/combat_planning.py::propose` **312**, `agent/planner.py::_candidates` **290**, `agent/runtime.py::step` **284**, `skills/combat.py::_local_recovery_request` **193**. Ezek a migráció szempontjából jelentősebbek, mint a fájlok puszta áthelyezése.

### Importfüggések (statikus importelőfordulások, nem call-count)

| Kapcsolat | Előfordulás |
|---|---:|
| `agent → runtime` | 71 |
| `agent → vision` | 51 |
| `skills → agent` | 50 |
| `skills → runtime` | 42 |
| `navigation → agent` | 29 |
| `agent → navigation` | 21 |
| `agent → quests` | 16 |
| `navigation → vision` | 16 |
| `agent → skills` | 8 |

**`wowbot.agent.models`-ra 196 különböző statikus modulhivatkozás mutat** a feloldott importgráf szerint. A forrásgráfban egy **32 modulból álló erősen összefüggő csoport** is van, amely quest, world-reducer, `runtime.skill_identity` és `skills.quest_item` modulokat kapcsol össze. Ezek *statikus importkapcsolatok*, dinamikus vagy conditional import is lehet köztük, tehát nem bizonyítják, hogy minden futási ág egyszerre ciklikus importhibát okoz.

**Következtetés:** `agent.models`/contracts/identity és a WorldModel–domain függőségek rendezése nélkül a `skills/combat.py` vagy `quest_graph.py` egyszerű áthelyezése dominóhatást okozhat. Első lépés az új stabil API és compatibility facade, és csak később a fájlmozgatás.

## 2. A valós végrehajtási lánc: ki birtokolja a döntést, az állapotot és az inputot?

```text
AgentRuntime.step
  ├─ enforce_runtime_safety
  ├─ sensor.poll / FAST / STATE
  ├─ update_runtime_perception  [MA MÉG MEGHÍVOTT RUNTIME LÉPÉS]
  ├─ build_runtime_observations
  └─ AutonomousAgent.tick
       ├─ WorldModel.ingest / packet reducer
       ├─ Supervisor + Freshness gates
       ├─ QuestExecutionRuntime.observe
       ├─ PlanningOrchestrator.choose / resolve
       ├─ AutonomyLoop / GoalManager
       ├─ ActiveSkillRuntime + SkillExecutor / skill FSM
       └─ CommandDispatcher.dispatch
            └─ InputExecutor.execute / execute_movement
                 └─ input scheduler + selected PID, foreground, bindings, watchdog
```

**FORRÁSBAN IGAZOLT:** `agent/runtime.py:316–362,439–460,559–560`; `agent/engine.py:63–205,276–712`; `execution/command_dispatch.py:35–88`; `agent/executor.py:39–114,181–228`. A dispatcher lokális `LOCAL_ACK`-ot állít elő, és külön kimondja, hogy ez nem világeredmény-visszaigazolás (`command_dispatch.py:49–76`). **Ezt a határt meg kell tartani.**

A migráció során egyetlen input authority maradjon. A `execution/resource_arbiter.py:13–65` már tartalmaz `LEGS`, `BODY_YAW`, `MOUSE`, `ACTION_KEYS`, `UI` lease fogalmakat. Ezt össze kell egyeztetni az `ActiveSkillRuntime` és a `CommandDispatcher` jogosultságával; új combat vagy travel alrendszer nem kaphat saját közvetlen fizikai inputot. Ez nem azt jelenti, hogy minden lease-szabály jelenleg minden útvonalban bizonyítottan aktív — ezt tesztelni kell.

**Új, magas prioritású probléma:** az `agent/engine.py:79–88` a WorldModel `__dict__`-jébe adja be a navigációs oracle-okat, és a `tdb_locations.route_cost_oracle` **globális modulváltozóját** felülírja a példány `self.navigation.walk_cost` metódusával (`agent/tdb_locations.py:191,207`). Ebből **több agentpéldánynál/PID-nél az utolsó inicializált példány költség-oracle-jának átvétele lehetséges**; ez forrás alapján kockázat, nem itt reprodukált live hiba. Váltandó explicit, példányhoz kötött `WorldGeometryQuery` / `TravelCostPort` függőséggé.

## 3. Szerveres adatút és addon: a bootstrap-vágás pontos helye

**FORRÁSBAN IGAZOLT:** `packetio/context.py:16–38` csak akkor ad contextet, ha van `game_build`, `session_id`, `character_guid`, `map_id`, `player_world_position.instance_id`, és nem loading/absent a player. `agent/runtime_packet_source.py:68–93` a `world.addon_state` és a bejövő addon payload összeolvasztása után építi ezt a packet session signature-t és `source.configure`-t. `agent/world.py:360–428` az addon alapján kezeli a WorldModel session epochját, és addig hold-olja a nem megfelelő sessionnel érkező packeteket.

**További, közvetlenül megfigyelt reducer-korlátok:** `agent/world_packet_reducer.py:677–740` egy `PACKET_CLIENT_MOVEMENT` pozíciót bizonyos ágakon addon state-tel cserél; ha a packet minta régebbi az addon `monotonic_time`-jánál, helyesen az újabb addonpozíció marad. A packetes mezők kivetítése ezért jelenleg nem addonfüggetlen, és a saját mozgás **kliensjelentett minta**, nem automatikus szerver-ACK. Ugyanitt `world_packet_reducer.py:691–713` a teljes `_packet_quest_pois` eseményadatból a jelenlegi publikált world state-ben csak az objective_index `-1` és objective_id `0` leadási blobokat vetíti ki. A későbbi `QuestTargetContext`-hez a teljes objective-POI hozzáférését külön, forrásazonosítóval kell megnyitni. E két problémára külön parity/consumer regression kell.

**Nem elég `addon_context` átnevezése.** A szükséges fejlesztés:

1. `SessionContextProvider`: kiválasztott PID és azonosított klienssession/character/build/map/instance, forrás és freshness, bizonyíték és külön `VALID`, `PENDING`, `MISMATCH`, `STALE` állapot.
2. `PacketContextBootstrap`: az addon nélküli packetkontextus megszerzése/validálása, epoch csere, map/phase váltás és stale-event elutasítás.
3. `WorldModel` session tulajdon áthelyezése a `SessionContextProvider`-re; `WorldPacketReducer` és `RuntimePacketSource` közös immutable `SessionIdentity`-t fogyaszt.
4. A **GUI/input-fókusz és modal UI** külön addon/kliens-local tény maradjon. A szerverkapcsolat és a foreground nem azonos fogalom.
5. Forráscsere **mezőnként és kapukkal**, nem az addon összes mezőjének egyszerre levágásával.

A packet event allowlist `packetio/validation.py:7–42` 22 eseménytípust sorol. Van entity lifecycle/position, quest credit/progress/POI, combat start/attack stop, scene, gossip selected, own movement; **nincs általános enemy cast start/update/stop, interrupt-result, összes aura, saját inventory baseline, teljes group state vagy talent lifecycle**. Egy WPP parser létezése nem helyettesíti a normalizált, exact-build payloadot, reducer- és consumer-tesztet.

**Addonos korlát:** a ZIP-ben nincs addon Lua és `Transport.lua`. A `FAST/STATE` teljes producer-szintű redesignját a három korábbi dokumentum mezőleltára támogatja, de **ebben a szűk forrásauditban a Lua producer nem ellenőrizhető**. Ezt az új dokumentumokban egyértelműen jelölni kell.

## 4. Travel/Navigation: mi létezik, mi hiányzik ténylegesen?

### 4.1 Már létezik, nem újraírni

- `navigation/contracts.py:13–78`: `NavigationRequest`, `ArrivalEnvelope`, `GlobalRoute`, `LocalMotionPlan`. A mai `NavigationRequest` még mode + destination dict, `avoid_combat` / `allow_combat` bool mezőkkel.
- `navigation/service.py:212–307`: typed request → Z/layer resolution → hostile danger + spawn threat → `GlobalNavigator.plan` → corridor → local plan → movement. A függvény maga is több tulajdonost egyesít.
- `navigation/global_planner.py:42–163`: MMAP route, floor-ellenőrzés, veszélyes detour, route cost, confidence. A `DangerMap` `navigation/danger.py:23–175` már hostiles köröket és sample-alapú route costot támogat, **nem üres hely a route risk modul**.
- `navigation/spawn_threats.py:69–216`: TDB/live spawn-becslés és danger bejegyzések.
- `navigation/flight_trip.py:33–108`: **létező** `TripPlan`, de csak `reason`, `take_off`, `flight`, `landing`, `attempts` — nem a végleges, mode-semleges leg-sorozat.
- `navigation/global_planner.py:208–209` már beköti a `flight_travel.plan_travel_flight`-ot, az pedig `flight_trip.plan_trip`-et hívja (`flight_travel.py:140–180`). **A korábbi »flight_trip nincs bekötve« állítás e ZIP-re hamis.** A `HORIZON_YARDS` szakaszolás és repülés utáni replanning már részben jelen van.
- `navigation/service.py:900–1293`: állapotkövetés, flight folytatás, leszállás, gyalogos finish. `navigation/service.py:1398–2589`: floor/layer, drop, zone sweep, walk-cost és egyéb, nem egyszerűen áthelyezhető beágyazott mechanizmus.

### 4.2 Pontosan mi az új cél?

```text
TravelRequest (cél + arrival + constraints; NEM ground/fly parancs)
  → TravelPlanner / TravelModePolicy candidate-generálás
      → GroundCandidate (MMAP)
      → FlightCandidate (jelenlegi flight_trip + flight_travel)
      → MixedCandidate (walk → takeoff → flight → land → walk)
  → RouteRiskEvaluator / TravelCostModel / RouteScore
  → egységes TripPlan: GroundLeg | MountLeg | TakeoffLeg | FlightLeg | LandingLeg | GroundLeg
  → TripExecutor / TransitionSystem
  → local Motion/Facing/MovementController
  → InputExecutor + ArrivalVerifier
```

**Veszély-provenance figyelmeztetés:** `navigation/danger.py:50–65` a nearby attackable listából előállított veszélyeket állandó `source="ADDON_TELEMETRY"` címkével rögzíti; a lista forrása a közös state-ben akár szerveres projekció is lehet. Ezen a határon külön `source/provenance` szükséges. A mostani default aggro-kör `10 yd`, a danger-cost `6`; az `avoid_combat` `permits` összehasonlítása `<8` (`danger.py:78–82`), ezért **egyetlen default mob köre önmagában még nem tiltja a pozíciót** — ez nem bug-bizonyíték, de fontos modell-felülvizsgálati és teszteset. A source authority, tényleges hostile faction/phase és a 3D floor kezelése nem hagyható ki az új kockázati számításból.

`TravelCostModel` **a meglévő `DangerMap` fölé épüljön**, ne annak másolata legyen. Új inputok: ellenség-GUID/pozíció/életciklus, 3D floor és LoS-bizonytalanság, becsült aggro-valószínűség, várható combat duration + HP/resource loss (a CombatModelből), halál/respawn kockázat, flight takeoff/landing/clearance/Skyriding állapot, transition failure, forrásbizonyosság. A közös `RouteScore` legyen hasonlítható: `ETA + combat_delay + risk_penalty + transition_penalty`, és őrizze meg komponenseit, ne csak egyetlen floatot. **A számok kezdetben heurisztikák**, majd `CombatRecorder`/sikertörténet kalibrálhatja; ne tüntessük ténymérésnek az expected aggro értéket.

### 4.3 A NavigationService célzott szétbontása

| Jelenlegi metódus / sáv | Új felelősség | Megjegyzés |
|---|---|---|
| `service.py:212–307 start_request` | `TravelService` → `TripPlanner` + `TripExecutor` | Külső API adapterrel kezdődjön; ugyanaz a request/correlation ID |
| `service.py:267–286` + `global_planner.py` | `GroundRouteProvider` / közös `RouteRiskEvaluator` | `DangerMap` marad megtartva |
| `service.py:900–1092 observe` | `TripExecutor.observe` | stage transition/eventre bontani, ne egyszerre átmozgatni |
| `service.py:1094–1293 flight/departure/ground` | `TravelTransitionSystem` / `FlightLegExecutor` / `GroundLegExecutor` | minden transition: precondition→action→verify→timeout→recover |
| `service.py:1295–1343` | `NavigationStateProjection` | csak read-only navmesh surface |
| `service.py:1412–1807` | `LayerResolver` / `DestinationZResolver` | a low-confidence/floor esetek kötelező regression |
| `service.py:1549–1620;1937–2135` | `HazardAwareRouteValidator` | drop/fall safe passage ne vesszen el |
| `service.py:2179–2365` | `SearchCoverage` / `ObjectApproachSafety` | a questnek csak API, ne service belső state |
| `service.py:2366–2589` | `NavigationRecovery` / `TravelCostQueryPort` | failure memory + grounded route cost |
| `navigation/navigation_combat.py` | `CombatLocalPositioningAdapter` | combat reposition nem `TravelRequest` távoli utazás |

**Fontos:** a `navigation/service.py` jelenleg `navmesh`-hez és layer state-hez kapcsolja a többi logikát; a szétbontás után invariánsokkal ellenőrizni kell a `player layer`, `route waypoint`, `flight continuation`, `arrival` tulajdonosát. Ha egy request `REPOSITION_FOR_LOS/FACING`, ne induljon 250 yardos flight + mount-flow.

## 5. Combat: a tényleges tulajdonosok és szétválasztás

| Forrás / konkrét tény | Javasolt cél |
|---|---|
| `agent/combat_controller.py:40–155` — `TargetManager` és `AbilityRuleEngine`, state observe + choose; actionbar_fast merge | `CombatContextBuilder` / `TargetSystem` / `AbilityRuntimeStateProvider` |
| `agent/target_manager.py:58–258` — target hysteresis + lifecycle | `combat/target/system.py`, de vizuális tartalom leválasztandó |
| `agent/target_manager.py:160–225` — `visual_tracks`, `occluded`, `visible` eltérő státuszba kapcsol | packet-lifecycle / selected GUID / last-seen alapján új target-loss FSM; nem puszta fájlmozgatás |
| `skills/ability_rules.py:17–80,83–356` — ability tags, definition/state/candidate/rules/score | `combat/ability/{definitions,state,rules}.py` + új RotationPolicy adapter |
| `agent/combat_planning.py:366–677` — domain proposal, vehicle és corpse ágak | `combat/policy` vs `quest/vehicle`, `loot` és recovery szétválasztandó |
| `skills/combat.py:43–1058` — aktív harci FSM, facing, range, visual follow, recovery | `CombatSkill` thin shell + `FacingController`/`Positioning`/`CombatArbitrator`/`Recovery` |
| `skills/target.py:30–160` — fizikai target kezdeményezés, verify | `TargetAcquisitionExecutor`; a planner csak requestet ad |
| `skills/combat_runtime.py:20–...` — combat verification/approach bridge | egy active combat owner; ne legyen második input authority |
| `verification/combat.py` és `runtime/verification_engine.py` | végrehajtási szerződés + domain-proven verifikáció |

**Új, nem elkészült képességek:** `MultiTargetSystem/CombatEntitySet`, `ResourceSystem`, `DamageModel`, `CooldownPlanner`, `IncomingDamageEstimator`, `DefensiveSystem`, `CastTracker`, `SpellDangerClassifier`, `InterruptPlanner`, `CCFallbackPlanner`, időzített 3D hazard, `CombatArbitrator`, `CombatRecorder`. A jelenlegi packetallowlist nélkül enemy-cast és hiteles interrupt outcome **nem állítható teljesnek**. Az `AbilityRuleEngine` már tartalmaz kandidatúrát és magyarázható szabályokat: ezen kell építeni, nem párhuzamos rotációs frameworköt kezdeni.

### Combat Role: külön role-policy, közös motor

- `CharacterProfile` → class/spec/talent/spell/form/pet/build és binding.
- `CombatRolePolicy`: `TANK`, `HEALER`, `DPS_MELEE`, `DPS_RANGED`, `DPS_SUPPORT`; `ContentContext`: `SOLO`, `DUNGEON`, `RAID`, `BATTLEGROUND`, `ARENA`, `WORLD_PVP`.
- `GroupCombatContext` + `EncounterContext`: tank/healer/DPS/PvP kontextus, threat/healing triage/boss mechanics és objective prioritás. `world_query.py:260` ugyan `group_state`-et olvas, de a feltöltött packetallowlistben nincs teljes group/raid/pvp eseménycsalád; nem bizonyított kész group authority.
- A policy ne váljon második action executor-rá. Kandidátusokat gyárt a `CombatArbitrator` számára. A tank prioritása aggro/pack/mitigation, a healeré Triage/Dispel/Mana/LOS, a DPS-é target/burst/interrupt. Arena/BG esetén objective/CC/DR/incoming burst külön policy, nem egyszerű DPS score.

## 6. Questing: mi a hiba elmélete és mit támaszt alá a kód?

**FORRÁSBAN IGAZOLT:**

- `agent/quest_model.py:369–633`: saját QuestModel, classifier/semantic hints/quest graph/quest objective.
- `agent/quest_graph.py:8–122`: **létezik** objective/quest dependency + readiness graph. **Nem** létezik ezzel egyenértékű, minden végrehajtási lépést reprezentáló mechanika-DAG; a `QuestGraph.build` objective/quest éleket épít (`quest_graph.py:42–84`).
- `quests/objective_mechanics.py:1–20,115–176,179–231`: TDB/DB2 mechanika-faktum + classifier. A fejléc kifejezetten jelzi, hogy a szerver oldali C++ scriptek további hatásai nem ismertek pusztán statikus adatból.
- `agent/tdb_knowledge.py:247–276`: a mechanikaosztályozást már tényleges fogyasztó hívja; **nem** elárvult kód.
- `agent/quest_planning.py:30–549`, `agent/quest_objective_planning.py:87–787`, `agent/quest_location_planning.py`, `agent/object_interaction_flow.py`, `agent/quest_runtime.py`: célválasztás, location, object interactions és credit folyamat több szereplő között van megosztva.
- `agent/quest_runtime.py:70–202`: a primary quest kiválasztás már támogatja a több aktív quest batch esetét (nem minden esetben kizárólag egy quest). Ne írjunk vissza primitív "one active quest" logikát.

**TERVEZETT felépítés:**

```text
QuestStateTracker → QuestUnderstanding
  → ObjectiveResolver → MechanicResolver
  → QuestExecutionGraph [PRECONDITION/AND/OR/SCENE/VEHICLE/MULTISTEP]
  → QuestPlanner
  → QuestTargetContext [nav,entity,interaction,spell,credit,search_region]
  → MechanicRegistry + MechanicContract
  → Core Capability Requests [Travel, Combat, Interaction, Item, UI]
  → QuestVerifier / QuestRecovery / QuestLearning
```

`MechanicContract`: preconditions → action request → expected event/evidence → progress/credit → failure classification → bounded retry/replan. Mechanic példák: kill/drop/credit, gossip branch, use target/location, spellclick, vehicle, escort, defense, scene/area trigger, staged script. `UNKNOWN/UNSUPPORTED` explicit állapot. A `QuestExecutionGraph` több mint a már létező `QuestGraph`: az objective belső lépéseit is reprezentálja, nem írja felül az eredeti questlánc-adatot.

**Hibák mérhetősége:** minden sikertelen objective-hoz `QuestID`, `ObjectiveID`, `attempt_id`, exact target/interaction/credit GUID, forrás/bizalom, travel/interaction/credit eseménysor, `FailureReason` (pl. `PHASE_MISMATCH`, `WRONG_FLOOR`, `SPELL_HIT_NO_CREDIT`, `UNKNOWN_MECHANIC`) tartozzon. Ezzel lehet objektíven megmérni a „minden harmadik összetett quest hibás” problémát. A `QuestVerifier` ne tekintse creditnek a sikeres inputot vagy castot.

## 7. Képfeldolgozás kivezetése: nem elég a vision könyvtár törlése

**Jelen runtime-bizonyíték:** `agent/runtime.py:356–362` a fő `step()` alatt meghívja az `update_runtime_perception` függvényt, a `runtime_observation_phase` visual projectiont tartalmaz; az `agent/engine.py` importál `VisualApproachSkill`, `VisualRuntimeRunner`, `CameraController`, és `engine_runtime_projection` `movement_visual_interrupt`-ot használ. A `skills/combat.py:707–766` vizuális követési/approach kéréseket tartalmaz. A target managerben pedig CV lifecycle van (`agent/target_manager.py:160–225`).

**Sorrend:** (a) producer/szenzor nélküli **packet+addon-only runtime teszt**, (b) minden consumer átállítása hiteles adatra vagy UNKNOWN-ra, (c) importhelyettesítés és interface-tests, (d) no-vision start és fight/quest/navigation smoke, (e) teljes CV törlés csak zöld kapu után. A minimális addon pixel-transport dekódja nem egyenlő vizuális felismeréssel; az adatcsatorna maradhat.

## 8. Pontos migrációs prioritás és elfogadási kapuk

| Fázis | Feladat | Függőség és elvárt bizonyíték |
|---|---|---|
| **P0** | ZIP forrásállapot baseline, futó konfiguráció, binding/PID/input, golden trace, hiányzó teszt- és producerforrások beszerzése | 498 parse; külső addon/Ymir/tesztek NINCSENEK a ZIP-ben; ne jelöljük késznek |
| **P1** | `contracts` / `SessionIdentity` / `WorldGeometryQuery` / `TravelCostPort` + explicit DI; globális oracle kivétele | ugyanaz a selected PID/WorldModel/map, multi-instance isolation teszt |
| **P2** | Packet bootstrap addonfüggetlenné tétele, session/epoch/freshness forrás-határok | addon nélkül session felépül; hibás build/player/phase nem autoritás; stale/wrong context drop |
| **P3** | Minimal addon schema és dual-source field authority, consumer-by-consumer migráció | FAST/STATE liveness, input/UI, quest/actionbar/talent; old/new projection parity |
| **P4** | Vision consumers leválasztása, importciklusok törése | no-vision startup és replanning; cél GUID ellenőrzés; unknown ne váljon false-ra |
| **P5** | Travel façade/TripPlan/transition; ground+flight meglévő route code újrahasznosítva | rövid ground, cave, rooftop, skyriding/steady, takeoff/landing, fail-safe |
| **P6** | Route risk/ETA/combat cost és route alternatívák; karakterprofil | danger detour regresszió + csak igazolt inputból várt aggro; flight vs ground választás |
| **P7** | Combat context/arbitrator/roles + packet cast/hazard + ability model | interrupt outcome + resource/cd + tank/healer/dps/arena/battleground izolált próbák |
| **P8** | Quest mechanic contracts/graph/target context + replay diagnosztika | 20–30 reprezentatív összetett questből baseline és előtte/utána sikeresség |
| **P9** | LLM offline adviser, memory calibration, legacy package kivezetés | elfogadott regresszió és mérési bizonyíték; semmi közvetlen LLM input |

**A fázisok logikai függőségek**, nem becsült órák vagy naptári ígéretek. Minden fázis után a meglévő agent továbbra is működőképes adapterréteggel maradjon, és visszavonható commitokból álljon a migráció. Ne legyen egyetlen óriási ``git mv`` + rewrite commit.

## 9. A 12 kritikus regresszió, ami nélkül nem szabad továbblépni

1. **Saját session:** rossz PID/player/map/phase, mapváltás, loading, reconnect, stale packet, context-collision soha ne váljon authoritatívvá.
2. **Input:** alt-tab, stop/manual, binding-cache változás, backend hibák, watchdog felengedés, egyetlen command owner.
3. **WorldModel:** FAST és STATE nem frissíti tévesen egymás stale adatait, session-váltás tisztít.
4. **Target:** candidate GUID ≠ selected GUID; elfedett/missing target ne tévesen legyen dead/success; CV nélkül működjön a recovery.
5. **Ground:** 3D layer, barlang/spirál/emelkedő/kerülő, MMAP clipped endpoint, leesésveszély.
6. **Flight:** felszálló és leszállóhely valóban elérhető, tető alatt ne szálljon fel, route végén valós ground arrival.
7. **Mixed Trip:** walk→mount→takeoff→flight→land→walk, minden transition verified; hibából újratervezés, nem végtelen loop.
8. **Route risk:** 5 hostile ground vs 0 hostile flight, plusz biztonságos gyalogos kerülő; hibás/öreg threat adat ne okozzon automatikus repülést.
9. **Combat:** facing, range, cooldown/unknown cooldown, két cél közötti switch, pet/stance/class-spec, defensive preemption.
10. **Cast/hazard:** interrupt csak a konkrét castot állította le; CC immune, csúszó ground AoE, késői adat; input tap nem siker.
11. **Quest:** conversation/gossip→script→scene→credit; item→spell→credit; vehicle; escort; phased objektum; no credit bounded recovery.
12. **Multi-PID:** két agent párhuzamosan, külön session/nav oracle/resource leases; semmilyen globális TDB route oracle nem szivárog át.

## 10. Prioritásos konkrét fájl- és metódusmigráció

Az alábbi táblázat **javasolt célhely**, nem állítás arról, hogy a kód már ott van. A jelenlegi API-kat compatibility adapterrel kell megtartani. A teljes **498 soros statikus forrásleltár** külön CSV-ben szerepel, de az automatikus category minden nem kézzel ellenőrzött fájlnál csak előzetes besorolás.

| Jelenlegi állomány | Új felelősség / hely | Teendő |
|---|---|---|
| `agent/models.py` | `core/contracts/legacy_compat.py`, később célzott típusok | `number`, `canonical`, state/Mode modellek consumer audit, deprecation facade |
| `agent/world.py` + `world_*_reducer.py` | `state/world_model.py`, `state/reducers/` | session ownership + source authority + view/projection port; ne legyen óriás-dict-váltás |
| `agent/runtime.py` | `app/runtime.py`, `adapters/addon_channel.py` | no-vision step; bootstrap és telemetria szétválasztás |
| `agent/engine.py` | `app/agent_coordinator.py` | DI, `tick` felbontás, global oracle kivétele, single owner |
| `agent/planner.py` | `planning/goal_planner.py` | quest/visual/physical move konkrétumok kivétele |
| `agent/planning_orchestration.py` | `planning/orchestrator.py` | planner/proposal/active skill life-cycle megtartása |
| `agent/autonomy_loop.py` | `planning/commitment.py` | subgoal/commitment és outcome külön, verifier gate |
| `agent/runtime_packet_source.py`, `packetio/context.py` | `sources/packet_context.py`, `sources/session_provider.py` | addon-independent bootstrap, build/epoch bound |
| `packetio/validation.py`, `agent/world_packet_reducer.py` | `sources/packet/events.py`, `state/reducers/packet.py` | exact-build event family, allowed fields, TTL and schema tests |
| `agent/tdb_locations.py` | `knowledge/tdb/locations.py` | module-global oracle megszüntetése, explicit query port |
| `navigation/contracts.py` | `travel/contracts.py` | typed `TravelRequest`, `TripLeg`, `RouteScore`, `TripPlan`, local request marad |
| `navigation/service.py:start_request` | `travel/service.py` | compatibility façade + TripExecutor, thin indítás |
| `navigation/global_planner.py` | `travel/providers/ground.py`, `travel/providers/flight.py` | MMAP route és flight plan közös kandidátusinterfész |
| `navigation/mmap_navmesh.py`, `detour_native.py` | `travel/ground/mmap.py` / provider | KEEP; ne módosítsuk a detour magot első körben |
| `navigation/flight_trip.py`, `flight_travel.py`, `flight_planner.py` | `travel/flight/` | létező bekötés adaptálása új leg-based TripPlanre |
| `navigation/danger.py`, `spawn_threats.py` | `travel/risk/danger.py`, `route_risk.py` | existing danger sampling megtartás + expected-combat cost |
| `navigation/z_resolver.py` és `service.py:1412–1807` | `travel/geometry/layers.py` | z/floor/multi-level invariáns |
| `navigation/arrival.py`, `service.py:1143–1175` | `travel/verification/arrival.py` | exact final arrival vs waypoint passed |
| `agent/movement_controller.py`, `agent/flight_control.py`, `agent/skyriding_control.py` | `travel/control/` | low-level only; input dispatcher adapteren keresztül |
| `navigation/navigation_combat.py` | `combat/positioning/navigation_adapter.py` | local reposition, a hosszú TripPlanner megkerülésével |
| `agent/target_manager.py` | `combat/target/system.py` | visual track lifecycle kivezetés, GUID evidence FSM |
| `skills/target.py` | `combat/target/acquisition_skill.py` | exact selected GUID verification |
| `agent/combat_controller.py` | `combat/context.py`, `combat/abilities/state.py`, `combat/recorder.py` | observe/rule/metrics külön |
| `skills/ability_rules.py`, `combat_ability_catalog.py` | `combat/abilities/` és `combat/rotation/` | definition/state/candidates és build/version elkülönítés |
| `agent/combat_planning.py` | `combat/planning.py`, plusz `quest/vehicle/`, `loot/` | domain mix kivétele |
| `skills/combat.py`, `skills/combat_runtime.py` | `combat/runtime.py`, `combat/skills.py`, `combat/arbitrator.py` | FSM thin wrapper, interakcióra open contract |
| `verification/combat.py` | `combat/verification.py` | enemy death, interrupt outcome, valid guid |
| `agent/quest_model.py`, `quest_graph.py` | `quest/state.py`, `quest/graph.py` | existing quest dependency graph KEEP |
| `quests/objective_mechanics.py` | `quest/mechanics/resolver.py` | current TDB/DB2 classifier KEEP + evidence |
| `agent/quest_planning.py`, `quest_objective_planning.py` | `quest/planner.py`, `quest/mechanics/execution_graph.py` | 482-soros `_propose_objectives` lépcsőkre, not one big move |
| `agent/objective_locator.py`, `quest_location_planning.py` | `quest/targets.py`, `quest/locations.py` | navigation/interaction/credit/search target szétválasztás |
| `agent/object_interaction_flow.py` | `interaction/core.py`, `quest/mechanics/object_use.py` | generic interaction és credit-domain szétválasztás |
| `quests/playbooks.py`, `scene_resolver.py`, `scene_path_planning.py` | `quest/mechanics/registry.py`, `quest/scenes/` | támogatott executor / ismeretlen script külön |
| `agent/quest_runtime.py`, `autonomy_loop.py` quest szegmensei | `quest/runtime.py`, `quest/recovery.py` | committed objective, bounded retries, phase-bound |
| `verification/quest.py`, `quest_dialog.py`, `interaction.py` | `quest/verification.py`, `interaction/verification.py` | MechanicContract saját expected evidence |
| `agent/perception.py`, `runtime_perception_phase.py`, `vision/**`, `skills/visual_*` | `legacy/vision/` majd teljes removal | csak consumer-bizonyíték után kivezetni |
| `execution/command_dispatch.py`, `agent/executor.py`, `execution/resource_arbiter.py` | `execution/` | KEEP, egyetlen input authority, lease regresszió |

## 11. Különösen fontos, még fel nem oldott kérdések

- A teljes Lua addon producer és FAST/STATE payload variánsai nincsenek a `src (2).zip`-ben; szükségesek a mezőszintű végleges törlési listához.
- A packet normalizálóhoz a tényleges futó Ymir/native oldali exact-build payloadok / golden session trace kell. Enélkül nincs bizonyíték arra, hogy minden eltávolított addonmező pótolható.
- A `tests/` könyvtár hiányzik; a 306 korábban említett célzott sikeres teszt **más időpontból és kontextusból származó audit állítás**, nem ennek a ZIP-nek ebben a futásban mért regressziós eredménye.
- Külön igazolni kell a STOP/MANUAL és background foreground állapotot P0–P4 után, a multi-PID isolationt, és a role/encounter adatok tényleges hiteles forrását.
- Nem javasolt az új elnevezések miatt megszüntetni bevált `NavigationRequest`, `QuestGraph`, `AbilityRuleEngine`, `ActiveSkillRuntime` részeket. A végleges implementációs szerződés legyen stabilabb, az osztálynevek változhatnak.

## 12. Forrásintegritás és izolált modul-smoke (e körben futtatva)

- A `src (2).zip` 498 Python entryjét byte-szinten összehasonlítottam a kibontott forrásállapottal: **0 eltérés**. A ZIP SHA-256: `a224a6d781fb5529bd5c62785cb3233a0ab29725488b59f5b54eda2c1d33f9af`.
- Izolált import/smoke működött: `NavigationRequest`, `ArrivalEnvelope`, `DangerMap`, `TargetManager`, `ActiveSkillRuntime`, `packetio.context`.
- Kontrollált DangerMap minta: 20 yd vízszintes út a 10 yd-nél lévő, 5 yd sugarú veszélyen keresztül **51,2** geometria+veszély pont; ugyanekkora út 10 yd oldalkitéréssel **20,0** pont. Ezek tesztparaméterek, nem WoW-kliens mérések, és a pontszám **nem másodperc**.
- Hiányzó addoncontextre `waiting_for_addon_context` állapotot adott a modul. Nem volt integrációs WoW / Ymir / addon producer teszt.

## 13. A következő bizonyítható mérési cél

**Mielőtt a kódot megváltoztatnánk**, egy rövid, reprodukálható trace-csomag kell: (a) 10 ground/flight/transition eset; (b) 10 eltérő combat case; (c) 20–30 összetett quest (gossip→scene, use item, killcredit, vehicle, escort, phasing); (d) wrong PID/map/session/FAST/STATE/stale event; (e) két agent egyidejű izolációja. A terv akkor kész a tényleges migrációra, ha minden cél-API-hoz megvan a tulajdonos és a megfigyelt sikerkritérium. Az itt leírt új rendszerek **jelenleg tervek**, nem live-igazolt képességek.
