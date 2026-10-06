# Képességterületi előrehaladás — 2026-10-07

Ez **óvatos becslés**, nem automatikus teszteredmény és nem „elkészült”
minősítés. A régi M0–M27 kapuk a fejlesztés történeti kiindulását adják; a
mai állapotot a jelenlegi forrás, a regressziós tesztek és a
[legutóbbi felhasználói élő futások](LIVE_VALIDATION.md) alapján értékeljük.
Egy szintetikus replay nem helyettesít élő elfogadást. A GitHub milestone
saját százaléka külön adat: **lezárt issue-k / összes issue**. Az alábbi
képességbecslést a milestone leírása mutatja; a kettőt nem szabad összekeverni.

## Pontozás

| Bizonyíték | Maximum | Értelmezés |
|---|---:|---|
| Közös architektúrába bekötve | 15 | WorldModel/planner/skill/verification út, nem külön brain |
| Funkcionális lefedettség | 25 | A terület lényeges ciklusai és fail-closed ágai |
| Offline regresszió | 20 | Releváns automata tesztek/replayek; részleges bukások levonva |
| Élő komponensbizonyíték | 20 | A felhasználó által futtatott kliensben tényleges állapotváltozás |
| Önálló end-to-end élő elfogadás | 20 | Reprezentatív teljes ciklus kézi rásegítés nélkül |

A részpontok 5-ös lépésekben becslések. A legutolsó oszlop minden területen
0, amíg a mai kódon ilyen teljes live kapu nincs igazolva. A 100% csak
az összes szükséges kapu elfogadásával jelenthető ki.

| GitHub domain milestone | Régi kapuk (történeti) | Arch. /15 | Funkció /25 | Offline /20 | Live /20 | End-to-end /20 | Becsült készültség |
|---|---|---:|---:|---:|---:|---:|---:|
| [Questing](https://github.com/jani9921/Wowbot/milestone/1) | M10–M12, M21, M26 | 15 | 15 | 20 | 15 | 0 | **65%** |
| [Herbalism](https://github.com/jani9921/Wowbot/milestone/5) | M22 | 15 | 5 | 10 | 0 | 0 | **30%** |
| [Mining](https://github.com/jani9921/Wowbot/milestone/6) | M22, AGENT-54 | 15 | 5 | 10 | 0 | 0 | **30%** |
| [Fishing](https://github.com/jani9921/Wowbot/milestone/7) | M22, AGENT-55 | 15 | 10 | 10 | 0 | 0 | **35%** |
| [Vision](https://github.com/jani9921/Wowbot/milestone/3) | M2–M4, M17, M19 | 15 | 15 | 20 | 15 | 0 | **65%** |
| [Skills](https://github.com/jani9921/Wowbot/milestone/8) | M13–M14, M21 | 15 | 15 | 20 | 15 | 0 | **65%** |
| [Combat](https://github.com/jani9921/Wowbot/milestone/9) | M23, AGENT-49 | 15 | 10 | 15 | 15 | 0 | **55%** |
| [Navigation](https://github.com/jani9921/Wowbot/milestone/2) | M20, AGENT-48 | 15 | 15 | 20 | 15 | 0 | **65%** |
| [World Model & Memory](https://github.com/jani9921/Wowbot/milestone/10) | M4–M9 | 15 | 15 | 15 | 10 | 0 | **55%** |
| [Runtime & Setup](https://github.com/jani9921/Wowbot/milestone/4) | M1–M2, addon kapuk | 15 | 15 | 15 | 10 | 0 | **55%** |
| [Autonomy & Verification](https://github.com/jani9921/Wowbot/milestone/11) | M12, M14, M26–M27 | 15 | 10 | 15 | 10 | 0 | **50%** |
| [Dungeon/PvE](https://github.com/jani9921/Wowbot/milestone/12) | M24 | 15 | 5 | 10 | 0 | 0 | **30%** |
| [PvP](https://github.com/jani9921/Wowbot/milestone/13) | M25 | 15 | 0 | 10 | 0 | 0 | **25%** |

## Mi támasztja alá, és mi hiányzik?

- **Questing:** a 2026-10-05-i egyórás felhasználói futásban kilenc questet
  leadott; a 2026-10-06-i barlangos quest eljutott 5/5 gubóig, Hrunig és
  Ralia ride creditig. Több lépéshez kézi segítség kellett (például item
  használat és Ralia taxi), az új giver-fix és több object-use ág csak
  offline ellenőrzött. Ez live részleges működés, nem önálló teljesítés.
- **Herbalism / Mining:** a közös ResourceDomain megerősített node-ból
  javasol MOVE és HERB/MINE skillt; verifikált site memória és full-bag
  gate offline tesztelt. Nincs dokumentált élő teljes gather/inventory
  ciklus, ezért nincs live pont.
- **Fishing:** cast → aktív várás → megerősített kapás → GATHER/loot
  állapotút és idegen spellcast kizárása offline tesztelt. Élő kapás és
  inventory-ciklus hiányzik.
- **Vision:** YOLO/World3D, minimap és hover a valós questfutásokban
  működött, de track-ID folytonosság, kis/takart NPC-k, hamis quest-jel és
  kameraelfordulás melletti stabil újrafelismerés nyitott.
- **Skills:** a közös registry és verification út offline széles; a
  gubó OBJECT_USE élőben kreditre vezetett. Az item-use, vendor és
  általános interakció minden ága nem live elfogadott.
- **Combat:** valós pókharcok és Hrun kill igazoltak; GUID-váltás,
  DEFEND-újraindulás, range/rotáció és multi-target továbbra is nyitott.
- **Navigation:** a zone-sweep érkezés, barlangba lejutás és gubó
  megközelítése live működött. Fel/le Z-választás, falnak futás,
  szintenkénti teljes bejárás és kézi segítség nélküli útvonal nincs
  elfogadva.
- **World Model & Memory:** FAST/FULL addon állapot és quest/world state
  ténylegesen táplált élő döntéseket; cross-view identity, tartós memória
  és adatbázis-növekedés korlátai nyitottak.
- **Runtime & Setup:** valós addon/pixelstrip és GPU-s látás futott, de a
  0.9.58 teljes STATE összeállási aránya ~75% volt, és a telepítő
  hardverválasztása/tiszta gépes end-to-end elfogadása hiányzik.
- **Autonomy & Verification:** hosszú, egyórás futásban több quest
  előrehaladt, de a felhasználó többször belenyúlt, és vannak hamis
  negatív/sikertelen ciklusok. Tartós önálló soak/live kapu nincs meg.
- **Dungeon/PvE / PvP:** a közös planner offline domain-proposaljai és
  néhány kapu létezik. Instance/queue/match, group/mechanika és teljes
  élő ciklus egyiknél sincs igazolva.

Források: [MASTER_COVERAGE.md](MASTER_COVERAGE.md),
[LIVE_VALIDATION.md](LIVE_VALIDATION.md),
[KNOWN_ISSUES.md](../KNOWN_ISSUES.md). Százalék csak új bizonyíték vagy
elfogadási kapu változása után módosítható; live tesztet a felhasználó
 indít, az asszisztens a naplót elemzi.
