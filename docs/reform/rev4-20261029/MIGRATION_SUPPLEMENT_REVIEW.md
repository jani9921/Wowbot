# A megtalált fájlszintű migrációs melléklet átvétele

2026-10-30. A felhasználó most adta át a korábban hiányzó
`SRC_MIGRACIOS_TERV_20261029_HU.md` fájlt. Az eredeti, 2026-10-29-i ZIP-ben
nem volt benne; az akkori input-manifest és hiánylista történeti tényként
megmarad. Az eredeti melléklet byte-változatlanul az `input/` könyvtárba került.

- SHA-256: `d4c7136232748c71e03400e0ed97fadec40f55189b1d2d9132831dde5310c1e4`
- Méret: 25 233 byte; 747 sor.
- [Átvételi manifest](supplement-manifest.json), [eredeti dokumentum](input/SRC_MIGRACIOS_TERV_20261029_HU.md).

A dokumentumot forráshoz igazított migrációs mellékletként használjuk. Nem
új master, nem korlátlan capture/input-engedély, nem a benne szereplő korábbi
terv automatikus implementáltsága. Az aktuális V4/Design és az újabb közvetlen
felhasználói irányok maradnak mérvadók. A `plan-evidence.json` ettől nem került elő.

## Ami pontosítja a jelenlegi munkát

A közös szerződések és bekötések nem jelentik az összes tulajdonosi határ
tényleges szétbontását. A melléklet konkrét Target/Ability/Facing extractiont,
vékony CombatSkillt, Travel provider/transition/recovery bontást és futó
questmechanika-gráfot kér, majd függőségi kapuval zárja le a régi utak kiváltását.
A teljes migráció készültsége ezek nélkül nem állítható.

Az új package neve önmagában sem elfogadási kapu. A meglévő
`navigation/travel.py` tényleges TravelRequest/TripPlan/TransitionSystem/
TripExecutor bekötése megmarad; attól, hogy nem `travel/` a könyvtár neve,
nem tekintjük hiányzónak. A monolit NavigationService bontása viszont külön
megvalósítási feladat, nem puszta átnevezés.

## Számozási megfeleltetés és ellenőrzött állapot

A melléklet M0–M8 ütemei nem a master M0/M1 elfogadási szintjei, és nem
írják felül az eddig követett P0–P9 fázisokat.

| Melléklet | P0–P9 kapcsolat | Ellenőrzött állapot / még szükséges munka |
|---|---|---|
| M0 baseline, contract, importkapu | P0/P1 | Scoped source/test/addon checkpointok és szerződések vannak. Új combat importkapu elkészült; teljes régi importgráf tisztítása és élő trace-kapu nincs lezárva. |
| M1 session/bootstrap | P2/P3 | Független login/PID/build, context és kézbesítési rés kezelve. Teljes retained collection, warm state és consumer parity hiányzik. |
| M2 Target/Ability/Facing extraction | P1/P7 | Az első konkrét bontás ebben a körben elkészült: egyetlen canonical TargetManager, ability contract/evaluator/catalog, tiszta facing. Régi importok csak reexportok. A nagy CombatSkill további szétbontása nyitott. |
| M3 arbitrator/role | P7 | Canonical arbitrator és aktuális profil/bar integráció megvan; a teljes Rotation/Interrupt/Defensive/Positioning/CC jelöltkészlet és role provider nincs kész. Solo/DPS az első cél; dungeon/raid/PvP nem bővül az M0/M1 kapuk előtt. |
| M4 Travel | P5 | Általános request, leg-vég és végső érkezés megkülönböztetése bekötött. A 2615 soros NavigationService provider/transition/recovery felelősségeinek további bontása nyitott. |
| M5 route risk | P6 | RouteScore és ground/flight összevetés bekötött. Teljes profilfüggő harci költség és élő kalibráció hiányzik. |
| M6 mechanikák és célkontextus | P8 | Közös classifier/resolver, physical actor vs credit ID és shared skill-kapu megvan. A hiányzó handler és minden régi special-case contract mögé rendezése nincs lezárva. |
| M7 execution graph | P8/P9 | Belső lépés/readiness/horizon és verifier-trial kapcsolatok vannak. Ez nem teljes conditional/recovery-edge graph executor; a hiányzó mechanikákat külön kell megírni. |
| M8 legacy/boundary cleanup | P4/P9 | SERVER runtime nem konstruál vision/trackert. Az összes régi domain helper és importciklus nincs kivezetve. Az új combat magra már tényleges tiltó importkapu fut. |

## Következő munkasorrend

1. Az itt elkészült combat extraction lezárása a meglévő regresszióval; egy
   implementáció, kompatibilis importok, új függetlenségi kapu.
2. P2/P3 source-progress/applied watermark és retained quest/inventory állapot,
   majd a támogatott questprogress és fogyasztók paritása.
3. Solo combat teljesebb adatútja és az FSM/target/facing/rotation/recovery
   felelősségeinek tényleges szétválasztása, közös arbitratorral.
4. Meglévő Travel controller megőrzése mellett provider/transition/recovery
   bontás; a questmechanika-gráf hiányzó futási/hibaágai.
5. Kiváltott adapterek/importok takarítása, majd a felhasználó élő próbái.

A megtalált dokumentum nem indok a működő MMAP/flight/verifier/dispatcher
eldobására. Nem keletkezik második combat vagy quest brain. Új százalék és
pontos befejezési idő nincs ebből levezetve; a kódos és élő kapuk külön maradnak.
