# REV4 P3 — ismeretlen saját questfrissítés és collection barrier

2026-10-30, kijelölt `projekt`. Offline tesztelt részadatút; teljes retained
quest-progress/consumer-paritás továbbra sincs késznek jelölve.

## Bekötés

Ha a kiválasztott saját karakter PlayerData-frissítésének QuestLog-része nem
olvasható a vizsgált prefix szerint, új `OWN_QUEST_LOG_INVALIDATED` esemény
megy a közös decoder → normalizálás → IPC → WorldModel adatúton. Ez nem új
questtény, hanem az előző teljes állapot használhatóságának elvesztése.

Külön, kizárólag erre engedett `WPP_12_1_QUEST_LOG_INVALIDATION_V1` layout és
70340-es buildcsalád kell. A szűk payload csak saját mover GUID és world map;
nincs továbbított ismeretlen byte vagy személyes szöveg. Másik karakter/map
nem törölheti a saját állapotot. Ismeretlen saját fragment-változás a quest- és
inventory-collectiont is érvényteleníti; részleges CREATE nem állít baseline-t.

A PlayerData maszkból bizonyítottan változatlan QuestLog sem invalidálódik,
sem nem kap új sample-időt: az olvasó ilyenkor a privát, más mezőkhöz tartozó
payload olvasása nélkül visszatér. Root nélküli quest-slot child maszk hibás.

## WorldModel-szabály

Az érvénytelenítés időkorlátot/barriert hagy a scope-hoz tartozó collectionben.
A nála régebbi vagy azonos idejű snapshot/delta nem állítja vissza az elveszett
állapotot. A később megfigyelt részadat pozitív PARTIAL tagságot adhat;
teljes, helyes baseline ismét COMPLETE tagságot adhat.

Későn beérkező invalidálás nem fiatalít és nem töröl indokolatlanul frissebb
mezőket: az invalidálásnál újabb konkrét tények megmaradnak. Az ismeretlenné
vált régi mezők viszont eltűnnek, ezért egyetlen frissebb slot nem menti meg
a teljes régi listát. Az ABSENT bizonyítékhoz továbbra is a teljes friss,
azonos scope-ú collection kell. Az UNKNOWN nem questleadás, abandon vagy
questteljesítés; a kliens/UI QuestModel progress változatlan marad.

Ugyanez a mezőnkénti szabály az inventory root-listában is érvényes. A korábbi
root-ág egyetlen frissebb slot miatt az egész régebbi invalidálást kihagyta;
így a többi régi hely indokolatlanul COMPLETE maradhatott. Most az invalidálás
idejénél régebbi/azonos helyek eltűnnek, és csak az újabb konkrét slotok
maradnak PARTIAL állapotban. Az invalidálásnál frissebb teljes 105 helyes
snapshot viszont továbbra is COMPLETE lehet. Azonos idejű, sorrendben nem
bizonyított visszaállítás konzervatívan UNKNOWN marad.

## Ellenőrzés

Célzott első kör: **106 pass**, szintetikus WPP-byteokkal, hitelesített IPC-vel és
valódi WorldModel/queryval. Külön próba: layout/direction gate, hiányzó prefix,
előző ABSENT elvesztése, régi snapshot elutasítása, friss részadat majd teljes
baseline, mezőnként késői invalidálás, változatlan maszk eredetideje, privát
fragment-tail kihagyása és másik world elutasítása.

Hat korábbi fixture-elvárás az egyetlen diagnosztikai eseményt, illetve a HP-
prefix után közvetlenül következő profilt várta. Ezek most az új explicit
UNKNOWN eseményt is ellenőrzik; a HP/profile értékellenőrzések megmaradtak.
Nem került ki teszt vagy korábbi hibakizárás.
A készlet-root korrekcióval és a profilpróbával bővített célzott kör **138 pass**;
az invalidálásnál frissebb teljes snapshot megőrzése és a régi mezők eldobása
külön teszt. Ezek a körök átfednek, nem összeadandók.

A végső kijelölt regresszió **3916 passed, 2 skipped, 10 változatlan deselection,
319 modul, exit 0**, pytest 141.02 s / runner 143.86 s. Mind az 537 source és
628 test Python-fájl AST-je érvényes; a teljes 627 testmodulból a kijelölt 319
futott, ez nem teljes repository-tesztfuttatási állítás.

Az első célzott kör öt korábbi fixture-elváráson, az első nagy kör a hatodik
profil-fixture eseménylistáján állt meg; az explicit új UNKNOWN esemény most
mindegyikben ellenőrzött. A payload-/HP/profile értékellenőrzések megmaradtak.
A készlet-root teljeslistát tévesen megtartó ága külön viselkedési javítás.

[Forrás/diff/parancs/JUnit checkpoint](quest-invalidation-evidence/verification.json).
Mind a 203 számozott coverage-sor és a korábbi checkpointok megmaradnak.

## Határok

Teljesen olvashatatlan külső UPDATE_OBJECT rekord, teljes natív retained-
baseline/progress witness, alkalmazott watermark és minden objective-kind
canonical progress-projekciója továbbra is nyitott. Ez a javítás az ismert
saját PlayerData/fragment jelzés körében zárja le a régi hamis teljes listát;
nem találgatja a többi packet tartalmát. A natív TTL-ek változatlanok.

Nem indult WoW/Ymir/capture/FULL_AI, nem ment kliensinput. Addon és pinned
Ymir byte-változatlan, éles memory DB nem módosult, új LIVE_VALIDATED nincs.
