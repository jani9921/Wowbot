# REV4 — a mai élő próbákból azonosított két regresszió

2026-10-30, Europe/Budapest. A felhasználó üzemeltette a klienst és az élő
próbákat. Az asszisztens csak olvasott, offline javított és tesztelt; nem
indított klienst, capture-t vagy FULL_AI-t, nem küldött inputot.

## 1. A szabályos MMAP-kapacitás téves elutasítása

A 08:46 és 10:35 körüli mentett statusban a 0-s világ navmesh-e még elérhető
volt, natív Detour útvonalakkal. A 15:54-es és 16:39-es status már
`map_parameters_invalid` hibát mutatott. Ezért a quest-NPC-hez, lootolható
holttesthez és questzónába indított MOVE az útvonal elkészítése előtt elbukott.
A záró WAIT/pixelstrip/foreground állapot egy része a felhasználói leállítás
következménye is lehet; önmagában nem mind külön plannerhiba.

Az új `mmap_format.map_parameters` túl szigorú pozitív kapacitásellenőrzése
volt a regresszió. A tényleges `mmaps.zip` 0000, 2175 és 2444 fejlécében a
signed `maxPolys` érték `-2147483648`. A generátor ugyanitt `1 << DT_POLY_BITS`
értéket tárol; a vizsgált Trinity forrásban `DT_POLY_BITS=31`. Ez kapacitás-
metaadat, nem ennyi poligon lefoglalása. A meglévő DT_POLYREF64 Detour init
ezt nem használja dinamikus referenceszélesség vagy tömbméret számítására.

A közös Python/natív olvasó most ezt az **egyetlen, pontosan azonosított**
kapacitásértéket is elfogadja, és változatlanul adja tovább. Más negatív/0/
túl nagy ismeretlen érték nem válik elfogadottá. Magic/verzió/hossz/NaN/tile-
szekció/CRC ellenőrzések megmaradnak; a hibát nem közvetlen egyenes MOVE-dal
vagy minden formátumhiba elnyelésével kerüljük meg.

Elsődleges forrás, ugyanaz a rögzített Trinity commit:

- [MapBuilder.cpp](https://github.com/TrinityCore/TrinityCore/blob/f439120b1f8c4f5a5c3fc0deb6aa01bf971e4fdf/src/tools/mmaps_generator/MapBuilder.cpp): `buildNavMesh`, kapacitás számítása és fájlba írása.
- [Trinity DetourNavMesh.h](https://github.com/TrinityCore/TrinityCore/blob/f439120b1f8c4f5a5c3fc0deb6aa01bf971e4fdf/dep/recastnavigation/Detour/Include/DetourNavMesh.h): a 31 bites kapacitás és signed paramétermező.
- A projekt meglévő `native/recastnavigation/Detour/Source/DetourNavMesh.cpp`
  `DT_POLYREF64` init ága; a DLL és az ABI nem módosult.

A checkpoint megőrzi a primary fájlok hashét és a három 40-byte fejlécet.
Nem másolja a teljes felhasználói navmesh-archívumot vagy játékadatot.

Mentett koordinátákon, valódi ZIP-pel és natív DLL-lel, inputmentesen:

- A 15:54-es, 0-s világon a holttesthez vezető út **READY / route_found**:
  844 tile betöltve, 3 poligon, 4 anchor. Ez offline útvonal, nem új élő loot.
- A 2444-es világ geometriája már betölthető: 547 tile. A mentett, ismeretlen
  Z-jű indulópont nem esett a földi mesh-re, ezért `NO_ROUTE /
  endpoint_not_on_mesh` maradt. Ez külön légimozgási/indulási probléma;
  ennek vagy a korábbi `flight_plan_no_landing_spot` megoldását nem állítjuk.

## 2. Realm és instance kapcsolat téves azonosítása

A 16:37-es JSONL-ben a `CMSG_PLAYER_LOGIN` connection 0-n, a
`SMSG_LOGIN_VERIFY_WORLD` connection 1-en jött. A korábbi dekóder kizárólag
azonos connection indexet fogadott. Így nem keletkezett natív session-baseline.
Az addon-migrációs identitás működött, de egy későbbi `queued_sample_expired`
kézbesítési rés után a provider GAP állapotát semmi nem állította helyre.
A 16:39-es status 10 ilyen veszteséget és hiányzó capture epochot mutatott.

A 16:57-es capture publikus saját create-prefixének vizsgálata igazolta:
connection 1-en `ActivePlayer` (7), `ThisIsYou=true`, a pending login pontos
GUID-ja és a verify-world mapja együtt jelen van. Nem olvastunk autentikációs
csomagot/kulcsot, és ehhez a probe-hoz saját private mezőt sem kértünk.

Az új `SessionHandshake` egyetlen pending login szűk, 60 másodperces korrelációs
ablakát és legfeljebb négy world-verification jelöltet tart. Azonos kapcsolaton
a meglévő exact login/verify út megmarad. Másik kapcsolaton csak a teljesen
beolvasott UPDATE_OBJECT explicit saját ActivePlayer create-je bizonyít:
pontos GUID, `ThisIsYou`, map, kapcsolat, rekord- és időbeli sorrend együtt.
Nem elegendő az egyetlen talált login, a legközelebbi GUID vagy a connection 1.
Hiányzó/rossz/dupla saját jelölés, lejárt vagy fordított sorrend nem baseline.

A V2 layout (`WPP_12_1_SESSION_REVIEWED_V2`) csak a vizsgált 70340 opcode-
család UPDATE_OBJECT útjának allowlistjén használható. A közös
SessionContextProvider, RuntimePacketSource és WorldModel kapui maradnak az
authorityk; a handshake nem indít skillt/inputot. A publikus bizonyítás előtt
nem olvasunk másik játékos private profile/quest/inventory prefixet.

Egy új belépési kísérlet ugyanabban a PKT-fájlban is új capture epochot nyit,
eldobja a régi own kapcsolatot, ownership-/fragment-cache-t és pending
korrelációt. A bridge az epochváltást is figyeli és törli a replay/progress
cache-t, nem csak új fájlfejlécnél. A progress első rekordja ilyenkor nem
szükségképpen 0; ettől nem gyártunk hamis rekordkiesést. Dupla verify egy már
elfogyasztott loginból nem hoz létre új sessiont.

## 3. Tényleges bizonyíték és hátralévő kapuk

A 17:04:33-as felhasználói capture új dekóderrel végzett offline visszaolvasása:
9308-as rekord, world connection 1, map 0; V2 baseline `verified_semantics=true`,
a valódi provider elfogadta és READY lett. Saját inventory-root, questlog,
profile, unit és 11 item update is dekódolódott. A visszaolvasás végén külső
UPDATE_OBJECT decode-hiba és csonka record nem volt. Az ismeretlen saját
prefixek továbbra is explicit quest/inventory invalidationt adnak; ettől nem
lett teljes native collection parity. Nyers recordot nem exportáltunk.

A geometriai célzott kör **69 pass**, a session/progress/identity/native
collection célzott kör **134 pass**. Ezek részben átfednek a széles körrel.

A végső kijelölt regresszió **3984 passed, 2 skipped, 10 változatlan
deselection, 322 modul, exit 0**, pytest 296.70 s / runner 301.02 s.
Mind az 552 source és 631 test Python-fájl AST-je érvényes; a teljes 630
testmodulból a kijelölt 322 futott. A számozott 203 coverage-sor megmaradt.

[Forrás/diff/parancs/JUnit/fejléc/capture-probe checkpoint](live-session-navmesh-evidence/verification.json).
A korábbi három checkpoint összes artifact- és forrás-ZIP-hashe is ellenőrizve.

Nem történt éles javítás utáni FULL_AI validáció. Az új Python-forrás egy
korábban elindított GUI/bridge folyamatba nem töltődik be automatikusan. Az
új élő próba előtt a felhasználónak újra kell indítania a GUI/bridge-et; ezt
az asszisztens nem tette meg. A Ymir EXE és az addon változatlan.

Retained mező-lifecycle/lease, warm collection baseline, hiányzó native
prefixek, consumer parity és a teljes Combat/Travel/Quest felelősségbontás
továbbra is nyitott. A valódi MMAP-hiba javítása és a felismert saját session
nem jelenti a teljes REV4 vagy bármely quest élő elfogadását.
