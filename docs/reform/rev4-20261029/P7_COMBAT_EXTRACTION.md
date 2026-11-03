# REV4 P7 — Target/Ability/Facing tényleges kódköltöztetés

2026-10-30. A [megtalált migrációs melléklet](MIGRATION_SUPPLEMENT_REVIEW.md)
M2 csomagjának első konkrét megvalósítása a kijelölt `projekt` mappában.
Nem teljes P7/role/combat-FSM újraírás és nem új élő combat-elfogadás.

## Egyetlen canonical implementáció

| Felelősség | Canonical hely | Kompatibilis régi import |
|---|---|---|
| TargetLifecycle/Policy/Candidate/Manager | `wowbot/combat/target/system.py` | `wowbot.agent.target_manager` |
| AbilityTag/Definition/RuntimeState/Rule/Candidate | `wowbot/combat/ability/contracts.py` | `wowbot.skills.ability_rules` |
| AbilityRuleEngine, cooldown és evaluation | `wowbot/combat/ability/evaluator.py` | `wowbot.skills.ability_rules` |
| Stabil ability metaadat | `wowbot/combat/ability/catalog.py` | `wowbot.skills.combat_ability_catalog` |
| CharacterProfile/CastReference/CombatCandidate | `wowbot/combat/contracts.py` | `wowbot.combat_contracts` |
| CombatArbitrator | `wowbot/combat/arbitrator.py` | `wowbot.combat_contracts` |
| GUID/ID típusok és összevetés | `wowbot/entity_identity.py` | `wowbot.runtime.entity_identity` |
| Finite-number normalizálás | `wowbot/value_helpers.py` | `wowbot.agent.models.number` |
| Tiszta bearing/facing geometria | `wowbot/combat/target/facing.py` | a CombatSkill meglévő módszere delegál |

A régi modulok nem őriznek második class-/függvényimplementációt. Reexportjuk
ugyanaz az objektum; a production CombatSkill, CombatController, SkillRegistry
és a profil-fogyasztók a canonical importot kapják. A controller diagnosztikai
és skill-attempt állapotának teljes további migrációját ez még nem zárja le.

A number és GUID-helper azért került közös, agenttől független modulba, mert
egy `wowbot.runtime` package-import a runtime inicializálásán keresztül az
agent modellekhez vezethetett volna. Az új combat mag ezt sem igényli.

Az eredeti kódot a checkpoint hash-jei ellen ellenőrizve költöztettük, nem új
rotációt terveztünk. A helyi cooldown, rangsorolás, target lifecycle és
GUID-ellenőrzés jelentése megmarad. A facing célazonosítása és adatforrás-
választása a skill határán marad; a core függvény csak pontokból és orientationből
számol szöghibát. Inputparancsot továbbra is a meglévő skill/executor lánc ad.

## Ellenőrzés

A célzott kör **191 pass**. Meglévő ability/target/identity/facing/controller/
cooldown és architecture regressziók, plusz:

- a régi és új exportok objektumazonossága;
- régi kompatibilitási modulokban nincs class-/függvénydefiníció;
- AST-kapu: a combat mag nem importál agent/skills/navigation/vision/input kódot;
- külön Python-folyamatban az ilyen importok tiltottak, a valódi evaluator,
  target lifecycle, GUID-ellenőrzés és facing számítás így is működik;
- fordulási irány, wrap, hiányzó/nonfinite input és változatlan selected-GUID kapu;
- production konstruktorok ténylegesen a canonical osztályt használják.

A végső kijelölt regresszió **3934 passed, 2 skipped, 10 változatlan deselection,
320 modul, exit 0**, pytest 184.66 s / runner 187.31 s. Mind az 549 source és
629 test Python-fájl AST-je érvényes; a teljes 628 testmodulból a kijelölt 320
futott. Ez nem teljes repository-tesztfuttatási állítás.

Külön AST-összehasonlítás **27 költöztetett deklaráció** törzsét a baseline-nal
azonosnak igazolja; kizárólag az evaluator lazy arbitrator-importjának útját
normalizálja. A másolt migrációs melléklet eredeti byte-hash-e szintén egyezik.

[Forrás/diff/parancs/JUnit checkpoint](combat-extraction-evidence/verification.json).
Mind a 203 számozott coverage-sor és a korábbi checkpointok megmaradnak.

## Ami továbbra is hátravan

A nagy CombatSkill FSM/recovery/rotation bontása, movement/CC/hazard jelöltek
közös arbitrálása, teljesebb cast/channel/aura/talent adatút és a használt solo
profil lezárása. Minden class/spec/tank/healer/PvP nem lett ettől kész.
A melléklet Travel/Quest további bontásai külön kapuk; package létrehozása
önmagában nem jelenti ezek teljesítését.

Addon és pinned Ymir byte-változatlan; nem indult játék/capture/FULL_AI,
nem ment kliensinput és nem módosult éles memóriaadatbázis.
