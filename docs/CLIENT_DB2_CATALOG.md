# Helyi DB2-katalógus és a meglévő TDB

2026-10-27: elkészült a külön `data/client_supplement.sqlite3` ItemEffect-, item–spell-,
AreaTrigger/alak- és ConversationLine-katalógus. Az alábbi eredeti katalógus számai változatlanok;
az új adatokat és a unit/self itemhasználat offline bekötését a [CLIENT_DB2_ITEM_EFFECT.md](CLIENT_DB2_ITEM_EFFECT.md)
részletezi. A talaj/object célzás, valamint az ARRIVE/WITNESS végrehajtási bővítése még nyitott.

## Szerepek

A meglévő TDB továbbra is ugyanarról a beállított fájlról, ugyanazzal a
ReferenceCatalog / WorldSqliteReference / TDBKnowledgeProvider lánccal működik.
Nem másoltuk át, nem cseréltük le, nem módosítottuk a konfigurációját.
A questszöveg, objective, starter/ender, spawn XYZ, feltétel és POI továbbra
is ebből és az élő megfigyelésekből származik.

Az új `data/client_reference.sqlite3` kiegészítő, csak olvasott kliensadat.
Forrása a gépen már meglevő `World of Warcraft/_retail_/dbc/enUS` könyvtár.
Futás közben nincs Wago- vagy más hálózati lekérés. A közös ReferenceCatalog
`client_quest()` felülete és ReferenceKnowledge `client_reference` mezője
questazonosító szerint kapcsolja a kiegészítést a meglévő questmodellhez.
Nincs külön questagy vagy mozgás-/inputtulajdonos.

## Tényleges adatlefedettség, 2026-10-25

| Adat | Darab | Jelentés |
|---|---:|---|
| Helyi DB2-forrásfájl | 1125 | SHA-256 + fejléc + séma leltár |
| Dekódolt tábla | 36 | Az összes helyi Quest*, SceneScript*, Path*, valamint Location, Map, AreaTable, UiMap és SpellEffect |
| Questazonosító kliensrekorddal | 66589 | Nem feltétlenül teljes szöveg vagy használható questmegoldás |
| Scene-csomag | 3530 | Nyers csomag + tagság/gyermekcsomag/scriptlánc |
| SceneScriptText | 40431 | Lekérdezhető adat; nem futtatott Lua |
| Útvonal PathNode-dal | 17511 | Sorrend + Location XYZ és rotáció |
| Scene-csomag támogatott literális path-hivatkozással | 253 | Lehet többjelöltes; nem automatikusan játékosnak szánt repülési út |
| Kliens quest-POI blob | 72381 | Map/UI-map/objective/feltétel megmarad |
| Kliens quest-POI pont | 170335 | Referenciageometria; nem sorrendi mozgási útvonal |
| Ellenőrzött referencia quest→gyűrűspálya kapcsolat | 4 | Egy konkrét mechanikához bekötött adatok, nem a teljes questadatbázis |
| Quest scene-kapcsolatjelölttel | 241 | Automatikus TDB/DB2 strukturális hivatkozáskeresés |
| Scene-kapcsolatjelölt | 332 | Forráslánc, időzítés és feltételek megőrizve |
| Egyetlen scene-csomagot adó questreferencia | 214 | Nem jelenti a scene aktív állapotát vagy a quest teljesíthetőségét |
| Többértelmű questreferencia | 27 | Nincs önkényes csomagválasztás |
| Feltételkulcsos táblából feloldott pályakapcsolat | 179 | A kiválasztó kód és a PlayerCondition kapcsolata is azonosított |

A maradék 1089 DB2 csak leltározott, nincs dekódoltnak jelölve.
A nyers rekordok `db2_rows` alatt maradnak; a `quest_links`, `scene_scripts`,
`scene_paths`, `path_nodes`, `locations`, `poi_blobs`, `poi_points` táblák
indexelt lekérdezéseket adnak. Minden dekódolt forrás és DBD definíció hash-e
visszakövethető. A dekóder exportja és az importált helyi fájl hash-e egyezni
kell; eltéréskor az import nem publikál kész adatbázist.

A WDC5-fejléc `WOWSTATIC_12_1_0_68914` címkéje statikus sémacímke. Nem állítjuk,
hogy ez a kiválasztott élő kliens buildje, vagy hogy minden statikus rekord
egyezik annak jelenlegi hotfix/phase/quest állapotával.

## Általános használat

A projekt gyökeréből:

```powershell
python tools/query_client_catalog.py
python tools/query_client_catalog.py --quest 77345 --details
python tools/query_client_catalog.py --quest 11 --details
python tools/query_client_catalog.py --scene 3978
python tools/query_client_catalog.py --path 49404
python tools/query_client_catalog.py --record SceneScriptText 46850
```

A `--quest` a már beállított TDB-t olvassa, és mellé adja a DB2-referenciát.
A `--tdb` kizárólag erre az egy lekérdezésre adhat másik meglévő WORLD-fájlt;
nem ír konfigurációt vagy másolatot. A `--details` az explicit TDB quest-script
és quest-elfogadás/jutalmazás SmartAI-hivatkozásokat is visszaadja; ezek
szerveroldali referenciaadatok, nem futtatandó kliensutasítások. Más questhez
tartozó scriptet és a „bármelyik quest” nullaazonosítót nem köti az aktuálishoz.

A több tízezer normál questet továbbra is a meglévő közös objective-, keresési,
harci, tárgyhasználati és interakciós skillek kezelik. Nem kell minden questhez
új Python-script. Egy eddig nem támogatott mechanika viszont újrahasználható
adaptert/skillt és valódi visszaellenőrzést igényel. A DB2 nem tartalmazza
az összes Retail szerveroldali questlogikát. A hiányzó vagy többértelmű
quest→scene kapcsolat `UNRESOLVED`, nem kitalált koordináta vagy kész megoldás.
A scene/pálya általános lekérdezése a négy questtől függetlenül működik.

## Gyűrűs questadapter és közös mozgás

Az adapter a `src/wowbot/quests/scene_path_planning.py` fájlban van.
A `data/quest_scene_bindings.json` négy, külön jelölt referencia-kapcsolatot
tartalmaz; koordinátákat nem. A lánc: scene package/member/script → pathID →
PathNode → Location. A quest és scene összerendelését külön fel kell oldani.

A JSON az automatikus feloldó utáni, opcionális ellenőrzött kivétellista.
Az általános import és a scene-feloldás nélküle is működik; nem kell minden
questet beleírni. Automatikus, ellentmondásmentes pályakapcsolat esetén az
automatikus eredmény az elsődleges. Ellentmondó egyértelmű forrás esetén az
építő hibával megáll. A négy oktatóquesthez az eddig feldolgozott kapcsolatok
nem adnak teljes automatikus indítóláncot; a már ismert pályák kivétele megmarad.

| Quest | Scene package | Path | Gyűrű + cél |
|---|---:|---:|---:|
| 65118 – How to Glide with Your Dragon | 3747 | 45295 | 5 + 1 |
| 65120 – How to Dive with Your Dragon | 3748 | 45296 | 5 + 1 |
| 65133 – How to Use Momentum with Your Dragon | 3749 | 45297 | 5 + 1 |
| 77345 – The Need For Higher Velocities | 3978 | 49404 | 8 + 1 |

Az adapter az aktív quest/objective és instance egyezésekor egy stabil MOVE-ot
és deklaratív FlightPath-ot ad. Nem mountol, nem kormányoz, nem dönt földi vagy
légi fázisról. A TravelModePolicy kezeli a mount-előfeltételt; a meglévő
NavigationService / ReachMovementController kezeli a felszállást, repülést,
leszállást, ellenőrzött MMAP földi megközelítést és érkezési bizonyítékot.
A Steady Flight leszállása ugyanarra a földi átadásra jut. Mounton lehet
sétálni; önmagában a repülő mount nem indít repülést. Nem kell új quest-ID
ágat tenni a mozgásvezérlőbe.

A szervercredit eredeti idővel és kiválasztott session/karakter/instance/build
kontextussal kerül a közös WorldModelbe. Nem ad inputjogot, nem frissíti az
addon liveness-t. A gyűrűcredit kötelező feltételét nem helyettesíti az, hogy
a karakter közel került egy ponthoz. A földi célhoz érve késő credit esetén
nem száll fel újra és nem gyárt sikert. Az aktuális fizikai bindingokat
továbbra is a kijelölt, ellenőrzött cache adja.

## Automatikus quest–scene feloldás és a tényleges határa

A `src/wowbot/quests/scene_resolver.py` a következő explicit kapcsolatokat
követi, questazonosítók felsorolása nélkül:

- TDB quest SourceSpellID → DB2 SpellEffect → scene/package.
- Quest elfogadásához, jutalmazásához vagy quest-owned SmartAI-eseményhez
  kötött cast/scene-play → spell/scene; a link és timed action list követhető.
- Spell trigger és pozitív TDB linked-spell élek, mélység-/csomópontkorláttal
  és ciklusvédelemmel. A feltételes trigger nem válik feltétlen műveletté.
- TDB spell_area és pozitív questfeltételes spell-kapcsolat; minden további
  feltétel megmarad. A negatív questfeltétel nem lesz pozitív indítókapcsolat.
- SceneScriptText EvalPlayerCondition → DB2 PlayerCondition questmezői →
  scene-csomag. A CurrQuest / CurrentCompletedQuest / PrevQuest / QuestKill
  szerepek külön maradnak; a korábban teljesített quest nem aktív questbizonyíték.
- Feltételazonosítóval kulcsolt literális táblák, például
  `pathInfo[conditionID] = {pathID=N}` és a hozzá tartozó
  `pairs(table) / EvalPlayerCondition(key) / pathID=value.pathID` kiválasztó.
  A tábla neve és a ciklus változónevei nincsenek rögzítve. Egy questhez csak
  a hozzá tartozó feltétel ágának pályája kerül, nem a közös scene összes útvonala.

A Play Scene Package effekt (195) csomagot nevez meg. A Play Scene effekt
(198) és Play Scene aura (430) scene-ID-t; ezeknél szükséges a TDB
scene_template → ScriptPackageID kapcsolat. A numerikusan azonos scene- és
package-ID nem helyettesítheti ezt. A 629424 importált SpellEffect rekordból
2155 scene-effekt/aurasorhoz nincs ilyen kapcsolat a jelenlegi helyi TDB-ben;
ez pontos, lekérdezhető adatbeli hiány, nem automatikus csomagtipp.

A feloldó külön tárolja a kapcsolat eredetét és a mozgási használhatóságát.
A 241 questnél talált 332 jelöltből 214 questnél egy csomag adódik, 27-nél több.
Ezek scene-referenciák: köztük cinematic/actor/camera és feltételes történeti
hivatkozások is vannak. Nem lettek játékosnak szánt repülési útvonallá
minősítve. A jelenlegi valódi adatokból **0 további végrehajtható gyűrűspálya**
állt össze minden szükséges kapcsolat és mechanika-egyezés mellett.

A támogatott Checkpoint/RaceComplete gyűrűs mechanika adatból felismerhető.
Egy egyértelmű, feltétlen, megfelelő időzítésű lánc, teljes abszolút XYZ-pálya,
egyértelmű ring/target objective és map esetén automatikus quest_routes
rekordot készít, ugyanahhoz a meglévő questadapterhez és közös mozgásvezérlőhöz.
Ezt offline, a négy kivételtől különböző questtel teszteltük. A valódi helyi
adatoknál hiányzó/feltételes láncot ez a teszt nem pótolja.

A `scene_resolution` lekérdezés megmutatja az állapotot, a forrásláncot,
a többértelműséget és a pálya tiltásának okát. A scene-pálya literálok külön
jelöltként is kereshetők, a feltételhez kötött egyszerű ágak feltétel-ID-val;
nem támogatott Lua elágazást vagy scriptet nem hajtunk végre.

Az indítólánc nélkül maradt négy oktatóquest, a hiányzó scene_template
kapcsolatok és a feltételek élő kiértékelése továbbra is nyitott. A teljes
Retail quest/szerverlogika nincs a helyi TDB/DB2-forráshalmazban igazolva.

## Skytop Observatory: gépi összekötés

A fő utazóquest 68796 (The Skytop Observatory); a hozzá kapcsolódó gyűrűs
futam neve To Skytop Observatory, azonosítója 72089. A futam adatkapcsolata:

`PlayerCondition 103255.CurrQuestID[0]=72089 → SceneScriptText 37290 pathInfo → scene package 3562 → Path 43699 → PathNode / Location`.

Ezt a normál feloldó hozza létre; 72089 nincs a négy kézi kivétel között.
A scriptben lévő név és „to skytop observatory” megjegyzés nem szükséges a
feldolgozáshoz. A kiválasztó ciklus és a feltételkulcsos tábla szerkezete adja
a kapcsolatot. Az adat az eredeti DB2 írása nélkül, a saját SQLite
quest_scene_candidates / scene_path_candidates / quest_scene_resolution
tábláiba kerül. Az agent közös ReferenceCatalog/ReferenceKnowledge felületén
egy aktív 72089 questhez már elérhető a path_reference és a koordináták.

A pálya **7 teljes XYZ-pontot** tartalmaz, eredeti Sequence értékei 1–7.
Kezdete (1831.7291,32.350697,304.61826), vége
(2414.0417,-1168.3229,345.67175). Nem MAX(Sequence)+1 alapján számolunk.

```powershell
python tools/query_client_catalog.py --quest 72089 --details
python tools/query_client_catalog.py --path 43699
```

A kapcsolat és a geometria feloldása offline ellenőrzött; a feltétel élő
kiértékelése, az ideiglenes futamquest észlelése és a futam végigrepülése
nincs élőben validálva. A futamnak a TDB-ben egy Complete the Course objective-ja
van, nem öt külön gyűrűcredit és egy Target Area. Emiatt a meglévő lecke-adapter
nem minősíti kész, végrehajtható gyűrűspályának pusztán a koordináták alapján.
A futam előrehaladásának megfelelő adaptere továbbra is nyitott részfeladat.

## Újraépítés

A dekóder `native/db2_exporter`: .NET 10, DBCD 2.3.0, rögzített NuGet lockfile.
WoWDBDefs revízió: `12ce70d5fef13370f0edf08889f01c05321d2e28`.
Csak statikus fájlokat olvas. Nincs processz-/memóriaolvasó, inputvezérlés vagy
online adatprovider. A definíciók beszerzéséhez az alábbi upstream forrás
használható; futáskor ezekre már nincs szükség.

```powershell
$catalogWork = Join-Path $PWD 'output/db2-rebuild'
New-Item -ItemType Directory -Path $catalogWork -Force
git clone https://github.com/wowdev/WoWDBDefs.git "$catalogWork/definitions-repo"
git -C "$catalogWork/definitions-repo" checkout 12ce70d5fef13370f0edf08889f01c05321d2e28
dotnet restore native/db2_exporter/Db2Export.csproj --locked-mode
dotnet build native/db2_exporter/Db2Export.csproj -c Release --no-restore
$db2Directory = 'C:/Program Files (x86)/World of Warcraft/_retail_/dbc/enUS'
$tableNames = @(Get-ChildItem -LiteralPath $db2Directory -Filter '*.db2' -File |
    Where-Object { $_.BaseName -match '^(Quest|SceneScript|Path|Location$|Map$|AreaTable$|UiMap$|SpellEffect$)' } |
    ForEach-Object { $_.BaseName })
dotnet native/db2_exporter/bin/Release/net10.0/Db2Export.dll $db2Directory "$catalogWork/definitions-repo/definitions" "$catalogWork/decoded-new" @tableNames
$existingWorld = (Get-Content config/reference_catalog.local.json -Raw | ConvertFrom-Json).path
python tools/build_client_catalog.py --output data/client_reference.new.sqlite3 --db2 $db2Directory --decoded "$catalogWork/decoded-new" --definitions "$catalogWork/definitions-repo/definitions" --definition-revision 12ce70d5fef13370f0edf08889f01c05321d2e28 --associations data/quest_scene_bindings.json --world-reference $existingWorld
```

Az exportkönyvtár és az új SQLite nem írhat felül meglévő exportot/katalógust.
A TDB-ből az építő a scene/quest/spell/SmartAI/feltétel kapcsolatokat olvassa;
csak származtatott hivatkozások kerülnek a klienskatalógusba. Nem importálja
vagy másolja át a TDB tábláit. Az `--associations` opcionális; elhagyásakor
csak az automatikus feloldó dolgozik.

Ha a DB2 már importálva van, újrakinyerés helyett elég a származtatott
kapcsolatokat újraépíteni a meglévő két adatbázisból:

```powershell
$existingWorld = (Get-Content config/reference_catalog.local.json -Raw | ConvertFrom-Json).path
python tools/resolve_client_scenes.py --catalog data/client_reference.sqlite3 --output data/client_reference.resolved.sqlite3 --world-reference $existingWorld --associations data/quest_scene_bindings.json
```

Ez a saját klienskatalógus új példányát publikálja atomikusan; a TDB-t csak
olvassa. A TDB hash-e építés közben sem változhat. Az eredeti klienskatalógus
is megmarad; az új fájl ellenőrzés után válthatja azt.

Upstream: [DBCD](https://github.com/wowdev/DBCD),
[WoWDBDefs – rögzített revízió](https://github.com/wowdev/WoWDBDefs/tree/12ce70d5fef13370f0edf08889f01c05321d2e28),
[TrinityCore extractors](https://github.com/TrinityCore/TrinityCore/tree/master/src/tools/map_extractor),
[SmartScript sémaszemantika](https://github.com/TrinityCore/TrinityCore/blob/master/src/server/game/AI/SmartScripts/SmartScriptMgr.h).
Spell/scene szemantika: [SpellEffects.cpp](https://github.com/TrinityCore/TrinityCore/blob/master/src/server/game/Spells/SpellEffects.cpp),
[SpellAuraEffects.cpp](https://github.com/TrinityCore/TrinityCore/blob/master/src/server/game/Spells/Auras/SpellAuraEffects.cpp),
[ConditionMgr.h](https://github.com/TrinityCore/TrinityCore/blob/master/src/server/game/Conditions/ConditionMgr.h).

## Nyitott ellenőrzés

Az adatimport és a mozgás/questhatár offline tesztelt. A 65118 korábbi élő
5/5 + 1/1 jóváírása nem validálja ezt az új refaktort, a leadást vagy a 77345
önálló teljesítését. Ezekhez felhasználói élő teszt kell. Az összes scene,
összes questmechanika, általános quest→scene-felderítés és feltételes scene
script értelmezése nincs késznek minősítve. Ismeretlen adat nem válik autoritássá.
