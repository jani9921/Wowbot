# Élő teszt javításai — 2026-10-21, 16:37–16:40

## Állapot

A PID 25416 futás vizsgálata alapján készült általános javítások.
Nincs beégetett quest-, NPC- vagy spell-ID a működési kódban.
A meglévő Planner / ActiveSkillRuntime / CommandDispatcher / verification
lánc maradt az egyetlen végrehajtási út. Az asszisztens nem indított élő
agentet és nem küldött játékbemenetet. Addonmódosítás nem kellett: 0.9.73.

## Feltárt és javított okok

1. **Surveyor's Disc:** megvoltak a helyes képességek a telemetriában,
   mégsem volt hozzájuk nem-harci objective-végrehajtás. A nyitott objective
   címének egyértelmű, pontos egyezése választja ki a friss járműgombot.
   A meglévő VEHICLE_ABILITY kezeli: aktuális spell és binding ellenőrzés,
   egy nyomás, majd az adott objective valódi creditjének ellenőrzése.
   Puszta cast vagy másik objective teljesülése nem elég. Ismeretlen vagy
   többértelmű gombnál várakozás van, nem próbanyomogatás.
2. **Mozgás ülő járműben:** a FAST ág eddig elfogyaszthatta a beszállás
   élét egy földi MOVE részeként. Most átadja a kanonikus feldolgozásnak.
   Helyhez kötött/használati gombsornál nem enged földi MOVE-ot, ugrálós
   RECOVER-t vagy egy korábbi beragadási létra folytatását. Igazolt támadó,
   távolsági vagy dash jármű meglévő vezetési útja megmarad.
3. **Sendrax beszélgetése:** a jó sort kattintotta, de 10 másodperc után
   kudarcnak könyvelte, miközben még tartott a szöveges/scriptelt rész.
   A quest később lett kész. A beszélgetési progressz új alapablaka
   45 másodperc, továbbra is véges határidővel és további input nélkül. GUID-csere nem
   ad jogot új kattintásra. Csak tényleges credit vagy határidő zárja le.
4. **Ablak bezárás–újranyitás:** a lejárt üresablak-időzítő átmaradt a
   következő megnyitásra, és a szerveres leadás megkerülte a korábbi
   vendor-only ismétlésvédelmet. Minden ablak új összeállítási időt kap.
   A több gossip-sor is tartalom. Két igazoltan üres bezárás után ugyanaz
   a GUID legfeljebb 120 másodperces pihenőt kap a szerveres ágakon is;
   új quest/session bizonyíték feloldja. Friss soft-recipient használható
   hozzárendeléshez, ha nincs hard target.
5. **Leadási útvonal nyolcszor megszakad:** a pontos szerveres cél és a
   térképi POI ugyanarra a questre párhuzamosan, azonos prioritással
   jött létre. A POI-változat mindig átadta a helyet a már ismert NPC-nek,
   aztán újra nyert. Ismert szerveres leadónál csak a kanonikus GUID/XYZ
   cél készül; a fallback nem versenyez vele. Hiányzó szerveradatnál a
   korábbi POI-út továbbra is rendelkezésre áll.
6. **Jelöltből nem lesz elküldött F7:** az NPC-javaslat építése már elindította
   a gombnyomási pihenőt, akkor is, ha végül DISMOUNT vagy másik cél nyert.
   A cooldown most csak a tényleges dispatch könyvelésében indul.
   A sikeres soft-interakció könyvelése is a valódi soft GUID-ot használja.
7. **Lassú visszaigazolások:** a beszállást a kliens később jelzi; az első
   no_response helyett rövid, input nélküli várakozás van. A leszállásról
   itt ~3,74 másodperc múlva érkezett friss adat: az ellenőrzési ablak
   5 másodperc, újabb nyomás nélkül. A megtanult rövid időzítés nem veheti
   el ezeket az összeállítási ablakokat. Loading/input-block esetén a
   biztonsági felügyelet marad elsődleges.

## Ellenőrzés

- 26 új, hordozható regressziós eset: csak szintetikus állapot és
  RecordingExecutor / tiszta policy; nem nyitják a felhasználó adatbázisát.
- Tágabb kapcsolódó tesztkör: **1135 sikeres, 2 korábban is hibás**.
  A két vizuális vehicle-aim teszt a változatlan projektben is ugyanúgy
  elbukik (`target_identity_changed`, illetve elmaradó track-rebinding).
  Ezeket nem gyengítettem le; a mostani szerveres Disc-út nem használja őket.
- A valódi felvétel négy állapot-visszajátszása input nélkül sikeres:
  Disc-gombok; Sendrax késői creditje; dupla POI megszűnése; késői leszállás.
- Mind a 450 Python-forrás szintaktikailag rendben; a coverage ledger
  mind a 203 számozott V4/Design sora megmaradt.
- Ez **OFFLINE_TESTED**, nem új élő elfogadási futás, nem FPS-eredmény,
  és nem az egész kódbázis minden hardveres tesztje.

## Bevezetés és következő teszt

Teljes GUI/runtime újraindítás szükséges. A 0.9.73 addon maradhat,
nem kell a korábbi 0.9.69-re visszamásolni. A következő élő tesztet a
felhasználó indítja: beszélgetés kivárása, szerveres leadás, majd a Disc
három művelete; ülés közben nincs földi útvonal vagy beragadás-helyreállítás.

A projekt nem Git-munkapéldány. A módosítás előtti fájlok mentése:
`C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight 1.2/work/live_fixes_20261021_1640/original`.
A források és tesztek elkülönített munkapéldányban készültek; csak az
ellenőrzött eltérések kerülnek vissza, hash-alapú konkurensmódosítás-védelemmel.
Futási adat, kép, bindings-cache és adatbázis nem kerül visszamásolásra.
