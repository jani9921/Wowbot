# REV4 P3 — kezdeti natív saját inventory-adatút

2026-10-30. A kijelölt `projekt`; **offline tesztelt CREATE/részadatút**.
A teljes inventory-/consumer-paritás még **PARTIAL**, nem készült el az addon
inventory helyettesítése. A közös WorldModel/query és tanácsadói felület maradt
a tulajdonos/fogyasztó; nincs külön inventoryvezérlő vagy inputút.

## Beolvasott mezők

A pinnelt WPP 70340-es `UpdateFieldsHandler1215`, `ItemHandler` és
`MythicPlusHandler` mezősorrendjéből készült célzott prefixolvasó:

1. A saját PlayerData CREATE QuestLog utáni fennmaradó részének pontos,
   feltételes/tömbös bejárása, majd az ActivePlayerData **105 InvSlots** GUID-ja.
   Realm/account/player/pet/declined/assist nevek/azonosítók, leaver- és kozmetikai
   adatok nem kerülnek a normalizált eseménybe. A szövegbájtokat nem dekódoljuk.
2. Kizárólag a szerverrel korrelált saját karakter tulajdonában lévő ItemData
   CREATE: item GUID/entry ID, contained-in GUID, stack count, durability/max.
   Más tulajdonosnál a private mezők olvasója nem fut tovább.
3. Saját ContainerData CREATE: **98 slothely** és NumSlots; a tényleges kapacitáson
   kívüli nemüres GUID, duplikált/rossz fajta GUID vagy csonka lista hibás adat.

A slotazonosítók **szerveres tárolóhelyek**. Nem neveztük át őket kliensoldali
bag/slot indexszé vagy kattintási koordinátává. A rootok bankot/equipmentet is
érinthetnek; egy ismert tulajdonlásból nem következik hordott vagy használható tárgy.

## Esemény, scope, tárolás

A `WPP_12_1_OWN_INVENTORY_REVIEWED_V1` kizárólagos layout alatt új allowlist:
`OWN_INVENTORY_ROOTS`, `OWN_INVENTORY_INVALIDATED`, `OWN_ITEM_UPDATE`,
`OWN_ITEM_REMOVED`. Ez nem tetszőleges struktúra-/stringengedélyezés.
PID/build/karakter/epoch/eredeti sample-idő és IPC-kapuk maradnak. A 70340-es
explicit buildcsaládon kívül a provider nem állít inventory-tényt.

A capture-dekóder kapcsolatonként követi a már igazolt saját item GUID-okat,
új login esetén eldobja őket. Tárgyeltűnés, tulajdonosváltás vagy egy még
nem dekódolt VALUES frissítés érvényteleníti a korábbi natív itemmintát.
CREATE → VALUES ugyanazon rekordban is a wire-sorrend szerint működik.
Aktív játékos még nem ismert inventory-deltája a rootmintát érvényteleníti;
nem találgatjuk, melyik slot változhatott.

A WorldModel legfeljebb 2048 saját mintát és bounded érvénytelenítési barriert
tart. Régebbi, sorrenden kívüli CREATE nem támaszt fel frissebben érvénytelenített
darabszámot. A query megőrzi a minták saját óráját és observation ID-ját;
a hot státuszban csak darabszám/coverage van, nem teljes root-/itemtömb.

`WorldQuery.native_inventory(now)` másolatot ad, `owned_item_count(item_id,now)`
ismert stackekből származó **megfigyelt alsó korlátot**. Nincs teljes hiánybizonyíték,
a `carried` UNKNOWN, a teljes inventory-coverage PARTIAL. A kétmásodperces
sample-kapu és a folytonossági generáció megmaradt. Scope-/loading-/GAP-váltás
előző mintáit még a következő projekció előtt sem adja vissza a query.

A read-only tanácsadói eszköz a kliens inventory-adata mellett külön
`native_ownership` mezőben kap bounded alsó korlátot és eredeti bizonyítékot.
A hozzá tartozó valódi packet-evidence referenciák is olvashatók. Nem kap
új író-/inputeszközt vagy használati jogosultságot. A UI-bag sor darabszámát és
kattintható helyét ez nem írja át.

## Ellenőrzési esetek

Pontos, nemüres PlayerData dinamikus tömbök, item-modifier/bonus rekordsorok,
declined name és opcionális szövegek; Item/Container CREATE; idegen tulajdonos;
csonka payload; ismeretlen delta; azonos rekordon belüli CREATE → VALUES;
tulajdonosváltás; régi, átrendezett minta; hiányzó item UNKNOWN; UI-adat megőrzése;
read-only másolat; sample-expiry; karakter/phase/loading/GAP; tanácsadói lineage.

A célzott körök átfednek: 40 prefixpróba, 104 IPC/own-state próba, 118
inventory/LLM próba, majd 63 profil/inventory/adviser regresszió. Nem összeadandók.
Az első széles kör két régi profiltesztje eseménysorszámot használt; az új
inventory-invalidation eseményre választottak profil helyett. Az elvárt kibővült
eseménysor és a név szerinti profilkiválasztás javítva; production kapu nem lazult.

A végső eredményt és teljes parancsot a
[checkpoint](native-inventory-evidence/verification.json) rögzíti. A korábbi
hibás futás is megmarad; új exclusion nincs. A 203 számozott coverage-sor és
minden korábbi checkpoint változatlanul megmarad.

Végső kijelölt regresszió: **3857 passed, 2 skipped, 10 változatlan deselection,
314 modul, exit 0**, pytest 175.75 s / runner 178.55 s. Az összes 535 source és
623 test Python-fájl AST-je érvényes. A teljes 622 testmodul helyett a kijelölt
314 futott. A végső körben a GAP/azonos baseline utáni cache-visszaöröklés
elleni új inventory-próba is benne van.

## Nyitott megvalósítási kapuk

Item/Container/ActivePlayerData VALUES teljes értelmezése, bizonyított kliens
bag-slot kapcsolat, carried/bank/equipment különbség, elveszett események és
warm-replay/tartós natív baseline teljessége; utána a fogyasztók és az addon
inventory karcsúsítása. Ezek **kódhiányok**, nem pusztán hiányzó élő tesztek.
A mostani pozitív minták nem bizonyítanak quest-creditet, lootjogot vagy
jutalomátvételt. Saját quest-progress, P7 cast/hazard/talent/role és történeti
memória-lineage korábbi nyitott kapui sem váltak automatikusan teljesítetté.

Nem indult játék, Ymir, capture vagy FULL_AI, nem ment kliensinput. Addon
0.9.80 és a pinned Ymir byte-változatlan. Új LIVE_VALIDATED állítás nincs.
