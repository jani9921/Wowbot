# REV4 P2/P3 — saját questlog slotok és packetfolytonosság

2026-10-30, Europe/Budapest. A kijelölt `projekt` módosítása.

**Offline tesztelt részadatút. A teljes packetes questdefiníció/progress és
inventory-paritás továbbra is PARTIAL.** A közös WorldModel/Query/QuestModel
architektúra megmaradt; nem keletkezett külön questtervező vagy inputút.

## Natív slotolvasó

A pinnelt WPP `UpdateFieldsHandler1215` 70340-es családjához igazított olvasó
a saját PlayerData VALUES blokk ismert QuestLog-prefixét kezeli:

- 175 slot; slotonként QuestID, StateFlags, EndTime, ObjectiveFlags,
  EnabledObjectivesMask és 24 ObjectiveProgress tárolóhely.
- A teljes slotminta és a belső mező-/számláló-delta eltérő maskot használ.
  A hiányzó érték `None`; a QuestID=0 tényleges üres slot.
- A megelőző, ismert méretű saját mezők átugorhatók. Account/guild/player
  azonosítók és nevek nem kerülnek a normalizált eseménybe. Ismeretlen dinamikus
  map/array/névblokk vagy nem teljesen bejárt megelőző UnitData-tail esetén
  questslot nem keletkezik találgatott offsetről.
- A `OWN_QUEST_LOG_UPDATE` csak igazolt saját login, ismert fragment, selected
  PID/GUID/build/world és a külön `WPP_12_1_QUEST_LOG_REVIEWED_V1` layout mellett
  lesz szemantikai adat. Másik játékos slotolvasója meg sem hívódik.
- A kompakt, szigorúan numerikus slotformátum 175 maximális értékű rekorddal
  együtt is elfér a meglévő 60 000 bájtos IPC-kapun. Hibás alak, bool helyetti
  szám, ismételt slot, csonkolás és túlcsordulás elutasított.

A WorldModel meglévő packetreducere birtokolja az adatot. A `WorldQuery`
`quest_log_slots()` és `quest_presence()` saját másolatot ad, nincs input- vagy
tervezési mellékhatás. Csak az összes slot friss, ismert QuestID-ját igazoló
baseline bizonyíthat ABSENT tagságot. Részleges vagy lejárt lista UNKNOWN.
Ez az ABSENT **nem** questleadási/abandon-nyugta.

Egy tárolóhelyen a quest lecserélése törli az előző quest számlálóit. A részleges
frissítés csak az érintett mezőket mintázza újra, az identitás és a többi számláló
eredeti ideje/evidence-ID-ja megmarad. A normál tick státusza csak lefedettséget
és darabszámot vetít ki; a 175 slot teste csak explicit queryn másolódik.

## Folytonossági hiba és javítás

A SessionContextProvider már korábban is törölte saját coverage-jelzőit egy GAP
állapotnál. A tényleges hiba a WorldModelben maradó packet-cache és evidence volt:
ugyanazon identitás/map mellett az identitás-baseline újbóli elfogadása után a régi
HP-/questslot-baseline életben maradhatott. Az új HP-delta így tévesen örökölhette
a korábbi COMPLETE jelzőt. Ezt valódi decoder → hitelesített inbox → reducer
teszt reprodukálja.

Most külön `continuity_generation` változik adatkimaradás, új capture-korszak és
valódi entity-scope váltás esetén. A közös packetkapu érvényteleníti az előző
aktuális cache-eket és packet-evidence-t; az immutable Observation/history
megmarad. A readonly field/belief/slot query már a következő projekció előtt is
kizárja az előző generációt. Addon UI-adat nem lesz ettől újabb vagy hitelesebb.

Az új semantic packetek a decoder valódi `capture_epoch` azonosítóját hordozzák.
A RuntimePacketSource és a WorldPacketReducer is kizárja a másik vagy hiányzó
korszakot, ha már ismert a provider aktuális korszaka. Folyamat-/karakter-/map-
azonosság önmagában nem helyettesíti ezt. Stabil baseline-replay és pusztán UI-map
változás megtartja a helyes cache-t; régi capture nem kerül át az új endpointon.

A régi, még futva maradt Python packetforrás nem feltétlenül küldi az új mezőt.
Ez konkrét `source_restart_required` státuszt és a GUI-ban **„forrás újraindítandó”**
jelzést ad. Másik korszakra **„capture-korszakra vár”** látható. A helyes új minta
után a jelzés automatikusan törlődik. A forrást/capture-t az asszisztens nem indította
vagy indította újra. A Ymir bináris és az addon nem módosult.

## Korlátok és következő kódos kapuk

1. A teljes saját CREATE UnitData→PlayerData blokklánc még nincs dekódolva. Ez az
   út a VALUES-ban kapott, ismert elrendezésű teljes/részleges slotfrissítést
   kezeli; nem állítja, hogy minden login automatikusan teljes slotbaseline-t ad.
2. A slotok a tagságot és a nyers storage-számlálókat adják. Questdefiníció,
   objective ID, StorageIndex és UI-sor nem vonható össze találgatással. A
   QuestModel aktív objective-jei/countjai ezért itt nem íródtak át.
3. A `questlog` összesített provider-coverage PARTIAL marad teljes slottagság
   mellett is, amíg a definíció-/objective-/consumer-paritás nincs kész.
   Addon questmező nem lett eltávolítva; TDB-név/order nem pótol bizonyított
   server objective/storage kapcsolatot.
4. Full inventory/container, aura/spec/talent/CC, interruptibility/hazard,
   történeti import-lineage és további mechanikák nyitottak. Új élő elfogadás nincs.

## Ellenőrzés

A sajátállapot/slot/session/policy célzott kör **117 passed**. A nagy regresszió
**3765 passed, 2 skipped, 10 változatlan deselection, 308 modul, 143.93 s, exit 0**.
Mind az 529 source és 617 test Python-fájl AST-parse ellenőrzése zöld.
A két skip korábbi opcionális képfájlhiány; ez nem a teljes 616 modulos teszttár
hibamentességének állítása. A célzott eredmény átfed a nagy körrel.

A nagy regresszió
pontos eredményét, változatlan kizárásait, AST- és hashbizonyítékát a külön
[native-questlog-evidence](native-questlog-evidence/) checkpoint tartalmazza.
A korábbi [provider-closure-evidence](provider-closure-evidence/) változatlan
baseline-ként megmarad. A 203 számozott V4/Design követelménysor megőrzött.

Az új UI-státusz tesztje tiszta függvénypróba, a decoder/query próbák szintetikus
packetek. Az asszisztens nem indított WoW-ot, Ymir-t vagy FULL_AI-t, és nem küldött
kliensinputot. A felhasználó korábbi addon-betöltési visszaigazolása továbbra is
nyitott; a 0.9.80 telepített forrásai ettől a Python-munkától nem változtak.
