# Vision → tracker → döntés → skill audit (2026-10-07)

## Hatókör és bizonyítás

Forrás: a `projekt` mappa 2026-10-07-i olvasható kódja; ebbe az audit nem írt. Ez futásiút- és elágazásleltár, nem új élő WoW-teszt. Állapotjelölések: **K** = kódút összekötve, **O** = célzott offline teszt is futott, **R** = csak részleges/örökölt út, **H** = hiányzó éles producer vagy diszpécser. Egyetlen alábbi **O** sem jelent önmagában live validációt. A projekt követelmény-ledgerét nem minősíti át.

## A teljes vision–döntési határlánc

| Szakasz | Bemenet → kimenet | Elágazás, sikertelenség és autoritás |
|---|---|---|
| Capture | `agent/capture_worker.py` → megosztott latest-frame ring | Kiválasztott kliens/PID, capture-context/generation. Nincs képsor; újabb frame felülírhat régit. Capture-kieséskor a perception readiness lejár, nem bizonyított detekció. |
| Detektor-feed | `vision/world3d/capture_yolo_feed.py` → `FeedResult` | A worker a legújabb frame-en `World3DPerceptionV2.detect` és track-frissítést futtat, generation-váltásnál resetel. Adaptive/fovea kapcsolható, jelenlegi default full-frame. A detector Hz nem egyenlő a WorldModel/agent Hz-cel. |
| YOLO/backend | `vision/world3d/v2.py`, `process_yolo_backend.py` | 3-class modell: `creature_unit_like`, `quest_object_outline_like`, `overhead_symbol_like`; confidence/class és ROI szabályok. Backend timeout/hiba után nem szabad „friss objektumként” továbbítani régi eredményt. A több-GPU/más hardver élő validációja hiányzik. |
| Feed→V3 | `vision/world3d/v3.py` | Feed poll, pontos frame-cache lookup, `result.tracked` átvétele, patch propagáció, detector dropout grace, UI-modal külön út, fallback detektorfuture. **[#98](https://github.com/jani9921/Wowbot/issues/98):** cache-misskor nem az eredmény saját képével történhet az ankorozás. |
| Tracker 1 | feed BoT-SORT / V3 patch tracker | Detekció, GMC/kameramozgás, coasting, újraazonosítás és ID. Reset, kitakarás, modelmiss, gyors kamerafordítás eltérő hibamód; hosszú live ID-folytonosság még nyitott [#35](https://github.com/jani9921/Wowbot/issues/35). |
| Tracker 2 | `agent/visual_tracks.py` | Upstream ID elsőbbség, szűk vizuális/spaciális re-ID, EMA-szerű pozíció, legfeljebb 8 miss/1,2 s grace, elveszett track nem inspectable. A source-local ID nem NPC-GUID. **[#105](https://github.com/jani9921/Wowbot/issues/105):** üres batch nem lépteti ezt a source-trackert, és az aktív egyeztetésben nincs időkapu; hosszú kihagyás után is régi ID-t adhat új upstream tracknek. |
| Canonical | `perception_sources._run_canonical` → `world3d/pipeline.py` | Ritkább World3D batch: track/névtábla/szimbólum/questobjektum-relációk, ROI, negatív evidence, geometry. **[#104](https://github.com/jani9921/Wowbot/issues/104):** hirtelen eltűnt ACTIVE track history/lock maradhat. |
| Publikálás | `perception_cycle.py`, `perception.py` | `projection_revision` és TTL; `ready_for_action` friss, kész world-lane-t kíván, nem feltétlen pozitív detekciót. Empty candidate is valid. FAST közbeni visual control-lane külön publikál. Canonical aszinkron munkánál köztes batch eldobható, ami nem detector frame-vesztés. |
| Observation | `runtime_observation_phase.py` | WORLD3D, UI_CV, minimap/map, WORLD3D_LOCAL_VIEW, entity-memory és cross-view observation. Visual signature felismerés 1 s cache/track cache; **[#75](https://github.com/jani9921/Wowbot/issues/75)** reset utáni track-ID újrahasználat rossz névazonosságot örökölhet, **[#76](https://github.com/jani9921/Wowbot/issues/76)** stabilizáló history nem takarít megfelelően. |
| WorldModel | `world_state_projection.py`, `world_query.py` | Track, mouseover-GUID, target-GUID, saját avatar, minimap és quest state összevezetése. A doboz önmagában nem tényszerű NPC-név. **[#69](https://github.com/jani9921/Wowbot/issues/69):** `visual_tracks()` lejárt belief-ű jelöltet is visszaadhat. |
| Javaslat | `visual_inspection_planning.py`, `visual_search_planning.py`, `quest_target_planning.py`, `quest_objective_planning.py`, `combat_planning.py` | UNKNOWN → INSPECT/SEEK, GUID-hoz kötött cél → TARGET/VISUAL_APPROACH/INTERACT/OBJECT_USE stb. Saját avatart és pusztán predicted tracket nem szabad cselekvési célként használni. A symbol→NPC kötés támogatott, de rossz vagy hiányzó alany esetén nem azonosítja automatikusan Jainát. |
| Döntés | `planner.py` → `proposal_ranking.py` → `planning_orchestration.py` → autonomy/supervisor | Availability, confidence, cooldown, utility, commitment, safety, majd navigation/recovery adapter. **[#94](https://github.com/jani9921/Wowbot/issues/94), [#95](https://github.com/jani9921/Wowbot/issues/95)** jó jelöltből elutasított approach; **[#99](https://github.com/jani9921/Wowbot/issues/99)** SEEK felülrangsorolhatja a kész OBJECT_USE-t. |
| Input és visszacsatolás | `runtime/skill_executor.py` → `agent/engine.py` → dispatcher → `active_skill_supervision.py` → `verification_engine.py` | Csak FULL_AI és érvényes authority mellett ad inputot; az ACK nem siker. Az aktív skill ellenőrzi a friss postconditiont; timeout, identity/safety, UI error, replan/könyvelés külön ág. Az ismert FAST preemption és PID/fókusz kérdések [#70](https://github.com/jani9921/Wowbot/issues/70), [#77](https://github.com/jani9921/Wowbot/issues/77), [#78](https://github.com/jani9921/Wowbot/issues/78). |

Az overlay nem a döntési API: átmenetileg megjelenhet `OCCLUDED`/`LOST_TEMPORARY`, de ezek `inspectable=False`; a jelenlegi `WorldQuery` stale-szűrési hibája miatt az egységes „mindig egy szép box” nem garantál cselekvési biztonságot. Az ID-t csak stabil, friss, azonosságában megerősített jelöltként szabad felhasználni.

## A 44 SkillContract végrehajtási és verifikációs leltára

Rövidítések: **M0** = `M0SkillDispatcher`+dedikált `wowbot/skills` osztály; **N** = `NavigationService`/movement runner; **V** = Search/VisualApproach + visual runtime; **G** = `SkillRegistry.commands/verify` generikus út. Minden eredmény az `ActiveSkillSupervisor` és `VerificationEngine.confirm` felé jut, majd csak az `Agent._finish` könyveli. Az `available()` minden indítás előtt külön kapu. A „timeout” az attempt kontraktus/memory-verifikációs ablaka, nem minden esetben a nyers szerződés száma.

| Skill | Indítási út / input | Pozitív bizonyíték; negatív/újratervezési ág | Szint |
|---|---|---|---|
| WAIT | Planner/passive-wait külön ág; az engine nem telepít attemptet és nem küld inputot | Új evidence/budget után újratervezés; a megmaradt G `WAIT`-verifier örökölt kompatibilitási kód, nem az éles út. Ez nem quest-siker. | O |
| WAIT_EVENT | M0 `DefendWaitSkill`, álló monitor | Quest objective progress; harc/halál megszakít, időkeret után replan. | O |
| INSPECT | G, hover / kamerafordítás / map-zoom / map-step | Friss mouseover GUID vagy helyben új tooltip; üres hover mintavétel, hibás map-kontextus, deadline. | O |
| CAMERA_CONTROL | G, karakterfordítás/nézetparancs | Orientáció vagy hiteles kameramozgás; hiányzó változás timeout. | O |
| REACQUIRE_TARGET | G, nézetfordítás | Eredeti GUID vizuális újraazonosítása; önmagában kamerafordítás nem siker. | K |
| SEEK_VISUAL_CUE | V `SearchSkill`/`SeekVisualCueController` | Újazonosított jelölt/hover identity; szektor-/időkeret, map/context és trackvesztés. | O |
| MOVE | N, perzisztens bounded forward/turn | Cél- és útvonalállapot ellenőrzés; stuck/path/context/interrupt és recovery. | O |
| FOLLOW | N, leader/region követés | Követési régió elérése; leader/context/útvesztés és timeout. | K |
| REACH_OBJECT | N, kiválasztott GUID világpozíciója | Interaction range; GUID- vagy Z/route eltérés, stuck. Lásd #101 rokon entity-recovery utat. | O |
| REACH_LOCATION | N, explicit WORLD_YARDS referencia | Inspekciós régió elérése; referencia/map/Z/stuck/timeout. | O |
| TARGET | M0 `TargetSkill`, hover-confirm-click / utolsó target | Pontos GUID vagy elvárt név a target-telemetriában; mellékattintás, stale hover, identity mismatch. | O |
| ACQUIRE_TARGET | G, TARGETNEARESTENEMY; producer csak harc közbeni védekező fallback, nem quest-felderítés | Attackable target; nem bizonyítja a kívánt mob GUID-ját, ezért csak generikus akvizíció. | R |
| APPROACH_TARGET | G, perzisztens forward+turn | Ugyanazon GUID és harci action in-range; target-csere/timeout. | O |
| VISUAL_APPROACH | V, perzisztens visual servo | Friss, kötött vizuális célon támogatott range/anchor; trackvesztés, wrong identity, timeout; #94/#95 admission. | O |
| INTERACT | M0 `InteractSkill`, kijelölt GUID + interact | Quest/gossip/vendor UI vagy hiteles state-változás; OUT_OF_RANGE→világ-/vizuális approach, facing/LOS/identity/no-response. | O |
| TALK | Ugyanaz a M0 `InteractSkill` | UI/quest state; azonos recovery és failure ágak, külön kontraktus. | O |
| USE | **Nincs kanonikus M0 route**; G parancság fail-closed ValueError | G verifierben örökölt object/inventory/quest ág maradt, de éles diszpécser ezt nem éri el. Nem azonos az OBJECT_USE-zal. | H |
| OBJECT_USE | M0 `ObjectUseSkill`, pontos object+cursor hover→jobbklikk, F7/Interact fallback | Quest-credit az adott objective-hoz; stale cursor, identity, OUT_OF_RANGE, hiányzó credit; #99 döntési éhezés. | O |
| QUEST_DIALOG | M0 `QuestDialogSkill`, normalizált Accept/Turn-in/reward választás | Konkrét quest/dialog átmenet; wrong UI/quest/choice, timeout; #82 régi baseline-event téves siker. | O |
| FIELD_TURN_IN | M0 `FieldTurnInSkill` | Field-complete UI és quest-állapot; unsupported mode/wrong UI/timeout. | O |
| EXTRA_ACTION | M0 `QuestToolSkill`, pontos type+ID és binding | Adott quest-credit; eltérő action/target, OUT_OF_RANGE, timeout. | O |
| LOOT | M0 `LootSkill`, soft interact vagy corpse hover→jobbklikk, out-of-range approach | Loot event, inventory/item/quest-credit; nem lootolható/eltűnt corpse/range/timeout. #100 KILL-credit téves pozitív, #101 Z-s recovery. | O |
| DEATH_RECOVERY | G, addon popup koordináta | Spirit/ghost/dead flag átmenet; hiányzó állapot timeout. | O |
| GATHER | G, megerősített node jobbklikk | Inventory/resource event/quest objective; UI error/timeout. Éles input producer nem validált. | R |
| HERB | G, herb node jobbklikk | Mint GATHER, herb-confirm gate; domain még nem működő élő képesség. | H |
| MINE | G, ore node jobbklikk | Mint GATHER, ore-confirm gate; domain még nem működő élő képesség. | H |
| FISH | G, explicit fishing binding | Azonos spell ID `SPELLCAST_SUCCEEDED`; kapás/loot/quest teljes halászati sikerét nem bizonyítja. | H |
| COMBAT | M0 `CombatSkill`, kiválasztott GUID, képesség/autoattack + recovery | Célhalál vagy engagement utáni hiteles combat drop; range/facing/LOS/resource/target loss/death/stall/timeout. | O |
| ASSIST | M0 `UseItemSkill`, barátságos exact target + item | Quest-credit; identity, readiness, range/facing/LOS, timeout. | O |
| USE_ON_TARGET | M0 `UseItemSkill`, exact item+target; bar/inventory/interact source | Quest-credit; téves GUID/item, range/facing/LOS, timeout; #102 alternatív local ID. | O |
| FOLLOW_INSTRUCTION | M0 `InstructedSpellSkill`, NPC szöveg szerinti ismert spell | Spell/quest-credit; nem ismert utasítás, identity, cooldown, timeout. | O |
| DEFEND | M0 `CombatSkill`, mint COMBAT aktív fenyegetésre | Threat/target halál/combat drop; a COMBAT hiba-/recovery-ágai. | O |
| ESCAPE | G, explicit bounded binding | Combat megszűnik vagy HP nő; a távolság javulását ez a G verifier nem méri. | R |
| EXIT_VEHICLE | G, VEHICLEEXIT | `in_vehicle=False`; UI error/timeout. | R |
| VEHICLE_ABILITY | G, pontos vehicle-bar binding | Cast/cooldown/quest progress vagy karakteres előrelendülés; timeout. Külön `VehicleSkill` osztály nincs bekötve (#36). | R |
| MOUNT | G, ismert mount binding | `is_mounted=True`; casting/combat gate, UI error/timeout. | O |
| DISMOUNT | G, ismert binding | Mounted→unmounted; timeout. | O |
| CLOSE_MAP | G, toggle csak ha jelenleg nyitott | Fresh map-closed; toggle race/timeout. | O |
| OPEN_MAP | G, toggle csak ha jelenleg zárt | Fresh map-open; combat/cast gate/timeout. | O |
| RECOVER | G, explicit stuck-létra lépés, bounded strafe/back/turn/jump | Pozícióváltozás; ha nincs, új evidence/replan; nem önálló navigációs siker. | O |
| REPAIR | G, vendor repair koordináta | Javítási költség 0 vagy csökken; rossz vendor/UI/timeout. | R |
| BUY_VENDOR | G, adott vendor slot jobbklikk | Item nő, pénz csökken vagy quest-credit; hibás slot/money/UI/timeout. | R |
| OPEN_BAGS | G, OPENALLBAGS | `bags_open=True`; quest item és vendor külön admission, timeout. | R |
| SELL_VENDOR | G, safe item slot jobbklikk | Item csökken, pénz nő vagy quest-credit; quest/equippable/locked kizárás, timeout. | R |

Az „O” azt jelenti, hogy a mai 23 célzott fájl közül az adott út modulja szerepelt és a kódút olvasható; **nem** jelenti az összes kombináció/hibaág külön tesztjét. A `ResourceDomain`-nak van GATHER/HERB/MINE/FISH proposal-vázlata, de a szükséges éles producer/ground truth hiányos, így ezek továbbra sem felhasználói képességek. `USE` deklarált szerződés és örökölt generic kód, de a kanonikus dispatch kifejezetten kihagyja; jelenleg nem találtam éles proposalt sem. Ezt kompatibilitási résként, nem igazolt live regresszióként kezelem.

## Kontroll és nyitott bizonyítási kapuk

`py -3.13 -m pytest -q --disable-warnings --tb=line` a 23 idevágó vision/tracker/skill/verification tesztfájlra: **210 passed, 1 failed**. Az egyetlen bukó `test_m0_search_skill.py::test_search_records_bounded_sector_coverage_then_reports_not_found`: a teszt 0,5 s-es frissítések után 4 szektort vár, a jelenlegi `SeekVisualCueController.scan_step_interval=.90` mellett csak 2 jutott ki. Ez a mai kód és teszt ütemezési szerződésének eltérése; a teljes suite korábban is tartalmazott vizuális keresési cadence-bukást [#17](https://github.com/jani9921/Wowbot/issues/17). Nem bizonyítja, hogy a live keresés rossz ütemű.

Külön reprodukált új hiba: [#104](https://github.com/jani9921/Wowbot/issues/104) ACTIVE→üres batch után a `World3DPipeline._track_history` nem ürül, míg LOST_TEMPORARY→üres batch után igen. Ez belső history/lock állapotszivárgás, nem a Live Vision dobozainak közvetlen eltűnési oka. A javításnak bounded grace-t kell tartania a legitim kitakarás/re-ID miatt.

Külön reprodukált [#105](https://github.com/jani9921/Wowbot/issues/105): `VisualTrackManager.update("WORLD3D", [V3:1], t=1)` után 100 s üres source-szakasz és `update(...[V3:999], t=101)` esetén a második jelölt új upstream ID-vel is `WORLD3D:1` maradt (`UPSTREAM_REIDENTIFIED`). Az aktív track időkapuja és az üres batch-es miss-előrehaladás hiányzik. Ez átlépi az 1,2 s loss és 12 s retired re-ID policyt; konkrét live előfordulás nincs mérve.

**A rövid kameraelfordulás más eset:** azonos objektum rövid kitakarása után kifejezetten kívánatos ugyanaz a track-ID. A javításnak a rövid, kamera-kompenzált re-ID ablakot meg kell őriznie. Hosszabb eltűnésnél ugyanazt az entitást továbbra is fel lehet ismerni erős megjelenési, hely- és/vagy addon-GUID bizonyítékkal, de nem pusztán azonos képernyőpozícióval. A tartós entitásazonosság és a képkockák közti vizuális track-ID két külön bizonyítási szint.

Hiányzó elfogadási bizonyítékok: szinkronizált 24–30 Hz tartós live trace frame-sequence/detector/tracker/canonical/agent bontásban; kameraelfordulás utáni GUID-alapú azonosítás; üres detektor-batch utáni ID-élettartam; az egyes skillcsaládok minden typed failure→recovery→verified success útjának célzott tesztje; több-questes teljes éles futás kézi beavatkozás nélkül. A projekt mappába nem írtam, FULL_AI-t nem indítottam.
