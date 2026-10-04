# WoW Autonomous Agent — Használati Útmutató

## Mi ez?

Egy Python-alapú, önálló AI agent, ami egy **WoW Retail privát sandbox szerveren**
irányítja a karaktert vizuális észlelés (képernyő-elemzés) és egy WoW addon
(csak-olvasó szenzor) kombinációjával. Cél: magas szintű célokat ("questelj",
"menj el ehhez az NPC-hez") önállóan végrehajtani — nem workflow-t követ,
hanem tervez és dönt.

**Fontos, őszinte figyelmeztetés**: ez egy aktívan fejlesztés alatt álló
kutatási projekt, nem egy kész, polírozott termék. A viselkedése sokat
javult mostanában (célazonosítás, quest-elfogadás felismerése), de vannak
még ismert hibák és nem minden mechanikát tud (lásd lent). **Kizárólag
privát/sandbox szerveren használd, sosem hivatalos Blizzard szerveren** —
input-injektálás (billentyű/egér automatizálás) sérti a ToS-t élő szerveren.

## Szükséges dolgok

- **Python 3.13** (vagy közeli verzió)
- Python csomagok: a `requirements.txt` szerint (`numpy`, `opencv-python`,
  `Pillow`, `dxcam`, `ultralytics`, `lap`) plusz CUDA-s `torch`. A telepítő
  varázsló a hiányzókat telepíti.
- Egy futó **WoW Retail kliens** (Interface 120100), csatlakoztatva egy
  privát sandbox szerverhez, amin van karaktered.
- Windows (a projekt Windows-specifikus inputot és ablakkezelést használ).

## 1. Telepítés

### 1.0 Telepítő varázsló (ajánlott)

Indítsd el a projekt mappájában az `INSTALL_WIZARD.bat`-ot. Python nélkül
a `.bat` rákérdez a Python 3.13 telepítésére; utána újra kell indítani a
varázslót. A **Minden egyben telepítés** sorban végrehajtja a következőket,
és hiba esetén megáll:

1. Ellenőrzi a Python verzióját (legalább 3.11), a kiválasztott WoW
   `_retail_` mappát, a Retail 12.1.x verziót és az írási jogot.
2. Telepíti a hiányzó Python-csomagokat. NVIDIA esetén CUDA-s PyTorchot
   és TensorRT-t ellenőriz/telepít; AMD/Intel esetén az ONNX Runtime
   DirectML providert ellenőrzi/telepíti.
3. Frissíti az addont az `Interface\AddOns` mappában.
4. A `_retail_` mappában meglévő TrinityCore extractorokkal elkészíti
   a hiányzó maps, vmaps és Exile's Reach (2175) mmaps adatokat. Az
   extractorokat és a WoW klienst **nem** tölti le.
5. NVIDIA esetén a csomagolt YOLO `.pt` modellből helyi TensorRT `.engine`
   fájlt épít, ha még nincs. AMD/Intel esetén a csomagolt `.onnx`
   modell és a DirectML provider szükséges. GPU nélkül `.pt`/CPU a fallback.
6. Ellenőrzi az addont, a navigációt és a modellútvonalat; elmenti a
   `config\local_env.bat`-ot és a GUI mmap-beállítását, majd asztali
   parancsikonokat készít.
7. A Befejezés oldalon kiírja az agent CPU-s logikáját és a YOLO **várható**
   futási módját/modellfájlját (TensorRT, PyTorch CUDA, DirectML vagy CPU).
   A tényleges GPU-futtatás csak az agent indulási naplójával igazolható.

Az AUTO_START-hoz a fióknevet/jelszót külön kell megadni az Automatikus
indítás lapon; a jelszó titkosítatlan helyi fájlba kerül. Első indításkor
az addon exportjából bindings-cache készül. Kézi GUI-indításnál a PID-et
explicit ki kell választani.

### 1.1 Addon telepítése WoW-ba

A `addon\AIPlayerControllerExport\` mappa a **kanonikus** addon (a
`addon\AIPlayerControllerExport-12.1.0\` egy bájtra egyező, verziózott
másolata ugyanennek — nem kell mindkettőt telepíteni).

1. Másold be a `addon\AIPlayerControllerExport\` mappát a WoW kliens
   `_retail_\Interface\AddOns\` mappájába.
2. **Ne nevezd át** — a mappanév maradjon `AIPlayerControllerExport`.
3. Indítsd újra a WoW-ot (vagy `/reload` a karakterválasztás után).
4. Belépés után írd be: `/aipc status` — ha addon-adatokat ír ki
   (protokoll/verzió/frissítési ráta), az addon fut és exportál.

Hasznos `/aipc` parancsok:
- `/aipc show` — diagnosztikai panel
- `/aipc error` — utolsó addon-hiba kiírása
- `/aipc events` — esemény-puffer összegzés
- `/aipc rate 0.5` — snapshot-gyakoriság állítása (0.2–10 mp)

Az addon **csak-olvasó szenzor** — nem mozgat, nem nyom gombot, nem dönt
semmiről. Minden akciót a Python oldal hajt végre, Windows-szintű
billentyű/egér inputtal.

### 1.2 Első próbálkozás — élő WoW nélkül

Mielőtt élesben tesztelnél, érdemes kipróbálni a **replay módot**, ami egy
rögzített játékmenetet játszik le, WoW futtatása nélkül:

```bash
output\REPLAY_AGENT.bat
```

Ez a `tests\fixtures\agent_quest_replay.jsonl` rögzített adatot dolgozza
fel, és `output\agent-replay\` alá írja az eredményt — jó módja
ellenőrizni, hogy a Python-oldal egyáltalán elindul-e nálad.

## 2. Élő futtatás

1. Indítsd el a WoW-ot, jelentkezz be a karaktereddel (privát szerver!).
2. Futtasd:
   ```bash
   output\START_AGENT.bat
   ```
   (ez a `tools\run_agent.py --gui`-t indítja el egy grafikus felülettel)
3. A GUI-n válaszd ki a WoW folyamatot (PID), ha többet talál, majd töltsd be
   az ehhez a klienshez frissen ellenőrzött bindings-cache-t. A batch szándékosan
   nem tölt be régi PID-et/cache-t és mindig MANUAL módban indul.
   A **TrinityCore mmaps** mező a `_retail_\mmaps` mappát mutatja (a
   telepítő varázsló generálja és állítja be). Exile's
   Reach world instance azonosítója 2175; az mmap csak igazolt, azonos
   instance-beli `WORLD_YARDS` végpontok között aktiválódik.
4. Két mód van:
   - **MANUAL** — az agent csak figyel, nem avatkozik be. Biztonságos alap.
   - **FULL_AI** — az agent önállóan irányítja a karaktert (mozgás, kamera,
     célválasztás, interakció). **Csak akkor kapcsold be, ha a WoW ablak
     aktív/előtérben van** — ha elveszti a fókuszt, az agent magától
     visszavált MANUAL-ba (biztonsági megállás).

A karakter viselkedését a GUI-n és/vagy közvetlenül a játékban figyelheted.

## 3. Debug-naplózás (opcionális, de hasznos)

Egy **külön ablakban/terminálban** indítva folyamatos, részletes naplót ír
minden tickről:

```bash
output\START_LIVE_DEBUGGER.bat
```

Ez a `tools\live_debug_monitor.py`-t futtatja, ami az agent állapotát
(`output\agent\pid-<PID>\agent_status.json`) figyeli és minden változást
kiment ide:

- `output\live-debug\live-debug-<időbélyeg>.jsonl` — soronként egy
  állapot-pillanatkép (mód, döntés, eredmény, célpont, quest állapot, stb.)
- `output\agent\pid-<PID>\live-captures\<időbélyeg>\` — screenshot-ok
  (`manifest.jsonl` + `.jpg` fájlok) kulcsfontosságú pillanatokról
  (állapotváltozás, "critical" jelölésű események, heartbeat)

Ezek nélkül is működik az agent — ez csak utólagos elemzéshez/hibakereséshez
kell.

### 3.1 Session offline visszajátszása (replay) — kell hozzá az addon?

2026-09-14 óta a `START_LIVE_DEBUGGER.bat` **egy harmadik fájlt is ír**:

- `output\live-debug\telemetry-<időbélyeg>.jsonl` — minden tickhez egy sor
  `{"at": ..., "state": ...}`, ahol `state` pontosan az az adatszerkezet, amit
  az agent élőben az addontól kap (`world.player`). Ez **közvetlenül**
  visszajátszható a meglévő, tesztelt `wowbot.agent.runtime.replay()`
  függvénnyel — WoW/addon **nélkül**, teljesen offline:

  ```python
  from pathlib import Path
  from wowbot.agent.runtime import replay
  replay(Path("output/live-debug/telemetry-20260914-120000.jsonl"),
         Path("output/replay-check"), goal="Questelj")
  ```

  Ez megmutatja, mit döntött volna a **jelenlegi** (javított) agent-kód
  ugyanarra a rögzített helyzetsorra — hasznos, ha egy élő session után
  változtattunk valamit, és meg akarjuk nézni, hogy a fix tényleg másképp
  viselkedne-e, anélkül hogy újra be kellene lépni a WoW-ba.

  **Fontos**: ez csak az ettől a változástól kezdve rögzített sessionökre
  működik — korábbi `telemetry-*.jsonl` nem létezik, mert korábban ez az adat
  sehova nem lett elmentve.

- **A `live-captures\...\*.jpg` képernyőképek NEM alkalmasak erre.** Kipróbáltuk
  (`tools/screenshot_session_replay.py`, élő adaton tesztelve, lásd
  `docs/LIVE_VALIDATION.md`): a képek valóban tartalmazzák a dekódolható
  AIPC5 pixel-csík adatot, DE a debug-capture csak ~0.5 másodpercenként ment
  képet (a `runtime.py`-beli `agent_status.json`-írás ugyanezzel a 0.5s-os
  kapuval), ami túl ritka ahhoz, hogy egy több lapos (`STATE_Z`) telemetria-
  csomag összes lapját összegyűjtsük — valós, 180 képkockás szegmenseken
  0/180 esetben sikerült teljes állapotot összeállítani. A screenshotokból
  tehát **nem** lehet visszajátszást csinálni; a fenti `telemetry-*.jsonl` a
  működő megoldás erre a célra.

## 4. `data\` mappa — miért fontos

A `data\tdb_spawn_catalog.sqlite3` egy NPC-spawn-helyeket tartalmazó
adatbázis. Ezt használja az agent **utolsó mentsvárként**, ha vizuálisan
nem talál semmit (pl. egy ismert quest-adó ismert koordinátái felé indul
el). Ez a fájl szükséges a teljes navigációs képességhez — ha hiányzik,
az agent még mindig működik, csak ezt a fallback-lehetőséget veszíti el.

## 5. Tesztek futtatása

A projekt gyökeréből:

```bash
python -m pytest -q
```

Legutóbbi offline teljes regresszió: **776 passed, 3 skipped** (2026-09-16).
A kihagyott tesztek környezet- vagy opcionális-fixture függők. Ez nem élő
validáció és nem helyettesíti a kiválasztott PID-del végzett, felhasználó által
indított tesztet.

Két **opcionális** csomag további teszteket old fel, ha telepítve vannak
(`pip install lupa dxcam`) — nélkülük ezek a tesztek csendben kimaradnak
(skip), nem buknak el:
- `lupa` — valódi Lua-futtatás mockolt WoW API-val (`tests/test_agent_transport.py`),
  ami az addon Lua-kódját is közvetlenül teszteli, nem csak a Python oldalt.
- `dxcam` — az opcionális DXGI Desktop Duplication capture backend
  (`AIPC_CAPTURE_BACKEND=dxgi`, lásd `dxgi_capture.py` és
  `docs/LIVE_VALIDATION.md`) teszteléséhez.

### 5.1 World3D tracker A/B / visszaállítás

A tanított YOLO production útvonal alapértelmezetten BoT-SORT társítást
használ kameramozgás-kompenzációval. Diagnózishoz vagy gyors visszaállításhoz
indítás előtt állítható:

```powershell
$env:AIPC_WORLD3D_TRACKER = "BOTSORT"   # production alapértelmezés
$env:AIPC_WORLD3D_TRACKER = "BYTETRACK" # gyors A/B, nincs kamerakompenzáció
$env:AIPC_WORLD3D_TRACKER = "LEGACY"    # korábbi saját társítás
```

Egy futó agent ezt nem veszi át; a Python GUI/agent újraindítása szükséges.

## 6. Ismert korlátok (őszintén)

- A látás-pipeline (`World3D`) heurisztikákkal (szín/alak/pozíció) dolgozik,
  nem tanított neurális hálóval — időnként téveszt (pl. fát/sziklát
  vizsgál NPC helyett), bár ezt sokat javítottuk.
- Az élő bizonyíték részleges: egy első kill/loot és korábbi célazonosítás
  dokumentált, de a teljes Exile's Reach quest-folyam, több szakasz, leadás és
  jutalomválasztás nincs teljes körűen élőben validálva. Mélyebb mechanikák
  (dungeon, profession, PvP) sem élesben teszteltek.
- OCR (szöveg-felismerés) jelenleg nem elérhető ezen a gépen
  (`ocr_backend: unavailable` — Tesseract nincs telepítve).
