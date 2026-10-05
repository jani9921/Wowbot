# Bug fixes és implementációk

Az élő tesztek (Exile's Reach, Alliance, Warrior) során talált hibák, a javításaik és az
új funkciók, naponként, 2026-09-30-tól (a mostani fejlesztési szakasz kezdete). A részletes
napló (okok, logok, tesztek, korábbi előzmények):
[`docs/LIVE_VALIDATION.md`](docs/LIVE_VALIDATION.md). A README „Változások” blokkja ebből
a fájlból készül (`python tools/readme_changes.py`).

**Jelölés:** ✅ élesben igazolva · 🧪 kész és offline tesztelve, élő megerősítés még nincs

---

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

### Bug fixes

#### Questek leadása, NPC-keresés
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
