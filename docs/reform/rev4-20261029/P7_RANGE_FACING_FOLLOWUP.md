# REV4 P5/P7 — sustained range, canonical facing és hibanyom

2026-10-30. A [korábbi Charge/range javítás](P7_COMBAT_RANGE_HANDOFF.md)
folytatása, ugyanabban a kijelölt `projekt` mappában. Offline ellenőrzött;
új élő elfogadás nincs.

A CombatSkill a Charge 25-yardos maximumából 20-yardos `desired_range` értéket
hagyott a recovery-contextben. Ez a következő közelítéskor már túl nagy volt
Slam/Shield Slam számára. A canonical `combat.positioning.range` most a
nem-movement rotáció kívánt távolságát választja. Ismert pozitív caster-
envelope megmarad (30 → 24 yd); ismeretlen/0 envelope mellett a meglévő
3.5 yd-es alapérték marad. Charge miatt nem hátrál ki és a geometriai cél
nem jogosít spellt: a friss usability/range/cooldown/binding kapuk változatlanok.

Az `entity`, `best_position`, `travel_position` tényleges tiszta implementációi
`entity_spatial.py`-ba kerültek, a régi module ugyanazokat az objektumokat
exportálja. Három AST-törzs változatlan, nincs párhuzamos state-owner.
Ez a megtalált fájlszintű migráció kis, tényleges felelősségbontása.

A ReachMovementController végső bearing-számítása a tiszta
`navigation.facing_geometry` modult használja. Explicit kérési pont,
selected GUID és szerver-entitás külön forrás. Hiányzó/eltávolított/eltérő GUID
vagy hiányzó/eltérő szervertérkép nem válik a régi kérési pont felé küldött
vak fordulássá. Identitás-/pozícióvesztéskor typed terminal eredmény jön,
nem 2.5–8 s elteltével általános `facing_failed`; új megfigyelés önmagában
nem élesíti újra, explicit indítás kell.

A controller továbbra is az egyetlen fizikai mozgás-owner. A geometria nem
nyom gombot és nem hosszabbít retry budgetet. A meglévő screen-space
`FaceController` byte-változatlan maradt. Egy kezdeti fájlnévütközést az import-
teszt fogott; ezt a rögzített checkpointból javítottuk, az új geometria külön
fájlt kapott. Az egyetlen későbbi széles teszthiba pozitív fixture-e még a
saját server actor nélkül indított, majd később csendben visszaélesített.
A pozitív próba most a szükséges actorral indul, a külön negatív próba igazolja,
hogy hiányzó identitás esetén valóban megáll és nem indul újra magától.

Minden sikertelen mozgás lezárásakor egy bounded `NAVIGATION_FAILURE_DETAIL`
mentődik a meglévő naplóba: action ID, valódi ok, phase, steering, utolsó
sample, exact facing geometry és legfeljebb 6 korábbi fordulóparancs. Nem
másolja az összes entitást/corridort/waypointot minden tickben. A 180 képes
capture-limit után is megvizsgálható lesz, kapott-e koordinátát, milyen szögre
akart fordulni és volt-e kimenő turn-utasítás.

Célzott körök: sustained-range/combat 109 pass; facing/navigation 98 pass
(átfedések, nem összeadandók). Végső kijelölt regresszió: **4015 passed,
2 skipped, 10 változatlan deselection, 324 modul, exit 0**, pytest 163.87 s /
runner 166.87 s. Mind az 557 source és 633 test Python-fájl AST-je érvényes;
a 632 testmodulból a kijelölt 324 futott. A 203 számozott sor megmaradt.

[Forrás/diff/parancs/JUnit checkpoint](range-facing-followup-evidence/verification.json).
A korábbi checkpointok változatlanul megmaradtak. Az asszisztens nem indított
játékot/capture-t/FULL_AI-t, nem küldött inputot, nem írt éles adatbázist.
Addon/Ymir változatlan.

Az élő 11 ráfordulási hiba mindegyikének oka nincs bizonyítva; a nem változó
heading és a parancs-/pose-/entity-állapot pontos viszonyát az új részletes
terminális nyom teszi ellenőrizhetővé. A dialog-, route-envelope-, addon
unit-pozíció és teljes entity-goal/floor konzisztencia további auditot igényel.
A teljes Combat/Travel/Quest migráció és retained provider-paritás nem zárult le.
