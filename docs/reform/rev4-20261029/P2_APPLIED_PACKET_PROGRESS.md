# REV4 P2/P3 — valódi decoder-progress és alkalmazási watermark

Későbbi mai korrekció: [élő logból javított MMAP/session regressziók](P2_LIVE_SESSION_NAVMESH_FIXES.md). A lentebbi mérés az akkori történeti checkpoint eredménye.

2026-10-30. Offline tesztelt bekötés a kijelölt `projekt` mappában.
Ez a [kézbesítési sorszám](P2_PACKET_DELIVERY.md) folytatása: különbséget
tesz a megérkezett és a saját collection-reduceren ténylegesen átment adat között.
Nem teljes retained-state/warm-replay vagy quest/inventory consumer parity.

## Forrás és hitelesített helyi üzenet

A Ymir bridge meglévő Python PKT-follower/dekóder útja minden valódi rekord
feldolgozása után tud progress-jelölést adni. Csak ugyanannak a dekódernek
korrelált, igazolt saját world connectionje számít. Más connection, BN-forgalom
vagy puszta timer nem állít új progresszt. A jel legfeljebb félmásodpercenként
megy; az eredeti record timestampet viszi tovább, nem az aktuális faliórát.
Régi PKT-backlog ettől nem lesz friss élő forrás.

Az `aipc.packet-progress.v1` szűk helyi controlséma: selected PID, process
generation, exact build, capture epoch, record number, eredeti timestamp és
dekódolási hibaszámláló. Nincs nyers packet/payload, GUID-lista, auth-/session
anyag vagy személyes szöveg. A meglévő sorszámozott V2 envelope HMAC-ján megy,
a gameplay-allowlist és a packet JSONL recorder felületét nem bővíti.
Bootstrap context nem használhatja gameplay-baseline helyett.

Az inbox csak a legutóbbi kumulatív kontrollt tartja, de az érkezési sorrend
alapján a korábbi szemantikus delták mögött adja át. A controlsor összevonása
nem dobja el a collection-deltákat. V1/unsigned controlséma nem elfogadott.

## Alkalmazási kapu a közös WorldModelben

A RuntimePacketSource felsorolja a két kontroll között átadott saját questlog/
inventory eseményazonosítókat, és az előző átadott progress sorszámát. A közös
reducer csak build/GUID/world ellenőrzés után és a tényleges collection-
redukció határán jelöli alkalmazottnak ezeket. A PACKET_PROGRESS megfigyelés
csak akkor APPLIED, ha mindegyik ellenőrzött, a lánc folytonos és a kiválasztott
session/PID/process/build/epoch/generation egyezik.

Ha a hívó a progresszt egy korábbi delta előtt vagy annak kihagyásával adja
be, UNAPPLIED lesz. Késői alkalmazás és új életjel ezt nem írja utólag át
bizonyított folytonossággá. A szokásos defer-rebuild batch helyes sorrendben
alkalmazott delta → kontroll útja működik. Egy GAP előtti, félretett kontroll
nem építheti fel újra az új generation állapotát.

A `WorldQuery.packet_stream_progress(now)` bounded másolatot ad; nincs
planner-, skill-, input- vagy aktuális world-authorityja. A kontroll nem lesz
`latest` addon observation, nem írja át `last_received`-et, nem ad quest/loot
creditet, és az ObservationIngestion nem írja minden alkalommal SQLite-ba.
Két másodperces forráskorhatár után EXPIRED. Érvénytelen query-idő vagy
eltávolított session-provider esetén UNKNOWN.

## Dekódolási hiba és fájlrotáció

Egy teljesen olvashatatlan UPDATE_OBJECT rekord növeli a dekóder hibaszámlálóját,
és megszünteti a korábban megtanult private-item ownership/fragment kontextust.
A következő igazolt progress a modellben is érvényteleníti a korábbi natív
mezőket: nem marad teljes quest/inventory lista egy esetleg kihagyott változás
után. Sikertelen packet bytejai nem kerülnek a progressba. A számláló nem
csökkenhet ugyanabban a forrásláncban.

A bridge immár a follower tényleges új headerére is új dekódert és capture
epochot hoz létre, és eldobja a régi entity/POI/session replay-cache-t.
Az új fájl továbbra is PID/build/process-élettartam ellenőrzést és saját
login-baseline-t igényel. Ez a Python-follower javítása; a Ymir EXE nem változott.

## Ellenőrzés és hátralévő kapu

A célzott kör **168 pass**: valódi kontrollnormalizálás/HMAC/forwarder/inbox/
adapter/WorldModel, normál és fordított feldolgozási sorrend, kumulatív kontroll,
defer-rebuild, rossz scope/epoch/process/build, elöregedés, dekódolási hibák és
fake followerrel futtatott valódi bridge/dekóder-lánc, fájlrotációval. Egy korai
fake followerből hiányzó snapshot metódus fixture-hibája javítva.

A végső kijelölt regresszió **3956 passed, 2 skipped, 10 változatlan deselection,
321 modul, exit 0**, pytest 169.76 s / runner 172.69 s. Mind az 551 source és
630 test Python-fájl AST-je érvényes; a teljes 629 testmodulból a kijelölt 321
futott. Ez nem teljes repository-tesztfuttatási állítás.
A végső kör az eltávolított provider és hibás query-idő próbáját is tartalmazza.

[Forrás/diff/parancs/JUnit checkpoint](applied-progress-evidence/verification.json).
Mind a 203 számozott coverage-sor és a korábbi checkpointok megmaradnak.

Az APPLIED a helyi, ellenőrzött collection-események alkalmazását jelenti,
nem minden szerveradat megismerését vagy hálózati/capture-veszteségmentességet.
A hiányzó natív baseline-t nem állítja elő, és **egyetlen mező TTL-jét sem
hosszabbítja meg**. A retained collection per-field lifecycle/lease szabálya,
warm snapshotok és teljes canonical questprogress/consumer parity a következő
megvalósítási kapu. A geometria/combat/UI freshness nem kap ebből kivételt.

Nem indult WoW, Ymir, capture vagy FULL_AI; a bridge tesztje fake process-
metadata/follower/UDP függőségeket kapott. Nincs kliensinput, éles memory DB
módosítás vagy új LIVE_VALIDATED állítás. Az addon és a pinned Ymir változatlan.
