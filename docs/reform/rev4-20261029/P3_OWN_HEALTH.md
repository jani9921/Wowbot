# P3 — saját HP és mezőnkénti mintaidő, 2026-10-30

**Részleges saját UnitData provider, offline tesztelt.** Saját HP CREATE-baseline és VALUES delta; nem teljes own-player/questlog/inventory baseline, nem új input-authority, és nincs új élő elfogadás. Aktuális kiegészítés és evidence: [P3/P4 provider-kör](P3_PROVIDER_CLOSURE.md).

## Bekötött adat

A meglévő, pinnelt WPP 12.1.5 UnitData-mask olvasó egészségmezői használhatók a saját karakterre is. Új maszkelrendezés nem lett kitalálva: ugyanaz a már meglévő ReadUpdateUnitData prefix dolgozik. A create által megismert fragmentlista nélkül a values blokk továbbra sem olvasható ki.

A decoder a saját GUID-ot csak a kiválasztott folyamat korrelált CMSG_PLAYER_LOGIN + SMSG_LOGIN_VERIFY_WORLD baseline-ja után fogadja el, ugyanazon kapcsolaton. Login intent önmagában nem elég. Az own ág a kifejezetten kezelt 70340-es opcode-családra korlátozott; közeli/egyéb buildhez nincs fallback. Új login törli az előző megerősítést.

Az **OWN_UNIT_UPDATE** csak mover GUID-ot, world map ID-t, CREATE/VALUES mintatípust, HP-t és/vagy max HP-t visz tovább. A saját CREATE ismert owner-függő UnitData-prefixéből együtt érkező HP és max HP kezdeti HP-baseline-t ad. Más játékos GUID-jából, ismeretlen fragmentből és a saját PlayerData/ActivePlayerData más mezőiből nem lesz ilyen esemény. Sem pozíció-, sem questlog-, sem inventoryteljességet nem állít.

A schema külön WPP_12_1_OWN_UNIT_REVIEWED_V2 eredetcímkét ad; a korábbi V1 csak delta-kompatibilis. V1 címkével CREATE nem állíthat baseline-t. Ez nem a korábbi, NPC-ken élőben validált layoutcímke átnevezése saját karakterre. A reducer ismét ellenőrzi a selected PID/session/build és exact own GUID határt, a mapot és frissességet. Másik karakter vagy map adata nem cserélheti le a saját HP-t.

## Egyetlen mezőfeloldó

Packet és addon HP ugyanabba az Evidence/FieldSourceResolver rétegbe kerül. A frissebb valós minta nyer; azonos mintánál a szerveres authority erősebb. Egy friss FAST HP ugyanabban a tickben leválthat régebbi packet HP-t. Health receipt nem frissíti a pixel/input liveness-t, és HP=0 önmagában nem generál automatikus halál-/resurrection-sikert.

A HP saját source-mintáját a Python transportnormalizáló health_sample_time néven őrzi. Mivel a STATE újabb FAST mezőket is tartalmazhat, nem szabad az egész snapshot korát ráhúzni a kevert HP-ra. A megmaradt mezőidőből és a control-időből csak azonos addonórán belüli relatív kor számolódik; ebből lesz helyi receipt mínusz kor. Nem történik ismeretlen abszolút órák automatikus összekeverése.

A közös Evidence opcionális mezőideje csak korábbra szűkíthet egy ismert eredetet; nem fiatalíthat meg deklarált origin-t, nem javíthat ki hibás/jövőbeli forrásidőt, és nem módosítja az Observation tartalmát vagy fingerprintjét. Teljes STATE-ből késve érkező régi HP nem írhatja felül az újabb packetet.

A FAST-projekció eddig az előző tick referenciaidejével futott, mert last_received csak a projection után frissült. A kiértékelési referencia már a jelenleg feldolgozott Observation receipt idejét is figyelembe veszi. Ettől a régi tények nem kapnak új sample-időt vagy TTL-t.

## Korlátok

- A provider az ismert saját CREATE és VALUES prefixet olvassa. Igazolt CREATE HP-párra az own_health baseline COMPLETE; kezdeti, csak delta adatra PARTIAL. Ez nem a teljes saját PlayerData/ActivePlayerData baseline-ja.
- A referencia- és HP-tények frissessége különbözik a saját session/UI/input authoritytól. A baseline meglétének metadata-ja nem frissíti a HP mintaidejét; scope/loading váltás törli.
- Questlog, inventory, aura/talent és egyéb ActivePlayerData még nem teljes packet-paritás. Power/resource egységek és saját profil-prefix már külön bekötve, részletes határaik a provider-kiegészítésben. A megjelölt addonforrás szükséges marad; mező nem lett eltávolítva.
- Az élő user-runban külön ellenőrizendő: saját HP-esés, gyógyulás, újabb FAST és régi STATE egymásra futása, map/sessionváltás és capture újraindítás. A tesztvektor és hitelesített localhost lánc nem élő combatbizonyíték.

A korábbi delta-only checkpoint célzott köre 112 pass volt. Az aktuális provider-kör eredménye és mentése a [provider-kiegészítésben](P3_PROVIDER_CLOSURE.md) szerepel; az egymást átfedő körök nem összeadandók.
