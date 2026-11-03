# REV4 P7 — Charge átmenet és szerverpozíciós combat-közelítés

2026-10-30. A felhasználó 17:04–17:12 közötti, PID 7784-es próbájának
olvasási auditja. A mentett képsor a 180-as limiten 17:07:50-kor véget ért;
a tartós AGENT_TRACE/addon observationök ezért is kellettek a folytatáshoz.
A memory-adatbázis `mode=ro` és `query_only=ON` módban lett lekérdezve;
nem konstruáltunk AgentMemory writert és nem módosítottuk az éles adatokat.

## Élőben látható javulás, pontos határral

Ebben a felhasználó által indított folyamatban már ismét elérhető a map 0
natív Detour mesh, `route_found`, 844 tile. A provider PACKET_BASELINE / READY
és CONTIGUOUS állapotban volt, egy rögzített sequence gap után is helyreállt.
Ez a [MMAP/session javítás](P2_LIVE_SESSION_NAVMESH_FIXES.md) konkrét élő
adatút-bizonyítéka, nem teljes REV4-elfogadás vagy végig autonóm quest igazolása.

A 58 mentett verifikáció között 9 `target_death_verified`, 8 `loot_verified`,
5 `quest_dialog_verified`, ugyanakkor 11 `facing_failed`, 2 `out_of_range`,
2 `route_endpoint_outside_arrival_envelope` és 2 sikertelen quest-dialog
szerepel. A manuális beavatkozások teljes határa nem ismert, ezért ezek
eredményjelzések, nem automatikusan 9 autonóm kill vagy teljesített quest.

## Pontosan reprodukált combat-hiba

A felhasználó jelezte, hogy közelről nem használható a Charge. A mért eset
ennél pontosabb: az addon sikeres 100-as spellt jelzett 1346193.111-kor,
miközben a karakter még a cél felé mozgott. A COMBAT 1346193.351-nél,
az indulása után 0.14 s-cel már `out_of_range` hibával lezárult. A következő
0.2 s-on belül a FAST már Slam/Shield Slam `in_range=true` értéket adott.
A Charge `in_range=false` ilyenkor helyes; nem általános harcképtelenség.

Az új, tiszta `combat.mobility.settling_deadline` kizárólag megfigyelt saját
movement-spell sikerénél enged rövid átmenetet. A meglévő Charge metaadat
0.8 s-os maximumot ad, az **eredeti cast idejétől**. Újabb frame nem
hosszabbítja meg. Ezalatt nincs új Charge, vak előrelépés vagy sikervisszajelzés.
Amint egy tényleges nem-movement támadás hatótávja jó, a közös rotáció
azonnal folytatódik. Lejárt/hiányzó/jövőbeli siker, másik vagy halott target,
ismeretlen spell/metaadat nem generál ilyen várakozást.

A második konkrét hiba: `_world_approach_request` csak a selected target
`world_position` mezőjét nézte. A friss Retail megfigyelésben ez `false`,
miközben az exact GUID-hoz a szerver-entitáslista adta a pozíciót. Így a
combat nem is kérte a már működő NavigationService-et, hanem range failure
lett. Most ugyanazt az exact-GUID / azonos instance / nem eltávolított /
élő actor pozíciós helperét használja, amelyet a canonical `move_to_entity`
már fogyaszt. Nincs NPC-ID-alapú csere, képi koordinátagyártás vagy második
mozgás-owner. Az addon selected identity/freshness és a navmesh kapuja megmarad.

Közeli, melee `in_range=true` targetnél a rotáció Charge nélkül is támad;
a meglévő erőforrás- és autoattack fallback megmaradt. Nem állítunk teljes
új melee/ranged profilrendszert vagy minden minimum-range spell kezelését.

## Ellenőrzés és még nyitott hibák

A célzott kör **101 pass**. Pontos korrelált Charge/FAST átmenet, eredeti
cast-óra szerinti lejárat, azonnali melee-folytatás, szerverpozíciós shared
közelítés, rossz GUID/map/eltávolítás és hiányzó adatok negatív ágai szerepelnek.

Végső kijelölt regresszió: **3999 passed, 2 skipped, 10 változatlan
deselection, 323 modul, exit 0**, pytest 229.76 s / runner 232.62 s.
A teljes teszttárra vagy élő játékmenetre ez nem teljeskörű állítás.

[Forrás/diff/parancs/JUnit/bounded trace checkpoint](combat-range-handoff-evidence/verification.json).
A rövid capture-probe és SQLite-kivonat nem visz át nyers packetet, chatet,
auth-/kulcsanyagot vagy a teljes éles adatbázist a checkpointba.

A 11 ráfordulási hiba gyökérokának vizsgálata még tart; azokat ez a javítás
nem nyilvánítja megoldottnak. A vizsgált egyedi cél a szerver raw és 96 elemre
korlátozott projectionben is szerepelt; önmagában a projection-limit nem
bizonyított ok. Route/face diagnostics és mozgó célhoz tartozó final-arrival
következetesség további ellenőrzést igényel. A két dialog failure oka sincs
ettől igazolva.

Az asszisztens nem indított WoW/Ymir/capture/FULL_AI-t, nem küldött inputot.
A mobility/range javítás után nincs új felhasználói live validation. A Ymir
EXE, az addon és az input-authority kapui nem változtak. Retained collection,
provider parity és a nagy Combat/Travel/Quest felelősségbontás továbbra nyitott.
