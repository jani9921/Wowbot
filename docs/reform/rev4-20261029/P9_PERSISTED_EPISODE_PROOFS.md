# REV4 P9 — tartós bizonyítékhoz kötött epizód-promóció

2026-10-30, kijelölt `projekt`. Offline tesztelt javítás a meglévő közös
EpisodeMemory / AgentMemory / verifier láncban. Nem teljes történeti
memory/TDB-lineage migráció és nem új élő elfogadás.

## A ténylegesen javított rés

A korábbi `EVIDENCE_LINKED_V1` kapu ellenőrizte a verifier-, action-, baseline-
és observed-azonosítók jelenlétét, de ezekhez nem követelt meg ténylegesen
elmentett bizonyítékot. Más observation ID-val újracsomagolt közös eredet is
növelhette a sikerszámlálót. A hasonló minták keresése a tárolt környezeti
verziót sem egyeztette következetesen az aktuálissal.

Az új `EVIDENCE_MANIFEST_V2` promóció:

- a már létező evidence_manifests táblából, egy bounded, paraméterezett
  lekérdezéssel olvassa vissza a hivatkozott proofokat; az async writer sorát
  az eddigi olvasási barrierrel megvárja;
- mindkét tényleges observationhöz mentett, összekötött evidence kell;
  tetszőleges ID-string, hiányzó rekord vagy sérült JSON nem elég;
- az epizód sessionje, karaktere és buildje egyezik a bizonyíték kontextusával;
  eredeti sample/receipt/expiry idő, epizód- és verifier-idő ellenőrzött;
- bizonytalan/csonkolt/hiányzó forrásgyökér nem igazol újrafelhasználható próbát;
  azonos gyökerű before/after wrapper nem igazol változást;
- a kézi/session-megszakítás és a nem igazolt cél továbbra is kizáró ok.

Az új task_pattern_source_roots tábla a minta és az eredeti forrásgyökér
kapcsolatát ugyanabban a tranzakcióban rögzíti, mint a sikeres próbát.
Ugyanaz a deklarált gyökér új observation ID-val sem számolható újra. Ez akkor
is igaz, amikor a bounded diagnosztikai provenance-listák már elhagyták a régi
azonosítót. Nem a nyers megfigyelési payload kerül az új táblába.

A régi epizódok és minták megmaradnak, nem törlődnek és nem kapnak utólag
kitalált proofot. Az újrahasználó query az új policyt és az aktuális
game-build/addon/UI/dimenzió verziót követeli meg. Ettől egy referencia továbbra
is tervjelölt, nem input-authority vagy friss világállapot.

## Ellenőrzés

A célzott kör **39 pass**: meglévő episode/memory/writer-szegmens regressziók,
valóban mentett before/after megfigyelések, sync/async writer, hiányzó/rosszul
kötött rekord, más session/karakter/build, hibás idő, sérült JSON, azonos
eredet két wrapperben, újracímkézett trial, tartós dedup a diagnosztikai lista
kompaktálása után, régi policy megőrzése és eltérő verzió elutasítása.

A végső kijelölt regresszió **3894 passed, 2 skipped, 10 változatlan deselection,
317 modul, exit 0**, pytest 156.13 s / runner 158.95 s. Mind az 536 source és
626 test Python-fájl AST-je érvényes; a teljes 625 testmodulból a kijelölt 317
futott, ez nem teljes repository-tesztfuttatási állítás.

Az első célzott kör 35 pass volt. A következő parancs egy nem létező régi
tesztfájl nevét is tartalmazta, ezért nem gyűjtött tesztet (exit 4); a javított
parancs eredménye 39 pass. Ez parancslista-hiba volt, nem termékregresszió.
Mindegyik kimenet a checkpointban megmarad.

[Forrás/diff/parancs/JUnit checkpoint](episode-proof-evidence/verification.json).
Mind a 203 számozott coverage-sor és a korábbi checkpointok megmaradnak.

## Határok

A kapu a rendelkezésre álló forrásláncot ellenőrzi; a korábbi, hiányos
TDB/import/retained-replay lineage-t nem rekonstruálja találgatással.
Hiányzó/sérült történeti bizonyíték esetén nincs automatikus promóció.
Nem készült minden lehetséges verifierhez új proof-provider, és a teljes
legacy-forráskivezetés még nincs lezárva.

Nem nyúltunk éles memory-adatbázishoz. A séma bővítése a következő szabályos
AgentMemory-megnyitáskor történik; meglévő tábla/rekord törlése nincs.
Az addon és a pinned Ymir változatlan. Nem indult játék, capture vagy FULL_AI,
nem ment kliensinput, új LIVE_VALIDATED állítás nincs.
