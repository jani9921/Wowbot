# REV4 P8 — a 10-28-as élő escort-teszt két hibája

2026-10-31, Claude. A felhasználó 10-28-i élő tesztje (65793 „Escort the
Wagon”) két hibát hozott. A reformátadás miatt mindkettő félbemaradt. Az
egyik javítva (offline), a másik adat hiányában nyitott.

## 1. „Az elején elrepült a POI zóna közepére” — JAVÍTVA, offline

Napló (15:40:05.90–15:40:06.92):

1. A szekér melletti várakozást (WAIT_EVENT, 65793:2) egy támadó megszakította:
   `SKILL_FAILURE reason=INTERRUPTED`.
2. `QUEST_FAILURE_RECORDED {"skill": "WAIT_EVENT", "reason": "interrupted"}`,
   15 mp-es tiltás.
3. A kísérő MOVE (`ESCORT_FOLLOW`) lefutott, és odaért a szekérhez.
4. Az escort-policy ezután a várakozást javasolta volna, de az tiltva volt.
5. Így a prio-56-os `LOCATE_QUEST_OBJECTIVE_REGION` MOVE nyert, és az agent a
   quest-terület közepére repült.

A kezdeti feltételezés (CANCELLED → FAILURE leképezés) nem volt helyes: a
`_project` már jól képezi a CANCELLED-et. Az ok a hibamemória.

A javítás: `QuestFailureMemory.PREEMPTIONS = {"interrupted", "cancelled"}`.
Egy megszakított vagy visszavont kísérlet semmit nem mond az objektíva
megközelítéséről, ezért nem kerül tiltásba. A valódi hibák (timeout,
range, path stb.) tiltása változatlan. A loop-detektor független, és
megmarad.

Teszt: `tests/test_preempted_quest_attempt_20261031.py` (2).

## 2. „A leadó NPC felette volt, alatta forgott” — NYITOTT, élő adat kell

A 10-28-as nyomból, ami az akkori elemzésben megmaradt:

- a leadási MOVE célja a TDB quest-POI: `x 1792, y 31, z 313`,
  `z_source=TDB_WORLD`, `knowledge_priority=PRIMARY_STATIC`;
- a route a navmeshen a z≈128-as szintre vetítette a végpontot
  (`layer_z 128.4`);
- beltér volt (`addon_is_indoors_true`);
- minden MOVE azonnal `reach_arrival_verified` lett, és ez körbeforgáshoz
  vezetett.

Mai kódállapot:

- `GlobalNavigator` már elutasítja azt a földi utat, amelyik 12 yardnál
  többel a cél ismert magassága alatt vagy felett végződik (East Arbalest,
  10-27). A vétóhoz azonban **megbízható** cél-Z kell: nem becsült, vagy
  PRIMARY_STATIC legalább 0,7-es `z_confidence`-szel. A quest-POI magassága
  becslés, így ez nem fogott.
- Az érkezés (`_level_distance`, `_original_goal_within_arrival`) csak
  megfigyelt saját magassággal vétózik. Beltérben ez hiányzott, ezért a
  lapos XY-érkezés átment.
- A szerveres leadás (`ServerNpcInteractionPolicy`: ender-entry, ≤80 yd)
  létezik. Hogy miért nem az nyert, a kirotált napló nélkül nem
  bizonyítható. Valószínű ok: a 185 yd függőleges eltérés miatt az ender a
  szerver látótávolságán kívül volt, így nem volt packet-entity.

Kipróbáltam, aztán visszavontam egy érkezés-oldali vétót: route-végpont
navmesh-magassága kontra cél-Z. Bizonyított, hogy ugyanazon a becsült Z-n
múlik, mint a planner vétója, így a 10-28-as esetben ez sem fogott volna. Egy
becsült Z-re épülő vétó pedig minden olyan POI-t blokkolna, ahol a POI
magassága pontatlan.

A következő élő tesztnél ezt kell rögzíteni (a telemetria-rotáció előtt):

- a leadó ender NPC (entry) szerepelt-e `packet_entities`-ben, és milyen
  távolságra;
- a saját `player_world_position` `z_observed` / `observed_z` értéke beltérben;
- a POI `z_estimated` / `z_confidence` értéke.

Ezekből dönthető el, hogy repülési fel-keresés kell-e (becsült POI-Z,
lent végződő földi út, nincs látható ender), vagy a szerveres leadás
prioritása hibás.
