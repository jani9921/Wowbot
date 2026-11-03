# REV4 P3 — saját item-/container-delták és mezőnkénti eredetidő

2026-10-30. A kijelölt `projekt`; **offline tesztelt, részleges VALUES adatút**.
Ez a [CREATE checkpoint](P3_NATIVE_INVENTORY.md) folytatása. Nem teljes inventory-
vagy input-paritás, és nem új élő validáció.

## Tényleges változás

A capture kapcsolaton már igazolt saját item GUID-jához a 70340-es WPP szerinti
ItemData/ContainerData VALUES mezők is olvashatók:

- StackCount, ContainedIn, Durability/MaxDurability, a ténylegesen változó
  ObjectData EntryID; Container NumSlots és változó slot-GUID-ok.
- A megelőző ismert skalármezők, charge-/enchantment-frissítések és bonus-key
  mezők pontosan átugorhatók. Root nélküli mask, hibás hossz vagy ismeretlen
  dynamic artifact/gem/modifier/fragment struktúra nem jelent tippelt offsetet.
- Új `WPP_12_1_OWN_INVENTORY_REVIEWED_V2` layout kell a VALUES mintához.
  A korábbi V1 nem állíthat ilyen deltát. Másik buildcsalád nincs engedélyezve.
- Tulajdonosváltásnál az új tulajdonos private mezői már nem kerülnek olvasásra.
  Ismeretlen itemfrissítés után a capture ownership-kapcsolata is megszűnik:
  új saját CREATE kell az ismételt private olvasáshoz. A modellben baseline
  nélküli delta nem gyárt új itemidentitást.

A szerveres tárolóindex továbbra sem kliensoldali bag/slot/kattintási hely.
ActivePlayerData InvSlots VALUES még nem teljes; az eddigi érvénytelenítési
ág megmaradt. Nincs új executor, UI-kattintás vagy binding-fallback.

## Órák, sorrend és bizonyíték

A WorldModel az item mezőinek eredeti sample-idejét és observation ID-ját külön
tartja. Egy durability- vagy táskaslot-frissítés nem fiatalítja meg a StackCountot,
egy számlálófrissítés nem fiatalítja meg a NumSlotsot vagy mind a 98 táskahelyet.
Eltérő mezők késve érkező, de az adott mezőnél újabb mintái külön alkalmazhatók.
Régi CREATE vagy törlési jel nem dobja el a nála frissebb saját mintát.

Az ItemGUID → entry kötés csak ismert lifecycle/scope-on belül marad referencia;
az eredeti identitásidejét nem írjuk át a darabszám órájára. Törlés, ismeretlen
ownership/layout vagy GAP újra érvénytelenít. A query és a read-only tanácsadói
adat külön közli az identity- és a counter-bizonyítékot/időt. A mennyiség továbbra
is csak friss, megfigyelt alsó korlát, nem teljes hiánybizonyíték.

A friss táskaslotok coverage-je külön COMPLETE/PARTIAL/UNKNOWN. Átmeneti duplikált
item-GUID vagy kapacitáson túli nemüres slot ellentmondás; abból nem lesz teljes,
használható tárolókép. Későbbi igazolt áthelyezési minta feloldhatja ezt.
Mindez read-only állapot: `carried` még UNKNOWN, inputjog nem keletkezik.

## Ellenőrzés

A célzott kezdeti kör **66 pass** (átfed a végsővel). A további duplikált-slot
és régi törlési próba is benne van a végső kijelölt regresszióban. Tesztek:
V1/V2 kapu, friss darabszám, másik mező nem fiatalít, mezőnként átrendezett
minták, részlegesen öregedő táskakép, ownership-váltás, ismeretlen/tail hiba,
új CREATE igénye és átmeneti slotellentmondás feloldása.

Forrás-ZIP, diff, parancs/JUnit/eredmény és a pinnelt primary WPP-fájlok hash-je:
[checkpoint](native-inventory-deltas-evidence/verification.json). A korábbi
checkpoint és mind a 203 számozott coverage-sor megmarad.

Végső kijelölt regresszió: **3866 passed, 2 skipped, 10 változatlan deselection,
315 modul, exit 0**, pytest 164.24 s / runner 167.08 s. Az összes 536 source és
624 test Python-fájl AST-je érvényes; a teljes 623 testmodul közül a kijelölt
315 futott. A végső kör tartalmazza a késői törlési barrier javítását is.

## Továbbra is nyitott

Aktív root-slot delták teljes feldolgozása, unsupported ItemData dynamic tömbök,
carried/bank/equipment elkülönítés és bizonyított kliens bag-slot kapcsolat;
folyamatosan igazolt natív collection baseline és warm-replay; minden inventory-
consumer és az addon karcsúsítása. A mostani részadatút nem jelenti ezek készségét.
Quest-progress, teljes P7 provider/role és történeti lineage korábbi kódhiányai
nem oldódtak meg ettől automatikusan.

Nem indult játék/capture/Ymir/FULL_AI, nem ment kliensinput. Addon és pinned
Ymir byte-változatlan, új LIVE_VALIDATED állítás nincs.
