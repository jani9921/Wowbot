# Auditált packet-telemetria port

## 2026-10-28: aktuális szerveres quest-POI állapot

A jelenlegi, külön engedélyezett 70575 capture-útban az
`SMSG_QUEST_POI_QUERY_RESPONSE` (`0x65001D`) most `QUEST_POI_UPDATE` eseményt
ad questenként. A helyi WPP-kezelő 12 darab int32 blobmezője, int16 X/Y/Z
pontjai és egybájtos bitmezője alapján készül; a 16:41-es és 16:59-es éles
fájl mind a négy válasza a production dekóderrel is teljesen feldolgozható.
A régebbi, nem ellenőrzött payload-család nem kap ebből szemantikus tényt.

- Payload: numerikus `quest_id`, `blobs`, opcionális `capture_timestamp`.
  A blob megőrzi a csoport sorszámát, BlobIndex-et, objective indexet/ID-t,
  térképeket, feltételeket, build-provenance-t és XYZ pontokat. Az ismétlődő
  BlobIndex önmagában nem csoportazonosító.
- Keretek: legfeljebb 64 quest, 64 blob/quest és 512 pont/quest; teljes
  payload-ellenőrzés, részleges szemantikus eredmény nélkül. Szabad szöveg,
  nyers payload és ismeretlen beágyazott mező nem jut át.
- A producer legfeljebb 64 aktuális POI-snapshotot tart az induló fogadónak.
  A `capture_timestamp` az eredeti időt őrzi, nem friss szerverészlelésként
  címkézi újra a régi geometriát. Legfeljebb 1800 másodperces adat használható;
  térképváltás töröl, új/üres szerverválasz felülír. A hitelesített IPC,
  kiválasztott PID/build/session/karakter és aktív quest továbbra is kötelező.
- A WorldModel egyelőre a -1 objective indexű leadóblobokat vetíti ki;
  a többi geometria megmarad az ownernél, de nem kész területbejáró funkció.
  A leadópoint navigációs keresési cél. Nem NPC-azonosság, inputjog vagy credit.

Ez a rész a mostani dekóderre vonatkozik. Az alábbi 2026-10-15-ös állapot
az eredeti port történeti dokumentációja; a későbbi live evidence-t a
`LIVE_VALIDATION.md` és az aktuális capture státusz írja le.

Állapot: **2026-10-15 — átemelve a `projekt` munkapéldányba, offline tesztelve;
élő Npcap/Ymir adatút és teljes Retail payload-lefedettség NINCS validálva.**

**Pontosítás a felhasználó kérésére:** ez jelenleg kutatási/prototípus
packet-telemetria keret, nem kész, beépített élő sniffer. Az elvárt végállapot
az agenttel együtt kezelt, kiválasztott PID-hez kötött capture → decode →
evidence, kézi PKT-fájlválasztás nélkül. Ennek producer/decode része hiányzik;
a GUI-BAT csak az inboxot engedélyezi. A parser/családtesztek nem igazolják
a hálózati titkosítás kezelését vagy bármely Ymir bináris kompatibilitását.

2026-10-15-én a hivatalos GitHub Releases API és
[Ymir Retail kiadás](https://github.com/TrinityCore/ymir/releases/tag/12.1.0)
alapján a közzétett Retail asset `ymir_retail_12.1.0.69933.zip`; a felhasználó
70391-es buildjéhez nem találtunk kiadott, igazolt csomagot. A nyilvános
[repo](https://github.com/TrinityCore/ymir) README-t tartalmaz, implementációs
forrást nem. A működéséből nem állítjuk bizonyíték nélkül sem az injectiont,
sem a teljesen passzív/no-memory megvalósítást. Nem telepítettünk/indítottunk
régi binárist, Npcapot, és nem töröltük a WoW cache-ét. Az upstream README
figyelmeztet: a teljes sniff személyes adatot is tartalmazhat. Nyers Ymir
capture-t nem szabad automatikusan közzétenni vagy az agentbe továbbítani.

Forrás: `C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2`.
Cél: `C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt`.
A forrás 12 `packetio` fájlja és a launcher SHA-256 alapján változatlan maradt.
A régi `runtime.py`, `world.py`, `gui.py` nem került rá a frissekre: külön,
a jelenlegi reducer/observation/lifecycle felosztáshoz illő bekötés készült.

## Adatút és jogosultság

```text
Explicit kiválasztott PID + kézzel kiválasztott passzív bemenet
  → Npcap/TCP vagy meglévő, felhasználó által megadott PKT 3.1
  → buildhez ellenőrzött, szűk parser
  → mező- ÉS érték-allowlist; ismeretlen adatból csak darabszám/hash
  → aláírt localhost UDP, aktuális runtime/addon kontextussal
  → korlátos inbox, mozgásminták coalescingja
  → RuntimePacketSource → Observation(PACKET_TELEMETRY)
  → WorldPacketReducer → az egyetlen WorldModel / evidence / event út
```

A packet sensor nem választ skillt, nem nyom gombot, nem állít FULL_AI módot,
nem tesz egy régi addonmintát frissé. A gyors vezérlési szál, a kiválasztott PID,
a binding-cache, a friss addon és a meglévő executor marad az input feltétele.
Fogyasztás a meglévő közepes fúziós körben történik; ez nem új 30 Hz-es
packet-navigációs vezérlő és nem FPS-ígéret.

Nincs kliensmemória-olvasás, injection, játékmódosítás, kulcskinyerés vagy
titkosításmegkerülés. A kód nem indít Ymir-t vagy más sniffer-producert,
és nem telepít drivert. Csak már létező, engedélyezett adatforrást olvas.

## Az audit során javított problémák

- A forrás manifest-loadere a hívó által megadott buildcímkét használta anélkül,
  hogy a C# tábla eredetét ellenőrizte volna. Most explicit buildcsalád,
  namespace és normalizált tartalomhash van; közeli buildre nincs fallback.
- Attack-start GUID-ok: két packed GUID128, nem két 64 bites szám.
  Attack-swing error: a felső két bit adja az okot, nem az alsó kettő.
- NEW_WORLD: a floor mezők megelőzik a reason mezőt. A szerver `world_map_id`
  nem írható a UI `map_id` helyére. A jelentés nem teleportálja a WorldModelt.
- Egy outgoing mozgás nem feltétlenül a játékos: vehicle/controlled mover is
  lehet. Csak a Player GUID típusának, realmjének és teljes low értékének
  egyezése engedi a saját XYZ/facing projekciót. Transporton/objektumon álló
  mover jelenleg nem ad navigációs felülírást.
- A régi, aláíratlan UDP-bemenet saját állítása szerinti PID-je kevés volt.
  Most futásonkénti helyi HMAC-képesség és session/karakter/térkép/instance/
  phase/build kontextus kell. A régi kontextus sorai váltáskor törlődnek.
- Az inbox a valós fogadási időből és forrásidőből számolja a mintavételi kort;
  régi/jövőbeli csomagot nem bélyegez át frissre. A navigációs felülírás legfeljebb
  0,75 s-os, frissebb addonminta elsőbbséget kap, az addon instance megmarad.
- TCP: overlap, uint32 sequence wrap, SYN/FIN/RST és korlátos gap/stream tárolás.
  Töredékes/truncated IP-datagramból nem készül TCP-tény.
- PKT-fájlcsere/truncation után parser és decoder is újraindul. Nincs nyitva
  tartott fájl a várakozás/yield idején, ami Windowson megakadályozná a cserét.
  A parser feedenként egyszer tömöríti a buffert, nem minden rekord után.
- A sidecar az endpointot cache-eli, nem minden eseménynél olvassa lemezről.
  A nagyfrekvenciás packet Observation nem kerül lépésenként SQLite-ba;
  a diszkrét, felismert események a meglévő event/replay útvonalon maradnak.

## Build és ténylegesen értelmezett mezők

Két külön ellenőrzött opcode-család van (nem egymás fallbackjei):

- **12.1.0 → 69214** tábla:

`69214, 69273, 69283, 69299, 69323, 69382, 69404, 69465, 69497, 69587, 69814, 69875, 69933`.

- **12.1.5 → 70340** tábla: `70340, 70391, 70448` (a WPP a 70448-at kifejezetten erre a táblára aliasolja).

Forrás: TrinityCore/WowPacketParser, commit
`1a72288ca3fab3363b99965d5e9782b99cd6803b`,
[opcode-család feloldó](https://github.com/TrinityCore/WowPacketParser/blob/master/WowPacketParser/Enums/Version/Opcodes.cs).
A teljes 69214 tábla normalizált UTF-8/LF SHA-256-ja:
`5e4387ac682620c7ca45013fa554ad14ca8e619d8a9fe45ce5ceb8f33519ef2c`.
A teljes 70340 tábla normalizált UTF-8/LF SHA-256-ja:
`dcb59d20e7def7014a20b8708b5ca6c6089aa97cab497e9dac6d25ec0a47bcc0`.
Mind a 106 beépített opcode-azonosítót külön összevetettük mindkét rögzített
táblával: ebben a szűk részhalmazban egyeznek. Ettől a két teljes tábla és
a payload-maskok nem válnak felcserélhetővé. A prefixekhez a rögzített WPP
MovementStats1210 / teleport / NEW_WORLD / quest-complete / combat olvasási
útvonalait is ellenőriztük; UPDATE_OBJECT maskokat továbbra sem találgatunk.

A port tartalmazza a releváns opcode-azonosítók szűk, ellenőrzött listáját;
nem kell hozzá a teljes WPP repót átmásolni. Opcionális külső `Opcodes.cs` csak
a rögzített hash/namespace/család egyezésével fogadható el. Megosztott opcode-
tábla önmagában nem bizonyít minden payload-layoutot: csak az alábbi felülvizsgált
prefixmezők engedettek, más adat UNKNOWN marad.

- CMSG_MOVE támogatott változatok: GUID, flags, move_time, XYZ/facing és a közös
  prefix/transport jelzők. A teljes opcionális movement tail nem feldolgozott.
- SMSG_NEW_WORLD: szerver map, XYZ/facing, floor és reason — kontextusevidence,
  nem UI-map felülírás.
- SMSG_MOVE_TELEPORT: mover/pozíció prefix — evidence, nem saját outgoing mozgás.
- SMSG_QUEST_UPDATE_COMPLETE: kész quest, **nem** leadott quest; csak a tényleges
  aktuális logban ismert questet frissítheti. Failed/timer külön jelzés.
- SMSG_ATTACK_START és ATTACK_STOP: GUID-pár; saját résztvevő ellenőrzése.
  `ATTACK_STOPPED(now_dead)` nem jelent globális combat-endet vagy lootjogot.
- SMSG_ATTACK_SWING_ERROR: CANT_ATTACK / OUT_OF_RANGE / BAD_FACING / DEAD_TARGET.

### 12.1.5 / 70448: szerveroldali NPC-tények (2026-10-19)

Csak a 70340-családban (`FAMILY_OPCODES`, a 69214-es táblával nem vetettük össze).
A layoutot valódi Ymir 70448 dumpon ellenőriztük (13:23, Exile's Reach). Provenance:
`RETAIL_70448_CAPTURE_VERIFIED_V1`, és ez csak ezt a két eseményt erősítheti meg:

- **SMSG_ON_MONSTER_MOVE → `ENTITY_POSITION`**:
  - Mező: mover GUID és a záró Vector3. Ez a spline **kezdőpontja**: a dumpban
    pontosan egyezik az előző spline célpontjával (medián eltérés 0,0 yd).
  - Megállás vagy egypontos spline esetén a pozíció → cél / move_time aránya
    2,5 yd/s, ez a mob gyaloglási sebessége.
  - A spline célpontját ma már a teljes WPP-alapú parse olvassa (lásd lent).
  - Nem tény: transport-relatív pozíció, és (0,0,0) pozíció.
- **SMSG_QUEST_GIVER_STATUS / _MULTIPLE → `QUEST_GIVER_STATUS`**:
  - Mezők: GUID és uint64 TrinityCore `QuestGiverStatus`, csoportosítva:
    `quest_available` („!”), `reward_ready` („?”), `trivial_available`, `future_quest`.
  - A payloadnak bájtra pontosan el kell fogynia.
  - A dumpban Captain Garrick (245394) `JourneyQuest` értéket kapott. Ez olyan
    adat, amit sem az addon API, sem a TDB nem ad meg.
- **Kizárva:**
  - Player és Pet GUID: más játékos pozíciója személyes adat, a pet gazdája
    ismeretlen. Ezek már a dekóderben elesnek, a JSONL-be sem kerülnek.
  - Az `SMSG_MOVE_UPDATE` a dumpban 720/720 esetben Player mover volt, ezért
    nincs dekódolva.

A WorldModel `state["packet_entities"]` mezője az addon UnitGUID szövegével kulcsol
(pl. `Creature-0-1465-2175-71046-245394-000053399A`). Ezt az átalakítást ugyanazon
menet addonja és dumpja egyezően igazolta.

- **Tartalom:** `kind`, `entry_id`, `map_id`, továbbá `position` (unitnál ≤ 300 s,
  `age` mezővel) és `quest_giver` (≤ 900 s).
- **Szűrés:** csak az aktuális world map (instance_id) GUID-jai kerülnek be.
- **Ürítés:** session-, karakter- vagy world map-váltáskor és `MAP_CHANGED`-kor.
  UI map-váltáskor (barlang) megmarad.
- **Inbox:** entitásonként csak a legfrissebb pozíciót tartja meg.
- **Hatás:** ezek tények, nem derived agent eventek, és nem adnak inputjogot.

A név és a quest-szerep entry_id alapján a TDB-ből jön; a szerver nem küld nevet,
ha a kliens cache-ében már megvan.

### SMSG_UPDATE_OBJECT és teljes ON_MONSTER_MOVE (2026-10-19, WPP-forrás alapján)

A mezősorrend a rögzített WowPacketParser commitból (`1a72288…`) származik:
V12_0_0_65390 `UpdateHandler`, `MovementHandler`, `UpdateFieldsHandler1215`.
A forrás a projekten kívül van: `..\_external\wpp-src\`. GPL-licences, ezért csak
specifikációként olvassuk, kód nincs átmásolva, és nem fut. A helyi
`V12_1_5_70340/Opcodes.cs` hash-e egyezik a rögzített `dcb59d20…` értékkel.
Saját olvasónk: `src/wowbot/packetio/update_object.py`, benne a WPP-vel azonos
bitolvasó (MSB-first, a bájtos olvasás nem nullázza).

**Dump-eredmény** (13:23):
- Mind a 389 UPDATE_OBJECT és 531 ON_MONSTER_MOVE rekord bájtra pontosan elfogy;
  ami nem így végződik, abból egyetlen tény sem lesz.
- 0 entry-eltérés a GUID és az ObjectData EntryID között.
- Az NPC-flagek a TDB-vel egyeznek (Bjorn, Alaria, Austin). Garrickra a szerver
  QuestGiver flaget küld, a TDB-ben nincs.
- A spline első pontja 166/175 lezárt mozgásnál pontosan a következő mozgás
  kezdőpontja.
- A teljes dump dekódolása 0,2 s, a leglassabb rekord 1 ms.

**Új események:**
- `ENTITY_CREATED`:
  - Mezők: GUID, entry, `object_kind` (UNIT/GAMEOBJECT), world map, pozíció és
    facing (`MOVEMENT` vagy `STATIONARY`).
  - Flagek: nyers `dynamic_flags`; unitnál `npc_flags` (64 bit); game objectnél
    `go_flags`, `go_state`, `go_type` és `quest_objective_id`. Az utóbbi a
    StateWorldEffectsQuestObjectiveID mező; Veil Blossom → 395312, quest 59002.
- `ENTITY_REMOVED`: `DESTROYED` vagy `OUT_OF_RANGE`.
- `ENTITY_FLAGS`:
  - A values update ObjectData-részéből jövő nyers `dynamic_flags`.
  - Csak akkor olvassuk, ha az adott GUID create-blokkját már láttuk; a
    fragmentlistája nélkül a bitmaszk nem olvasható.
  - Fragmentváltozást tartalmazó frissítést nem olvasunk.
- `ENTITY_POSITION`: a spline start mellé `move_time_ms` és — csak egypontos
  spline-nál — `destination_*`. A WorldModel ebből lineáris `estimate`-et számol
  (`progress`, `arrived`).

**WorldModel `packet_entities`:**
- Új mezők: `info`, `dynamic_flags`, `removed` (60 s-ig látszik) és `distance`.
- A projekció legfeljebb 96 elemű. Elöl a szerver szerinti „!”/„?” quest giverek
  állnak, utánuk távolság szerint a többiek.
- Egy álló game object create-pozíciója az eltávolításáig érvényes, egy unit
  pozíciója legfeljebb 300 s-ig.

**Szándékosan kihagyva:**
- Player-, ActivePlayer-, pet-, item- és corpse-objektumok: ezek dekódolás után
  elesnek, a JSONL-be sem kerülnek.
- Health, power és cooldown: az addon számára ezek secret értékek, a packetből
  kiolvasásuk az AGENTS.md szerint bypass lenne.

**Nem validált:**
- A `dynamic_flags` bitjeinek jelentése (lootolható, game object „neked
  aktív”). A dumpban a quest-GO-k (Veil Blossom, Campfire) 0x8200, az ajtó
  0x8000 értéket kapott, de a 59002-es quest nem volt aktív. Bitjelentést csak
  egy aktív questes vagy lootolós dump után adunk.
- A planner még nem használja ezeket a tényeket; élőben semmi nincs validálva.

Current/max HP, power, célpontállapot, általános spell/damage/heal/LOS, quest
dialog/accept/reward/credit és a loot lifecycle **még hiányzik**. Nincs kitalált
mask. Haláljelzés önmagában nem ad saját corpse/loot eligibilityt.

## Bekapcsolás — a GUI-indítókban engedélyezve

A felhasználó későbbi kérésére a `START_AGENT.bat`, `START_AGENT_DXGI.bat` és
`START_AGENT_LIVE_VISION.bat` most explicit `AIPC_PACKET_TELEMETRY=1` értéket
állít be a helyi konfiguráció betöltése után. Csak a kiválasztott PID
csatlakoztatásakor indul a passzív fogadó. Nem indul sidecar, capture vagy
FULL_AI automatikusan; az `AUTO_START.bat` működését nem változtattuk meg.
A runtime-könyvtár saját alapértéke továbbra is kikapcsolt, más belépési pontnál
az alábbi kapcsoló szükséges. A három frissített BAT-hoz nem kell kézi PowerShell-beállítás.

Az aktív `projekt` könyvtárban, a GUI indításához használt környezetben:

```powershell
$env:AIPC_PACKET_TELEMETRY = '1'
# Ezután innen indítsd újra a szokásos GUI launchert.
```

A kiválasztott PID runtime-ja legkorábban friss, támogatott addonkontextus után
írja az `output/agent/pid-<PID>/packet_endpoint.json` fájlt. A pontos path a
`packet_telemetry.endpoint` diagnosztikában látható. Az alap UDP-port 47651,
`AIPC_PACKET_PORT` felülírhatja; foglalt port nem buktatja el a GUI-t.
Kikapcsolás más belépési pontnál: env flag `0`, majd GUI-újraindítás; a három
GUI-BAT explicit értékét is `0`-ra kell állítani, ha azokkal indul.

A descriptor helyi IPC-kulcsot tartalmaz: ne publikáld. Ez nem WoW-authkulcs;
az aláírás véletlen/korábbi/másik küldőt választ el, nem véd egy olyan helyi
folyamattól, amely a felhasználó fájljait is olvashatja.

### GUI: fogadó és tényleges adat külön jelzés

A felső `Detektor:` sor folytatásában látszik a `Packet:` és az `adat:` állapot.

- `kikapcsolva`, `indításra vár`, `addonkontextusra vár`, `nem támogatott build`,
  `fogadóhiba` vagy `leállítva`: nincs aktív, használatra kész vétel.
- `aktív | adat: nincs (0)`: a fogadó kész, de még nincs elfogadott bejövő esemény.
- `aktív | adat: érkezik (N)`: legfeljebb 2 másodperce érkezett elfogadott esemény.
- `aktív | adat: szünetel (N)`: volt vétel, de a legutóbbi több mint 2 másodperces.

A jelzés a GUI órájával is öregszik, tehát egy befagyott régi runtime-snapshot
nem marad örökké „érkezik”. Kontextusváltáskor a legutolsó vétel ideje törlődik;
az összesítő számláló önmagában nem igazol új kontextushoz érkezett adatot.
Az `N` elfogadott bejövő események száma, **nem** a szemantikailag megértett
játékesemények vagy teljesített questek száma. Új GUI-t kell indítani a friss kódhoz.
Nem támogatott buildnél az `observed_game_build` a ténylegesen jelentett buildet
mutatja, nem egy kitalált helyettesítőt.

A sidecar már megvan: `tools/run_packet_sidecar.py` → `packetio/sidecar.py`.
A GUI-BAT a fogadót engedélyezi, nem választ adatforrást és nem indítja a küldőt.
A sidecar indításához egy explicit meglévő PKT-fájl vagy Npcap-interfész szükséges;
a nyers titkosított hálózati adat önmagában nem ad quest/HP/loot tényeket.

### Már rendelkezésre álló PKT

Az alábbi PID és útvonal csak példa, az aktuális kiválasztottra kell cserélni:

```powershell
python tools/run_packet_sidecar.py --pid 12345 --pkt-owner-pid 12345 `
  --pkt-file C:\captures\current-session.pkt `
  --endpoint output\agent\pid-12345\packet_endpoint.json `
  --diagnostics output\packet-capture\status.json
```

PKT 3.1 önmagában nem tartalmaz bizonyítható PID-tulajdonost. Az
`--pkt-owner-pid` a felhasználó explicit eredetellenőrzése, nem automatikus
bizonyítás. Rossz/régi fájl nem címkézhető vakon aktuális saját kliensnek.
Offline vizsgálathoz nincs live forward:

```powershell
python tools/run_packet_sidecar.py --pid 12345 --pkt-file C:\captures\sample.pkt `
  --record-only --record output\packet-capture\offline-events.jsonl
```

### Npcap

Ehhez külön Npcap és az opcionális `requirements-packet.txt` (`psutil`) kell.
Semmit nem telepítettünk automatikusan. A nyers Retail TCP titkosított/opaque
lehet; ez az út nem ígér visszafejtett quest/HP/loot adatot.

```powershell
python tools/run_packet_sidecar.py --list-interfaces
python tools/run_packet_sidecar.py --pid 12345 --interface '<ellenőrzött Npcap eszköz>' `
  --endpoint output\agent\pid-12345\packet_endpoint.json --decoder opaque --allow-unknown
```

A sandbox-JSONL decoder csak teszt/mirror backend; önmagában nem válik hiteles
Retail szemantikai forrássá. Ismeretlen eseményt alapból nem továbbítunk.

## Teszt és következő elfogadási lépés

Az új packet-tesztek a parser/inbox mellett a tényleges WorldModelt és
AgentRuntime-ot is ellenőrzik RecordingExecutorral. A localhost UDP-körteszt
valódi tesztsocketeket használ; a sandbox hálózati szűrése ezt blokkolja,
ezért külön, engedélyezett tesztkörnyezetben futott. A pontos végső eredmények
a `LIVE_VALIDATION.md` megfelelő bejegyzésében szerepelnek.

Élő elfogadás még szükséges: valódi bemenet eredete/PID-je, build- és forrásidő,
NPC/quest események egyezése, Z/facing pontosság, reconnect, karakter/map/phase
váltás, nincs régi adat, nincs hamis lootjog, késleltetés és hosszú futás.
A felhasználó vezeti a live tesztet. Az asszisztens nem indított capture-t,
sniffer-producert, FULL_AI-t és nem küldött játékinputot.
