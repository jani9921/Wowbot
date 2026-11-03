# REV4 P3 — saját CREATE rekordból származó kezdeti questslotok

2026-10-30. A kijelölt `projekt`; **OFFLINE_TESTED részadatút**.

A natív QuestLog olvasó eddig a saját PlayerData VALUES változásait kezelte.
Belépéskor a teljes slotlista a CREATE rekordban érkezhet; a következő VALUES
csak egyetlen változást tartalmazhat. Most a korrelált saját karakter
UnitData CREATE-jának fennmaradó része is pontosan bejárható a PlayerData
QuestLog-prefixéig. Az adat ugyanabba a WorldModel-tárolóba és read-only querybe
kerül; külön questmodell vagy inputút nem jött létre.

## Prefix és jogosultság

A pinnelt WPP `UpdateFieldsHandler1215` 70340-es családjának mezősorrendje az
alap. Owner/Empath/UnitAll függő mezők, dinamikus spell/effect/channel tömbök,
opcionális assistadat és a PlayerData saját prefixe szerint olvasunk. Nincs
fix bájtugrás az ismeretlen blokkokon át. A tömbök bounded méretűek.

- A selected own GUID-ot továbbra is azonos kapcsolatú, szerverrel igazolt
  login korrelálja. Másik karakter vagy nem igazolt login nem hívja meg az
  új saját prefixolvasót. A támogatott buildcsalád nem bővült találgatással.
- QuestLog CREATE csak explicit PartyMember mezőlefedettségnél olvasható a
  protokoll szerint; hiányzó flag nem jelent üres questlistát.
- Account/guild/duel/pet/assist azonosítók és névbájtok méret szerint átugorva,
  nem jutnak a normalizált eseménybe. Csak a saját GUID/world és numerikus
  questslotok kerülnek az allowlistre.
- Az új `WPP_12_1_QUEST_LOG_REVIEWED_V2` layout és `sample_kind=CREATE` együtt
  engedi a kezdeti slotmintát. A korábbi V1 layout nem állíthat CREATE-baseline-t.
  Mind a 175 teljes, egyedi slot kell; részleges delta nem címkézhető át.
- Csonka/hibás remainder vagy slotkollekció nem ad részleges kezdeti listát.
  A tőle függetlenül érvényes HP/profil-prefix megmaradhat saját bizonyítékként.

## Fogyasztás és határok

A WorldQuery ugyanazt a `quest_log_slots` / `quest_presence` szerződést használja.
A teljes, friss tagság az adott mintában hiányzó QuestID-t ABSENT-ként jelezheti;
lejárt/részleges vagy megszakadt kontextusban ez UNKNOWN. A státusz megőrzi,
hogy CREATE vagy VALUES alapozta meg a listát. Régebbi, sorrenden kívüli teljes
minta nem viszi vissza a baseline óráját. A tárolás nem fiatalítja meg a régi
slotidentitást vagy számlálót.

A jelenlegi konzervatív kétmásodperces slot-/mezőfrissességi kapu megmaradt.
Ez **nem folyamatosan igazolt teljes questállapot**: a megtartott natív állapot
és streamfolytonosság további migrációs feladat. CREATE-tagság nem bizonyít
questfelvételt, teljesítést, leadást vagy UI-objective sorrendet. A későbbi
PlayerData/ActivePlayerData részekből inventory/profil/talent baseline-t ez a
prefix nem állít. Az addont ezek előtt nem karcsúsítjuk.

## Ellenőrzés

Célzott körök: 60, majd a V2/UnitAll/folytonosság-kiegészítéssel 71 pass;
átfedő eredmények. A végső körben a további részleges-CREATE elutasítás is fut.

Végső kijelölt regresszió: **3838 passed, 2 skipped, 10 változatlan deselection,
313 modul, exit 0**, pytest 172.52 s / runner 175.53 s. Az új tesztmodul benne
van; a korábbi kizáráslista nem változott. Ez nem a teljes teszttár zöldségének
vagy élő questteljesítésnek az állítása.

Ellenőrzött: Owner/Empath/UnitAll kombinációk, üres/nemüres dinamikus mezők és
assistnév, csonka lista, hiányzó jogosultsági flag, másik karakter, V1/V2 layout,
részleges delta átminősítésének tiltása, valós helyi IPC → canonical query.

[Forrás-ZIP, diff, hash, parancs és JUnit](own-create-questlog-evidence/verification.json).
Korábbi checkpoint és a 203 számozott requirement-sor megmaradt. Addon/Ymir
byte-változatlan. Nincs asszisztensi játék/capture/FULL_AI indítás vagy input,
és nincs új LIVE_VALIDATED állítás.
