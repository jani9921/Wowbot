# Vineyard quest-item javítás — 2026-10-28

Állapot: **részleges, offline tesztelt; a javítás utáni élő teszt még nyitott**.

## Mi változott

- A meglévő TDB-ből olvasott spell-hit/kill-credit kapcsolat és a helyi DB2
  item/spell lánc összeköti a tűzoltó készüléket a Vineyard objective-val.
- A kiegészítő SQLite tartalmazza a szükséges nyers SpellEffect, SpellRadius
  és SpellDuration adatokat. A geometria adatból jön: 15 yard, 60 fok, 5 s.
- A közös quest-tervező szerveres tűz-GUID-hoz kér navmesh útvonalat és
  odafordulást, majd önmagán aktiválja a készüléket. A tűz nem Tab/F7-cél.
- A látható táskagombot vagy az item ellenőrzött actionbar-gombját a meglévő
  UseItemSkill használja. Minden aktiválás előtt újraellenőrzi a pontos itemet,
  objective-ot, pozíciót, irányt, mozgást, cooldown-t és a gomb azonosságát.
- Az addon 0.9.78 célpont nélkül is közöl publikus item readiness-adatot;
  hiányzó range ettől még nem jogosít Interact/F7-re.
- Egyetlen aktiválást küld, kivárja a hatást és az objective számlálóját.
  A cast, cooldown, eltűnt trigger vagy más quest progressze nem siker.
- A már használt / sikertelenül próbált trigger átmeneti kihagyást kap.
  Nincs új inputgazda, külön quest brain vagy azonosítóra írt végrehajtás.

## Ellenőrzés

55 célzott offline eset sikeres (a három új tesztmodul). A rögzített 0/8-as
állapot újraprojektálásakor a közös Planner MOVE-ot választ a tűzhöz. A
szimulált megérkezés a rögzített táskagombot aktiválja egyszer; csak a pontos
26391:0 progressz eredményez sikert. A helyi mmaps/Detour adatból számolt
útvonal hat anchor, 42.486 yard; közeli, elfordított állapotban a közös
NavigationService face-on-arrival fordulást kér. Input nem lett kiküldve.

A szélesebb csomagban 141 modulból **1766 teszt sikeres, 1 sikertelen**.
A hiba a `test_packet_object_use_20261019.py` régi UDP-backlog visszajátszási
tesztje (`test_backlog_older_than_an_open_context_is_restamped_not_dropped`).
Külön ellenőrizve a javítás nélküli projektben és a stagingben is azonosan
hibázik: hiányzik a visszajátszott `packet_entities`. Ez nem a Vineyard
módosítás által bevezetett eltérés; továbbra is nyitott, nincs kihagyva vagy
sikernek feltüntetve. Az 55 új célzott teszt része a 1766 sikeres tesztnek.
A korábbi repülési/actionbar, Blackrock-forrás/harc, quest-item, addon/codec,
azonosság, mozgás és scoped quest-credit regressziók sikeresek.

## Még szükséges

A felhasználó indítja a következő élő tesztet. Friss GUI-folyamat és a
0.9.78 addon betöltése szükséges (futó WoW esetén `/reload`). Ellenőrizendő
az önálló odamenés, fordulás, itemhasználat, 8/8 és leadás. A régi futás
kézi 1/8–2/8 jóváírása nem számít a javított agent sikerének. A támogatott
periodikus self-emitter/cone családon túli mechanikák nem lettek általános
SmartAI-végrehajtóvá nyilvánítva. Részletek és korlátok: LIVE_VALIDATION.md.
