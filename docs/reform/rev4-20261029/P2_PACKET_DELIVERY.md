# REV4 P2/P3 — hitelesített packetkézbesítés folytonossága

2026-10-30, kijelölt `projekt`. Offline tesztelt kiegészítés a meglévő helyi
IPC-hez; nem teljes retained-state/warm-replay implementáció.

## A javított hiány

A korábbi helyi UDP-envelope HMAC-kal hitelesített, selected-PID/session scoped
volt, de nem hordozott küldőoldali kézbesítési sorszámot. Egy kieső delta így
nem feltétlenül látszott. Erre nem lehetett volna hosszú életű, változatlan
quest/inventory-állapotot alapozni.

Az UdpJsonForwarder most `aipc.packet-envelope.v2` borítékot küld. A küldő
véletlen helyi azonosítója és a contextenként növekvő sorszám is a HMAC része.
Ezek nem játék-/auth-adatok és nem szerveres opcode-mezők. A régi V1 pozitív
mintái kompatibilisek maradnak, de UNSEQUENCED státuszuk nem bizonyít teljes
kézbesítést.

Az inbox külön követi a kézbesítési állapotot. Sorszámrés, küldőcsere,
protokollváltás, tényleges mailbox-kiesés és sorban lejáró minta explicit loss.
Normális, azonos mezőre vonatkozó coalescing nem kiesés. Duplikált/késői
datagram nem tekerteti vissza a sorszámot; egy utólag megérkező hiányzó csomag
nem teszi utólag teljessé a korábbi állapotot. A rés sticky a következő
hitelesített runtime contextig. Változatlan context configure nem törli.

## Meglévő authority és helyreállítás

A RuntimePacketSource a normál és a gyors movement-lane előtt ellenőrzi a
kézbesítést. Kieséskor a közös SessionContextProvider GAP állapotú lesz és
új packet-baseline-t kér. Egy új addon-frame sem javítja ki a hiányzó
szerveres átmenetet. A meglévő `WorldModel.fresh()` inputkapu azonnal hamis,
a scoped natív queryk pedig a régi quest/készlet/mezőbizonyítékot kizárják.

Az endpoint új bootstrap contextet kap; a már meglévő producer identity-
snapshotja helyreállíthatja az identitást/mapot. Ettől a korábbi questlog és
inventory nem válik ismét ismertté. Baseline nélküli itemdelta nem gyárt új
itemidentitást; új megfelelő saját CREATE helyreállítja a pozitív adatot.
Az addon UI-frissesség és a bindings-authority továbbra is külön követelmény.

Régi, SessionContextProvider nélküli migrációs adapter veszteség után a közös
WorldModellel eldobatja a régi natív mezőket, és megtartja a meglévő aktuális-
entitás snapshot-helyreállítását. Ebből nem állít teljes natív baseline-t vagy
retained-state folytonosságot. A production runtime már a közös providert
konstruálja. Nem került be új inputút vagy capture-folyamatindítás.

## Ellenőrzés és határok

Célzott kör: **138 pass**, tényleges HMAC/byte/inbox/adapter/WorldModel lánccal.
Külön próbák: sorszámmódosítás aláírás nélkül, hibás stamp, 50 mozgás coalescing,
duplikáció, rés/késői csomag, küldőcsere, V1-státusz, overflow/expiry;
gyors és normál lane revokálás; addon nem javítja a rést; identity replay
nem inventory-baseline; új CREATE helyreállít. Nincs kliensinput.

A végső kijelölt regresszió **3908 passed, 2 skipped, 10 változatlan deselection,
318 modul, exit 0**, pytest 173.00 s / runner 175.81 s. Mind az 537 source és
627 test Python-fájl AST-je érvényes. A teljes 626 testmodulból a kijelölt 318
futott; ez nem teljes repository-tesztfuttatási állítás.

A nagy kör először hét legacy backlog-/queue-pressure regressziót talált:
a providert nem használó migrációs ág túl széles tiltást kapott. A közös
WorldModel-field invalidálás megőrzi a régi pozitív snapshot-helyreállítást,
miközben a szigorú ág továbbra is packet-baseline-t követel. A javított célzott
156-os, majd az új overflow-próbával bővített 57-es kör is zöld; átfednek,
nem összeadandók. A legelső új teszt egyik elvárása két külön receipt-időt
hasonlított, ezt a fixture-ben korrigáltuk. Minden tesztkimenet megmarad.

Egy ellenőrző parancs véletlenül kétszer indította ugyanazt a nagy tesztet;
mindkettőt leállítottuk, az összekeveredett kimenet nem eredmény. Külön final,
majd a javítás után külön verified könyvtárban futott az elfogadott ellenőrzés.
Az incident-jegyzék a checkpoint része, játék/capture/input nem volt érintett.

[Forrás/diff/parancs/JUnit checkpoint](packet-delivery-evidence/verification.json).
Mind a 203 számozott coverage-sor és a korábbi checkpointok megmaradnak.

A sorszám a helyi kézbesítést követi, nem bizonyít minden hálózati csomagra
veszteségmentes capture-t. A legutolsó elveszett datagram újabb kézbesítés
nélkül nem észlelhető sorszámrésként. Időkorlátos forráséletjel/progress-proof,
alkalmazott watermark, teljesebb unknown-layout érvénytelenítés és per-field
retained-state követelmény még hátravan. A jelenlegi natív TTL-ek nem lettek
megnövelve; a régi mezők ideje nem íródik át. Teljes native parity nincs késznek
jelölve. A meglévő Ymir/packet worker a felhasználó következő szabályos
újraindításakor tölti be az új Python-kódot; az asszisztens nem indította újra.

Addon és pinned Ymir byte-változatlan. Nem indult WoW, capture vagy FULL_AI,
nem változott éles memory DB, nincs új LIVE_VALIDATED állítás.
