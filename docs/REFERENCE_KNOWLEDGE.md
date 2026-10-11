# Primary TDB knowledge and learned corrections — 2026-10-08

Status: incrementally implemented and offline-tested; **not live-validated**.
This supports the existing AutonomousAgent/WorldModel/planner, not a second
quest brain. It does not start FULL_AI or dispatch client input.

## Configuration and storage

Resolution order: explicit constructor path, AIPC_REFERENCE_CATALOG, local
config/reference_catalog.local.json, then data/world_reference.sqlite3.
The local configuration is ignored by Git. This machine selects:

    C:/Users/<user>/Downloads/TDB_full_world_1210.26091_2026_09_09.sqlite3

Restart the GUI/runtime after configuration changes. Keep that file in place
or update the configuration. Runtime status.reference_catalog reports
READY/MISSING/INVALID, path, source filename/hash/version and read-only status.
A missing catalogue does not manufacture facts; existing live sensors and
learned-memory mechanisms remain available.

The source is opened mode=ro with query_only enabled. Raw Trinity WORLD and
the earlier normalized import schema are supported. Neither schema nor
reference rows are rewritten. The separate hotfix SQL is not silently merged
into this WORLD database. The read-only all-table census is in
`audits/tdb-20261008.md` with machine-readable schema/count/build/sample data
in `audits/tdb-20261008.json`: 247 tables, 6,910,565 rows, 23 empty;
`PRAGMA quick_check=ok`. A structural census is not a proof of every row's
current Retail validity.

Learning uses the profile's existing entity_memory.sqlite3, new table
reference_experience: evidence_key (primary key), kind, quest_id, npc_id,
context, observed_at, data (JSON). Existing entity/GUID/visual stores remain.
The agent reads reference plus learned overlay, preserving original data.

## Decision integration

- TDB is the **primary static source** of quest/objective/chain, NPC/GO role,
  spawn, POI, item-source and service candidates. Exact quest IDs distinguish
  Alliance/Horde variants; identical titles do not merge quests. A credit
  creature ID is not automatically an attackable unit or spawn.
- Bounded projections feed the shared WorldModel, WorldQuery, quest graph,
  exact GO objective ID/name, quest semantics, ender filtering, objective and
  giver/ender location planning. There is no second quest brain. Static
  identity, location and eligibility are not live confirmation.
- When the addon objective is missing its type, a uniquely matched TDB
  gameobject objective supplies a reversible `INTERACT` search hypothesis.
  The YOLO box alone never authorizes use. At the cursor, a fresh matching
  object ID wins; if the Retail hover omits that ID, an **exact TDB template
  name** plus the same quest's live mouseover flag or matching tooltip can
  validate it. The `OBJECT_USE` skill rechecks this after its own fresh hover
  before right-clicking. A different explicit object ID always rejects use;
  success still needs quest credit.
- Current quest text wins over static hints. Verified context-matched learned
  enders correct imported/legacy hints. Conflicting explicit ender rows and
  completion text nominate neither NPC.
- An identified live entity or open quest UI still wins. Otherwise the TDB
  objective/role search region precedes generic API waypoints. Its MOVE needs
  map/instance match and navmesh validation; unknown phase, difficulty or
  terrain context is not assumed satisfied. POI polygons yield bounded
  **interior search samples**, never individual-object coordinates or a
  precomputed route. Mixed-build, ambiguous or uncertain-Z geometry is kept
  queryable but cannot authorize navigation. Explicit GO spawn Z can help
  resolve a cave layer, still subject to live perception and verification.
- For the same semantic POI target, the highest absolute `VerifiedBuild`
  survives; equal-build blobs remain separate. `-66384` is a manually edited
  row of client build 66384, not an older negative build. Distinct spawn GUIDs,
  polygon vertices and phase variants are not globally discarded merely
  because another row has a newer build. Raw rows and omitted/superseded
  counts remain inspectable; a build number is provenance, not proof of
  in-game availability.

## Learning rules

- FULL addon snapshots fill unknown quest text and objective descriptions.
- Consistent target/mouseover GUID and NPC ID teach entity identity.
  Exact NPC XYZ requires actual WORLD_YARDS telemetry; player coordinates
  are never substituted for an NPC's position.
- Missing giver/ender relationships require successful verified QUEST_DIALOG,
  a new matching QUEST_ACCEPTED/QUEST_TURNED_IN event and matching
  dialog/target GUID. A click or opened dialog is insufficient.
- A verified action plus matching objective-counter increase teaches the
  observer's search region, not an exact object spawn.
- Actual movement samples are bounded to 1 Hz and 256 points per attempt,
  with plan/action/quest linkage and success/failure. Historical routes are
  recorded, not automatically replayed.
- Context separates character (session fallback), faction when known, map,
  phase and instance. Unknown faction is not guessed. Default queries use
  30-day observations while older history remains stored.
- Two failed attempts at the same hint in the same context suppress that
  hint for its 24-hour failure window; failure does not prove NPC absence.

Quest text and repeated sightings are deduplicated/throttled. Route samples
accumulate in memory until terminal bookkeeping. Writes use EntityMemory's
existing transactions; this is not a claim of fully asynchronous overlay I/O.

## Limits and open gates

Cross-map POI coordinate validation, uncertain/mixed-Z floor resolution,
phase/condition evaluation, comprehensive loot/locale/service semantics,
general hotfix merging, automatic source rewriting, cross-character/faction
consolidation and safe autonomous historical-route reuse remain open.
Existing visual signatures remain connected; no new encoder or guaranteed
camera-turn re-ID is introduced. Projection is bounded to two current NPCs,
30 active and 10 live-available quests; not all stored history or all 247
tables are projected every tick. Other allowlisted records remain queryable.
Live learning, end-to-end completion and long-run latency remain unvalidated.

## Checks

Read-only queries without starting an agent:

    py tools/query_reference.py --quest 58915
    py tools/query_reference.py --quest 55639
    py tools/query_reference.py --npc 162943
    py tools/query_reference.py --services 162943
    py tools/query_reference.py --item 500
    py tools/audit_tdb.py --help

The source file is roughly 655 MB; the selected-database cold startup and
runtime projection need separate measurement on each machine. The prior
1.07-second startup and 5–6 ms first-quest figures were for the earlier
projection, not a guarantee after adding more TDB knowledge. No runtime
benchmark here proves live agent throughput.

Focused TDB/reference suites: 61 passed on 2026-10-08. Broader results and
known legacy assertions are recorded in `LIVE_VALIDATION.md`; this does not
claim a green whole-project suite or a live quest completion.

User-run test after restarting GUI:

1. Confirm READY and the correct database path in reference_catalog.
2. Run a short quest test with selected PID and verified bindings. Note any
   manual intervention; do not infer autonomous success from assisted runs.
3. Inspect exact quest identity, reference_knowledge provenance and actual
   hover/target before interaction.
4. After real acceptance/turn-in, inspect QUEST_ROLE event/GUID evidence;
   no matching event must mean no confirmed role.
5. Confirm current navmesh movement, no polygon waypoint loop, and no
   player-as-NPC coordinate substitution.
6. Restart to verify learned persistence, inspect tick latency, and record
   evidence in LIVE_VALIDATION.md.
