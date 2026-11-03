# REV4 P3 — saját inventory root-slot VALUES

2026-10-30. A kijelölt `projekt`; részleges, offline tesztelt adatút.
A [saját item-/container-delták](P3_NATIVE_INVENTORY_DELTAS.md) folytatása.
Nem teljes inventory-paritás és nem új élő validáció.

## Bekötés

A 70340-es WPP-család ActivePlayerData 13 szavas változásmaszkjában a 163-as
array root és a 164–268-as slotbitek alapján pontosan a változott InvSlots
GUID-ok kerülnek a közös decoder → normalizált V2 event → IPC → WorldModel/query
láncba. Csak a korrelált saját karakter és ismert CGObject fragment érvényes.
A V1 layout nem állíthat VALUES mintát. Az index nem kliensoldali bag/slot.

Az ActivePlayerData önálló, illetve ismert ObjectData utáni InvSlots-változása
olvasható. Egyéb, megelőző változó mezők együttállása továbbra is explicit
érvénytelenítés; nincs találgatott offset. Az InvSlots változását nem jelző
maszk megőrzi a korábbi root-adat eredeti idejét, nem küld új készletmintát.
Ismeretlen tail, hiányzó array root vagy nem-item GUID nem ad részleges hamis
snapshotot.

## Összevezetés és eredet

A root-slotok külön órát és observation ID-t kapnak. A CREATE 105 mezőt ad,
a VALUES csak a megváltozott helyeket frissíti. Egy slot változása nem írja
felül vagy fiatalítja meg a többi 104 helyet. Késői, eltérő slothoz tartozó
minta külön alkalmazható; régi teljes CREATE vagy érvénytelenítés nem dobja
el a frissebb deltát. Érvénytelenítés után régi snapshot/delta nem támasztja
fel a korábbi collectiont.

A query `root_baseline_time`, `root_sample_time` és mezőnkénti
`root_slot_evidence` adatot ad. Összevont snapshothoz nem rendel egyetlen új
megfigyelési időt. A teljes 105 friss, konzisztens mező COMPLETE membership;
részleges vagy öregedő adat PARTIAL/UNKNOWN. Azonos item-GUID két helyen
ellentmondás: nincs használható root-lista, amíg igazolt áthelyezés nem oldja
fel. Baseline nélküli delta csak a ténylegesen megfigyelt pozitív részadatot
adja, nem igazol hiányt, darabszámot vagy hordott helyet.

A forrás TTL-je és a GAP/karakter/map/phase kapuk megmaradtak. A hot status
csak összesítő, nem másolja minden tickben a 105 helyet. Az addon inventory
és az input/binding-authority nem változott. Nincs quest-credit/loot receipt
következtetés pusztán slotváltozásból.

## Ellenőrzés és határok

A célzott root/item/container/continuity kör **46 pass**; átfed a kijelölt
nagy regresszióval, nem összeadandó. A próbák tényleges maszk-/GUID-byteokat,
normalizálást és hitelesített teszt-IPC-t is használnak. Mozgatás, mezőórák,
reordering, invalidation barrier, hibás/truncated/tail adat, V1/V2 kapu,
duplikált GUID és baseline nélküli delta külön ellenőrizve.

A végső kijelölt regresszió **3878 passed, 2 skipped, 10 változatlan deselection,
316 modul, exit 0**, pytest 147.57 s / runner 150.47 s. Az összes 536 source
és 625 test Python-fájl AST-je érvényes. A teljes 624 testmodul közül a kijelölt
316 futott; ez nem teljes repository-tesztfuttatási állítás.

Forrás-ZIP, byte-hash, diff, pontos parancs/JUnit és primary WPP hash:
[checkpoint](native-inventory-roots-evidence/verification.json). A korábbi
checkpointok és mind a 203 számozott coverage-sor változatlanul megmaradnak.

Nyitott kódhiány marad: vegyes ActivePlayerData prefixek teljes feldolgozása,
unsupported ItemData dynamic tömbök, carried/bank/equipment és kliens bag-slot
kapcsolat; folytonossággal igazolt retained collection és warm-replay;
inventory-consumerek teljes átállása és addon-karcsúsítás. A korábbi quest-
progress, P7 provider/role és történeti lineage hiányok ettől nem szűntek meg.

Nem indult játék/capture/Ymir/FULL_AI, nem ment kliensinput. Addon és pinned
Ymir változatlan, új LIVE_VALIDATED állítás nincs.
