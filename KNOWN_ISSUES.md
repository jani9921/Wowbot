# Ismert hibák és gyenge pontok

Állapot: 2026-10-06. Forrás: az élő tesztek naplója ([docs/LIVE_VALIDATION.md](docs/LIVE_VALIDATION.md))
és a hibajavítások listája ([BUGFIXES.md](BUGFIXES.md)).

**Jelölés:** 🔴 hiba, nincs javítva · 🟠 gyenge pont / korlát · 🧪 javítva, de élőben még nem igazolt

---

## Navigáció, magasság (Z)

- 🧪 **Z resolver** (a karakter saját szintje és a célpontok magassága egy helyen: navmesh + VMAP + útvonal-elérhetőség
  + minimap-szintjelzés). Visszajátszáson jó, élőben még nem futott.
- 🧪 **Leesés a spirálról:** az esés után a lenti szintről tervez újra, a lefelé bejárás fenti szakaszait átugorja.
- 🟠 **Első szint-becslés barlangban, előzmény nélkül:** ha az agent a barlangon belül indul, az első becslés a terep
  alapján a felső szintet (peremet) választhatja (0,5-ös bizonytalansággal jelzi). Ajánlott fent indítani.
- 🟠 **A minimap-pötty helye pontatlan** (néhány yard): a resolver ezért 8 yardos körzetben keresi a járható szintet.
- 🟠 **Falnak ütközés:** a „nem halad” állapotból lassan (10+ mp) lesz „elakadt”, a kiszabadító lépések későn indulnak.
- 🔴 **Egységes zóna-térkép hiányzik:** a quest-zóna bejárása egyetlen útvonalat követ (le, majd fel), nem a kék
  terület összes járható szintjét.
- 🟠 **Live Vision talajvonal** (útvonal a 3D képen) nincs kész, csak a sarokban lévő térkép.
- 🟠 **VMAP:** csak függőleges felületek; rálátás-ellenőrzés (LOS) és a mozgó/dinamikus objektumok (ajtók, gubók)
  ütközése nincs benne.

## Quest-tárgyak, játékobjektumok

- 🔴 **Gubók és más quest-objektumok (pl. „Trapped Expedition Member rescued from cocoons”):** az agent nem nyitja
  ki őket. Az addon a „soft interact” célpontot csak egységekre exportálja, objektumra nem; a képfelismerés
  (YOLO) az objektumokat nem ismeri.
- 🧪 **Quest-tárgy használata célponton** (Re-Sizer, First Aid Kit): kijelölés → Interact Target → ha nem hat,
  odamegy és újra. Lehet, hogy élőben elsőre nem működik; a táskás használat tartalék.
- 🟠 **Célzókurzoros tárgyak:** az addon nem jelzi, hogy élesítve van-e a célzókurzor (`SpellIsTargeting`); az agent
  használat után ráklikkel a célpontra (ez feltevésen alapul).

## Kijelölés, hover, látás

- 🔴 **Kicsi NPC a képernyő szélén / felugró ablak alatt** (pl. Lindie, gnóm, 980×508-as kliensen): a YOLO nem látja,
  és a kijelölt, de doboz nélküli egységet az agent nem keresi újra → percekig áll vagy kóvályog.
- 🟠 **Megközelítés kis NPC-hez:** a „közel van” dobozméret (19 %) gnómnál nem jön el, túlmegy; tömegben a követés
  átcsúszhat más egységre.
- 🧪 **Gyorsabb hover/kijelölés** (csak a hover utáni adat számít, gyors kudarc, újra-hover) és az **egér előrevetítése
  mozgó trackre**: visszajátszáson és teszteken jó, élőben még nem.
- 🟠 **Kóválygás azonosítás miatt:** távoli ismeretlen alakokat egymás után megközelít, hogy kiderüljön, mik
  (pl. vadkan-keresés).
- 🟠 **Kliensméret:** 980×508 / 843×475 mellett a minimap szint-nyilai (▼/▲) nem láthatók; 1600×829-en az agent egyszer
  nem indult el (a pixelcsík állapot-oldalai hiányoztak) — az ok nem tisztázott.
- 🟠 **„!” felismerő:** a küszöb szándékosan alacsony (0,01), ezért halvány hamis „!” jelek előfordulnak.
- 🟠 **NPC neve csak hoverrel derül ki:** a WoW API nem ad képernyő-pozíciót a névtáblákhoz.

## Harc

- 🟠 **A harci cooldownok titkosak** a Retail 12-ben (az addon 0-t olvas); a saját varázslatokat az agent maga követi.
- 🧪 **NPC-utasítás követése** (Captain Garrick: „Charge at me again”): élőben nem igazolt.
- 🟠 **Kiképző quest felvétele után** 15 mp várakozás, mielőtt az NPC utasítást ad.

## Rendszer

- 🟠 **`agent_memory.sqlite3` mérete ~1 GB** (főleg hibakereső telemetria); a takarítás lassabb, mint a növekedés.
- 🟠 **A helyi nyelvi modell (Ollama)** nem indul automatikusan (a telepítő vagy a felhasználó indítja).
- 🟠 **TensorRT motor** kiválasztása fájl alapján, GPU-kompatibilitás ellenőrzése nélkül.
- 🟠 **Nagy Python-modulok** (800–880 sor) még nincsenek szétbontva.
- 🔴 **15 bukó teszt** (régebbi tervezési döntéseket rögzítő elvárások, felülvizsgálandók):
  - `test_agent_core.py`: `test_arrival_is_not_quest_completion`, `test_blocked_primary_move_uses_an_available_alternative`
  - `test_agent_runtime.py`: `test_complete_offline_quest_combat_loot_turnin_replay`
  - `test_camera_and_domain_1_0.py`: `test_camera_verification_waits_for_paged_snapshot_but_real_receive_loss_disarms`
  - `test_global_architecture_invariants.py`: `test_inv14_visual_local_search_has_finite_sector_and_time_budget`
  - `test_location_fallback.py`: `test_map_location_precedes_db_fallback`
  - `test_m0_search_skill.py`: `test_search_records_bounded_sector_coverage_then_reports_not_found`
  - `test_multistep_plan.py`: `test_kill_objective_builds_generic_verified_horizon_but_executes_only_first_step`
  - `test_persistent_movement_controller.py`: `test_reached_quest_poi_is_not_reissued_after_camera_observation_drift`
  - `test_quest_understanding_patch.py`: `test_confirmed_objective_location_wins_without_hypothesis_move`,
    `test_world_model_and_planner_use_low_priority_location_hypothesis`
  - `test_travel_reach_fallback.py`: `test_arrived_travel_without_credit_switches_from_move_to_bounded_local_search`,
    `test_new_quest_evidence_invalidates_old_arrival_fallback`, `test_transition_required_reach_searches_for_entrance_not_another_move`
  - `test_v5_m3_adaptive_quest_environment.py`: `test_agent_completes_adaptive_quest_and_discovers_follow_up`
