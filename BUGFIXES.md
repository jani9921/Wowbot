# Bug fixes — javítások

Az élő tesztek (Exile's Reach, Alliance, Warrior) során talált hibák és javításaik,
naponként. A részletes napló (okok, logok, tesztek): [`docs/LIVE_VALIDATION.md`](docs/LIVE_VALIDATION.md).

**Jelölés:** ✅ élesben igazolva · 🧪 javítva és offline tesztelve, élő megerősítés még nincs

---

## 2026-10-05

### Questek leadása, NPC-keresés
- 🧪 **Garricknál nem adta le a kész questet, Private Cole-nál nem vette fel a következőt.**
  Az INSPECT „már megnéztem, nem kell” memóriája 60 mp-ig kihagyta őket, pedig közben
  a quest kész lett, illetve a játékos odament a „!” helyre.
  → Az ítélet csak ugyanabban a quest-állapotban és helyben (5 yardon belül) érvényes,
  20 mp-ig. Quest-adó keresése közben (nincs aktív quest) barátságos NPC-t soha nem hagy ki.
- 🧪 **Rossz leadó NPC.** A quest szövege nem nevezte meg a leadót, a helyi MI tippelt
  (Richter, tévesen). → Ha a leadót csak az MI tippelte, a quest-adó is jelölt marad.
- 🧪 **„Meet Bjorn Stouthands west of the Alliance Camp”** szövegből nem ismerte fel a
  leadót. → A „Meet / Meet with / Join <név>” minta is leadót jelöl.
- 🧪 **Négyszer szólította meg Bjornt 11 mp alatt, mindig „out of range”.** → Az első
  megszólítás marad; hatótáv-hiba után 20 mp-ig nem szólítja meg vakon újra, előbb
  megkeresi és megközelíti.

### Helyi MI, telepítő
- 🧪 **A GUI mindig kikapcsolta a helyi MI-t (quest-szövegértelmező).** → Újra a
  `config/ai_decision.json` szerint fut (alapból be), ha az Ollama elérhető.
- 🧪 **Telepítő, friss NVIDIA gép:** az `ultralytics` a CPU-s PyTorch-ot húzta fel, a CUDA-s
  telepítés „már megvan”-t mondott, és a telepítés megállt. → A CUDA-s torch települ először.
- 🧪 **Telepítő:** egy hiányzó TensorRT / CUDA / DirectML az egész telepítést leállította
  (addon és navigáció nélkül). → Csak figyelmeztetés, a telepítés folytatódik.
- 🧪 **Telepítő:** opcionális lépés az Ollama telepítésére (winget), indítására és a modell
  letöltésére; az „Indítás most” 5 perces próba (20 helyett); aposztrófos mappanév a
  parancsikonoknál.

---

## 2026-10-04

### Vendor quest („Stocking Up on Supplies”)
- ✅ **Richtert hoverezte, de nem nyitotta meg a boltját.** A szerver `1/1`-et küldött kész
  jelzés nélkül, az agent késznek vette. → Az API „nincs kész” jelzése erősebb a
  számlálónál; a „purchased from X / sold to X” vásárlás/eladás feladat X vendornál.
- ✅ **Nyitott boltnál leállt (WAIT).** Az addon üres árulistát küldött (Retail 12:
  `C_MerchantFrame.GetItemInfo`), és csak a vásárlást tervezte. → Addon 0.9.55; nyitott
  boltnál vásárlás és eladás is tervezve; a megnyílt bolt sikeres interakciónak számít.
- 🧪 **Ugyanazt a 3 NPC-t hoverezte körbe-körbe.** → Megnevezett, nem kellő NPC-t nem
  hoverez újra (10-05-én finomítva, lásd fent).

### Jutalom és leadás
- ✅ **Egyetlen jutalomnál nem tudott leadni** (nem volt „Complete” gomb). → Addon 0.9.46.
- ✅ **Két jutalomnál nem választott.** → Automatikus választás: használható → item level →
  eladási ár → első sor (addon 0.9.53 adja az item levelt).
- 🧪 **Kiválasztotta a jutalmat, de nem nyomta meg a „Complete Quest”-et.** Retail 12-ben a
  jutalomgomb kijelölése nem látszott az addonnak. → Addon 0.9.54 (`QuestInfoFrame.itemChoice`).
- ✅ **A kijelölt leadó NPC (Garrick) helyett a leadási pontra ment.** → A kész quest
  leadójához közel kijelölt NPC-t megszólítja.
- 🧪 **„You need to be closer” ciklus (Wrathion):** a képernyő-doboz alapján „elég közel”-nek
  hitte. → Hatótáv-hiba után valóban előremegy: 5, majd 3, majd 2 lépés.
- 🧪 **A „need to be closer” hibát elveszítette** (az addon órája 6 mp-et késett). → Esemény-sorszám alapján dönt.
- 🧪 **Huxworth kijelölve és látható, mégsem közelítette meg.** → A célponthoz kötött
  World3D track is érvényes horgony.

### Speciális questek
- ✅ **Scout-o-Matic 5000** („Use <unit> to …”): nem használta. → Használat/lovaglás/beszállás
  szöveg NPC-interakció; járműbe ülés sikernek számít (addon 0.9.47).
- ✅ **Minden barátságos NPC „releváns” lett** (Lindie-t újra és újra kijelölte). → Ha a feladat
  megnevezi az NPC-t, csak azt.
- ✅ **Re-Sizer:** a vaddisznót megtámadta a tárgyhasználat helyett; távoli célnál nem
  tudta használni. → Tárgyhasználati feladatnál nincs harc; táskagombok Retail 12-ben
  (addon 0.9.48); hatótáv-hiba után közelítés.
- ✅ **Giant Boar:** nem ült fel rá. → „Ride/Mount/Board/Enter <unit>” felismerése.
- ✅ **A disznón utasként várt.** → Járműsáv exportja (addon 0.9.49), a jármű képességei
  kerülnek az akciósávra.
- ✅ **Monstrous Cadaver-eket nem támadta.** → VEHICLE_ABILITY készség; Trample előre-roham
  módban (célzás, majd nyomás).
- 🧪 **A saját disznó dobozát hitte célpontnak.** → Kamera-zoomtól és járműtől független
  saját-karakter felismerés (hover, forgás közben helyben maradó doboz, középső fókusz).
- ✅ **Kijelentkezés után nem ült vissza a disznóra.** → Újra felül, amíg a jármű-szakasz nyitott.
- ✅ **Lassú volt a disznós rész** (161 mp várakozás 310-ből). → Járműképesség nem vár a
  kijelölési „commitment”-re (161 → 36 mp).
- 🧪 **Elvesztette a célzott doboz követését** (alacsony confidence). → Forgás-korrekciós
  újrakötés; azonos helyen és méretben a gyengébb doboz is ugyanaz a célpont (felhasználói ötlet).
- ✅ **A szkriptelt leszállás után a disznót kereste.** → Állapotmentes visszaszállás-szabály;
  🧪 EXIT_VEHICLE készség, ha magától kell kiszállni.
- 🧪 **Egyedi célpont (pl. Torgok) halott → várjon a respawnra** (felhasználói szabály, max. 180 mp).

### Navigáció
- ✅ **Nem jutott be Torgok épületébe** (terep-magasság az épület alatt). → Bejárható szintek
  vizsgálata, a legrövidebb teljes út.
- ✅ **Nem jutott ki az épületből** (rossz kiinduló magasság). → A kiinduló szintet is vizsgálja.
- ✅ **A minimap-pötty felé indulva egy helyben állt** (az első útpont alatta volt). → Közeli
  útpontok kihagyása.
- ✅ **A távolabbi questre ment előbb** (egyenlő pontszám). → Valós távolság dönt.
- 🧪 **Kőbe ragadt, majd ugyanarra ment vissza.** → Akadály-jelölés és kitérő útvonal.
- 🧪 **Elhagyta a nyitott quest területét egy másik quest kedvéért.** → A területen belül
  más quest útvonala 120 mp-ig vár.
- 🧪 **Rossz minimap-pötty** (leadási „?” jelet és a kijelölt célpont jelét is quest-pöttynek vette).
- 🧪 **Kijelölt célpont minimap-jele** (képernyőn kívüli célpont iránya és távolsága).

### Telemetria, futás
- 🧪 **„telemetry suspended” megállás, miközben az adat folyt.** → A FAST csomag frissíti az élő-jelzést.
- 🧪 **Két agent futott ugyanarra a WoW-ra.** → A második nem indul el.
- 🧪 **Live capture-ök megtöltötték a lemezt.** → Csak a legutóbbi 3 szegmens marad.

### Helyi MI (Ollama)
- ✅ **Quest/képesség/beszéd szövegértelmezés** helyi modellel (qwen3:4b, GPU-n ~2 mp);
  csak bonyolultabb questeknél ad tanácsot (addon 0.9.51–0.9.52 adja a quest szövegét és a quest-adót).
- 🧪 **A quest saját szövegéből a leadó NPC neve** („Return to …”, „Speak with …”, „back to me”).

---

## 2026-10-03

### Quest-folyamat
- ✅ **A leadási ponton egy helyben toporgott** („?” keresés helyett újra és újra MOVE).
  → A pont közelében körbenézés és a környék bejárása.
- 🧪 **Leadott quest maradt az „elsődleges”**, és kiszűrte a többi quest lépéseit.
- 🧪 **Egy NPC két questet kínált, 38 mp-ig várt.** → Soronként felveszi; újra megszólítja, ha
  maradt quest (addon 0.9.42).
- 🧪 **Questek csoportosítása** (felhasználói kérés): előbb az egy helyen lévőket csinálja meg.
- ✅ **Kampány questek elsőbbsége** (felhasználói döntés; addon 0.9.44 kampány-jelző).
- ✅ **2 perces WAIT a quest-területen.** → A terület cellánkénti bejárása körbenézéssel.
- 🧪 **Felesleges MOVE a quest-területen belül** (minden kill után új út).
- ✅ **„Cook the meat on the campfire”** tárgyként jött, nem használta a tábortüzet. → Objektum-interakció.

### Harc, célpont, loot
- 🧪 **Slam-et soha nem használta** (Retail harcban titkosítja a cooldownt). → Saját
  cast-okból számolt cooldown (addon 0.9.42).
- ✅ **TARGET kattintás mellément** (a célpont kicsúszott a kurzor alól). → Hover → az addon
  megerősíti a GUID-ot → csak utána kattint (TARGET és LOOT).
- ✅ **Közelharcban álló kecskét nem támadta** (0 rage, nincs képernyő-doboz). → Auto-attack
  az interact billentyűvel.
- 🧪 **4,5 percig nem csinált semmit harcban** (a célpont képernyőn kívül). → Korlátos várakozás, majd újratervezés.
- 🧪 **„Target needs to be in front of you” → meghalt.** → Fordulási keresés támadással; harcban is támadhat.
- ✅ **Halál után megállt.** → Szellem-futás a holttesthez, feltámadás (addon 0.9.45).
- 🧪 **5/5 után is ölte a kecskéket** (a tooltip a kész sort is mutatta). → Kész sorok nem számítanak.
- 🧪 **Üres hullát próbált lootolni; a karakter alatti hullát nem találta.** → `lootable=false`
  figyelése; softinteract hulla az interact billentyűvel.
- ✅ **Tüske-disznót hoverezte, de nem jelölte ki** (a tooltipben a quest neve szerepelt). → Ez is quest-relevancia.
- 🧪 **Barátságos NPC-k és mások petje mellé tévedt.** → Aktív questnél csak a szükséges NPC.

### Teljesítmény, rendszer
- ✅ **Lassú agent (FAST ~14 Hz), óriási memória-adatbázis** (500 MB + 2,26 GB WAL). →
  Pillanatnyi állapotok nem kerülnek a DB-be; ~26 Hz.
- 🧪 **„Érvénytelen movement lease” hibák** (túl rövid fordulás, rossz sávon küldött egérmozgás).
- 🧪 **Ugyanazt az üres pontot hoverezte 11–12×.** → Változatlan nézetben 25 mp-ig kihagyja.
- 🧪 **Oszlop és kő közé szorult.** → Sorban kipróbált fizikai menekülési lépések.
- ✅ **A térkép nyitva maradt a leadási pontnál, ezért WAIT.** → CLOSE_MAP.
- ✅ **YOLO v10 modell** (újraellenőrzött címkék, creature mAP50 .43 → .68), alapértelmezett.
- 🧪 **Quest-terület a minimap kék körvonalából** (addon 0.9.43).
- 🧪 **AMD/Intel GPU:** DirectML-lel fut a YOLO (CPU 251 ms → 18 ms/kép).
