# WoW agent — forráskódhoz igazított migrációs terv

**Forrásaudit és célarchitektúra-illesztés — 2026. október 29.**

> Ez a dokumentum a feltöltött `src (2).zip` tényleges forrásfájai alapján készült. Nem kódmódosítás és nem live-validáció. A cél annak meghatározása, hogy a jelenlegi működő részeket hogyan érdemes a megbeszélt új architektúrába migrálni úgy, hogy a lehető legtöbb bevált kód megmaradjon.

## 1. Rövid diagnózis

A jelenlegi rendszer funkcionálisan sokkal előrébb jár annál, mint amit a régi package-határok sugallnak. A fő probléma nem a képességek hiánya, hanem az, hogy a felelősségek több réteg között szétfolytak.

A feltöltött forrásban:

- `wowbot/agent`: **242 Python-fájl, ~56 826 sor**;
- `wowbot/navigation`: **52 fájl, ~10 918 sor**;
- `wowbot/skills`: **31 fájl, ~5 686 sor**;
- `wowbot/quests`: **9 fájl, ~1 790 sor**;
- `wowbot/runtime`: **22 fájl, ~3 416 sor**;
- `wowbot/verification`: **11 fájl, ~1 217 sor**.

A legnagyobb koncentrációk közül:

- `navigation/service.py`: ~2 589 sor;
- `skills/combat.py`: ~1 058 sor;
- `agent/movement_controller.py`: ~1 151 sor;
- `agent/quest_location_planning.py`: ~1 194 sor;
- `agent/object_interaction_flow.py`: ~1 152 sor;
- `agent/planner.py`: ~863 sor;
- `agent/combat_planning.py`: ~782 sor.

A package-ek között sok a kétirányú függés. A statikus importgráfban különösen erős:

- `agent -> runtime`: 71 importkapcsolat;
- `agent -> vision`: 51;
- `skills -> agent`: 50;
- `skills -> runtime`: 42;
- `navigation -> agent`: 29;
- `agent -> navigation`: 21;
- `navigation -> vision`: 16;
- `agent -> quests`: 16.

Ez azt jelenti, hogy **nem érdemes egyszerre nagy átnevezéssel vagy package-áthelyezéssel kezdeni**. Előbb stabil szerződéseket kell bevezetni, majd fokozatosan mögéjük mozgatni az implementációt.

## 2. A javasolt végleges rétegmodell

```text
                 LIVE SOURCES
       packet                minimal addon
          \                    /
           \                  /
            Source adapters / reducers
                     |
                WorldModel
                     |
          +----------+----------+
          |                     |
     Core capabilities      Knowledge
          |              TDB / DB2 / memory
          |
   +------+------+--------------------+
   |             |                    |
 Travel       Combat             Interaction/UI
   |             |                    |
   +------+------+--------------------+
          |
       Domain logic
   quest / gathering / dungeon / raid / PvP / farming
          |
      Goal/Planner
          |
      Active skill
          |
    Input + Verification
```

A fő elv: **Navigation/Travel és Combat legyen két önálló, generikus core capability.** A Questing ne tartalmazzon saját mozgás- vagy harcmotort, csak mechanikát és célkontextust írjon le.

## 3. Mi maradjon, mi változzon?

### 3.1 KEEP — jó alap, minimális szerkezeti módosítással

| Jelenlegi fájl / terület | Javaslat | Indok |
|---|---|---|
| `runtime/active_skill.py` | KEEP | Jó közös skill-életciklus. |
| `runtime/skill_executor.py` | KEEP + vékony adapter | Jó végrehajtási boundary; a Travel/Combat service-ek ide csatlakozzanak. |
| `runtime/verification_engine.py` | KEEP | Az action != success elvet jól tartja. |
| `runtime/supervisor.py` | KEEP | Globális megszakítás/prioritás maradjon központi. |
| `execution/command_dispatch.py` | KEEP | Egyetlen fizikai input authority maradjon. |
| `navigation/contracts.py` | KEEP + bővítés | `NavigationRequest`, `ArrivalEnvelope`, `GlobalRoute`, `LocalMotionPlan` jó alap. |
| `navigation/mmap_navmesh.py` / `detour_native.py` | KEEP | Ground routing magja. |
| `world_geometry/service.py`, `terrain_maps.py`, `vmaps.py` | KEEP | Geometriai authority. |
| `navigation/progress.py`, `stuck_resolver.py`, `arrival.py` | KEEP | Jól elkülöníthető alkomponensek. |
| `skills/ability_rules.py` | KEEP + SPLIT | Már tartalmaz `AbilityDefinition`, `AbilityRuntimeState`, kandidátusrangsorolást. |
| `agent/target_manager.py` | KEEP + MOVE | Jó TargetSystem-mag. |
| `quests/objective_mechanics.py` | KEEP + EXPAND | Már most mechanika-feloldó mag. |
| `agent/quest_graph.py` | KEEP + EXPAND | Jó dependency/readiness alap a végrehajtási gráfhoz. |
| `verification/*` | KEEP | Domainenkénti verifikátorok jók; contract alapúvá teendők. |

### 3.2 SPLIT — működik, de túl sok felelősséget visz

| Jelenlegi fájl | Szétbontás |
|---|---|
| `navigation/service.py` | `TravelService`, `TripExecutor`, `GroundRouteProvider`, `FlightRouteProvider`, `TravelTransitionSystem`, `RouteRiskEvaluator`, `NavigationRecoveryCoordinator` |
| `skills/combat.py` | `CombatSkill` marad orchestration shell; target/facing/ability/rotation/recovery logika külön combat modulokba |
| `agent/combat_controller.py` | állapotaggregáció → `CombatContext`; target → `TargetSystem`; ability választás → `RotationSystem`; statisztika → `CombatRecorder` |
| `agent/planner.py` | high-level proposal orchestration marad; travel mód, vizuális fallback és domain-specifikus részlogika kikerül |
| `agent/quest_planning.py` + quest mixinek | `QuestPlanner` + `ObjectiveResolver` + `MechanicResolver` + `QuestRecovery` |
| `agent/quest_location_planning.py` | location provider + search region + Z/floor adapterekre bontás |
| `agent/object_interaction_flow.py` | generikus Interaction capability és quest-specific MechanicContract szétválasztása |

### 3.3 MOVE — jó kód, rossz package-ben

| Régi hely | Új javasolt hely |
|---|---|
| `agent/target_manager.py` | `combat/target_system.py` |
| `agent/combat_controller.py` | részei `combat/context.py`, `combat/state_machine.py`, `combat/recorder.py` |
| `agent/combat_planning.py` | `combat/policy.py` + domain proposal adapter |
| `agent/travel_mode.py` | `travel/mode_policy.py` |
| `agent/movement_controller.py` | `travel/control/movement_controller.py` |
| `agent/flight_control.py`, `agent/skyriding_control.py` | `travel/control/flight/` |
| `agent/flight_capability.py`, `mount_capability.py` | `travel/capabilities.py` |
| `agent/objective_locator.py` | `quest/target_context.py` / `quest/location_resolver.py` |
| `agent/quest_runtime.py` | `quest/runtime.py` |
| `agent/quest_graph.py` | `quest/execution_graph.py` |
| `quests/objective_mechanics.py` | `quest/mechanics/resolver.py` |
| `quests/playbooks.py` | `quest/mechanics/registry.py` vagy compatibility adapter |

### 3.4 DEPRECATE / REMOVE FROM TARGET ARCHITECTURE

A célrendszerben nincs vizuális fallback. Ezért a következők ne legyenek core runtime függőségek:

- `wowbot/vision/**`;
- `agent/visual_*`;
- `agent/vision_*`;
- `agent/map_search_planning.py` vizuális részei;
- `agent/active_perception.py` vizuális részei;
- `skills/combat_visual_follow.py`;
- `skills/visual_approach.py`, `visual_runtime.py`;
- `diagnostics/live_vision_monitor.py` csak archivált/legacy debug eszköz lehet.

Nem az első migrációs commitban kell fizikailag törölni őket. Előbb a runtime-importokat és szerződésfüggéseket kell megszüntetni, utána lehet package-szinten eltávolítani.

## 4. Combat — konkrét forrásmigráció

### 4.1 Jelenlegi helyzet

A combat jelenleg legalább négy authority-szerű helyre oszlik:

1. `agent/combat_planning.py` — proposal/domain szint;
2. `agent/combat_controller.py` — állapot + target + ability ranking;
3. `skills/combat.py` — több mint 1000 soros végrehajtó FSM, facing/range/LOS/recovery logikával;
4. `skills/ability_rules.py` — ability definíció + runtime state + candidate scoring.

Ezen felül `agent/target_manager.py`, `skills/target.py`, `verification/combat.py`, `navigation/navigation_combat.py` is részt vesz a folyamatban.

### 4.2 Célstruktúra

```text
wowbot/combat/
    contracts.py
    context.py
    state_machine.py
    arbitrator.py

    target/
        system.py
        scoring.py
        facing.py
        multi_target.py

    ability/
        definitions.py
        state.py
        catalog.py
        evaluator.py

    rotation/
        policy.py
        damage_model.py
        resource_model.py
        cooldown_planner.py

    reaction/
        cast_tracker.py
        spell_danger.py
        interrupt.py
        cc_fallback.py
        defensive.py
        incoming_damage.py

    positioning/
        policy.py
        threat.py

    roles/
        base.py
        dps.py
        tank.py
        healer.py
        group_context.py
        encounter_context.py
        pvp.py

    recorder.py
```

### 4.3 Pontos átemelési térkép

- `agent/target_manager.py` → `combat/target/system.py`. A `TargetCandidate`, `TargetScoringPolicy`, lifecycle logika megtartható.
- `skills/combat.py::_target_bearing_error` és `_exact_facing_turn` → `combat/target/facing.py`. Az inputparancs-generálás azonban maradjon executor/controller oldalon; a FacingController elsősorban desired heading + angle error eredményt adjon.
- `skills/ability_rules.py::AbilityDefinition` → `combat/ability/definitions.py`.
- `skills/ability_rules.py::AbilityRuntimeState` → `combat/ability/state.py`.
- `AbilityRuleEngine.evaluate()` → `combat/ability/evaluator.py`.
- jelenlegi `choose()` prioritás → kezdetben compatibility `RotationSystem`; később utility/scoring modell.
- `agent/combat_controller.py` health trend/multi target/range stats → `CombatContext` + `CombatRecorder`.
- `CombatController.choose_action()` ne maradjon végleges ability authority; az új `CombatArbitrator` választ a Rotation/Interrupt/Defensive/Movement jelöltek közül.
- `skills/combat.py` végül vékony FSM/executor legyen: a döntést ne maga gyártsa, hanem `CombatDecision`-t hajtson végre és verifikáljon.

### 4.4 Új CombatArbitrator szerződés

```text
CandidateAction:
    source: ROTATION | INTERRUPT | DEFENSIVE | POSITIONING | CC | MOBILITY
    deadline
    priority
    expected_utility
    target_guid
    ability_id / movement_request
    preconditions
    cancellation_key
```

A runtime minden combat tickben ugyanabba az arbitratorba adja:

- normál DPS/heal/tank action jelöltet;
- interrupt/CC reakciót;
- defensive jelöltet;
- hazard escape/positioning mozgást;
- target switch / facing igényt.

Ez oldja meg a jelenlegi problémát, hogy a facing/range recovery és a rotation egymásba van szőve a `CombatSkill`-ben.

### 4.5 CombatRoleSystem

A `CharacterProfile` alapján oldódjon fel:

```text
RoleProfile = role + content + spec/build
```

Role-ok:

- `TANK`
- `HEALER`
- `DPS_MELEE`
- `DPS_RANGED`
- `DPS_SUPPORT`

Content:

- `SOLO`
- `DUNGEON`
- `RAID`
- `BATTLEGROUND`
- `ARENA`
- `WORLD_PVP`

A role **nem külön combat engine**. Scoring/policy rétegként módosítja a TargetSystem, PositioningSystem, CooldownSystem, DefensiveSystem, ThreatSystem és RotationSystem viselkedését.

## 5. Travel/Navigation — konkrét forrásmigráció

### 5.1 Jelenlegi erősség

A jelenlegi kódban már van:

- `NavigationRequest` és `ArrivalEnvelope`;
- MMAP/Detour ground routing;
- `GlobalNavigator`;
- `flight_trip.py::TripPlan`;
- `flight_travel.py` adapter;
- walk→flight→walk tervezési alap;
- `DangerMap`;
- `SpawnThreats`;
- progress/stuck/recovery;
- flight és ground kontrollerek.

Tehát az új Travel architektúrához **nem új navigation engine kell**, hanem a meglévő elemek új komponálása.

### 5.2 Jelenlegi fő probléma

A `NavigationService` 2500+ sorban egyszerre:

- fogad requestet;
- old Z/floor-t;
- figyeli a hostiles/spawn threatet;
- választ és generál global route-ot;
- kezeli flight departure-t;
- kezeli ground approachot;
- épít corridort;
- local plant készít;
- movement controllert hajt;
- arrival-t ellenőriz;
- stuck/recovery-t kezel;
- layer transitiont kezel.

A `NavigationRequest.destination` dictben ma több flight-specifikus kulcs (`flight`, `flight_path`, `flight_departure`, `flight_relaunch`, `flight_style`) is átfolyik. Ez annak a jele, hogy a magas szintű request és a konkrét végrehajtási mód összekeveredett.

### 5.3 Célstruktúra

```text
wowbot/travel/
    contracts.py            # TravelRequest, ArrivalRequirement, TripPlan, TripLeg
    service.py              # public facade
    planner.py              # candidate trip generation + selection
    mode_policy.py
    cost_model.py
    risk.py
    transitions.py
    executor.py

    ground/
        route_provider.py   # MMAP/Detour
        corridor.py

    flight/
        route_provider.py   # flight_trip / flight_planner / flight_route
        landing.py
        takeoff.py

    local/
        planner.py
        movement_controller.py
        facing.py

    recovery/
        progress.py
        stuck.py
        replan.py
```

### 5.4 TravelRequest

A domain ne mondja meg, hogy ground vagy flight.

```text
TravelRequest:
    request_id
    destination
    arrival_requirement
    target_entity_id?
    urgency
    combat_policy
    allowed_modes?
    constraints
```

A `NavigationRequest.mode` (`MOVE_TO_LOCATION`, `APPROACH_ENTITY`, stb.) egy része megmaradhat `purpose`/arrival intentként, de a közlekedési mód ne legyen a destination dict rejtett flagje.

### 5.5 TripPlan

```text
TripPlan:
    legs = [
       GroundLeg,
       MountTransition,
       TakeoffTransition,
       FlightLeg,
       LandingTransition,
       GroundLeg,
    ]
```

A meglévő `flight_trip.py::TripPlan` legyen migrációs kiindulópont, de általánosítsuk minden travel módra.

### 5.6 RouteRiskEvaluator / TravelCostModel

A jelenlegi `DangerMap` és `SpawnThreats` már jó alap. Ezeket nem eldobni kell, hanem egy közös költségmodellbe emelni.

Ground feature-ök:

- route length / ETA;
- live hostile exposure;
- becsült aggro probability;
- expected combat count;
- expected combat delay;
- expected HP/resource loss;
- death risk;
- water/slope/terrain;
- korábbi stuck/fall/recovery history.

Flight feature-ök:

- mount + takeoff overhead;
- open-sky/takeoff feasibility;
- clearance;
- landing feasibility;
- flight style/capability/resource;
- landing utáni ground leg;
- failure history.

Transition feature-ök:

- mount/dismount idő;
- combat restriction;
- indoor/outdoor állapot;
- verification failure probability.

Egységes score:

```text
RouteScore:
    eta
    distance
    combat_cost
    danger_cost
    transition_cost
    failure_risk
    confidence
    total_utility
```

A `SpawnThreats.near_segment()` / `DangerMap.route_cost()` irányából lehet a ground corridorra hostile-exposure költséget visszainjektálni. A karakter combat profilja adhat várható TTK/survival költséget, így ugyanaz az út Warriorral és cloth casterrel eltérően pontozható.

## 6. Questing — konkrét forrásmigráció

### 6.1 Jelenlegi helyzet

A jó elemek már megvannak, csak túl sok helyen:

- `agent/quest_model.py`
- `agent/quest_runtime.py`
- `agent/quest_graph.py`
- `agent/quest_planning.py`
- `agent/quest_objective_planning.py`
- `agent/quest_location_planning.py`
- `agent/objective_locator.py`
- `quests/objective_mechanics.py`
- `quests/playbooks.py`
- külön object/talk/item/scene/vehicle planner fájlok.

A `quests/objective_mechanics.py` már most nagyon közel áll az új `MechanicResolver` fogalmához: `KILL`, `COLLECT_DROP`, `OBJECT_USE`, `SPELLCLICK`, `VEHICLE_ABILITY`, `USE_ITEM`, `AREA_TRIGGER`, stb. mechanikákat osztályoz. Ezt kell központi authority-vá tenni.

### 6.2 Célstruktúra

```text
wowbot/quest/
    models.py
    state_tracker.py
    understanding.py
    execution_graph.py
    planner.py
    runtime.py
    recovery.py
    learning.py

    objective/
        resolver.py
        target_context.py
        location_resolver.py

    mechanics/
        contracts.py
        registry.py
        resolver.py
        kill.py
        collect.py
        interact.py
        talk.py
        use_item.py
        scene.py
        vehicle.py
        escort.py
        area_trigger.py
        scripted.py
```

### 6.3 QuestTargetContext

Az egyik legfontosabb új contract:

```text
QuestTargetContext:
    navigation_target
    entity_target
    interaction_target
    spell_target
    credit_target
    search_region
    evidence
    confidence
```

Ez leváltja azt az implicit feltételezést, hogy egy objective-nak „egy targetje” van. A jelenlegi `ObjectiveLocator` csak location hypothesis-t ad; ezt érdemes `LocationResolver`-ré szűkíteni, és fölé tenni a többféle targetet összefogó contextet.

### 6.4 MechanicContract

Minden mechanika azonos szerződés szerint fusson:

```text
MechanicContract:
    mechanic_type
    prerequisites
    required_capabilities
    prepare(context)
    next_action(context)
    expected_evidence
    verify(before, after)
    failure_classification
    recovery_policy
```

Példák: `KillContract`, `UseItemOnTargetContract`, `GossipContract`, `VehicleContract`, `SceneContract`.

A QuestPlanner csak a contractot és a contextet válassza ki. A Travel/Combat/Interaction core capability-k végzik a tényleges mozgást/harcot/interakciót.

### 6.5 QuestExecutionGraph

A jelenlegi `QuestGraph` readiness/dependency kódja legyen az alap, de az új gráf node-ja ne csak objective legyen. Lehessen például:

```text
Objective
  -> TRAVEL
  -> ACQUIRE_ENTITY
  -> INTERACT
  -> WAIT_SCENE
  -> VERIFY_CREDIT
```

A gráf támogatása:

- prerequisite;
- parallel objective;
- conditional branch;
- scene/vehicle transition;
- WAIT_FOR_STATE node;
- explicit verification node;
- recovery/replan edge.

### 6.6 Failure taxonomy

A jelenlegi általános `FailureReason` mellé quest-domain részletezés kell:

- `TARGET_NOT_FOUND`
- `TARGET_IDENTITY_AMBIGUOUS`
- `LOCATION_UNKNOWN`
- `ROUTE_UNREACHABLE`
- `WRONG_FLOOR`
- `MISSING_ITEM`
- `MISSING_BINDING`
- `MECHANIC_UNKNOWN`
- `MECHANIC_UNSUPPORTED`
- `INTERACTION_FAILED`
- `SPELL_NO_EFFECT`
- `NO_OBJECTIVE_PROGRESS`
- `SCENE_NOT_RESOLVED`
- `WAITING_SERVER_STATE`
- `STALE_DATA`
- `PHASE_MISMATCH`

A cél az, hogy a „quest bugol” helyett az agent és a log pontosan megmondja, melyik contract melyik szakasza bukott el.

## 7. Minimal addon — konkrét migráció

### 7.1 A jelenlegi blokkoló függés

A packet pipeline ma nem addonfüggetlen. `packetio/context.py::addon_context_status()` több addon-state mezőt megkövetel:

- `game_build`;
- `session_id`;
- `character_guid`;
- `map_id`;
- `player_world_position.instance_id`;
- `loading`;
- `player_present`.

`RuntimePacketSource` ezt az `addon_context`-ot használja a packet endpoint konfigurációjához és a kontextus-összevetéshez. A `world_packet_reducer.py` szintén több ponton addon_context-tal ellenőrzi a scope-ot.

Ezért **az addont nem szabad előbb karcsúsítani, mint a packet bootstrapot leválasztani róla**.

### 7.2 Cél authority

```text
PACKET          = world/server truth
ADDON           = client/UI truth
DB2/TDB         = reference knowledge
MAP/VMAP/MMAP   = geometry
MEMORY          = historical experience
```

### 7.3 Új SessionContextProvider

Javasolt új contract:

```text
SessionContext:
    selected_pid
    process_build
    session_epoch
    character_guid
    world_map_id
    instance_id
    phase?
    source_evidence
    freshness
```

Forrásai:

1. process/capture/build identity;
2. authenticated packet handshake/own-player observation;
3. minimális addon csak ott, ahol tényleg kliens/UI context kell.

Az `addon_context()` helyett a packet pipeline ezt a provider contractot kapja.

### 7.4 Mit tartson meg a minimális addon?

Elsősorban:

- transport/schema/session sequence saját meta;
- `loading`, `input_blocked`, UI error;
- látható quest/gossip/reward/talent UI állapot és szükséges koordináták;
- active actionbar/page/override és tényleges kliensoldali readiness, amíg packetből nem bizonyított;
- bindinghez/UI-hoz szükséges kliens-only állapot;
- soft-interact recipient / mouseover csak ha a végrehajtási contract ténylegesen használja.

Költöztetendő packet authority-ra, amikor a baseline igazolt:

- own GUID/world identity;
- position/orientation;
- health/power;
- world entities/GUID/entry/position;
- enemy casts/auras/area trigger lifecycle;
- quest credit/progress és más szerver által meghatározott állapot.

## 8. A legfontosabb package-boundary szabály

A jelenlegi kódban a `navigation` és `skills` sokszor `wowbot.agent.*` modelleket/helper-eket importál. Ez hosszú távon fenntartja a körkörös rétegezést.

Cél:

```text
runtime/contracts + world/contracts + domain contracts
        ^
        |
combat / travel / quest / skills
        ^
        |
agent orchestration
```

Vagyis **az `agent` legyen composition root/orchestrator, ne utility- és domain-modellraktár**.

Elsőként kimozgatandó közös típusok:

- `Command`, általános state helper-ek → runtime/execution contracts;
- world entity identity/position helper-ek → world package;
- movement/arrival contracts → travel package;
- ability contracts → combat package;
- quest objective/mechanic contracts → quest package.

## 9. Javasolt migrációs sorrend

### M0 — Contract freeze és tesztbaseline

- jelenlegi tesztkör rögzítése;
- fontos live trace-ek/golden sessionök archiválása;
- új package-ek létrehozása még viselkedésváltozás nélkül;
- import dependency check bevezetése.

### M1 — Addonfüggetlen session/packet bootstrap

- `SessionContextProvider`;
- `RuntimePacketSource` átkötése;
- `world_packet_reducer` scope check migráció;
- csak ezután addon mezők kivezetése.

### M2 — Combat contracts és Target/Ability extraction

- `TargetManager` áthelyezése;
- AbilityDefinition/RuntimeState extraction;
- Facing tiszta geometriai komponens;
- compatibility adapterek, hogy a régi `CombatSkill` tovább működjön.

### M3 — CombatArbitrator + role layer

- Rotation/Interrupt/Defensive/Positioning candidate contract;
- CombatArbitrator;
- RolePolicy (DPS/Tank/Healer) és GroupCombatContext;
- először SOLO/DPS compatibility, majd dungeon roles.

### M4 — Travel contracts és TripPlan generalizálás

- `TravelRequest` a jelenlegi NavigationRequest fölé/utódjaként;
- `TripPlan` általánosítása;
- Ground/Flight provider interface;
- transition leg-ek;
- régi NavigationService façade mögött az új planner fut.

### M5 — RouteRiskEvaluator

- `DangerMap` + `SpawnThreats` összefésülése risk feature-ökké;
- combat profile alapú expected combat cost;
- ground/flight/mixed candidate összehasonlítás;
- MMAP route danger cost.

### M6 — Quest MechanicContract és TargetContext

- `objective_mechanics.classify()` → MechanicResolver;
- QuestTargetContext;
- MechanicRegistry;
- elsőként a már működő KILL/TALK/OBJECT_USE/COLLECT_DROP út migrálása;
- minden régi quest special-case csak adapter legyen az új contract mögött.

### M7 — QuestExecutionGraph

- objective + mechanika lépésekből futó gráf;
- WAIT/SCENE/VEHICLE/ITEM/ESCORT node-ok;
- részletes failure taxonomy;
- learning recipe csak verified success után.

### M8 — Legacy/visual cleanup és package boundary enforcement

- visual runtime importok eltávolítása;
- `agent` domain helper-ek kimozgatása;
- deprecated compatibility adapterek törlése;
- ciklikus importok megszüntetése;
- source authority dokumentum és acceptance ledger frissítése.

## 10. Mit NEM csinálnék

1. Nem írnám újra az egész agentet.
2. Nem törölném elsőként a régi vizuális fájlokat; előbb leválasztanám a fogyasztókat.
3. Nem bontanám szét egyszerre a `NavigationService`-t úgy, hogy közben megszűnik a működő MMAP/flight út.
4. Nem csinálnék külön TankCombatEngine/HealerCombatEngine/DpsCombatEngine osztályokat; egy engine + role policy legyen.
5. Nem kérdeznék LLM-et minden GCD-n. Az LLM offline policy/rotation profil optimalizálásra jó, a realtime döntő determinisztikus.
6. Nem questenként írnék új special-case ágat; minden új questhiba először azt mutassa meg, melyik MechanicContract hiányzik vagy hibás.

## 11. Az első konkrét refaktorcsomag, amit megcsinálnék

Ha implementációra kerül a sor, az első valódi PR/commit-sorozatot így választanám:

1. új `wowbot/combat/` package, benne a meglévő `TargetManager` és Ability contractok költöztetése compatibility re-exporttal;
2. új `SessionContext` contract és packet bootstrap leválasztás az addonról;
3. új `wowbot/travel/contracts.py` (`TravelRequest`, `TripPlan`, `TripLeg`, `RouteScore`) úgy, hogy a régi NavigationService még adapterként működik;
4. új `wowbot/quest/mechanics/` package, amely először csak a jelenlegi `objective_mechanics` és `playbooks` kódot csomagolja egységes API mögé;
5. dependency-gate teszt, amely megtiltja, hogy `combat/`, `travel/`, `quest/` új kódja közvetlenül `wowbot.agent.*`-ból importáljon, kivéve átmeneti explicit allowlistet.

Ez a sorrend a struktúrát kezdi tisztítani úgy, hogy a jelenlegi működő útvonalak minél tovább érintetlenek maradnak.
