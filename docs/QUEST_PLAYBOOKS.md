# Quest-forgatókönyvek (mechanikánként)

Mechanikai leírások: 2026-10-26; futási bekötés: 2026-10-28. A felhasználó célja: „előre rákészülni az ilyen meg olyan questekre … hogy csak az apró-cseprő
bugokat kelljen javítani, ne mechanikákat átírogatni”.

Minden objective kap egy mechanikát a TDB + kliens-DB2 alapján (`objective['mechanism']`,
`src/wowbot/quests/objective_mechanics.py`). A darabszámok és a lefedettség:
[QUEST_MECHANICS.md](QUEST_MECHANICS.md) (`tools/quest_mechanics_census.py`).
Ez a dokumentum mechanikánként leírja:

- **Felismerés:** statikus jel (TDB/DB2) és élő jel (addon, szerver-csomag).
- **Lépéssor:** mit csinál az agent, milyen sorrendben.
- **Kész-jel:** mi igazolja a sikert. Csak élő bizonyíték számít, szintetikus visszajátszás nem.
- **Buktatók:** amit élőben már láttunk, vagy a statikus adat előre mutat.
- **Ma:** a kezelő és az állapot. ✅ élőben igazolt, 🧪 offline, 🟡 részleges, ⬜ nincs.

Közös szabályok, minden forgatókönyvre:

1. **A szerver mondja meg az igazat.** A pozíció, GUID, flagek, spline és kredit a csomagokból jön, a TDB csak
   tudás.
   - Egy objektum akkor használható, ha az Activate bit be van kapcsolva és a NO_INTERACT bit nincs
     (`go_flags_usable`).
   - Egy NPC kill-célpont akkor, ha nem szolgáltató, vagy a kijelölt célpontunk támadhatónak látszik.
2. **Beszélgetés-kapu.** Sok objektum és esemény csak az NPC-vel való beszélgetés után nyílik meg. Ilyen a battle
   plan asztal, Kavia távcsöve és a Blacktalon-párbaj. Ha a mechanika objektumot vagy harcot vár, de a szerver
   zárva mutatja, előbb az objective NPC-jével kell beszélni.
3. **Kivárás, ha kredit jár érte.**
   - NPC-beszéd: `ObjectiveSpeechHold`.
   - Szkriptelt utazás: `ScriptedRideHold`.
   - Gossip-indította hullám: SCRIPTED_EVENT hold.
   - Csak a nyitott objective-hez kötött eseményt várjuk ki, idegen NPC beszédét nem.
4. **Nincs questenkénti szkript.** Új eset = a forgatókönyv egy jelének bővítése, nem új „agy”.
5. **Egy mérce a célpontokra** (`objective_choice.py`, 2026-10-27). Elsőbbséget kap az, ami közel van és egy szinten
   van, ahová egy szkriptelt utazás letett, és ami egyszeri feladat. A számlálós ölés menet közben teljesül.
   Egy sokkal jobb cél menet közben is átveszi a vezetést.

## Beszélgetési sorok próbája — 2026-10-28

Általános helyzeti próba is van: ha egy még nyitott megérkezési vagy
feloldatlan objective konkrét pontján vagyunk, és ugyanott áll a quest
ismert adója, a közös resolver megszólítási jelöltként engedi át. Nem kell
hozzá „find me” mondat vagy NPC-név az objective-ben. A játékos és az NPC
legfeljebb 10 world yardra lehet a ponttól; ismert magasságnál a szintnek is
egyeznie kell. Többpontos keresési terület, másik objective vagy másik map
nem ilyen bizonyíték. A célpont továbbra is az élő szerveres GUID, az F7
címzettjének pontosan egyeznie kell, és az eredményt a questkredit igazolja.
A kifejezett harci, gyűjtési, tárgyhasználati és szkriptelt várási mechanikák
saját végrehajtója megmarad. Állapot: offline tesztelt, új élő igazolás nélkül.

A helyet megnevező találkozás is kérhet beszélgetést. A „Meet with the caravan”
önmagában nem jelent egy „the caravan” nevű NPC-t. Ha ugyanennek a questnek a
szövege azt mondja, hogy „find me at the caravan”, a szöveg saját questadója
adja a megszólítandó template-jelöltet. A közös conversation resolver ezt a
mai szerveres NPC-khez köti; más spawn régi GUID-ja nem lesz mai címzett.
Mounton előbb leszáll, majd a pontos soft-interact címzettnél F7 következik.
A következő stories objective nem indítja újra ezt a találkozási lépést.
A Toward the City esete offline javítva; a teljes karavánút új élő igazolása
még hátravan (LIVE_VALIDATION.md, 2026-10-28 22:00).

Állapot: **részleges / offline tesztelt**, új élő igazolás még nincs.
A felhasználó újabb utasítása engedi a questhez kötött, pontosan azonosított
NPC közönséges beszélgetési sorainak korlátos kipróbálását.

- Egyedi questjelölés, témakapcsolat vagy bemutatkozós questben a saját névvel
  kezdődő sor elsőbbséget kap. Ha a quest azt mondja, hogy „Speak with me”,
  a TDB egyértelmű questszereplőjének ismert template-változatai kötik a
  megnyitott ablakot a feladathoz. A technikai credit neve eltérhet az NPC-től.
- Egyetlen ilyen beszélgetési sort kipróbál. Több sima sor esetén az
  „I am ready” előnyben van. A vásárlós, fizetős, megerősítős és más questhez
  explicit kötött sor nem lesz találomra választott alternatíva.
- A meglévő skill kattint és kivárja a questállapot visszajelzését. Az ablak
  bezárása vagy megváltozása nem kredit. Kredit nélkül lezárult kattintás után
  másik sor következhet, azonos helyzetben legfeljebb négy külön próba.
- Azonos NPC/GUID, questállapot és menü mellett az újranyitás, sorrendcsere
  és elmozdult kattintási pont nem felejti el a próbát. A közös
  QuestAttemptMemory tárolja, a napló `QUEST_GOSSIP_TRIAL` eseménnyel mutatja.
  Előfeltétel-, identitás- vagy végrehajtási hiba nem bizonyítja a sor
  kreditképtelenségét. Kimerült próbák után explicit diagnózis marad.

Alexstrasza eredeti „I am ready” sorát a felhasználó választotta ki; az nem
agent-validáció. A mentett állapot visszajátszása már a helyes sor kattintását
adja, de új élő teszt kell a végleges kredithez.

## Kódbeli bekötés a meglévő skillekhez — 2026-10-28

A forgatókönyvek típussal ellátott lépései a `src/wowbot/quests/playbooks.py` fájlban vannak.
A mechanikát továbbra is a közös TDB/DB2-osztályozó adja. A
`src/wowbot/agent/quest_playbooks.py` az egyértelmű, még nyitott objective-hez köti a lépéseket.
Az MD emberi leírás; a futás a kódbeli leképezést és a meglévő policyk jelöltjeit használja.

- A terv előnézete a mechanika következő lépéseit és az elvárt visszajelzést mutatja. Így egy CREDIT_OBJECT
  proxy „KILL” sora helyett beszélgetés, megközelítés és OBJECT_USE jelenik meg. A következő lépés
  végrehajtása minden alkalommal új jelölt- és skill-ellenőrzést igényel.
- A közös `QuestAttemptMemory` feljegyzi a sikertelen opciót, GUID-ot, megközelítési pontot/próbát,
  az eredményt és az ugyanazon epizód előző hibás action ID-ját. A másik objective kreditje nem lesz
  ennek az objective-nek a sikere; a sikeres ablaknyitás és a questkredit külön mező.
- A rangsor egy már felajánlott, elérhető alternatívát részesíthet előnyben. Az opcióazonosságban nincs
  frame ID, időbélyeg vagy bbox; a TALK és INTERACT azonos F7-e egy próbafajta. A skill eredeti kulcsa,
  cooldownja és próbálkozási kerete változatlan marad.
- Az igazolt megérkezés után elérhető, ugyanahhoz a feladathoz tartozó használatot a régi LOCATION
  commitment elengedi. A TARGET commitment a saját GUID-ján belül követi az alternatíva rangsorát.
  Másik quest vagy elveszett célazonosság ezzel nem írhatja felül a célt.
- A napló új eseménye `QUEST_PLAYBOOK_TRIAL`, a státuszban a legutóbbi húsz próba
  `quest_playbook_trials` néven látható. A terv jelöltpontozásában a `quest_playbook` mező magyarázza
  a következő opciót. A napló megfigyelt eredményt kapcsol a próbához; ez önmagában nem bizonyít
  kizárólagos okságot, különösen kézi beavatkozás mellett.

Az MD-ben hiányzóként jelzett klasszikus ESCORT, EMOTE, konténerhasználat és ismeretlen kreditforrás
továbbra is hiányzik. A hiányzó kezelő a tervben `HANDLER_MISSING`; abból nem készül kitalált
harci forgatókönyv. Az alternatív repülési leszállópont keresése külön nyitott feladat.

Automatikus, játékinput nélküli forgatókönyvtesztek:
`tests/test_quest_playbook_runtime_20261027.py`. Ezek a kötést, sorrendet, alternatívaválasztást,
GUID-megőrzést, cooldownokat, epizódazonosságot és a kredit elkülönítését ellenőrzik.
27 új forgatókönyveset átment; a kapcsolódó regresszió 1471 passed / 1 skipped / 9 deselected.
A korábbi hibák és kizárások részletei a LIVE_VALIDATION.md 2026-10-28-as bejegyzésében vannak.
**OFFLINE_TESTED / PARTIAL**: az egyes questmechanikák lent jelölt élő lefedettségét ez nem növeli.

---

## KILL, KILL_LABEL, PROGRESS_BAR (rejtett kill-sorok)

- **Felismerés:**
  - A kredit-lény spawnolt vagy KillCredit-forrásai vannak.
  - A proxy kredit („Kill Credit … [DNT]”) mögött valódi lények állnak.
  - Progress barnál a rejtett, leírás nélküli kill-sorok töltik a csíkot.
  - KILL_LABEL: a lények egy címkéhez tartoznak (TWW/Midnight).
- **Lépéssor:**
  1. Szerver-pozíció.
  2. Megközelítés (lerepülés, ha kell).
  3. Tab, GUID-ellenőrzéssel.
  4. Harc.
  5. Loot, ha kell.
  6. Következő legközelebbi célpont, ragadós választással (nem ugrál két mob között).
- **Kész-jel:** objective-számláló a quest-logban, `QUEST_UPDATE_ADD_CREDIT`.
- **Buktatók:**
  - Repülő célpont: 3D-s Tab, 35 yd.
  - Mountról harc előtt le kell szállni.
  - Elit célpontot csak explicit objective esetén támadunk.
  - Barátságos kredit-lény (lásd GOSSIP_ACTOR).
- **Ma:** ✅ KILL. 🟡 PROGRESS_BAR (10-22). 🟡 KILL_LABEL (nincs élő eset).

## COLLECT_* (item-gyűjtés)

- **Felismerés:** `item_sources` a quest-item kapcsolatból; ha az nem ad lényt vagy objektumot, akkor a
  loot-táblák döntenek:
  - **DROP:** lény ejti.
  - **OBJECT:** objektumból jön.
  - **VENDOR:** boltban vehető.
  - **CONTAINER:** egy táska-itemet kell kinyitni.
  - **SPELL:** egy spell hozza létre.
  - **OTHER:** szerver-script adja. Ezek többnyire rejtett sorok.
- **Lépéssor:**
  - **DROP:** a KILL-forgatókönyv, majd szerver-loot (GUID → pozíció → F7).
  - **OBJECT:** OBJECT_USE vagy objektum-loot.
  - **VENDOR:** BUY_VENDOR.
  - **CONTAINER:** a táskában lévő item használata.
  - **OTHER:** a quest többi objective-je vagy beszélgetés hozza, külön teendő nincs.
- **Kész-jel:** az item megjelenik a táskában, és nő az objective-számláló.
- **Buktatók:**
  - A loot-ablakot be kell zárni.
  - Tele táska (S5).
  - Az OTHER-sort nem szabad keresni (zónabejárás a semmiért).
- **Ma:** ✅ DROP. 🟡 OBJECT. 🧪 VENDOR. ⬜ CONTAINER (táska-item használata).

## TALK (beszélgetés) és WITNESS (végignézés, kivárás)

- **Felismerés:**
  - TALKTO típus.
  - „Talk to / Speak with / … consulted / confronted”.
  - A kredit-NPC gossip-flages.
  - „Kill Credit: Talk to X”.
  - WITNESS: „witnessed / observed / listen / leaves”, conversation-szereplő.
- **Lépéssor:**
  1. Az NPC szerver-pozíciója, megközelítés, felé fordulás.
  2. F7 (a soft-interact egyezik).
  3. A quest-hez kötött gossip-sor kiválasztása.
     Kék quest-előtag nélküli beszédsornál az élő sor témája is használható,
     ha a nyitott TALK objective és a TDB questszereplője egyértelműen
     összeköti a sort az adott questtel. Két külön questhez tartozó,
     egyenként egyértelmű témát egymás után intéz; nem kattint végig minden sort.
  4. Ha az NPC beszélni kezd: helyben várunk (legfeljebb 20 s csend, 90 s).
  5. Ha utána objektum nyílik meg: az az első.
- **Kész-jel:** az objective-számláló. A WITNESS-nél a jelenet vagy beszéd végén jön a kredit.
- **Buktatók:**
  - A nyitott ablak alatt a planner korán kilép, ezért a beszédfigyelő külön `observe`-ot kap (10-26 23:06).
  - A gossip után „wrong_quest_ui”, ilyenkor nem szabad ugyanazt az NPC-t ismét megszólítani, ha objektum jön.
  - Az üres vagy haszontalan ablakot 4 s után bezárja.
  - A barátságos elit beszélgetőpartnerre nem vonatkozik a harci elit-vétó;
    ettől még nem válik engedélyezett harci célponttá.
  - Az explicit „Left and Right” mindkét szereplőt megnevezheti. Név szerinti
    keresésnél a „Bazentus” teljes névelem alapján a „Forgemaster Bazentus” is
    jelölt; ehhez az új beszélgetőpartner-keresésben nem kell minden rangot
    kézzel felvenni. A „the Forgemaster” szerep szerinti keresés: a név mellett
    az adott NPC saját TDB `subname`/`TitleAlt` mezője is jelöltet adhat.
  - Több különböző név nem lesz automatikusan ugyanaz az NPC. Az egyértelmű
    questkapcsolat és a jelen lévő szerveres szereplők szűkítenek; a friss GUID,
    numerikus azonosító és tényleges soft-interact címzett marad a végrehajtás
    alapja. A kétértelmű szerepet nem a legközelebbi forgemasterrel oldja meg.
  - Az első kredit után a még nyitott másik beszélgetéshez nem kell kivárni a
    45 s kezelt-NPC tiltást. A külön 4 s F7-korlát továbbra is érvényes.
- **Ma:** ✅ TALK (Fao, Kavia). 🧪 beszéd-kivárás. 🟡 WITNESS (scene/ride hold van, conversation-végjel nincs).
  🧪 2026-10-28: Edress két jelöletlen témája, Left/Right és a címes Bazentus
  szereplőfeloldása offline ellenőrizve. A mostani Kavia-panaszhoz felülvizsgált
  képkocka MANUAL volt; az új javítások élő eredménye még nem igazolt.
  🧪 Az általános névelem- és szerepkeresés kapcsolódó regressziója:
  1737 passed / 1 skipped / 9 korábban dokumentált hiba deselected.

## GOSSIP_ACTOR (beszélj, aztán párbaj)

- **Felismerés:** a kredit KillCredit-forrásai barátságos gossip-NPC-k („I'm here to test your combat skills.”).
  Élőben `npc_flags & 1`, nem támadható.
- **Lépéssor:**
  1. A legközelebbi partnerhez megy.
  2. F7, majd a gossip-opció kiválasztása.
  3. Ha ő támad, DEFEND. Ha nem, a kijelölt, most már támadható célpontot a kill-vadászat megtámadja.
  4. A partner „megadja magát” (nem hal meg), jön a kredit, majd a következő partner.
- **Kész-jel:** az objective-számláló. Az NPC mondata, pl. „Perhaps I'll best you... next time.”
- **Buktatók:**
  - Hullám-hold nincs; minden párbaj egy partner.
  - Ugyanahhoz a partnerhez ne menjen vissza.
- **Ma:** 🧪 (10-26, Sharp Practice).

## OBJECT_USE, CREDIT_OBJECT, INTERACT (objektum)

- **Felismerés:**
  - GAMEOBJECT típus.
  - A szerver objektumot köt az objective-hez (`quest_objective_id`).
  - Egy GO spellje DB2 KILL_CREDIT-et ad a kreditre (Kavia távcsöve).
  - Igék: open / activate / light / examine / repair / free.
- **Lépéssor:**
  1. Ha az objektum zárva van (NO_INTERACT), előbb az objective NPC-jével kell beszélni.
  2. Odalépés 1,2 yd-re, felé fordulva.
  3. F7 csak akkor, ha más egység nem a kliens interact-célpontja.
  4. A mountról előbb le kell szállni (SPELLCASTER `Data6` = lóhátról nem használható).
- **Kész-jel:** `object_use_credit_verified`, azaz a quest-digest előrehaladása.
- **Buktatók:**
  - Az objektum soft-interactját az addon nem exportálja, ezért a szerver GUID + flagek döntenek.
  - Közeli NPC elveszi az F7-et.
- **Ma:** ✅ (totemek, gubó, battle plans, távcső 10-26). 🟡 INTERACT (szöveg-alapú).

### Használat utáni mozdulat: gyom kihúzása

- **Felismerés:** a látható "Pull ... Weeds" objective pontos tárgyneve,
  a TDB goober és annak DB2 "Pulling Weeds" spellje együtt. A "pull lever"
  vagy egy ellenség behúzása ettől nem lesz hátrálós feladat.
- **Lépéssor:** a szokásos azonosítás/megközelítés/F7, a megfogás kivárása,
  majd ugyanazon OBJECT_USE FSM-ben 0,3 s-os hátráló lépések. A saját friss
  channel spell-ID engedi a húzáshoz szükséges mozgást; más castot nem szakít meg.
- **Ellenőrzés:** a megfelelő objective creditje; a kattintás önmagában kevés.
  Minden lépést járható, azonos szintű rövid navmesh út ellenőriz. Elakadás,
  szél, ismeretlen talaj, identitásvesztés vagy elfogyott keret esetén leáll
  a mozgás, és naplózott újratervezés következik.
- **Állapot:** 🟡 offline tesztelt, élő önálló teljesítés még nincs igazolva.
  Az új csatornázási jelhez az addon frissítése /reload-dal szükséges.

## USE_ITEM és SPELL_CREDIT (item vagy spell a célra)

- **Felismerés:**
  - A kredit-spell forrása nem objektum, spellclick vagy lény, és a questnek van itemje (StartItem, ItemDrop,
    SourceSpell).
  - Igék: used on / placed / thrown / planted.
- **Lépéssor:**
  1. Odamegy a célhoz (lény, pont vagy objektum).
  2. Item-használat: actionbar, Extra Action vagy táska.
  3. Célpontra dobós itemnél célzás.
  4. „Use X on target” esetén nyitó használat, majd harc.
- **Kész-jel:** az objective-számláló.
- **Buktatók:**
  - Talajcélzós item (C6).
  - A cooldown harc közben titkos.
  - Az ItemEffect nem tartalmazza az összes szerver-script célját vagy creditjét. A hiányzó/többértelmű
    kapcsolat ismeretlen marad; a StartItem vagy SourceSpell önmagában nem elég egy célpont kiválasztásához.
- **Ma (2026-10-27):** ItemXItemEffect → ItemEffect → SpellEffect/trigger és SpellMisc/SpellRange
  dekódolva a `data/client_supplement.sqlite3` fájlba. A questhez kapcsolt item profilja a közös
  ReferenceKnowledge → QuestModel → USE_ON_TARGET/ASSIST útvonalra kerül. Az egyértelmű unit-célzás
  és az objective-terület elérése utáni, actionbaros self-use offline tesztelt; a talaj-, object/item-,
  vegyes és ismeretlen célzás végrehajtó adaptere nyitott, ezek nem válnak találgatott unit-használattá.
  A siker továbbra is az eredeti objective számlálójának változása; élő teszt még szükséges.

## SPELLCLICK, SPELLCLICK_VEHICLE, VEHICLE_ABILITY, MOUNT (jármű)

- **Felismerés:**
  - `npc_spellclick_spells` a szereplőn; ha `VehicleId` is van, jármű.
  - Ha a kredit-spellt egy lény vagy jármű spellje adja: VEHICLE_ABILITY.
  - „Kill Credit: Ride …”: RIDE vagy MOUNT.
- **Lépéssor:**
  1. F7 (spellclick).
  2. Járműben a DB2 SpellEffect alakja szerint gombokat használ (dash, ráközelítős, missile).
  3. Pitch-kormányzás.
  4. Visszaszáll, ha kiesett.
  5. Kiszáll, ha kész.
- **Kész-jel:** az objective-számláló; a jármű-állapot megszűnése.
- **Buktatók:**
  - A jármű-sáv `in_range` mindig False.
  - Taxiból vagy szkriptelt utazásból tilos kiszállni.
  - Harcban a mountról le kell szállni.
- **Ma:** ✅ (Giant Boar, Training Wings, harpoon, „Hop on a dragonriding mount”).

## ARRIVE és AREA_TRIGGER (eljutni valahová)

- **Felismerés:**
  - AREATRIGGER típus.
  - „Arrive / Reach / Enter / Travel / Investigate … / discovered”.
  - A quest POI pontja.
- **Lépéssor:**
  1. A POI-ra megy (repül), a cél szintjén (Z) érkezik.
  2. Ha nincs kredit, kis körben bejárja a POI-poligont.
- **Kész-jel:** az objective-számláló. Az area-trigger csak a szerveren él, ezért élő jele nincs, csak a kredit.
- **Buktatók:**
  - Rossz szinten érkezés: `arrived_on_other_level` (10-26).
  - Barlangban vagy beltérben nem szabad repülni.
- **Ma:** 🟡 (POI + zónabejárás; nincs explicit area-trigger cél).

## ESCORT (kísérés, követés, védelem). Három külön forgatókönyv

A TDB-ben a kísérés-szövegű objective-ek három esetre bomlanak:

### E1: társ, aki minket követ

Példák: „Speak to Varastrasza with Zalethgos”, „Fight your way across … with Ysera”.

- **Felismerés:**
  - A szöveg „with <NPC>” / „bring <NPC> to”.
  - Élőben a szerver egy lényt mutat, ami a játékossal együtt mozog (követő). A spline-ja a játékos felé mutat.
- **Lépéssor:** a többi objective-et kell csinálni. A társ magától jön.
  - Csak akkor várunk rá, ha messze maradt (>30 yd).
  - Nem mountolunk vagy repülünk, ha a társ gyalog van és lemaradna.
- **Kész-jel:** a többi objective krediten keresztül.
- **Buktatók:** mount vagy repülés közben a társ eltűnik; a társ meghal.
- **Ma:** 🟡 (`follower_ready` kezeli a követő megszólítását). ⬜ mount-tiltás társ mellett.

### E2: klasszikus kísérés (mi követjük az NPC-t)

Példa: „Escort Nadia safely from the cave”.

- **Felismerés:**
  - „escort / keep … safe”.
  - Az indító gossip („I'm ready”).
  - Élőben az NPC monster-move spline-on halad, és beszél („Follow me”, „Stay close”).
- **Lépéssor:**
  1. A gossip-indítás.
  2. Az NPC követése 5–15 yd-en belül (a spline végpontja felé).
  3. Az NPC-t támadó mobok megölése (DEFEND az NPC körül).
  4. Nem kalandozunk el (zónabejárás tiltva, amíg a kísérés tart).
- **Kész-jel:** kredit az út végén. Hiba: `quest failed` (az NPC meghalt), ilyenkor újrafelvétel és újrakezdés.
- **Buktatók:** az NPC bevárja a játékost; a túl gyors (mountos) követés; a mobok az NPC-t támadják, nem minket.
- **Ma (2026-10-28):** 🟡 offline. `agent/escort_planning.EscortPolicy`:
  - az alany a tőlünk idézett, az objective által megnevezett entry (TDB `escort_creatures`);
  - 12 yd felett követő MOVE, közel WAIT_EVENT-tartás, kilátásból vissza az utolsó helyre.
  - Élő eset: Black Wagon Flight 65793, 12:05 (az ágens a célhoz repült, 59 percet várt).
  - A 15:38-as felhasználói futásban a követés és a közbejött harcok már
    látszanak, a leadás rossz emeleten állt meg. A follow-up offline javításban
    a normál tartás/újraellenőrzés és a combat yield CANCELLED, nem FAILURE;
    aktív saját kísérés mellett a más questhez tartó MOVE sem előzheti meg.
    Combat/loot továbbra is a közös végrehajtóval működik. A teljes quest és
    a fenti leadás új élő igazolása még hiányzik; részletek: LIVE_VALIDATION.md.
  - Hiányzik még:
    - az alany támadóinak célzása;
    - quest-failed figyelés;
    - újraindítás utáni kiindulópont.
- **Korábbi állapot:** ⬜. Kellett hozzá:
  - kísérés-állapot (melyik GUID-ot kísérjük);
  - követő MOVE a spline-ra;
  - DEFEND, amely az NPC támadóit is célozza;
  - quest-failed figyelés.
  - Ez a következő nagyobb építési lépés (AGENT_MILESTONES Q2).

### E3: hely vagy tárgy védése

Példák: „Runestone defended”, „Guardians activated”.

- **Felismerés:** „defend / protect / survive / … defended”, progress bar.
- **Lépéssor:** a helyszínen maradunk, és megöljük a hullámokat (SCRIPTED_EVENT hold, 45 s csend = vége).
- **Kész-jel:** a progress bar vagy a számláló.
- **Ma:** 🟡 (SCRIPTED_EVENT hold, Meredy 10-20).

## NPC_TRANSPORT (beszélj, és elvisz)

Felhasználó, 2026-10-27: „ha visszamenne Wrathionhoz, ő is felvinné az arbalest mellé … lehet, hogy lesz még ilyen
quest, ahol az NPC-vel mindig kell beszélni, és ő elvisz valahova, ott csinálni kell valamit, utána megint beszélni
vele, megint elvisz valahova.”

- **Felismerés:**
  - gossip-opció („Take me to…”, „I'm ready”, „Fly me…”), utána jármű, scene, taxi vagy `NEW_WORLD`;
  - a TDB-ben az NPC gossipja egy spellt vagy jármű-spellclicket indít;
  - élőben a leszállás után a quest-cél a leszállópont közelében van.
- **Lépéssor:**
  - Ha a cél messze van vagy nehéz megközelíteni (más szint, híd, fal), és az NPC elvisz oda: beszélgetés, majd
    utazás (ScriptedRideHold).
  - A leszállás után az ottani célpont elsőbbséget kap (`objective_choice` placed-here bonus).
  - Ha végzett, vissza az NPC-hez, és jöhet a következő kör.
- **Kész-jel:** az ottani objective krediten.
- **Ma:**
  - 🟡 A leszállás utáni elsőbbség és a szkriptelt utazás kivárása megvan.
  - ⬜ Nincs „utazás vagy saját út” költség-összevetés: az utazós NPC nem szerepel jelöltként.

## EMOTE

- **Felismerés:** „Dance Party Started”, „/cheer”, „salute”.
- **Lépéssor:** az NPC kijelölése, majd a `/emote` parancs. Ehhez chat-input kell: biztonságos makró-gomb az
  addonból, a felhasználó bindeli.
- **Ma:** ⬜ (AGENT_MILESTONES Q5).

## CRITERIA_TREE, PROXY_UNKNOWN, SPELL_CREDIT (ismeretlen forrás): általános forgatókönyv

Ezek szerver-scriptek („Prey”, „photo taken”, „riddle complete”, „Complete the events of …”). Statikus adatból nem
lehet kitalálni őket, ezért az általános élő lánc dolgozik:

1. Quest POI és a megnevezett NPC/objektum (TDB).
2. Élő jelek:
   - quest-giver jel;
   - objective-hez kötött objektum (`quest_objective_id`);
   - nyitott objektum (`go_flags_usable`);
   - gossip-opció a quest nevével;
   - NPC-beszéd;
   - vignette.
3. Ha mindez hiányzik: zónabejárás a POI-n, majd a helyi LLM-értelmező a quest szövegére (komplex questek).
4. Ha semmi nem segít: rövid WAIT és jelentés a futás-riportban (A1/A4). Ilyenkor a felhasználónak szólni kell, nem
   végtelen ciklusba futni.

**Ma:** 🟡. A lánc megvan, de nincs „feladom és jelzem” végpont.

## Nem tervezett most

PET_BATTLE, PVP (a BG külön lépcső, P1), RESOURCE (más munkából jön), LEARN_SPELL (tréner, S7).

---

## Építési sorrend (a census szerint, a legutóbbi három kiegészítőben)

1. **E2 klasszikus kísérés** + **E1 mount-tiltás társ mellett.** Kevés darab, de ha nincs kezelve, a quest
   elbukik (failed), tehát ez akasztja meg a láncot.
2. **USE_ITEM:** az ItemEffect dekódolása és a unit/self bekötés offline elkészült; következő lépés
   az élő validáció, a talaj/object célzási adapter és a script-only item–objective kapcsolatok feloldása.
   A korábbi objective-darabszám nem megoldott vagy élőben teljesített questek száma.
3. **ARRIVE / AREA_TRIGGER:** a cél szintje és a POI-poligon bejárása. Kb. 940 objective.
4. **WITNESS:** a conversation és a scene végének jele csomagból. Kb. 180 objective.
5. **COLLECT_CONTAINER, EMOTE:** kicsi, gyors nyereség.
6. **Az általános forgatókönyv végpontja:** „nem tudom, szólok”, a futás-riportban.
