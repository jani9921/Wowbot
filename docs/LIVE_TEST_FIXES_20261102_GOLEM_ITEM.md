# It's Alive! — a gólemes quest-item kapcsolata és végrehajtása

2026-11-02. A felhasználó futtatta az élő tesztet. A javítás
**offline tesztelt; új élő siker még nincs igazolva**.

## Élő bizonyíték

`output/agent/pid-25640/live-captures/20261102-174259-474-002/manifest.jsonl`:
17:43:01–17:45:39, 180 mentett állapot. MOVE 49, COMBAT 113, TARGET 8,
WAIT 10; itemhasználati vagy táskanyitási döntés nincs köztük. A későbbi
lezárt státuszban a 26257:0 objective 0/1, a 26257:1 ölési objective 25/25.
Ez az itemes lépés kimaradását mutatja, nem az önálló teljes quest sikerét.

Az API `monster` kategóriája mindkettőt KILL-ként normalizálta. A már
meglévő 25+46 selector-javítás az item célzási módját felismerte, de az item
és a bekapcsolási objective közti kapcsolat továbbra is hiányzott.

## Gyökérok és javítás

Az olvasott helyi DB2/TDB adatok szerint a Harvest Watcher Heart (57954)
Wake Harvest Golem spellje (79436) a 42601-es járművet idézi meg. A spell
második effectjéhez tartozó implicit célfeltétel az eredeti 42381-es
Overloaded Harvest Golemre mutat. Az objective a létrejövő járművet nevezi
meg credit-ID-ként, ezért a korábbi kizárólagos kill-credit keresés nem
kapcsolta össze őket. A fizikai célpont és a credit/jármű külön marad.

- A DB2 supplement megőrzi a támogatott SUMMON + DEST_NEARBY_ENTRY effect
  entry-jét és valódi effect-indexéből számolt bitmaszkját. Nem ír jóvá creditet.
- Külön, read-only adapter fogadja el az egyetlen pozitív creature-entry
  feltételt. Több/alternatív/negatív/reference/scriptelt feltételt nem találgat.
  A [TrinityCore feltételsémája](https://trinitycore.info/database/master/world/conditions)
  szerinti SourceGroup effect-maszk; nem effect-sorszám.
- Csak az objective credit-entryjével egyező summon és a hozzá tartozó
  célfeltétel egyértelmű kapcsolata ad új item-mechanikát. Nincs beégetett
  quest-, item-, spell- vagy gólem-ID a működési kódban.
- A QuestModel az eredeti actor NPC-ID-ját kapja. Az érintett objective
  USE_ITEM_ON_TARGET lesz; a másik objective száma/típusa nem változik.
- A meglévő szerveres item-célpont megközelítés és GUID-ellenőrzött TARGET
  most a feloldott UNIT itemekre is működik, nem csak gyógyításra. Egy
  sikertelen barátságos kijelölés után az enemy-Tab csak a meglévő szerveres
  egyértelműségi kapun és utólagos pontos GUID-ellenőrzésen át próbálható.
- Azonos NPC-ID esetén a kijelölt item-célhoz nem kell név vagy képi doboz.
  Az aktiválás a meglévő igazolt actionbar- vagy látható táskagomb-úton megy.
  A kapott item-reláció nem ölési utasítás és nem automatikus F7-engedély.
- A siker továbbra is a megfelelő objective tényleges progress-változása.
  A summon-metaadat, cooldown és elküldött parancs önmagában nem siker.

## Ellenőrzés és következő élő próba

**419 passed**, 27 kapcsolódó tesztmodul, 87.93 s pytest; nincs új kizárás.
Ebben benne van 21 új regressziós eset: eredeti actor vs. új jármű,
rossz effect-maszk/feltétel, megközelítés, GUID-kijelölés, rossz kijelölés,
táskából használat és credit-verifikáció. A korábbi 207-es kör átfed,
nem adandó hozzá a 419-hez.

A tényleges helyi katalógus és a mentett questadat read-only probe-ja
USE_ITEM_ON_TARGET / NPC 42381 / item 57954 eredményt adott a 0/1-es
objective-re. Ez katalógus-/modellpróba, nem teljes élő replay vagy live-proof.

GUI/agent újraindítás után a felhasználó próbálhatja: eredeti gólemhez
megközelítés, pontos kijelölés, szív használata, majd a 0/1 → 1/1
progress és a járműállapot ellenőrzése. Addon- vagy Ymir-csere nem kell ehhez
a Python-javításhoz. Az asszisztens nem indított FULL_AI-t, nem adott
kliensinputot, nem módosított éles adatbázist és nem fejlesztett vizuális ágat.

A scoped before/after patch, parancs, JUnit, katalógus-probe és hash-ek:
`reform/rev4-20261029/golem-item-20261102-evidence/`.
