# TDB (TrinityCore világadatbázis) beállítása

Az agent a TDB-t statikus világmemóriaként használja: tudja belőle, hol állnak a quest-felvevők és -leadók,
hol vannak a quest-objektumok és a lények spawnjai, és mekkora a quest-terület (POI-poligon). Amit élőben
igazol, azt egy külön, tanult TDB-fájlba menti (`output/agent/profiles/<user>/tdb_learned.sqlite3`).

Az adatbázis **nincs a repóban**: SQLite-ként 655 MB, ami túl nagy a git-hez. Az alábbi lépésekkel bárki
elkészítheti a hivatalos TrinityCore kiadásból. TDB nélkül is fut az agent, csak a TDB-alapú
helyismeret nélkül (a játék API-ja és a látás alapján dolgozik).

## 1. Letöltés

A szerver ugyanezt a TDB-t futtatja; a koordináták ezért egyeznek a játékbeliekkel.

- Kiadás: **TDB 1210.26091** (2026-09-09), Retail 12.1 —
  <https://github.com/TrinityCore/TrinityCore/releases/tag/TDB1210.26091>
- Fájl: `TDB_full_1210.26091_2026_09_09.7z` (kb. 150 MB)

Másik TDB-verzió a koordináták és spawnok eltérése miatt hibás helyekre vezethet.

## 2. Kicsomagolás

7-Zippel csomagold ki. Ebből egy fájl kell: `TDB_full_world_1210.26091_2026_09_09.sql` (kb. 620 MB).

Ellenőrzéshez az SQL-fájl SHA256-ja:

```
608534d1dc97535c92d756914a02fe36264e484b519f6e54f6d10cf56c6f4d96
```

PowerShellben: `Get-FileHash .\TDB_full_world_1210.26091_2026_09_09.sql`

## 3. Átalakítás SQLite-tá

A konverter az SQL-t **nem futtatja**, csak az `INSERT` értékeit olvassa ki, és SQLite-ba tölti
(246 tábla, kb. 6,9 millió sor, néhány perc):

```bat
python tools\convert_tdb_mysql_to_sqlite.py "C:\Users\<user>\Downloads\TDB_full_world_1210.26091_2026_09_09.sql" "C:\Users\<user>\Downloads\TDB_full_world_1210.26091_2026_09_09.sqlite3"
```

A végén egy JSON-összegzést ír ki (`"status": "complete"`, `"integrity_check": "ok"`).

## 4. Bekötés

Hozd létre a `config/reference_catalog.local.json` fájlt (gépenkénti beállítás, nem kerül a repóba):

```json
{
  "path": "C:/Users/<user>/Downloads/TDB_full_world_1210.26091_2026_09_09.sqlite3"
}
```

Ugyanezt az `AIPC_REFERENCE_CATALOG` környezeti változó is megadhatja; az erősebb a fájlnál.

Az agent az adatbázist csak olvassa. A tanult adatok a profil saját `tdb_learned.sqlite3` fájljába kerülnek,
ugyanazzal a táblaszerkezettel. A TDB sorait soha ne töltsd vissza a szerver adatbázisába: duplikált NPC-k
jelennének meg.
