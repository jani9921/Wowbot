# Átalakítási állapot és túlélési követelmények

Dátum: 2026-10-30, Europe/Budapest. Ez a fájl állapotfeljegyzés és tervezési kiegészítés. Nem igazol új agentfunkciót vagy élő sikert. Ebben a munkakörben csak olvasás és dokumentálás történt; nem indult capture, FULL_AI vagy kliensinput.

## Ellenőrzött állapot

A korábbi, kizárólag tervezési állapothoz képest a célprojektben már tényleges kódmódosítások vannak. Az állapot forrása a projekt naplója és a mentett teszteredmények; a P0–P9 fejezetcímek vagy új fájlok puszta létezése nem jelenti a fázis elfogadását.

Célprojekt: `C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt`.

| Terület | Ellenőrizhető állapot |
|---|---|
| P1-A | A példányhoz kötött navigációs költséglekérdezés elkészült, offline tesztelt. |
| P1-B | A logikai session/world kontextus és a packetállapot hatókörváltás miatti érvénytelenítése elkészült, offline tesztelt. A teljes független bootstrap ettől még nem kész. |
| P1-C | Navigációs lekérdezési függőségek és közös gyűjtési forrásegyeztetés: a kijelölt rész elkészült, offline tesztelt. |
| P1-D | Közös evidence-értékek, megfigyelési/fogadási idő és forrásleszármazás: a kijelölt rész elkészült, offline tesztelt. A tágabb P1 státusza továbbra is részleges. |
| Későbbi átállás | P1-E–P9 nevű munkakönyvtár és új forrásmódosítások, résztesztek léteznek. Az összes fázis lezárását és teljes termékfunkcióját ez az ellenőrzés nem igazolja. |
| Utolsó mentett összesített kör | 301 tesztmodul; 3629 passed, 2 skipped, 10 deselected; exit 0. Ez mentett eredmény, most nem futtattam újra. |
| Aktuális forrás | A fenti teszt után a `collection_coverage.py` és `geometry_contracts.py` is változott a fájlidők szerint. A mentett zöld kör nem bizonyítja automatikusan az azóta módosított forrás állapotát. |
| Élő elfogadás | A felsorolt átállási részekből nem következik új, sikeres felhasználói live quest-, repülés-, combat- vagy talentteszt. |

Bizonyítékok:

- [A célprojekt élő és offline ellenőrzési naplója](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt/docs/LIVE_VALIDATION.md:3>)
- [P1-D mentett ellenőrzési összesítés](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1d-20261029/validation-summary.json>)
- [Legutóbbi összesített tesztnapló](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1e-p9-20261029/combined-2.log>)
- [A tesztkör befejezési eredménye](<C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/_work/rev4-p1e-p9-20261029/combined-2-result.json>)

## Saját élet, harc előtti regenerálódás, étel

Az agent friss, a kiválasztott karakterhez tartozó élet/maximális élet adatból állapítsa meg a harckészültséget. Hiányzó, elavult vagy nem hozzáférhető érték `UNKNOWN`; ebből nem lesz feltételezett 100% élet. A publikus addonadat vagy ellenőrzött szerveres szemantika használható a saját mező jogosult adatforrásaként, titkos érték megkerülése nélkül.

Új harc kezdeményezése előtt a profilhoz és a várható ellenfélhez igazított felkészülési szabály döntsön. Kevés életnél a meglévő questcél megőrzésével regenerálódás következzen. A pihenés megkezdési és befejezési küszöbe legyen eltérő, hogy ne váltogasson folyamatosan evés és támadás között. Ne követeljen minden harc előtt automatikusan 100%-ot; a cél a helyzethez megfelelő visszatöltés. Ismeretlen életből ne kezdeményezzen vakon új pullt, de a már megtámadott karakter védelmét ne tiltsa le.

Ételt csak a saját táskában megfigyelt, ténylegesen rendelkezésre álló és használható tárgyból válasszon. Az itemazonosító, hatás, mennyiség, követelmények és használhatóság igazolja a választást. Az alapanyag, quest item vagy csak hasonló nevű tárgy nem válik étellé. A fogyasztás a meglévő végrehajtón, igazolt aktív bindingon vagy az addonból kapott aktuális látható bag UI-n keresztül történjen; ne legyen kitalált gyorsbillentyű vagy UI-koordináta.

Evés csak az adott tárgy valódi használati feltételeivel, harcon kívül és megfelelően biztonságos helyen induljon. A mozgás és az új pull várjon. A használat után a regenerálódási állapotot és az élet változását kell figyelni, nem újra és újra ugyanazt a tárgyat aktiválni. Az item fogyása vagy egy elfogadott gombnyomás önmagában nem bizonyítja a feltöltődést. Támadás, veszély, kézi beavatkozás vagy elveszett inputjogosultság megszakítja a pihenési tervet; harci veszélyben a közös reakciókezelés veszi át a szükséges feladatot.

Ha nincs étel, a profil által megengedett saját gyógyítás vagy megfigyelt természetes regenerálódás mérlegelhető. A várakozásnak oka, várt állapotváltozása és újraértékelési feltétele legyen. Tartós hiány vagy elmaradó gyógyulás ne okozzon végtelen evési/harckezdési ciklust. Automatikus vásárlást vagy ritka fogyóeszközök felhasználását ez a követelmény nem határozza meg.

## Defenzív cooldownok harc közben

A döntés már növekvő veszélynél szülessen meg: életarány és annak trendje, friss bejövő sebzés, több támadó, ismert közelgő nagy sebzés, elkerülhetetlen cast vagy tartós sebzés alapján. Nem elegendő egyetlen, minden classra azonos alacsony HP-küszöb, és nem kell megvárni a közvetlen halálveszélyt.

A tényleges class/spec/forma és ismert képességek határozzák meg a jelölteket. Külön szerepe van a sebzéscsökkentésnek, absorbnak, blokk/kitérés jellegű védelemnek és saját gyógyításnak. A választás vegye figyelembe az ismert sebzéstípust, időzítést, aktív védekező aurát, erőforrást, cooldown/charge állapotot és a várható további veszélyt. Csak a jelenlegi baron igazoltan elérhető, használható és kötött képesség aktiválható; ismeretlen cooldown nem jelent kész képességet.

A rendszer ne süsse el indokolatlanul egyszerre az összes védelmet, és ne ismételje a már aktív hatást. Súlyos veszélyben indokolt kombináció megengedhető. A kitérés, interrupt, védekezés és gyógyítás egy közös harci döntés része, ugyanazzal az inputtulajdonossal és navigációval. A gyors reakció nem vár helyi LLM-válaszra.

A saját spell sikeres aktiválása, a védekező aura/absorb megjelenése és a ténylegesen megfigyelt hatás külön ellenőrzési állapot. A gombnyomásból nem következik automatikusan sikeres védelem. Ezt a követelményt még implementálandó és külön offline, majd felhasználói live próbával igazolandó képességként kell kezelni.

## Elfogadási példák

| Helyzet | Elvárt viselkedés |
|---|---|
| Kevés élet, használható étel a bagben, biztonságos harcon kívüli állapot | Evés és megfigyelt visszatöltés előzi meg az új támadást. |
| Elég élet | Nincs felesleges evés vagy várakozás. |
| Csak főzési alapanyag vagy használhatatlan tárgy van | Nem próbálja ételként fogyasztani. |
| Ismeretlen élet vagy stale inventory | Nem talál ki egészségi állapotot vagy tárgykészletet. |
| Elfogy az étel, de nincs igazolt regenerálódás | Nem könyveli el feltöltődésként; korlátos újraértékelés és pontos ok. |
| Támadás vagy AoE evés közben | A pihenés megszakad; védekezés/kitérés ugyanazon közös vezérlésből. |
| Nincs étel vagy tartós sebzés megakadályozza a pihenést | Nincs végtelen használati ciklus; alternatíva vagy jelzett hiány. |
| Még közepes élet, de ismert közelgő nagy sebzés | A helyzethez megfelelő elérhető defenzív időben mérlegelhető. |
| Aktív védelmi aura, cooldown vagy hiányzó binding | Nincs indokolatlan ismétlés vagy feltételezett aktiválás. |
| Regenerálódás vagy védekezés után folytatás | Friss állapotból, az eredeti feladat és pontos cél megtartásával folytat. |

Ezek tervezett elfogadási feltételek, nem ebben a munkában lefuttatott agenttesztek.
