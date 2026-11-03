# REV4 P5 — friss saját minta lassú route-query után; projektált végpont

2026-10-30, Claude, a Codex-átadás (`CLAUDE_ATADAS_20261030.md` §5) WIP-jének
lezárása.

## A probléma

A cold mesh / lokális query az agent lock alatt fut. A WIP előtt a lassú
query után a mozgás ugyanabból a, közben elöregedett frame-ből kapott
parancsot.

## A megoldás

Ugyanaz a `NavigationService` és `ReachMovementController` marad az egyetlen
owner, nincs második navigátor. A `start_request` és a `local_plan` mért
időtartama `_planning_clock` (alapértelmezés `time.perf_counter`), tesztben
injektálható.

0.6 s-nál hosszabb tervezés után (a küszöb kizáró) `RouteFeedback` jön létre.
Ez immutable előfeltétel:

- legkorábbi minta = `now + elapsed`;
- eredeti saját pozíció és megfigyelt Z;
- scope: PID/map/instance, halál, szellem, jármű.

A várakozás alatt:

- nincs mozgási command, és a `local_plan` sem fut;
- az `observe` `awaiting_post_plan_feedback` állapotot ad;
- a FAST sáv leengedi a lease-t, és `movement_route_plan_pending` okkal
  medium handoffot kér; nehéz queryt nem futtat.

A medium (`resume_owned_route`) feloldja a várakozást:

| Eredmény | Feltétel | Következmény |
|---|---|---|
| READY | friss minta, nincs elmozdulás | a meglévő route folytatódik |
| REPLAN | >2 yd elmozdulás vagy megváltozott / újonnan ismert saját Z | ugyanaz a request, ugyanaz a Trip, eredeti kezdőidővel |
| `post_plan_feedback_timeout` | 2 s friss minta nélkül | STALE_OBSERVATION |
| `post_plan_feedback_context_changed` | megváltozott scope | WRONG_MAP_CONTEXT |
| `post_plan_feedback_interrupted` | loading / input-block / nincs jelen a játékos | megszakítás |

Az eredeti request/attempt deadline nem hosszabbodik meg. Cancel/reset
eldobja a várakozást; késői minta nem éleszti újra.

## Claude-javítások a WIP-en (tudatos döntés, nem rollback)

1. **Újracímkézett minta.** A WORLD_YARDS pozíciónak saját `sample_time`-ot
   kell hordoznia. Korábban az állapot `monotonic_time`-ja is elég volt, így
   egy régi pozíció egy újabb merged state-ben frissnek tűnhetett.
   Normalizált térképnél a régi fallback megmaradt.
2. **Projektált végpont.** Az `anchor_tolerance = desired − |anchor − cél|`.
   Ezen belül a háromszög-egyenlőtlenség garantálja, hogy a cél az
   interakciós sávban van. Az alsó határ 0.2 yd helyett
   `ANCHOR_TOLERANCE_FLOOR = 0.5`. A legkisebb előremenő impulzus lovon
   ~0.56 yd, ezért 0.2 yd-es körnél rángatózás lenne. Ha a végpont messzebb
   van a céltól, mint a sáv, csak elérhető, sávba nem hozható.
3. **0/None határ.** A `_interaction_band` explicit pozitív értéket keres
   (desired_range, majd radius, végül a controller toleranciája). Az `or`-lánc
   a 0-t hiányzónak vette.
4. **Tesztdublőr.** A `test_uniform_entity_identity_20261016` hiányos
   `SimpleNamespace` requestje `timeout=None`-t kapott. Az explicit timeout a
   WIP óta minden owned requestnél ellenőrzött, és a típusos
   `NavigationRequest` mindig hordozza ezt a mezőt. Kizárás nem került
   hozzá.

## WIP-elemek, amik változatlanok és most le vannak fedve

- Corridor/waypoint az entity-anchor controller-kulcsban: új route vagy
  waypoint nullázza a régi megérkezési bizonyítékot, sima MOVE-nál marad az
  XY-identitás.
- Kis (<2 yd) célmozgás csak ARRIVED után kér replant, és csak ha a cél
  kikerült a sávból.
- Bounded `route_feedback` diagnosztika a movement- és a nested
  failure-nyomban.

## Ellenőrzés

- Új modul: `tests/test_route_feedback_wip_20261030.py`, 15 teszt. Lefedi:
  - lassú, gyors és határérték query;
  - újracímkézett / jövőbeli minta, REPLAN, ismert Z=0 és ismeretlen Z;
  - scope, halál, szellem, jármű, loading, timeout;
  - lassú lokális replan, megőrzött deadline/budget, cancel/reset, FAST
    handoff;
  - horgony-tolerancia, 0/None sáv, korridor-kulcs, kis célmozgás.
- Az átadás meglévő köre: **117 passed**.
- A 4083-as kör modullistája, az eredeti 10 kizárással, plusz az új modul:
  **4098 passed, 2 skipped, 10 deselected, 327 modul, exit 0**,
  197.79 s pytest.
- AST: 561 source és 636 test Python-fájl. 203 számozott coverage-sor
  változatlan. A két addoncsomag azonos. Az Ymir-pin változatlan.

Bizonyítékok: [route-feedback-wip-evidence](route-feedback-wip-evidence/source-verification.json)
(patch a 4083-as baseline-hoz, a fájl-hashek, a parancsok, a JUnit és a
logok).

## Határok

**OFFLINE_TESTED.** Élő futás nem volt rá. Ez nem globális
dispatch-frame/frissesség- vagy ACK-rendszer, és nem aszinkron route-worker:
a cold mesh query továbbra is blokkolhatja a főciklust. Nyitott kockázat: ha
a lassú query repülés vagy esés közben fut, a megállás után az elmozdulás
ismételt REPLAN-t okozhat. Ezt az eredeti budget korlátozza, élőben még nem
mértük.
