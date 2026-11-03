# Párhuzamos, folyékony vezérlés: terv

Állapot 2026-10-15: **a közös gyors végrehajtási mag részben implementálva,
offline tesztelve; élő validáció még nincs.** Az alábbi új státusz az irányadó
az implementációról. A későbbi, 2026-10-13-as tervszakaszok megőrzött roadmapek:
az ottani sebességek, kliensviselkedési feltételezések és javasolt fázisok nem
tekinthetők jelenlegi mérésnek vagy elkészült funkciónak.

## 2026-10-15 este — Éles szenzorcsomagolás indulási hibája javítva (offline)

Az esti két felhasználói futásban a gyors szál **nem indult el**: a
`build_default_sensor()` egy `SensorHub`-ot adott vissza, amely nem továbbította
a belső `BufferedPixelSensor.peek_latest()` lehetőségét. A pumpa `start()` hívása
így `False`-t adott; a korábbi, közvetlen teszt-szenzoros ellenőrzés ezt nem fedte le.
Ez nem YOLO-/tracker-frekvenciahiba és nem élő párhuzamos validáció.

- A hub most a **saját elsődleges** producer nem fogyasztó pillanatképét adja át,
  eredeti fogadási idővel. Nem hív `poll()`-t, nem üríti a közepes kör
  átmeneti eseménysorát, nem frissíti újra a régi adat idejét. Elavult, jövőbeli,
  hibásnak jelölt vagy lezárt forrás nem engedélyez gyors inputot.
- A képesség külön ellenőrizhető (`supports_peek_latest`): egy csak `poll()`-t
  ismerő belső forrás nem tesz úgy, mintha gyors olvasást támogatna.
- `parallel_control.pump` mutatja a tényleges szálállapotot, aktivitást,
  szenzortípust és hibát. Sikertelen bekötésnél
  `sensor_without_peek_latest` jelenik meg, nem csak néma `enabled=False`.
  Ismételt indítás nem hoz létre második gyors szálat; a végső STOPPED fájl
  már kikapcsolt, leállított pumpát mutat.
- Regresszió: GDI/DXGI és külön capture-folyamatos gyári bekötés; tényleges
  `SensorHub → BufferedPixelSensor` láncon mozgás + pointer blokkolt közepes
  feldolgozás mellett; eredeti időbélyeg/átmenetek megőrzése; MANUAL indulás
  input nélkül; konfigurációs kikapcsolás; fókusz, vészleállítás, deadline,
  adathiány és lezárás. A két csomagolt-szenzoros reprodukció javítás előtt
  elbukott, a közvetlen teszt-szenzoros változat ugyanakkor átment.

Kapcsolódó offline kör: **303 passed**, exit 0. A felhasználó új GUI-folyamatot
indít és ő vezeti az élő tesztet. Ott külön ellenőrizendő a pumpa aktivitása,
`control_hz`/`pointer_hz`, `busy_skips`, együtt futó mozgás/hover, egyszeri
interakció, cast/combat/UI biztonság és STOP. Az ébresztési cél továbbra sem
bizonyított 60 Hz-es vezérlés vagy minden skill élő elfogadása.

## 2026-10-15 — Mi került ténylegesen a `projekt` munkapéldányba?

Későbbi, ugyanazon napi kiegészítés: a feltételes, többquestes feladatsor,
a TDB/SQLite alapú leadó- és folytatás-előtöltés, opcionális helyi LLM-sorrend
és a gyors mozgásbecslés is bekerült. Pontos aktuális hatókör:
`docs/QUEST_AGENDA_DESIGN.md`. A lenti első-fázis státusz és megőrzött roadmap
nem jelenti azt, hogy minden jövőbeli tervfázis elkészült volna.

- A `projekt_parallel` csak referencia; nem másoltuk rá a jelenlegi trackert,
  navigációt és javításokat. Egyetlen `ActiveSkillRuntime`, `NavigationService`,
  planner és `CommandDispatcher` maradt. A párhuzamosság kompatibilis
  tevékenységeket jelent egy aktív kísérleten belül, nem több egymást felülíró skillt.
- A `ParallelRuntimePump` önálló gyors szálon (60 Hz-es ébresztési cél) olvassa a
  sensor és a perception legfrissebb, nem fogyasztó pillanatképét. Nem épít
  képsort, nem üríti ki a közepes kör telemetria-postaládáját, és nem futtat
  adatbázisos felismerést. A tényleges vezérlési frekvenciát az új megfigyelések,
  végrehajtási idő és közös zárolás határozza meg; ez **nem 60 FPS-es ígéret**.
- A MOVE/FOLLOW/REACH mellett a meglévő VISUAL_APPROACH, SEEK_VISUAL_CUE, TARGET,
  INTERACT/TALK, COMBAT/DEFEND, LOOT, OBJECT_USE és USE_ON_TARGET állapotgépek
  is használják ezt az utat. INSPECT közben az egérkövetés gyors, az inspect
  eredményének ellenőrzése továbbra is a közepes kör feladata. A terminális
  eredmény egyszer, azonos action ID-val kerül vissza a közös könyvelésbe.
- Az aktív cél friss dobozát követő, gomb nélküli POINTER mehet a mozgás mellett.
  Helyre menet még nem azonosított, questtel összefüggő jelölt fölé is vihető
  az egér; ebből nem lesz automatikusan kattintás vagy bizonyított NPC-azonosság.
  A friss mouseover a rendes megfigyelési/azonosítási láncba kerül. Egy másik
  NPC GUID-jához nem másoljuk át a régi cél képpozícióját.
- A `ResourceArbiter` atomikus, rövid erőforrás-bérletekkel tartja távol az
  egérkövetést az interakciótól. A fizikai parancsok továbbra is az eredeti
  dispatcher/executoron mennek. A közepes kör nem lépteti újra ugyanazt az FSM-et
  egy régebbi képpel, ha azt a gyors kör frissen vezérli; a biztonság, explicit
  vizuális átadás és deadline ettől még elsőbbséget kap.
  A döntési óra az observation-összeállítás után frissül; az addon és a doboz
  eredeti mintavételi ideje ettől nem változik. Így az időközben dolgozó gyors
  kör után a közepes kör nem adhat régi vezérlési időt ugyanannak az FSM-nek.
- Cast/channel alatt a lábak és a fordulás leállnak; az egér követhet, a
  meglévő verifier figyelheti a castot és a creditet, de új kattintás/képesség
  nem indul. Modal UI, combat-preemption, esés, halál, fókuszvesztés,
  session/map/karakter- vagy perception-epoch váltás, elöregedett adat esetén
  leállás/átadás történik. A meglévő input-watchdog megmarad. Ismeretlen
  castidejű képességekről nem állítjuk, hogy menet közben biztonságosak.
- A `VisualRecognitionWorker` éles futásnál háttérben olvassa a meglévő vizuális
  memóriát (32 várakozó munka, egy másodperces cache, epochváltáskor eldobás).
  Ez tanácsadó jelöltlista, nem friss tooltip és nem target/GUID-bizonyíték.
  Közvetlen offline `step()` hívásoknál a régi szinkron út marad.

### Bekapcsolás, mérés és még nyitott részek

- Új GUI-folyamat szükséges. Éles `AgentRuntime.start()` esetén alapból aktív;
  visszakapcsolók: `AIPC_PARALLEL_CONTROL=0`, `AIPC_ASYNC_VISUAL_MEMORY=0`.
  Nincs automatikus FULL_AI-élesítés, PID- vagy bindingváltás. E munka során
  nem indítottunk FULL_AI-t és nem küldtünk inputot a játékba.
- Az állapot és a live-debug log `parallel_control.implementation` mezője
  `shared-fast-channels-v1`; külön látszik `control_hz`, `pointer_hz`, az
  erőforrás-tulajdonos, az action ID és a parancscsatorna. A
  `loop_rates.runtime_poll_hz` a lassabb runtime-poll, nem a gyors vezérlés;
  a régi `fast_control_hz` név kompatibilitásból megmarad.
- A felhasználó kérésére a 16:45-ös, töltő nélkül futtatott, alacsony FPS-es
  teszt **nem mérvadó teljesítmény- vagy viselkedési referencia**. Új, normál
  FPS-es, felhasználó által vezetett teszt kell: mozgás + követés egyazon
  kísérletben, friss hover utáni egyszeri interakció, cast alatti megállás,
  UI/combat/fókuszváltás biztonsága és STOP utáni nulla held key.
- A feladatsor első, feltételes változata elkészült (lásd a fenti kiegészítést).
  A skillek közti megállás nélküli útvonal-átadás,
  bizonyított instant-képességek menet közbeni aktiválása és az összes
  quest/vehicle/taxi ág élő elfogadása **nem készült el ettől**. A külön
  `target_approach_budget_exhausted` szabály és a hosszú takarásos ReID sem
  lett ebben a módosításban javítottnak nyilvánítva.

Offline bizonyíték: `tests/test_parallel_control.py` és a kapcsolódó runtime,
perception, input, M0/M1 és monitor-regressziók; összesítés:
`docs/LIVE_VALIDATION.md`. Ezek szimulált inputtal futnak, nem élő questek.

## Megőrzött 2026-10-13-as terv (nem implementációs/validációs státusz)

Felhasználói kérések, 2026-10-13:
- „mindennek kb. párhuzamosan kellene futnia, nem az, hogy egyszer futok, megállok, ráviszem az egeret, megint futok, megint megállok, megfordulok”;
- „teljesen folyékonyan kellene az egésznek mennie”;
- „minden skillnek párhuzamosan kellene működnie: megyek, nézelődök, quest-helyeket kérek le, következőnek ide meg oda megyek”.

A terv az AGENTS.md szerinti közös architektúrán belül marad: egy AutonomousAgent, egy WorldModel, egy planner, skillek és verification. Nincs külön „agy” feladatonként. Ami változik: a skillek nem egymás után, egyenként futnak, hanem **csatornák**ként egyszerre, közös erőforrás-elosztással.

---

## 0. A WoW szabályai, amelyekhez a tervnek igazodnia kell

Forrás: Blizzard és a közösségi wiki (lista a fejezet végén). Amit élőben még ellenőrizni kell, azt jelöli.

| szabály | következmény a tervre |
|---|---|
| **Egér:** a bal gombos húzás csak a kamerát forgatja; a jobb gombos húzás a karaktert (és a kamerát) fordítja; jobb gomb + A/D = oldalazás; két gomb együtt = előre futás. Húzás közben a kurzor nem mutat semmire. | Az egér **egy** erőforrás (`EGÉR`). Kamera-nézelődés és egy célon tartott kurzor nem mehet egyszerre, csak felváltva. |
| **Interact billentyű (soft target, Dragonflight óta):** az „Interact With Target” billentyű a kijelölés és kattintás nélkül szólítja meg a kiemelt NPC-t, illetve használja a kiemelt objektumot. Feltétel: hatótávon belül legyen, és **a karakter felé nézzen** (`SoftTargetInteractArc`: 0 = szembe, 1–2 = tágabb ív). A jelentési táv alapértéke `SoftTargetInteractRange` = 10. | **A legfontosabb változás:** gubónál és NPC-nél nem kell egérrel célozni. Oda kell menni, rá kell fordulni, majd **interact billentyű** (a projektben az F7 / INTERACTTARGET, addon soft_targets). Az egér csak azonosításra kell (tooltip), vagy tartalékként. Ezzel a „fordul el, az egér lemarad” hiba nagyrészt eltűnik. |
| **Click-to-Move** (`autoInteract`): jobb klikk egy távoli NPC-re vagy objektumra, és a karakter odamegy, majd közel érve interakcióba lép. Ki van kapcsolva: „túl messze” hiba. | Egy kliens-beállítás, amit a felhasználó engedélye nélkül nem kapcsolunk be (AGENTS.md: konfiguráció csak igazolt, kifejezett változtatással). Lehetséges tartalék, nem alap. |
| **Cast:** a nem-instant cast és a channel mozgásra megszakad; az instant mozgás közben is megy, de GCD-t indít. Mob is megszakíthatja vagy elkábíthatja a castot. Gyűjtésnél a mozgás megszakítja a castot. | Cast-os interakció és képesség csak álló lábbal. Az instant képességek mehetnek menet közben. A GCD alatt nincs új képesség. |
| **Helyben fordulás cast alatt:** a források nem rögzítik; általános tapasztalat, hogy nem szakítja meg. | **Élőben ellenőrizni.** Addig a cast alatt a fordulás is tiltott. |
| **Közelharc:** ~5 yd, és a cél felé kell nézni („facing the wrong way”). A Tab a nézési irányban lévő célt választja; a soft target enemy azt, ami a kamera közepén van. | A Harc-csatorna a facinget is kezeli (fordulás a célra), nem csak a távolságot. |
| **Mount:** NPC-hez és quest-objektumhoz általában le kell szállni (kivétel: speciális mountok); gyűjtésnél a kliens magától leszállíthat. | Az Interakció előtt leszállás (ha mounton van). |
| **Loot:** auto-loot; a loot-ablak bezárul, ha a karakter eltávolodik. | Loot alatt a lábak a holttest mellett maradnak. |
| **Interakciós táv:** a pontos NPC-, objektum- és loot-távot a források nem rögzítik; a soft-target jelentési táv 10 yd. | A tényleges távot a „túl messze” hibából és a soft-target megjelenéséből tanulja (ma is így van). |

Források:
- [Accessibility Updates in Dragonflight (Blizzard)](https://worldofwarcraft.blizzard.com/en-us/news/23876525/)
- [Dragonflight Accessibility Update (Warcraft Tavern)](https://warcrafttavern.com/wow/news/dragonflight-accessibility-update)
- [Interact with target – Icy Veins](https://www.icy-veins.com/forums/topic/68208-interact-with-target-accessibility-option-improved-with-targeting-in-dragonflight/)
- [Basic Movement and Combat (Blizzard)](https://worldofwarcraft.blizzard.com/en-us/news/20151231/welcome-to-world-of-warcraft-basic-movement-and-combat)
- [Mouse Right click move / Left click camera (Blizzard fórum)](https://us.forums.blizzard.com/en/wow/t/mouse-right-click-move-left-click-camera-look-not-working/688121)
- [Instant cast (Warcraft Wiki)](https://warcraft.wiki.gg/wiki/Instant_cast)
- [Spiritwalker's Grace (Warcraft Wiki)](https://warcraft.wiki.gg/wiki/Spiritwalker%27s_Grace)
- [CVar autoInteract (Warcraft Wiki)](https://warcraft.wiki.gg/wiki/CVar_autoInteract)
- [TurnOrActionStop (wowprogramming)](https://wowprogramming.com/docs/api/TurnOrActionStop.html)
- [CheckInteractDistance (Warcraft Wiki)](https://warcraft.wiki.gg/wiki/API_CheckInteractDistance)
- [Dead zone (Warcraft Wiki)](https://warcraft.wiki.gg/wiki/Dead_zone)
- [Soft target mode (Blizzard Watch)](https://blizzardwatch.com/2022/08/25/soft-target-mode/)
- [How can you interact while mounted (Blizzard fórum)](https://us.forums.blizzard.com/en/wow/t/how-can-you-interact-while-mounted-in-shadowlands/785858)

---

## 1. Miért szaggatott most

| ok | hol | hatás |
|---|---|---|
| Egyszerre egy skill (`agent.pending`) | engine / runtime | minden skill végén terminális eredmény, majd 1–2 Hz-es újratervezés: a karakter vár |
| A gyors kör csak mozgás-skillt léptet | `fast_movement_lane.advance_fast_movement` | nézelődés, egér, interakció csak a lassú körben |
| HOVER / CLICK megállít | `executor.execute`: `stop_movement()` + `_release()` | minden egérmozdulat és kattintás előtt megáll a karakter |
| Fordulás közben az egér a régi helyen marad | HOVER egyszeri pozícióra | „elfordul, megint nincs ott semmi” |
| Nincs következő cél előre | planner a cél elérése *után* választ | érkezéskor megáll, újratervez, elindul |
| Keresés = megállás + körbeforgás | SEEK / INSPECT / OPEN_MAP | a karakter áll, a kamera forog, vagy nyitva a térkép |

Élő példák (2026-10-13): 18:24 első gubó (fordul el / egér késik / 360°-os keresés), 18:09 pötty-ciklus
(45 s állás), 17:22 (40 s WAIT a gubó előtt).

---

## 2. Célkép: egy ember így játszik

- **Megy** a következő helyre (a navmeshen, kanyarodva, megállás nélkül).
- Közben **nézelődik**: a kamera kicsit körbenéz, az egér rámegy az érdekes dolgokra (tooltip), de ettől nem fordul el és nem áll meg.
- Közben **tudja, hová megy utána**: a quest-helyek, pöttyök és TDB-pontok alapján már megvan a következő 2–3 cél.
- Ha útközben **meglát** valamit, ami kell (gubó, quest-NPC, mob), menet közben rácélez, odamegy, használja vagy megszólítja, aztán megy tovább.
- **Harc**: közben is mozoghat, és a harc végén a mozgás folytatódik, nem kezdődik elölről.

---

## 3. Architektúra: erőforrások, csatornák, napirend

### 3.1 Erőforrások (amiből egyszerre csak egy tulajdonos lehet)

| erőforrás | mi az | példa-tulajdonos |
|---|---|---|
| `LEGS` | előre/hátra/oldalazás (W/S/Q/E) | Mozgás |
| `BODY_YAW` | karakter fordítása (A/D billentyű) | Mozgás, vagy Interakció/Harc a célra fordulásnál |
| `EGÉR` | **egy** fizikai eszköz: mutató helye, bal/jobb kattintás, bal gombos kamerahúzás, jobb gombos fordítás | felváltva: Figyelem (hover vagy kamera-nézés) vagy Interakció (tartalék jobb klikk) |
| `ACTION_KEYS` | képességek, **interact billentyű** (F7 / INTERACTTARGET), ugrás | Interakció, Harc |
| `UI` | térkép, dialógusablakok | Quest-dialógus, vásárlás (kizárólagos) |

Az **erőforrás-elosztó (ResourceArbiter)** rövid lejáratú bérleteket (lease) ad ki erőforrásonként, prioritás
szerint: biztonság > harc > interakció > mozgás > figyelem. Elvétel **nem állítja le** a többi erőforrást.
Ha például az Interakció elkéri az `EGÉR`-et, a Figyelem elengedi, de a `LEGS` a Mozgásnál marad, és a
karakter megy tovább. A kamera-nézelődés és a hover ugyanazt az `EGÉR`-et használja, ezért időben váltják egymást.

Az executor ma kétféle bérletet ismer: mozgás (InputScheduler + watchdog) és egyszeri parancs. Ezt kell
erőforrásonkéntire bővíteni. A `POINTER` és a `CAMERA` (bal húzás) már ma is futhat mozgás közben; a `CLICK`
viszont nem, ehhez új, nem-blokkoló kattintás kell.

### 3.2 Csatornák (mind a gyors körben fut, 20–40 Hz, egyszerre)

1. **Mozgás:** követi az aktuális úti célt (navmesh-útvonal, szakadék-védelem).
   - **Előre tudja a következőt:** amikor az aktuális célhoz ~8 yd-ra ér, már a következő felé kanyarodik. Nem áll meg, nem vár újratervezésre.
   - Megáll, ha a tervező azt kéri, vagy ha a biztonsági réteg leállítja.
2. **Figyelem (tekintet + egér):** menet közben
   - a kamerával kis szögben körbenéz (bal húzás, a karakter nem fordul), a menetirány ±60°-ában;
   - a legértékesebb látott jelölt fölé viszi az egeret, és tooltipet olvas (quest-objektum, „!”/„?” NPC, mob);
   - **fordulás-kompenzációt** használ: a karakter elfordulásakor az egér azonnal a jelölt *új* képpozíciójára ugrik.

   Az eredményt eseményként adja a WorldModelnek („gubó látható itt”, „a kurzor alatti NPC: Alaria, !”). Nem áll meg, nem forgat körbe.
3. **Interakció:** ha a tervező kijelölt egy célt (gubó, NPC, holttest), akkor
   - a Mozgás odaviszi, az Interakció pedig a `BODY_YAW`-val **a célra fordítja a karaktert** (soft-target feltétel: szembe nézni);
   - amikor az addon jelzi, hogy a soft-target interact célpont **a kijelölt cél** (GUID / objektum-azonosító / név egyezik), és hatótávon belül van, akkor **interact billentyű** (F7). Egérrel célozni nem kell; a fordulás miatti egér-lemaradás így nem számít;
   - az egér csak azonosításra kell (tooltip, ha a soft-target nem ad elég adatot), illetve tartalékként jobb klikkre, ha nincs soft-target;
   - utána visszaadja az erőforrásokat, és jelenti az eredményt.

   Közben a Mozgás odaviszi (a cél pontja lesz az aktuális úti cél).

   **Cast-os interakció** (felhasználó: „az interact meg az object use nem feltétlen működik futás közben, ha castolni kell”).
   A gubó kinyitása, gyűjtés, sok objektum-használat cast; mozgás közben nem indul el, vagy megszakad.
   - Odaérés menet közben. A kattintás előtti ütemben az Interakció elkéri a `LEGS`-et (W elenged), és **csak a cast idejére** áll meg.
   - Cast alatt (addon `is_casting`): nincs W/S/oldalazás/ugrás. Helyben fordulás, kamera-húzás és egérmozgatás szabad, ezek nem szakítják meg a castot.
   - Közben a tervező már a következő célt készíti elő.
   - A cast végén vagy a creditnél a `LEGS` azonnal vissza a Mozgáshoz.
   - Cast nélküli interakció (NPC megszólítás, loot, egyszerű objektum) menet közben vagy minimális lassítással.
   - Hogy egy célnál van-e cast, azt a tervező tanulja és tárolja (első használatkor `is_casting` és a cast hossza); addig óvatosan cast-osnak veszi.
4. **Harc:** célpont és képességek (`ACTION_KEYS`, `BUTTONS`), közben mozoghat (közelít, követ). A végén a Mozgás onnan folytatja, ahol tartott.
5. **Biztonság** (mindig a legmagasabb prioritás): esés, szakadék, halál, töltés, fókuszvesztés, F12 esetén minden bérletet azonnal visszavon.

### 3.3 Napirend (a tervező új szerepe, lassú kör, 1–2 Hz, háttérben)

A tervező nem lépésenként dönt („most MOVE, most SEEK”), hanem egy **napirendet** tart karban, és csak akkor
módosítja, ha új bizonyíték jön:
- **Úti célok sora:** a következő 2–3 hely, sorrendben. Például Hrun gödrében: TDB-gubók a spirál sorrendjében, közbe a felbukkanó sárga pöttyök, majd a leadó NPC.
- **Aktív célpont** (ha van): melyik gubó / NPC / mob, milyen azonosítással (tooltip, object_id, guid).
- **Mire figyeljen a Figyelem:** milyen dolgok érdekesek (quest-objektum, „!”, egy bizonyos NPC neve).
- **Quest-helyek lekérése** folyamatosan, a háttérben: addon API-pinek, TDB, tanult memória, minimap-pöttyök. **Térképet nem nyit** menet közben; a nyitott térkép a karaktert is megállítja (UI), ezért csak végső tartalék, álló helyzetben.

A csatornák eseményeket küldenek (credit, látott cél, elért pont, hiba). A tervező ezekből frissíti a
napirendet, és a csatornák a frissített napirenddel **megszakítás nélkül** folytatják.

### 3.4 Ellenőrzés (verification) aszinkron

A mai „skill → ellenőrzés → következő skill” helyett minden csatorna saját, folyamatos ellenőrzéssel dolgozik:
- **Mozgás:** halad-e, beragadt-e (a meglévő progress / stuck logika);
- **Interakció:** jött-e credit, „túl messze”, „nincs rálátás”, cast fut-e;
- **Figyelem:** friss-e a minta, egyezik-e a tooltip.

A hibák **nem állítják meg az egészet**. Csak az érintett csatorna reagál (pl. „túl messze”: az Interakció
közelebb kéri a célt, a Mozgás megy tovább).

---

## 4. Példa: Hrun gödre, folyékonyan

1. A napirend: [8000022 z60, 8000025 z33, 8000023 z17, 8000026 z−1, 8000024 z−6] a spirál sorrendjében.
2. A Mozgás indul a spirálon lefelé. A Figyelem közben ±60°-ban nézelődik és tooltipet olvas.
3. A Figyelem meglátja a gubót (doboz + „Thick Cocoon” tooltip). A tervező kijelöli aktív célpontnak, a Mozgás úti célja a gubó TDB-pontja (4 yd).
4. A karakter fut felé, az Interakció ráfordítja. Amint a soft-target a gubó (és hatótávon belül van),
   elengedi a W-t, és megnyomja az interact billentyűt (F7). A kinyitás castja alatt áll; közben az egér és a
   kamera szabad, a tervező már a 8000025-öt célozza.
5. Credit: a napirend lépteti a sort. A Mozgás már a 8000025 felé kanyarodik, közben a Figyelem nézelődik tovább.
6. Pók támad: a Harc kiszolgálja, közben a Mozgás csak annyit enged, amennyit a harc kér. Harc után megy tovább a 8000025 felé, nem újratervez a semmiből.
7. Sárga pötty jelenik meg: a tervező beszúrja a napirendbe a következő helyre, ha közelebb van.

### 4.1 Quest-lánc egy napirendben (felhasználó: „itt a questet csinálom meg, utána leadom, amoda megyek, a questet felveszem”)

A napirend nem áll meg a quest végén. Előre tartalmazza a teljes láncot:

1. Az aktuális quest objektívái (pl. a gubók a spirál sorrendjében).
2. A **leadás**: a leadó NPC helye (TDB-ender, tanult memória, API-pin). Már akkor a sor végén van, amikor az utolsó objektíva még folyik.
3. A **következő felvevő**: a leadás után elérhető quest(ek) „!” helye (API quest-line pinek, TDB-starter). Ha a leadó maga adja a folytatást, ugyanott marad (follow-up).
4. A felvétel után az új quest objektívái kerülnek a sor elejére.

Az utolsó credit pillanatában a Mozgás már a leadó felé kanyarodik. A leadó ablakának bezárása után már a
következő felvevő felé indul, nem áll meg, és nem nyit térképet. A közeli, egymás melletti questeket
(felvétel, objektívák, leadás) a napirend összevonja, ahogy a 10-11-es kötegelés is (220 yd-on belül).

---

## 5. Megvalósítás fázisokban

Minden fázisnak külön visszajátszó tesztje van a rögzített élő futásokból, és külön élő kapuja. Minden fázis
kapcsolóval (`ai_decision.json`) kikapcsolható; kikapcsolva a mai működés marad.

| fázis | tartalom | elfogadás |
|---|---|---|
| A | **ResourceArbiter + executor bérletek** erőforrásonként; nem-blokkoló kattintás; a HOVER mozgás közben POINTER-ként fut (minta-frissesség ellenőrzéssel, nem megállással) | input-diagnosztika: kattintás és egérmozgatás alatt a W tartva; meglévő tesztek zöldek |
| B | **Mozgás-csatorna + úti célok sora**: érkezés előtt a következő célra kanyarodik, nincs WAIT/újratervezés-szünet | visszajátszás: 18:24-es és 10-07-es futás útvonala megállás nélkül; élő: bejárás megállás nélkül |
| C | **Figyelem-csatorna**: menet közbeni kamera-nézelődés + egér a jelöltön + fordulás-kompenzáció; a SEEK/INSPECT megállós keresés tartalékká válik | visszajátszás: a gubó-doboz fordulás közben is az egér alatt (< 0.03 képernyő hiba) |
| D | **Interakció-csatorna**: gubó (objektum) először, menet közbeni jobb klikk | élő: ≥ 3 gubó, 0 esés, nincs „elfordul” ciklus |
| E | Interakció NPC-kre (megszólítás, quest-dialógus), holttest-loot | élő: felvétel/leadás megállás nélkül odaérkezve |
| F | **Harc-csatorna** a párhuzamos modellben (mozgás + képességek) | élő: harc után a bejárás folytatódik |
| G | **Napirend-alapú tervező**: a skill-lánc helyett célok sora + aktív célpont + figyelem-lista; háttérben quest-hely lekérés | élő: quest-sor (felvétel → objektívák → leadás) megállások nélkül |

---

## 6. Mi marad, mi változik a kódban

- **Marad:** WorldModel, perception (World3D, minimap, addon), NavigationService, Z resolver, szakadék-védelem, quest-modell, TDB és memória, verification-logika (átrendezve), biztonsági megszakítások, F12.
- **Bővül:**
  - executor: erőforrás-bérletek, nem-blokkoló kattintás;
  - gyors kör: a mozgás mellett minden csatornát léptet;
  - planner: napirend.
- **Tartalékká válik:** a lépésenkénti skill-láncok (SEEK → INSPECT → TARGET → INTERACT, SEEK → OBJECT_USE), kapcsolóval.

## 7. Kockázatok

- **WoW-kliens viselkedése:** jobb klikk és kamera-húzás menet közben. A jobb gomb nyomva tartása a karaktert fordítja, ezért csak rövid kattintás lehet. Élőben igazolni kell; a tartalék egy ~120 ms-os W-elengedés.
- **Érzékelési késés:** a World3D ~15 Hz-en fut, kb. 100 ms-os késéssel. A fordulás-kompenzáció és a ~1,5 s-os „coasting” fedezi.
- **Komplexitás:** sok csatorna egyszerre nehezebben debugolható. Ezért kell minden ütemben csatornánként rövid diagnosztika a live-debug logba (ki birtokol mit, mi a cél, miért nem kattintott).
- **Átállás:** fázisonként, kapcsolóval, hogy egy rossz fázis ne rontsa el a többit.
