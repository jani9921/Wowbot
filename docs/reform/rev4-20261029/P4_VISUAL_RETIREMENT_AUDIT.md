# REV4 P4 — a vizuális agent kivezetése: belépési pontok, maradék fallbackek, sorrend

2026-10-30, Claude. Felhasználói irány (AGENTS.md, 2026-10-30): fokozatosan ki
kell vezetni a vizuális felismerést és a rá épülő agent-viselkedést. Ez a
dokumentum audit és első lépés. A kivezetés **nincs kész**, és egy worker
kikapcsolása nem jelent kivezetést.

## 1. Profilfeloldás

`RuntimeProfile.resolve()` sorrendje:

1. explicit argumentum;
2. `AIPC_RUNTIME_PROFILE`;
3. `AIPC_SERVER_MODE=0` → LEGACY_VISION;
4. `AIPC_SERVER_MODE` megadva vagy `AIPC_PACKET_TELEMETRY=1` → SERVER;
5. különben **LEGACY_VISION**.

Közvetlen konstrukció (`AutonomousAgent(..., runtime_profile=None)`,
`WorldModel(..., runtime_profile=None)`) → **LEGACY_VISION**. Production-ben az
`AgentRuntime` mindig `resolve()`-ot hív, és a profilt továbbadja az agentnek.

## 2. Belépési pontok

| Belépési pont | Előtte | Most |
|---|---|---|
| `START_AGENT.bat` → GUI | SERVER (a packet-telemetriából kikövetkeztetve) | SERVER, explicit `AIPC_RUNTIME_PROFILE` (ha nincs megadva) |
| `START_AGENT_DXGI.bat` → GUI | SERVER (kikövetkeztetve) | SERVER, explicit |
| `START_AGENT_LIVE_VISION.bat` | SERVER (a telemetria miatt); a LIVE_VISION/YOLO változók **hatástalanok** | változatlan; félrevezető név, kivezetendő |
| `AUTO_START.bat` → `tools/wow_auto_start.py` → GUI `--auto-full-ai` | **LEGACY_VISION, packet inbox nélkül** | SERVER + `AIPC_PACKET_TELEMETRY=1` alapértelmezés (`setdefault`, felhasználói felülírás megmarad) |
| GUI `connect` | `RuntimeProfile.resolve()`; World3D-modell csak vizuális profilban | változatlan |
| `run_agent.py --replay`, `tools/replay_telemetry_decisions.py`, `agent/offline_replay.py` | `AutonomousAgent` alapértelmezés = LEGACY_VISION (offline, inputmentes) | változatlan; explicit profil kell, ha a replay a SERVER döntéseket hivatott mutatni |
| `START_WORLD3D_*`, `REVIEW_*`, `VIEW_UNITS_*` BAT-ok | dataset/annotátor eszközök, nem agent | a vision-csomaggal együtt kivezetendők |

Tesztek: `tests/test_packet_launchers.py` (+3).

## 3. Mit nem épít már a SERVER profil

`AgentRuntime(vision=...)` → `vision and profile.visual`. SERVER-ben nem jön
létre:

- PerceptionWorker / ProcessPerceptionWorker;
- World3D tanult detektor és YOLO-folyamat;
- LiveVisionMonitor;
- AutoLabeledExampleCollector, MapMarkerCropCollector;
- VisualPrototypeMemory;
- `SearchSkill`, `VisualApproachSkill` (`engine.py`).

A képernyő-capture (`AIPC_CAPTURE_*`) **marad**: az addon pixelcsíkjának
szállítása, nem világfelismerés.

## 4. Ami SERVER-ben még fut, csak utólag eldobjuk

A tervező SERVER-ben is legyártja a vizuális javaslatokat, a
`Planner.prefer_server_targets` → `vision_driven` pedig utólag szűri őket.
A szűrt halmaz:

- skillek: `VISION_SEARCH_SKILLS` (SEEK_VISUAL_CUE, INSPECT, OPEN_MAP,
  VISUAL_APPROACH, REACQUIRE_TARGET, CAMERA_CONTROL);
- `VISION_MOVE_PURPOSES` (minimap-pont, más szint, helyi keresés);
- pointeres TARGET.

Ha semmi más nincs, ebből lesz a „Szerver mód: …várok” WAIT.

Legalább 30 közvetlen gyártóhely (`Proposal.make` szó szerinti skillnévvel)
van 12 modulban:

| Modul | Skillek |
|---|---|
| `agent/visual_search_planning.py` (6) | SEEK_VISUAL_CUE |
| `agent/combat_planning.py` (4) | REACQUIRE_TARGET, VISUAL_APPROACH |
| `agent/object_interaction_flow.py` (3) | SEEK_VISUAL_CUE, VISUAL_APPROACH |
| `agent/quest_location_planning.py` (3) | SEEK_VISUAL_CUE |
| `agent/quest_target_planning.py` (3) | REACQUIRE_TARGET, SEEK_VISUAL_CUE, VISUAL_APPROACH |
| `agent/entity_objective_flows.py` (2) | SEEK_VISUAL_CUE |
| `agent/map_search_planning.py` (2) | INSPECT, OPEN_MAP |
| `agent/navigation_situation.py` (2) | OPEN_MAP, SEEK_VISUAL_CUE |
| `agent/visual_inspection_planning.py` (2) | INSPECT |
| `agent/escort_follow.py` (1) | SEEK_VISUAL_CUE |
| `agent/quest_objective_planning.py` (1) | VISUAL_APPROACH |
| `agent/travel_reach_fallback.py` (1) | SEEK_VISUAL_CUE |

Változónévvel épített javaslatok is vannak (pl. a `visual_search_planning`
INSPECT-ágai), így a szám alsó becslés.

Kockázat: ezek a döntések SERVER-ben is futási időt visznek. Egyes
mellékhatásaik a szűrés előtt állapotot módosíthatnak, ezt modulonként
ellenőrizni kell. A szűrés csak egy helyen véd.

## 5. Elvégzett első lépés: közös értéktípusok

- A `MapPoint` és a `WorldPosition` a `wowbot/coordinates.py`-ba költözött. A
  `wowbot.vision.models` ugyanazokat az osztályobjektumokat exportálja tovább
  (`isinstance` és a régi importok érvényesek).
- 14 navigációs modul és az `agent/navigation.py` importja átállt.
- A navigációban vision-import már csak a legacy vizuális
  megfigyelés-típusokra maradt (`NavigationVisionObservation`,
  `MinimapObservation`, `MarkerObservation`, `FeatureType`,
  `LocalWorldModel`). Ezek a vizuális térkép-gráf/helyi világ moduljaiban
  vannak (`engine`, `graph_builder`, `local`, `spatial_context`,
  `local_world_bridge`), és velük együtt vezetendők ki.
- Határteszt: `tests/test_shared_coordinate_values_20261030.py`.

## 5b. Második lépés: SERVER-ben nem készül vizuális javaslat (részben kész)

Közös jelző: `server_mode.server_profile(state)`, azaz
`state["runtime_profile"] == "SERVER"`. A WorldModel strukturált (SERVER)
projekciója állítja be; LEGACY_VISION állapotban nincs ilyen kulcs.

Az elv: a SERVER kimenet egyezzen meg a mai „legyártjuk, majd kiszűrjük”
kimenettel, csak a vizuális javaslat ne készüljön el. Ahol egy vizuális
`return` lezárt egy ágat (például elért keresési terület), ott SERVER-ben
`return []` van, nem továbbfutás. Két szándékos viselkedésváltozás van:

1. **Térképes lépés → TDB-fallback (hibajavítás).** SERVER-ben a
   `WorldMapFallbackPolicy` a térkép-CV lépést eleve lezártnak veszi
   (`exhausted=True`, `allow_db_fallback=True`).
   - Előtte az OPEN_MAP elkészült, a szűrő eldobta, a térkép sosem nyílt
     meg, és a lépés sosem zárult le.
   - Így a kijelölt célpont TDB-spawn fallbackja és a TDB questgiver-hely
     fallback (`INSPECT_REFERENCE_LOCATION`) SERVER-ben soha nem
     kapcsolhatott be.
   - Ennek a nyoma a 10-28-as „Több adat szükséges…” /
     `unavailable_skills: OPEN_MAP` várakozás.
   - Nyitott térképnél nincs CV-szkennelés és szülőtérképre lépés:
     egyenesen CLOSE_MAP jön.
2. **Jármű-cél (`combat_planning._vehicle_attack`).** A képernyős
   VISUAL_APPROACH helyett a meglévő következő ág fut: MOVE a cél becsült
   world-helyére.

SERVER-ben már nem készül:

- `Planner.inspections` (World3D/minimap/térkép-CV INSPECT);
- `VisualSearchPlanningPolicy` (SEEK) — a bemeneti javaslatok változatlanul
  mennek tovább;
- OPEN_MAP (`add_quest_fallbacks`);
- REACQUIRE_TARGET, SEEK körbenézés, VISUAL_APPROACH a kijelölt barátságos
  célpontra (`quest_target_planning`);
- REACQUIRE_TARGET és két VISUAL_APPROACH (`combat_planning`);
- a leadási-pont SEEK és az elért keresési terület SEEK
  (`quest_location_planning`);
- a régi escort SEEK-reacquire (`escort_follow`; a szerveres kísérést az
  `escort_planning.EscortPolicy` végzi).

**2b — a maradék gyártóhelyek is őrzöttek:**

| Hely | SERVER-ben |
|---|---|
| `quest_location_planning` – elért SPEAK/KILL terület, elért objektum-terület, elért TRAVEL terület | `return []` (ugyanúgy lezárja az ágat) |
| `quest_location_planning._minimap_dot_local_search` | nem hívódik |
| `object_interaction_flow.propose_object_steps` – VISUAL_APPROACH és dobozos SEEK | nem készül; a soft-target alapú OBJECT_USE marad |
| `quest_objective_planning._item_target_approach` – képernyős VISUAL_APPROACH | helyette a meglévő world-pozíciós MOVE (`APPROACH_ITEM_TARGET`) fut |
| `navigation_situation.adapt` | már korábban is `server_mode_selected` alapján visszatért |

Szerkezeti teszt (`test_every_visual_proposal_producer_is_server_gated`): az
`agent/` minden olyan függvényének, ami szó szerinti vizuális skillnévvel
javaslatot gyárt, SERVER-őrfeltételt kell tartalmaznia. Kivétel csak a
tisztán vizuális modul és a hívónál őrzött segédfüggvény, indoklással
felsorolva.

A `vision_driven` utólagos szűrő biztonsági hálóként marad, amíg a
LEGACY_VISION profil él.

Tesztek: `tests/test_server_no_visual_proposals_20261030.py` (8).
Bizonyítékok: [visual-retirement-step2-evidence](visual-retirement-step2-evidence/source-verification.json).

- Kijelölt kör: **4111 passed, 2 skipped, 10 változatlan deselection,
  exit 0**.
- Teljes teszttár: 5780 passed, 5 skipped, **16 failed**, változatlan
  hibalista a lépés előtti futáshoz képest.
  - 14 közülük ugyanaz a lista, ami 10-28-án, a REV4 előtt is fennállt.
  - 2 (`test_procedural_sensor_memory`) a 4083-as baseline-on is ugyanígy
    bukik (fájlszinten ellenőrizve).
  - A teljes tár nem futtatható a baseline-zipből, mert hiányoznak belőle a
    tools/data/runtime fájlok.

## 5c. Harmadik lépés: nincs hover-célzás SERVER-ben (2026-10-31)

Paritás-audit:

- A tervező SERVER-ben már nem ad pointeres TARGET-et
  (`server_mode.pointer_target`), és nem ad holttest-horgonyos LOOT-ot
  (`combat_planning`, `server_mode_selected`).
- A SERVER projekció (`_structured_only`) nem ad `target.screen_position`-t,
  `confirmed_mouseover_anchors`-t vagy `visual_candidates`-t.
- A skillek hover-ágai tehát csak az adat hiánya miatt nem indultak el,
  explicit döntés nem volt mögöttük.
- Ha mégis elindultak, a dispatcher `pointer_gate`-je csendben eldobta a
  HOVER/POINTER parancsot, a skill pedig a teljes határidőig várt egy
  megerősítésre, ami sosem jött.
- A kiváltó utak megvannak:
  - Tab (`TAB_SERVER_GUID`, `TAB_DEFEND`, `TAB_FRIEND_RESCUE`);
  - Interact/F7 (`INTERACT_KEY_PACKET`, soft-interact holttest és objektum,
    `ServerLootPolicy`);
  - GUID-ellenőrzött `INTERACTTARGET`.

Közös jelző: `skills/hover_confirm.pointer_acquisition_retired(world_state)`,
ami a SERVER profilt jelenti.

| Hely | SERVER-ben |
|---|---|
| `hover_confirm_step` | azonnal `FAILED`, egérmozgatás nélkül |
| `live_track_point`, `pointer_tracking.live_pointer_point` / `follow_pointer` | nincs képernyős célpont, nincs POINTER |
| `TargetSkill.begin` | nincs HOVER; a képernyős CLICK / CLICK_CURRENT_CURSOR helyett `LOW_CONFIDENCE`, `pointer_acquisition_retired`; a Tab és a TARGETLASTTARGET marad |
| `InteractSkill.begin` / REACQUIRE | nincs hover-pont: közvetlen GUID-ellenőrzött `INTERACTTARGET` |
| `LootSkill.begin` holttest-horgony | `CORPSE_NOT_FOUND`, `pointer_acquisition_retired`; a soft-interact Interact előtte marad |
| `CombatSkill` cél-visszaszerzés és auto-attack hover | nem indul; a meglévő STARTATTACK / újratervezés jön |
| `UseItemSkill` jobb klikk | a `live_track_point` miatt nem indul |

Szándékosan marad az OBJECT_USE ugyanarra a pontra küldött HOVER-je. A
`begin()` csak akkor fogad el pontot, ha az legfeljebb 0,002-re van a kurzortól,
vagyis a HOVER nem mozgatja az egeret, csak friss addon-mintát kér a jobb klikk
előtt. Ez a kurzor alatti, addon-tooltippal igazolt objektumhasználat, nem
vizuális felismerés. Kivezetése az objektum-F7 paritás élő igazolásához
kötött.

Szerkezeti teszt: `test_every_skill_pointer_aim_is_server_gated`. A
`skills/` minden HOVER/POINTER parancsot gyártó függvénye őrzött, vagy
indoklással szerepel a kivételek között.

Tesztek: `tests/test_server_no_hover_acquisition_20261031.py` (6). Kijelölt
kör: **4117 passed, 2 skipped, 10 változatlan deselection, exit 0**.

## 5d. Launcherek: halott vizuális alapértékek (2026-10-31)

A `runtime_vision_composition` a LIVE_VISION/YOLO/World3D env-változókat csak
vizuális profilban olvassa, így SERVER-ben hatástalanok voltak.

- Kikerültek a `START_AGENT.bat`, `START_AGENT_DXGI.bat`,
  `START_AGENT_LIVE_VISION.bat` és `tools/wow_auto_start.py`
  alapértékei közül.
- A capture (`AIPC_CAPTURE_BACKEND=dxgi`, `AIPC_CAPTURE_PROCESS=1`) marad:
  ez az addon-pixelcsíkot szállítja.
- A `START_AGENT_LIVE_VISION.bat` csak a meglévő parancsikonok miatt maradt
  meg a régi néven. Eddig is SERVER-re oldódott fel, mostantól ezt
  kimondja (`AIPC_RUNTIME_PROFILE=SERVER`).
- Explicit LEGACY_VISION env-vel a kód saját alapértékei érvényesek.

Tesztek: `tests/test_packet_launchers.py` (+5: három launcher SERVER-t mond,
egyik sem állít vizuális alapértéket, és az unattended start sem).

## 5e. Importhatár: a SERVER út nem tölt be vision-modult (2026-10-31)

Importgráf-próba külön folyamatban. Lépései:

1. a SERVER agent/runtime/world/planner/navigation/skills/dispatcher/GUI
   modulok betöltése;
2. egy SERVER WorldModel ingest;
3. egy planner-kör.

Előtte betöltődött:

- `wowbot.vision.entity_memory`;
- `wowbot.vision.map_mouseover`;
- `wowbot.vision.models`;
- a numpy-s `wowbot.vision.minimap_quest_area`.

Egyik sem volt vizuális szerep:

| Érték | Új hely | Régi modul |
|---|---|---|
| `EntityMemory`, `EntityMemoryProfile` (addon-megerősített entitás-memória) | `wowbot/entity_memory.py` (a logger neve a régi marad) | ugyanazokat re-exportálja |
| `classify_tooltip`, `normalize_map_mouseover`, `MapMouseover` (addon-tooltip) | `wowbot/map_mouseover.py` | re-exportál |
| `offsets_to_world` (tiszta minimap-geometria) | `wowbot/coordinates.py` | re-exportál |
| `MapMarker` (térkép-CV marker) | marad; a `world_query.map_markers` lustán importálja | — |

Most a SERVER útban nincs `wowbot.vision*` modul, nincs legacy vizuális
navigációs modul (`navigation/engine`, `graph_builder`, `local`,
`spatial_context`, `local_world_bridge`), és nincs numpy/cv2/torch.

Tesztek: `tests/test_server_imports_no_vision_20261031.py` (2).

A coverage-sorok szövege a régi modulútvonalakat idézi. Ezek a re-exportok
miatt érvényesek maradnak, a sorok változatlanok.

## 6. Javasolt kivezetési sorrend (inkrementális, mindegyik után teszt)

1. **[KÉSZ, offline, 5b] Gyártás SERVER-ben:** a 4. pont moduljai SERVER profilban ne is
   gyártsanak vizuális javaslatot (a profil a state-ben:
   `runtime_profile`). Az utólagos szűrő biztonsági háló marad, amíg a
   legacy profil él. Modulonként: kiváltó szerveres út megvan-e.
   - SEEK/INSPECT/OPEN_MAP → szerver-entity / POI / TDB-zóna;
   - VISUAL_APPROACH → typed `move_to_entity`;
   - REACQUIRE_TARGET → GUID / Tab.
2. **[KÉSZ SERVER-ben, offline, 5c] Vizuális hover-célzás:** `skills/hover_confirm`, a `HOVER` ágak a
   target/interact/loot/object_use/combat skillekben,
   `agent/visual_approach_command`, `vision_seek`. Csak a szerveres/F7/Tab út
   paritása után. A LEGACY_VISION kód még megvan; törlése az 5. ponttal megy.
3. **[RÉSZBEN, 5d] Legacy profil és belépési pontok:** `START_AGENT_LIVE_VISION.bat`, a
   LIVE_VISION/YOLO env-alapértékek a launcherekben és a
   `wow_auto_start`-ban (**kész**), `runtime_vision_composition`, a perception
   worker/process, a vision-dataset gyűjtők, a GUI World3D-modellútja (ezek
   csak LEGACY_VISION-ben épülnek; a törlésük az 5. ponttal megy).
4. **[ELŐFELTÉTEL KÉSZ, 5e] Vizuális navigációs modulok:** `navigation/engine`, `graph_builder`,
   `local`, `spatial_context`, `local_world_bridge`. Csak ha a SERVER út
   egyiket sem importálja (importgráf-próba). Az importgráf-próba igazolja, hogy
   nem importálja. Production importőrük nincs; a tesztjeik és a coverage-
   sorok (V4-024, V4-027, DESIGN-029, DESIGN-081) hivatkoznak rájuk. A
   tényleges eltávolítás felhasználói jóváhagyást kér, mert fájlokat és teszteket
   töröl (Lomtárba), és a 4083-as checkpoint modullistáját is érinti.
5. **A `wowbot/vision` csomag, a dataset/annotátor eszközök és a
   függőségek** (YOLO/torch/OpenCV), a tesztjeikkel együtt.

Nem része: az addon strukturált UI-adata és a pixelcsík-transzport. Ezek a
selected target, soft recipient, actionbar/range, quest/gossip UI miatt
kellenek, amíg nincs igazolt nem vizuális paritás.

## 7. Állapot

- Széles regresszió a 2. és 5. pont után: **4103 passed, 2 skipped,
  10 változatlan deselection, exit 0**.
- AST: 561 source és 637 test fájl. A 203 sor változatlan. Az addon és az
  Ymir-pin változatlan.
- Bizonyítékok: [visual-retirement-step1-evidence](visual-retirement-step1-evidence/source-verification.json).
  A launcherek a baseline-zip hatókörén kívül esnek, ezért külön hash-lista
  van róluk.

- Audit, közös értéktípusok, explicit SERVER belépési pontok: OFFLINE_TESTED.
- A 6. pont 1. lépése (SERVER nem gyárt vizuális javaslatot): OFFLINE_TESTED, 5b.
- A 6. pont 2. lépése SERVER-ben: OFFLINE_TESTED, 5c.
- A 3. lépés launcher-része: OFFLINE_TESTED, 5d.
- A 4. és 5. lépés előfeltétele (importhatár): OFFLINE_TESTED, 5e.
- A legacy vizuális kód tényleges törlése: nincs megkezdve. Ehhez felhasználói
  jóváhagyás kell.
- Élő ellenőrzés: nincs. Élőben figyelendő:
  - SERVER-ben nem marad hover-várakozás. Ahol korábban egy skill a
    határidőig várt egy eldobott HOVER megerősítésére, ott most azonnal
    `pointer_acquisition_retired` vagy kulcsos út jön;
  - a TDB-fallback mostantól SERVER-ben is bekapcsolhat
    (`INSPECT_REFERENCE_LOCATION` REACH_LOCATION és a selected-target
    REACH_OBJECT DB-spawn);
  - a jármű-cél és a távoli quest-item célpont képernyős követés helyett
    world-pozíciós MOVE-ot kap.
