# Agent-építési mérföldkövek (konkrét lépcsők és kapuk)

Állapot: 2026-10-12, a külső feature-lista összevetésével kiegészítve 2026-10-26-án. A GitHub-mérföldkövek ([milestones](https://github.com/jani9921/Wowbot/milestones)) a
képességterületek. Ez a dokumentum mindegyiket számozott, egymásra épülő **építési lépcsőkre** bontja.
Minden lépcsőnél le van írva:
- mit kell megépíteni;
- mi a **kapu**: mikor számít késznek;
- mi az állapota.

A V5 specifikáció M1–M6 „definition of done” pontjai
(`wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt`) a megfelelő lépcsőknél
hivatkozva vannak.

**Jelölés:**
- ✅ élőben igazolt, ismételhetően;
- 🟡 élőben részben megy (kézi segítséggel vagy nem minden esetben);
- 🧪 megépítve, offline tesztelve, élőben még nem igazolt;
- ⬜ nincs megépítve.

**Kapuszabály:** egy lépcső akkor ✅, ha
- (1) van rá offline regressziós teszt, **és**
- (2) legalább **3 külön élő futásban** kézi beavatkozás nélkül teljesült, **és**
- (3) a futásjelentés (AB1) mérőszáma a küszöb alatt van.

Szintetikus visszajátszás nem számít élő igazolásnak.

---

## Építési sorrend (release-létra)

Mindig a legalacsonyabb nyitott AB-szinten dolgozunk; egy szint a felsorolt lépcsők kapujával zárul.

| Szint | Cél | Szükséges lépcsők | Kapu |
|---|---|---|---|
| **AB1 — Mérhető futás** | Minden élő teszt után automatikus jelentés; a haladás mérhető, nem becsült. | A1, A2 | A `tools/run_report.py` egy futásból ezeket adja: kész questek és idejük, 5 s-nál hosszabb tétlenségek az okukkal, elbukott skillek okkal, kézi beavatkozások, vision-resetek, esések. A próbaidő csak az aktív FULL_AI időt számolja. |
| **AB2 — Exile's Reach első fele** | A kezdéstől a Quilboar-táborig (Northbound, Cooking Meat, Quilboar questek, Scout-o-Matic, Re-Sizer) kézi segítség nélkül. | Q1–Q4, S1–S4, C1–C3, N1–N2, W1–W2 | 3 futás × 0 kézi beavatkozás; 10 s-nál hosszabb tétlenség < 5 / 30 perc; nincs elakadás 60 s-nál tovább. |
| **AB3 — Exile's Reach végig** | Hárpiák, Darkmaul, barlangos quest (Hrun), a Darkmaul Citadel előtti lánc. | + N3–N4, Q5, C4, V2 | Egy teljes Exile's Reach futás 0 kézi beavatkozással; 2 további futásban legfeljebb 1 beavatkozás. |
| **AB4 — Robusztus látás** | Az NPC-k és mobok azonosítója és doboza stabil; pontos megközelítés. | V2–V4, V6 | Visszajátszós tesztek valódi, sűrű felvételből; élőben nincs új track-ID ugyanarra az NPC-re ablak/kamerafordulás után; megközelítésből < 10 % „túl messze”. |
| **AB5 — Tartós önállóság** | Hosszú, változatos önálló futás. | A3–A5, N5–N6, W4 | 2 órás soak 0 kézi beavatkozással; nincs hamis siker a verifikációban (mintavételes ellenőrzés a futásjelentésből). |

Herbalism és Mining **félretéve** (felhasználói döntés, 2026-10-12): nincs rájuk építési lépcső. A Fishing
későbbi téma, AB5 után.

---

## Questing ([milestone 1](https://github.com/jani9921/Wowbot/milestone/1)) — V5 M3

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| Q1 | NPC-párbeszéd | Felvétel, leadás, jutalomválasztás, több quest egy ablakban, gossip-opció, üres ablak bezárása, követő quest ugyanannál az NPC-nél | Mind az 5 ablaktípus élőben, 3 futásban | 🟡 felvétel/leadás ✅, két quest egy ablakban ✅ (10-11), követő quest + ESC 🧪 |
| Q2 | Objective-típusok | KILL, COLLECT (loot), USE_ITEM lényen, OBJECT_USE (totem, gubó), TALK/INTERACT_NPC, BUY/SELL, jármű, ESCORT/DEFEND | Minden típus legalább egy Exile's Reach questen, kézi segítség nélkül | 🟡 KILL/loot ✅; jármű ✅; totem ✅; Re-Sizer, vendor, gubó 🧪/🟡 |
| Q3 | Helykeresés | Létra: élő jel → sárga pötty (memória) → TDB-spawn → TDB-POI kígyózó bejárás; a TDB a szövegben megnevezett lényt is adja | A célpont a quest felvétele után ≤ 60 s alatt kijelölve, a futások 80 %-ában | 🧪 (zóna-bejárás 10-11 élőben elindult) |
| Q4 | Sorrend és leadás | Közeli quest előbb, kötegelt leadás (120/220 yd), leadó-keresés, tanult leadóhely magassággal | Nincs „leadás, majd vissza ugyanoda” egy futásban sem | 🧪 |
| Q5 | Speciális questek | Barlang/többszint, gossip-harc (Hjalmar), emote (/wave, /dance), Extra Action, dungeon-belépő | Az Exile's Reach összes ilyen questje önállóan | 🟡 barlang élőben egyszer kész (10-06), emote ⬜ |
| Q6 | Beszéd- és objektum-kapus objective-ek | Gossip után kivárt NPC-beszéd, ha kreditet ad; a beszélgetés után aktiválódó quest-objektum (szerver-link vagy DB2 KILL_CREDIT spell) F7-tel | Best Plans and Intentions (66048) önállóan, 3 futásban | 🟡 asztal ✅ egyszer (10-26), Edress-várakozás + távcső 🧪 |
| Q7 | Szintlépés-hézag | Ha nincs elérhető quest a szintünkön: közeli, szintnek megfelelő mobok ölése (TDB spawn + szerver-pozíció) a következő quest szintjéig | Elakadás nélkül átjut egy hézagon | ⬜ |

Quest-típusok előre: a [QUEST_MECHANICS.md](QUEST_MECHANICS.md) felmérés minden objective-et mechanikába sorol
(TDB + DB2, `tools/quest_mechanics_census.py`), a [QUEST_PLAYBOOKS.md](QUEST_PLAYBOOKS.md) mechanikánként leírja a
felismerést, a lépéssort, a kész-jelet és a buktatókat. A következő építési sorrend ott van (E2 kísérés, USE_ITEM/ItemEffect,
ARRIVE, WITNESS).

Nyitott issue-k: [#1](https://github.com/jani9921/Wowbot/issues/1), [#3](https://github.com/jani9921/Wowbot/issues/3), [#4](https://github.com/jani9921/Wowbot/issues/4), [#34](https://github.com/jani9921/Wowbot/issues/34), [#37](https://github.com/jani9921/Wowbot/issues/37), [#38](https://github.com/jani9921/Wowbot/issues/38).

## Navigation ([milestone 2](https://github.com/jani9921/Wowbot/milestone/2)) — V5 M5

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| N1 | Útvonal és megérkezés | MMAP-útvonal, megérkezés-ellenőrzés, útvonal nélküli megérkezés | 95 % sikeres MOVE egy futásban | ✅ |
| N2 | Beragadás és esés | Stuck-felismerés és -feloldás; esés-debounce (2 s), veszélyzóna csak valódi esésre | 0 „fall_hazard_on_route” holtpont; stuck-feloldás < 10 s | 🟡 stuck ✅, esés 🧪 |
| N3 | Szintek (Z) | Z resolver, VMAP, saját szint követése, fel/le nyilak, célpont-magasság (tanult hely + TDB z) | A barlangos quest 3 futásban, rossz szintre tervezés nélkül | 🟡 (élőben egyszer; Bjorn-eset 🧪) |
| N4 | Zóna-bejárás | TDB-POI kígyózó cellák, kamerapásztázás, csak quest-releváns megszakítás | A bejárás ≤ 3 percen belül megtalálja a célt a futások 80 %-ában | 🧪 |
| N5 | Egységes zóna- és szinttérkép | Összefogja a minimap kék területét, a TDB-poligont és a szinteket | Egy többszintes zónában nincs ismételt cella-bejárás | ⬜ |
| N6 | Útvonal-tapasztalat | [#33](https://github.com/jani9921/Wowbot/issues/33) a tanult akadályok és átjárók az éles szolgáltatásban | Ugyanazon az akadályon 2. alkalommal nincs stuck | ⬜ |
| N7 | Szállítóeszközök | Lift, hajó, zeppelin: a szerver transport-GameObjectje és útvonal-állása (Ymir) alapján várni, felszállni, leszállni | Egy liftes és egy hajós átkelés önállóan | ⬜ |
| N8 | Taxi (flight path) | Flight master megszólítása, célállomás választása, leszállás utáni folytatás; a TDB taxi-csomópontjai és a tanult állomások alapján | Hosszú út taxival ott, ahol gyorsabb, 3 futásban | ⬜ |
| N9 | Temető-választás | Halál után holttest-futás vagy spirit healer, ha a holttest elérhetetlen; több temető közül a legközelebbi | Elérhetetlen holttestnél nincs végtelen ciklus | ⬜ |

## Vision ([milestone 3](https://github.com/jani9921/Wowbot/milestone/3)) — V5 M4

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| V1 | Egységfelismerés | YOLO v10 (3 osztály), capture-vezérelt feed, ≥ 30 Hz World3D | Tartósan ≥ 30 Hz egy 5 perces futásban | ✅ (0.9.63 után) |
| V2 | Track-folytonosság | Nincs reset NPC-ablakra (#35), elavult dobozok (#69, #104–#106) | A futásjelentés szerint < 1 vision-reset / 5 perc (térképnyitáson kívül); egy NPC egy azonosítóval | 🧪 (#35, 10-12) |
| V3 | Azonosítás | Hover → tooltip/GUID-megerősítés, minimap célpont-jel | ≥ 90 % sikeres INSPECT egy futásban | ✅ |
| V4 | Kis/takart NPC, hamis jel | [#12](https://github.com/jani9921/Wowbot/issues/12), [#14](https://github.com/jani9921/Wowbot/issues/14), szimbólumszerű doboz nem quest-jel | Nincs megszakítás állatnál leadóútvonalon; kis NPC (gnóm) megtalálva | 🟡 |
| V6 | Sűrű „feketedoboz” felvétel | ~10 Hz rögzítés a döntések körül, visszajátszós teszt a megközelítésre és a hoverre | Legalább 5 valódi felvételből vágott regressziós teszt | ⬜ |

## Runtime & Setup ([milestone 4](https://github.com/jani9921/Wowbot/milestone/4))

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| R1 | PID, bindings, addon-kézfogás | Kiválasztott PID és bindings-cache, élesítési kapu | Élesítés 3 futásban hibátlan | ✅ |
| R2 | Pixelcsík | Két sáv (0.9.63), STATE/FAST összefésülés beágyazott mezőkkel | Nincs elveszett mező (pl. quest-sorok) 3 futásban | 🟡 (merge-javítás 10-11 után ✅ két questnél) |
| R3 | Addon-verzió | [#32](https://github.com/jani9921/Wowbot/issues/32): a futó addon verzióját az élesítés ellenőrzi | Régi addonnal nem indul FULL_AI | ⬜ |
| R4 | Tiszta telepítés | [#39](https://github.com/jani9921/Wowbot/issues/39), TDB-útmutató ([TDB_SETUP.md](TDB_SETUP.md)) | Üres gépen a wizard + TDB-lépések után fut | 🟡 |
| R5a | Háttér-üzem: takarásban | A játékablak nincs fókuszban, más ablak takarja. Ablakonkénti capture (WGC) a DXGI asztal-duplikáció helyett; input közvetlenül a kiválasztott ablaknak (PostMessage a SendInput + fókuszkövetelmény helyett); a felhasználó közben használhatja a gépet | 30 perc futás, miközben a felhasználó más ablakban dolgozik; 0 elkóborolt billentyű más ablakba | ⬜ |
| R5b | Háttér-üzem: tálcán (minimalizálva) | Minimalizált ablakot a Windows nem rajzol ki, így a pixelcsík nem olvasható. Az állapotnak képernyő nélkül kell jönnie: a szerver-csomagokból (Ymir, read-only) a pozíció, entitások, quest-log, gossip/quest-ablak, loot, harc; amit csak az addon tud, annak csomag-megfelelőjét kell megtalálni. A quest- és gossip-ablak tartalmát a szerver küldi (SMSG_GOSSIP_MESSAGE, SMSG_QUEST_GIVER_QUEST_DETAILS / REQUEST_ITEMS / OFFER_REWARD_MESSAGE / QUEST_LIST_MESSAGE, SMSG_GOSSIP_COMPLETE); a WowPacketParser a felhasználó dumpjaiból már kiszedte (gossip_menu_option szövegek, quest_details, quest_offer_reward, 2026-10-25), az élő dekóder viszont ma csak a QUEST_GIVER_STATUS-t és a QUEST_UPDATE_ADD_CREDIT-et olvassa. A quest-log a játékos update-mezőiben jön. Memóriaolvasás és injektálás továbbra is tilos | 30 perc futás tálcára tett játékkal, 0 kézi beavatkozás | ⬜ |

## Skills ([milestone 8](https://github.com/jani9921/Wowbot/milestone/8)) — V5 M2

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| S1 | TARGET, INTERACT, LOOT | Hover-megerősített kijelölés, megszólítás friss hibaüzenettel, lootolás | ≥ 90 % első próbálkozásra | ✅ |
| S2 | Tárgyhasználat | Akciósáv, Interact-gomb, táska; távol → előbb odamegy; átváltozó célpont | Re-Sizer 3/3 önállóan | 🧪 |
| S3 | Jármű | VEHICLE_ABILITY / EXIT_VEHICLE; [#36](https://github.com/jani9921/Wowbot/issues/36) holt `VehicleSkill` takarítása + integrációs teszt | Scout-o-Matic és Giant Boar önállóan | ✅ (#36 ⬜) |
| S4 | Kereskedő és UI | BUY/SELL, nyitott bolt fogja az inputot, CLOSE_DIALOG, nincs térkép ablak fölött | Stocking Up < 60 s a boltnál | 🧪 |
| S5 | Táska és javítás | Tele táska → eladás a legközelebbi vendornál (TDB `npc_vendor` + szerver-pozíció), javítás repair vendornál adott tartósság alatt, szürke tárgyak eladása | 2 órás futásban nincs „tele táska” elakadás | 🟡 (SELL/REPAIR skill van, időzítés ⬜) |
| S6 | Felszerelés-fejlesztés | Quest-jutalom és drop: jobb tárgy felvétele (item-szint/statok a DB2-ből) | Nincs gyengébb tárgy felvéve egy futásban | 🟡 (jutalomválasztás van, auto-equip ⬜) |
| S7 | Tréner | Új szintnél class tréner felkeresése (TDB `trainer`), spellek megtanulása, az actionbar-katalógus frissítése | Szintlépés után a tréner önállóan | ⬜ |
| S8 | Postaláda | Csak később, ha szükséges | — | ⬜ |

## Combat ([milestone 9](https://github.com/jani9921/Wowbot/milestone/9)) — V5 M2

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| C1 | Egy célpont | Warrior-rotáció, auto-attack, harc vége = harcon kívül | ≥ 95 % ölés egy futásban | ✅ |
| C2 | Hiba-helyreállítás | Range/facing/LOS-hiba helyreállítása | Nincs 3-nál több egymás utáni ugyanilyen hiba | 🟡 |
| C3 | Halál | Halál → szellem → feltámadás | 3 futásban önállóan | ✅ |
| C4 | Több ellenfél | Adds, célpontváltás, [#6](https://github.com/jani9921/Wowbot/issues/6) GUID-váltás, [#44](https://github.com/jani9921/Wowbot/issues/44) NPC-utasítás | Hárpia-tábor 2+ ellenféllel halál nélkül | ⬜ |
| C5 | Single-Button Assistant | Exile's Reach után a kliens Single-Button Assistantja egy gombon a legjobb DPS-t adó következő spellt kínálja (a felhasználó a 2-es bindre tette, 2026-10-21). Harcban, érvényes célponttal ezt a gombot lehet folyamatosan nyomni a saját rotáció helyett. Csak feljegyzés, a felhasználó jóváhagyásával épül. | — | ⬜ |
| C6 | Lerakós / célpontra dobós quest itemek | Pl. Bottled Water Elemental (66998, 30 s CD, talajcélzós). Terv (2026-10-23): az addon két rejtett biztonságos gombja (`/use [@target] item:<id>` egységre, `/use [@player] item:<id>` a lábhoz; @target talajcélzóra nem működik, ilyenkor a mob szerver-pozíciójához megy), a felhasználó bindeli őket (AddOns → AIPC), az agent a bindings-cache-ből látja. Halott mob: soft-interact kijelölés. Felhasználó: „egyelőre hagyjuk”. | — | ⬜ |
| C7 | Pihenés | Harc után evés/ivás vagy pihenés egy küszöbig, mielőtt új célpontot keres; harc közben menekülés/defenzív alacsony HP-n | Halál nélkül 10 egymás utáni harc | ⬜ |
| C8 | Megszakítás és immunitás | Ellenfél cast-jának megszakítása (Pummel), immunis/ellenálló mobon a hatástalan spell kihagyása a tanult találat/miss alapján | Nincs ismételt hatástalan cast ugyanazon a mobon | ⬜ |

## World Model & Memory ([milestone 10](https://github.com/jani9921/Wowbot/milestone/10))

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| W1 | Addon-tények | FAST/FULL összefésülés, frissesség, quest-modell | 0 „elveszett mező” hiba a futásjelentésben | 🟡 |
| W2 | TDB-memória | TDB mint statikus világmemória + tanult TDB-fájl, ugyanazzal a táblaszerkezettel | Minden Exile's Reach quest felvevője, leadója és helye megvan, élőben megerősítve | 🧪 (élőben ír) |
| W3 | Quest-lény memória | Felvevő, leadó, objective, jármű, kinézet | ✅ | ✅ |
| W4 | Növekedés és karbantartás | [#18](https://github.com/jani9921/Wowbot/issues/18): a ~1 GB-os debug-napló korlátozása, konszolidáció | A profilmemória < 200 MB egy hét futás után | ⬜ |

## Autonomy & Verification ([milestone 11](https://github.com/jani9921/Wowbot/milestone/11)) — V5 M1, M6

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| A1 | Futásjelentés | `tools/run_report.py` (lásd AB1) | Egy futás jelentése < 30 s alatt elkészül, és egyezik a kézi elemzéssel | ⬜ |
| A2 | Aktív próbaidő | A `--trial-seconds` csak az aktív FULL_AI időt számolja | A felfüggesztés nem fogy a keretből | ⬜ |
| A3 | Nincs hamis siker/kudarc | Verifikáció-audit a futásjelentés mintáiból (pl. a Re-Sizer, a bolt és a leadás esetei) | 0 ismert hamis eredmény 3 futásban | 🟡 |
| A4 | Tétlenség-őr | 10 s-nál hosszabb WAIT-szakasz automatikus okelemzése és helyreállítása | A futásjelentésben nincs 30 s-nál hosszabb tétlenség | ⬜ |
| A5 | Soak | 2 órás önálló futás | AB5 kapuja | ⬜ |
| A6 | Élő megfigyelés | A GUI-ban állapotgép-, útvonal- és célpont-nézet; opcionálisan összefoglaló értesítés telefonra | A felhasználó a GUI-ból látja, mit miért csinál | 🟡 (GUI + LIVE VISION van) |

## Fishing ([milestone 7](https://github.com/jani9921/Wowbot/milestone/7)) — AB5 után

A TDB-ben 1 668 halraj-spawn van (csak a régi kontinenseken); a sima horgászathoz víz kell, amit a
navigációs adatok (VMAP/MMAP) ismernek.

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| F1 | Úszó és kapás | [#26](https://github.com/jani9921/Wowbot/issues/26) úszó és kapás felismerése | 20 dobásból ≥ 18 kapás észlelve | ⬜ |
| F2 | Kifogott hal igazolása | [#27](https://github.com/jani9921/Wowbot/issues/27) zsákmány-ellenőrzés a cast helyett | 20 dobásból ≥ 15 igazolt hal | ⬜ |
| F3 | Horgászhely | Víz a navigációs adatokból, halraj a TDB-ből + látás | Önálló helyválasztás és 30 perc horgászat | ⬜ |

Herbalism ([5](https://github.com/jani9921/Wowbot/milestone/5)) és Mining ([6](https://github.com/jani9921/Wowbot/milestone/6)):
**félretéve** (felhasználói döntés, 2026-10-12). A TDB tartalmazza a node-okat (13 681 spawn, főleg a régi
kontinenseken, pool-rotációval), ha később mégis előkerülnének.

## Dungeon/PvE és PvP ([12](https://github.com/jani9921/Wowbot/milestone/12), [13](https://github.com/jani9921/Wowbot/milestone/13))

AB5 után, a Fishing mellett vagy után. A szerveren mindhárom játszható botokkal (felhasználó, 2026-10-26):
follower dungeon, sima dungeon bot-társakkal, battleground bot-játékosokkal. Első lépcsőjük az éles
állapot-producer ([#28](https://github.com/jani9921/Wowbot/issues/28), [#29](https://github.com/jani9921/Wowbot/issues/29)): instance/csoport-, illetve meccs/cél-állapot az addonból és a szerver-csomagokból.

| # | Lépcső | Mit kell megépíteni | Kapu | Állapot |
|---|---|---|---|---|
| D1 | Follower dungeon | Belépés (queue/portál), a követők mellett haladás, bossok, halál/wipe kezelése, kilépés; dungeon-útvonal a navmesh-ből | Egy follower dungeon végig, 0 kézi beavatkozás | ⬜ |
| D2 | Dungeon bot-társakkal | Csoport-szerep (DPS/tank), target-követés, pull-szabályok, loot-roll | Egy normál dungeon végig botokkal | ⬜ |
| P1 | Battleground bot-játékosokkal | Queue → accept → játék → kilépés → újra; cél-alapú navigáció (zászló, node), PvP-harc | 3 egymás utáni BG kézi beavatkozás nélkül | ⬜ |


---

## Összevetés egy külső bot feature-listájával (2026-10-26)

Ez egy **autonóm agent**, nem questelő bot: a közös AutonomousAgent / WorldModel / evidence / planner / skills /
verification architektúra minden területet (quest, harc, navigáció, gazdaság, később horgászat, dungeon) ugyanúgy
kezel. A questing ma a legfejlettebb terület, nem az egyetlen cél.

A felhasználó egy kereskedelmi pixel-bot feature-listáját adta át. Mindegyik pont be van sorolva: **átvesszük**
(új vagy meglévő lépcső), **átírjuk** (a cél jó, de mi máshogy érjük el), vagy **nem vesszük át** (okkal).

**Questingben jóval előrébb járunk** (felhasználó: „questingbe mi már jobbak vagyunk 100x”). Az ő questingjük
kész, kézzel írt 1-től maxig profilokból áll. A mi agentünk minden questet maga old meg, profil nélkül:
- a TDB + kliens-DB2 + élő szerver-adatok (Ymir) alapján;
- jármű-képességekkel a DB2-ből;
- scene-pályákkal, kredit-spell objektumokkal és kivárt NPC-beszéddel;
- többszintű navigációval, zóna-bejárással, skyridinggal és repüléssel;
- komplex questeknél a helyi LLM-értelmezővel.

Az ő listájukból a questinghez semmit nem kell átvenni. A haszon a körítésben van: pihenés, interrupt, vendor/javítás,
felszerelés, tréner, taxi, lift és temető.

### Átvesszük

| Terület | Pont a listából | Nálunk |
|---|---|---|
| Combat | pihenés a következő célpont előtt; menekülés alacsony HP-n | C7 |
| Combat | interrupt; immunis mobon a spell kihagyása | C8 |
| Combat | azonnali harc, ha megtámadnak | ✅ DEFEND, combat-dismount, landolás (10-26) |
| Combat | auto-facing | ✅ facing-javítás a combat skillben |
| Navigáció | lift/elevator | N7 (hajó és zeppelin is) |
| Navigáció | taxi | N8 |
| Navigáció | több temető | N9 |
| Navigáció | anti-stuck; akadálykerülés | ✅ N2, 🟡 N6 |
| Navigáció | feltámadás, corpse run | ✅ C3 |
| Inventory | auto vendor tele táskánál; javítás; több vendor zónánként | S5 |
| Inventory | jobb drop felvétele | S6 |
| Questing | spell-tréner | S7 |
| Grinding | grind, ha nincs quest | Q7 (csak a szintlépés-hézagra) |
| Monitoring | állapot-, útvonal-, célpont-nézet; telefonos követés | A6 |
| Profile | a játék keybindjeinek beolvasása | ✅ R1 bindings-cache |
| Fishing | addonos horgászat | F1–F3 (AB5 után) |
| Postaláda | multi mailbox | S8 (később) |
| Core | háttér-üzem, a PC közben használható; a játék tálcán is lehet | R5a, R5b |
| Battleground | teljes BG-ciklus, cél-alapú navigáció, PvP-harc (a szerveren botokkal) | P1 (AB5 után) |
| Dungeon | follower dungeon és dungeon bot-társakkal | D1, D2 (AB5 után) |
| Gazdaság | aukciósház | később (AB5 után), a postaládával együtt |

### Átírjuk (ugyanaz a cél, más út)

| Pont a listából | A mi irányunk |
|---|---|
| Kész quest/grind profilok 1-től maxig, JSON útvonalak, waypoint-rögzítés | Nincs kézi profil. A quest-logika a TDB + kliens-DB2 + élő szerver-adatok (Ymir) alapján dől el. Az útvonalat MMAP/Detour adja, a tapasztalatot a tanult útvonalak és akadályok (N6). |
| Profil-szkriptelés komplex questekhez, custom szkriptelt szekvenciák | Általános mechanizmusok (jármű-képességek DB2-ből, scene-pályák, kredit-spell objektumok), és a komplex questeknél a helyi LLM-értelmező. Nincs questenkénti szkript. |
| Osztályonkénti kézi rotációk, C# rotációszerkesztő, SimCraft-konverzió | Rotáció az actionbar + DB2 spell-katalógusból, tanult találat/miss alapján. Később Single-Button Assistant (C5). |
| Lootolás a csillogás képi felismerésével | Szerver-alapú loot: lootolható GUID → pontos x,y,z → F7 (server-first mód). |
| Addon-adatok: buffok, cooldownok | Harcban a cooldownok titkosak (az addon 0-t olvas). A saját castokat lokálisan követjük, a buffokat és a debuffokat az addon exportálja. |
| Pozíció 6 tizedessel pixelből | Pozíció pixelből és Ymir-csomagból; a szerver-pozíció és a spline az elsődleges. |
| Kattintásos (click-to-move) vagy WASD mozgás | WASD-irányítás visszacsatolással (hover, pitch, skyriding). Click-to-move nem kell. |
| JSON class-konfigok, mount-sebesség beállítás | Képesség-felismerés: mount/riding/skyriding az addonból és a DB2-ből (TravelModePolicy), kézi konfig nélkül. |
| Web UI (Blazor) | A meglévő GUI bővítése (A6); külön webes felület nem kell. |
| Konfigurálható célpont-listák | A célpontot a quest objective adja (TDB/DB2 kredit-lények); a grind (Q7) szint szerint választ. |

### Nem vesszük át

| Pont a listából | Ok |
|---|---|
| Emberi (Bezier) egérmozgás, anti-AFK mozgás, „2-PC mód a biztonságért”, nem HWID-kötött licenc | Felismerés-kerülés és termék-licencelés: a sandbox szerveren nincs célja, és nem része a projektnek. |
| Több bot-példány egyszerre, VM-futtatás | A projekt szabálya: csak a kiválasztott PID az autoritatív. Egy kliens, egy agent. |
| Herb, mining, skinning, kombinált gyűjtő profilok | Most félretéve (felhasználói döntés, 2026-10-12), nem elvi okból: az autonóm agent később ugyanazzal a világmodellel és skillekkel gyűjthet. |
| Profil-piactér | Nincsenek profiljaink, amiket cserélni lehetne. |
| Osztály-specifikus funkciók (hunter pet, ammo, warlock healthstone) | A karakter Warrior; ha más osztály jön, a C7/C8 általános mechanizmusai bővülnek. |
| Wowhead-linkek | Saját TDB/DB2 adatunk van; nem kell külső oldal. |
