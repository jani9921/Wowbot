# REV4 P8.5 — különesetek leltára és kivezetése

2026-11-02, Claude. Cél (P8 terv): minden beégetett quest- és helyzetág vagy a
quest-gráfba (playbook-mechanikába) kerül, vagy törlődik.

## 1. Kódszintű quest-, NPC- és térkép-ID-ágak

Keresés a `src/wowbot` alatt:

- `entry_id`, `npc_id`, `object_id`, `quest_id`, `spell_id`, `item_id`,
  `map_id`, `ui_map_id` és `instance_id` összevetése 3–6 jegyű literállal;
- literál ID-halmazok és -táblák;
- név szerinti összevetések (Wrathion, Sabellian, Edress, Kavia, Rellid,
  Garrick, Fao, Meredy, Hogger stb.).

**Eredmény: nincs ilyen elágazás.** A találatok:

| Hely | Mi az | Döntés |
|---|---|---|
| `combat/ability/catalog.py` (23922 …) | Képességkatalógus, spell-ID → szabály | Marad: harci adat, nem quest-ág. |
| `packetio/opcodes_12_1.py`, `pkt_dump_import.py` (70340, 70575, 69214, 70448) | Kliensbuild → opcode-tábla | Marad: protokollverzió. |
| Kommentek (pl. 26209, 427169, 187158) | Élő esetek dokumentációja | Marad: magyarázat, nem feltétel. |

## 2. Quest-specifikus adatfájlok

| Fájl | Mi az | Döntés |
|---|---|---|
| `data/quest_scene_bindings.json` | 4 felülvizsgált kapcsolat: Skyriding-tréning quest → kliens SceneScript csomag (65118, 65120, 65133, 77345) | **Marad, referenciaadatként.** Sem DB2, sem TDB nem köti a questet a scene-csomaghoz. A futás csak akkor használja, ha az aktív quest, az instance és az objective mennyisége egyezik. Ez adat, nem kódág. |
| `data/skyriding_courses.json` | Kurzus-pályák (gyűrű-találati sugár, útvonal) | **Marad, referenciaadatként**, ugyanezen okból. |

## 3. Mechanikánkénti kezelők és a gráf

Minden helyzetfüggő policy egy playbook-mechanika lépése
(`quests/playbooks.PLAYBOOKS`). A 8.5-ben a gráf megkapta azokat, amelyek
eddig „csak leírt” jelölést viseltek:

| Policy (agent/) | Mechanika (playbook) | Lépések |
|---|---|---|
| `escort_planning.EscortPolicy` | ESCORT (új könyv) | TALK → DIALOG → FOLLOW → DEFEND (a kísért egység támadói) → RESTART (elbukott quest eldobása) |
| `emote_planning.EmotePolicy` | EMOTE (új könyv) | APPROACH → TARGET → EMOTE (ADDON_ACTION) |
| `container_planning.ContainerOpenPolicy` | COLLECT_CONTAINER (új könyv) | OPEN_CONTAINER (OPEN_BAGS, USE_ON_TARGET) → LOOT |
| `objective_probes.ObjectiveProbeLadder` | SPELL_CREDIT, PROXY_UNKNOWN, UNRESOLVED, COLLECT_OTHER, CRITERIA_TREE (új könyvek) | APPROACH → PROBE (gossip-NPC-k, majd használható POI-objektumok, mindegyik egyszer) → OBSERVE |
| `arrival_targets.ArrivalTargetPolicy` | ARRIVE, AREA_TRIGGER | APPROACH |
| `objective_speech_planning.ObjectiveSpeechHold` | TALK, WITNESS | TALK → DIALOG → OBSERVE (beszéd- és beszélgetés-tartás) |
| `rescue_object_planning` | OBJECT_USE (mentés) | APPROACH → USE_OBJECT |
| `directed_item_planning` | USE_ITEM (kúp) | APPROACH → TARGET → USE_ITEM |
| `server_kill_planning`, `server_loot_planning` | KILL, COLLECT_DROP | APPROACH → TARGET → FIGHT → LOOT |
| `server_npc_planning`, `quest_dialog_planning` | TALK, GOSSIP_ACTOR, CREDIT_OBJECT | TALK → DIALOG … |
| `vehicle_combat_planning`, `scripted_ride_planning`, `scene_path_planning` | SPELLCLICK_VEHICLE, VEHICLE_ABILITY, NPC_TRANSPORT | BOARD → VEHICLE / OBSERVE |

Továbbra is kezelő nélkül, típusosan jelölve: PET_BATTLE, PVP, RESOURCE,
LEARN_SPELL, OTHER.

A census lefedettsége (`objective_mechanics.COVERAGE`) ennek megfelelően
frissült: ESCORT, EMOTE, COLLECT_CONTAINER, ARRIVE, AREA_TRIGGER és az
ismeretlen forrásúak most PARTIAL (offline).

## 4. Tesztek

- A `test_quest_playbook_runtime_20261027` két tesztje tudatosan változott: a
  „csak leírt” lista most PET_BATTLE, PVP, RESOURCE és OTHER. A kísérés
  előrejelzése FOLLOW → DEFEND → RESTART, sosem KILL+LOOT a proxy-kreditre.
- Minden könyv minden lépés-skillje létező szerződés
  (`test_md_only_handlers_are_not_executable_capabilities`).

## 5. Élő igazolás

Egyik új könyvnél sincs még; a 26209 próbalétrája élőben igazolt
(2026-10-31).
