# REV4 P1-B — közös session- és világkontextus

2026-10-29, Europe/Budapest. **A jelen munkacsomag IMPLEMENTED / OFFLINE_TESTED; a teljes P1 továbbra is PARTIAL.**
Az aktív projekt a projekt nevű mappa. Nem történt új élő teszt, addontelepítés, kliensvezérlés vagy capture-indítás.

## Bekötött szerződés

A közös wowbot.context_contracts modul három immutable értéktípust vezet be: SessionIdentity, WorldContext és SessionContext. A modul kizárólag a standard libraryt használja; nincs agent-, vision-, navigációs vagy packet-provider függése, és nem hoz létre új állapottulajdonost.

- SessionIdentity: kiválasztott PID, session_id, saját karakter-GUID, kliensbuild.
- WorldContext: a meglévő instance_id világ-/navigációs térképazonosító, ettől külön a UI-map, valamint az ismert vagy unknown phase.
- SessionContext: ellenőrzött értékpár és kompatibilis, hétmezős szótáradapter.

Az instance_id korábbi elnevezése megmarad: ez nem bizonyít egyedi dungeon-instance azonosságot. A 0 érvényes világazonosító lehet. A phase=None unknown marad; nem lesz belőle kitalált alap-phase vagy 0. A logikai kontextus nem helyettesíti az IPC runtime/context nonce-ot, a mintavételi időt vagy az input-authority ellenőrzését.

A packetio.context meglévő addon_context / addon_context_status függvényei kompatibilis facade-ként használják az új értékeket. Az értékelés VALID / PENDING / MISMATCH állapotot és hiányzó mezőket ad; PID-t kizárólag az explicit kiválasztott PID-hez kötéskor kap. A régi waiting_for_addon_context / unsupported_game_build okok megmaradnak. Hibás típusú azonosító, map vagy phase nem válik érvényes kontextussá.

A RuntimePacketSource ebből az értékelésből hozza létre a saját immutable session_context értékét és a meglévő IPC-szótárat. Változatlan logikai kontextus nem generál új nonce-ot. Hiányzó vagy hibás új kontextus lezárja az előző aktív fogadói kontextust. A diagnosztika külön mutatja a kontextus állapotát és a hiányzó mezőneveket; a GUI a hibás kontextust/PID-t is megkülönbözteti a várakozástól.

## Javított hibák

1. A feldolgozásra váró packet-entitás/POI adatok régi összevetéséből kimaradt a session_id és a phase. Azonos PID, karakter, világ és build mellett így egy régi session vagy phase entitása később az új kontextushoz kötődhetett. A várakozó sor most teljes session/world hatókört őriz, az eredeti mintavételi idő megtartásával.
2. A tárolt entitás-, quest-credit-, POI- és scene-hatókörből kimaradt a phase. Az érintett projekciók most azonos közös hatókört használnak. A session/phase-váltás érvénytelenít, míg a puszta UI-térképváltás ugyanabban a világban megtartja az entitást.
3. A NEW_WORLD eredetű szervertérkép-hint az entitástábla hatóköréhez képest volt ellenőrizve. Üres entitástáblánál átcsúszhatott egy korábbi phase térképe; hiányzó world-context alatt pedig a cache-ben maradva később újra megjelenhetett. A hint most közvetlenül az aktuális kontextushoz van ellenőrizve. A régi entitás-térképminták sem keverednek az új hatókör mintáihoz.

Az IPC-aláírás, a teljes transport-context összevetése, a selected-PID ellenőrzés, a build/layout allowlist, a kétmásodperces mintafrissesség és a packet/adatforrás input-authority különbsége megmaradt. Ezeket nem váltja ki az új logikai összevetés. A bootstrap továbbra is addonfüggő; az adatok forrásprioritása ebben a munkacsomagban nem rendeződött át.

## Ellenőrzés

| Próba | Eredmény |
|---|---|
| Első regresszió a forrásjavítás előtt | **5 failed, 3 passed**: phase-cache és négy hibás pending-újrakötés reprodukálva; a helyes context/UI-map kontrollok sikeresek |
| Szervertérkép-próba a P1-B előtti mentésen | **1 failed**, a régi phase hintje megmarad |
| Két új kontextusteszt-modul a végső körben | **55 passed** |
| Packet/context/GUI/client részhalmaz a végső körben | **276 passed** |
| Végső kombinált regresszió | **3292 passed, 1 failed, 1 skipped, 10 deselected**, 260 modul, pytest: 97.39 s, exit 1 |
| Új tesztkizárás | **0**; a korábbi tízes lista változatlan |
| Szintaxis | **500 forrásmodul + 595 teszt-Python-fájl**, 0 parse-hiba |
| Addon | A korábbi baseline mind a **8 addonfájlja változatlan** |
| Élő teszt / asszisztens által indított WoW/capture/FULL_AI | **Nem történt** |

A helyi UDP körteszt a sandboxban nem kapott datagramot; a módosítás előtti mentés és egy két egyszerű UDP-socketből álló kontroll is ugyanezt mutatta. A sandboxon kívüli külön körteszt sikeres, és a végső kombinált kör is tartalmazza a sikeres valódi localhost továbbító→fogadó utat. Ez környezeti tesztkorlátozás volt, nem igazolt új fogadóhiba.

A kombinált kör egyetlen megmaradt bukása:

test_quest_drop_combat_handoff_20261028.py::test_ambiguous_blank_reference_rows_do_not_pick_a_collect_objective_by_index

Ugyanez a teszt a külön visszaolvasott P1-B előtti forrásmentésen is hibás 990401 → 990201:0 kapcsolatot ad. Az ambivalens, üres referencia-objective-k összerendelése továbbra is nyitott hiba. Nem került új kizárás mögé; a teljes tesztkör ezért nem nevezhető zöldnek. Az offline próbák nem igazolnak teljesített valódi questet.

## Nyitott követelmények

Ez a meglévő határ első közös értékszerződése, nem a teljes SessionContextProvider. A folyamat indulási idejének/PID-újrafelhasználásának ellenőrzése, a capture/world revision, az egyedi instance-azonosság, a packet baseline+delta életciklus és az addonfüggetlen cold/warm bootstrap még nincs elkészítve. A phase a jelen forrásokból csak akkor ismert, ha ténylegesen megérkezik; az ismeretlent ez a változás nem oldja fel.

A további P1 query-/geometry-portok és Evidence-szerződés, majd a P2 bootstrap és a P3 mezőnkénti source authority külön kapuk. A no-vision runtime, TripPlan, combat- és questmechanika-átszervezés későbbi fázisok; ezeket a jelen típusok megléte nem teljesíti. A számozott V4/Design coverage-sorok és történeti live minősítések változatlanul megmaradtak.

## Visszaállíthatóság és bizonyíték

A P1-B előtti baseline.zip **1095** forrás-, teszt- és követési fájlt őriz byte-hashekkel a baseline.json mellett. A P1-A utáni állapotot menti, tehát az előző munkacsomag javításai is megmaradnak.

Mentés és teljes tesztkimenet: C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1b-20261029.
A kis bizonyítékcsomag a dokumentum melletti p1b-evidence/ könyvtárban található. A validation-summary.json a teszteredményt és a nyitott részeket, a change-manifest.json a forrás/teszt/követési módosítások régi/új hashét, a changes.diff a szöveges változásokat rögzíti. Az IPC/build/parser/input-owner fájlok változatlansága külön ellenőrzött.

Az új Python-forrást a GUI következő indítása tölti be. Az élő teszteket továbbra is a felhasználó vezeti; a jelen csomag nem ad új capture- vagy inputjogosultságot.
