# REV4 P5/P7 — NavigationService és CombatSkill felelősségbontás

2026-10-31, Claude. Az átadás 6. pontja és a
[SRC_MELY_AUDIT](input/SRC_MELY_AUDIT_20261029_HU.md) 4.3/4.4 bontási
térképe szerint. Tizenegy szelet kész (1, 1b, 2–10), mindegyik offline
tesztelt. A térkép
minden sora le van fedve; ami szándékosan maradt, azt a dokumentum vége
indokolja.

Az elv:

- valódi komponens jön létre, saját állapottal és határral, nem üres
  manager-réteg vagy mixin;
- a viselkedés változatlan;
- a régi belépési pontok vékony delegálásként megmaradnak, mert hívók és
  tesztek használják őket;
- a kód szó szerint költözik, csak a tulajdonos változik.

## 1. `navigation/hazard_route.py` — `HazardAwareRouteValidator`

A NavigationService szakadék- és folyosóközép-geometriája (257 sor) költözött
ide.

- `DROP_*` / `CENTER_*` állandók, `_drop_side`, `_walkable_near`,
  `_densified`, `_edge_distance`, `segment_walkable`, `center`
  (volt `_away_from_drops`), `_walkable_offsets`, `_simplified`,
  `without_drop_spikes`.
- A tulajdonos aktuális ZResolverét és navmesh-ét providerrel olvassa, mert a
  navigációs reset a ZResolvert lecseréli.
- Saját állapota az elakadt eltolt pontok listája (`offset_stuck`). Ez a
  resetet is túléli, ahogy korábban a service-attribútum is.
- Nem birtokol route-ot, requestet vagy inputot. A route- és
  waypoint-tulajdonos (`_note_offset_stuck`, az aktív route olvasása) a
  service-ben maradt.

A `service.py` 2912 sorról 2672-re csökkent (az 1b szelettel együtt ~2640).

## 1b. `navigation/fall_hazards.py` — `FallHazardMemory`

A megfigyelt szakadékesések route-veszélyként való megjegyzése költözött ide.

- A felső route magasságán jegyzi meg az esést, szint és instance szerinti
  hatókörrel, 10 percig.
- Egy későbbi, ugyanazon a szinten átmenő földi utat elutasít.
- Ha a játékos még a „peremen” áll a saját szintjén, az nem esés volt.
- Ugyanazt a peremet csak egyszer jegyzi meg.

A service csak azt dönti el, melyik magasságon könyveli az esést
(route-hint, megbízható réteg, aktív horgony). A service `_fall_hazards`
nézetként ugyanazt a listát adja; a navigációs reset ugyanúgy törli, mint
korábban.

## 2. `skills/combat_recovery.py` — `CombatLocalRecovery`

A CombatSkill 194 soros helyi recovery-döntése költözött ide. Három okra
(OUT_OF_RANGE, FACING_WRONG_WAY, LINE_OF_SIGHT) egyetlen biztonságos helyi
korrekciót vagy típusos hibát választ:

- világpozíciós megközelítési kérés;
- LOS-áthelyezés;
- pontos facing-fordulás vagy facing-sweep;
- kis, képernyőhöz horgonyzott helyi próba;
- keret vége.

A mozgást a NavigationService végzi; a komponens nem birtokol inputot és
célpontot.

A facing-parancsokat (pontos fordulás, sweep-lépés), a világ-megközelítési
kérést és a kereteket a FacingController-bontásig a tulajdonos skill adja.
A keretek így skillenként felülírhatók maradnak, ahogy a tesztek használják.

A `combat.py` 1070 sorról 883-ra csökkent.

## 3. `navigation/layer_resolver.py` — `DestinationLayerResolver`

A szintkérdések költöztek ide (200 sor):

- az aktív route magassága ott, ahol a játékos áll (a saját szint
  követésének döntetlen-feloldója);
- egy új route kezdőállapota a követett saját szinten (becslés, soha nem
  „observed”);
- egy magasság nélküli keresési cella a játékos szintjén van-e;
- egy magasság nélküli cél járható, elérhető szintje;
- a megfigyelt saját szint figyelése.

A figyelés (`observed_layer`) állapota a megfigyelt saját Z és a „más
szinten óta” időpont. Az eredménye `CONTRADICTED`, `CONFIRMED` vagy `None`.

- A route bukását (`route_on_observed_other_layer`) és a
  `_route_own_z_unobserved` törlését továbbra is a service végzi.
- A rétegpróba (`_ambiguous_layer_probe`) a service-ben maradt, mert
  route-ot tervez.

A ZResolvert providerrel olvassa, mert a reset lecseréli.

## 4. `navigation/navigation_combat.py` — `CombatLocalPositioningAdapter`

A korábbi `NavigationCombatMixin` mixin helyett ez komponens, explicit
portokkal:

- a service FaceControllere, LOS-tervezője és DangerMapje;
- két entity-goal port a service request-tulajdonosára.

Ez nem indít második kontrollert vagy input-leaset. Saját állapota csak a
legutóbbi LOS-recovery direktíva; a service `_latest_los_recovery` nézetként
adja, és a reset ugyanúgy törli. A `NavigationService` már nem örököl a
mixinből.

## 5. `skills/combat_facing.py` — `CombatFacingController`

A pontos facing-fordulás és a korlátos facing-sweep parancsai költöztek ide.

- A kiválasztott GUID ellenőrzése (`CombatSkill._target_bearing_error`) a
  skill határán marad; ezt egy meglévő határteszt rögzíti.
- A kísérlet állapota a skill contextben marad.
- A keretek és a bindingek a skillen maradnak, így skillenként
  felülírhatók.

## 6. `skills/combat_arbitrator.py` — `CombatArbitrator`

A tickenkénti akcióválasztás költözött ide, változatlan sorrendben:

1. jármű-override;
2. cast-várás, pontos előfordulás;
3. „use X on target” nyitó;
4. vizuális követés (csak legacy), GCD, ugyanabból a fast mintából nincs két
   döntés;
5. a legjobb használható képesség; ha nincs, akkor mobility-settle,
   auto-attack fallback, majd range-recovery vagy típusos OUT_OF_RANGE.

Minden kollaborátort a skillen keresztül hív, így a tesztek ott patchelhetik.

Ezzel a `CombatSkill` vékony FSM-shell lett: begin, verify, FSM-állapot és a
kísérlet-context.

## 7. `navigation/travel_cost.py` — `TravelCostQueryPort`

Tervezési lekérdezések, amelyek route-ot, billentyűt és requestet nem
érintenek:

- `object_pull_step_safe`;
- `recovery_step_drops`;
- `player_layer_z`;
- `walk_cost`.

Saját állapota csak a walk-cost cache. Az engine ugyanazokat a
service-metódusokat köti be travel_cost, player_layer és step guard
szerepben.

## 8. `navigation/zone_sweep.py` — `ZoneSweepGeometry`

A zónabejárás geometriája költözött ide:

- `lower_layer_point`, saját cache-sel, amit a reset töröl;
- `route_hops` (a perem–alj route rövid hopokra mintázva);
- `sweep_hops` (a TDB-spawnok beszúrása).

A bejárási napló (visited, irány, done) **szándékosan a service-ben
maradt**, mert a planner, az érkezés-ellenőrzés és a hop-passed ellenőrzés
közösen használja. Hat meglévő teszt a service-en rögzíti a napló formáját.

## 9. `navigation/travel_transitions.py` — `TravelTransitionPolicy`

A repülés-indulás és a földi szakasz átmeneti döntései (csak döntések):

- `departure_active`, `departure_flight_ready`, `flight_destination`;
- `after_departure_walk`: a felszállási ponton repül, repülhetetlen zónában
  földön folytatja az eredeti célt, vagy vár;
- `ground_request`;
- `departure_walk` (a felszállási séta orákuluma, cache-sel, amit a cancel és
  a reset töröl).

A requestet, a lábak indítását az egyetlen movement-kontrolleren és a
határidőket továbbra is a service birtokolja.

## 10. `navigation/position_acquisition.py` — `ServerPositionWait`

A route előtti első saját szervermagasság várása kapott saját komponenst.

- Állapota a várakozás: kezdési idő és session/világ hatókör.
- Ehhez tartozik a diagnosztikai trace.
- Döntései: `WAITING`, `READY`, időtúllépés, kontextusváltás, megszakítás.
- A service `_position_wait` / `_position_trace` nézetként adja tovább;
  ezeket a meglévő tesztek olvassák.
- A request, a keret, a mérő fordulás és a folytatott tervezés a service-é
  maradt.

## Méret

| Fájl | Előtte | Utána |
|---|---|---|
| `navigation/service.py` | 2912 | 2248 |
| `skills/combat.py` | 1070 | 622 |

## Tesztek

`tests/test_service_combat_split_20261031.py` (12):

- a költözött függvények és állandók már nincsenek a tulajdonosban;
- a régi belépési pontok egysoros delegálások;
- a komponensek az aktuális resolvert és navmesh-et olvassák;
- a reset- és cancel-szemantika változatlan;
- a megfigyelt-szint figyelés vár, megerősít, ellentmond, és próba esetén
  azonnal ellentmond;
- a combat-pozicionálás adapter, nem mixin;
- az új komponensek nem importálják a tulajdonosukat és a vision-t.

A viselkedést a meglévő tesztek fedik: gödör, spirál, pit-run,
walking-route, cave-layer, observed-layer, forge-wait, zone sweep, repülés
és felszállás, LOS/range/facing recovery, auto-attack és rotáció.

## Ami szándékosan maradt

- A `_start_request` (125 sor) és az `_observe_control` (204 sor) a service
  request-, route- és waypoint-tulajdonának magja.
  - A szemantikus trip-réteg már létezik: `navigation/travel.py`
    `TripExecutor` és `TransitionSystem`.
  - Az átmeneti döntések kikerültek (9. pont).
  - A maradék a tulajdonos állapotát írja: aktív request, route, waypoint,
    hibaok, pozícióvárás. Ezt egy másik osztályba költöztetni üres
    manager-réteg volna, amit az elv kizár.
  - A szerverpozíció-várás saját állapotgépe kikerült (10. pont).
- A `CombatSkill._verify` (172 sor) a skill FSM-je; ez marad a vékony shell
  része.

Élő igazolás: nincs. Ez szerkezeti átrendezés változatlan viselkedéssel.
