# Ismert hibák és gyenge pontok

Állapot: 2026-10-07. A **nyitott/lezárt feladatok hiteles állapota** a
[GitHub Issues](https://github.com/jani9921/Wowbot/issues) oldalon van. Az alábbi
részletes megfigyelések a 2026-10-06-i élő tesztek pillanatképét őrzik; nem
helyettesítik az issue-k aktuális státuszát. Forrás:
[docs/LIVE_VALIDATION.md](docs/LIVE_VALIDATION.md) és [BUGFIXES.md](BUGFIXES.md).

## Képességterületi GitHub-mérföldkövek

A [képességbecslés és bizonyítékai](docs/DOMAIN_PROGRESS.md) a régi M0–M27
kapukat történeti kiindulásként, a jelenlegi kódot és a friss élő futásokat
aktuális bizonyítékként kezeli. A GitHub natív progress bar csak a lezárt
issue-k aránya, nem a becsült készültség.

| Domain milestone | Nyitott feladatok |
|---|---|
| [Questing](https://github.com/jani9921/Wowbot/milestone/1) | [Ralia #1](https://github.com/jani9921/Wowbot/issues/1), [gubó #3](https://github.com/jani9921/Wowbot/issues/3), [quest-adók #4](https://github.com/jani9921/Wowbot/issues/4) |
| [Herbalism](https://github.com/jani9921/Wowbot/milestone/5) | [élő ciklus #20](https://github.com/jani9921/Wowbot/issues/20) |
| [Mining](https://github.com/jani9921/Wowbot/milestone/6) | [élő ciklus #21](https://github.com/jani9921/Wowbot/issues/21) |
| [Fishing](https://github.com/jani9921/Wowbot/milestone/7) | [élő ciklus #22](https://github.com/jani9921/Wowbot/issues/22) |
| [Vision](https://github.com/jani9921/Wowbot/milestone/3) | [kis NPC #12](https://github.com/jani9921/Wowbot/issues/12), [jelölt-kóválygás #13](https://github.com/jani9921/Wowbot/issues/13), [hamis ! #14](https://github.com/jani9921/Wowbot/issues/14), [hover #15](https://github.com/jani9921/Wowbot/issues/15) |
| [Skills](https://github.com/jani9921/Wowbot/milestone/8) | [loot #2](https://github.com/jani9921/Wowbot/issues/2), [item use #5](https://github.com/jani9921/Wowbot/issues/5) |
| [Combat](https://github.com/jani9921/Wowbot/milestone/9) | [GUID-váltás #6](https://github.com/jani9921/Wowbot/issues/6) |
| [Navigation](https://github.com/jani9921/Wowbot/milestone/2) | [Z resolver #7](https://github.com/jani9921/Wowbot/issues/7), [zóna-bejárás #8](https://github.com/jani9921/Wowbot/issues/8), [stuck #9](https://github.com/jani9921/Wowbot/issues/9), [minimap #10](https://github.com/jani9921/Wowbot/issues/10), [VMAP #11](https://github.com/jani9921/Wowbot/issues/11) |
| [World Model & Memory](https://github.com/jani9921/Wowbot/milestone/10) | [memóriaadatbázis #18](https://github.com/jani9921/Wowbot/issues/18) |
| [Runtime & Setup](https://github.com/jani9921/Wowbot/milestone/4) | [addon-csomagok #16](https://github.com/jani9921/Wowbot/issues/16), [TensorRT #19](https://github.com/jani9921/Wowbot/issues/19) |
| [Autonomy & Verification](https://github.com/jani9921/Wowbot/milestone/11) | [regressziós tesztek #17](https://github.com/jani9921/Wowbot/issues/17) |
| [Dungeon/PvE](https://github.com/jani9921/Wowbot/milestone/12) | [élő instance #23](https://github.com/jani9921/Wowbot/issues/23) |
| [PvP](https://github.com/jani9921/Wowbot/milestone/13) | [élő match #24](https://github.com/jani9921/Wowbot/issues/24) |

A lentebb felsorolt platformkorlátok és már élőben igazolt működések nem
automatikusan nyitott hibák. Új hiba esetén külön issue, reprodukció és
elfogadási feltétel kell; a részletes futási bizonyíték továbbra is a
`docs/LIVE_VALIDATION.md`-be kerül.

**Jelölés:** 🔴 hiba, nincs javítva · 🟠 gyenge pont / korlát · 🧪 javítva, de élőben még nem igazolt · ✅ élőben működik

---

## ⚠️ Átnézendő: Z resolver és a barlangos (többszintes) quest — működik, de nincs kész

A felhasználó döntése (2026-10-06 este): **a funkció működik, de átnézendő, átgondolandó, optimalizálandó.** A „Who
Lurks in the Pit” (55639) quest élőben végig lement (5/5 gubó → Hrun megölve → Ralia), de gyenge teljesítménnyel:
~13 perc, sok kézi beavatkozással (egyszer kézzel kellett arrébb vinni, a Ralia-repülést kézzel kellett indítani).
A 21:41-es futás hibái (részletek: `docs/LIVE_VALIDATION.md`):

- 🟠 Sok ismételt, eredménytelen lépés: 12 sikertelen helyi keresés (SEEK), 11 sikertelen hover-ellenőrzés (INSPECT),
  30× azonnal „sikeres” bejárási MOVE ugyanarra a pontra (🧪 javítva), 7× `ambiguous_player_layer` (🧪 4 mp türelem).
- 🟠 Felfelé nyílnál ugyanarra a padlóra ment (3 yd „feljebb”) a gubó párkánya helyett (🧪 javítva: legalább 6 yd, azaz
  egy emelet); ha több emelet is van fölötte, lépcsőzetesen megy fel.
- 🟠 Harc: a pók GUID-ja harc közben kicserélődik (…C54D3F → …454D3F), a DEFEND ilyenkor újraindul (~2 mp); a
  harcba-közelítést (VISUAL_APPROACH) és a MOVE-ot a „harc kezdődött” megszakítás azonnal leállítja.
- 🟠 Loot: többször „nem nyílt meg a loot ablak” / „nincs holttest”.
- 🟠 Az `input_blocked` (chat/menü fókusz) biztonsági okból MANUAL-ba kapcsol — kézi beavatkozás után újra kell indítani.
- 🔴 „Ride Ralia Dreamchaser”: lent kijelölte Raliát, de a megközelítés elvesztette; nem beszélt vele, a repülést kézzel
  kellett indítani. A végén fent (taxi után) ismeretlen magasság miatt vissza akart menni a gödörbe (🧪 javítva).
- 🟠 A Z resolver szabályai (folytonosság, esés, útvonal-tiebreak, próbaszakasz, `indoors`, emeletnyi különbség) sok
  élő esetre egyenként lettek foltozva — egységes átgondolás kell (lásd a zóna-térkép pontot lent).
- 🧪 **Quest-adó felvétele quest nélkül** (22:12): két „!” között ingázott; most 4 yd-ig megy, a soft-interact NPC-t
  szólítja meg, 10 mp-ig marad. Élőben még nem igazolt; ha a soft-interact rossz NPC-t ad, a pontonkénti egyszeri
  próbálkozás után a helyi keresés veszi át.
- 🧪 A teljes addon-állapot ritkán állt össze (ebben a futásban 199 / 4390 oldal), ezért a tooltip, a kredit és az
  események késtek — ez sok INSPECT-hibát és lassú reakciót okozott. Addon 0.9.58: minden állapot kétszer, sűrűbb
  oldalak (szimuláció: ~78 %). Ha élőben 95 % alatt marad: oldalanként 2 képkockás tartás (FAST ~20 %-kal ritkább).
  100 % elkapás nem lehetséges: amit a játék két képernyőfrissítés között rajzol, az egyik sosem jelenik meg.

## Navigáció, magasság (Z)

- 🧪 **Z resolver** (a karakter saját szintje és a célpontok magassága egy helyen: navmesh + VMAP + útvonal-elérhetőség
  + minimap-szintjelzés). Élőben működik a barlangos questen, de lásd fent: átnézendő.
- 🧪 **Leesés a spirálról:** az esést a következő minták alapján dönti el (ugrás ≠ esés), a lenti szintről tervez újra,
  a bejárás már elhagyott szakaszait átugorja; vízszintesen a célon, de más szinten nem forog tovább.
- 🧪 **Első szint-becslés barlangban, előzmény nélkül:** az addon `indoors` jelzése alapján a felszínt (peremet)
  kizárja; bizonytalan szintnél 12 yd-os próbaszakaszt megy, mozgás közben tisztul. Ha több barlangszint is
  lehetséges, az első szakasz rossz szintről is indulhat (falnak futásnál 4 mp után megáll).
- 🟠 **A minimap-pötty helye pontatlan** (néhány yard): a resolver ezért 8 yardos körzetben keresi a járható szintet.
- 🟠 **Falnak ütközés:** a „nem halad” állapotból lassan (10+ mp) lesz „elakadt”, a kiszabadító lépések későn indulnak.
- 🔴 **Egységes zóna-térkép hiányzik:** a quest-zóna bejárása egyetlen útvonalat követ (le, majd fel), nem a kék
  terület összes járható szintjét.
- 🟠 **Live Vision talajvonal** (útvonal a 3D képen) nincs kész, csak a sarokban lévő térkép.
- 🟠 **VMAP:** csak függőleges felületek; rálátás-ellenőrzés (LOS) és a mozgó/dinamikus objektumok (ajtók, gubók)
  ütközése nincs benne.

## Quest-tárgyak, játékobjektumok

- ✅ **Gubók és más quest-objektumok (pl. „Trapped Expedition Member rescued from cocoons”):** hover → friss addon-minta
  → jobb klikk → F7 tartalék; élőben 5/5 (21:41-es futás). „Too far” esetén közelít, mozgás közben megvárja a
  megállást (🧪). Teljesítmény: lásd a fenti „Átnézendő” részt.
- 🧪 **A teljes addon-állapot ritkán állt össze** (lásd fent, addon 0.9.58).
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
