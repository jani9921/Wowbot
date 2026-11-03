# REV4 P5 — saját pozíció kérése a grounded 3D route előtt

2026-10-30. Felhasználói pontosítás: addonból nincs saját Z, állva nem
feltétlenül érkezik saját mozgáscsomag; ezért volt a korábbi ugrás.
A meglévő kód a 2026-10-28-as mounted mérés óta egy 0.06 s helyben
fordítást használ HEIGHT_PROBE_TURN néven. Ez a mód megmaradt.

A sorrendi hiba valós volt: start_request már navmesh/Z-tervezést futtatott,
míg a probe csak a későbbi controller.command része volt. Hibás/ambiguous
rétegből a route már előtte elbukhatott, így a probe nem futhatott le.

Most a live packet-lane-nel rendelkező, grounded, MMAP-ot igénylő world
request hiányzó saját megfigyelt magasságnál először pozíciót kér. Ugyanaz
a NavigationService és ReachMovementController marad az egyetlen owner.
A pending rész nem hív globális/lokális útvonaltervezést és nem állít
megérkezést; egy bound turn commandot javasol, utána nem küld előremenetet.
A binding hiánya nem válik kitalált billentyűvé. Az érkező koordinátát a
meglévő own packet reducer/projector adja; nincs memory-reader vagy új parser.

A gyors lane a használható own pozíciónál leengedi a mozgási lease-t és
movement_position_acquired_pending okkal medium handoffot kér. Nem hív
nehéz route queryt. A MovementSkillRunner medium lépése ugyanazt a requestet,
eredeti célt és kezdőidőt folytatja a megfigyelt Z-ből. A lokális query-út is
blokkolva van a first fix előtt; a controller observe sem rejt route queryt
az új pending fázis mögé.

A várás maximum 3 s vagy az eredeti rövidebb request budgetje. Az ismételt
same-request start nem indít új órát. TIMEOUT itt POSITION_UNCERTAIN,
kontextusváltás WRONG_MAP_CONTEXT; dialog/cast/combat/death/fall/vehicle
átmenet megszakít. Cancel/reset eldobja a pending requestet; késői packet
önmagában nem indítja újra. Az álló helyzetben megtartott megfigyelt own
Z nem vált ki új probe-ot. Vision/legacy, már repülő és vehicle ágak saját
meglévő szerződése változatlan; ez még nem minden flight/vehicle first-fix
és nem a közvetlen M0 move_to_entity typed-route migrációja.

A position_acquisition snapshot a controller resetje után is bounded módon
megőrzi az utolsó frissítő command-JAVASLATOT, eredeti időt, acquired Z-t /
forrást, tervezési eredményt vagy valódi hibát. Sikertelen mozgásnál bekerül
a NAVIGATION_FAILURE_DETAIL eseménybe. A javaslat nem állítja, hogy a fizikai
input ténylegesen lement; az a meglévő dispatcher/executor nyomából igazolandó.
Nincs teljes world/corridor/packet body másolás vagy tickenkénti DB-írás.

Célzott végső kör: 112 pass; további flight/travel regresszió: 71 pass
(átfedő körök, nem összeadandók). Kijelölt regresszió: **4057 passed, 2 skipped, 10 unchanged deselections, 325 modules, exit 0**, 176.38 s
pytest / 178.97 s runner. A 10 korábbi deselection változatlan, nem teljes
teszttár-futtatás. 558 source és 634 test Python-fájl AST-ellenőrzött,
203 számozott coverage-sor változatlan.

[Forrás/diff/JUnit/parancs checkpoint](position-before-route-evidence/verification.json).
Az előző exact server-pose checkpoint megmaradt. Addon/Ymir változatlan;
az asszisztens nem indított játékot/capture-t/FULL_AI-t, nem küldött kliens-
inputot és nem írt éles DB-t. A jelenlegi javítás OFFLINE_TESTED. Új élő
probe/quest elfogadás, a korábbi 11 facing-hiba teljes magyarázata, a nagy
Combat/Travel/Quest felelősségmigráció és retained-provider paritás nyitott.
