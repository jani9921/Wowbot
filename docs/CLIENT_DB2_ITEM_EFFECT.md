# DB2 ItemEffect supplement — 2026-10-27

Status: decoded real local files; runtime integration OFFLINE_TESTED. Live quest use NOT_VALIDATED.

The new data/client_supplement.sqlite3 is separate from the existing client_reference.sqlite3 and TDB.
Both original catalogues are opened read-only. The supplement is published atomically only after
source DB2 hash, layout hash, DBD hash, table identity, row count and SQLite integrity checks.
Its schema label is not asserted to be the currently selected live build.

## Actual decoded data

| Table | Rows |
|---|---:|
| ItemEffect | 61797 |
| ItemXItemEffect | 60302 |
| ItemSparse | 175229 |
| SpellMisc | 417635 |
| SpellName | 414027 |
| SpellRange | 222 |
| SpellTargetRestrictions | 48831 |
| AreaTrigger | 3663 |
| AreaTriggerSphere / Box / Cylinder / Disk | 32 / 10 / 35 / 2 |
| AreaTriggerBoundedPlane | 0 |
| ConversationLine | 72912 |

There are zero orphan item-effect links. AreaTriggerPolygon.db2 is absent locally; it was not
invented or marked decoded. Shape-specific records and legacy shape fields remain available as
reference data. Decoded conversation lines/duration are reference data, not conversation-end evidence.

SpellEffect rows for item spells and their reachable triggers are copied into an indexed table from
the existing client catalogue only after checking its stored source hash against the current local
SpellEffect.db2. The trigger search in the runtime reader has depth/node/cycle limits and reports
truncation. Conditions, specialization, difficulty, raw target masks and implicit targets are preserved.

## Runtime path

TDB StartItem / ItemDrop or the current quest special_item → ClientSupplement item profile →
ReferenceKnowledge.items.use_profiles + objective.item_uses → matched QuestModel objective →
existing location/target policies → USE_ON_TARGET / ASSIST → QuestProgressVerifier.

An item is associated with an objective by an exact credit effect (including explicitly represented
trigger edges), an explicit item name in that objective, or the existing live quest-tool classification.
A SourceSpellID is never used as an item ID. Credit proxies are not automatically selected as units.
The existing objective ID/text matcher handles hidden rows; completed objectives retain their counters.

Only TriggerType=0 is an active use candidate. Equip, proc, pickup and learn effects remain diagnostic.
Multiple on-use effects, missing spell data, specialization/PlayerCondition restrictions and unknown
target modes remain explicit. Static target class is not a GUID, current range, usable flag or input binding.

Unit use passes item_id, item_spell_id, target mode and available numeric entity identity to the
existing skill. The skill rechecks the projected item/spell context, active quest, selected recipient,
friendly/hostile constraint and verified action/bag evidence at dispatch. F7 retains its stricter live
exact-item/recipient readiness rule; catalogue data cannot authorize F7 at long range.

Self-use is available through a verified actionbar item after the existing objective locator reports
arrival at its search area. It does not pin or click an unrelated selected unit. Without the supported
arrival/action evidence it is not dispatched.

For navigation estimates, the DB2 maximum range can replace the generic short interaction-distance
guess. The item's current public in_range evidence takes precedence; range/LOS/facing errors still
request the existing approach/replan path. Negative static cooldowns mean inherited/unknown, not ready.
Input acknowledgements, cooldown changes and ITEM_USED never replace objective credit.

Ground, gameobject/item, mixed, area-only and unknown targeting are classified and visible but their
new execution adapters are not implemented here. These modes return an explicit unsupported-mechanic
wait through the shared planner. Scene/conversation completion and AreaTrigger-based ARRIVE integration
remain separate open work; this database export does not claim those acceptance gates.

## Actual reference checks

- Quest 56034: item 170557 → spell 305716, hostile UNIT, 15 yd, 8000 ms reference cooldown.
- Quest 59941: item 178051 → spell 325346, hostile UNIT, 15 yd, 8000 ms reference cooldown.
- Quest 65996: item 193917 → spell 375881, UNIT/ANY, 10 yd. Its server-script heal credit is absent
  from SpellEffect; the existing heal-clause/current special-item path supplies the objective link.

The classifier census uses the same annotate_items association as runtime when a sibling supplement
exists. Runtime can additionally see live special_item and existing enriched subject references, which
an offline census does not have. Neither census mechanism labels nor the number of decoded records is
a count of completed quests.

The full 61511-objective census completed after integration: 713 objectives across 684 quests
have an unambiguous explicit DB2 item association (150 objectives in the latest three expansions).
These counts are associations, not supported targeting modes or completed quests. QUEST_MECHANICS.md
was regenerated with this supplement. The targeted regression work passed 189 distinct tests
(185 in the broad run; a 64-test follow-up included four additional range/arrival tests), including
23 new supplement regressions. Syntax validation passed for all 15 changed Python modules/tools/tests.

## Read-only inspection

From the project root:

    python tools/query_client_catalog.py --item 170557
    python tools/query_client_catalog.py --item 193917
    python tools/query_client_catalog.py --area-trigger 45
    python tools/query_client_catalog.py --conversation-line 1

ClientCatalog(...).supplement.record(table, id) exposes the raw decoded supplement record.
ClientCatalog diagnostics include supplement state and provenance. Missing/invalid catalogues remain explicit.

## Rebuild

The exporter is native/db2_exporter (DBCD 2.3.0; locked dependencies), using pinned WoWDBDefs
revision 12ce70d5fef13370f0edf08889f01c05321d2e28. Run it on the required tables listed in
tools/build_client_supplement.py, plus the existing optional shape files, into a new export directory.
Then:

    python tools/build_client_supplement.py --output <new-supplement.sqlite3> --db2 <local-db2-directory> --decoded <export-directory> --definitions <pinned-dbd-directory> --client-catalog data/client_reference.sqlite3 --definition-revision 12ce70d5fef13370f0edf08889f01c05321d2e28

The builder refuses to overwrite an existing database. Do not silently combine DB2 versions.
