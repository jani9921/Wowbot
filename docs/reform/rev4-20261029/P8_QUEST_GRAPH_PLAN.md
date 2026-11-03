# REV4 P8 — quest-mechanika gráf: terv és szeletek

2026-10-31, Claude. A felhasználó kérése: „kezdjed a legelejéről ahogy gondolod”.

## Kiindulás (felmérés)

Ami megvan, az többnyire leíró szerepű.

**Megvan:**

- Mechanika-osztályozó: `quests/objective_mechanics.classify`, TDB + DB2.
- Playbookok: `quests/playbooks.py`, lépéssorok mechanikánként.
- `MechanicResolver` és `QuestExecutionGraph`: lineáris lépéslánc,
  diagnosztika.
- `agent/quest_playbooks.scores_for`: a már elbukott opciót kerüli,
  pontozási torzítással.
- `QuestGraph`: quest- és objective-függőség, readiness.
- `QuestAgenda`: gördülő horizont.

**A döntést valójában szétszórt flow-k hozzák:** `quest_objective_planning`,
`object_interaction_flow`, `entity_objective_flows`, `server_npc_planning`,
`quest_dialog_planning`.

**A legnagyobb hiány** a census szerint ([QUEST_MECHANICS.md](../../QUEST_MECHANICS.md))
az ismeretlen forrású mechanika, friss objective-ekben:

| Mechanika | Friss objective-ek |
|---|---|
| SPELL_CREDIT | 2221 |
| PROXY_UNKNOWN | 1688 |
| COLLECT_OTHER | 1382 |
| CRITERIA_TREE | 793 |
| UNRESOLVED | 150 |

Ezekre nincs kezelő. Odaérés után a planner a „már ott vagy” MOVE-ot
kiszűri, és az általános „Több adat szükséges” WAIT marad. Élő eset
2026-10-31 08:27, 26209 „Murder Was The Case”:

- a credit-NPC-k technikaiak (Furlbrow Murder Info 001–004);
- a valódi alanyok a farm gossip-NPC-i;
- a kapcsolat core-scriptben van, nincs TDB-sor róla.

## Elvek

- Nincs új „agy” és nincs questenkénti szkript. A gráf a meglévő
  skilleket és javaslatokat rendezi.
- A szerver az igazság: pozíció, GUID, flagek, POI, credit. A TDB tudás, a
  kliens-DB2 statikus kiegészítés.
- Minden lépés ellenőrzött kimenetű. Ha nincs kimenet, az próba, nem siker.
- Végtelen WAIT helyett korlátos próbák, utána típusos „kimerült” állapot
  és továbblépés.

## Szeletek

1. **8.1 — Próbalétra az ismeretlen forrású objective-ekre.**
   - A szerveres objective-POI területén korlátosan, sorban:
     1. a helyi gossip-NPC-k egyenkénti megszólítása (MOVE, F7, a
        korlátos gossip-próba);
     2. ha valamelyik megtámad: a meglévő védekezés;
     3. egy NPC csak egyszer.
   - Ha elfogyott: típusos `OBJECTIVE_PROBES_EXHAUSTED`, és a quest
     félreteszi az objective-et, nincs végtelen WAIT.
2. **8.2 — Recovery-élek a playbookokban.**
   - Hibaok alapján explicit következő lépés, például
     `TARGET_NOT_FOUND` → keresés, `OUT_OF_RANGE` → megközelítés,
     „nincs tárgy” → gyűjtés.
   - Ez a mai „kerüld az elbukott opciót” torzítás helyére kerül.
3. **8.3 — Agenda egy helyen.**
   - A több kész vagy aktív quest sorrendje a `QuestAgenda`-ban: zóna,
     távolság, readiness.
   - A mai leadási zóna-szabály (`turnin_order`) ennek az első darabja.
4. **8.4 — Hiányzó kezelők a census sorrendjében.**
   - ESCORT E2;
   - USE_ITEM talaj/objektum-célzás;
   - ARRIVE célpont;
   - WITNESS vége-jel;
   - COLLECT_CONTAINER, EMOTE.
5. **8.5 — Special-case kivezetés.**
   - Leltár a beégetett quest- és helyzetágakról.
   - Mindegyik vagy a gráfba kerül, vagy törlődik.

## 8.1 elkészült (offline tesztelt, 2026-10-31)

`agent/objective_probes.py`, `ObjectiveProbeLadder`. A planner a quest
javaslatai után hívja.

- **Mikor indul.**
  - Aktív, befejezetlen objective, ismeretlen forrású mechanikával.
  - A karakter a szerveres objective-POI 45 yd-es körzetében áll
    (`world.query.quest_objective_pois`). Szerveres POI nélkül nem indul.
  - Harcban, halottként vagy szellemként nem indul.
- **Jelöltek.**
  - Élő, gossip-flages szerveres NPC-k a POI 40 yd-es körzetében.
  - Kizárva: a questadó és a szolgáltató flagesek (vendor, tréner, javító,
    repülőmester stb.), valamint aki éppen minket támad (az a védekezésé).
- **Lépések.**
  - A legközelebbihez MOVE a szerveres pozícióra, utána F7 a pontos
    soft-interact GUID-ra (a meglévő `server_npc_interaction_ready` kapu).
  - NPC-nként 15 s jut, utána a következő jön.
  - A nyitott ablak a `quest_dialog_planning`-ben jogosult lesz a korlátos
    gossip-próbára (`OBJECTIVE_TALK_PROBE`); más NPC ablaka nem.
- **Prioritás:** 60. Minden ismert kezelő megelőzi.
- **Ha minden jelölt elfogyott:** típusos WAIT
  (`objective_probes_exhausted`, a próbált GUID-okkal) az általános „Több
  adat szükséges” helyett.
- **Teszt:** `tests/test_objective_probes_20261031.py` (5).

### Élő tesztek 2026-10-31 09:40 és 09:54 (26209)

A próbalétra nem indult el.

- **Első futás.** A karakter 2–6 yardon belül állt a gossip-csavargók
  mellett, a mechanika jó volt (SPELL_CREDIT). A világállapotban viszont nem
  volt szerveres POI.
- **Második futás.** A diagnosztika már kimondta: `no_server_objective_poi`.
- **Gyökérok.**
  - A szerver loginkor 1–1.5 s-mal a login `NEW_WORLD` előtt küldte a
    POI-kat.
  - A világba lépés a kontextus entity-scope-ját és a
    `continuity_generation`-t is lépteti.
  - Ettől a `packet_continuity.discard_fields` és a projekció minden POI-t
    eldobott.
  - A kliens POI-t csak loginkor és quest-felvételkor kér, így nem jött
    vissza.
- **Javítás (offline).**
  - A POI-k identitás-hatókörűek (`world_packet_reducer._poi_scope`: PID,
    session, karakter, build).
  - Világ-, UI-térkép-, phase- és folytonossági lépés nem törli őket.
  - Ismeretlen kontextusban csak rejtve vannak.
  - Másik identitás alatt továbbra is törlődnek.
  - Az entitások folytonossági takarítása változatlan.
- **Tesztek.**
  - Új: a világba lépést és a folytonossági lépést túléli, másik
    identitásnál törlődik.
  - Módosítva: a `test_field_sources` belső hatókör-alakja.

### Élőben igazolva 2026-10-31 10:4x: 26209 teljesítve és leadva

- **Élőben igazolva.**
  - A próbalétra sorra kikérdezte a csavargókat.
  - A lefizetés megerősítését (addon 0.9.81) elfogadta.
  - A támadókat leverte.
  - 3 credit jött, utána leadás és két követő quest felvétele.
- **Ugyanezen a napon kellett hozzá.**
  - A packet-csatorna javításai:
    - a POI identitás-hatókörű;
    - a POI nem évül 2 s után (az inboxban sem);
    - az elévült pozíció vagy entitás nem kézbesítési rés.
  - Gossip: előbb az ingyenes sor, a fizetős utána.
  - `GOSSIP_CONFIRM`: legfeljebb 100 copper, ismert összeg, NPC gossip-ablakában.
- **Csak offline javítva (élő ellenőrzésre vár, a karakter újrakezdésekor).**
  - A terület-MOVE nem húz vissza a POI közepére.
  - A kliens F7-címzettje, ha ki nem kérdezett jelölt, megszólítható.

Hátravan a 8.1-ből:

- a POI-n lévő használható objektumok próbája;
- a kimerült objective tényleges félretétele az agendában (most csak
  típusos WAIT);
- élő igazolás a 26209-cel.

Élő igazolás: egyik szeletnél sincs még.

## 8.2–8.4 (offline tesztelt, 2026-11-02)

A felhasználó a 8.1-et lezárta („8.1 kész”). Élő igazolás egyik alábbi
szeletnél sincs még.

- **8.2, recovery-élek.**
  - `quests/playbooks.FAILURE_CLASSES` + `RECOVERY_EDGES`: a sikertelen lépés
    oka megnevezi a javító lépést (TARGET_NOT_FOUND → APPROACH,
    OUT_OF_RANGE → APPROACH, nincs tárgy → LOOT/FIGHT/USE_OBJECT,
    nincs kredit → másik alany).
  - `quest_playbooks.scores_for`: a javító lépés +8, más létező
    alternatíva +4, az elbukott opció mínuszt kap. Él nélkül marad a régi +6.
  - Teszt: `tests/test_recovery_edges_20261102.py`.
- **8.3, agenda egy helyen.**
  - A `QuestAgenda` költségében a leadási zóna-szabály (`turnin_order.zone_place`)
    minden kész feladatra érvényes: más zóna a saját/ismeretlen után jön.
  - A próbalétra kimerült objective-e (`ObjectiveProbeLadder.deferred`)
    300 s-ra `DEFERRED_EXHAUSTED`. A quest keresés/MOVE/WAIT javaslatai
    −20-at kapnak, ha van más kész feladat; egyedül megtartja őket.
    Haladásnál a félretétel megszűnik, lejártakor új kör jön.
  - Teszt: `tests/test_agenda_one_place_20261102.py`.
- **8.4, kezelők (részben).**
  - **E2 kísérés:** a kísért egység támadói (unit target mező) kill-célok
    (`escort_planning.escort_attackers`), a harc quest-relevánsnak tekinti
    őket. Elbukott kísérés (addon 0.9.82 `is_failed`): típusos, alacsony
    prioritású WAIT `ABANDON_AND_REACCEPT`-tel; az újrafelvétel adaptere
    hiányzik. Teszt: `tests/test_escort_defend_20261102.py`.
  - **ARRIVE / AREA_TRIGGER:** a kliens AreaTrigger DB2 pontos XYZ-je és
    sugara (`agent/arrival_targets.py`). Forrás: Type-10 objective vagy TDB
    `areatrigger_involvedrelation` (`area_triggers` a referenciában).
    Teszt: `tests/test_arrival_targets_20261102.py`.
  - **WITNESS / beszélgetés:**
    - A szerver Conversation-objektuma (HighGuid 7, ObjectType 13) entitás
      lett. Amíg él, a karakter tart; az eltűnése a vége-jel.
    - Beszélgetés-entry-nként tanulja: CREDIT_AT_END / CREDIT_BEFORE_END /
      NO_CREDIT. Az utóbbi kettőt nem várja meg újra. Első találkozásnál
      legfeljebb 60 s-ot vár.
    - WITNESS objective-nél a megnevezett beszélők sorai is tartják
      (20 s csend = vége).
    - A `LastLineEndTime` (WPP 12.1 ConversationData) dekódolása hátravan:
      egy valódi felvétel kell az ellenőrzéséhez.
    - Teszt: `tests/test_witness_conversation_20261102.py`.
  - **USE_ITEM talaj/célzás: PARKOLVA** (felhasználó, 2026-11-02): a
    végső simításoknál jön vissza, a YOLO modellel és a trackerrel.
  - **COLLECT_CONTAINER:** a quest-tárgy táska-jobbklikkes útja (mint a
    26391 tűzoltónál) nyitja ki a TDB `item_loot_template` konténerét
    (`container_items` a referenciában, addon `has_loot`). Sikernek számít a
    loot-ablak vagy a kredit; a loot-ablakot a közös LOOT lépés üríti.
    Nem kell hozzá addon-gomb (`agent/container_planning.py`).
  - **EMOTE:** addon 0.9.83, egy secure gomb („AIPC: quest emote”, `CLICK
    AIPCEmoteButton:LeftButton`, Bindings.xml).
    - A felhasználó egyszer bindeli. Az addon-mesterprompt „csak szenzor”
      szabályát a felhasználó felülírta (2026-11-02).
    - Harcon kívül az addon a nyitott objective saját emote-szavát teszi a
      gombra: explicit `/cheer`, az első szó, vagy az utolsó kettő közül egy.
      Mind a kliens összes `EMOTEn_CMDm` parancsából választ.
    - Az agent ugyanabban a szövegben újra ellenőrzi a szót, odamegy az NPC-hez
      (TDB entry), Ctrl+Tabbal GUID-ellenőrzötten kijelöli, és `ADDON_ACTION`
      skill-lel megnyomja a gombot. Csak a kredit igazolja
      (`agent/emote_planning.py`).
  - Teszt: `tests/test_emote_container_20261102.py`.
  - **Elbukott quest újrafelvétele:** addon 0.9.84, ugyanaz az AIPC gomb.
    Ha van FAILED quest a logban, az kerül rá (abandon); az agent csak a
    pontosan exportált, még FAILED questre nyomja. Siker: a quest eltűnik a
    logból, utána a közös felvételi folyamat veszi fel újra.
  - **„Nem tudom, szólok”:** `agent/needs_user.NeedsUserLedger`. A típusos
    zsákutcák (kimerült próbák, nem támogatott tárgy-célzás, elbukott
    kísérés) egyszer `OBJECTIVE_NEEDS_USER` journal-eseményt kapnak, és a
    státuszban `needs_user` listában látszanak.
  - **8.1 maradéka:** az NPC-k után a POI szerver által használhatónak
    jelölt (Activate) objektumai, mindegyik egyszer (MOVE, majd F7 a szerveres
    GUID-ra).
  - Teszt: `tests/test_failed_quest_needs_user_20261102.py`, és két új teszt
    a `test_objective_probes_20261031`-ben.
  - **Szándékosan nyitva:**
    - `LastLineEndTime` (beszélgetés-hossz): élő felvétel kell hozzá;
    - talaj-célzás: parkol a végső simításra.
- **8.5 kész:** [P8_5_SPECIAL_CASES.md](P8_5_SPECIAL_CASES.md).
  - Nincs quest-ID-s kódág.
  - A két quest-specifikus adatfájl felülvizsgált referenciaadatként marad.
  - Az ESCORT, EMOTE, COLLECT_CONTAINER és az ismeretlen forrású mechanikák
    playbook-könyvet kaptak; a census lefedettsége frissült.
