# Bug fixes és implementációk

Az Astra 6 által végzett fejlesztések: az élő tesztek (Exile's Reach, Alliance, Warrior)
során talált hibák, a javításaik és az új funkciók, naponként, 2026-09-24-től, amikor az első
YOLO modell bekerült az agentbe.
A részletes napló (okok, logok, tesztek, korábbi előzmények):
[`docs/LIVE_VALIDATION.md`](docs/LIVE_VALIDATION.md). A README „Változások” blokkja ebből
a fájlból készül (`python tools/readme_changes.py`).

**Jelölés:** ✅ élesben igazolva · 🧪 kész és offline tesztelve, élő megerősítés még nincs

---

## 2026-10-11

### Új funkciók / implementációk
- 🧪 **TDB telepítési útmutató és konverter** (`docs/TDB_SETUP.md`, `tools/convert_tdb_mysql_to_sqlite.py`): az
  adatbázis 655 MB, nem fér a repóba; a hivatalos TrinityCore TDB 1210.26091 kiadásból bárki elkészítheti.
  A konverter az SQL-t nem futtatja, csak az értékeket tölti SQLite-ba.

### Bug fixes
- 🧪 **#35: NPC-ablak nyitása/zárása nullázta a teljes látást** (élő 2026-10-11: kb. 40 reset 20 perc alatt, minden
  quest-/gossip-ablaknál és térképnél). Minden reset után az NPC-k új track-azonosítóval tértek vissza (pl. Jaina
  minden megszólítás után), a dobozok későn álltak vissza. A quest-/gossip-ablak már nem számít jelenetváltásnak:
  a látás alatta megtartja a trackeket, bezárás után ugyanazzal az azonosítóval folytatja. A térkép továbbra is reset.
- 🧪 **Richterhez lassan jutott oda: hamis „túl messze”, aztán sétált a nyitott bolt mellett** (élő 15:50:51–15:52).
  - Az addon a „túl messze” hibaüzenetet még 3 s-ig küldi. A 15:51:14-es, valójában sikeres megszólítást (a bolt
    megnyílt) az előző próbálkozás régi hibája miatt `out_of_range`-nek könyvelte, és közelítésbe, majd térképbe
    kezdett a nyitott bolt mellett. Most csak az adott próbálkozás alatt keletkezett hiba számít, és a megnyílt bolt
    előbb dönt.
  - 15:50:53–15:51:03 között 11 s-ig állt: Jaina ki volt jelölve, de egyik feladathoz sem kellett, a keresés pedig
    „nincs target”-re várt. Ha semmi más lépés nincs, egy ilyen kijelölt barátságos NPC most nem akasztja meg a keresést.
- 🧪 **Nyitott kereskedőablak mellett is kamerázott/sétált** (élő 15:51–15:52, Stocking Up on Supplies).
  Egy eladás és egy vásárlás 64 s-ig tartott. Közben egy távoli UNKNOWN felé induló SEEK (87) megelőzte a
  vásárlást (86); amikor a vendoradat 2 s-nál régebbi volt, a vásárlás/eladás nem is volt elérhető, és ilyenkor
  is a SEEK nyert. Most ha a kereskedő nyitva van, és van még vásárlás/eladás feladat, csak a kereskedési lépések
  (és a harci önvédelem) maradnak; friss vendoradatra rövid WAIT-tel vár.
- 🧪 **Leadás után és leadóhoz menet azonnal térképet nyitott, ami a quest-ablakot is bezárta** (élő 15:36:59,
  15:54:29, 15:56:56; felhasználó: „van, hogy emiatt záródik be a quest UI”, Stocking Up on Supplies).
  - A térkép nem nyílik meg, ha egy aktív questnek ismert a helye. 15:54:29-kor a 58914 leadóhelye ismert volt,
    csak a MOVE volt pillanatnyilag tiltva, és 1 s múlva be is zárta („Leadási hely ismert”).
  - Leadás vagy felvétel után legfeljebb 6 s-ig kivárja a következő teljes állapotot, ami az új quest-felvevő
    helyeket hozza, mielőtt térképet nyitna.
  - Nyitott quest-, gossip- vagy kereskedőablak fölött soha nem nyit térképet.
- 🧪 **A kijelölt leadó NPC mellett 25 s-ig cellákat járt** (élő 15:46, Jaina, 56034). A leadóhely körüli
  keresés (70 + megbízhatósági bónusz) megelőzte a kijelölt Jaina megszólítását (70). Ha a kijelölt barátságos
  NPC egy kész quest valószínű leadója, a megszólítás most 92-es prioritású.
- 🧪 **Járműben (Giant Boar) térképet nyitott** (élő 15:47, 15:48): járműben a térkép nem nyílik meg.
- Nem hiba: a 15:54:32-es UI_UNKNOWN megállás a felhasználó ESC-jére feljött játékmenü volt; a biztonsági
  leállás helyesen működött.
- 🧪 **Hjalmarnál leadta a questet, de a következőt nem vette fel, hanem elment** (élő 15:54).
  A leadás után az ablak bezárult, és egy pillanattal korábban választott „Leadási hely” MOVE a már leadott
  questtel még 35 s-ig vitte el. Javítás:
  - a leadási MOVE leáll, amint a quest kikerül a naplóból;
  - leadás után ugyanazt az NPC-t még egyszer megszólítja, 20 s-on belül, mert a folytatást általában ő adja.
    Ha magától felkínálja, nem szól újra.
  - Ha egy NPC-ablak 6 s után is üres (nincs gomb, se quest-sor), ESC-vel bezárja (új CLOSE_DIALOG lépés);
    a gombot csak akkor nyomja meg, ha az ablak még nyitva van. Eddig ilyenkor örökké várt volna.
- 🧪 **Lement a bányába, mielőtt a bánya előtti törpénél (Bjorn) leadta volna a questet** (élő 15:56–15:59).
  A 55965 leadója a TDB-ben a bánya bejárata fölött áll (z 94.8); alatta ugyanazon az x/y-on a barlang van.
  A tanult leadóhely magasság nélkül volt mentve, így az útvonal a barlang szintjére ment. Most a tanult hely
  a mellette lévő TDB-spawn magasságát kapja.
- 🧪 **Re-Sizer a Wandering Boarokon: nagyon döcögős** (élő 15:39–15:45). A quest kb. 6 percig tartott, az
  utolsó malacot a felhasználó csinálta meg. Három ok:
  1. A zóna-bejárás a malacoknál nem állt meg, mert az objective `USE_ITEM`, és csak a KILL/COLLECT típusoknál
     álltunk meg élőlényért. Most minden objective-nál megáll, ahol tárgyat kell nevesített lényen használni.
  2. Messziről nyomta az Interact gombot (`out_of_range`). Most ha a kijelölt malac a becsült helye szerint
     7 yd-nél messzebb van, vagy a doboza a képen még kicsi, előbb odamegy.
  3. A sikeres használatot is hibának könyvelte (`identity_uncertain`): a malac „Re-sized Boar”-rá változik,
     a target lecserélődik, a quest-előrelépés csak utána jön. Most előbb az előrelépést nézi, és cast után
     a határidőig kivárja.
  4. A TDB-ből nem kapta meg a malacok helyét: az objective egy láthatatlan kill-credit lényre mutat (156722),
     aminek nincs spawnja. Most ilyenkor az objective szövegében megnevezett lényt (Wandering Boar, 29 spawn)
     keresi meg a TDB-ben, csak helyként; az azonosítás továbbra is tooltipből megy.
- 🧪 **Két szomszédos quest: az egyiket leadta, aztán visszajött a másikért** (élő 15:11–15:16, 55184/55186).
  Grek'og megölése után (55186 kész) a 55184 még 3/7 volt, ugyanott. Két hiba vitte el leadni:
  1. Egy minimap fel/le nyilat (valószínűleg a kész quest leadási „?”-je a dombon) a nyitott 55184 céljának vett,
     és elindult felé. A nyíl most a kész quest POI-jához tartozik, ha az közelebb van.
  2. Így 121 yd-re került a 55184 POI-középpontjától, és a halasztás (120 yd) megszűnt.
     A már várakozó leadás most addig vár, amíg a nyitott quest területe 220 yd-en belül van.
- 🧪 **Ugrás után leállt a MOVE, és nem tervezett új utat** (élő 15:15:39, a felhasználó szóközt nyomott).
  Lejtőn futva vagy ugrás közben a „zuhanás” jel 1–1,9 s-ig is tartott, és az ismételt FAST csomagok miatt
  a mért idő akkor is nőtt, amikor nem jött új minta. A 8 yd-es veszélyzóna ott maradt, ahol a karakter állt,
  így minden új útvonalat már az indulásnál `fall_hazard_on_route`-tal eldobott.
  Javítás:
  - a zuhanást az addon mintaidején mérjük, és 2 s alatt nem bukik el a MOVE;
  - egy veszélyzóna nem blokkol, ha a karakter ugyanazon a szinten még benne áll (akkor nem volt esés);
  - valódi esés után a karakter alsóbb szinten van, ott a régi szabály marad.
- 🧪 **Két quest egy ablakban: nem vette fel egyiket sem** (élő 14:53, Austin Huxworth a Northbound leadása után).
  Az addon a teljes STATE csomagban elküldte mindkét quest sorát. A Python viszont a frissebb FAST csomag kis
  `quest_ui`-jával (nyitva / gomb / pont, sorok nélkül) egészében felülírta, így az agent üres listát látott,
  és az ablak előtt várt. Ugyanez elvihette a jutalomválasztás sorait is.
  Javítás: a FAST csak a saját mezőit írja felül, a sorok és jutalmak a teljes állapotból maradnak; ha a FAST
  szerint az ablak bezárult, a sorok törlődnek. Valószínűleg a 10-08-as Hjalmar-esetben is ez okozta az üres
  `entries` listát.
- 🧪 **Leadás felé menet egy sündisznót kezdett „lesni”** (élő 14:52–14:53): a leadóhely 155 yd-re volt, de
  a sündisznó doboza fölött egy általános „szimbólumszerű” doboz ült. A leadási út ezt bárhol quest-jelnek
  vette, és kb. tízszer megszakította a sétát (SEEK/INSPECT). Most egy ilyen gyenge jel csak a leadóhely 40 yd-es
  körzetében szakít meg. Valódi „?”/„!” quest-jel (quest_marker/badge) továbbra is bárhol megszakíthat.
- 🧪 **Northbound felvétele után nem indult el a leadáshoz** (élő 14:25, `live-debug-20261011-142018`). A leadási
  MOVE kétszer elbukott: előbb `fall_hazard_on_route`, aztán `fall_in_progress`, utána csak INSPECT/WAIT a teszt
  végéig. Az ok: a táborban minden apró párkány- vagy lejtőlelépés `falling` mintát adott (0–1 s-os
  FALL_STARTED/ENDED párok). A navigáció az első ilyen mintára elbuktatta a MOVE-ot, és 8 yd-et 10 percre
  „zuhanásveszélyesnek” jelölt. Így a tábor útjai sorra letiltódtak, a leadóhoz vezetőé is.
  Javítás: egy `falling` minta csak szünetelteti a kormányzást. A MOVE akkor bukik el és akkor lesz veszélyzóna,
  ha a zuhanás 1 s-nál tovább tart (egy ugrásnál hosszabb, kb. 9–10 yd esés); a veszélyzóna ekkor a párkánynál
  van, nem a landolásnál. Rövidebb valódi esést továbbra is a navmesh-szintváltás ellenőrzés igazol landoláskor.

## 2026-10-10

### Új funkciók / implementációk
- 🧪 **A külön munkapéldány beolvasztva** (`uj-mappa-2026-09-28-1918`: GitHub-alap + barlangos javítások + két
  pixelcsík + TDB-bekötés). Mentés: `projekt_backup_20261008_pre_chatgpt_merge`, `projekt_backup_20261010_pre_tdb_sync`.
  A felhasználó ezentúl a `projekt` mappából futtat.
- 🧪 **TDB mint világmemória, ami tanul** (felhasználó: „memóriaként, tudja mi hol van és a jövőben is mentse”).
  A szerver ezt a TDB-t futtatja, ezért a TDB az elsődleges statikus tudás. Amit az agent élőben igazol
  (beszélgetés, quest felvétele/leadása, ölés, loot, tárgyhasználat), azt a TDB formájában elmenti
  (`learned_spawn`, `learned_quest_role` az `entity_memory.sqlite3`-ban, világszintű, nem jár le), és a TDB mellé
  olvassa vissza: a közeli élő sor megerősíti a TDB-spawnt, a hiányt kitölti. A régi quest-creature memória
  (147 sor) első induláskor beolvad. Valódi TDB-vel: a 55639, 58914, 55988 leadója (a TDB-ben nincs) most megvan,
  hellyel együtt.

### Bug fixes
- 🧪 **A látás 10-07 óta lassabb (World3D ~42 → ~32 Hz), túlfutás NPC-n, sok sikertelen INSPECT, SEEK körbe-körbe.**
  Két ok, mindkettő a 0.9.61/62-es két-sávos csíkból:
  - a STATE-sáv a képernyő teljes tetején futott (~1800 px széles, 116 px magas), ezért a detektor elől a teljes
    felső sávot kitakarta — közelről az NPC feje és a „!”/„?” pont ott van, a doboz nem nőhetett felfelé, a
    megállási méret sosem jött el;
  - a sávok minden 1/60 mp-es tickben minden cellát újrarajzoltak (~10 ezer Lua-hívás), ez a kliens FPS-ét és vele
    a capture-t vitte le (0.9.59/60: 39–44 Hz, 0.9.61+: 31–35 Hz azonos ablakméretnél).
  → **Addon 0.9.63:** a STATE-sáv 128×33 cella (512×132 px, a régi csík helye a bal felső sarokban, ugyanaz az
  1024 bájtos lap), a maszk ismét csak ezt a szigetet takarja; csak a megváltozott bájtok cellái rajzolódnak újra
  (szimulációban 2,4× kevesebb munka tickenként).
- 🧪 **Kijelölt, de a képen nem látható célpont: odamegy a minimap-jeléhez** (felhasználó 2026-10-11). A kijelölt
  egység minimap-jeléből számolt világpontra (`MINIMAP_TARGET_MARKER`) navmesh-MOVE indul: barátságos célpontnál
  10 yd felett (megállás 4,5 yd), quest-ellenségnél harcon kívül 8 yd felett (megállás 6 yd, utána COMBAT/Charge).
  Ha az egység megjelenik a képen vagy másik célpont lesz kijelölve, a MOVE megszakad. Eddig ilyenkor csak
  elfordult/körbenézett, ellenségnél semmi sem jött.
- 🧪 **Tanult TDB: `tdb_learned.sqlite3`** (felhasználó: „ugyanúgy, ahogy a TDB-ben van”). A tanult adat a profil
  mappájában egy második TDB-fájlba kerül, pontosan a TDB tábláival és oszlopaival (`creature`, `gameobject`,
  `creature_queststarter/-ender`, `quest_poi`, `quest_poi_points`); jelölés `VerifiedBuild = -1`, guid
  9 000 000 000-tól, a „hányszor/mikor/honnan/név” adat a `learned_row` táblában. Az eredeti TDB érintetlen marad
  (SQLite ATTACH-csal együtt olvasható). A korábbi tanult sorok első induláskor átköltöznek. A creature/gameobject
  sorokat **nem szabad** a szerver adatbázisába importálni (meglévő NPC-k helyei — duplán spawnolnának).
- 🧪 **Hiányzó quest-POI pótlása a látásból** (felhasználó: „bele lehet írni a sokszöget, ha hiányos? A kék zónát
  visionből?”): ha a minimap kék quest-területe egyszer zártan látszott, a cellák konvex burka quest_poi/
  quest_poi_points sokszögként a tanult TDB-be kerül (csak nőhet), és a zóna-bejárás ezt használja, ha a TDB-ben
  nincs sokszög.
- 🧪 **Cooking Meat: a zónában egy perc WAIT** (2026-10-11 13:36): az egyetlen másik javaslat, egy MOVE az API-ponthoz,
  később leesés-veszély miatt blokkolódott, a zóna-mód pedig „van teendő”-nek vette. → A zónán belül egy MOVE nem
  gátolja a bejárást, a prioritás dönt; a zóna-mód csak TDB/tanult sokszögnél aktív.
- 🧪 **Quest-zóna bejárás újratervezve** (felhasználóval egyeztetve). Célkeresési lépcső a zónában: (1) ami kéznél
  van (quest-releváns egység/objektum az egér alatt, kijelölve, a képen); (2) sárga minimap-pötty — **pötty-memória**:
  minden látott pöttyöt megjegyez (3 perc), elfordult kamera után is odamegy; ami a minimap látóterében, a nyíl alatt
  kívül eltűnt, az elhasznált; (3) TDB-spawn — a minimapon belüli, pötty nélküli spawn kimarad (elhasznált/nincs ott),
  a minimapon kívüli cél marad; (4) a TDB quest-POI sokszög bejárása: **kígyózó, 25 yd-os cellák**, a széltől 3 yd-ra
  beljebb, spawnsűrűség szerinti enyhe súly, 10 yd-on belül számít bejártnak, megszakítás után onnan folytatja.
  A bejárás **azonnal indul**, ha a zónában semmi nincs kéznél (eddig 4 helyben pörgés után); séta közben **2,5
  mp-enként balra/jobbra pillant** a kamera (új CAMERA_GLANCE: bal gombos húzás, ami nem engedi el az előre-gombot,
  a követő kamera magától visszaáll). **Csak quest-releváns dolog szakítja meg**: quest-objektum körvonal, quest-jel,
  lény, ha az objektíva lényt kér; a helyben pörgő keresés és a tetszőleges dobozok megközelítése a zónában kimarad.
- 🧪 **Kijelölt Kee-La mellett WAIT-en ragadt** (17:48–17:49): egy 1 mp-es OPEN_MAP letakarta a bal felső
  STATE-csíkot; a dekóder elfelejtette a helyét, és utána csak a jobb oldali FAST-sávot olvasta — a teljes állapot
  40+ mp-es lett, a tárgyhasználat (2 mp-nél frissebb állapotot kér) le volt tiltva. → A dekóder megjegyzi a csík
  utolsó helyét, minden FAST-only képkockán ellenőrzi (olcsó fejléc-próba), és ~2 mp-enként teljes keresést is
  futtat; ha a csík visszajön, azonnal újra olvassa (teszt: letakarás → csak FAST → feltakarás → mindkét sáv).
- 🧪 **Emergency First Aid „csak bohóckodott”** (17:36–17:38, fél perces quest): kijelölt Austin Huxworth mellett
  sem használta a First Aid Kitet. Három ok: (1) a munkapéldány TDB-patch-e az objektíva-MOVE-ot 96-os prioritásra emelte,
  ez minden helyi lépést (tárgyhasználat, TARGET, harc) legyőzött; (2) barátságos célpontra ASSIST ment, ami csak
  akciósávos tárgyat tud elsütni, a quest special item interact gombos; (3) a „First Aid Kit used on Austin”
  objektíva földi objektum-keresést indított („Quest-object terület elérve: UNKNOWN cue”). → A TDB-MOVE csak akkor
  96-os, ha nincs kéznél helyi munka; barátságos célponton interact-gombos USE_ON_TARGET; a „used on <NPC>”
  objektíva nem objektum-keresés. Ugyanez a 96-os MOVE szakította meg a murlock-TARGET-et is (17:17).
- 🧪 **Lootolás után a hulla újra kijelölve, ESC-ig várt** (17:25): a hullát (halál-jelző bármelyik formában, vagy
  saját friss ölés/loot) nem jelöli ki.
- 🧪 **2/6-nál otthagyta a murlockokat Jaina felé** (17:25): a félkész quest leadója fölött szürke „?” van, a
  detektor nem különbözteti meg a sárgától; a TDB/tanult szerepek szerint egy félkész quest leadója fölötti jel nem
  teszi relevánssá.
- 🧪 **Quest-zóna bejárása a TDB quest-POI területén** (felhasználó: „a quest POI pontok által megadott területet
  járja be”): a nyitott objektíva TDB-sokszögének belsejéből vett pontok (≤25) a bejárás cellái, a vak 3×3-as rács
  helyett; navmesh-útvonallal.
- 🧪 **Új karakter, 0.9.63 (17:12): a FAST-sáv egyáltalán nem olvasódott** (`fast_packets: 0`), csak a lassú STATE
  (~1,9 Hz) — mouseover, target, mozgás késve: a quest-adóhoz kézzel kellett közelebb menni, murlockot nem jelölt ki.
  A dekóder a minimap alatti FAST-sávot csak széles (>224 oszlop) felső sáv vagy tömörítetlen `STATE` lap után
  kereste; a 0.9.63-as keskeny sáv tömörített `STATE_Z` lapokat visz. → A `STATE_Z` lap is indítja a keresést
  (teszt tömörítő mockkal; a javítás nélkül elbukik).
- 🧪 **A munkapéldány utolsó patch-e 6 tesztet eltört:** hiányzó `completion_state` mezőn elhasalt a tervező, és a
  tábortüzet („Cook the meat”, a tooltipben nincs quest-sor) sosem használta volna. → A quest-sor csak akkor
  kötelező, ha maga az objektum a TDB szerinti GAMEOBJECT-kredit (felhasznált totem); `quest()` nem omlik össze
  `quest_poi` tábla nélkül; a tesztek nem olvassák a Letöltések mappában lévő TDB-t.
- 🧪 **Az alap-tesztek újra védenek (felhasználó: „kellenének alap tesztek, hogy ne törjön el egy skill”).** 15
  teszt hetek óta piros volt, így semmit nem jeleztek — köztük a teljes szimulált quest (felvétel → MOVE → harc →
  loot → leadás), a „megérkezés nem teljesítés”, a „megérkezés kredit nélkül → korlátos helyi keresés”, a keresés
  véges kerete. Az ok elavult tesztadat volt (normalizált térképpont világkoordináta nélkül, a régi 0,5 mp-es
  keresési ütem, a régi „5 mp kiesés → MANUAL” szabály); az elvárásokat megtartva frissítve. Új alap: **0 bukás**.
- 🧪 **A célon állva navmesh-útvonal hiánya miatt elbukott a MOVE** (`required_navmesh_route_unavailable`): ha a
  karakter már a megállási távolságon belül van, nem kell útvonal, az érkezés sikeres.
- 🧪 **Élőben látott, fázisazonosítós TDB-spawn kiesett** (Henry Garrick 156859, a fázis ismeretlen): a tanult
  sorral megerősített spawn átmegy a fázisszűrőn.

## 2026-10-06

### Új funkciók / implementációk
- ✅ **A barlangos quest („Who Lurks in the Pit”) élőben végig lement** (21:41, ~13 perc): 5/5 gubó, Hrun megölve,
  Ralia. Gyenge teljesítménnyel és kézi segítséggel — a funkció (Z resolver + többszintes quest) **átnézendő,
  átgondolandó, optimalizálandó** (lásd KNOWN_ISSUES, „Átnézendő”).
- 🧪 **Falnak futás:** 4 mp egy helyben, folyamatos előre-gombbal → elakadt, a kiszabadító lépés indul.
- 🧪 **Útvonal a járható sáv közepén** (Detour DLL, C++): minden portálon át pont, a fal/szakadék szélétől 1,5 yd-ra,
  sűrűbb pontok (spirál: 56 → 83 pont); a köztes pontot 2,5 yd-on belül veszi el.

### Bug fixes
- 🧪 **Kinyitott gubó, mégis „nem kapott kreditet”** (munkapéldány 20:07: a kredit 2 mp-cel a határidő után jött a
  teljes állapotban, a FAST csomagból kimaradt; 15 mp-ig tiltotta a következő gubót). → Kattintás/F7 után kivárja
  az utána mintavételezett teljes állapotot (legfeljebb +10 mp), csak akkor mondja sikertelennek.
- 🧪 **Megállt egy hunter petet hoverelni, tovább nem ment a spirálról** (09:42). A pet hosszú neve miatt a FAST
  csomag a tartalék változatra váltott, abban nincs időbélyeg; a WorldModel 0-t látott, „régi csomagnak” vette, és
  25 mp-ig minden csomagot eldobott, miközben a telemetria frissnek látszott. → Az összerakó pótolja az időbélyeget,
  a WorldModel nem dobja el az időbélyeg nélkülit.
- 🧪 **„Az út ideiglenesen tiltva” egy INSPECT után:** a 12 mp-es „nem közeledik” szabály az álldogálást (hover,
  harc, loot) is körözésnek vette. → Csak akkor tiltja a célt, ha a karakter ténylegesen ment (≥ ~4 yd), de nem
  közeledett.
- 🧪 **Gubós feladat alatt pet, pók, fáklya hoverelése:** ha minden nyitott objective tárgy (gubó), a creature-doboz
  nem szakítja meg a mozgást és nem kap INSPECT-et (quest-jeles egység továbbra is igen).
- 🧪 **A barlangban indított agent nem mozdult (`ambiguous_player_layer`, 3 bukás → 45 mp WAIT).** Az első
  szint-becslés a peremet (z≈98) választotta a 45–60-as barlangszint helyett, és bizonytalan szintről minden MOVE
  azonnal elbukott. → Ha az addon szerint bent vagyunk (`indoors`) és a terepnek megfelelő legfelső szint alatt
  8+ yd-dal vannak padlók, a felszín nem lehet a szintünk; bizonytalan szintnél 12 yd-os próbaszakaszt megy a
  legvalószínűbb szintről (nem a teljes utat), a mozgás közben kizárja a lehetetlen szinteket. Visszajátszás
  (20:08): 60,5 → 55,4 → 51,3 → 48,0, bizonyosság 0,95.

- 🧪 **Gubó „You are too far away.”** (21:16, egy szinttel lejjebb lévő gubó; kétszer 8 mp várakozás, aztán
  otthagyta). → A hibaüzenetre azonnal OUT_OF_RANGE; 6 mp-ig nem kattint újra, hanem a gubó-doboz felé közelít, a
  „közel vagyok” dobozméret minden ilyen hibánál 25 %-kal nő (sikeres nyitásnál a doboz ~0,19–0,24 magas volt).
- 🧪 **Gubó mozgás közben: „elavult nézet”, 15 mp tiltás, otthagyta** (21:17). → Megvárja, hogy a karakter megálljon,
  újra rámutat ugyanoda és friss azonosítást kér (legfeljebb kétszer); ilyen átmeneti hibák után az OBJECT_USE csak
  2–5 mp-ig szünetel, nem 15-ig.
- 🧪 **Jobb klikk után a kliens odafordította/odaléptette a karaktert, de a nyitás nem indult** (21:15, 15 mp várakozás).
  → Megálláskor egyszer újra kattint oda, ahol friss minta szerint a gubó van az egér alatt (csak ha a karakter
  nézete változott; ha csak az egér mozdult, nem).
- 🧪 **Felszaladt a bejárathoz, majd vissza** (21:16, 32 mp). Egy magasság nélküli keresési cellát a resolver a
  peremre tett. → A keresési rács a játékos szintjén keres (`floor_hint: SAME`); barlangban a csak más szinten
  (15+ yd) elérhető cellát kihagyja.

- 🧪 **A bejárat alatti lejtőn oda-vissza fordult 30 mp-ig** (21:29). A lejtő fölé benyúlik a perem navmesh-poligonja;
  a szint-követés a peremet (z 93,5) tartotta, miközben a karakter a lejtőn (~78) ment, így a következő útvonalpontot
  „másik szintnek” vette, nem hagyta el, és a vezérlő 3D-ben a végső cél magasságával mért (15,9 yd egy 1 yd-ra lévő
  pontig). → Ha két szint is lehetséges, a követett útvonal magassága dönt; a köztes pont a saját magasságát kapja;
  ha a karakter már egy későbbi szakaszon jár, a kihagyott pont elhagyottnak számít (nem fordul vissza).
- 🧪 **A spirálon a szakadék szélén ment** (felhasználó). A legrövidebb út a kanyar belső (szakadék felőli) szélére
  simul. → Detour DLL: minden útvonalpontot a legközelebbi navmesh-széltől (fal vagy szakadék) 2,5 yd-ra tol a
  sétányon belül; a köztes pontot 1,5 yd-on belül veszi el (a 2,5 yd a kanyarokat a szakadék felé vágta).

- 🧪 **A quest kész után visszaindult a gödörbe** (21:54, taxi után). A célpont (Ralia) ismeretlen magasságát a REACH_OBJECT
  0-ra írta; a navigáció ezt ismert z=0-nak vette (a gödör alja). → Ismeretlen magasságnál a navigáció dönt, a saját
  szintet előnyben részesítve.
- 🧪 **Felfelé nyílnál a gubó alá ment** (21:44): a „feljebb” szűrő 3 yd-ot kért, így ugyanazon a padlón 3 yd-dal
  magasabb pontot választott. → Legalább 6 yd (egy emelet).
- 🧪 **30× azonnal „sikeres” bejárási MOVE ugyanarra a peremi pontra** (21:44, 4 mp): a navigáció elhagyottnak
  ítélte a pontot, de a bejárás nem jegyezte fel. → A döntés a bejárásba is bekerül.
- 🧪 **Útközben 7× azonnal bukott a MOVE `ambiguous_player_layer` miatt.** → 4 mp türelem: addig a tervezett
  útvonalon megy (az útvonal segít tisztázni a szintet).

- 🧪 **Addon 0.9.58 — a teljes állapot ritkán állt össze** (21:41: 199 / ~880; a tooltip, a quest-kredit és az
  események másodpercekkel késtek, sok INSPECT emiatt bukott). Ok: minden ~6 oldalas állapotot csak egyszer
  mutatott, a képkockák ~20 %-a nem jut el hozzánk, egy elveszett oldal sosem jött újra. → Minden állapotot legalább
  kétszer mutat, és minden 4. csomag állapot-oldal (eddig minden 6.). Szimuláció: összeállás 23 % → ~78 %,
  leghosszabb kiesés 12 mp → 3 mp; a FAST kb. 10 %-kal ritkább. Telepítve a WoW mappába; `/reload` kell.

- 🧪 **Quest nélkül két „!” quest-adó között ingázott, egyiknél sem vette fel a questet** (22:12; Private Cole
  58914 és Henry Garrick 55196). Cole „!”-jánál a kijelölt Lady Jainát próbálta egy percig (nem válaszolt), Henry
  Garricknál 8,5 yd-ra „megérkezett”, és azonnal visszaindult 80 yd-ot Cole-hoz. → Az „!” pontot 4 yd-ig közelíti
  meg (7–9 yd-ról a mellette álló Richter volt a soft-interact célpont, 4–5 yd-ról Cole); ott a kliens soft-interact
  NPC-jét az interact gombbal szólítja meg (NPC-nként egyszer, hard target nélkül, a quest/gossip ablak a siker);
  a pontnál a soft-interact NPC megelőzi a korábban kijelölt egységet; odaérés után 10 mp-ig nem indul a másik
  adóhoz.
- ✅ **Addon 0.9.58 élőben:** 3653 oldal / 229 teljes állapot (16 oldal/állapot; előtte 22) — kb. 75 % összeállás.

## 2026-10-05

### Új funkciók / implementációk
- 🧪 **Telepítő – helyi MI lépés:** megerősítés után telepíti az Ollamát (winget), elindítja és
  letölti a modellt (`qwen3:4b-instruct-2507-q4_K_M`); a Befejezés oldalon külön gomb.
- 🧪 **Telepítő – figyelmeztetések:** a hiányzó GPU-gyorsítás (TensorRT / CUDA / DirectML) külön
  figyelmeztetés, a telepítés folytatódik.
- 🧪 **NPC-memória az INSPECT-hez:** a hoverrel már megnevezett, nem szükséges NPC-t nem
  hoverezi újra; csak ugyanabban a quest-állapotban és helyben érvényes, 20 mp-ig.
- ✅ **GitHub:** ez a lap, a README „Változások” blokkja, és a projekt szinkronja a repóba
  (személyes fájlok és felhasználónév nélkül).
- 🧪 **A nagy fájlok szétbontása** (12 db, 750–1276 sor → legfeljebb ~660): a metódusok változatlanul
  témánkénti modulokba kerültek, a régi importútvonalak mind működnek; az 571 soros quest-tervező
  függvény három részre bontva. A tesztek mindegyik lépés után zöldek, a 3 régi méretkorlát-teszt is.
- ✅ **Verziók (git tag):** minden nagyobb változás előtt a GitHubon lévő állapot verziócímkét kap,
  így bármikor visszaállítható (lásd README, „Verziók”).
- 🧪 **Útvonal a Live Visionben:** jobb alsó sarokban felülnézeti kis térkép (menetirány felfelé) az útvonal
  összekötött pontjaival, a következő ponttal, a zóna-bejárás szakaszaival és a céllal, magasság szerint színezve
  (kék = lejjebb, narancs = feljebb, zöld = egy szinten); a kép alján irányjelzés („WP 14 yd, 34° jobbra, le 4 yd”).
- 🧪 **Quest-lény memória (`quest_creature_memory`):** a profilban megmarad, melyik quest-et ki
  adta és ki vette át (a párbeszédablak NPC-je), mely lények voltak a célpontok, melyik járműre szállt
  fel, a lények kinézete, és hogy mivel teljesültek az objective-ek (pl. „8× Trample a disznóról a
  Monstrous Cadaverekre, itt”). Felhasználás: az emlékezett leadó a legerősebb leadó-bizonyíték; a pin
  ismert quest-adóját „!” nélkül is kijelöli; ha minden közeli pin quest-adója ismert, a többi NPC-t
  nem hoverezi újra; a keresett lényhez hasonló kinézetű dobozt nézi meg először. A tanult
  jármű-képesség hatások (pl. Trample = előre roham) újraindítás után is megmaradnak.
- ✅ **Addon 0.9.56:** a kész quest questlog-befejezési sora („Return to Captain Garrick…”) és a leadó
  GUID-ja is átjön; a legutóbbi párbeszéd questjének szövege elsőként megy át, akkor is, ha a quest
  már nincs a logban.

### Bug fixes

#### Új karakter, egyórás futás (Exile's Reach, 9 quest leadva)
- 🧪 **Emergency First Aid: Kee-Lát háromszor hoverezte, a felhasználó ki is jelölte, mégsem használta rajta a
  First Aid Kitet.** Csak az „elsődleges” objective-et (Bjorn) nézte, Kee-La objective-jét – ugyanaz a quest,
  ugyanaz a tárgy – kihagyta, és a keresési MOVE közben sem állt meg. → Ha egy tárgyas objective célpontja van
  a kurzor alatt vagy kijelölve, az is sorra kerül; a quest-útvonal/pötty MOVE megáll, ha egy nyitott
  objective-ben név szerint szereplő egység kerül a kurzor alá.
- 🧪 **Jainánál egy másik játékost jelölt ki (előtte állt), és 47 yardot ment utána a quest felvétele helyett.**
  Az addon nem küld „játékos” jelzőt a targetről/mouseoverről. → A `Player-` GUID játékosnak számít, NPC-ként
  sosem közelíti meg és nem szólítja meg.
- 🧪 **Captain Garrick (Enhanced Combat Tactics): „Charge at me again” – háromszor kérte, az agent Slamet
  nyomott.** A rotáció a Charge-ot harconként egyszer engedi (nyitó). → Friss NPC-utasításban megnevezett
  képességnél ez a korlát feloldódik, utasításonként egyszer; a WoW használhatóság/hatótáv/cooldown jelzése
  továbbra is érvényes.
- 🧪 **Gyorsabb kijelölés (felhasználó: „gyorsabbá/pörgősebbé”):** a kijelölés a hover előtti, régi
  mouseover-re kattintott (a semmibe), majd 8 mp-ig várt → csak a hover utáni minta számít, és ha 0,7 mp alatt
  nincs új target, újra-hoverel vagy azonnal sikertelen. Az üres INSPECT 5,6 mp helyett ~0,4 mp. A már
  megnevezett egység újra-hoverelésének tiltása kikerült (az üres pont/holttest/saját karakter tiltás marad).
  A futásban a sikertelen INSPECT/TARGET ~7 percet vitt el.
- 🧪 **Re-Sizer: kóválygott, a felhasználó vitte a vadkanokhoz és csinálta meg a 2/3, 3/3-at.** A távoli vadkanon az
  Interact nem csinált semmit, ezután a táskából jobb klikkelte a tárgyat, ami csak „élesítette” a kurzort; a
  következő vadkan-kijelölés bal klikkje sütötte el (1/3). → A felhasználó szabálya szerint: kijelölés, majd
  Interact Target megfelelő távolságon belül (vagy jobb klikk a célponton); ha 1,5 mp alatt nem indul a
  használat, odamegy és újrapróbálja. A táskás út csak tartalék, utána a célpontra kattint. (Élő teszt kell.)
- **Scout-o-Matic leadás (~3,5 perc):** Lindie Springstock (gnóm) a képernyő szélén, a „new gear” felugró
  ablak alatt állt; a 980×508-as képen a YOLO nem látta, ezért 70 mp-ig állt mellette, majd keresési cellákat
  járt. Nincs javítva: nagyobb kliensablak kell, vagy a kijelölt, de doboz nélküli egység újrakeresése.
- 🧪 **Az egér lemaradt a mozgó trackről:** a hover oda céloz, ahol az egység a kurzor odaérésekor várhatóan
  lesz (a doboz mért sebessége × a kép kora + egérkésés, legfeljebb 0,5 mp és 12 % képernyő); fordulás közben nem.

#### Navigáció: gödör/barlang, quest-zóna
- ✅ **A zóna-bejárás szakaszai érkezéskor lezárulnak** (élőben 2026-10-06: a szakaszok ~2 mp alatt sikeresek,
  nincs többé körbeforgás).
- 🧪 **A spirálon „leesett”, előre-hátra szaladgált, a gubó fölött egy helyben forgott.** Az ugrásokat és a lejtőn
  lefelé futást is esésnek vette, és egy 1 mp-es „esésből” 90 yarddal lejjebb (a gödör aljára) tette magát; utána
  a peremre; így a 60,8-as gubó-párkány 35 yarddal alatta volt, miközben vízszintesen rajta állt. → Az esést a
  következő minták alapján dönti el (ha a régi padló még alatta van, ugrás volt; legfeljebb 40 yardos esés); MOVE
  nélkül is követi a szintet; poligon-szélen a környék padlóját tartja; más szinten lévő útvonalpontot nem vesz
  elhagyottnak; ha vízszintesen a célon áll, de más szinten, nem forog tovább; a bejárás átugrott szakaszai készek.
- 🧪 **Z resolver (a felhasználó terve szerint):** egyetlen helyen dől el a karakter saját szintje (a navmesh
  szintjei + folytonosság + esés) és a célpontok magassága: járható navmesh-poligon, VMAP-padló (és elég
  belmagasság), útvonallal elérhető a mostani szintről, a minimap-pötty szintjelzése szerint; bizonytalan célnál
  csak 30 yardot megy, aztán újraszámol. Új VMAP-olvasó (TrinityCore collision), és a Detour DLL-be (C++)
  került a szint-lekérdezés (ezerszer gyorsabb). A gubó-pötty felé már nem a peremre tervez, hanem a 66,6-os
  párkányra.
- 🧪 **A spirálról leesve légvonalban akart visszamenni a fenti pontra (nekiment a falnak).** Az addon nem küld
  magasságot, így leesés után is fent hitte magát. → Az esés-esemény (FALL_ENDED) után a lenti szintre teszi
  magát és onnan tervez újra; ha a lefelé bejárás egy fenti szakaszát ugrotta át, azt teljesítettnek veszi és
  lentről folytatja.
- 🧪 **A spirál alján, a barlang bejáratánál 30 mp-ig körbe-körbe forgott, centinként lépkedett** (a zóna-bejárás
  4. pontja 0,1–0,5 yardra volt, „megérkezett”, mégsem állt meg). Két hiba együtt okozta: a navmesh-útvonal vége
  Detour-pontosságú, 0,000075 yarddal eltért a kért céltól, ezért minden vezérlőlépés újratervezett, és az
  újratervezés a „megérkezett” állapotot visszaállította „megy”-re. A gyors (FAST) sáv látta az érkezést és
  megállt, de a lépést csak a lassú sáv zárhatja le, és az ugyanarra a mintára „nincs új pozíció”-t
  látott. → Az újratervezés a kért célt hasonlítja; a „megérkezett/elakadt” ítélet megmarad a következő
  indításig. (Az útvonal eddig minden navmesh-es MOVE-nál folyton újratervezett.)
- 🧪 **A gubó sárga pöttyének lefelé nyila két képkockán eltűnt** (halvány nyíl, illetve a kék zónakeret egy
  pixelsora a nyíl tetején), ilyenkor „egy szinten” lett volna. → Halvány nyilat második lépésben keres,
  a keret pixelsorát levágja; a nyilat nem számolja szürke pöttynek. Élő képkockákon: a gubó minden
  képen „lejjebb”.
- 🧪 **„Who Lurks in the Pit”: a gödör peremén (2D-ben „a zónában”) keresgélt, térképet nyitott és Bjornt
  szólította meg, le nem ment.** → A zóna szélén indul a zóna bejárása; ha a navmesh a POI mellett jóval
  mélyebb, elérhető szinteket köt össze (itt a spirál, 34 szakasz, z 91 → −22), rövid szakaszokban
  végigmegy rajtuk le, majd vissza fel, és minden szakasz után keres (sárga pötty, seek, inspect, harc).
  Élőben a lemenet már működött (12:52).
- 🧪 **Pók után a lefelé út a fenti peremről indult, egy helyben toporgott.** → A navigáció követi a játékos
  saját szintjét, az új útvonal onnan indul (becsült magasságként, így a Torgok/Wrathion-féle
  kijutás változatlan).
- 🧪 **Oda-vissza a quest-adók között; sárga „!” ikon pöttynek nézve (95 yd kitérő); Cole „!”-jét nem
  vette észre; gubó-objective miatt Bjorn megszólítása.** → Leadás után 10 mp-et vár az új pinekre; a blokkolt
  út alternatívája nem lehet sokkal távolabbi; a „!”-pinek körüli pöttyök ikonok; a „!” keresése a kurzor
  alatti dobozon is; tárgyas objective nem tesz NPC-t relevánssá.
- 🧪 **Minimap szint-nyilak:** a szürke pöttyöt és a pötty alatti/feletti kis háromszöget (▼/▲) felismeri
  (1600×900-on; 843×475-ön a nyíl 1–2 px, nem látszik); lefelé nyílnál nem a pötty felé megy ezen a szinten,
  hanem lefelé folytatja a zóna bejárását. A sárga pötty mérethatára a minimap méretéhez igazodik.
- 🧪 **Minimap-szabály (felhasználó):** kék területen belül = zónában; sárga pötty = ugyanabban a térben;
  szürke pötty le/fel nyíllal = lejjebb/feljebb van az objective. Új minimap-osztályok a tanításhoz.

#### Questek leadása, NPC-keresés
- 🧪 **Három quest-adóhoz ment oda, csak a harmadiknál (Bjorn) vett fel questet.** A leadás után
  Captain Garrick kijelölve maradt, és üres questlognál minden kijelölt barátságos NPC
  „releváns” volt: a Garrick-ág minden körben lezárta a tervezést, mielőtt az egér alatti NPC
  kijelölése (TARGET) sorra került volna. Private Cole („!” a feje fölött) és Henry Garrick
  hoverezve volt, mégsem jelölte ki őket; közben 88 yardról újra Garrick felé indult, és
  9 mp-ig tétlenül várt. → A már megszólított, „!” nélküli kijelölt NPC-t az ágens elengedi;
  a következő kijelölés felülírja. Billentyűt nem nyom: a Retail 12.1-ben nincs „Clear Target”
  kötés, a vak Esc pedig a játékmenüt nyithatja meg.
- 🧪 **Garricknál nem adta le a kész questet, Private Cole-nál nem vette fel a következőt.**
  Az INSPECT „már megnéztem, nem kell” memóriája 60 mp-ig kihagyta őket, pedig közben
  a quest kész lett, illetve a játékos odament a „!” helyre.
  → Az ítélet csak ugyanabban a quest-állapotban és helyben (5 yardon belül) érvényes,
  20 mp-ig. Quest-adó keresése közben (nincs aktív quest) barátságos NPC-t soha nem hagy ki.
- 🧪 **Rossz leadó NPC.** A quest szövege nem nevezte meg a leadót, a helyi MI tippelt
  (Richter, tévesen). → Ha a leadót csak az MI tippelte, a quest-adó is jelölt marad.
- 🧪 **„Meet Bjorn Stouthands west of the Alliance Camp”** szövegből nem ismerte fel a
  leadót. → A „Meet / Meet with / Join &lt;név&gt;” minta is leadót jelöl.
- 🧪 **Négyszer szólította meg Bjornt 11 mp alatt, mindig „out of range”.** → Az első
  megszólítás marad; hatótáv-hiba után 20 mp-ig nem szólítja meg vakon újra, előbb
  megkeresi és megközelíti.

#### Helyi MI, telepítő
- 🧪 **A GUI mindig kikapcsolta a helyi MI-t (quest-szövegértelmező).** → Újra a
  `config/ai_decision.json` szerint fut (alapból be), ha az Ollama elérhető.
- 🧪 **Telepítő, friss NVIDIA gép:** az `ultralytics` a CPU-s PyTorch-ot húzta fel, a CUDA-s
  telepítés „már megvan”-t mondott, és a telepítés megállt. → A CUDA-s torch települ először.
- 🧪 **Telepítő:** egy hiányzó TensorRT / CUDA / DirectML az egész telepítést leállította
  (addon és navigáció nélkül). → Csak figyelmeztetés, a telepítés folytatódik.
- 🧪 **Telepítő:** az „Indítás most” 20 perces próbát indított (→ 5 perc); aposztrófos mappanév
  elrontotta a parancsikonokat.

---

## 2026-10-04

### Új funkciók / implementációk
- ✅ **Járművek (általánosan, minden quest-járműre):** a jármű akciósávjának exportja
  (addon 0.9.49), VEHICLE_ABILITY készség, a képességek használati módja (előre-roham /
  célzott / közeli) a megfigyelt hatásból, a tooltipből vagy a helyi MI-ből; visszaszállás
  kijelentkezés után. 🧪 EXIT_VEHICLE, ha magától kell kiszállni.
- 🧪 **Saját karakter felismerése** kamera-zoomtól és járműtől függetlenül (hover, forgás közben
  helyben maradó doboz, középső fókusz), maszkolás nélkül.
- ✅ **Helyi MI (Ollama, qwen3:4b, GPU-n ~2 mp/kérdés):** quest-feladatok, jármű-képességek és
  NPC-beszéd értelmezése bonyolultabb questeknél; benchmark eszköz a modellválasztáshoz.
  Addon 0.9.51–0.9.52: quest szöveg, quest-adó és leadó rögzítése.
- 🧪 **Leadó NPC a quest saját szövegéből** („Return to …”, „Speak with …”, „back to me”).
- 🧪 **Vizuális prototípusok:** questenként megtanulja, milyen alakú/színű dolgot kell ölni,
  és a hasonló dobozokat hamarabb nézi meg.
- ✅ **Minimap quest-pötty:** a sárga pötty felé indul, ha a célpont nem látszik.
- 🧪 **Kijelölt célpont minimap-jele:** képernyőn kívüli célpont iránya és távolsága.
- ✅ **Vendor questek:** bolt megnyitása, a legolcsóbb tárgy megvétele, szemét eladása
  (addon 0.9.55).
- ✅ **Jutalom automatikus választása:** használható → item level → eladási ár → első sor
  (addon 0.9.53).
- ✅ **Navigáció többszintes helyeken (épületek):** a cél és a kiindulás bejárható szintjeinek
  vizsgálata a navmeshen.
- 🧪 **Respawn-várakozás** egyedi célpontra (pl. Torgok), ha valaki más megölte.
- 🧪 **„Need to be closer” lépésszabály:** hatótáv-hiba után 5, majd 3, majd 2 lépés előre.
- 🧪 **Confidence-öröklés** (felhasználói ötlet): azonos helyen és méretben a gyengébb
  YOLO-doboz is ugyanaz a célpont.
- 🧪 **Vision dataset új formátum:** teljes képek YOLO-címkékkel a detektor tanításához.
- 🧪 **Live capture megőrzés:** csak a legutóbbi 3 szegmens marad.

### Bug fixes

#### Vendor quest („Stocking Up on Supplies”)
- ✅ **Richtert hoverezte, de nem nyitotta meg a boltját.** A szerver `1/1`-et küldött kész
  jelzés nélkül, az agent késznek vette. → Az API „nincs kész” jelzése erősebb a
  számlálónál; a „purchased from X / sold to X” vásárlás/eladás feladat X vendornál.
- ✅ **Nyitott boltnál leállt (WAIT).** Az addon üres árulistát küldött (Retail 12:
  `C_MerchantFrame.GetItemInfo`), és csak a vásárlást tervezte. → Addon 0.9.55; nyitott
  boltnál vásárlás és eladás is tervezve; a megnyílt bolt sikeres interakciónak számít.
- 🧪 **Ugyanazt a 3 NPC-t hoverezte körbe-körbe.** → Megnevezett, nem kellő NPC-t nem
  hoverez újra (10-05-én finomítva).

#### Jutalom és leadás
- ✅ **Egyetlen jutalomnál nem tudott leadni** (nem volt „Complete” gomb). → Addon 0.9.46.
- ✅ **Két jutalomnál nem választott.** → Automatikus választás (lásd fent).
- 🧪 **Kiválasztotta a jutalmat, de nem nyomta meg a „Complete Quest”-et.** Retail 12-ben a
  jutalomgomb kijelölése nem látszott az addonnak. → Addon 0.9.54 (`QuestInfoFrame.itemChoice`).
- ✅ **A kijelölt leadó NPC (Garrick) helyett a leadási pontra ment.** → A kész quest
  leadójához közel kijelölt NPC-t megszólítja.
- 🧪 **„You need to be closer” ciklus (Wrathion):** a képernyő-doboz alapján „elég közel”-nek
  hitte. → Hatótáv-hiba után valóban előremegy (5/3/2 lépés).
- 🧪 **A „need to be closer” hibát elveszítette** (az addon órája 6 mp-et késett). → Esemény-sorszám alapján dönt.
- 🧪 **Huxworth kijelölve és látható, mégsem közelítette meg.** → A célponthoz kötött
  World3D track is érvényes horgony.

#### Speciális questek
- ✅ **Scout-o-Matic 5000** („Use &lt;unit&gt; to …”): nem használta. → Használat/lovaglás/beszállás
  szöveg NPC-interakció; járműbe ülés sikernek számít (addon 0.9.47).
- ✅ **Minden barátságos NPC „releváns” lett** (Lindie-t újra és újra kijelölte). → Ha a feladat
  megnevezi az NPC-t, csak azt.
- ✅ **Re-Sizer:** a vaddisznót megtámadta a tárgyhasználat helyett; távoli célnál nem
  tudta használni. → Tárgyhasználati feladatnál nincs harc; táskagombok Retail 12-ben
  (addon 0.9.48); hatótáv-hiba után közelítés.
- ✅ **Giant Boar:** nem ült fel rá. → „Ride/Mount/Board/Enter &lt;unit&gt;” felismerése.
- ✅ **A disznón utasként várt.** → A jármű képességei kerülnek az akciósávra.
- ✅ **Monstrous Cadaver-eket nem támadta.** → Trample előre-roham módban (célzás, majd nyomás).
- 🧪 **A saját disznó dobozát hitte célpontnak.** → Saját-karakter felismerés (lásd fent).
- ✅ **Kijelentkezés után nem ült vissza a disznóra.** → Újra felül, amíg a jármű-szakasz nyitott.
- ✅ **Lassú volt a disznós rész** (161 mp várakozás 310-ből). → A járműképesség nem vár a
  kijelölési „commitment”-re (161 → 36 mp).
- 🧪 **Elvesztette a célzott doboz követését** (alacsony confidence). → Forgás-korrekciós
  újrakötés és confidence-öröklés.
- ✅ **A szkriptelt leszállás után a disznót kereste.** → Állapotmentes visszaszállás-szabály.

#### Navigáció
- ✅ **Nem jutott be Torgok épületébe** (terep-magasság az épület alatt). → Szintvizsgálat.
- ✅ **Nem jutott ki az épületből** (rossz kiinduló magasság). → A kiinduló szintet is vizsgálja.
- ✅ **A minimap-pötty felé indulva egy helyben állt** (az első útpont alatta volt). → Közeli
  útpontok kihagyása.
- ✅ **A távolabbi questre ment előbb** (egyenlő pontszám). → Valós távolság dönt.
- 🧪 **Kőbe ragadt, majd ugyanarra ment vissza.** → Akadály-jelölés és kitérő útvonal.
- 🧪 **Elhagyta a nyitott quest területét egy másik quest kedvéért.** → A területen belül
  más quest útvonala 120 mp-ig vár.
- 🧪 **Rossz minimap-pötty** (a leadási „?” jelet és a kijelölt célpont jelét is quest-pöttynek vette).

#### Telemetria, futás
- 🧪 **„telemetry suspended” megállás, miközben az adat folyt.** → A FAST csomag frissíti az élő-jelzést.
- 🧪 **Két agent futott ugyanarra a WoW-ra.** → A második nem indul el.
- 🧪 **Live capture-ök megtöltötték a lemezt.** → Megőrzési szabály (lásd fent).

---

## 2026-10-03

### Új funkciók / implementációk
- ✅ **Leadási pont körüli keresés:** a pont közelében körbenéz és bejárja a környéket a „?” NPC-ért.
- ✅ **Quest-terület bejárása cellánként**, minden cellában körbenézéssel.
- 🧪 **Quest-terület a minimap kék körvonalából** (addon 0.9.43).
- ✅ **Kampány questek elsőbbsége** (felhasználói döntés; addon 0.9.44 kampány-jelző).
- 🧪 **Questek csoportosítása:** előbb az egy helyen lévőket csinálja meg, utána adja le együtt.
- 🧪 **Több quest egy NPC-nél:** soronként veszi fel (addon 0.9.42, QUEST_GREETING).
- ✅ **Hover-megerősített kattintás:** TARGET és LOOT csak akkor kattint, ha az addon
  megerősítette a GUID-ot a kurzor alatt.
- ✅ **Auto-attack az interact billentyűvel**, képernyő-doboz nélkül is.
- ✅ **Halál kezelése:** szellem-futás a holttesthez, feltámadás (addon 0.9.45).
- 🧪 **Saját cast-okból számolt cooldown** (harcban a cooldown titkosított).
- ✅ **YOLO v10 modell** (újraellenőrzött címkék, creature mAP50 .43 → .68), alapértelmezett.
- 🧪 **Telemetria-visszajátszó eszköz** a döntések offline ellenőrzéséhez.
- 🧪 **Memória felhasználónkénti profilban** (nem PID-enként).
- 🧪 **Indítás bindings-cache nélkül:** az első AUTO_START az addon exportjából készít egyet.
- 🧪 **Telepítő varázsló:** „Minden egyben telepítés”, automatikus belépés, parancsikonok.
- 🧪 **AMD/Intel GPU:** a YOLO DirectML-lel fut (CPU 251 ms → 18 ms/kép).

### Bug fixes

#### Quest-folyamat
- ✅ **A leadási ponton egy helyben toporgott** („?” keresés helyett újra és újra MOVE).
- 🧪 **Leadott quest maradt az „elsődleges”**, és kiszűrte a többi quest lépéseit.
- 🧪 **Egy NPC két questet kínált, 38 mp-ig várt.** → Soronként felveszi; újra megszólítja, ha maradt quest.
- ✅ **2 perces WAIT a quest-területen.** → Cellánkénti bejárás.
- 🧪 **Felesleges MOVE a quest-területen belül** (minden kill után új út).
- ✅ **„Cook the meat on the campfire”** tárgyként jött, nem használta a tábortüzet. → Objektum-interakció.

#### Harc, célpont, loot
- 🧪 **Slam-et soha nem használta** (Retail harcban titkosítja a cooldownt). → Saját cast-okból számolt cooldown.
- ✅ **TARGET kattintás mellément** (a célpont kicsúszott a kurzor alól). → Hover-megerősített kattintás.
- ✅ **Közelharcban álló kecskét nem támadta** (0 rage, nincs képernyő-doboz). → Auto-attack az interact billentyűvel.
- 🧪 **4,5 percig nem csinált semmit harcban** (a célpont képernyőn kívül). → Korlátos várakozás, majd újratervezés.
- 🧪 **„Target needs to be in front of you” → meghalt.** → Fordulási keresés támadással; harcban is támadhat.
- ✅ **Halál után megállt.** → Halál kezelése (lásd fent).
- 🧪 **5/5 után is ölte a kecskéket** (a tooltip a kész sort is mutatta). → Kész sorok nem számítanak.
- 🧪 **Üres hullát próbált lootolni; a karakter alatti hullát nem találta.** → `lootable=false`
  figyelése; softinteract hulla az interact billentyűvel.
- ✅ **Tüske-disznót hoverezte, de nem jelölte ki** (a tooltipben a quest neve szerepelt). → Ez is quest-relevancia.
- 🧪 **Barátságos NPC-k és mások petje mellé tévedt.** → Aktív questnél csak a szükséges NPC.

#### Teljesítmény, rendszer
- ✅ **Lassú agent (FAST ~14 Hz), óriási memória-adatbázis** (500 MB + 2,26 GB WAL). →
  Pillanatnyi állapotok nem kerülnek a DB-be; ~26 Hz.
- 🧪 **„Érvénytelen movement lease” hibák** (túl rövid fordulás, rossz sávon küldött egérmozgás).
- 🧪 **Ugyanazt az üres pontot hoverezte 11–12×.** → Változatlan nézetben 25 mp-ig kihagyja.
- 🧪 **Oszlop és kő közé szorult.** → Sorban kipróbált fizikai menekülési lépések.
- ✅ **A térkép nyitva maradt a leadási pontnál, ezért WAIT.** → CLOSE_MAP.

---

## 2026-10-02

### Új funkciók / implementációk
- 🧪 **Telepítő varázsló (első változat):** Python csomagok, WoW `_retail_` mappa ellenőrzése,
  addon telepítése, navigációs adatok (maps / vmaps / mmaps) a TrinityCore extractorokkal
  közvetlenül a `_retail_` mappából (zip nélkül), TensorRT engine, beállítások mentése.
- 🧪 **Elakadás-kezelés:** futás közbeni ugrás kis akadálynál, nagyobb hátralépés, a megtanult
  akadály a navmeshen ellenőrzött kitérővel; ismétlődő elakadásnál folytatja a lépéssort.
- 🧪 **Harc névtábla nélkül:** a kijelölt célpont képernyő-helye a hozzá kötött World3D trackből
  (Retail 12 nem ad névtábla-pozíciót); „rossz irányba nézel” esetén a célpont felé fordul.
- 🧪 **Quest-NPC szűrő quest nélkül:** csak „!”-jeles NPC-t (vagy API-s quest-pin közelében lévőt)
  szólít meg; a semmit nem mondó NPC 300 mp-ig kimarad.
- 🧪 **YOLO v9** (4975 kép) és hibaelemzés: a gyenge pontszám fő oka a hiányzó címkék és a saját
  karakter következetlen jelölése, nem a képminőség → újraellenőrzési kép-pool; annotátor:
  nyilas lapozás, figyelmeztetés mentetlen módosításra, kép törlése visszavonással.
- ✅ **Quest-adó API-vizsgálat** (addon 0.9.39): kiderült, hogy Retail 12.1-ben nincs API, ami
  hoverre/targetre megmondaná, ad-e questet egy NPC → csak a „!” jel, a párbeszédablak és a
  térkép-pinek használhatók.

### Bug fixes
- ✅ **Futás közben „elakadtnak” hitte magát.** A gyors telemetria-csomagok nem vitték a pozíciót,
  így minden minta a régi helyet mutatta. → Addon 0.9.38; csak friss pozíció számít haladásnak.
- 🧪 **A Murloc Hideaway hajóroncsánál valóban elakadt** (a roncs nincs a navmeshben, újra-
  generálással sem kerül bele). → Megtanult akadály és kitérő útvonal.
- ✅ **Az első murlocot nem lootolta** (nem jegyezte meg, hogy ő ölte meg), és a loot-ellenőrzés
  rossz eseménynevet várt. → Harc-memória, javított ellenőrzés, 6 mp-es időkorlát.
- ✅ **Kill után nem volt mire kattintani lootoláskor.** → A halálkori World3D doboz lesz a hulla helye.
- 🧪 **A saját karakter dobozára kattintott lootoláskor.** → A saját doboz minden társításból
  kimarad; az addon 0.9.41 jelzi, ha a hulla üres.
- 🧪 **„Rossz irányba nézel” után 14 mp-ig várt, miközben ütötték.** → Fordulás a célpont felé, rövid tiltás.
- 🧪 **Kee-La (nem quest-adó) ~45 mp-et vitt el a quest-adó keresésből.** → Quest-NPC szűrő.
- ✅ **„Murloc Mania” (55122) teljesítve** a javítások után (felhasználói jelentés).

---

## 2026-10-01

### Új funkciók / implementációk
- 🧪 **Térkép-API pontok** (addon 0.9.37): quest-adók („!”) és dungeon/raid bejáratok helye; aktív
  quest nélkül a legközelebbi quest-adóhoz indul (✅ 10-02-én élesben elérte Jainát).
- 🧪 **Quest-adó keresés aktív quest nélkül:** gyűrűben bejárt, navmeshen ellenőrzött cellák,
  minden cellában körbenézés.
- 🧪 **World Map / minimap ikon-felismerő (YOLO) folyamat:** gyűjtő, átnéző és tanító eszközök;
  modell még nincs, mert élesben egyetlen quest-pin sem látszott a térképen.
- ✅ **Kamera-mozgás kompenzáció** két világ-kivágással és több hipotézis közüli választással,
  és a saját karakter képernyőhöz kötött követése → a saját karakter végig egy azonosítón maradt.
- 🧪 **Érkezés-szabály (felhasználói):** megérkezett, ha a célpont doboza a saját karakter mellé
  ér vagy kb. negyedéig-harmadáig átfed vele.
- 🧪 **Kilépési-él korrekció (felhasználói ötlet):** ha a doboz alul tűnt el → hátralép, oldalt →
  arra fordul, felül → előrelép.
- ✅ **Kill vége = harcon kívül (felhasználói szabály):** a célpont HP-ja titkos, ezért a harc vége
  jelzi a kill-t, és azonnal jön a loot.
- 🧪 **Live Vision eseményvezérelt megjelenítés** (terhelt gépen 30 → 40 Hz).

### Bug fixes
- ✅ **Kamera-forduláskor minden doboz új azonosítót kapott** (a kompenzáció a képernyőhöz rögzített
  pixel-csíkot és HUD-ot nézte). → Világ-kivágások; a „GMC failed” numpy-hiba is javítva.
- 🧪 **Ugyanazzal az azonosítóval két doboz, azonnali újraszületések.** → Egyedi azonosítók
  képkockánként, bővebb újra-azonosítás.
- ✅ **A „need to be closer” hibák elvesztek** (code 852). → Esemény alapján; az interakciós
  magasság élesben tanult (.13 → .186).
- 🧪 **Szaggatott, „stop-and-go” közelítés és túlfutás.** → Folyamatos előre-menet, egyszeri
  azonosság-ellenőrzés, előre megállás, nagyobb érkezési tűrés.
- 🧪 **Végrehajtási hibák** („Érvénytelen movement lease / klienskoordináta”). → Minimális
  fordulási idő, képernyőn belüli pontok.
- 🧪 **Egy véletlen gnóm játékost követett.** → Újrakötés csak megbízható, hasonló méretű dobozra.
- 🧪 **WAIT-holtpont kijelölt, de képernyőn kívüli egységnél.** → Visszakeresés az utolsó irányban.
- ✅ **A loot rossz pontra kattintott** (az utolsó mouseover helyére). → A halálkori doboz;
  18:27-kor az első sikeres élő lootok.
- ✅ **A harc 17–32 mp-ig futott a kill után.** → Harcon-kívül szabály.
- ✅ **Nem minden mobot lootolt** (a terület-loot már kiürítette a többit). → Sikeres loot után a
  közeli saját hullák kész.
- 🧪 **A World Map újra és újra megnyílt** (üres térkép). → 2 üres keresés után 10 percig nem.
- 🧪 **Egy kijelölt játékos blokkolta a quest-adó keresést.** → Játékos-kijelölés nem blokkol.
- ✅ **Mérföldkő:** teljes lánc élesben (keresés → kijelölés → quest elfogadása → útvonal → harc
  → loot), és 18:43-kor a „Murloc Mania” célja 6/6, teljesen önállóan.

---

## 2026-09-30

### Új funkciók / implementációk
- ✅ **3-osztályos YOLO egység-detektor (v8)**: lény / quest-tárgy körvonal / fej feletti jel;
  TensorRT ~7 ms.
- ✅ **Szál-profilozó** (`thread_profile_history.jsonl`) a fő ciklus akadásainak méréséhez.
- 🧪 **Stabil World3D objektumréteg (felhasználói kérés):** a dobozok aktívak és helyben maradnak,
  a nyers állapot (elveszett, takarásban) a háttérben látszik.
- ✅ **Képrögzítés-vezérelt YOLO külön folyamatban:** minden új képkockán fut (élesben ~27 Hz,
  követéssel együtt).
- ✅ **A World3D érzékelés saját folyamatban** (élesben 36–92 Hz, korábban 15–18 Hz).
- ✅ **Memória késleltetett és háttérben írása:** az agent lépése 70 → 30 ms, a gyors vezérlés
  12 → 21 Hz.
- 🧪 **Pixel-csík dekódolás** egy numpy-lépésben, a képrögzítő folyamatban.
- ✅ **Korlátos, időzített automatikus tesztfutás** (felhasználói engedéllyel).

### Bug fixes
- ✅ **Kee-La-t (nem válaszoló NPC) újra és újra megszólította.** → Néma NPC egy időre kimarad
  (később: Jainát nem blokkolja, ha hatótáv-hiba volt).
- ✅ **A fő ciklus „éhezett”, a karakter helyben forgott.** → Folyamat-alapú képrögzítés
  alapból; a nagy World3D nézet nem kerül az adatbázisba (0/110 elavult minta, 18 Hz).
- 🧪 **A saját karakter duplikált doboza inspektálható maradt.**
- 🧪 **A quest-jel egy elveszett (rossz) testhez kötődött**, ezért elfordult Jainától. → Élő testek előnyben.
- 🧪 **A pixel-csík dekódolás teljesen leterhelte a szenzor-szálat.**
- 🧪 **Elveszett követés, ha egy NPC-nek két váltakozó doboza volt.** → Élő folytatás.
- 🧪 **Gyakori azonosító-csere.** → Teljes képes detektálás, BoT-SORT pontszám-fúzió nélkül
  (visszajátszásban 2079 → 199 új azonosító/perc), rövid kiesés utáni újra-azonosítás.
- 🧪 **Villogó UI-jelzők** (a térkép 28× „nyílt-zárt” 4 mp alatt). → Debounce.
- 🧪 **Távoli néma megszólítások és WAIT-holtpont.** → Előbb közelítés.
- ✅ **Az INTERACT a gombnyomás előtti adat alapján bukott** (és az óra-eltérés miatt is). →
  Javítva; 18:26-kor élesben elfogadta a „Murloc Mania” questet.
- 🧪 **A közelítés után 120 mp-ig minden feladat tiltva volt.** → Sikeres közelítés újranyitja.

---

## 2026-09-29

### Új funkciók / implementációk
- 🧪 **BoT-SORT követés kamera-mozgás kompenzációval** (sparse optical flow), 30 frissítésnyi
  „elveszett” puffer, a dobozfajták nem cserélhetnek azonosítót; háttérben töltődik be.
- 🧪 **Követő kamerás keresés (felhasználói beállítás):** a keresés a karaktert fordítja
  (TURNLEFT/RIGHT) a kamera húzása helyett.
- 🧪 **Teljes magasságú YOLO látómező:** a quest-jel a kép tetején sem esik ki; kemény UI-maszkok
  a telemetria-csíkra, HUD-ra, chatre, akciósávra, egység-keretekre.
- 🧪 **Saját karakter jelölése:** a Live Vision „[SELF]”-ként mutatja, nem inspektálható.
- 🧪 **Detektor-kimaradás tűrése és simítás:** egy üres YOLO-frissítés nem törli az összes dobozt
  (legfeljebb 8 frissítésig marad), a dobozok simítva mozognak.

### Bug fixes
- 🧪 **A barátságos NPC követése közben cserélődtek az azonosítók, és fölöslegesen nyílt a World
  Map.** → Steering-újrakötés a közeli egyértelmű dobozra; a térkép 30 mp-ig nem nyílik újra.
- ✅ **Részleges hozzárendelésnél a BoT-SORT végleg kikapcsolt** („tracker assigned 2/3”). →
  Támogatott állapot; élesben a tracker végig működött.
- 🧪 **A kijelölt Jainát nem szólította meg** (egy régi „már beszéltem vele” jelző sosem járt le). → 60 mp után lejár.
- 🧪 **Az azonosság-ellenőrző hover túl hamar feladta** (0,85 mp, az addon 1,48 mp alatt
  válaszolt). → 2 mp.
- 🧪 **Jaina helyett Kee-La-t választotta** (a quest-jeles csoport alacsony pontszám miatt
  kiesett). → A jeles alany-csoportok előnyben.
- 🧪 **Képernyőn kívüli kitalált doboz** (y = 1,68) miatt forgott körbe. → Levágás, normalizálás a teljes képre.
- 🧪 **Egy fáklyalángra indult el előre** (a jel alá kitalált „test” kapott mozgási jogot). → A kitalált
  doboz csak hoverelhető, mozgást nem kap; YOLO-jel alá nem készül kitalált test.
- 🧪 **Kamera-fordulás után nem kötötte újra a kijelölt NPC dobozát.** → GUID-dal ellenőrzött újrakötés.

---

## 2026-09-28

### Új funkciók / implementációk
- 🧪 **Folyamatos „legújabb képkocka” YOLO:** nincs mesterséges 8–15 Hz-es fék (visszajátszásban 36 Hz).
- 🧪 **Warrior harc-rotáció:** Charge nyitásként, közelben Shield Slam / Slam, ha semmi sem
  használható, jobbklikk auto-attack a kijelölt célpontra; a harc legfeljebb 45 mp.
- 🧪 **Több quest-ajánlat egy NPC-nél:** egyértelmű sorválasztás (kész sor előre, majd a legfelső).
- 🧪 **Quest special item a táskából** (pl. Re-Sizer), ha nincs az akciósávon (addon 0.9.36).

### Bug fixes
- 🧪 **A GUI lefagyott csatlakozáskor és a második FULL_AI-nál.** → Háttérszálas indítás és vezérlés.
- 🧪 **Quilboar Briarpatch: a navmesh-út egy 45°-os sziklán át vezetett.** → Meredek átmenetek tiltva.
- 🧪 **Két quest-ajánlat sorainak nem volt koordinátája** (x = 0, y = 0). → Addon 0.9.33; addig
  biztonságos WAIT a nyitott ablak mögött.
- 🧪 **Leadás előtt újra és újra megnyitotta a World Mapet.** → Leadási pontnál nem talál ki bejáratot.
- 🧪 **A quest-ajánlatot jutalomválasztásnak nézte.** → Addon 0.9.34.
- 🧪 **MOVE közben megtámadták, 47 mp-ig nem védekezett, és meghalt.** → Addon 0.9.35: harci
  FAST csomag (harc-állapot, akciósáv).
- 🧪 **Harc után falba futott** (a futó animáció haladásnak számított). → Csak valós elmozdulás számít.
- 🧪 **Re-Sizer quest: megtámadta a vaddisznót tárgyhasználat helyett.** → USE_ITEM felismerés (addon 0.9.36).

---

## 2026-09-27

### Új funkciók / implementációk
- 🧪 **Quest MOVE közben passzív vizuális keresés**, és a harc által megszakított MOVE folytatása
  (180 mp-ig).
- ✅ **FULL_AI élesítés kézfogással** (előtér, friss addon, World3D, billentyű-export);
  telemetria-kimaradáskor elengedi az inputot, de megtartja a FULL_AI-t; fókuszvesztés kezelése.
- 🧪 **Passzív WAIT közös 5 mp-es kerete**, utána kényszerített újratervezés.
- 🧪 **Kijelölt ellenség megközelítése hover nélkül** egy stabil World3D track alapján.

### Bug fixes
- 🧪 **Az elakadás-figyelő nem indította el a menekülési lépéseket.**
- 🧪 **A tracker sebessége összeomlott** (egy kiugró mérés lefojtotta). → Gördülő medián.
- 🧪 **Túl sok gyenge YOLO-doboz** (0,05-ös küszöb). → 0,15.
- 🧪 **A World Map újra és újra megnyílt** (a 0 „szülőtérképet” valódinak vette).
- 🧪 **MOVE-megszakítási vihar:** 79 MOVE-ból 77-et gyenge jelek szakítottak meg. → Szigorúbb kapu.
- 🧪 **Idegen (nem általa ölt) hullákat akart lootolni.** → Csak saját kill.
- 🧪 **CLOSE_MAP be-ki ciklus** (a bezárás után újra kinyitotta). → A FAST térkép-jelzőt olvassa.
- 🧪 **30 mp-es passzív várakozások** egy tiltott útvonal után. → 5 mp.

---

## 2026-09-26

### Új funkciók / implementációk
- 🧪 **v4 YOLO modell** (2794 kép) TensorRT engine-ekkel, alapértelmezett.
- 🧪 **Független „legújabb képkocka” érzékelés-pumpa** (tracker offline 23 → 33 Hz).
- 🧪 **Harc:** képességhasználati előzmény, friss (FAST) akciósáv-adatok, a kijelölt célpont
  vizuális követése; addon 0.9.32 a spell-hatótávokkal.
- 🧪 **Kék quest-terület** a World Mapről/minimapről → navmeshen bejárható lefedési pontok
  (addon: C_Map koordináta-átváltás).
- 🧪 **Lassú, egyirányú kamera-söprés** a gyors bal-jobb rángatás helyett.

### Bug fixes
- 🧪 **A saját karakter maszkja eltakarta az előtte álló NPC-t.** → A maszk csak metaadat.
- 🧪 **Jaina quest-jelét a fix minimap-kizárás törölte, és WAIT lett.** → Átfedés engedve; a
  támogatott jel–test csoport keresést indít.
- 🧪 **Murloc-loot után rossz útvonal és kitalált bejárat.** → Világ-koordináta + kötelező navmesh.
- 🧪 **A kijelölt Murloc után WAIT** (késő célpont-adat, lassú akciósáv). → Nameplate-társítás,
  FAST akciósáv.
- 🧪 **Éhező tracker és vak TAB-célpont.** → Független pumpa; a TAB nem kereső eszköz.
- 🧪 **Átláthatatlan WAIT és ismételt World Map keresés.** → A WAIT oka kiíródik; a képernyő
  szélén lévő tooltip nem térképpont.

---

## 2026-09-25

### Új funkciók / implementációk
- 🧪 **TensorRT és foveált gyors út:** a YOLO külön folyamatban, osztott memóriával (20 → 9 ms).

### Bug fixes
- 🧪 **Élesben a tanult detektor sokkal kevesebbet látott,** mint az annotáló előnézet (túl magas
  kapu, a HUD-sáv kizárás törölte a valódi lényeket). → Osztályonkénti kapuk, CUDA-eszköz javítva.
- 🧪 **600–800 ms-os akadások** (memória-karbantartás, státusz-építés). → Korlátozott törlés,
  ritkább karbantartás.
- 🧪 **A Live Vision ablak elvette az erőforrást.** → 1 OpenCV szál, alacsony prioritás.

---

## 2026-09-24

### Új funkciók / implementációk
- 🧪 **Az első tanított YOLO modell** (`world3d_annotation_assist_combined_1077_v1`) bekötve az
  élő World3D útba: a felismerések UNKNOWN jelöltek maradnak, konzervatív küszöbök, háttérben
  melegedő GPU.

### Bug fixes
- 🧪 **Nem létező jutalomablak miatt ragadt WAIT-ben** egy harci feladat közben. → Addon 0.9.30
  (csak látható ablakból olvas), a FAST „bezárva” jelzés azonnal törli.
