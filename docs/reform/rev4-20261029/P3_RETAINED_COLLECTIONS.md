# REV4 P3 — megtartott natív kollekciók: progresszel igazolt mezőbérlet

2026-10-31, Claude. Offline tesztelt. Ez a [P2 alkalmazási
watermark](P2_APPLIED_PACKET_PROGRESS.md) által „következő megvalósítási kapunak”
nevezett, mezőnkénti lifecycle/lease szabály. A warm bootstrap és a teljes
consumer-paritás **nem** része.

## A hiba

A szerver a saját questlog-/inventory-mezőket (VALUES) csak változáskor küldi.
A natív nézetek viszont minden mezőórát 2 mp-es TTL-lel mértek
(`packet_quest_log.MAX_AGE`, `packet_inventory.MAX_AGE`). Ennek a
következményei:

- egy hibátlan CREATE-baseline (175 questslot, a teljes root-lista, a
  tárgyak) 2 mp múlva UNKNOWN lett, pedig semmi nem változott;
- a „teljes, friss” tagság, ami az ABSENT bizonyítékhoz kell, gyakorlatilag
  csak a baseline utáni 2 mp-ben létezett.

A TTL emelése tilos és hibás is volna: egy kihagyott delta után régi értéket
tartana életben.

## A szabály

`runtime_packet_progress.retained(model, observed_at, now)`. Egy
`observed_at`-kor mintázott natív kollekció-mezőóra `now`-kor akkor aktuális,
ha:

1. 2 mp-en belüli (a régi field clock); **vagy**
2. van friss APPLIED tanú (`now − witness.sample_time ≤ 2 s`), azonos
   continuity tokennel, és az igazolt alkalmazási lánc a tény előtt vagy
   annál kezdődött: `applied_since ≤ observed_at ≤ witness.sample_time`.

Az `applied_since` az a pont, ahonnan minden kézbesített saját
collection-esemény ténylegesen átment a reduceren. A tanúnál nem korábbi
mezőt így a szerver legutóbbi értékének tekinthetjük, mert:

- egy későbbi változás felülírta volna;
- egy invalidálás korlátként törölte volna (`OWN_QUEST_LOG_INVALIDATED`,
  `OWN_INVENTORY_INVALIDATED`, mezőnként);
- egy token-, kézbesítési- vagy rekordszám-rés, illetve DECODE_GAP az összes
  régi natív mezőt eldobta volna.

| Előző tanú | Új APPLIED tanú `applied_since`-e |
|---|---|
| nincs (a continuity token első tanúja) | −∞: a token minden kézbesített eseményét lefedi, a régebbit a tokenváltás már eldobta |
| APPLIED, láncolt | az előző `applied_since` |
| DECODE_GAP, láncolt | a rés tanújának mintaideje (ott törlődtek a mezők) |
| más kontextus/küldő | az új tanú saját ideje (konzervatív) |
| UNAPPLIED | nincs bérlet; a lánc a tokenváltásig UNAPPLIED marad |

## Javítás: a DECODE_GAP élre vált

Eddig a `reason` akkor volt `decode_gap`, ha a kumulatív hibaszámláló
nem nulla. Egyetlen dekódolási hiba vagy rekordszám-rés után tehát a teljes
capture-élettartam alatt soha többé nem lehetett APPLIED tanú. Most DECODE_GAP
pontosan akkor van, amikor a számláló **nő**. Ugyanez a feltétele a mezők
eldobásának is (`discard_fields`). A következő, változatlan számlálójú tanú a
réstől kezdve újra lefed.

## Ami nem változott

- Nincs TTL-emelés. A HP-, power-, profil-, entity-, geometria-, combat- és
  UI-frissesség nem kap bérletet.
- A tanú UI-/addonfrissességet (`last_received`) és inputjogot nem ad.
- A tanú nem pótolja a hiányzó baseline-t.
- Az ABSENT-hez továbbra is COMPLETE tagság kell. Ez most bérelt, igazoltan
  aktuális tagság is lehet.
- Kihagyott vagy átsorolt delta (UNAPPLIED), DECODE_GAP, kézbesítési rés és
  lejárt tanú után a mező UNKNOWN.

## Tesztek

`tests/test_retained_native_collections_20261031.py` (6). Esetek:

- láncolt tanúkon átívelő baseline (PRESENT/ABSENT és darabszám), majd a
  tanú elöregedése;
- regresszált lánc;
- a deltát megelőző tanú;
- DECODE_GAP után nincs feltámasztás;
- a bérlet mindig a legújabb értéket tartja;
- a `retained()` határfeltételei: tanúnál újabb tény, lefedés előtti tény,
  öreg tanú, státusz, `applied_since=None`, tokenváltás.

A `test_applied_packet_progress_20261030.py` régi tesztje
(`..._does_not_extend_native_field_...`) még a bérlet előtti kaput rögzítette.
Most mindkét oldalt rögzíti (`test_only_a_fresh_applied_chain_leases_...`):

- lejárt tanúval UNKNOWN;
- friss láncolt tanúval aktuális;
- elöregedés után újra UNKNOWN;
- a `last_received` változatlan.

Nem került ki teszt, és nincs új kizárás.

## Nyitott

1. **Warm bootstrap:** ha az agent a session közben indul, nincs saját
   CREATE-baseline a következő login- vagy zónaváltásig. A PKT-fájl
   saját-állapotú újrajátszása a session elejétől nincs meg.
2. **Consumer-paritás:** a natív questlog/inventory nézetet ma csak a
   `WorldQuery` saját segédei használják (`quest_presence`,
   `owned_item_count`). Planner, verifier vagy QuestModel még nem fogyasztja.
   Az addon-adat marad az elsődleges.
   - 2026-10-31 óta a paritást egy **árnyékfigyelő** méri
     (`agent/native_parity.py`, `NativeParityMonitor`). Minden medium tickben
     összeveti a natív és az addon-nézetet, és ha az ítélet változik,
     `NATIVE_PARITY` journal-eseményt ír. Fogyasztót nem érint.
   - Questlog: csak akkor `AGREE` vagy `DIFFER`, ha mindkét oldal teljes,
     egyébként `UNKNOWN`.
   - Inventory: közös tárgynál a natív alsó korlát az addon fölött `DIFFER`.
     A csak natívan látott tárgyak (pl. felszerelés) ítélet nélkül listázva.
   - Csak quest-/item-ID és darabszám kerül a logba.
   - A paritást a következő élő teszt journalja igazolhatja; az autoritás
     átállítása csak utána jöhet.
   - Teszt: `tests/test_native_parity_20261031.py` (5, ebből egy a valódi
     packet-bridge-en át).
3. Élő igazolás: nincs. Élőben figyelendő:
   - a `packet_quest_log.membership` és a `packet_inventory.root_membership`
     COMPLETE marad-e hosszabb, változás nélküli szakaszon;
   - DECODE_GAP után újra lefed-e.
