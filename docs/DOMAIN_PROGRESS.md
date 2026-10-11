# Képességterületi kódaudit — 2026-10-07

> **Korrekció:** az alábbi százalékok előzetes képességleltár-becslések, **nem** lezárt, mély kódaudit eredményei. A későbbi kritikusút-audit új runtime/vision/combat/memory hibákat igazolt; ezért ezekből a számokból nem következik készültségi vagy live-validációs állítás. A bizonyítékokat és a nyitott audit-határokat lásd: [FULL_CODEBASE_AUDIT_2026-10-07.md](FULL_CODEBASE_AUDIT_2026-10-07.md).

Ezek **óvatos, 0–100%-os használhatósági becslések**, nem lefutott tesztek aránya és nem készültségi ígéret. A jelenlegi `projekt` forrás 390 Python-moduljának leltára, a 13 terület éles adatforrás → WorldModel → planner → skill/input → sikerellenőrzés útvonala, a teljes regressziós kör és a dokumentált felhasználói élő futások alapján készültek. A GitHub export `src`, `addon`, `config`, `tests`, `tools` fájljai az auditkor megegyeztek a `projekt` másolatával; a kihagyott eltérések két ideiglenes `.tmp` és két helyi, nem publikálandó fiókfájl voltak.

A százalék az **aktuális felhasználói képességet** becsüli. 0% itt azt jelenti, hogy nincs összekötött éles adat→cselekvés→eredmény út, nem azt, hogy egyetlen sor kód sincs. Részleges élő siker kézi segítséggel nagyjából 40–60%; ismételten önálló, változatos helyzetekben elfogadott ciklus nélkül 75% fölé nem megyünk. 100% csak a terület dokumentált teljes élő elfogadásakor lehetséges. A GitHub milestone saját sávja ettől különböző adat: **lezárt issue / összes issue**.

Teljes tesztkör a `projekt` másolatban: **2454 passed, 5 skipped, 15 failed**. A bukások nem bizonyítottan mind azonos gyökerűek; több quest/travel/search elvárást érintenek. Új live tesztet az audit során nem indítottunk.

| GitHub mérföldkő | Becsült használhatóság | Mit igazol a jelenlegi kód és élő napló? | Legfontosabb nyitott kapu |
|---|---:|---|---|
| [Questing](https://github.com/jani9921/Wowbot/milestone/1) | **50%** | Quest-log, dialog, objective, turn-in és credit út éles; több questet leadott, de kézi rásegítéssel és regressziókkal. | [#34](https://github.com/jani9921/Wowbot/issues/34) travel WAIT-loop, [#37](https://github.com/jani9921/Wowbot/issues/37) credit-eszkaláció, [#38](https://github.com/jani9921/Wowbot/issues/38) forráshierarchia; stabil önálló lánc. |
| [Navigation](https://github.com/jani9921/Wowbot/milestone/2) | **45%** | MMAP/VMAP, Z resolver, minimap és stuck-recovery használatban; barlangba és gubókhoz eljutott. | Többszintes route, fal/rámpa, fallback regresszió; [#33](https://github.com/jani9921/Wowbot/issues/33) útvonal-tapasztalat nincs az éles szolgáltatásban. |
| [Vision](https://github.com/jani9921/Wowbot/milestone/3) | **45%** | YOLO/World3D, minimap, hover és követés ténylegesen futott. | [#35](https://github.com/jani9921/Wowbot/issues/35) ID/box folytonosság, [#40](https://github.com/jani9921/Wowbot/issues/40) tartós feed-Hz, kis/takart NPC és hamis jel. |
| [Runtime & Setup](https://github.com/jani9921/Wowbot/milestone/4) | **40%** | A kiválasztott PID, addon/pixelstrip, GPU-s látás és helyi GUI futott; installerben backend-választó ágak vannak. | [#30](https://github.com/jani9921/Wowbot/issues/30) élesítési kapu, [#32](https://github.com/jani9921/Wowbot/issues/32) futó addon verzió, [#39](https://github.com/jani9921/Wowbot/issues/39) tiszta gépes install; nincs több hardveren elfogadva. |
| [Herbalism](https://github.com/jani9921/Wowbot/milestone/5) | **0%** | ResourceDomain/HERB kattintási váz és szintetikus teszt van, de éles node-adat nincs. | [#25](https://github.com/jani9921/Wowbot/issues/25) producer → [#20](https://github.com/jani9921/Wowbot/issues/20) élő teljes ciklus. |
| [Mining](https://github.com/jani9921/Wowbot/milestone/6) | **0%** | ResourceDomain/MINE és site-memória váz van, de éles node-adat nincs. | [#25](https://github.com/jani9921/Wowbot/issues/25) producer → [#21](https://github.com/jani9921/Wowbot/issues/21) élő teljes ciklus. |
| [Fishing](https://github.com/jani9921/Wowbot/milestone/7) | **0%** | Cast-parancs és szintetikus bobber-állapotú planner ág van; a FISH jelenleg a castot, nem a kifogott halat igazolja. | [#26](https://github.com/jani9921/Wowbot/issues/26) bobber/kapás producer + [#27](https://github.com/jani9921/Wowbot/issues/27) teljes verifikáció → [#22](https://github.com/jani9921/Wowbot/issues/22) élő ciklus. |
| [Skills](https://github.com/jani9921/Wowbot/milestone/8) | **50%** | Közös skill/verification út és valós object-use, item-use, loot, dialog használat; élőben igazolt járműhasználat (Scout-o-Matic, Giant Boar, Trample, visszaszállás), vendor vétel/eladás, jutalomválasztás, hover-megerősített TARGET/LOOT és interakciós hibakezelés ([#59](https://github.com/jani9921/Wowbot/issues/59)–[#63](https://github.com/jani9921/Wowbot/issues/63), [#46](https://github.com/jani9921/Wowbot/issues/46), [#47](https://github.com/jani9921/Wowbot/issues/47)). | Loot/item-use élő hibatűrés, [#36](https://github.com/jani9921/Wowbot/issues/36) typed VehicleSkill bekötése. |
| [Combat](https://github.com/jani9921/Wowbot/milestone/9) | **50%** | Valós pókharcok és Hrun kill; célzás, rotáció, eseménykorreláció és verifikáció kódja éles; élőben igazolt auto-attack interact billentyűvel, „kill vége = harcon kívül” szabály, halál → szellem-futás → feltámadás és jármű-harc ([#64](https://github.com/jani9921/Wowbot/issues/64), [#65](https://github.com/jani9921/Wowbot/issues/65)). | [#6](https://github.com/jani9921/Wowbot/issues/6) GUID-váltás, [#44](https://github.com/jani9921/Wowbot/issues/44) NPC-utasítás, range/facing/LOS, több cél és megszakítás ismételt élő elfogadása. |
| [World Model & Memory](https://github.com/jani9921/Wowbot/milestone/10) | **45%** | Addon FAST/FULL tények, evidence, SQLite, háttéríró és visszatöltés működő alap. | [#18](https://github.com/jani9921/Wowbot/issues/18) növekedés, [#25](https://github.com/jani9921/Wowbot/issues/25) hiányzó resource producer, cross-view azonosság. |
| [Autonomy & Verification](https://github.com/jani9921/Wowbot/milestone/11) | **30%** | Közös goal/supervisor/anti-loop/verification út és hosszú, részben sikeres futás. | Kézi beavatkozások, hamis siker/kudarc, a 15 bukó teszt [#17](https://github.com/jani9921/Wowbot/issues/17), [#42](https://github.com/jani9921/Wowbot/issues/42) input_blocked → MANUAL; tartós önálló soak nincs. |
| [Dungeon/PvE](https://github.com/jani9921/Wowbot/milestone/12) | **0%** | DungeonDomain csak kézzel injektált instance/group állapotból tudna tervezni. | [#28](https://github.com/jani9921/Wowbot/issues/28) éles állapot → [#23](https://github.com/jani9921/Wowbot/issues/23) élő ciklus. |
| [PvP](https://github.com/jani9921/Wowbot/milestone/13) | **0%** | PvPDomain csak kézzel injektált match/objective állapotból adna MOVE-ot. | [#29](https://github.com/jani9921/Wowbot/issues/29) éles állapot → [#24](https://github.com/jani9921/Wowbot/issues/24) élő ciklus. |

## Lezárt (kész) feladatok és a GitHub-sáv — 2026-10-07

A `BUGFIXES.md` ✅ (élőben igazolt) tételei képességenként lezárt issue-ként kerültek
a mérföldkövekbe, hogy a natív GitHub-sáv (lezárt / összes) a már elvégzett munkát
is mutassa. A 🧪 (csak offline) tételek nem kaptak lezárt issue-t. A natív sáv
továbbra sem azonos a fenti használhatósági becsléssel.

| Mérföldkő | Lezárt (kész) | Nyitott | GitHub-sáv |
|---|---|---|---:|
| Questing | #45 lánc, #46 vendor, #47 leadás, #48 terület-bejárás, #49 barlangos quest | #1, #3, #4, #34, #37, #38 | 5/11 ≈ 45% |
| Navigation | #50 épületek, #51 minimap-pötty, #52 zóna-szakaszok | #7, #8, #9, #10, #11, #33 | 3/9 ≈ 33% |
| Vision | #53 YOLO v10, #54 külön folyamatok, #55 kamera-kompenzáció | #12, #13, #14, #15, #35, #40, #43 | 3/10 = 30% |
| Runtime & Setup | #56 élesítési kézfogás, #57 fő ciklus teljesítmény, #58 addon 0.9.58 | #16, #19, #30, #31, #32, #39 | 3/9 ≈ 33% |
| Skills | #59 járművek, #60 hover-kattintás, #61 loot, #62 objektum, #63 interakció | #2, #5, #36 | 5/8 ≈ 63% |
| Combat | #64 auto-attack/harc vége, #65 halál | #6, #44 | 2/4 = 50% |
| World Model & Memory | #66 quest-relevancia | #18, #25 | 1/3 ≈ 33% |
| Autonomy & Verification | #67 helyi MI, #68 időzített FULL_AI | #17, #41, #42 | 2/5 = 40% |
| Herbalism / Mining / Fishing | — | #20 / #21 / #22, #26, #27 (+#25) | 0% |
| Dungeon/PvE / PvP | — | #23, #28 / #24, #29 | 0% |

## Statikus kódaudit — 2026-10-07

`ruff` (F, B szabályok) és célzott kézi átnézés a futási útvonalon; telepítés és
tesztfuttatás nélkül. Nem definiált név vagy szintaktikai hiba nincs; a billentyű-
elengedés, a vészleállítás és a bindings-ellenőrzés rendben van. Új issue-k:

- [#30](https://github.com/jani9921/Wowbot/issues/30) **valódi hiba:** a `waiting_for_world3d_detector` blokkoló csak kiírás, a FULL_AI a detektor bemelegedése alatt is élesedhet (`agent/runtime.py`), teszt nincs rá.
- [#31](https://github.com/jani9921/Wowbot/issues/31) csendben elnyelt kivételek (bejárat-tanulás, képességhatás-mentés, képkocka-figyelők).
- [#32](https://github.com/jani9921/Wowbot/issues/32) a futó addon verzióját az élesítés nem ellenőrzi; két azonos addon-másolat.
- [#33](https://github.com/jani9921/Wowbot/issues/33) `NavigationMemory`/`NavigationEngine` nincs az éles úton; hívásonként új, le nem zárt SQLite-kapcsolat.
- [#41](https://github.com/jani9921/Wowbot/issues/41) 13 halott változó a modulbontás után, 50 nem használt import, 5 db 800+ soros modul (a `service.py` 1163 sor).
- [#42](https://github.com/jani9921/Wowbot/issues/42), [#43](https://github.com/jani9921/Wowbot/issues/43), [#44](https://github.com/jani9921/Wowbot/issues/44): a `KNOWN_ISSUES.md` eddig issue nélküli pontjai (input_blocked, Live Vision talajvonal, NPC-utasítás).

## Miért nulla az öt vázkódos terület?

Az éles `src/wowbot/agent/world_query.py` olvassa a `resource_observations`, `fishing`, `instance_state`, `group_state`, `pvp_state` mezőket, a `planning_domains.py` pedig ezekből állítana elő terveket. A `src` és `addon` jelenlegi kódjában nincs e mezők éles írója. A tesztek injektált állapottal bizonyítják a planner ágát, nem a játéktól az eredményig tartó funkciót. Ezt korábban túlértékeltem.

A régi M0–M27 kapuk történeti alapok, nem a mai képességek automatikus igazolásai. Részletes követés: [CURRENT_SOURCE_COVERAGE.md](CURRENT_SOURCE_COVERAGE.md), [LIVE_VALIDATION.md](LIVE_VALIDATION.md), [KNOWN_ISSUES.md](../KNOWN_ISSUES.md). A felhasználó indítja az élő teszteket; az asszisztens a naplókat elemzi.
