# REV4 P7 — harc előtti regenerálódás (túlélés, első szelet)

2026-10-31, Claude. Offline tesztelt. A
[túlélési kiegészítés](input/STATUSZ_ES_TULELES_KIEGESZITES_20261030_HU.md)
„Saját élet, harc előtti regenerálódás, étel” részéből a természetes
regenerálódás készült el. Az étel és a harc közbeni defenzív cooldownok
**nincsenek kész**.

## Saját élet forrása

12.1-ben az addon a `UnitHealth("player")` értékét titkosként olvassa, így a
saját HP a szerveré (Ymir CREATE/VALUES). A VALUES csak változáskor jön, ezért
a teli vagy változatlan HP 2 mp múlva UNKNOWN. Az UNKNOWN soha nem lesz
100 %.

A `survival_planning.own_health_fraction(state)` két forrást fogad el:

- csak friss mezőbizonyítékot (`packet_own_health.selected_fields`
  health + max_health);
- vagy addonértéket, ha annak saját mintaideje 2 mp-en belüli.

## Döntés: `ReadinessPolicy` (planner, harcon kívüli ág)

| Helyzet | Viselkedés |
|---|---|
| HP < 45 % (start) | REST; az új pull visszatartva |
| pihenés közben 45–90 % | tovább pihen (hiszterézis), nincs evés/támadás közti váltogatás |
| ≥ 90 % (befejezés) | READY |
| ≥ 45 % és nem pihen | nincs felesleges pihenés |
| harc / szerver szerint ránk célzó egység / halál | nincs REST; a combat-policy viszi (a megtámadott karakter védelme nincs tiltva) |
| UNKNOWN egy alacsony érték után, újabb bizonyíték nélkül | REST (`unknown_after_low_health`), nincs vak új pull |
| UNKNOWN alacsony érték nélkül | nem blokkol (nem különböztethető meg a teli csíktól; lásd lent) |
| látható kísért egység (escort) | nincs REST, mert elveszítené |
| az előző REST regeneráció nélkül végződött | 30 mp-ig nincs új REST, a quest folytatódik; nincs pihenés/pull ciklus |

Visszatartott új pull:

- harcon kívüli COMBAT;
- `TAB_SERVER_GUID` TARGET;
- `APPROACH_SERVER_KILL_TARGET` MOVE.

A loot, a beszélgetés, az utazás és a leadás marad. A REST prioritása 112:
a loot (120–122) előtte van, a beszélgetés (102–104) és a pull (≈96) mögötte.

## Végrehajtás: `RestSkill` (kanonikus M0)

A REST a többi M0 skill útját járja:

- M0SkillDispatcher;
- SkillExecutor (deferred start);
- ActiveSkillSupervision;
- VerificationEngine (`own_health_regenerated_verified`);
- skill-szerződés (`own_health_regenerated`, 45 s).

A skill **nem ad inputot**. A természetes regenerációhoz nem kell, az üléshez
vagy evéshez pedig igazolt binding vagy bag-UI kellene. A kimenetek:

- SUCCESS: megfigyelt HP a befejezési küszöbön; a gombnyomás vagy az eltelt
  idő nem számít;
- FAILURE: nincs HP-emelkedés 10 mp-en belül (`NO_PROGRESS`,
  `no_health_regeneration`), vagy lejárt a 45 mp-es ablak;
- CANCELLED (`INTERRUPTED`): fenyegetés. Ez preempció, ezért nem kerül a
  quest-hibamemóriába ([P8_LIVE_1028_FOLLOWUP](P8_LIVE_1028_FOLLOWUP.md)).

## Tesztek

`tests/test_pre_pull_regeneration_20261031.py` (10). Esetek:

- a HP forrása, illetve UNKNOWN;
- hiszterézis;
- csak a pullt tartja vissza, a védekezést nem;
- ismeretlen HP alacsony érték után;
- korlátos újrapróba;
- escort;
- a skill SUCCESS / NO_PROGRESS / CANCELLED / halál kimenetei, input nélkül;
- a kanonikus regisztráció;
- planner-integráció: alacsony szerver-HP mellett REST van, és nincs
  kill-approach.

## Nyitott

1. **Étel:** csak a táskában megfigyelt, igazoltan étel itemből lehet. Kell
   hozzá az item identitása, hatása (DB2 Item/ItemSparse/SpellEffect),
   darabszáma, követelményei és használhatósága, valamint aktív binding vagy
   látható bag-UI. Ez még nincs meg, és nem találgatjuk.
2. **Az „ismeretlen HP-ból nincs pull” szabály teljes formája.** Ehhez saját
   HP-bérlet kell, a natív kollekciók mintájára
   ([P3_RETAINED_COLLECTIONS](P3_RETAINED_COLLECTIONS.md)). Az alkalmazott
   progress-tanúnak a saját HP-eseményekre is ki kellene terjednie. Addig a
   teli HP és az adathiány nem különböztethető meg, ezért csak az
   alacsony utáni ismeretlen állapot blokkol.
3. Profil- és ellenfélfüggő küszöbök: most 45/90 %, egységesen.
4. Defenzív cooldownok harc közben (trend, bejövő sebzés, aura): nincs
   megkezdve.
5. Élő igazolás: nincs.
