# REV4 P1-E — MMAP/Detour formátum és hibadiagnózis

Későbbi mai korrekció: [élő logból javított MMAP/session regressziók](P2_LIVE_SESSION_NAVMESH_FIXES.md). A lentebbi mérés az akkori történeti checkpoint eredménye.

2026-10-30. A kijelölt `projekt`, **OFFLINE_TESTED**. Nem új router:
a meglévő Python és natív Detour loader kapott közös statikus formátumellenőrzést.
Új élő útvonal-, recovery- vagy érkezésigazolás nincs.

## Feltárt ok és változás

A Python tile parser az egyik wrapper-verziót nem ellenőrizte, és a hibás
fejlécet/csonka tile-t üres poligonlistaként adta vissza. Ebből gyakran
`no_route_tiles` lett, tehát hibás geometriai adat és hiányzó út nem vált külön.
A natív loader is ellenőrizetlenül továbbadta a verziómezőket, a root mmap
paramétereit pedig csak részben olvasta. Egy korábbi komment a dtVersion és
mmapVersion jelentését is felcserélte.

A közös `mmap_format` olvasó a már támogatott Trinity **MMAP v16 / Detour v7**
fájlt ellenőrzi. Ez fájlformátum, nem WoW kliensbuild vagy a dataset tartalmi
revíziója. Másik verzió nincs automatikusan kompatibilisnek nyilvánítva.

- Root map: magic, verzió, minimális hossz, véges origin és pozitív/bounded
  paraméterek; korábbi 36-byte paraméterprefix és a 40-byte, offmesh-listás
  v16 fejléc méretei. Ismeretlen/csonka kiegészítés nem lesz útalap.
- Tile: wrapper magic, **külön dtVersion és mmapVersion**, adathossz, belső
  Detour magic/verzió, számlálók, véges headerértékek és szekcióméretek.
  A natív ABI előtti minimumlink/detail/offmesh-konzisztencia külön ellenőrzött.
- Python oldalon a beolvasott vertexek végesek. A natív DLL előtt a méret- és
  szekciókapu fut; ismeretlen verzióhoz nem hívunk DLL tile-betöltést.
- Csonka/rossz adatok és ZIP member CRC/read hibák ERROR, eltérő verzió
  VERSION_MISMATCH, hiányzó adat MISSING_DATA. Létező, de járási flaggel kizárt
  víz nem hiányzó adat: NO_ROUTE. Egy bizonyított teljes folyosó továbbra is READY.
- Részben betöltött, hibás tile-ok melletti sikertelen natív/Python keresés
  nem igazolja a földrajzi elérhetetlenséget. A hiba bounded diagnózisként
  megmarad a warm/cached lekérdezésben is. A sikeres teljes út feltételei,
  walking policy, arrival verifier és input-owner nem változtak.
- A WorldGeometry/GeometryResult adapter átveszi a kifejezett formátumstátuszt,
  nem alakítja NO_ROUTE-vá. Magasabb réteg így a tényleges okot kapja a recoveryhez.

## Elsődleges formátumforrás

A [TrinityCore MMapDefines.h konkrét commitja](https://raw.githubusercontent.com/TrinityCore/TrinityCore/f439120b1f8c4f5a5c3fc0deb6aa01bf971e4fdf/src/common/mmaps_common/MMapDefines.h)
rögzíti a wrapper mezősorrendet, v16 értéket és root/offmesh struktúrákat.
A [projektben vendorizált Detour](../../../native/recastnavigation/Detour/Include/DetourNavMesh.h)
és a hozzá tartozó `DetourNavMesh.cpp` adja a v7/64-bit polyref méreteket.
A primary forrás és a vendorizált fájlok SHA-256 manifestje a checkpoint része.
A loader nem frissít kódot vagy formátumot hálózatról.

## Ellenőrzés

A célzott geometriai kör 53 pass; az utána hozzáadott ZIP CRC eset is benne van
a végső széles körben. A minimális route-fixture korábban szöveget írt a map
fejléc helyére; most valódi szintetikus v16 root headerrel dolgozik.

Végső kijelölt regresszió: **3815 passed, 2 skipped, 10 változatlan deselection,
312 modul, exit 0**, pytest 135.62 s / runner 138.49 s. Az összes 532 source és
621 test Python-fájl AST-je érvényes; a teljes teszttár 620 testmodulja közül a
kijelölt 312 futott. Az új modul benne van, új kizárás nincs.

Rögzített esetek: rossz root/tile magic, eltérő wrapper vagy mesh verzió,
csonka fejléc/szekció, NaN, hibás offmesh hossz, CRC hiba, hiányzó tile,
víz/walking filter, normál route, cached diagnózis, natív DLL előtti elutasítás.

[Checkpoint, forrás-ZIP, diff és ellenőrzési manifest](mmap-format-evidence/verification.json).
A 203 számozott coverage-sor és az előző checkpointok megmaradtak.
Az addon 0.9.80 és a pinned Ymir hash változatlan. Nem indult kliens/capture/
FULL_AI, nem ment játékinput, nem történt új live validáció.

## Határok

Ez nem minden bináris fájl szemantikai épségének vagy minden geometriai adat
aktuális játékbeli helyességének bizonyítása. MAPS/VMAPS parser, teljes offmesh
útvonalvégrehajtás, horizontális LOS és ismeretlen dataset revision ettől nem
kapott új képességet. A már jelzett saját quest/progress/inventory-, combat-
provider-, történeti lineage- és élő kalibrációs kapuk továbbra is nyitottak.
