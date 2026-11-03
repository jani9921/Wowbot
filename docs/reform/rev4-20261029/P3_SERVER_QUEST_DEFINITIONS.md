# REV4 P3 — szerveres questdefiníció és pontos objective–POI kapcsolat

2026-10-30, Europe/Budapest. A kijelölt `projekt` forrása.

**OFFLINE_TESTED részadatút; a teljes packetes quest-/inventory-paritás továbbra
is PARTIAL.** Ez a kör a korábbi natív slotolvasót egészíti ki tényleges
queststruktúrával, és a meglévő QuestModel/WorldQuery/Planner fogyasztókat köti
hozzá. Nem keletkezett külön quest- vagy inputvezérlő.

## Dekóder és forrás

A pinnelt WowPacketParser 12.1-es QueryHandlerének teljes
`SMSG_QUERY_QUEST_INFO_RESPONSE` rekordját olvassuk. Az opcode mind a 69214-es,
mind a 70340-es táblában `0x650016`; a már explicit ellenőrzött buildcsaládok
érvényesek, tetszőleges új buildhez nincs fallback. A payload saját allowlistje
`WPP_12_1_QUEST_DEFINITION_REVIEWED_V1`.

- Quest ID, publikus questszöveg, típus/flag/reference mezők, start item és
  follow-up hivatkozás; objective-enként globális ID, signed StorageIndex,
  technikai credit ObjectID, típus, mennyiségek, flag/visibility és leírás.
- A feltételes szövegek jelenlétét jelezzük, de nem választunk aktuális
  szöveget ismeretlen PlayerCondition alapján. A portrait név/model nem
  leadó-/felvevő-NPC vagy aktuális GUID bizonyítéka.
- A teljes rekord vége ellenőrzött. Hibás hossz, érvénytelen szám, duplikált
  objective-ID, eltérő külső/belső QuestID, ismeretlen tail vagy rossz irány
  nem eredményez részlegesen megbízható definíciót.
- A szerver `HasData=false` válasza UNAVAILABLE; nem üres, teljesített vagy
  törölt quest. Chat/account/auth/session anyag nincs az allowlisten.

## Egyetlen modell és fogyasztói

A definíciót a QuestModel birtokolja, a WorldQuery másolatot ad róla.
OBSERVED_REFERENCE, nem aktív questtagság, NPC-jelenlét, targetazonosság,
interakciós jog vagy jutalomátvétel. Eredeti sample/receipt idő, observation ID,
layout, capture-korszak és rekord-lineage tartozik hozzá; lekérdezés nem
frissíti az idejét. Legfeljebb 128 definíció, 1800 másodperces referencia-életkor.

A scope a selected PID, process lifetime, session, karakter és build. Világ- vagy
phase-váltás önmagában nem írja át a quest struktúráját. Ismeretlen identitás,
loading vagy stream-GAP alatt a használat szünetel. Igazolt új baseline után a
megmaradt struktúra referencia lehet; ettől a régi progress/POI nem válik ismét
aktuális adattá. Új karakter/session/build/lifetime nem örökli a másik scope-ot.

A UI-objective kapcsolat exact globális ID-ból vagy **egyértelmű, questen belüli
szövegegyezésből** jön létre. Rejtett sorok, üres szöveg, duplikált megnevezés
és explicit eltérő ID esetén nincs kitalált indexkapcsolat. Azonos technikai
objective-et két látható sorhoz sem kötünk. Új/missing/lejárt definíció törli
a korábbi kötést; teljes STATE újraépítés után a megfelelő kötés visszaépül.

Konkrét fogyasztói változások:

1. A questhely-tervező és a QuestExecutionRuntime ugyanazt a read-only
   objective-geometry query portot kapja. Pontos globális ID mellett nem szűrnek
   még a látható sor feltételezett sorszámával is. Az elsőként látszó, de 9-es
   natív objective-indexű célnál a valódi policy már a helyes POI-t adja tovább
   MOVE-jelöltként. A geometry ettől nem lesz objektum-/NPC-azonosság vagy
   közvetlen inpututasítás; a navigáció és arrival verifier kapui megmaradnak.
2. `quest_objective_storage(quest_id, objective_id, now)` exact globális ID →
   StorageIndex → saját friss slotminta összekötést ad. A negatív, túl nagy,
   többértelmű storage vagy hiányzó/lejárt slot UNKNOWN. A minták saját időt és
   bizonyítékot tartanak. Nem írjuk a tárolót UI-sorszámként a QuestModelbe,
   és a szám önmagában nem jelenti az objective vagy a quest sikerét.
3. A közös skill-azonossági kapu használja az új technikai objective-ID-t.
   Aktuális natív kapcsolat mellett egy eltérő régi TDB objective-ID nem
   igazolhatja a szereplőt. A technikai credit ObjectID nem lesz kötelező
   fizikai NPC-/gameobject-ID. UI/server fizikai kapcsolat és normál target
   ellenőrzés továbbra is kell.

## Capture-korszak és két vezérlési ritmus

A korábbi közepes ritmusú szűrés mellett a gyors movement peek is ugyanazt a
capture-korszak ellenőrzést használja. Egy idegen worker eseménye nem módosítja
a flight feedbacket, és nem szoríthatja ki az aktuális worker mintáját a
coalescing tárolóból. Map/remove barriereket is csak saját korszakukon belül
alkalmazunk. A peek nem fogyasztja el a közepes ritmus eseménysorát.

Azonos rekord külön capture-korszakban külön delivery-ID-t kap; a közös
semantic_record_id megmarad. Így az új worker kézbesítése nem vész el a dedupban,
de ugyanaz a forrásrekord nem számít két független bizonyítéknak. A régi,
korszak nélküli események legacy identity-képzése változatlan.

A szerveres questgeometria read-only lekérdezése is elutasítja a folytonossági
generáció előtti állapotot, még a következő projekciós kör előtt.

## Ellenőrzés és checkpoint

A végső kijelölt regresszió **3798 passed, 2 skipped, 10 változatlan deselection,
311 modul, exit 0**. Pytest: 145.91 s; teljes runner: 148.88 s. Mind az 531
forrás- és 620 teszt-Python fájl AST-ellenőrzése sikeres. A két skip hiányzó
opcionális Garrick-detektor / Exile's Reach raster kép. A teljes teszttár
619 testmodulja helyett a korábban kijelölt és újonnan bővített 311 futott.

A célzott körök átfednek, nem összeadható független eredmények:

- 142 pass: epoch/delivery/evidence-root, saját resource/profile, entity/codec.
- 80 pass: új definíció + IPC/QuestModel/helykeresés, natív slotok, POI és gap.
- 33 pass: friss runtime/identity bekötés és mechanic-contract kör.
- 47 pass: a széles körben feltárt kompatibilitás/queue-pressure ágak javítása.

Az első széles futásban 3794 pass mellett négy hibát találtunk. Egy tényleges
projekciós kompatibilitási hiba volt: minimális, QuestModel nélküli modellnél az
új query-projekció nem volt opcionális. Három queue-teszt fixture-e minden
képkockával másik worker-korszakot állított elő, bár egyetlen capture-t modellez;
a fixture a dekódolás előtt közös korszakot kapott. A production epoch-kapu nem
lett lazítva, új exclusion nincs. A hibás futás eredménye is megmarad.

A végső széles futás pontos parancsa, JUnitja, eredménye, a scoped baseline és
aktuális forrás-ZIP, byte-hashek, diff, első hibás futás és a primary WPP
forrásfájlok hash-listája a
[checkpointban](server-quest-definition-evidence/verification.json) található.
Ez kijelölt regresszió, nem a teljes teszttár sikerességének állítása.

## Nyitott kapuk

Teljes saját CREATE → UnitData → PlayerData questlog baseline; minden
objective-típus bit-/conditional-progress és aktuális questállapot paritása;
inventory/container baseline és fogyasztói migráció. A jelenlegi addonadatokat
ezek elkészülte előtt nem töröltük. A follow-up/portrait/giver reference mezők
önmagukban nem tesznek elérhetővé questet vagy aktuálissá szereplőt.

P7 cast interruptibility/hazard/talent és további role-lefedettség, történeti
import-lineage, további mechanic handlerek és élő költségkalibráció sem vált
teljessé ettől a körtől. Mind a 203 számozott coverage-sor megmaradt.

Az asszisztens nem indított játékot, Ymir-t, capture-t vagy FULL_AI-t, és nem
küldött kliensinputot. Az addon 0.9.80 és a pinned Ymir byte-változatlan.
Felhasználói addon-load és új élő működésigazolás továbbra is nyitott.
