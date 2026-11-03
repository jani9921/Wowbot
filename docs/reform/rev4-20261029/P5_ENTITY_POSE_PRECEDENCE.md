# REV4 P5/P7 — exact server pose és ismeretlen addon-Z

2026-10-30. A felhasználó pontosítása: Retail addonból nincs használható Z;
a saját world XYZ mozgáscsomagokból érkezik. Offline javítás a kijelölt
`projekt` mappában; új élő elfogadás nincs.

A selected-target megközelítés korábban csak üres addon-pozíció mellett
használta a szerver actorját. Most a meglévő exact GUID / azonos instance /
nem removed / megfelelő kind ellenőrzésű szerverpozíció kap elsőbbséget
akkor is, ha az addon ad nem üres XY-t és hamis z_known / Z=0 értéket.
A kiválasztás és a friss target-azonosság továbbra is addon/UI bizonyíték;
a szerverpozíció nem választ targetet és nem engedélyez F7-et vagy spellt.
A mozgó server recipient ugyanazon reachen frissíti XYZ/layer értékeit.

Az addon-normalizáló minden UNIT_POSITION eredetű target/mouseover/soft-target/
visible-unit magasságot UNKNOWN-ként kezel, a használható XY-t és GUID-ot
megtartja. Az érkező szerver valós Z=0 értéke megmarad. Szerver hiányában
a navigation fallback és controller sem gyárt z=0 / layer_z=0 magasságot.
Az eredeti Observationt a navigáció nem írja át.

A saját álló karakter utolsó szervermagasságának meglévő megtartása és a
HEIGHT_PROBE_TURN változatlan: a korábbi ugrást a 2026-10-28-as mérés után
helyben fordítás váltotta fel. Külön nyitott sorrendi hiba: a typed route
tervezése a controller probe-ja előtt is lefuthat vagy elbukhat. Ez a
checkpoint önmagában még nem a tervezés előtti pozíciószerzés javítása.
A move_to_entity meglévő M0 ága továbbra is közvetlen controller reach;
a require_navmesh jelző jelenléte nem bizonyít tényleges typed MMAP route-ot.
Ennek medium-lane handoffja külön migrációs munka.

Célzott kör: 141 pass. Kijelölt regresszió: **4029 passed, 2 skipped, 10 unchanged deselections, 324 modules, exit 0**.
A korábbi tíz deselection változatlan; nem a teljes teszttár futtatása.
Az első célzott parancs egy nem létező modult nevezett meg, ezért ott nem
futott teszt; javított modullistával a két célzott kör 74 / 141 pass lett.
203 számozott coverage-sor változatlan. Addon/Ymir nem módosult.

[Forrás/diff/JUnit/parancs checkpoint](entity-pose-precedence-evidence/verification.json).
Az asszisztens nem indított játékot/capture-t/FULL_AI-t, nem küldött inputot,
nem módosított éles adatbázist. A tizenegy korábbi facing-hiba, teljes Travel/
Combat/Quest migráció és retained-provider paritás továbbra sincs lezárva.
