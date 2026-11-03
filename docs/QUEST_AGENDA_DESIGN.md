# Előretekintő feladatterv és mozgó célpontok becslése

## 2026-10-19 — Az agenda folytatása és a tényleges döntés összekötése

Az előző váz nem hiányzott teljesen, de leadás után elveszett belőle a
folytatáskeresés, és a vizuális fallback újra felülírhatta a már ismert
questgiverhez vezető utat. Ez most javított, **offline tesztelt** működés;
az új forrás élő validációja még hátravan.

Egy valóban felvehető questből már öt feltételes szakasz látszik:

1. Felvevő megkeresése, a valódi ajánlat ellenőrzése és felvétel.
2. A ténylegesen felvett quest/objective adatok kiolvasása.
3. Végrehajtás a közös skillrendszerrel, quest-credit ellenőrzéssel.
4. Igazolt teljesülés után a megfelelő leadási mód és hely használata.
5. Leadás után friss ajánlat/hely lekérése, majd az agenda újraépítése.

A második és későbbi szakaszok BLOCKED állapotú előretervek, nem végrehajtható
billentyűsorok. A legfeljebb 24 lépéses itinerary leírja az elvárt bizonyítékot,
és külön jelzi, ha hiányzó evidence vagy skillhiba miatt újratervezés kell.
Nem gyárt mérés nélküli valószínűségeket, NPC-azonosságot vagy quest-creditet.

A canonical QuestModel TURNED_IN állapota átviheti a korábban előkészített
folytatást a leadás utáni időszakba, akkor is, ha a referencia-projekcióból az
előző quest már kiesett. A quest eltűnése önmagában nem igazolja a leadást.
Üres, ténylegesen ismert questlog esetén van `discover:available` feladat;
hiányzó/olvashatatlan questadatból ilyet nem következtetünk.

A friss ajánlat vagy UI-változás azonnal frissíti az agendát. A Planner csak
már meglévő, elérhető javaslatot fogyaszt; a `current_task` és `recommendation`
mezők a tényleges tervezői ajánláshoz kötik az előretervet. Az ajánlás nem
végrehajtási vagy sikerigazolási authority. Harc, loot és nyitott dialógus
továbbra is a canonical felügyelet/skill-szerződés szerint működik.

A POI már rendelkezésre álló célhelye esetén a MOVE az első; menet közben csak
a meglévő, konkrét questcue-handoff állíthatja meg célzott azonosításra.
Ha nincs használható helyi questjel vagy ismert célhely, a térképi keresés
megelőzi a véletlen player/NPC-dobozok vizsgálatát. Az addon 0.9.68 leadás és
más érdemi questváltozás után az előző állapothoz tartozó lekérdezési korlát
miatt nem vár újabb 15 másodpercet. A válasz továbbra is aszinkron és élőben
ellenőrizendő; térképnyitási cooldown és keresési keret megmarad.

Ehhez az összetett javításhoz GUI-újraindítás és az új addon update/reload
szükséges. Az eredeti, alább dokumentált 2026-10-15-i agenda önmagában nem
igényelt addoncserét. Nem került be új kötelező LLM vagy külön quest-agy.

Állapot: **2026-10-15, implementálva a `projekt` munkapéldányban,
offline tesztelve; élőben még nem validált.**

## Mit tervez meg?

A meglévő Planner `QuestAgenda` része fenntart egy feltételes feladatsort:

1. A valóban felvehető, addonból ismert questek felvétele és visszaigazolása.
2. A ténylegesen felvett questek nyitott objective-jeinek megoldása.
3. A közös területre eső munkák csoportosítása, a felesleges visszautak kerülése.
4. A kész questek leadóinak előkészítése a TDB és a tanult SQLite-memória alapján.
5. Leadás után ugyanannál az NPC-nél vagy máshol elérhető folytatás ellenőrzése.

Példa: három quest egy területre szól. A munkák csoportba kerülnek;
az első kész quest távoli leadása legfeljebb 600 másodpercig halasztható, ha
a csoportban maradt ténylegesen végrehajtható munka. A közvetlenül útba eső
leadás kivétel. Ha a munka tiltott/elérhetetlen, a terv nem tilthat le minden
leadási alternatívát. Az összes objective igazolt teljesülése után a következő
leadási cél a meglévő javaslatok közül kerül előre.

Minden nyitott objective mellett megjelenik a képességszintű megoldási lánc is,
például azonosítás → target → közelítés → harc → szükség szerinti loot →
quest-credit ellenőrzés. Ez nem előre eltárolt billentyűsor: minden lépcsőnél
az eredeti skill-szerződés, range/facing/LOS és friss azonosság dönt.

## Hogyan számol előre, miközben fut egy skill?

- A közepes kör legfeljebb másodpercenként frissíti a nézetet, questváltozásra
  hamarabb. Ez nem hívja újra a skillválasztót és nem cseréli le az aktív kísérletet.
- A célhelyeket a meglévő `tdb_locations` feloldók szűrik térkép, instance,
  fázis, objective és élő POI-egyezés szerint. A friss, tanult korrekciók ugyanazon
  a meglévő referencia/memória útvonalon jönnek. Nincs új adatbázis vagy második agy.
- Azonos XY, de több mint 15 yard ismert Z-különbség nem azonos munkaterület.
  Ismeretlen vagy nem konvertált koordinátából nem készül navigációs cél.
- A `route_preview` legfeljebb 24 jövőbeli lépést fűz össze, feltételesen
  teljesült előfeltételekkel és a következő célhoz mért távolságbecsléssel.
  A szimulált teljesülés kizárólag helyi változó: nem ír questállapotot, creditet,
  memóriát vagy inputot. A lépések valódi READY/BLOCKED állapota változatlan.
- A sorrend becslés, **nem navmesh-útvonal és nem garantált optimális körút**.
  A tényleges útvonalat, peremeket és barlangszinteket továbbra is a közös
  NavigationService kezeli. Ismeretlen bejáró vagy fázis új bizonyítékot igényel.
- Csak már létező, elérhető M0-javaslat rangsorát módosíthatja. Proposal-keyt,
  targetet, paramétert, bindinget nem ír át. Használható objektum, harc, loot
  vagy dialógus nem szorulhat hátra egy terv által megemelt keresés mögé.
- Explicit primary quest és MAIN_CAMPAIGN korlátozás megmarad. Generikus
  questelésnél a felhasználó által kért többquestes csoportosítás működik.

## TDB-előtöltés és questfolytatás

A referenciaolvasó a valódi gossip-ajánlatokat is figyelembe veszi, nem csak
a questlogot és a map API-t. Az ajánlat objective-területe előkészíthető,
de a munka BLOCKED marad, amíg a quest nincs igazoltan a logban.

Az explicit `NextQuestID` / `RewardNextQuest` kapcsolatokból legfeljebb két
következő quest metaadata tölthető elő. Egy projekciónál legfeljebb négy új
katalógusolvasás engedett; a 64 elemű, kontextushoz kötött cache 60 másodperces.
Az ismert feladóhely és a tanult role/spawn korrekció is használható. Mindez
`REQUIRES_LIVE_AVAILABILITY`: a TDB-kapcsolat **nem bizonyítja a felvehetőséget**.
A forrás SQLite-t nem módosítjuk, titkos kliensadatot nem kérünk le.

A legfeljebb 32 helyjelöltből álló nézet először típusos szerep/objective
csoportonként tart meg egy közeli jelöltet, majd közelség szerint töltődik fel.
Így sok közeli objective-spawn nem szorítja ki automatikusan az ismert távoli
leadót. A folytatás előtöltése a feladóhelyeket részesíti előnyben; a térkép-,
fázis- és azonosságellenőrzések ettől még változatlanul szükségesek.

FIELD_TURN_IN/AUTO_COMPLETE/SPECIAL_UI esetén nem tervez automatikusan visszautat
az eredeti feladóhoz. Másik quest nyitott UI-ja nem alakíthatja át az aktuális
quest leadási módját. Az elfogadást/leadást a meglévő UI és verifier intézi.

## Opcionális helyi LLM

A meglévő `SemanticAdvisor` háttérmunkása kap egy új `agenda` feladattípust.
Nem telepítünk és nem kapcsolunk be új modellt: a meglévő konfiguráció érvényes.

Az LLM csak megadott task ID-k sorrendjét javasolhatja. A válaszból kiesik minden
kitalált task/NPC/koordináta/parancs; hiányos, duplikált vagy függőséget sértő
sorrend nem használható. A rangsor nem old fel BLOCKED feltételt, és csak
összehasonlítható távolságú feladatokat rendezhet át. Egy késve megérkező válasz
nem szakítja meg az aktív feladatot. Az alapműködés LLM nélkül is determinisztikus;
a lassú/elérhetetlen modell miatt az agent nem várakozik.

A tényleges helyi modell új feladattípusra adott válaszának minősége még nem
élőben ellenőrzött; a tesztek hamisított transportot használnak.

## Mozgó target: rövid becslés, nem ReID

A gyors vezérlési nézet a friss, azonos trackű dobozokból becsüli a képernyőn
mért sebességet. Rövid lineáris illesztést használ; a kurzor célpontja a kép
korával és kis inputkéséssel előretartott pont. Maximum 0,5 másodperces lead
és 0,12 képernyőegységnyi eltolás engedett. Ez nem világkoordinátás NPC-útvonal.

Hirtelen irányváltás, nagy illesztési hiba, térbeli ugrás, régi/takart doboz,
kamerafordulás vagy zoom, új ID, session/map/phase/epoch váltás után a becslést
elengedi/újrakezdi. A becsült pont kizárólag célzás: nem ad GUID-azonosságot,
lootjogot, kattintási engedélyt vagy új track-ID összefűzést. A friss tooltip/
target visszaigazolás továbbra is kötelező.

## Diagnosztika és validáció

- `quest_agenda.implementation = grounded-quest-agenda-v1`
- `quest_agenda.steps`, `preferred_step`, `same_area_groups`, `itinerary`
- `quest_agenda.advice`, `advice_key`, `selection_reason`
- `parallel_control.target_motion.implementation = bounded-target-motion-v1`

Ezek bekerülnek a statusba és a live-debugba is. A GUI-t újra kell indítani.
Nem módosult addon/protokoll; ehhez a változáshoz önmagában nem kell addoncsere.

Offline bizonyíték: `test_quest_agenda.py`, `test_agenda_reference_prefetch.py`,
`test_target_motion_prediction.py` és a kapcsolódó regressziók. A pontos végső
eredmény a `LIVE_VALIDATION.md`-ben szerepel. Az alacsony FPS-es, töltő nélküli
régi futás továbbra sem mérvadó. Új, felhasználó által vezetett normál FPS-es
teszt kell; FULL_AI-t az asszisztens nem indít és nem vezérli a klienst.
