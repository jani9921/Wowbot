# REV4 P8 — 2026-10-31 02:09-es élő teszt: Fargodeep Mine

2026-10-31, Claude. Az élő tesztet a felhasználó futtatta; a javítás
**csak offline tesztelt**, élőben nincs igazolva.

## Tünet

A bánya bejáratánál az agent „váltogatott move-al” megállt, utána „csak
állt”. A REST közben élőben működött: 02:10:55-kor indult, 02:11:35-kor
sikeresen véget ért.

## Gyökérokok

A kliens UI-térképe 37 (Elwynn) és 39 (Fargodeep Mine) között ugrált, néhány
másodpercenként. A karakter közben a 0-s világ egy pontján állt
(x −9826, y 198). Ott két navmesh-réteg van egymás felett, kb. 40 yard
különbséggel.

1. **Kontextus-invalidáció.**
   - A `StateInvalidationPolicy` minden `map_id`-váltást `MAP_CONTEXT`-nek
     vett.
   - Ez megszakította a MOVE-ot (`state_invalidated:map_context`), és
     resetelte a navigációt.
   - A reset a ZResolvert is lecserélte, így a követett saját szint elveszett.
2. **Packet-transport.**
   - A `RuntimePacketSource` aláírása tartalmazta a UI-térképet, ezért minden
     ugrás új transport-nonce-ot adott.
   - Az Ymir felől még a régi kontextussal érkező események `wrong_context`
     címen kiestek, a saját `MOVEMENT_UPDATE` is.
   - 160 s alatt egyetlen saját magasság sem érkezett.
   - A reducer logikai kapui ráadásul a UI-térképet is egyeztették.
3. **Próba-cooldown.**
   - Egy megválaszolatlan mérő fordulás után 30 s-ig minden MOVE 3 s-ot várt
     fordulás nélkül, majd `server_position_probe_timeout`-tal bukott.
   - Ez lett a hurok, közben a quest-felderítés és a leadási POI váltogatott.

A P1-B szerződés ezt már így mondta ki: a UI-térkép nem világ-, session- vagy
phase-azonosság, és a puszta UI-térkép-váltás megtartja az entitásokat. A
transport-nonce és négy kapu ettől eltért.

## Javítás

- **`runtime/state_invalidation.py`**
  - Új esemény az ugyanazon ismert világon belüli, ugrás nélküli
    UI-térkép-váltásra: `UI_MAP`.
  - Nem szakít meg és nem resetel navigációt, commitmentet vagy kamerát.
  - Csak a UI-térképből származó nézeteket (térképkeresés, vizuális
    projekciók) frissíti.
  - Világváltás, 50 yd feletti ugrás, ismeretlen világ vagy loading továbbra
    is `MAP_CONTEXT`.
- **`agent/runtime_packet_source.py`**
  - Csak UI-térképben eltérő aláírásnál a transport megtartja a nonce-ot.
  - Minden más változás (session, karakter, build, világ, phase, PID,
    loading/bootstrap) ugyanúgy új kontextust ad.
- **`agent/world_packet_reducer.py`, `agent/runtime_packet_progress.py`**
  - A logikai kapuk UI-térkép nélkül egyeztetnek.
  - Változatlan: a pontos transport-egyezés (`ipc_context == context`), a
    PID, a session, a karakter, a build, a világ, a phase, a capture-epoch és
    a 2 s-os frissesség.
  - A repülési visszajelzés és a packet-navigáció projekciója entity-scope
    szerint marad érvényes.
- **`agent/movement_controller.py` + `navigation/service.py`**
  - Egy lejárt pozícióvárás után a következő MOVE újra fordulhat egyet.
  - Ez 30 s-onként legfeljebb háromszor engedélyezett (`HEIGHT_PROBE_RETRIES`).
  - A trace `probe_released` mezőben mutatja.

## Tesztek

- **`tests/test_ui_map_step_20261031.py` (4).**
  - Azonos világban, egy ponton a 37↔39 váltás `UI_MAP`, csak a
    térképkeresés resetel.
  - Világváltás, ugrás, ismeretlen világ és loading esetén `MAP_CONTEXT`.
  - A próba-újrafordulás korlátos: 1, 1, 1, 1, majd 0 fordulás; az ablak
    után újra fordul.
- **`tests/test_packet_agent_bridge.py`.**
  - A UI-térkép-váltás megtartja a nonce-ot és a sorban álló saját
    mozgáspacketet: z 31.75, `PACKET_CLIENT_MOVEMENT`.
  - A régi paraméterlistában a `map_id`-esetet tudatosan egy
    `instance_id`-váltás váltotta: az továbbra is eldob.
- **`tests/test_skyriding_live_feedback_20261025.py`.**
  - A UI-térkép-váltás megtartja a repülési visszajelzést.
  - A régi `map_id`-eset helyére egy phase-váltás került: az továbbra is
    eldob.

Két régi teszt szándékosan változott: az a régi szerződést rögzítette, hogy
a UI-térkép-váltás kontextusváltás. Új kizárás nincs.

## Nyitott

- **Élő igazolás nincs.** A következő élő teszt a Fargodeep Mine bejárata
  legyen. A logban ezt kell ellenőrizni:
  - `STATE_INVALIDATED event=UI_MAP` jelenik meg, `MAP_CONTEXT` nem;
  - folyamatosan jönnek saját `MOVEMENT_UPDATE`-ek;
  - a MOVE nem szakad meg.
- A 10-28-as leadási hiba (fenti NPC, lent pörgő agent) továbbra is nyitott,
  lásd `P8_LIVE_1028_FOLLOWUP.md`.

## Élő eredmény 2026-10-31 08:00–08:04 és második javításkör

Az élő tesztet a felhasználó futtatta, én csak a logot olvastam. A
Fargodeep Mine quest élőben végigment (QUEST_COMPLETED +77 s). A 37↔39
váltások `UI_MAP` eseményként futottak, MOVE-megszakítás nélkül.

Három új hiba, mindhárom **csak offline javítva**:

1. **Várakozás a bányában.**
   - A karakter a 39-es mikro-térképen állt, a quest POI-k és a TDB-helyek a
     37-es zónatérképen vannak.
   - Minden világkoordinátás szűrő pontos UI-térkép-egyezést várt
     (`reference_knowledge`, `tdb_locations`, `quest_search_hints`,
     `quest_location_planning`, `objective_locator`).
   - Most az `agent/ui_zones.py` a DB2 UiMap szülőlánca alapján egy zónának
     veszi a mikro- és dungeon-térképet a zónájával.
   - A normalizált (0–1) térképkoordináták szigorú ellenőrzése nem változott.
2. **Leadás TDB-ből.**
   - A szerver elküldte a 62-es quest leadási POI-ját (+5.05 s,
     −9466, 74, 56), de a login betöltőképernyője alatt.
   - A reducer `loading` közben minden tárolt POI-t törölt.
   - Most a loading csak elrejti őket; hatókörváltás továbbra is töröl.
3. **Goldshire–Westfall váltogatás.**
   - Két kész quest (62 Goldshire, 26378 Westfall) azonos 110-es
     prioritással és azonos, 20-nál plafonozott távolságbüntetéssel billegett.
   - Felhasználói szabály: mindig az azonos térképen lévőt adja le először;
     ne menjen át, hogy aztán visszajöjjön.
   - Most az `agent/turnin_order.py` sorrendje: azonos zóna, ismeretlen,
     más zóna, mindegyiken belül a közelebbi.
   - A leadás zónáját csak a szerveres POI, a kliens-API pin vagy a közeli
     szerveres NPC adja. A TDB-régió `map_id`-je csak az aktuális térkép
     másolata, ezért nem bizonyíték.

Tesztek:

- `test_ui_map_zone_20261031.py` (2);
- `test_turnin_zone_order_20261031.py` (4);
- `test_server_quest_poi_20261028.py`: új eset, a betöltőképernyő alatti POI
  túléli a loadingot.
