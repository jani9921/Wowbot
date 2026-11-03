# REV4 P3/P4 — saját állapot és a pixeltransport ellenőrzése

2026-10-30, Europe/Budapest. Munkamappa: a kijelölt `projekt`.

**A lent felsorolt adatútak offline teszteltek. A teljes P3 mezőparitás még PARTIAL.**
Az eddigi általános „kb. 70%” becslés helyett konkrét lezárt és nyitott kapuk szerepelnek.
Nem történt új élő quest-/combat-/utazásvalidáció vagy asszisztensi kliensinput.

## Ebben a körben elkészült

| Adatút | Bekötött működés | Határ |
|---|---|---|
| Saját HP kezdeti állapota | A korrelált saját GUID CREATE UnitData-blokkjából HP és max HP érkezik; a VALUES delta ugyanazt a közös mezőfeloldót használja. A feltételes owner/critter/regen mezők sorrendje kezelt. | A COMPLETE jelző a saját **HP-baseline-ra** vonatkozik; nem teljes saját karakter-/quest-/inventory-baseline. A mintakor külön érvényesül. |
| Saját erőforrás | A `SMSG_POWER_UPDATE` saját GUID/type/raw-value mezői bekerülnek a WorldModelbe, majd a meglévő ability-költségvizsgálatba. | Csak igazolt saját login, exact buildcsalád és közös selected-PID/session authority mellett. Nincs új input-authority. |
| Erőforrás-egységek | A tényleges PowerType.db2 21 rekordjának DisplayModifier értéke számolja a kijelzett értéket. Például 750 nyers rage = 75 rage. | Nem egyetlen kitalált osztó vonatkozik minden típusra. Ismeretlen skálázás raw-only marad; MaxBasePower nem aktuális max power. |
| Saját profil prefixe | A UnitData `Race`, `ClassId`, `PlayerClassId`, `DisplayPower`, `Level` mezői külön `OWN_PROFILE_UPDATE` eseményen érkeznek. A CharacterProfile a pozitív PlayerClassId-t részesíti előnyben. | Nincs talent/spec/role találgatás. A két class ID külön tény, nincs hardcoded névlista. Ismeretlen class/race/level nulla nem válik ismert állapottá. |
| Típusváltás | A mennyiség és a maximum is resource-type szerinti evidence-kulcsot kap. Típusváltás után régi rage/mana mennyiség vagy maximum nem címkéződik át. | Hiányzó típushelyes mennyiség/max `None`, nem 0 és nem másik erőforrás értéke. A maximum továbbra is tényleges mintából kell. |
| Gyakori frissítések | A fogadó azonos flow/GUID/típus/megváltozott-mezők szerint összevonja a saját state-deltákat. | CREATE baseline és diszkrét quest/cast esemény megmarad. Eltérő partial mezőhalmazokat nem olvaszt hamis közös mintaidővé. Movement peek nem kap HP/power mintát. |
| SERVER pixeltransport | A teljes AgentRuntime a valódi PixelSensor → grid-dekóder → PacketAssembler → BufferedPixelSensor/SensorHub → WorldModel úton fogad szintetikus BGRA STATE/FAST képeket. | Csak az OS képszolgáltató helyettesített; a szenzor/dekóder/reducer nem. A Windows GDI/DXGI és valódi játék megjelenítése továbbra is live-kapu. |

Minden profil-/HP-/erőforrás-fogyasztó ugyanazt a FieldSourceResolvert használja:
újabb addonadat megelőzhet régebbi packetet, azonos mintán a szerver erősebb.
Késve befejezett STATE megtartja eredeti mintakorát. Másik GUID/map/phase/capture-korszak,
loading és lejárat nem örökít régi packetmezőt. A saját UnitData-prefix csak a kiválasztott,
szerver által visszaigazolt karakterre olvasható; más játékos create/values profilja kimarad.

## Forrás és egységek

A PowerType és ChrClassesXPowerTypes táblát a meglévő DBCD.IO exportáló külön
tesztpéldánya dekódolta, a pinnelt WoWDBDefs `12ce70d5fef13370f0edf08889f01c05321d2e28`
definícióival. Az erőforráshoz csak a PowerType enum és DisplayModifier használatos;
a class-tábla sorrendjéből nem lett találgatott UnitData Power[] index.

- PowerType: 21 rekord, layout `14BBEEA1`, DB2 SHA-256
  `0674639fc2a69e87c7d2f2b46178a1dc8ed86b0d6cf48d97cfda059814d96703`.
- DBD SHA-256: `7ad0174a351fae5b7d896874b6e5ecc3694954ade3fac71f78e7ea757218422a`.
- ChrClassesXPowerTypes: 82 exportált rekord, layout `70DA1F8C`; vizsgálati evidence,
  nem közvetlen runtime slot-mapping.
- A kis runtime-katalógus: `data/client_power_types.json`; a létrehozó eszköz
  ellenőrzi a DB2/DBD/export hashét, layoutját, sorait és az enumok egyediségét.
  A közös loader cache-elt, hiányzó/hibás formátumot UNKNOWN-ként kezel.
- A statikus schema-label `WOWSTATIC_12_1_0_68914`, **nem élő buildvalidáció**.
  A katalóguson `live_build_verified=false` marad.
- Mind a költöztető, mind a GitHub-export fájllistája tartalmazza a kis katalógust.
  A meglévő nagy SQLite-katalógusokat ez a munka nem módosította.

A packet opcode a két ellenőrzött családban különbözik: POWER_UPDATE 69214 esetén
`0x45017E`, 70340 esetén `0x45017D`. A byte PowerType az int32 Power **előtt** van.
A saját UnitData új prefixe csak a vizsgált 70340-es családra engedélyezett.
Nem kapta meg automatikusan az NPC-ken korábban élőben validált címkét:
`WPP_12_1_OWN_UNIT_REVIEWED_V2`, `WPP_12_1_POWER_REVIEWED_V1` és
`WPP_12_1_OWN_PROFILE_REVIEWED_V1` az offline vizsgált scope-ot jelölik.

## Ellenőrzés és checkpoint

A célzott sajátállapot-/policy-/combat-/pixeltransport-kör **92 passed**.
Ez átfed a nagy regresszióval, nem hozzáadandó. A mailbox első új tesztjének
fixture-e payloadmódosítás után a régi content-ID-t tartotta meg; az inbox ezt
helyesen replayként elutasította. A fixture most a tényleges új tartalomból
képez új azonosítót, a replaykapu nem gyengült.

Végső kijelölt regresszió: **3736 passed, 2 skipped, 10 változatlan deselection;
306 modul; 137.48 s; exit 0**. A két skip változatlan opcionális képfájlhiány.
Ez nem a teljes 614 modulos teszttár hibamentességének állítása.
Mind az **526 source és 615 test Python-fájl** AST-parse ellenőrzése zöld;
614 test_*.py és egy helper van a tests fán.

A végső regresszió, parancs, változatlan tíz kizárás, JUnit, export-ellenőrzés,
AST és hashek a [provider-closure-evidence](provider-closure-evidence/) könyvtárban.
A mentés a kör előtti scoped baseline-t külön megtartja, nem írja felül a korábbi
P1-E–P9 checkpointot. A 203 számozott V4/Design követelménysor változatlan.

Az addon marad **0.9.80-12.1.0 / Interface 120100**; nincs új addonmásolás vagy
geometriaváltás ebben a körben. A két csomag byte-ra azonos. A Ymir-példány hash-e
változatlan, a programot az asszisztens nem indította el.

## Még nyitott kódos kapuk

1. Teljes packet questlog/questdefiníció és inventory/container baseline, minden
   fogyasztó paritása; a saját állapot további mezői, tényleges resource-max,
   aura/spec/talent/CC. Addonmező ebből a körből nem került eltávolításra.
2. Enemy interruptibility/channel/delay/hazard provider és a támogatott role-ok
   bővítése. Az öt korábbi cast-opcode nem vált ettől teljes combatrendszerré.
3. Történeti SQLite/TDB/import lineage, további nem támogatott questhandlerek és
   a geometriai hibák teljes verziódiagnosztikája.
4. A valódi Windows pixeltransport, travel/combat/quest élő kapui és a tényleges
   út-/harc-/recovery-idő kalibrálása. Ezekhez a felhasználó futtat élő próbát.

## Következő felhasználói live-próba szempontjai

Saját HP-esés/gyógyulás, resource-fogyasztás/töltés, resource-type váltás;
session/loading/map/GUI újraindítás. A packet HP/profile/resource nem tartja
frissnek az addon UI-ját vagy a kliensinput-jogosultságot. A már telepített addon
sikeres `/reload`/pixelstrip-betöltése még felhasználói visszaigazolást igényel.
