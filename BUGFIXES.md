# Bug fixes és implementációk

Az Astra 6 által végzett fejlesztések: az élő tesztek (Exile's Reach, Alliance, Warrior)
során talált hibák, a javításaik és az új funkciók, naponként, 2026-09-24-től, amikor az első
YOLO modell bekerült az agentbe.
A részletes napló (okok, logok, tesztek, korábbi előzmények):
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
