# Mező- és függőségi melléklet az architektúratervhez


## Forrásellenőrzött REV4 korrekció – olvasd el a régi fejezetek előtt

**Állapot:** a `src (2).zip` 498 Python-fájljának AST + statikus importgráf elemzése és a kritikus futási láncok forráshelyi ellenőrzése megtörtént. **Ez nem teljes függvényenkénti live audit**, és a ZIP nem tartalmazza a `tests/` fájlokat, a Lua addon producert vagy a natív Ymir producercsatornát. Az új célmodulok nem implementációk. A teljes új, pontos fájl→API→tulajdonos migrációs indoklás a `SRC_MELY_AUDIT_20261029_HU.md` dokumentumban van; a `SRC_498_MODUL_LELTAR_20261029.csv` csak statikus leltár.

**A legfontosabb új, kóddal alátámasztott döntések:**

1. A `navigation/flight_trip.py` és `flight_travel.py` **már be van kötve** a `navigation/global_planner.py:208–209` hívásba, ezért a travel redesign a működő mixed-flight út kiterjesztése, nem a nulláról új bekötés. A `flight_trip.TripPlan` még nem a végleges általános `TripLeg`-sorozat.
2. A `navigation/danger.py:100–175` és `spawn_threats.py` **már tartalmaz veszélyes mobkerülést**. A `RouteRiskEvaluator` az előrejelzett harcidő/HP-veszteség/aggro + flight/transition cost **új rétege**, ne második DangerMap legyen.
3. Az `agent/quest_graph.py:8–122` **már ismeri** az objective/quest dependency readiness-t; az új `QuestExecutionGraph` **belső mechanikalépéseket** ír le, nem lecseréli a questláncot. `quests/objective_mechanics.py` már aktív TDB/DB2 classifier, `agent/tdb_knowledge.py` fogyasztja.
4. `agent/engine.py:79–88` dinamikusan csatol nav oracle-okat WorldModelhez, és `tdb_locations.route_cost_oracle` **modulszintű globális metódushivatkozás**. Ezt explicit, példányonkénti porttá kell tenni a multi-PID izoláció érdekében.
5. `packetio/context.py:16–38` és `agent/runtime_packet_source.py:68–93` a mai packet bootstraphez addon-state-et követel; `agent/world.py:360–428` session ownershipja is az addon megfigyeléssel kapcsolódik össze. **Az addonmezőket addig nem lehet törölni**, amíg új bootstrap + field parity + input/UI regression nincs.
6. A fő `agent/runtime.py:356–362` **jelenleg is hívja a vizuális update-et**, a `skills/combat.py` és `agent/target_manager.py` is tartalmaz visual-track alapú logikát. A no-vision runtime csak consumer-szintű kivezetéssel készül el.
7. Az importgráf szerint `agent.models`-ra 196 modultól jön hivatkozás; egy 32-modulos import-SCC mutat erős összekapcsoltságot. **Előbb szerződések és átmeneti facade-ok, később a fájlmozgatás.**
8. `execution/command_dispatch.py` és `agent/executor.py` megtartja az **egyetlen input authorityt**, az ACK ≠ világállapot-siker elvet, a PID, foreground, bindings, watchdog védelmeket. Az új Travel/Combat/Quest modulok nem kerülhetik meg.

**Külön ellenőrzött source-különbségek:** `world_packet_reducer.py:677–740` még addonstate-ből egészíti ki a saját packetes pozíció-/instance- és mapkörnyezetet; a teljes packetes quest-POI-tárolóból a fogyasztóknak csak a turn-in blobokat teszi ki. A `danger.py:50–65` veszélyprovenance címe fix `ADDON_TELEMETRY`, ezért ezt mezőszinten javítani kell a risk-kalkuláció előtt. Ezekből önmagukban nem következik live hiba, de migráció előtti tesztesetek.

**Ajánlott függőségi ütemezés:** `P0 baseline/trace → P1 contracts + DI + oracle isolation → P2 session bootstrap → P3 addon/packet mező parity → P4 no-vision runtime → P5 leg-based Travel/Transition → P6 RouteRisk → P7 Combat + roles → P8 mechanic-based Quest → P9 legacy cleanup/LLM calibration`. A régebbi T0–T8 ütemeket nem szabad automatikusan késznek vagy ennek megfelelőnek tekinteni.

---

2026. október 29. — kizárólag tervezési leltár. A táblázatok nem kapcsolnak ki forrást és nem jelentenek új live validációt.

**A felhasználó újabb iránya alapján a történeti specifikációk számozása nyomkövetési háttér. A fő terv elején szereplő tervezési felülvizsgálat érvényes: a végleges felelősségi és komponenshatárokat a mai cél és a működés indokolja; egy régi osztály vagy ledgerpont önmagában nem tesz kötelezővé egy jövőbeli modult.**

**Aktuális cél: packetes szerverállapot + strukturált addontelemetria. Nincs YOLO/OCR/World3D/VLM, passzív vizuális megfigyelés vagy vizuális fallback. A V4/Design vizuális elvárásai történeti anyagok. Az addon pixeltransportjának protokolldekódolása szükség esetén külön adatcsatorna maradhat.**

## A. A mai addon producermezőinek döntési táblája

A snapshotban 84 felső szintű producermező van, a FAST producerben 42 mező-hozzárendelés. Az összetett mezők részadatokat tartalmaznak; a táblázat ezeket kifejezetten szétválasztandónak jelöli. Ez a Lua producer leltára, nem állítás arról, hogy minden mező minden FAST-profilban, minden pillanatban átfér a transporton. A lapozás, méretkorlát és elhagyott mező továbbra is teljesség/frissesség kérdése. [Transport csomagolása](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/Transport.lua:136>)

A „megtartandó” a célállapotban indokolt helyi adatot jelenti. Az „átköltöztetendő” nem azt jelenti, hogy már ma törölhető: a jobb oldali kapu teljesítéséig az adatút hiányos lenne.

| Snapshotmező | Döntés | Célforrás és indok | Mai packetes korlát / kiváltási kapu |
|---|---|---|---|
| [protocol_version](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2482>) | MEGTARTANDÓ | Addoncsatorna saját metaadata. Saját schema/session/sequence és frissesség; latest_event csak a maradó kategóriák eseményeit tartalmazza. | A másik producer életjele nem helyettesíti az addoncsatornáét. **T7** |
| [schema_version](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2483>) | MEGTARTANDÓ | Addoncsatorna saját metaadata. Saját schema/session/sequence és frissesség; latest_event csak a maradó kategóriák eseményeit tartalmazza. | A másik producer életjele nem helyettesíti az addoncsatornáét. **T7** |
| [addon_version](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2484>) | MEGTARTANDÓ | Addoncsatorna saját metaadata. Saját schema/session/sequence és frissesség; latest_event csak a maradó kategóriák eseményeit tartalmazza. | A másik producer életjele nem helyettesíti az addoncsatornáét. **T7** |
| [game_version](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2485>) | SZÉTVÁLASZTANDÓ | Ellenőrzött process/capture build + addon interfészverzió. A process/payload build és az addon kompatibilitása külön tény; Interface 120100 nem teljes payload-build. | Packetdekódolási buildellenőrzés már van; addonfüggetlen bootstrap még kell. **T2/P0** |
| [game_build](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2486>) | SZÉTVÁLASZTANDÓ | Ellenőrzött process/capture build + addon interfészverzió. A process/payload build és az addon kompatibilitása külön tény; Interface 120100 nem teljes payload-build. | Packetdekódolási buildellenőrzés már van; addonfüggetlen bootstrap még kell. **T2/P0** |
| [addon](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2487>) | MEGTARTANDÓ | Addoncsatorna saját metaadata. Saját schema/session/sequence és frissesség; latest_event csak a maradó kategóriák eseményeit tartalmazza. | A másik producer életjele nem helyettesíti az addoncsatornáét. **T7** |
| [timestamp](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2488>) | MEGTARTANDÓ | Addoncsatorna saját metaadata. Saját schema/session/sequence és frissesség; latest_event csak a maradó kategóriák eseményeit tartalmazza. | A másik producer életjele nem helyettesíti az addoncsatornáét. **T7** |
| [monotonic_time](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2489>) | MEGTARTANDÓ | Addoncsatorna saját metaadata. Saját schema/session/sequence és frissesség; latest_event csak a maradó kategóriák eseményeit tartalmazza. | A másik producer életjele nem helyettesíti az addoncsatornáét. **T7** |
| [player_present](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2490>) | MEGTARTANDÓ | Publikus kliens/UI. A konkrét kliensablak inputjogosultságához szükséges; szerverkapcsolat egészsége külön mező. | A szerver nem közli az aktuális billentyűfókuszt és a teljes lokális modal állapotot. **T7** |
| [nameplates](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2491>) | KIVEZETENDŐ KÉPERNYŐS NÉZET | Szerveres entitásnézet + addon target/soft-target. Nameplate képernyőhorgony és vizuális tracking nem cél. Szükséges unitmező a saját hiteles providerén keresztül éljen. | A szerveres entitásállapothoz és a tényleges interakciós címzetthez külön adatút tartozik. **T0/T3/T7** |
| [loading](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2492>) | MEGTARTANDÓ | Publikus kliens/UI. A konkrét kliensablak inputjogosultságához szükséges; szerverkapcsolat egészsége külön mező. | A szerver nem közli az aktuális billentyűfókuszt és a teljes lokális modal állapotot. **T7** |
| [input_blocked](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2493>) | MEGTARTANDÓ | Publikus kliens/UI. A konkrét kliensablak inputjogosultságához szükséges; szerverkapcsolat egészsége külön mező. | A szerver nem közli az aktuális billentyűfókuszt és a teljes lokális modal állapotot. **T7** |
| [ui_error](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2497>) | MEGTARTANDÓ | Publikus kliens/UI. A konkrét kliensablak inputjogosultságához szükséges; szerverkapcsolat egészsége külön mező. | A szerver nem közli az aktuális billentyűfókuszt és a teljes lokális modal állapotot. **T7** |
| [ui_error_at](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2498>) | MEGTARTANDÓ | Publikus kliens/UI. A konkrét kliensablak inputjogosultságához szükséges; szerverkapcsolat egészsége külön mező. | A szerver nem közli az aktuális billentyűfókuszt és a teljes lokális modal állapotot. **T7** |
| [ui_error_sequence](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2499>) | MEGTARTANDÓ | Publikus kliens/UI. A konkrét kliensablak inputjogosultságához szükséges; szerverkapcsolat egészsége külön mező. | A szerver nem közli az aktuális billentyűfókuszt és a teljes lokális modal állapotot. **T7** |
| [ui_error_code](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2500>) | MEGTARTANDÓ | Publikus kliens/UI. A konkrét kliensablak inputjogosultságához szükséges; szerverkapcsolat egészsége külön mező. | A szerver nem közli az aktuális billentyűfókuszt és a teljes lokális modal állapotot. **T7** |
| [event_type](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2501>) | MEGTARTANDÓ | Addoncsatorna saját metaadata. Saját schema/session/sequence és frissesség; latest_event csak a maradó kategóriák eseményeit tartalmazza. | A másik producer életjele nem helyettesíti az addoncsatornáét. **T7** |
| [character_guid](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2502>) | ÁTKÖLTÖZTETENDŐ | Ellenőrzött saját karakter kontextus. P0 saját identitás és epoch nélkül nem törölhető a mai bootstrap. | Mai kontextus addonfüggő. **T2/P0** |
| [character_name](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2503>) | ELHAGYHATÓ VEZÉRLÉSI ADATKÉNT | GUID/entry a WorldModelben; opcionális lokális megjelenítés. Személyes név ne kerüljön át packetes exportként; current_target szöveg ne legyen második target authority. | Névalapú saját identitás vagy target-azonosítás nem szükséges. **T2/T7** |
| [map_id](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2504>) | SZÉTVÁLASZTANDÓ | Packet world/instance + DB2 transzformáció + UI-map kontextus. Megjelenített map a kliensé; koordinátaátváltás csak ellenőrzött transzformációval; teljes map_context nem törölhető. | MAP_CHANGED létezik; az UI-map/display/floor nem azonos a szerver world-mappal. **T2/T4** |
| [map_context](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2505>) | SZÉTVÁLASZTANDÓ | Packet world/instance + DB2 transzformáció + UI-map kontextus. Megjelenített map a kliensé; koordinátaátváltás csak ellenőrzött transzformációval; teljes map_context nem törölhető. | MAP_CHANGED létezik; az UI-map/display/floor nem azonos a szerver world-mappal. **T2/T4** |
| [map_world_transform](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2506>) | SZÉTVÁLASZTANDÓ | Packet world/instance + DB2 transzformáció + UI-map kontextus. Megjelenített map a kliensé; koordinátaátváltás csak ellenőrzött transzformációval; teljes map_context nem törölhető. | MAP_CHANGED létezik; az UI-map/display/floor nem azonos a szerver world-mappal. **T2/T4** |
| [minimap_geometry](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2507>) | KIVEZETENDŐ A CÉLFELÉPÍTÉSBŐL | Nincs szükséges szerepe a szerveres + addon vezérlésben. Nincs minimapképből vagy kamerából történő keresés. A szükséges questkoordináta strukturált packet/API/DB2 adatból jön. | A régi kamera/minimap/vizuális keresési adatút öröksége. **T0/T7** |
| [zone_name](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2508>) | SZÁRMAZTATÁS/MEGJELENÍTÉS | Ellenőrzött terület + helyi klienskatalógus; szükség esetén lokális UI. Megjelenítési adat ne vezéreljen név alapján world/instance váltást. | Teljes area/zone feloldás nincs a mai szűk eseményfelületben. **T2/T7** |
| [subzone_name](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2509>) | SZÁRMAZTATÁS/MEGJELENÍTÉS | Ellenőrzött terület + helyi klienskatalógus; szükség esetén lokális UI. Megjelenítési adat ne vezéreljen név alapján world/instance váltást. | Teljes area/zone feloldás nincs a mai szűk eseményfelületben. **T2/T7** |
| [position](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2510>) | ÁTKÖLTÖZTETENDŐ RÉSZENKÉNT | Saját packetes mozgás + ellenőrzött maptranszformáció. CMSG mozgás kliens által jelentett minta, nem automatikusan szerver-visszaigazolás; normalizált térképpont külön koordinátatér. | MOVEMENT_UPDATE részben kész; projekció addonkontextusra támaszkodik. **T2/P0+T4** |
| [player_world_position](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2512>) | ÁTKÖLTÖZTETENDŐ RÉSZENKÉNT | Saját packetes mozgás + ellenőrzött maptranszformáció. CMSG mozgás kliens által jelentett minta, nem automatikusan szerver-visszaigazolás; normalizált térképpont külön koordinátatér. | MOVEMENT_UPDATE részben kész; projekció addonkontextusra támaszkodik. **T2/P0+T4** |
| [orientation](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2514>) | ÁTKÖLTÖZTETENDŐ RÉSZENKÉNT | Saját packetes mozgás + ellenőrzött maptranszformáció. CMSG mozgás kliens által jelentett minta, nem automatikusan szerver-visszaigazolás; normalizált térképpont külön koordinátatér. | MOVEMENT_UPDATE részben kész; projekció addonkontextusra támaszkodik. **T2/P0+T4** |
| [health](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2515>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [max_health](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2516>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [power](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2517>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [max_power](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2518>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [money](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2519>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [power_type](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2520>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [level](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2521>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [class](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2522>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [race](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2523>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [is_casting](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2524>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [combat_hint](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2525>) | PYTHONBA HELYEZENDŐ SZÁRMAZTATÁS | Közös WorldModel és verification eredménye. Revision és digest az elfogadott állapotból; corpses és combat hint forrásos, kontextusos, korlátos történet. | Alapadatfüggő; a származtatásnak nem kell addonban külön világot fenntartani. **T1/T3/T7** |
| [is_mounted](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2526>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [mount_capability](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2527>) | SZÉTVÁLASZTANDÓ | Packet mozgás/aura/jogosultság + statikus adat + lokális usability. Szerverről megszerezhető rész költözik; lokális indoor/mount availability és el nem érhető publikus feltétel marad vagy UNKNOWN. | Repülési flags/pitch/velocities részben vannak; teljes capability/energy nem garantált. **T3/P5+T5/T6** |
| [is_in_combat](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2528>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [is_dead](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2529>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [is_ghost](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2530>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [in_vehicle](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2533>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [has_vehicle_ui](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2534>) | MEGTARTANDÓ | Publikus kliens UI. A helyi vehicle/actionbar kontextus és az aktiválás igazolásához kell. | Vehicle utasszerep és a ténylegesen megjelenő UI külön adat. **T7** |
| [on_taxi](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2535>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [vehicle_guid](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2538>) | ÁTKÖLTÖZTETENDŐ | Saját szerveres player/unit, aura, cast, movement és inventory állapot. Mezőnként ellenőrzött update/layout és baseline kell; ismeretlenből nem lesz 0/false. Csak engedélyezett normalizált saját játékállapot. | A mai ENTITY_UNIT_UPDATE creature/vehicle/GO körre korlátozott; teljes own-player baseline hiányzik. **T3/P3–P5** |
| [camera_distance](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2539>) | KIVEZETENDŐ A CÉLFELÉPÍTÉSBŐL | Nincs szükséges szerepe a szerveres + addon vezérlésben. Nincs minimapképből vagy kamerából történő keresés. A szükséges questkoordináta strukturált packet/API/DB2 adatból jön. | A régi kamera/minimap/vizuális keresési adatút öröksége. **T0/T7** |
| [movement](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2540>) | SZÉTVÁLASZTANDÓ | Packet mozgás/aura/jogosultság + statikus adat + lokális usability. Szerverről megszerezhető rész költözik; lokális indoor/mount availability és el nem érhető publikus feltétel marad vagy UNKNOWN. | Repülési flags/pitch/velocities részben vannak; teljes capability/energy nem garantált. **T3/P5+T5/T6** |
| [flight](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2541>) | SZÉTVÁLASZTANDÓ | Packet mozgás/aura/jogosultság + statikus adat + lokális usability. Szerverről megszerezhető rész költözik; lokális indoor/mount availability és el nem érhető publikus feltétel marad vagy UNKNOWN. | Repülési flags/pitch/velocities részben vannak; teljes capability/energy nem garantált. **T3/P5+T5/T6** |
| [actionbar_context](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2542>) | MEGTARTANDÓ / KOMPATIBILITÁS RENDEZENDŐ | Kliens helyi bar és kiválasztott cache ellenőrzése. Context/revision kötelező; snapshot_context alias kivezethető migráció után; addon nem választ másik cache-t és nem talál ki bindingot. | A teljes lokális slot/page/makró/billentyű-feloldást nem adja a mai packetfelület. **T1/T7** |
| [actionbar_snapshot_context](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2543>) | MEGTARTANDÓ / KOMPATIBILITÁS RENDEZENDŐ | Kliens helyi bar és kiválasztott cache ellenőrzése. Context/revision kötelező; snapshot_context alias kivezethető migráció után; addon nem választ másik cache-t és nem talál ki bindingot. | A teljes lokális slot/page/makró/billentyű-feloldást nem adja a mai packetfelület. **T1/T7** |
| [skyriding_bar](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2544>) | MEGTARTANDÓ / KOMPATIBILITÁS RENDEZENDŐ | Kliens helyi bar és kiválasztott cache ellenőrzése. Context/revision kötelező; snapshot_context alias kivezethető migráció után; addon nem választ másik cache-t és nem talál ki bindingot. | A teljes lokális slot/page/makró/billentyű-feloldást nem adja a mai packetfelület. **T1/T7** |
| [current_target](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2546>) | ELHAGYHATÓ VEZÉRLÉSI ADATKÉNT | GUID/entry a WorldModelben; opcionális lokális megjelenítés. Személyes név ne kerüljön át packetes exportként; current_target szöveg ne legyen második target authority. | Névalapú saját identitás vagy target-azonosítás nem szükséges. **T2/T7** |
| [target](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2547>) | SZÉTVÁLASZTANDÓ | Packet entitásállapot + strukturált addon kijelölés/hover. GUID, HP és XYZ a megfelelő forrásból; pontos addon céltoken/tooltip felhasználható. Képernyős bbox és vizuális azonosítás kivezetendő. | Szerveres entitás és unitrészhalmaz megvan; lokális céltoken az addoné. **T3/P3+T7** |
| [soft_targets](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2562>) | MEGTARTANDÓ | Publikus kliens soft-target/F7 recipient. Célazonosság és mintavételi idő kötelező; az utólagos CMSG megfigyelés nem előzetes jogosultság. | A gombnyomás előtti pontos lokális címzett nem teljes szerveres információ. **T7** |
| [interact_guid](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2563>) | MEGTARTANDÓ | Publikus kliens soft-target/F7 recipient. Célazonosság és mintavételi idő kötelező; az utólagos CMSG megfigyelés nem előzetes jogosultság. | A gombnyomás előtti pontos lokális címzett nem teljes szerveres információ. **T7** |
| [quest_item_target](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2564>) | SZÉTVÁLASZTANDÓ, UI-RÉSZ MARAD | Publikus helyi range/usability + igazolt szerveres item/cooldown. Önmagunkon aktivált készülékhez nem kell hamis target GUID; range unknown maradhat; spell és credit külön. | Mai USE_ITEM előfeltétel ebből kap publikus readiness-t; teljes packetes kiváltás nincs. **T3/P4–P5+T7** |
| [visible_units](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2565>) | ELHAGYHATÓ DUPLIKÁCIÓ | Közös entitásnézet a WorldModelben. Ne legyen második, eltérő tartalmú világlista; nincs külön képernyős világmodell a célfelépítésben. | A mai mező a target leegyszerűsített másolata. **T1/T7** |
| [actionbar](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2573>) | SZÉTVÁLASZTANDÓ | Lokális slot/page/binding + packet spellállapot + DB2 spelladat. A helyi tényleges tartalom és állapot kell az aktiváláshoz; statikus spelladatot nem kell ismételten exportálni. | Teljes actionbutton/spell/cooldown provider még hiányzik. **T3/P5+T7** |
| [vehicle_bar](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2574>) | SZÉTVÁLASZTANDÓ | Lokális slot/page/binding + packet spellállapot + DB2 spelladat. A helyi tényleges tartalom és állapot kell az aktiváláshoz; statikus spelladatot nem kell ismételten exportálni. | Teljes actionbutton/spell/cooldown provider még hiányzik. **T3/P5+T7** |
| [control_bindings](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2575>) | MEGTARTANDÓ / KOMPATIBILITÁS RENDEZENDŐ | Kliens helyi bar és kiválasztott cache ellenőrzése. Context/revision kötelező; snapshot_context alias kivezethető migráció után; addon nem választ másik cache-t és nem talál ki bindingot. | A teljes lokális slot/page/makró/billentyű-feloldást nem adja a mai packetfelület. **T1/T7** |
| [binding_catalog_page](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2576>) | MEGTARTANDÓ / KOMPATIBILITÁS RENDEZENDŐ | Kliens helyi bar és kiválasztott cache ellenőrzése. Context/revision kötelező; snapshot_context alias kivezethető migráció után; addon nem választ másik cache-t és nem talál ki bindingot. | A teljes lokális slot/page/makró/billentyű-feloldást nem adja a mai packetfelület. **T1/T7** |
| [active_quests](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2577>) | ÁTKÖLTÖZTETENDŐ | Questdefiníció + saját questlog baseline/delta. Objective ID/type/object ID és teljesség szükséges; célzottan engedélyezett questszöveg-séma kell. | Mai credit/update/complete nem teljes log/definíció. **T2/P1–P2** |
| [quest_text](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2578>) | ÁTKÖLTÖZTETENDŐ | Questdefiníció + saját questlog baseline/delta. Objective ID/type/object ID és teljesség szükséges; célzottan engedélyezett questszöveg-séma kell. | Mai credit/update/complete nem teljes log/definíció. **T2/P1–P2** |
| [quest_locations](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2579>) | SZÉTVÁLASZTANDÓ | Packet objective-POI + DB2 térképadat + lokális UI-marker. A feladat geometriája és a képernyőn/megnyitott mapon megjelenített jelölő külön; POI nem NPC-azonosság. | Quest POI van, mai publikus projekció csak turn-in; más markerfajták nem automatikusan szerveresek. **T3/P6+T7** |
| [map_pois](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2580>) | SZÉTVÁLASZTANDÓ | Packet objective-POI + DB2 térképadat + lokális UI-marker. A feladat geometriája és a képernyőn/megnyitott mapon megjelenített jelölő külön; POI nem NPC-azonosság. | Quest POI van, mai publikus projekció csak turn-in; más markerfajták nem automatikusan szerveresek. **T3/P6+T7** |
| [quest_state_revision](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2581>) | PYTHONBA HELYEZENDŐ SZÁRMAZTATÁS | Közös WorldModel és verification eredménye. Revision és digest az elfogadott állapotból; corpses és combat hint forrásos, kontextusos, korlátos történet. | Alapadatfüggő; a származtatásnak nem kell addonban külön világot fenntartani. **T1/T3/T7** |
| [quest_turn_in_receipts](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2582>) | ÁTKÖLTÖZTETENDŐ | Igazolt questleadási tranzakció és állapot. A logból eltűnés lehet abandon is; pontos elfogadási/leadási életciklus és duplicate kezelés kell. | QUEST_COMPLETED nem garantál rewarded/turned-in állapotot. **T2/P2** |
| [quest_ui](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2583>) | SZÉTVÁLASZTANDÓ | Packet tartalom/állapot + publikus UI felület/címzett/gomb. Logikai tartalom átállítható megfelelő parserrel; renderelt láthatóság, gomb és lokális readiness marad. Vendor teljes kiváltás későbbi külön kapu. | Scene/quest status nem teljes párbeszéd/vendorkészlet/reclaim/extra-action UI. **T2/P2+T3+T7** |
| [extra_action](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2584>) | SZÉTVÁLASZTANDÓ | Packet tartalom/állapot + publikus UI felület/címzett/gomb. Logikai tartalom átállítható megfelelő parserrel; renderelt láthatóság, gomb és lokális readiness marad. Vendor teljes kiváltás későbbi külön kapu. | Scene/quest status nem teljes párbeszéd/vendorkészlet/reclaim/extra-action UI. **T2/P2+T3+T7** |
| [death_recovery](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2585>) | SZÉTVÁLASZTANDÓ | Packet tartalom/állapot + publikus UI felület/címzett/gomb. Logikai tartalom átállítható megfelelő parserrel; renderelt láthatóság, gomb és lokális readiness marad. Vendor teljes kiváltás későbbi külön kapu. | Scene/quest status nem teljes párbeszéd/vendorkészlet/reclaim/extra-action UI. **T2/P2+T3+T7** |
| [vendor_ui](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2586>) | SZÉTVÁLASZTANDÓ | Packet tartalom/állapot + publikus UI felület/címzett/gomb. Logikai tartalom átállítható megfelelő parserrel; renderelt láthatóság, gomb és lokális readiness marad. Vendor teljes kiváltás későbbi külön kapu. | Scene/quest status nem teljes párbeszéd/vendorkészlet/reclaim/extra-action UI. **T2/P2+T3+T7** |
| [tutorial_hint](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2587>) | MEGTARTANDÓ | Publikus kliens/UI, optional debug. Strukturált addon/UI adat; képfelismerési horgony vagy kamerakeresés nem tartozik hozzá. Tutorial_hint csak opcionális, korlátos diagnosztika. | A kurzor és nyitottablak-állapot nem teljes szerveradat. **T7** |
| [mouseover](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2588>) | SZÉTVÁLASZTANDÓ | Packet entitásállapot + strukturált addon kijelölés/hover. GUID, HP és XYZ a megfelelő forrásból; pontos addon céltoken/tooltip felhasználható. Képernyős bbox és vizuális azonosítás kivezetendő. | Szerveres entitás és unitrészhalmaz megvan; lokális céltoken az addoné. **T3/P3+T7** |
| [cursor_position](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2589>) | MEGTARTANDÓ | Publikus kliens/UI, optional debug. Strukturált addon/UI adat; képfelismerési horgony vagy kamerakeresés nem tartozik hozzá. Tutorial_hint csak opcionális, korlátos diagnosztika. | A kurzor és nyitottablak-állapot nem teljes szerveradat. **T7** |
| [map_mouseover](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2590>) | KIVEZETENDŐ A CÉLFELÉPÍTÉSBŐL | Nincs szükséges szerepe a szerveres + addon vezérlésben. Nincs minimapképből vagy kamerából történő keresés. A szükséges questkoordináta strukturált packet/API/DB2 adatból jön. | A régi kamera/minimap/vizuális keresési adatút öröksége. **T0/T7** |
| [world_map_open](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2591>) | MEGTARTANDÓ | Publikus kliens/UI, optional debug. Strukturált addon/UI adat; képfelismerési horgony vagy kamerakeresés nem tartozik hozzá. Tutorial_hint csak opcionális, korlátos diagnosztika. | A kurzor és nyitottablak-állapot nem teljes szerveradat. **T7** |
| [inventory](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2592>) | SZÉTVÁLASZTANDÓ | Saját item/count/container packet + lokális bag slot UI. Itemmennyiség szerveres; látható baggomb helye/lock/render helyi. Teljes mezőt egyszerre eltávolítani hibás. | A mai eseményfelületben teljes inventory baseline nincs. **T3/P4+T7** |
| [bags_open](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2593>) | MEGTARTANDÓ | Publikus kliens/UI, optional debug. Strukturált addon/UI adat; képfelismerési horgony vagy kamerakeresés nem tartozik hozzá. Tutorial_hint csak opcionális, korlátos diagnosztika. | A kurzor és nyitottablak-állapot nem teljes szerveradat. **T7** |
| [heartbeat](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2594>) | MEGTARTANDÓ | Addoncsatorna saját metaadata. Saját schema/session/sequence és frissesség; latest_event csak a maradó kategóriák eseményeit tartalmazza. | A másik producer életjele nem helyettesíti az addoncsatornáét. **T7** |
| [latest_event](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2598>) | MEGTARTANDÓ | Addoncsatorna saját metaadata. Saját schema/session/sequence és frissesség; latest_event csak a maradó kategóriák eseményeit tartalmazza. | A másik producer életjele nem helyettesíti az addoncsatornáét. **T7** |
| [killed_corpses](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:2599>) | PYTHONBA HELYEZENDŐ SZÁRMAZTATÁS | Közös WorldModel és verification eredménye. Revision és digest az elfogadott állapotból; corpses és combat hint forrásos, kontextusos, korlátos történet. | Alapadatfüggő; a származtatásnak nem kell addonban külön világot fenntartani. **T1/T3/T7** |

### FAST producer

Az azonos nevű mezőre ugyanaz a döntés vonatkozik, mint fent. A két csak FAST-ban megjelenő mező (`actionbar_fast`, `quest_digest`) is külön döntést kap. A FAST-csomagban átvitt régi snapshotdigest nem önálló friss questmegfigyelés.

| FAST-mező | Döntés | Kapu |
|---|---|---|
| [timestamp](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3041>) | MEGTARTANDÓ | T7 |
| [monotonic_time](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3041>) | MEGTARTANDÓ | T7 |
| [map_id](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3042>) | SZÉTVÁLASZTANDÓ | T2/T4 |
| [map_context](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3042>) | SZÉTVÁLASZTANDÓ | T2/T4 |
| [health](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3045>) | ÁTKÖLTÖZTETENDŐ | T3/P3–P5 |
| [max_health](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3046>) | ÁTKÖLTÖZTETENDŐ | T3/P3–P5 |
| [is_dead](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3047>) | ÁTKÖLTÖZTETENDŐ | T3/P3–P5 |
| [is_ghost](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3048>) | ÁTKÖLTÖZTETENDŐ | T3/P3–P5 |
| [in_vehicle](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3049>) | ÁTKÖLTÖZTETENDŐ | T3/P3–P5 |
| [has_vehicle_ui](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3050>) | MEGTARTANDÓ | T7 |
| [on_taxi](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3051>) | ÁTKÖLTÖZTETENDŐ | T3/P3–P5 |
| [is_in_combat](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3052>) | ÁTKÖLTÖZTETENDŐ | T3/P3–P5 |
| [is_mounted](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3053>) | ÁTKÖLTÖZTETENDŐ | T3/P3–P5 |
| [is_casting](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3054>) | ÁTKÖLTÖZTETENDŐ | T3/P3–P5 |
| [player_present](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3056>) | MEGTARTANDÓ | T7 |
| [ui_error](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3057>) | MEGTARTANDÓ | T7 |
| [ui_error_at](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3058>) | MEGTARTANDÓ | T7 |
| [ui_error_sequence](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3059>) | MEGTARTANDÓ | T7 |
| [ui_error_code](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3060>) | MEGTARTANDÓ | T7 |
| [input_blocked](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3061>) | MEGTARTANDÓ | T7 |
| [loading](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3065>) | MEGTARTANDÓ | T7 |
| [position](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3071>) | ÁTKÖLTÖZTETENDŐ RÉSZENKÉNT | T2/P0+T4 |
| [player_world_position](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3075>) | ÁTKÖLTÖZTETENDŐ RÉSZENKÉNT | T2/P0+T4 |
| [orientation](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3077>) | ÁTKÖLTÖZTETENDŐ RÉSZENKÉNT | T2/P0+T4 |
| [movement](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3078>) | SZÉTVÁLASZTANDÓ | T3/P5+T5/T6 |
| [mouseover](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3082>) | SZÉTVÁLASZTANDÓ | T3/P3+T7 |
| [target](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3084>) | SZÉTVÁLASZTANDÓ | T3/P3+T7 |
| [soft_targets](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3094>) | MEGTARTANDÓ | T7 |
| [interact_guid](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3095>) | MEGTARTANDÓ | T7 |
| [quest_item_target](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3096>) | SZÉTVÁLASZTANDÓ, UI-RÉSZ MARAD | T3/P4–P5+T7 |
| [cursor_position](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3097>) | MEGTARTANDÓ | T7 |
| [map_mouseover](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3098>) | KIVEZETENDŐ A CÉLFELÉPÍTÉSBŐL | T0/T7 |
| [quest_ui](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3099>) | SZÉTVÁLASZTANDÓ | T2/P2+T3+T7 |
| [extra_action](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3100>) | SZÉTVÁLASZTANDÓ | T2/P2+T3+T7 |
| [combat_hint](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3101>) | PYTHONBA HELYEZENDŐ SZÁRMAZTATÁS | T1/T3/T7 |
| [bags_open](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3102>) | MEGTARTANDÓ | T7 |
| [world_map_open](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3103>) | MEGTARTANDÓ | T7 |
| [actionbar_context](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3104>) | MEGTARTANDÓ / KOMPATIBILITÁS RENDEZENDŐ | T1/T7 |
| [actionbar_fast](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3105>) | SZÉTVÁLASZTANDÓ | T3/P5+T7 |
| [quest_digest](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3121>) | PYTHONBA HELYEZENDŐ SZÁRMAZTATÁS | T1/T3/T7 |
| [quest_turn_in_receipts](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3122>) | ÁTKÖLTÖZTETENDŐ | T2/P2 |
| [quest_state_revision](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/addon/AIPlayerControllerExport/AIPlayerControllerExport.lua:3123>) | PYTHONBA HELYEZENDŐ SZÁRMAZTATÁS | T1/T3/T7 |

## B. TDB/referencia kapcsolatok a forrásban

53 forrásfájlt jelölt a `reference_knowledge|tdb_|PRIMARY_STATIC|TDB_PRIMARY|source_priority` keresés a `projekt/src` alatt. Egyes találatok kommentek, diagnosztikai szövegek, providerhivatkozások vagy importeszközök. A lista nem végrehajtott trace, és nem igazol önmagában 53 hibás prioritást. Az összes találat és sora a plan-evidence.json fájlban megmarad. A viselkedést érintő konkrét hibákat és kivételeket a fő terv 2. fejezete külön megnevezi.

| Forrás | Kapcsolat | Tervezett rendezés |
|---|---|---|
| [agent/agenda_sources.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/agenda_sources.py:10>) | Cél és régió | Ugyanazon objective/ender esetén aktuális live hely és szerep előre; TDB régió csak keresési jelölt. Friss turn-in javítás megtartandó. |
| [agent/conversation_actors.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/conversation_actors.py:37>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/directed_item_facts.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/directed_item_facts.py:54>) | Quest item | Item–spell–credit kapcsolat, DB2 alakzat és aktuális readiness külön; loot/spell megfigyeléssel kiváltható rész és TDB-hézag explicit. |
| [agent/directed_item_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/directed_item_planning.py:43>) | Quest item | Item–spell–credit kapcsolat, DB2 alakzat és aktuális readiness külön; loot/spell megfigyeléssel kiváltható rész és TDB-hézag explicit. |
| [agent/engine.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/engine.py:83>) | Közös állapot és bekötés | Új provider a meglévő WorldModel/QuestModel adatútjába; régi statikus promotion és projekció ne maradjon rejtett authority. |
| [agent/engine_runtime_projection.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/engine_runtime_projection.py:404>) | Közös állapot és bekötés | Új provider a meglévő WorldModel/QuestModel adatútjába; régi statikus promotion és projekció ne maradjon rejtett authority. |
| [agent/escort_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/escort_planning.py:33>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/gui.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/gui.py:59>) | Adminisztráció/import | Megőrizhető offline archiváló és GUI; a futó planner állapota ne az SQL-importtól függjön. Ez nem önmagában runtime prioritási hiba. |
| [agent/learned_world.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/learned_world.py:7>) | Tanult tudás | Saját megfigyelés eredete, feltétele és érvényessége külön a TDB-ből importált tudástól; történeti adat ne váljon live tényállássá. |
| [agent/map_poi_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/map_poi_planning.py:79>) | Cél és régió | Ugyanazon objective/ender esetén aktuális live hely és szerep előre; TDB régió csak keresési jelölt. Friss turn-in javítás megtartandó. |
| [agent/object_interaction_flow.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/object_interaction_flow.py:137>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/objective_locator.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/objective_locator.py:29>) | Cél és régió | Ugyanazon objective/ender esetén aktuális live hely és szerep előre; TDB régió csak keresési jelölt. Friss turn-in javítás megtartandó. |
| [agent/objective_speech_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/objective_speech_planning.py:57>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/objective_transport.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/objective_transport.py:33>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/packet_entity_facts.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/packet_entity_facts.py:151>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/pkt_dump_import.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/pkt_dump_import.py:10>) | Adminisztráció/import | Megőrizhető offline archiváló és GUI; a futó planner állapota ne az SQL-importtól függjön. Ez nem önmagában runtime prioritási hiba. |
| [agent/quest_contextual_talk.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_contextual_talk.py:33>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/quest_creature_learning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_creature_learning.py:204>) | Tanult tudás | Saját megfigyelés eredete, feltétele és érvényessége külön a TDB-ből importált tudástól; történeti adat ne váljon live tényállássá. |
| [agent/quest_dialog_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_dialog_planning.py:225>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/quest_giver_evidence.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_giver_evidence.py:241>) | Cél és régió | Ugyanazon objective/ender esetén aktuális live hely és szerep előre; TDB régió csak keresési jelölt. Friss turn-in javítás megtartandó. |
| [agent/quest_item_knowledge.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_item_knowledge.py:128>) | Quest item | Item–spell–credit kapcsolat, DB2 alakzat és aktuális readiness külön; loot/spell megfigyeléssel kiváltható rész és TDB-hézag explicit. |
| [agent/quest_item_search.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_item_search.py:76>) | Quest item | Item–spell–credit kapcsolat, DB2 alakzat és aktuális readiness külön; loot/spell megfigyeléssel kiváltható rész és TDB-hézag explicit. |
| [agent/quest_location_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_location_planning.py:391>) | Cél és régió | Ugyanazon objective/ender esetén aktuális live hely és szerep előre; TDB régió csak keresési jelölt. Friss turn-in javítás megtartandó. |
| [agent/quest_model.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_model.py:374>) | Közös állapot és bekötés | Új provider a meglévő WorldModel/QuestModel adatútjába; régi statikus promotion és projekció ne maradjon rejtett authority. |
| [agent/quest_objective_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_objective_planning.py:203>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/quest_playbooks.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_playbooks.py:71>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/quest_search_hints.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_search_hints.py:16>) | Cél és régió | Ugyanazon objective/ender esetén aktuális live hely és szerep előre; TDB régió csak keresési jelölt. Friss turn-in javítás megtartandó. |
| [agent/quest_transition_hold.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_transition_hold.py:75>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/quest_turn_in.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/quest_turn_in.py:85>) | Cél és régió | Ugyanazon objective/ender esetén aktuális live hely és szerep előre; TDB régió csak keresési jelölt. Friss turn-in javítás megtartandó. |
| [agent/reference_catalog.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/reference_catalog.py:249>) | Forrás/provider | Mezőnkénti live/learned/static lekérdezés; TDB csak indokolt kiegészítés; cache és forráslánc megőrzése. |
| [agent/reference_experience.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/reference_experience.py:39>) | Tanult tudás | Saját megfigyelés eredete, feltétele és érvényessége külön a TDB-ből importált tudástól; történeti adat ne váljon live tényállássá. |
| [agent/reference_fallback.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/reference_fallback.py:2>) | Forrás/provider | Mezőnkénti live/learned/static lekérdezés; TDB csak indokolt kiegészítés; cache és forráslánc megőrzése. |
| [agent/reference_knowledge.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/reference_knowledge.py:22>) | Forrás/provider | Mezőnkénti live/learned/static lekérdezés; TDB csak indokolt kiegészítés; cache és forráslánc megőrzése. |
| [agent/reference_world_sqlite.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/reference_world_sqlite.py:11>) | Forrás/provider | Mezőnkénti live/learned/static lekérdezés; TDB csak indokolt kiegészítés; cache és forráslánc megőrzése. |
| [agent/rescue_object_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/rescue_object_planning.py:139>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/runtime_observation_phase.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/runtime_observation_phase.py:196>) | Közös állapot és bekötés | Új provider a meglévő WorldModel/QuestModel adatútjába; régi statikus promotion és projekció ne maradjon rejtett authority. |
| [agent/semantic_advisor.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/semantic_advisor.py:126>) | Tanácsadó réteg | Forráscímkés közös tényeket kapjon; TDB név vagy LLM-hipotézis ne legyen identity/inputjog. |
| [agent/server_npc_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/server_npc_planning.py:89>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/spatial_memory.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/spatial_memory.py:14>) | Közös állapot és bekötés | Új provider a meglévő WorldModel/QuestModel adatútjába; régi statikus promotion és projekció ne maradjon rejtett authority. |
| [agent/spawn_catalog.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/spawn_catalog.py:12>) | Forrás/provider | Mezőnkénti live/learned/static lekérdezés; TDB csak indokolt kiegészítés; cache és forráslánc megőrzése. |
| [agent/tdb_knowledge.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/tdb_knowledge.py:59>) | Forrás/provider | Mezőnkénti live/learned/static lekérdezés; TDB csak indokolt kiegészítés; cache és forráslánc megőrzése. |
| [agent/tdb_locations.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/tdb_locations.py:106>) | Forrás/provider | Mezőnkénti live/learned/static lekérdezés; TDB csak indokolt kiegészítés; cache és forráslánc megőrzése. |
| [agent/turnin_resolver.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/turnin_resolver.py:31>) | Cél és régió | Ugyanazon objective/ender esetén aktuális live hely és szerep előre; TDB régió csak keresési jelölt. Friss turn-in javítás megtartandó. |
| [agent/vehicle_prerequisites.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/vehicle_prerequisites.py:21>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |
| [agent/visual_search_planning.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/visual_search_planning.py:42>) | Örökölt vizuális ág | Kívül esik a célarchitektúrán; autonóm és passzív vizuális keresési hívásai kivezetendők, nem újrapriorizálandók. |
| [agent/world_beliefs.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/world_beliefs.py:55>) | Közös állapot és bekötés | Új provider a meglévő WorldModel/QuestModel adatútjába; régi statikus promotion és projekció ne maradjon rejtett authority. |
| [agent/world_evidence_reducer.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/world_evidence_reducer.py:32>) | Közös állapot és bekötés | Új provider a meglévő WorldModel/QuestModel adatútjába; régi statikus promotion és projekció ne maradjon rejtett authority. |
| [agent/world_query.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/world_query.py:69>) | Közös állapot és bekötés | Új provider a meglévő WorldModel/QuestModel adatútjába; régi statikus promotion és projekció ne maradjon rejtett authority. |
| [agent/wpp_tdb_import.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/agent/wpp_tdb_import.py:586>) | Adminisztráció/import | Megőrizhető offline archiváló és GUI; a futó planner állapota ne az SQL-importtól függjön. Ez nem önmagában runtime prioritási hiba. |
| [navigation/global_planner.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/navigation/global_planner.py:76>) | Navigáció/geometria | Magasság és veszély forrása külön; TDB-spawn potenciális, live hostile tényleges. Közös utazás/arrival szerződés. |
| [navigation/service.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/navigation/service.py:199>) | Navigáció/geometria | Magasság és veszély forrása külön; TDB-spawn potenciális, live hostile tényleges. Közös utazás/arrival szerződés. |
| [navigation/spawn_threats.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/navigation/spawn_threats.py:136>) | Navigáció/geometria | Magasság és veszély forrása külön; TDB-spawn potenciális, live hostile tényleges. Közös utazás/arrival szerződés. |
| [skills/object_pull.py](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/src/wowbot/skills/object_pull.py:19>) | Actor és mechanika | Objective/actor/credit reláció providerfüggetlenül; szerveres numeric kapcsolat, feltétel, tanulás, majd TDB. UI/skill és identity szerződés marad. |

## C. A mai normalizált packetes eseményfelület

A következő 22 típus szerepel a mai _FIELDS allowlistben. A név nem teljes payload-dekódolást és nem minden builden élőben igazolt funkciót jelent. A NETWORK_STREAM_CHUNK és PACKET_OPCODE_OBSERVED diagnosztikai adat; nem játékállapot. A validátor külön layout/producer/build-provenance kaput használ. A hiányzó questdefiníció, inventory és teljes saját player baseline tervezett munka.

| Esemény | Engedélyezett mezők |
|---|---|
| `QUEST_POI_UPDATE` | `blobs`, `capture_timestamp`, `quest_id` |
| `NETWORK_STREAM_CHUNK` | `byte_count`, `sequence_start`, `sha256` |
| `PACKET_OPCODE_OBSERVED` | `byte_count`, `connection_index`, `opcode_name`, `record_number`, `sha256` |
| `MOVEMENT_UPDATE` | `adv_flying`, `can_fly`, `coordinate_space`, `facing`, `fall_xy_speed`, `fall_z_speed`, `falling`, `flying`, `forward_velocity`, `is_selected_client_movement`, `move_time`, `movement_flags`, `mover_guid`, `on_transport`, `pitch`, `sequence_index`, `source_opcode`, `standing_on_game_object`, `teleport`, `up_velocity`, `x`, `y`, `z` |
| `MAP_CHANGED` | `coordinate_space`, `facing`, `floor_difficulty`, `floor_index`, `reason`, `world_map_id`, `x`, `y`, `z` |
| `QUEST_COMPLETED` | `quest_id` |
| `QUEST_UPDATED` | `failed`, `quest_id`, `timer_failed` |
| `QUEST_CREDIT_ADDED` | `count`, `object_id`, `objective_type`, `quest_id`, `required` |
| `COMBAT_STARTED` | `attacker_guid`, `victim_guid` |
| `ATTACK_STOPPED` | `attacker_guid`, `now_dead`, `victim_guid` |
| `SPELL_CAST_FAILED` | `attack_swing`, `reason` |
| `ENTITY_POSITION` | `coordinate_space`, `destination_x`, `destination_y`, `destination_z`, `entity_guid`, `entry_id`, `move_time_ms`, `source_opcode`, `x`, `y`, `z` |
| `ENTITY_CREATED` | `bounding_radius`, `combat_reach`, `coordinate_space`, `created_by`, `dynamic_flags`, `entity_guid`, `entry_id`, `facing`, `faction_template`, `go_flags`, `go_state`, `go_type`, `health`, `level`, `max_health`, `npc_flags`, `object_kind`, `position_source`, `quest_objective_id`, `summoned_by`, `target_guid`, `unit_flags`, `unit_flags2`, `unit_flags3`, `world_map_id`, `x`, `y`, `z` |
| `ENTITY_UNIT_UPDATE` | `bounding_radius`, `combat_reach`, `created_by`, `entity_guid`, `entry_id`, `faction_template`, `health`, `level`, `max_health`, `summoned_by`, `target_guid`, `unit_flags`, `unit_flags2`, `unit_flags3` |
| `ENTITY_REMOVED` | `entity_guid`, `entry_id`, `removal` |
| `ENTITY_FLAGS` | `dynamic_flags`, `entity_guid`, `entry_id` |
| `QUEST_GIVER_STATUS` | `entity_guid`, `entry_id`, `future_quest`, `quest_available`, `quest_incomplete`, `reward_ready`, `status_flags`, `trivial_available` |
| `SCENE_STARTED` | `package_id`, `playback_flags`, `scene_id`, `scene_instance_id` |
| `SCENE_ENDED` | `canceled`, `scene_instance_id` |
| `SCENE_EVENT` | `scene_event`, `scene_instance_id` |
| `MOVEMENT_ROOT` | `mover_guid`, `rooted` |
| `GOSSIP_SELECTED` | `entity_guid`, `entry_id`, `gossip_menu_id`, `gossip_option_id` |

## D. A 83 történeti master-pont nyomkövetése

Ez történeti nyomkövetés, nem a jelen célra kötelező specifikáció. A meglévő fájlok követelménysorait és bizonyítási státuszait ez a dokumentum nem írja át. A forrásledger számozott sorai mellett a későbbi dátumos bejegyzéseket is olvasni kell: egy régebbi sorban felsorolt hiányt egy frissebb, szűk részjavítás érinthet. Az alábbi táblázat ezért nem minősít át automatikusan teljes követelményt `LIVE_VALIDATED`-re.

A felhasználó frissebb, kizárólag szerveres + addon iránya felülírja a történeti vizuális elvárásokat. A V4/Design nem irányadó célterv. A kliens/UI forrás hitelessége a strukturált addonmezőkben megmarad, képfelismerés nélkül. Az alábbi régi sorok forrásbeli státusza nem jelenti a hozzájuk tartozó vizuális funkció jövőbeli megőrzési kötelezettségét.

| Pont | Tervezett kapcsolat | Státuszkezelés / további igazolás |
|---|---|---|
| [0. VÉGSŐ CÉL](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:25>) | 1, 4, 24–27: közös agent és tulajdonosi határok | Meglévő központ megtartása; nincs új domainagy. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:171>). |
| [1. LEGFONTOSABB ARCHITEKTURÁLIS ELV](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:125>) | 1, 4, 24–27: közös agent és tulajdonosi határok | Meglévő központ megtartása; nincs új domainagy. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:172>). |
| [2. NE ÉPÍTS KÜLÖN BOTOKAT](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:226>) | 1, 4, 24–27: közös agent és tulajdonosi határok | Meglévő központ megtartása; nincs új domainagy. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:173>). |
| [3. AGENT ABSZTRAKCIÓ](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:283>) | 1, 4, 24–27: közös agent és tulajdonosi határok | Meglévő központ megtartása; nincs új domainagy. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:174>). |
| [4. GOAL MANAGER](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:326>) | 1, 4, 24–27: közös agent és tulajdonosi határok | Meglévő központ megtartása; nincs új domainagy. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:175>). |
| [5. GOAL ≠ PLAN ≠ ACTION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:393>) | 1, 4, 24–27: közös agent és tulajdonosi határok | Meglévő központ megtartása; nincs új domainagy. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:176>). |
| [6. WORLD MODEL](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:453>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:177>). |
| [7. OBSERVATION LAYER](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:506>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:178>). |
| [8. SENSOR HIERARCHY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:573>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:179>). |
| [9. ENTITY ≠ LOCATION ≠ ROLE ≠ APPEARANCE ≠ STATE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:638>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:180>). |
| [10. MULTI-MAP / MULTI-LOCATION ENTITY MEMORY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:725>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:181>). |
| [11. DINAMIKUS QUEST ROLE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:795>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:182>). |
| [12. UNIVERSAL MAP MARKER](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:849>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:183>). |
| [13. DETECTION ≠ RECOGNITION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:904>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:184>). |
| [14. TEMPORAL TRACKING](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:950>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:185>). |
| [15. EVIDENCE ENGINE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:994>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:186>). |
| [16. CORRELATED EVIDENCE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1034>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:187>). |
| [17. BELIEF ENGINE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1084>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:188>). |
| [18. CONTRADICTION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1126>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:189>). |
| [19. PREDICTIVE WORLD MODEL](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1181>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:190>). |
| [20. PREDICTION ERROR](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1242>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:191>). |
| [21. EVENT MEMORY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1295>) | 5–8, 13: forrás, bizonyíték, kontextus, történet | Mezőnkénti authority, eredetlánc, snapshot/gap és UNKNOWN; prediction külön részleges képesség marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:192>). |
| [22. QUEST MODEL](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1347>) | 11–14, 22: questjelentés és tanult reláció | Hiányzó packetes definíció/baseline és nem megfigyelt mechanika külön nyitott követelmény. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:193>). |
| [23. QUEST OBJECTIVES](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1396>) | 11–14, 22: questjelentés és tanult reláció | Hiányzó packetes definíció/baseline és nem megfigyelt mechanika külön nyitott követelmény. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:194>). |
| [24. QUEST GRAPH](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1458>) | 11–14, 22: questjelentés és tanult reláció | Hiányzó packetes definíció/baseline és nem megfigyelt mechanika külön nyitott követelmény. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:195>). |
| [25. AUTOMATIC NEW QUEST UNDERSTANDING](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1514>) | 11–14, 22: questjelentés és tanult reláció | Hiányzó packetes definíció/baseline és nem megfigyelt mechanika külön nyitott követelmény. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:196>). |
| [26. QUEST SEMANTIC GENERALIZATION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1561>) | 11–14, 22: questjelentés és tanult reláció | Hiányzó packetes definíció/baseline és nem megfigyelt mechanika külön nyitott követelmény. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:197>). |
| [27. QUEST TEMPLATE LEARNING](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1619>) | 11–14, 22: questjelentés és tanult reláció | Hiányzó packetes definíció/baseline és nem megfigyelt mechanika külön nyitott követelmény. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:198>). |
| [28. PROCEDURAL MEMORY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1675>) | 11–14, 22: questjelentés és tanult reláció | Hiányzó packetes definíció/baseline és nem megfigyelt mechanika külön nyitott követelmény. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:199>). |
| [29. EPISODE LEARNING](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1719>) | 11–14, 22: questjelentés és tanult reláció | Hiányzó packetes definíció/baseline és nem megfigyelt mechanika külön nyitott követelmény. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:200>). |
| [30. NE MEMORIZÁLJ VAKON](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1769>) | 11–14, 22: questjelentés és tanult reláció | Hiányzó packetes definíció/baseline és nem megfigyelt mechanika külön nyitott követelmény. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:201>). |
| [31. ACTIVE LEARNING](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1812>) | 9, 13, 23: packet/addon adat és kontextusos tanulás | A szerveres és addon megfigyelésekből tanulunk. Vizuális detektor vagy képi tanulás nem része az új célnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:202>). |
| [32. ACTIVE PERCEPTION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1852>) | 9, 13, 23: packet/addon adat és kontextusos tanulás | A szerveres és addon megfigyelésekből tanulunk. Vizuális detektor vagy képi tanulás nem része az új célnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:203>). |
| [33. AI / VLM](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1899>) | 9, 13, 23: packet/addon adat és kontextusos tanulás | A szerveres és addon megfigyelésekből tanulunk. Vizuális detektor vagy képi tanulás nem része az új célnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:204>). |
| [34. VISUAL MEMORY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:1969>) | Történeti vizuális követelmény; kívül esik a jelen célon | Vizuális memória, minimapképi kalibráció és képi re-ID nem tervezett. GUID-azonosság és strukturált maptranszformáció a megfelelő adatútban marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:205>). |
| [35. SEMANTIC MEMORY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2012>) | 9, 13, 23: packet/addon adat és kontextusos tanulás | A szerveres és addon megfigyelésekből tanulunk. Vizuális detektor vagy képi tanulás nem része az új célnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:206>). |
| [36. SPATIAL MEMORY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2050>) | 9, 13, 23: packet/addon adat és kontextusos tanulás | A szerveres és addon megfigyelésekből tanulunk. Vizuális detektor vagy képi tanulás nem része az új célnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:207>). |
| [37. MEMORY AGING](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2089>) | 9, 13, 23: packet/addon adat és kontextusos tanulás | A szerveres és addon megfigyelésekből tanulunk. Vizuális detektor vagy képi tanulás nem része az új célnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:208>). |
| [38. CONCEPT DRIFT](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2128>) | 9, 13, 23: packet/addon adat és kontextusos tanulás | A szerveres és addon megfigyelésekből tanulunk. Vizuális detektor vagy képi tanulás nem része az új célnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:209>). |
| [39. SENSOR SELF-CALIBRATION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2166>) | 9, 13, 23: packet/addon adat és kontextusos tanulás | A szerveres és addon megfigyelésekből tanulunk. Vizuális detektor vagy képi tanulás nem része az új célnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:210>). |
| [40. SENSOR HEALTH](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2206>) | 6–8, 26: forrásegészség | Forrásonkénti health és teljesség; streamhiba nem silent vizuális inputengedély. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:211>). |
| [41. WORLD MODEL GRAPH](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2254>) | 16–21: map, floor, topológia és élő entitás | Geometriaképesség és koordinátatér külön; teljes 3D collision és általános re-ID nem állítható késznek. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:212>). |
| [42. MAP TOPOLOGY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2303>) | 16–21: map, floor, topológia és élő entitás | Geometriaképesség és koordinátatér külön; teljes 3D collision és általános re-ID nem állítható késznek. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:213>). |
| [43. MAP ↔ MINIMAP GEOMETRY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2345>) | Történeti vizuális követelmény; kívül esik a jelen célon | Vizuális memória, minimapképi kalibráció és képi re-ID nem tervezett. GUID-azonosság és strukturált maptranszformáció a megfelelő adatútban marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:214>). |
| [44. 3D RE-IDENTIFICATION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2397>) | Történeti vizuális követelmény; kívül esik a jelen célon | Vizuális memória, minimapképi kalibráció és képi re-ID nem tervezett. GUID-azonosság és strukturált maptranszformáció a megfelelő adatútban marad. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:215>). |
| [45. NPC BEHAVIOR MEMORY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2443>) | 16–21: map, floor, topológia és élő entitás | Geometriaképesség és koordinátatér külön; teljes 3D collision és általános re-ID nem állítható késznek. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:216>). |
| [46. GENERIC SKILL SYSTEM](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2481>) | 14–21: közös skill/nav/interaction szerződések | Meglévő végrehajtók rendezése; földi és két repülési mód külön igazolandó. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:217>). |
| [47. SKILL CONTRACT](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2548>) | 14–21: közös skill/nav/interaction szerződések | Meglévő végrehajtók rendezése; földi és két repülési mód külön igazolandó. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:218>). |
| [48. MOVEMENT SKILL](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2591>) | 14–21: közös skill/nav/interaction szerződések | Meglévő végrehajtók rendezése; földi és két repülési mód külön igazolandó. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:219>). |
| [49. COMBAT SKILL](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2645>) | 14–21: közös skill/nav/interaction szerződések | Meglévő végrehajtók rendezése; földi és két repülési mód külön igazolandó. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:220>). |
| [50. INTERACTION SKILL](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2690>) | 14–21: közös skill/nav/interaction szerződések | Meglévő végrehajtók rendezése; földi és két repülési mód külön igazolandó. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:221>). |
| [51. DOMAIN MODULES](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2741>) | 4, 14, 24: közös szolgáltatások minden domainhez | Mining/fishing/dungeon/PvP teljes támogatása e tervben nem implementált; régi hiányok és státuszok megmaradnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:222>). |
| [52. GENERIC TASK SOLVING](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2791>) | 4, 14, 24: közös szolgáltatások minden domainhez | Mining/fishing/dungeon/PvP teljes támogatása e tervben nem implementált; régi hiányok és státuszok megmaradnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:223>). |
| [53. QUEST ALL DAY EXAMPLE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2839>) | 4, 14, 24: közös szolgáltatások minden domainhez | Mining/fishing/dungeon/PvP teljes támogatása e tervben nem implementált; régi hiányok és státuszok megmaradnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:224>). |
| [54. MINING EXAMPLE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2920>) | 4, 14, 24: közös szolgáltatások minden domainhez | Mining/fishing/dungeon/PvP teljes támogatása e tervben nem implementált; régi hiányok és státuszok megmaradnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:225>). |
| [55. FISHING EXAMPLE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:2985>) | 4, 14, 24: közös szolgáltatások minden domainhez | Mining/fishing/dungeon/PvP teljes támogatása e tervben nem implementált; régi hiányok és státuszok megmaradnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:226>). |
| [56. DUNGEON EXAMPLE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3040>) | 4, 14, 24: közös szolgáltatások minden domainhez | Mining/fishing/dungeon/PvP teljes támogatása e tervben nem implementált; régi hiányok és státuszok megmaradnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:227>). |
| [57. PVP EXAMPLE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3098>) | 4, 14, 24: közös szolgáltatások minden domainhez | Mining/fishing/dungeon/PvP teljes támogatása e tervben nem implementált; régi hiányok és státuszok megmaradnak. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:228>). |
| [58. UNKNOWN SITUATION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3153>) | 6, 16, 23, 26: bizonytalanság és visszaellenőrzés | Action, movement és objective sikere külön; recovery hatóköre és inputjog explicit. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:229>). |
| [59. NOVELTY DETECTION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3203>) | 6, 16, 23, 26: bizonytalanság és visszaellenőrzés | Action, movement és objective sikere külön; recovery hatóköre és inputjog explicit. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:230>). |
| [60. PLAN CONFIDENCE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3249>) | 6, 16, 23, 26: bizonytalanság és visszaellenőrzés | Action, movement és objective sikere külön; recovery hatóköre és inputjog explicit. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:231>). |
| [61. CLOSED-LOOP EXECUTION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3288>) | 6, 16, 23, 26: bizonytalanság és visszaellenőrzés | Action, movement és objective sikere külön; recovery hatóköre és inputjog explicit. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:232>). |
| [62. ACTION VERIFICATION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3335>) | 6, 16, 23, 26: bizonytalanság és visszaellenőrzés | Action, movement és objective sikere külön; recovery hatóköre és inputjog explicit. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:233>). |
| [63. FAILURE RECOVERY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3372>) | 6, 16, 23, 26: bizonytalanság és visszaellenőrzés | Action, movement és objective sikere külön; recovery hatóköre és inputjog explicit. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:234>). |
| [64. QUEST EXECUTION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3429>) | 13–14, 22–26: quest és tartós cél | Teljes quest és hosszú futás külön live kapu; tanult történet nem aktuális progress. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:235>). |
| [65. LONG-RUN AUTONOMY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3472>) | 13–14, 22–26: quest és tartós cél | Teljes quest és hosszú futás külön live kapu; tanult történet nem aktuális progress. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:236>). |
| [66. GOAL PRIORITY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3533>) | 13–14, 22–26: quest és tartós cél | Teljes quest és hosszú futás külön live kapu; tanult történet nem aktuális progress. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:237>). |
| [67. RESOURCE / INVENTORY STATE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3572>) | 13–14, 22–26: quest és tartós cél | Teljes quest és hosszú futás külön live kapu; tanult történet nem aktuális progress. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:238>). |
| [68. LEARNING FROM SUCCESS](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3628>) | 13–14, 22–26: quest és tartós cél | Teljes quest és hosszú futás külön live kapu; tanult történet nem aktuális progress. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:239>). |
| [69. LEARNING FROM FAILURE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3667>) | 13–14, 22–26: quest és tartós cél | Teljes quest és hosszú futás külön live kapu; tanult történet nem aktuális progress. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:240>). |
| [70. OFFLINE REPLAY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3706>) | 25–26: replay, golden és live bizonyíték | Ebben a munkában nincs új agentteszt vagy live futás, csak dokumentumellenőrzés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:241>). |
| [71. GOLDEN SESSIONS](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3760>) | 25–26: replay, golden és live bizonyíték | Ebben a munkában nincs új agentteszt vagy live futás, csak dokumentumellenőrzés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:242>). |
| [72. LIVE VALIDATION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3803>) | 25–26: replay, golden és live bizonyíték | Ebben a munkában nincs új agentteszt vagy live futás, csak dokumentumellenőrzés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:243>). |
| [73. OBSERVABILITY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3867>) | 25–26: replay, golden és live bizonyíték | Ebben a munkában nincs új agentteszt vagy live futás, csak dokumentumellenőrzés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:244>). |
| [74. WORLD MODEL QUERY API](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3923>) | 5, 11, 13: közös WorldModel/tudáslekérdezés | Fogyasztónkénti migráció és régi közvetlen TDB prioritás megszüntetése még tervezett. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:245>). |
| [75. PERFORMANCE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:3971>) | 13, 21, 26: teljesítmény és háttérmunka | Nem blokkoló tervezés/SQLite, queue-metrikák; célfrekvencia nem mért teljesítménygarancia. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:246>). |
| [76. SAFETY / ARCHITECTURAL BOUNDARY](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:4026>) | 4, 7, 23: változatlan capture/input határ | Nincs új memóriaolvasás, inputátvétel vagy közvetlen packetküldés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:247>). |
| [77. IMPLEMENTÁCIÓS SORREND](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:4084>) | 25 és a következő melléklet: ütemezés | T0–T8 nem az M0–M27 átnevezése; nincs gate-emelés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:248>). |
| [78. DEFINITION OF DONE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:4233>) | 25–27: elfogadás és végleges cél | A terv nem implementáció, offline replay nem live quest; a felhasználó későbbi döntése előtt nincs építés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:249>). |
| [79. FINAL PRODUCT DEFINITION](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:4313>) | 25–27: elfogadás és végleges cél | A terv nem implementáció, offline replay nem live quest; a felhasználó későbbi döntése előtt nincs építés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:250>). |
| [80. ULTIMATE PRINCIPLE](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:4373>) | 25–27: elfogadás és végleges cél | A terv nem implementáció, offline replay nem live quest; a felhasználó későbbi döntése előtt nincs építés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:251>). |
| [81. CODING AGENT BEHAVIOR](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:4450>) | 25–27: elfogadás és végleges cél | A terv nem implementáció, offline replay nem live quest; a felhasználó későbbi döntése előtt nincs építés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:252>). |
| [82. FINAL ARCHITECTURE TEST](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/docs/MASTER_AGENT_PROMPT.md:4508>) | 25–27: elfogadás és végleges cél | A terv nem implementáció, offline replay nem live quest; a felhasználó későbbi döntése előtt nincs építés. Státusz változatlan: [eredeti ledger](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:253>). |

## E. Történeti M0–M27 nyomkövetés

A 0–82 master M0–M27 sorozata és a későbbi V4 determinisztikus M0 / quest M1 fogalmai régi specifikációs jelölések. A jelen célhoz a fő terv T0–T8 ütemei tartoznak. A korábbi kapuk fájlbeli státuszát ez a dokumentum nem változtatja meg; a vizuális elvárások nem követelményei az új célnak. Az új működéshez saját offline és user-live elfogadási bizonyíték kell.

| Master milestone | Tervezett érintettség | Állapot |
|---|---|---|
| [M0](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:301>) | T0: forrásaudit és megőrzött baseline | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M1](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:302>) | T0/T8: aktuális user-live baseline és összehasonlítás | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M2](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:303>) | T1/T2: normalizált Observation és packetes baseline | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M3](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:304>) | T1/T4: időbeli állapot és mozgáskövetés | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M4](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:305>) | T1: mezőnkénti evidence/belief | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M5](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:306>) | T1–T3: egy közös WorldModel | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M6](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:307>) | T1/T3: entitás, több hely és live életciklus | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M7](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:308>) | T3: szerveres/addon memória provenance és kontextus; a vizuális rész történeti | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M8](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:309>) | T2/T3: normalizált eseménynapló | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M9](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:310>) | Megőrzendő; prediktív részek új igazolása külön feladat | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M10](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:311>) | T2: questdefiníció és aktív állapot | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M11](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:312>) | T2/T3: objective és mechanikafüggőség | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M12](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:313>) | T1/T3/T5: közös planner és költség | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M13](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:314>) | Meglévő registry; új tények a preconditionbe | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M14](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:315>) | T2–T8: végrehajtás és bizonyítás külön | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M15](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:316>) | T3: sikeres mechanikák feltételes tanulása | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M16](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:317>) | T3/T8: általánosítás külön próba | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M17](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:318>) | Bizonyítékszerzés packetből/addonból; képi keresés és követés kívül esik a célon | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M18](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:319>) | Legfeljebb opcionális szöveges adviser; képi/VLM ág nélkül | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M19](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:320>) | T0/T7/T8: forráshealth és mért késleltetés | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M20](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:321>) | T4–T6: közös utazás és három mozgási mód | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M21](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:322>) | T2/T3/T7: aktuális címzett és UI verification | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M22](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:323>) | Meglévő közös gathering képességek; teljesítésük nem e terv feladata | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M23](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:324>) | T3/T4: élő cél, itemforrás és közös combat/nav | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M24](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:325>) | Meglévő domain helye megmarad; teljes dungeon nincs újra minősítve | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M25](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:326>) | Meglévő domain helye megmarad; PvP hiányok külön | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M26](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:327>) | T0/T8: tartós cél és visszaállás | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |
| [M27](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/MASTER_COVERAGE.md:328>) | T8: külön felhasználói soak/live elfogadás | Nincs új acceptance-állítás; eredeti ledger és dátumos kiegészítései érvényesek. |

## F. Ellenőrzés és a terv korlátai

A leltár forrásparse-ot, teljes mező-hozzárendelést, függőségi besorolást, 83 master-pont és 28 milestone jelenlétét, helyi fájlhivatkozásokat és forrás-hasheket ellenőriz. Ez a dokumentum konzisztenciáját támogatja; nem az új architektúra működését teszteli.

A mai hiányok közül kifejezetten nyitott: addonfüggetlen packetbootstrap; teljes quest/player/inventory baseline; új quest/loot/spell payloadok exact-build igazolása; minden objective-POI bekötése; a friss közös repülési integráció teljes viselkedésének ellenőrzése; általános 3D collision és megbízható teljes flight módválasztás; TDB nélküli ismeretlen drop/script reláció; class/spec profilok, enemy cast/interrupt/CC és időzített AoE; automatikus talentadat/UI/commit és build-kompatibilitás; átállítás utáni user-live és hosszú futás. A meglévő részfunkciók tesztjeit a terv nem nullázza le.

A fő terv és ez a melléklet a külön outputmappában készült. A tényleges projekt forrásai, configjai, adatbázisai, addonja és ledgerei ebben a munkában nem kaptak módosítást. Nincs indított kliensvezérlés/capture vagy új live esemény. Saját fájlhash-ellenőrzés nem helyettesít futó process auditot, és a párhuzamos, más munkából származó fájlmódosításokat külön jelzi a validáció.


## G. Új combat- és talentadatok — tervezett bővítés

Ezek az új követelményekhez szükséges tervezett adatkörök. Nem részei automatikusan a fenti 84/42 mezős leltárnak vagy a mai 22 eseménytípusnak. Forrásonként és exact-build szemantikával külön kell őket bekötni; a class alapadata már van, a teljes profil/cast/hazard/talent-életciklus nincs e terv által igazolva.

| Adatkör | Tervezett tartalom |
|---|---|
| Saját karakterprofil | class/spec ID, szint, szerep, aktív konfiguráció és revizió, forma/stance, pet, erőforrások, ismert és elérhető képességek |
| Harci spellprofil | Mechanikai szerep, range/költség, cooldown/charge, cél/facing/LoS feltétel, aktív bar/binding és tényleges readiness |
| Enemy cast/channel | caster és castpéldány, spell, start/update/end/tick, tényleges ismert cél vagy koordináta, szakíthatóság, forrás/frissesség |
| Interrupt/CC eredmény | A konkrét cast megszakítása vagy kontrollált leállása, siker/kudarc/immune és releváns aura; természetes castvég külön |
| Harci veszély | Időzített alakzat, hely/irány/pálya, map/floor/Z, aktiválás/lejárat, tényleges veszélyhatás és bizonytalanság |
| Talentállapot | Ponttípus és egyenleg, tree/node/entry/rank, feltétel/költség, aktív config/build, pending preview és alkalmazás külön |
| Talent UI-aktiválás | Addonból kapott látható node/choice/apply horgony és állapot; normál kliensinput, utána tényleges configigazolás |

---

# H. 2026-10-29 — Új source-authority és core-capability adatkontraktusok

> Tervezési kiegészítés. Nem állítja, hogy az alábbi mezők és providerek már teljesen implementáltak.

## H.1 Forrásfelelősség végleges iránya

```text
PACKET          = aktuális world/server truth
ADDON           = kliens/UI truth
DB2/TDB         = statikus vagy kontextusos referencia
MAP/VMAP/MMAP   = geometria / navigációs felület
MEMORY          = korábbi tapasztalat, nem aktuális authoritative state
```

A source authority mezőnként értendő, nem globális prioritási listaként.

## H.2 Minimal Addon Contract

A cél-addon minimális producerkategóriái:

| Kategória | Példa | Miért addon? |
|---|---|---|
| Addon transport meta | protocol/schema/session/sequence/timestamp | Saját csatorna frissessége és konzisztenciája |
| Client lifecycle | loading, input_blocked, player_present, UI error | A szerver nem ismeri a lokális input/UI állapotot |
| Local action context | active actionbar, override/vehicle bar, usable local slot, binding context | A szerveradat nem bizonyítja a konkrét kliens gyorsbillentyű jelentését |
| Quest/Gossip/Reward UI | open state, visible row/button, reward choice, local anchor | UI-interakcióhoz lokális kliensállapot kell |
| Bag/Talent UI | visible state, node/choice/apply UI állapot | Kliens UI workflow és normál input aktiválás |
| Soft interaction context | soft-interact recipient, szükséges mouseover/local recipient | A tényleges kliensoldali címzett külön tény |

World entity, world position, combat unit state, enemy cast, quest-credit, scene és más szerver által meghatározott mező a validált packet provider elkészülte után ne maradjon addon-authority.

## H.3 Addon kiváltási kapu

Egy mező csak akkor törölhető addonból, ha mind teljesül:

```text
packet parser exact-build valid
→ normalized event/schema valid
→ baseline + delta lifecycle valid
→ WorldModel projection valid
→ all consumers migrated
→ freshness/unknown semantics tested
→ replay/live comparison acceptable
```

Külön prioritás: a packet bootstrap ne függjön az `addon_context` lététől.

## H.4 TravelRequest / TripPlan adatkontraktus

Javasolt magas szintű mezők:

```text
TravelRequest
- destination_ref / xyz
- map/instance/floor
- arrival_radius / envelope
- face_on_arrival
- interaction requirement
- urgency
- allowed/disallowed travel modes
- safety constraints

TripPlan
- plan_id / revision
- legs[]
- expected ETA
- RouteScore
- invalidation conditions
```

Leg típusok:

```text
GROUND
MOUNT_TRANSITION
TAKEOFF
FLIGHT
LANDING
DISMOUNT
```

## H.5 RouteScore / Risk adatok

```text
eta
distance
combat_cost
danger_cost
transition_cost
failure_risk
confidence
```

Ground risk input:

```text
hostile GUID/position
estimated aggro/exposure radius
route intersection / exposure time
engaged vs non-engaged
elite/caster/special risk
expected combat probability
expected fight delay
expected HP/resource loss
death/recovery risk
terrain/water/stuck penalty
```

Flight risk input:

```text
takeoff/landing suitability
open-sky / indoor status
clearance profile
flight capability/state/resource
failure history
```

## H.6 Combat core adatok

### Target/Facing

```text
current_target_guid
target_candidates[]
target_score / reason
target_commitment
target_position / distance
player_facing
desired_facing
angle_error
range/reachability
```

### Ability

```text
AbilityDefinition: spell/range/cost/gcd/cast/channel/cooldown/charges/tags
AbilityState: known/talented/bound/active_bar/ready/cd_remaining/resource_ok/in_range/usable
```

### Multi-target

```text
CombatEntitySet
active_enemies
engaged_enemies
nearby_non_engaged
priority_targets
dangerous_casters
aoe_cluster
```

### Combat arbitration

```text
ActionCandidate
- type
- producer subsystem
- target
- utility / priority
- deadline
- preconditions
- cost
- movement conflict
- verification contract
```

## H.7 Combat role és group adatok

```text
role = TANK | HEALER | DPS_MELEE | DPS_RANGED | DPS_SUPPORT
content = SOLO | DUNGEON | RAID | BATTLEGROUND | ARENA | WORLD_PVP
```

`GroupCombatContext`:

```text
members[]
role assignments
tank/healer identity
HP/debuff/death state
threat ownership
current pull
positions
objective / encounter phase
```

PvP specifikus jelöltek:

```text
kill_target
cc_target
enemy_healer
diminishing_returns
major_defensive/trinket state
BG objective role
```

## H.8 QuestExecutionGraph adatkontraktus

```text
QuestExecutionGraph
- quest_id
- nodes[]
- dependencies
- alternatives
- parallel groups
- active executable nodes
```

`ObjectivePlan`:

```text
objective_id
mechanic_type
nav_target
entity_target
interaction_target
spell_target
credit_target
search_region
required_item/spell/state
completion_signal
confidence/evidence
```

`MechanicContract`:

```text
preconditions
action
expected_evidence
success_condition
failure_reasons
recovery_options
```

FailureReason legalább:

```text
TARGET_NOT_FOUND
TARGET_IDENTITY_AMBIGUOUS
LOCATION_UNKNOWN
ROUTE_UNREACHABLE
WRONG_FLOOR
MISSING_ITEM
MISSING_BINDING
MECHANIC_UNKNOWN
MECHANIC_UNSUPPORTED
INTERACTION_FAILED
SPELL_NO_EFFECT
NO_OBJECTIVE_PROGRESS
SCENE_NOT_RESOLVED
WAITING_SERVER_STATE
STALE_DATA
PHASE_MISMATCH
```

---

# Forrásaudit utáni függőségi kiegészítés

A tényleges kódban a packet pipeline jelenleg addon-context függő. A `packetio/context.py::addon_context_status()` és `addon_context()` a `game_build`, `session_id`, `character_guid`, `map_id`, `player_world_position.instance_id`, `loading`, `player_present` mezőket használja; `RuntimePacketSource` erre építi a packet session signature-t, a `world_packet_reducer.py` pedig ezzel ellenőrzi több projekció scope-ját.

Ezért az addon karcsúsítás kiváltási kapuja:

```text
SessionContextProvider kész
+ packet own-player/session bootstrap igazolt
+ reducer scope check átállítva
=> csak ezután törölhető az addonból a bootstrapként használt world-state mező
```

Új source-authority elv:

- PACKET: world/server state;
- ADDON: client/UI state;
- DB2/TDB: referencia;
- MAP/VMAP/MMAP: geometria;
- MEMORY: történeti tapasztalat.

Új package-függőségi szabály: a `combat`, `travel`, `quest` domain package-ek ne függjenek közvetlenül `wowbot.agent.*` moduloktól. A szükséges modellek/contracts közös runtime/world/domain contract rétegbe kerüljenek.
