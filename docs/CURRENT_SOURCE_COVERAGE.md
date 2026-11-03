# Current-source coverage ledger

2026-10-30 REV4 P5/P7 canonical entity approaches — **OFFLINE_TESTED / full
migration PARTIAL**. M0 combat/interaction/loot and final LOS now enter typed
shared navigation; server routes require geometry, FAST defers queries to the
same medium owner without another retry/action. Original deadline/goal/GUID
survives; moving entity goals replan without rewriting corridor anchors.
Physical release precedes arrival interaction; explicit handoff preserves only
its owned request. Bounded nested navigation failure details persist. FAST and
medium share one scoped own-Z projection, continuity GAP clears inherited Z;
corpse pose does not imply loot entitlement. Selected regression **4083 passed, 2 skipped, 10 unchanged deselections, 326 modules, exit 0**,
211.81 s pytest; 560 source + 635 tests parse, 203 rows unchanged. Main-query
blocking, dispatch-time source freshness, full provider/domain migration and
live acceptance remain open. Addon/Ymir unchanged, no assistant client input/
capture/live DB writes. [Details](reform/rev4-20261029/P5_DOMAIN_NAVIGATION_HANDOFF.md).

2026-10-30 REV4 P5 own-position acquisition before grounded 3D routing —
**OFFLINE_TESTED / full migration PARTIAL**. A live packet-assisted MMAP
request with unknown own height first proposes the existing bound 0.06 s
turn and awaits real own movement feedback. No route query, forward command
or arrival before that fix; FAST yields planning to the same medium owner.
Original trip/goal/deadline survives; pending budget <=3 s, scope/identity/
input transitions stop it, cancel cannot silently rearm. Bounded proposal/
acquisition/failure details survive controller reset and enter terminal logs.
Selected regression **4057 passed, 2 skipped, 10 unchanged deselections, 325 modules, exit 0**, 176.38 s pytest; 558 source + 634 tests
parse, all 203 rows preserved. Targeted 112 pass and flight/travel 71 pass
overlap. Addon/Ymir unchanged, no assistant client input/capture/live DB writes
or new live acceptance. Direct M0 entity typed routing and full provider/
domain migration remain open. [Details](reform/rev4-20261029/P5_POSITION_BEFORE_ROUTE.md).

2026-10-30 REV4 exact server-pose priority — **OFFLINE_TESTED / full
ownership migration PARTIAL**. Exact scoped server actor XYZ wins over nonempty
addon UnitPosition; numeric Retail addon unit Z remains UNKNOWN. No fabricated
zero layer, selected-target/F7/spell authority unchanged; moving recipient
updates the same reach. Existing own stationary height/probe is preserved,
but pre-route acquisition and M0 typed-route handoff remain separate gaps.
Selected regression: **4029 passed, 2 skipped, 10 unchanged deselections, 324 modules, exit 0**. 203 numbered rows unchanged, addon/Ymir
unchanged, no assistant live input/capture/database writes or live acceptance.
See [pose fix/checkpoint](reform/rev4-20261029/P5_ENTITY_POSE_PRECEDENCE.md).

2026-10-30 REV4 P5/P7 range/facing follow-up — **OFFLINE_TESTED / full
ownership migration PARTIAL**. Mobility opener range no longer becomes the
sustained rotation's approach radius; ranged envelopes remain distinct from
melee defaults and do not permit spells. Three existing entity-pose helpers
have one pure canonical implementation with exact old reexports. Final facing
uses pure source/GUID/map assessment; missing identity/position cannot fall
back to an old request point or silently re-arm a terminal attempt. Bounded
terminal failure geometry/last-command diagnostics persist beyond image-ring
limits. Existing screen-space FaceController is preserved byte-for-byte.
Selected regression: **4015 passed, 2 skipped, 10 unchanged deselections, 324
modules, exit 0**, 163.87 s pytest; 557 source + 633 test Python files parse,
203 rows unchanged. Eleven recorded live facing failures are not all declared
fixed. No assistant live input/capture/database writes, addon/Ymir unchanged.
See [follow-up and checkpoint](reform/rev4-20261029/P7_RANGE_FACING_FOLLOWUP.md).

2026-10-30 REV4 P7 combat range handoff — **OFFLINE_TESTED / remaining combat
and facing gaps PARTIAL**. User trace shows OUT_OF_RANGE only 0.14 s after
combat start while a successful Charge was still moving; fresh melee range
followed ~0.2 s later. A bounded original-cast-time mobility settle prevents
that premature verdict and yields immediately to actual non-movement range.
Selected-position absence now uses the existing exact server actor helper
before the shared NavigationService approach. Identity/map/removal/freshness
gates remain; no retreat to force Charge and no guessed melee range. Selected
regression: **3999 passed, 2 skipped, 10 unchanged deselections, 323 modules,
exit 0**, 229.76 s pytest; 553 source + 632 test Python files parse, 203 numbered
rows unchanged. User's previous run provides live map-0 navmesh and native
session/gap recovery evidence, not post-range-fix quest acceptance. Eleven
facing failures and other recorded errors remain under investigation. Only
read-only SQL was used; no assistant game/capture/input/live DB mutation.
See [range handoff](reform/rev4-20261029/P7_COMBAT_RANGE_HANDOFF.md).

2026-10-30 REV4 live-log regression fixes — **OFFLINE_TESTED / full migration
PARTIAL**. User-operated morning/afternoon runs exposed a valid signed Trinity
maxPolys capacity rejected by the new format gate and realm/instance login
connections split across indices. The exact reviewed capacity is accepted
without relaxing other format checks. Different-connection session binding
requires exact pending login GUID, world/map/order and public ThisIsYou
ActivePlayer CREATE; no guessed connection or private-player probe. Relogin
rotates epoch and drops replay/ownership/progress caches even within one file.
Recorded user capture replay reaches READY and reviewed own fields. Actual
saved-pose native routing on map 0 is READY; the map 2444 start remains outside
the ground mesh with unknown Z. Neither is a completed live quest. Selected
regression: **3984 passed, 2 skipped, 10 unchanged deselections, 322 modules,
exit 0**, 296.70 s pytest; 552 source + 631 test Python files parse, 203 numbered
rows unchanged. No assistant client/capture/FULL_AI/input/live DB actions;
addon/Ymir unchanged. Retained state, full provider parity, large Combat/Travel/
Quest ownership migration and new live acceptance remain open.
See [log fixes and checkpoint](reform/rev4-20261029/P2_LIVE_SESSION_NAVMESH_FIXES.md).

2026-10-30 REV4 P2/P3 applied decoder progress — **OFFLINE_TESTED / retained
state parity PARTIAL**. A strict authenticated local control message reports
actual records on the verified own world connection, preserving capture time.
WorldModel checks that preceding own collection events really passed their
reducers and that the control/application chain matches the active generation.
Out-of-order/skipped reduction is UNAPPLIED, source age expires, and unknown
outer UPDATE_OBJECT decode invalidates native fields without forwarding bytes.
Capture header rotation resets the decoder/epoch and replay caches. Controls
are ephemeral, never gameplay evidence, UI freshness or input authority; no
field TTL is extended. Selected regression: **3956 passed, 2 skipped, 10
unchanged deselections, 321 modules, exit 0**, 169.76 s pytest. All 551 source
and 630 test Python files parse; all 203 numbered rows unchanged. Per-field
retained lifecycle/leases, warm collection baselines and consumer parity remain
code gaps. No game/capture/input/live DB changes/new live acceptance; addon/
Ymir unchanged. See [applied progress checkpoint](reform/rev4-20261029/P2_APPLIED_PACKET_PROGRESS.md).

2026-10-30 REV4 migration supplement / P7 core extraction — **OFFLINE_TESTED /
full responsibility migration PARTIAL**. The missing 747-line migration plan
was received, hash-pinned and preserved separately from the original ZIP.
Its M0-M8 phases are explicitly mapped to P0-P9; package creation alone is not
completion. Target lifecycle/scoring, ability contracts/evaluation/catalog,
character/cast contracts, arbitrator and pure facing now have canonical combat
implementations. Legacy paths re-export identical objects; shared numeric/GUID
primitives no longer require agent/runtime composition. Production consumers
use canonical imports. Isolated subprocess evaluation succeeds with agent,
skills, navigation, vision and input imports blocked; 27 moved declarations
retain their original AST bodies. Selected regression: **3934 passed, 2 skipped,
10 unchanged deselections, 320 modules, exit 0**, 184.66 s pytest. All 549 source
and 629 test Python files parse; all 203 numbered rows unchanged. Full CombatSkill,
Travel/Quest ownership splitting, retained-state/provider parity and role data
remain implementation gaps. No game/capture/input/live DB changes/new live
acceptance; addon/Ymir unchanged. See [extraction](reform/rev4-20261029/P7_COMBAT_EXTRACTION.md)
and [supplement review](reform/rev4-20261029/MIGRATION_SUPPLEMENT_REVIEW.md).

2026-10-30 REV4 P3 own collection invalidation — **OFFLINE_TESTED / native
quest/inventory parity PARTIAL**. Unknown own PlayerData/fragment updates now
emit a narrow, build-specific questlog invalidation. Proven unchanged masks
do not read private fields, rejuvenate clocks or invalidate known membership.
Questlog and inventory-root barriers preserve only newer concrete fields;
one newer slot no longer keeps an entire older collection COMPLETE. Older or
equal-time snapshots cannot revive invalidated fields; newer complete data can
restore membership. UI progress and input authority are unchanged. Selected
regression: **3916 passed, 2 skipped, 10 unchanged deselections, 319 modules,
exit 0**, 141.02 s pytest. All 537 source and 628 test Python files parse;
203 numbered rows unchanged. Outer-record decode loss, retained progress/
applied-watermark and complete consumer parity remain code gaps. No game/
capture/input/live DB changes/new live acceptance; addon/Ymir unchanged. See
[collection invalidation checkpoint](reform/rev4-20261029/P3_QUEST_LOG_INVALIDATION.md).

2026-10-30 REV4 P2/P3 authenticated delivery continuity — **OFFLINE_TESTED /
retained-state parity PARTIAL**. V2 IPC signs the sender/context sequence;
gaps, sender changes, mailbox loss and queued expiry invalidate continuity.
Coalescing and duplicates do not invent loss. The common session provider
requires a packet rebaseline; addon frames cannot repair it, and the existing
input-freshness gate is revoked immediately. Old native query state cannot
survive an identity-only replay. Legacy migration discards native fields but
preserves positive current-entity recovery; V1 remains UNSEQUENCED. No source
TTL was extended and no old sample was restamped. Selected regression:
**3908 passed, 2 skipped, 10 unchanged deselections, 318 modules, exit 0**,
173.00 s pytest. All 537 source and 627 test Python files parse; all 203
numbered rows unchanged. Capture liveness/progress proof, applied watermarks,
full unknown-layout handling and retained collection parity remain code gaps.
No game/capture/input/live DB changes/new live acceptance; addon/Ymir unchanged.
See [delivery checkpoint](reform/rev4-20261029/P2_PACKET_DELIVERY.md).

2026-10-30 REV4 P9 persisted episode proof gate — **OFFLINE_TESTED / full
historical lineage migration PARTIAL**. Pattern promotion now resolves actual
saved manifests through the shared writer/read barrier, checks original
times, session/character/build and linked before/after observations, and rejects
unknown/uncertain origins. Durable per-pattern source-root dedup survives
diagnostic-list compaction; rewrapped shared roots are not independent trials.
Old records persist, but the old V1 policy is not reused; current environment
version must match. Selected regression: **3894 passed, 2 skipped, 10 unchanged
deselections, 317 modules, exit 0**, 156.13 s pytest. All 536 source and 626
test Python files parse; 203 numbered rows unchanged. This does not reconstruct
missing historical TDB/import/replay provenance or complete every provider.
No live DB modification/game/capture/input/new live acceptance; addon/Ymir
unchanged. See [proof gate checkpoint](reform/rev4-20261029/P9_PERSISTED_EPISODE_PROOFS.md).

2026-10-30 REV4 P3 own inventory root VALUES — **OFFLINE_TESTED / full
inventory parity PARTIAL**. Reviewed ActivePlayerData InvSlots masks now
reach the shared decoder/IPC/WorldModel query. Sparse updates merge by slot,
preserving every original source clock and evidence; older whole snapshots
or invalidations cannot erase newer deltas. Unknown prefixes/tails invalidate,
contradictory duplicate item identities suppress usable membership, and a
delta without baseline supplies only positive partial evidence. UI bag-slot,
carried state and input authority remain unchanged. Selected regression:
**3878 passed, 2 skipped, 10 unchanged deselections, 316 modules, exit 0**,
147.57 s pytest. All 536 source and 625 test Python files parse; all 203
numbered rows unchanged. Mixed ActivePlayerData, retained collections,
warm-replay and full consumer parity remain code gaps. No game/capture/input
or new live acceptance; addon/Ymir unchanged. See
[root VALUES checkpoint](reform/rev4-20261029/P3_NATIVE_INVENTORY_ROOTS.md).

2026-10-30 REV4 P3 owned item/container VALUES — **OFFLINE_TESTED / full
inventory parity PARTIAL**. Reviewed V2 delta masks now update quantity,
containment, durability/capacity and changed container GUID slots. Every value
retains its own source clock; unrelated fields cannot rejuvenate it, reordered
different-field updates can apply independently, and older removals cannot
erase newer state. Unknown dynamic/fragment layouts also drop capture ownership
until CREATE. Transient contradictory slot identities are UNKNOWN. Identity
binding and counter evidence/time stay separate; UI bag/action authority is
unchanged. Selected regression: **3866 passed, 2 skipped, 10 unchanged
deselections, 315 modules, exit 0**, 164.24 s pytest. All 536 source and
624 test Python files parse; 203 numbered rows unchanged. Active root VALUES,
carried/client-slot and complete retained-state/consumer parity remain open.
No game/capture/input/new live acceptance; addon/Ymir unchanged. See
[item delta checkpoint](reform/rev4-20261029/P3_NATIVE_INVENTORY_DELTAS.md).

2026-10-30 REV4 P3 native inventory CREATE — **OFFLINE_TESTED / inventory
parity PARTIAL**. Selected-own PlayerData remainder → ActivePlayerData root
GUIDs, owner-verified ItemData count/durability and ContainerData slots now
reach the canonical WorldModel/query. Private/foreign fields are skipped,
unknown deltas invalidate old native samples, reordered CREATE cannot undo a
newer invalidation, and gap/identity scope cannot be reused. A read-only
advisor receives bounded ownership lower bounds and original evidence;
carried location remains UNKNOWN, UI bag/coordinates stay client-owned.
No absence, quest credit or item-use authority is inferred. Selected regression:
**3857 passed, 2 skipped, 10 unchanged deselections, 314 modules, exit 0**,
175.75 s pytest. All 535 source and 623 test Python files parse. All 203
numbered rows unchanged. Addon/Ymir unchanged; no game/capture/input/new live
acceptance. VALUES, carried/client-slot matching, native retained state and
complete consumer parity remain code gaps. See
[native inventory/checkpoint](reform/rev4-20261029/P3_NATIVE_INVENTORY.md).

2026-10-30 REV4 P3 own CREATE quest membership — **OFFLINE_TESTED / full
quest-progress and inventory parity PARTIAL**. Reviewed UnitData remainder and
PlayerData prefix now supply the selected own character's initial 175 QuestLog
slots to the existing canonical owner. Conditional Owner/Empath/UnitAll fields
are consumed by exact layout, account/name data skipped, wrong actors ignored.
V2/sample_kind=CREATE requires all complete slots; V1/partial data cannot claim
a create baseline. Fresh membership can establish absence, never quest success;
two-second sample freshness and continuity gates remain. Selected regression:
**3838 passed, 2 skipped, 10 unchanged deselections, 313 modules, exit 0**,
172.52 s pytest. All 533 source and 622 test Python files parse; all 203
numbered rows remain unchanged. Addon/Ymir unchanged, no client/capture/input,
no new live acceptance. Remaining PlayerData/ActivePlayerData, persistent native
state and progress/inventory parity are not declared complete. See
[own CREATE checkpoint](reform/rev4-20261029/P3_OWN_CREATE_QUESTLOG.md).

2026-10-30 REV4 P1-E binary format follow-up — **OFFLINE_TESTED**.
Python and native MMAP loaders share checked Trinity v16 / Detour v7 map/tile
headers, distinct version fields, bounded parameters and section sizes.
Malformed/truncated/CRC data produces ERROR, unsupported versions produce
VERSION_MISMATCH, missing files remain MISSING_DATA; walking-excluded water is
NO_ROUTE. Cached failures retain their cause, native rejects unknown formats
before DLL loading, and typed WorldGeometry queries retain the status.
Final selected regression: **3815 passed, 2 skipped, 10 unchanged deselections,
312 modules, exit 0**, pytest 135.62 s. All 532 source and 621 test Python files
parse. All 203 numbered rows remain unchanged. This is not full geometry
semantic validation, live route acceptance, or full REV4 completion.
See [format checkpoint and limits](reform/rev4-20261029/P1E_MMAP_FORMATS.md).

2026-10-30 REV4 P3 native quest definitions and P2 epoch lanes —
**OFFLINE_TESTED / full baseline and consumer parity PARTIAL**. The reviewed
whole-record quest query exposes global objective IDs and signed storage fields.
QuestModel owns scoped, bounded observed definitions; exact ID or unique text
binds visible objectives without inferred row order. QuestRuntime and the real
location policy share the read-only objective POI query, selecting exact IDs
before UI ordinals. A storage query joins exact IDs to fresh own slots without
asserting objective completion; technical credit IDs are not physical actors.
Current native objective relations supersede conflicting static credit IDs.
Fast movement peek and medium ingestion share capture-epoch rejection;
coalescing/barriers are epoch-scoped, while replayed common records share one
evidence root. Final selected regression: **3798 passed, 2 skipped,
10 unchanged deselections, 311 modules, exit 0**, 145.91 s pytest time.
All 531 source and 620 test Python files parse; all 203 numbered rows below
are unchanged. No assistant game/capture/input, no new live acceptance.
Addon 0.9.80 and pinned Ymir are unchanged. Full own CREATE-chain, quest progress
parity, inventory/container and other documented gates remain open. See
[definitions and checkpoint](reform/rev4-20261029/P3_SERVER_QUEST_DEFINITIONS.md).

2026-10-30 REV4 P2/P3 native quest slots and continuity — **OFFLINE_TESTED /
complete quest/inventory parity PARTIAL**. Reviewed own PlayerData VALUES masks
now expose 175 quest slots and 24 storage counters through the canonical packet
reducer and read-only WorldQuery. Complete fresh slot membership can prove
absence; partial/stale data cannot. Replacing a slot's QuestID drops the old
counters, field ages remain distinct, UI objective order is not inferred.
Definitions and objective alignment stay UNKNOWN; QuestModel/active objectives
are not overwritten by raw slot indices. Own full CREATE-chain coverage is open.
A reproduced same-epoch GAP/identity-rebaseline bug now invalidates native
baseline/cache/evidence through a separate continuity generation. Immutable trace
and replay deduplication remain. Confirmed events must match the active capture
epoch; a stale worker gets a specific restart status and GUI message, opaque
traffic cannot clear it. Selected regression: **3765 passed, 2 skipped,
10 unchanged deselections, 308 modules, exit 0**, 143.93 s. All 529 source and
617 test Python files parse. No assistant game/capture/input operation, no new
live acceptance. All 203 numbered rows and prior checkpoints are preserved.
See [native questlog and continuity](reform/rev4-20261029/P2_P3_NATIVE_QUESTLOG.md).

2026-10-30 REV4 P3/P4 provider closure — **OFFLINE_TESTED / full parity PARTIAL**.
Own HP CREATE baseline now accompanies VALUES deltas. Selected-own power packets
use a verified 21-row DB2 DisplayModifier reference and resource-type scoped
amount/max evidence. A type change cannot reuse another resource's amount or
maximum. The reviewed own profile prefix supplies numeric race/class/player-class,
level and DisplayPower to the same resolver and CharacterProfile; unknown
specialization/talents/role are not invented. Other player create/values profiles
are not read. State coalescing preserves CREATE and discrete events, and separates
partial field sets. Real PixelSensor/grid/reassembly/buffer/runtime ingestion of
synthetic BGRA STATE/FAST works with detector/tracker imports forbidden; only the
OS pixel source is replaced. This is not live GDI/DXGI or quest acceptance.
Selected regression: **3736 passed, 2 skipped, 10 unchanged deselections,
306 modules, exit 0**; focused overlapping group 92 passed. All 526 source and
615 test Python files parse. The small reference is included by both current
export modes. Addon remains 0.9.80, Ymir hash is unchanged. No assistant game,
capture or input operation. Earlier approximate percentages are superseded by
explicit closed/open gates; all 203 numbered rows below remain unchanged.
See [P3/P4 provider checkpoint](reform/rev4-20261029/P3_PROVIDER_CLOSURE.md).

2026-10-30 REV4 P3 follow-up — selected own-player HP deltas and sample age:
**OFFLINE_TESTED / full field migration PARTIAL**. The existing reviewed
12.1.5 UnitData reader now emits only HP/max-HP for the correlated own login
after server world verification and with known fragment layout. Other players
are not forwarded. Exact PID/session/build/own GUID/map and liveness gates remain.
Fresh packet and addon values share the per-field resolver; newer FAST wins
in the same tick, delayed STATE preserves its health origin, and a field-time
override cannot rejuvenate or repair invalid origin evidence. Complete own
player/questlog/inventory baseline remains UNKNOWN/PARTIAL. Final selected
regression: **3682 passed, 2 skipped, 10 unchanged deselections, 303 modules,
exit 0**. All 522 source and 612 test Python files parse; all 13 new test
modules are included. The optional-latest projection compatibility failure
from the first wider HP run is fixed and included. No assistant client input.
The 203 numbered rows and prior live evidence remain unchanged. See
[P3 own HP and clock boundaries](reform/rev4-20261029/P3_OWN_HEALTH.md).

2026-10-30 REV4 follow-up — Lua 5.1 addon load and packet NPC cast facts:
**OFFLINE_TESTED / full migration PARTIAL; estimated coding progress about 70%**.
The user reported addon 0.9.79 did not load. The snapshot exceeded Lua 5.1's
60-upvalue limit; newer Lua compile tests had missed it. Version 0.9.80 uses
the existing namespace reference, compiles in Lua 5.1/LuaJIT/Lua 5.4, and the
whole TOC load registers /aipc in an input-free Lua 5.1 harness. Four installed
addon files were backed up and replaced; hashes match. User /reload/live proof
is pending. Five reviewed NPC spell opcodes now reach the canonical WorldModel;
exact cast identity/lifecycle is separate from unknown interruptibility and
hazards. Interrupt-log records lacking CastID cannot prove exact-cast success.
Final selected regression: **3669 passed, 2 skipped, 10 unchanged deselections,
302 modules, exit 0**. All 521 source and 611 test Python files parse; all 12
new test modules are included. No assistant game/capture/input operation.
All 203 numbered/historical rows remain unchanged. See
[P7 packet casts and addon failure/fix](reform/rev4-20261029/P7_PACKET_CASTS.md).

2026-10-30 REV4 P1-E–P9 integration: **OFFLINE_TESTED / wider acceptance PARTIAL**.
Typed geometry, independent identity/session baseline, field policies and collection
coverage, a structural SERVER runtime, original-goal Travel lifecycle, estimated
route scores, character/combat arbitration, quest mechanic/target-role contracts,
and scoped async LLM/verified-episode handling are wired into the existing owners.
Final selected regression: **3637 passed, 2 optional-fixture skips, 10 unchanged
deselections, 301 modules, exit 0**. All 519 source and 610 test Python files parse;
both addon packages compile and now carry version 0.9.79-12.1.0 / Interface 120100.
The addon has not been installed into the game. No new live input or acceptance.
Full packet questlog/inventory/own-state parity, enemy cast/hazard/talent providers,
all class/spec/role coverage, historical import lineage and measured calibration
remain explicitly incomplete. Addon fields and legacy detectors were retained.
All 203 numbered/historical coverage rows below are preserved byte-for-byte.
Details and user-live sequence: [P1-E–P9 implementation](reform/rev4-20261029/P1E_P9_IMPLEMENTATION.md).

2026-10-29 REV4 P1-D — shared Evidence and source lineage:
**PARTIAL / OFFLINE_TESTED** for wider P1. Common immutable evidence values
are used by the existing WorldModel, reducer, belief, snapshot and read-only
query paths; legacy Evidence imports/constructor positions remain compatible.
Observed and received times are distinct when a real monotonic sample is
available. Future/invalid records do not become current facts; known-origin
copies do not restart the source lifetime. Packet direction/build/layout and
logical/transport context metadata remain evidence, not input authority.
Shared/overlapping ancestry and same-frame local/cross views count once;
unknown/truncated ancestry cannot manufacture independent support. Completeness
defaults to UNKNOWN; source priority is unchanged. Detailed ancestry stays in
immutable query records with a bounded winner summary in diagnostics.
Forty-nine new cases pass. Final regression: 3543 passed, 2 optional-fixture
skips, 10 unchanged deselections, 290 modules, exit 0. All 502 source and 599
test Python files parse; eight addon files and IPC/parser/navigation owners are
unchanged. Synthetic benchmark adds about 0.43 ms median on the measured small
ingest path; this is not a live FPS claim. No new live input/acceptance.
Persistent/imported lineage, coverage/completeness consumers, per-field source
authority, typed geometry and independent bootstrap remain open. All numbered
and historical coverage below is retained.
Details: docs/reform/rev4-20261029/P1D_EVIDENCE_LINEAGE.md and LIVE_VALIDATION.md.

2026-10-29 REV4 P1-C — navigation query DI and collect-source identity:
**PARTIAL / OFFLINE_TESTED** for wider P1. Six navigation callbacks are no
longer attached to WorldModel. Immutable per-owner query ports serve quest
floor/sweep planning, resurrection and the walk to a flight departure;
Planner/session reset retains its provider. Existing navigation/input owners
remain. The shared collect-source resolver now rejects partial blank-row
ordinal guesses, includes completed counters when checking list alignment,
and preserves exact IDs, unique text and complete multi-item workflows.
Legacy parent-only item identity is explicitly marked as a weaker hint and
cannot authorize SPELLCLICK. The previously open quest-drop ambiguity test
now passes. Thirty new cases pass across two modules. Final regression:
3366 passed, 1 skipped, 10 unchanged deselections, 267 modules, exit 0.
All 500 source and 597 test Python files parse; eight addon files are unchanged.
No new live input/acceptance. Shared Evidence and typed geometry-result
semantics, independent session bootstrap and field authority remain open.
All 203 numbered/historical coverage rows below are preserved.
Details: docs/reform/rev4-20261029/P1C_NAVIGATION_QUERIES.md and LIVE_VALIDATION.md.

2026-10-29 REV4 P1-B — shared logical session/world context:
**PARTIAL / OFFLINE_TESTED** for wider P1. Immutable SessionIdentity,
WorldContext and SessionContext values now connect the existing packet source,
addon-context facade and WorldModel reducer. Pending facts cannot be rebound
across session/phase changes; entity/credit/POI/scene scopes include phase.
UI-map-only changes retain same-world entities. Server map hints are checked
against current context even with no entities or temporarily missing world
fields. Logical validity does not replace IPC nonce, freshness or authority.
The two new modules have 55 passing tests. Final combined regression:
3292 passed, 1 pre-existing failed, 1 skipped, 10 unchanged deselections,
260 modules; 500 source and 595 test Python files parse. The remaining quest
drop ambiguity also fails on the pre-change backup. Localhost UDP passes
outside the sandbox and in the final run; sandbox UDP timeouts were separately
reproduced with the baseline and a minimal socket control. All eight addon
files are unchanged. No new live input/acceptance. Independent session
bootstrap, process/capture/world generations, other query/evidence ports and
field authority remain open. All numbered/historical coverage below is retained.
Details: docs/reform/rev4-20261029/P1B_SESSION_CONTEXT.md and LIVE_VALIDATION.md.

2026-10-29 REV4 P1-A — per-agent TravelCostPort:
**PARTIAL / OFFLINE_TESTED** for the broader P1; the scoped global-oracle
removal is implemented. The composition root injects its own navigation cost
query through quest location/runtime, turn-in/pickup, agenda, vehicle recovery
and contextual NPC/dialog/handoff consumers. Session resets retain the owner;
the query is not serialized into world state. Pure/legacy helpers without a
provider retain their geometric fallback and cannot borrow another agent.
Eleven new isolation tests pass. Final combined regression: 3162 passed,
1 pre-existing failed, 1 skipped, 10 unchanged baseline deselections across
250 modules. The ambiguous blank quest-drop reference test also fails on the
pre-change source backup; it remains open and was not added to exclusions.
All 499 source and 593 test Python files parse. No new live input/validation.
Session/bootstrap, other geometry ports, source authority and P2–P9 remain
unimplemented by this change. Numbered historical coverage is unchanged.
Details: docs/reform/rev4-20261029/P1A_QUERY_ISOLATION.md and LIVE_VALIDATION.md.

2026-10-29 generic flight integration (V4-024/025/026/027; DESIGN-026/027/029/031)
and exact TALK_CREDIT recipients (V4-014/015/017/022/033):
**PARTIAL / OFFLINE_TESTED**. GlobalNavigator now consumes the older lateral
A* / open-sky trip planners through the current geometry and FlightPlan
contracts. NavigationService owns verified departure walking, existing flight
control and final ground approach with one original goal/correlation; a flight
horizon or departure endpoint cannot prove final arrival. Both flight styles,
off-mesh touchdown, cancellation and missing/clipped geometry are covered by
integration tests. The user-run 72429 WAIT exposed a missing numeric talk-credit
kind; exact type-3 NPC relations now enter the shared server-NPC interaction.
Native geometry and saved-state replays are offline evidence. Complete flight
trips, live Maruukai credit and separate Nokhud approach churn remain live-open.
Final combined regression: 2908 passed, 1 skipped, 10 prior baseline exclusions
across 220 modules. All 498 source modules and two new test modules parse.
Detailed results and artifacts are in LIVE_VALIDATION.md. All numbered source
requirements and acceptance-gate statuses below are preserved.

2026-10-29 item-source SPELLCLICK collection (V4-014/015/017/022/033;
DESIGN-037): **PARTIAL / OFFLINE_TESTED**. Exact open item/source relations
plus the live per-GUID server click flag feed the common server-NPC approach,
facing and soft-recipient interaction. Normal drop sources retain kill/loot;
the new item interaction verifies its own objective counter and retires only
verified consumed GUIDs. Completed visible item rows no longer become hidden
object searches for other pending objectives; genuinely hidden sources remain.
The saved post-reed run now proposes the feather creature, plans a native MMAP
route, and passes a simulated arrival/F7/scoped-credit sequence. Live feather
collection is pending. Final regression: 2883 passed, 1 skipped, 10 prior
baseline exclusions across 218 modules; 497 source modules and the new test
module parse. See LIVE_VALIDATION.md and the retained task artifacts. Numbered
requirements and acceptance-gate statuses below are preserved.

2026-10-29 ghost/turn-in/mount retry handoff (V4-017/022/023/025/068;
DESIGN-069/075): **PARTIAL / OFFLINE_TESTED**, plus the recorded 16:21
API-POI -> server Tomul -> interaction -> turn-in/next acceptance handoff.
The earlier direct ghost fallback is superseded by common MMAP or current-mount
Steady Flight. Current completed-quest packet/API pins outrank alternative
historical ender spawns; an agreeing floor keeps separate static provenance.
Flight MOVE requires a mounted player, and mounting/capability changes release
obsolete decision evidence. User-directed temporary retry/task bans are capped
at 20 s, missing-mount backoff at 0.5 s. Final combined regression: 2840 passed,
1 skipped, 10 baseline exclusions across 217 modules; 163 focused tests and 76
mount/retry cases passed with overlap. Evidence is recorded in LIVE_VALIDATION.md
and the task artifacts. Ghost resurrection and complete escort support remain
unvalidated/partial. No acceptance gate is promoted.

2026-10-28 ghost corpse-run handoff (V4-068; DESIGN-069):
**PARTIAL / OFFLINE_TESTED**. The existing death policy receives WorldModel
navigation/hostile oracles through WorldSnapshot, recognizes the existing
mounted-ghost airborne state, and retains its explicit same-instance fallback
only to the real known corpse. Living/arbitrary movement still requires MMAP.
Near-corpse XY arrival without known Z/reclaim popup can use bounded descent;
reclaim delay and actual button verification remain authoritative. Active
corpse movement/descent stops when ghost state ends. 2790 broad tests passed
(1 skipped, 10 documented baseline exclusions), followed by 58 final focused
tests with overlap. Retained-state RecordingExecutor replay now starts the
corpse MOVE; live travel and resurrection remain pending. See LIVE_VALIDATION.md.
No M0/M1 gate or unrelated requirement is promoted.

2026-10-28 Vineyard directed quest item: **PARTIAL / OFFLINE_TESTED**.
The shared quest reference handoff now joins local DB2 item/periodic/cone
geometry with exact conditional TDB spell-hit credit. QuestDomain requests
normal NavigationService approach/facing and canonical UseItemSkill activation;
the addon supplies public self-item readiness with no selected unit. Exact
item/objective/pose/button checks and scoped credit verification remain the
input and success boundaries. The supported periodic-emitter family has
bounded retries/waits; other families remain explicitly unresolved. 55 focused
offline cases and a native recorded-position route replay passed; broader
regressions are recorded in VINEYARD_DIRECTED_ITEM_FIX_20261028.md. The fixed
Vineyard quest still requires a user-run live test. All numbered rows and gate
statuses below are preserved.

2026-10-28 general local quest-NPC chat trial (V4-014–017/022/033/056;
Design-037/038/046/048): **PARTIAL / OFFLINE_TESTED**. A current specific
arrival/unresolved objective point plus its known giver and live talkable
server actor may propose the existing interaction without a required prose
phrase or NPC-name overlap. Current objective/world/floor and explicit
identity gates remain. Search polygons, unaccepted tasks and known combat,
collect, item/object or scripted-event mechanics do not authorize this new
fallback. Existing gossip trials, paid-row guards, cooldowns and credit
verification remain; this is not a general new recovery controller or
pre-confirmed credit. 553 related tests across 34 modules and 134 final
focused tests passed (overlap); retained-state replay also works after
removing the quest description. Live validation is pending. See
LIVE_VALIDATION.md; no acceptance gate is promoted.

2026-10-28 22:00 meeting-place / quest-speaker relation (V4-014–017/022/033/056,
Design-037/038/046/048): **PARTIAL / OFFLINE_TESTED**. Same-quest first-person
instructions naming the current meeting place now resolve through the shared
conversation actor policy. The speaker template is candidate evidence; current
server GUID/position, explicit objective identity, facing, exact soft recipient,
mount state and normal quest-credit verification retain authority. This fixes
the diagnosed Toward the City WAIT in front of Tomul without a per-quest script
or a second action owner. 521 related tests across 33 modules and 19 final
focused tests passed (overlapping); saved-state replay replaces WAIT with
DISMOUNT/INTERACT. The subsequent caravan stages still need a user-run live
test. No acceptance gate is promoted; see LIVE_VALIDATION.md.

2026-10-28 gossip alternatives, completed-campaign priority and mount-to-flight
handoff (V4-025–027/033/056 and shared action/quest verification;
Design-025–027/046/048): **PARTIAL / OFFLINE_TESTED**. Exact quest actors
can select a unique own-name introduction, or a sole row of a catalogue-bound
"Speak with me" quest speaker, despite a technical credit caption. The user's
newer direction allows bounded ordinary-chat trials when the exact actor is
known: the existing shared attempt memory tracks no-credit choices and prevents
menu-reopen loops; only normal quest-state evidence verifies progress. Failed
preflight and cancellation do not condemn an option. Full current row data is
rechecked at dispatch. This is not a complete server gossip-menu decoder.
An unreturned campaign still suppresses far side detours. Late can_glide facts
can cancel/replan an active ground MOVE as flight through the same owner;
cancellation is not arrival. Broad regression 2722 passed / 1 skipped /
10 known baseline deselections; final targeted checks 175 passed. Three actual
gossip snapshots and four saved travel/policy cases replayed without input.
Live completion is pending; no acceptance gate is promoted. See LIVE_VALIDATION.md.

2026-10-28 collection-source combat handoff (V4-008/010/014–016/034,
shared quest/evidence, target identity and verification requirements):
**PARTIAL / OFFLINE_TESTED**. Discovery and combat now share the existing
objective-item-creature relations. A selected live source of an unfinished
COLLECT objective reaches COMBAT with its quest/objective ids, without
matching the mob's name to the item's name or narrowing all sources to one
target_entity. Multi-source/multi-quest and primary-objective cases are
preserved. Conflicting GUID/entry/item evidence and completed/fulfilled
counters do not authorize hunting. Existing skill/input/credit gates remain.
633 related tests passed across 52 modules in the actual project; 491 source
files parse. Twelve recorded frames replayed without input or progress
mutation. This is not post-fix live validation or a new completed quest.
The separate Vineyard item-use gap remains unresolved. No gate is promoted;
see LIVE_VALIDATION.md.


2026-10-28 object post-use movement and cross-zone campaign routing (V4-033
interaction / quest verification, V4-025–027 navigation context and arrival):
**PARTIAL / OFFLINE_TESTED**. The reviewed plant-pulling family is resolved
from objective text + exact TDB goober + client spell name, and executed inside
the existing ObjectUseSkill with pinned GUID, bounded safe backward steps and
objective-scoped credit. Own current channel identity crosses the addon/FAST
boundary and permits only that mechanic to move during its channel. Other
scripted movement families remain absent. Same-world server quest POIs in a
neighboring UI zone remain usable; different physical instances still need a
separate transition mechanism. Real saved-state geometry replay plans the
campaign destination; it is not a live completion. 2576 related tests passed
(1 skipped / 10 documented baseline cases deselected); final focused checks
131 passed. No gate is promoted; see LIVE_VALIDATION.md and task artifacts.

2026-10-28 escort / turn-in follow-up (V4 sections 25–28 and 58; shared
evidence, ownership, cancellation and verification invariants): **PARTIAL /
OFFLINE_TESTED**. Natural escort rechecks/combat yields are cancellation,
not learned failure; engaged escorts retain travel ownership. Current server
quest-POI XYZ is decoded for the explicitly reviewed 70575 family, delivered
across receiver startup with its original age, and resolved ahead of TDB.
Exact live NPC evidence still leads. Canonical turn-in proposals own the route;
mount/flight-capability and planning failures do not invalidate the known floor;
supported-stuck and target rejection retain context-scoped suppression.
Saved-state replay with real geometry now plans the upper landing. This is
not a completed live flight/hand-in or an M0/M1 gate promotion. Indoor egress,
escort restart/failure/attacker handling and the unreproduced MOVE `x` exception
remain unresolved as detailed in LIVE_VALIDATION.md.
Final related regression: 2479 passed, 1 skipped, 10 documented pre-existing
failures deselected; input-free geometry replay is distinct from live success.

2026-10-28 name-term and role-based TALK discovery (shared reference,
candidate identity, quest-context and interaction verification requirements):
short names can discover unlisted prefixes; definite roles can match an
NPC's own base TDB subtitle. Distinct matching names remain unresolved
candidates until the common server/quest-context resolver narrows them.
An arbitrary nearest actor, a literal generic-role name, a truncated query
or a conflicting current NPC-ID/GUID does not gain interaction permission.
Latest NPC record revisions win before name/title matching. Existing strict
fallbacks and execution identity/recipient checks remain in place.
**OFFLINE_TESTED / PARTIAL:** 1737 related tests passed, 1 skipped, 9 documented
pre-existing failures deselected; real-catalogue saved-state replay preserved
Edress/Left row selection and Right/Bazentus/Kavia server approach. No new
live interaction/credit is validated. Translated-title lookup is not added.
See LIVE_VALIDATION.md for evidence, query bounds and timing scope. No gate
is promoted.

2026-10-28 unmarked conversation topics and actor identity follow-up
(shared TALK/quest-dialog, target selection and verification requirements):
exact current actors can resolve from coordinated names and recognized titles;
their TDB relation also binds the common playbook. A unique unfinished quest
topic can select an actual unmarked chat row using its explicit role/context.
Known nonattackable elites skip only the combat veto; hostile/unknown elite
protection and numeric identity checks remain. Quest-counter progress releases
the same-NPC handled delay while preserving the short interaction throttle.
**OFFLINE_TESTED / PARTIAL:** 113 focused tests passed; final related regression
1705 passed / 1 skipped / 9 documented pre-existing failures deselected.
Saved-state replay
reproduces the earlier failures and selects the new Edress/Left rows and
Right/Bazentus server approach. User clicks supplied the observed Edress
credits. Kavia's reviewed MANUAL frame already proposed MOVE before this
change; her autonomous contact issue remains unvalidated. There is no generic
incoming gossip-menu-to-credit packet mapping. See LIVE_VALIDATION.md for
the final regression and remaining live validation. No gate is promoted.

2026-10-28 existing quest-playbook/skill binding (V4-040/050/051/060/070;
Design-050/075/076): typed playbook steps project existing mechanism knowledge
into plan horizons and bounded candidate-score guidance. Only unique active
objectives qualify; hidden static rows match by ID/text, never visible array
order. Existing QuestAttemptMemory now owns the bounded trial journal, linking
failures to later verified action results while distinguishing own objective
credit. Stable options exclude sampling churn and group equivalent F7 aliases.
Location commitment can yield to a same-objective ready action after verified
approach or a failed option. Target commitment preserves its GUID while
honoring grounded alternative scores. Existing input authority, availability,
cooldowns, proposal keys and failure budgets remain decisive.
**OFFLINE_TESTED / PARTIAL**: 1471 related tests passed, 1 skipped,
9 documented pre-existing failures deselected (27 new scenario cases).
Missing ESCORT/EMOTE/container/script-source
handlers and alternate landing selection remain absent; no live quest coverage
or acceptance gate is promoted. See LIVE_VALIDATION.md for checks/exclusions.

2026-10-27 coal/NPC facing and Wrathion boarding follow-up
(V4-027/028/029/032/033; Design-025/037/038/075/076): the user-run test
exposed three MANUAL transitions from an invalid precision movement duration,
repeated fixed-time facing failures, and a speech hold applied to an unfinished
travel-with objective. Forward pulses now have legal duration and an explicit
translation expiry; improving final turns continue within a hard total budget.
Current server vehicle candidates can resolve via bounded cached exact-entry
catalogue lookups, retaining live GUID/recipient checks and VEHICLE_ENTERED
verification. ARRIVE does not arm speech credit; obsolete speech waits replan.
Recorded-state replay selects the current Wrathion vehicle without hover.
**OFFLINE_TESTED:** 1062 related tests passed (19 new cases; two documented
pre-existing failures deselected); live follow-up remains unvalidated.
At that revision, general alternative landing search and a cross-skill
recovery-outcome journal were UNIMPLEMENTED; the 2026-10-28 entry above records
the subsequent partial journal/playbook binding, with landing search still absent.
`docs/RECOVERY_OPTIONS_PLAN.md` records their scope and existing partial
recovery mechanisms. No gate is promoted.

2026-10-27 forge live follow-up (V4-027/032/033/038/040;
Design-025/037/038/055): the first patch's use-capable server ID selection
was exercised in user tests; autonomous use/credit was not validated. The
next failures were an inferred lower floor vetoing an exact fresh F7
recipient, and a latched ambiguous-floor result typed as INTERNAL_ERROR
despite a new measured own Z. Shared interaction readiness now distinguishes
measured from inferred height. Navigation replans a still-owned, unexpired
request from newer observed own position; typed finite position recovery
replaces permanent software-error suppression. A fresh interrupted use cast
does not blacklist the contact as missing quest credit.
**OFFLINE_TESTED:** 928 related tests passed (15 new; two documented
pre-existing failures deselected), including real MMAP replay of the recorded
latched-error/new-position boundary. Post-fix live route, cast and objective
credit remain unvalidated; no gate is promoted.

2026-10-27 forge/fragment interaction follow-up (V4-027/031/032/033;
Design-023/025/037/038/055): shared server-object selection and dispatch
distinguish a use candidate from passive quest scenery even when both share
an objective and Activate. Failed contacts lead to finite canonical navmesh
approach probes, not the same learned edge/F7 loop. Current exact recipient
identity, map, facing, stop state and actual quest-credit verification remain
required. Final interaction forward leases account for speed/pose age;
in-place facing takes priority over an unnecessary height-probe jump.
Old moving-follower coordinates cannot force an incorrect turn.
**OFFLINE_TESTED:** 834 related tests passed, including 25 new regressions;
recorded-state and real MMAP replay
select the usable forge and a reachable side-probe on the measured own floor.
Live use/credit, all mounted overshoots and the separate unknown-floor WAIT
remain unvalidated. Two pre-existing test failures are documented with a
pre-change-source reproduction in LIVE_VALIDATION.md. No gate is promoted.

2026-10-27 Oathstone conversation follow-up: shared objective subject parsing
separates the NPC name from a trailing location; cached TDB role projections
include the exact entry's template name. This fixes an observed M1 WAIT at
a current server/soft-interact Wrathion omitted from the six-entry historical
name preview. Existing server GUID/recipient checks remain decisive for input.
**OFFLINE_TESTED:** 164 related tests passed (15 new); recorded-state replay
now proposes TALK via INTERACT to entry 187045. Live objective credit and
the conversation's later steps are unvalidated; no numbered gate is promoted.

2026-10-27 short vertical flight follow-up (V4-025/026/027; Design-025/026):
global route construction now retains requested flights across an observed
height difference even below the ordinary 40 yd horizontal flight minimum.
Missing required flight geometry, a ground path on the wrong known level,
and XY-only arrival shortcuts cannot silently replace the upper landing.
The existing canonical MOVE/Skyriding controller and bounded landing recovery
remain the owners. **OFFLINE_TESTED:** 164 related tests passed, including
16 new regressions; real MMAP/VMAP read-only replay plans a z 247.05 landing
and takeoff from the recorded z 199.90 state. Post-fix live flight and quest
credit are unvalidated; no numbered requirement or gate is promoted.

2026-10-27 accept-to-talk follow-up: corrected an observed WAIT_EVENT ->
generic WAIT path in the shared M1 conversation/locator chain. Offer greetings
do not arm objective speech; explicit live talk objectives can resolve the
current server actor beyond a truncated static named-creature preview. Both
approach and gossip selection consume the same grounded candidates, retaining
GUID checks and context-scoped interaction throttling. 103 targeted tests
passed; a recorded stuck state now proposes INTERACT offline. Real assault
start/credit after the fix remains unvalidated; no numbered gate is promoted.

2026-10-27 large linked quest object follow-up: shared object approach / arrival /
facing / interaction branches corrected OFFLINE_TESTED. The server policy now
consumes the same learned edge as the running MOVE and accepts the current
exact gameobject soft recipient, with dispatch-time pose/identity checks.
81 targeted regressions passed; one independent UDP snapshot replay failure
remains documented. Recorded Siege Arbalest state now admits OBJECT_USE;
actual use/credit after this change remains unvalidated. Talon Strike's
ground-target Extra Action is an additional explicit gap, not completed here.
No numbered acceptance gate is promoted by the offline replay.

2026-10-27 single-duel and post-turn-in transition follow-up: V4-057 / V4-063
received a bounded input-free planner handoff for an observed scripted duel
and delayed local quest offer, including absent target / NPC phase replacement.
125 targeted tests passed and the user-recorded transitions were replayed
without client input. Combat/death retain priority; no spawn identity is rebound.
The user's manual return to Wrathion is excluded from autonomous evidence.
These branches are OFFLINE_TESTED; live acceptance and all existing numbered
coverage rows retain their prior status. See LIVE_VALIDATION.md.

2026-10-27 ItemEffect follow-up: targeted OFFLINE_TESTED work for the shared
M1 objective classifier, locator/item skill and credit verification requirements.
Real local ItemEffect/ItemXItemEffect/ItemSparse and spell/shape/conversation
records were decoded into a separate verified supplement. Quest-scoped unit/self
use references feed ReferenceKnowledge -> QuestModel -> existing item skills.
Ground/object/mixed/unknown execution, AreaTrigger ARRIVE and conversation WITNESS
completion remain partial/absent as described in CLIENT_DB2_ITEM_EFFECT.md.
This does not promote any complete numbered requirement or live acceptance gate.

2026-10-26 vehicle aim follow-up: targeted OFFLINE_TESTED corrections for
V4-055 / DESIGN-059 and the shared planning/navigation path. A selected
vehicle target's in-place pitch MOVE was discarded by XY arrival filtering,
combat admission and target commitment selection. The corrected path retains
air XYZ and aim Z, rejects empty/speed-buff attack candidates and exposes
named cooldown waits. Nine new regressions, related suite 210 passed with
two previously documented visual-aim failures excluded; six recorded states
replayed without client input. Post-fix live damage/quest completion remains
unvalidated; speed-buff travel policy and nonlethal damage-based learning
remain outside this correction. All numbered rows and acceptance statuses
below are preserved; no whole requirement is promoted. See LIVE_VALIDATION.md.

2026-10-25 quest-scene resolution follow-up: OFFLINE_TESTED generic explicit
source-spell/aura/SmartAI/condition links and condition-keyed literal path
tables, with cycle/ambiguity/target/phase guards. Existing TDB is read in place;
original DB2, cache, addon/capture and movement authority are unchanged.
36 decoded tables; 332 candidates / 241 quests, 214 single-package references,
27 ambiguous and 179 keyed path bindings. Automatic lookup of race 72089
selects condition 103255 -> package 3562 -> Path 43699, seven complete XYZ
nodes, and exposes it through the existing shared reference projection.
No fifth hand-written mapping. Reference resolution is not live quest or
race completion. Four reviewed exceptions persist; live scene/condition
authority, Skytop race-progress adapter, general script interpretation and
all quest mechanics remain partial/unimplemented. Actual-project checks:
529 passed / 43 modules, 467 source parses. No game input/capture/FULL_AI
launch, no whole requirement/gate promoted; numbered rows stay unchanged.
See LIVE_VALIDATION.md and CLIENT_DB2_CATALOG.md.

2026-10-25 generic flight/client-data follow-up: OFFLINE_TESTED quest-domain
scene adapter with declarative FlightPath; the shared NavigationService /
ReachMovementController owns flight and verified ground approach for both
Skyriding and Steady Flight. No per-quest movement branch or separate brain.
Canonical selected-context server counters retain original times and do not
refresh addon authority. Real arrival credit and selected-cache gates remain.

Existing TDB remains in place, byte-for-byte unchanged and configured as
before. Supplementary local DB2 SQLite inventories 1125 files and decodes 35
tables (1090 inventory only): 66589 quest IDs, 3530 scene packages, 40431 texts,
17511 paths, 72381 POI blobs / 170335 points. The common reference provider
exposes generic client quest data; scene/path/raw queries work independently
of the four reviewed quest-path relations. Quest 77345 has eight local rings
plus landing. Unknown quest-scene relations stay UNRESOLVED; general script
interpretation/all mechanics and all live quest completion are not claimed.

Actual-project checks: 502 passed / 42 modules, 466 source parses. Native
Detour replay from recorded touchdown finds ground approach with the same
owner; walking after alignment uses explicitly synthetic heading feedback.
No live input/capture/FULL_AI launch. Post-refactor landing, walking, hand-in
and Higher Velocities completion remain NOT_LIVE_VALIDATED. All numbered
rows are unchanged, no whole requirement/gate is promoted. See
LIVE_VALIDATION.md and CLIENT_DB2_CATALOG.md.

2026-10-25 landing/turn-in follow-up: LIVE user-run PID 13840 confirms
5/5 rings, 1/1 target area and quest 65118 complete, still awaiting turn-in.
Delayed credit caused a relaunch and an unreachable overshoot. OFFLINE_TESTED
repair suppresses the last-ring relaunch/boost and transfers the same owned
MOVE to ordinary verified MMAP walking after touchdown; mounted capability
alone does not select flight. Native geometry replays find paths from the
recorded touchdown/target to the server-confirmed ender and reproduce the
overshoot failure. Actual-project checks: 430 passed across 23 modules,
including 15 new regressions; 462 source Python parses. Existing numbered
rows are unchanged; no whole requirement/gate is promoted. Post-fix landing,
mounted approach and actual hand-in remain NOT_LIVE_VALIDATED. See
LIVE_VALIDATION.md.

2026-10-25 Skyriding live follow-up: the user-run 27160/26524 recordings
confirm active SKYRIDING actionbar projection and ready relevant bindings,
but flight feedback was absent from canonical/control state and the course
was not completed autonomously. OFFLINE_TESTED repair projects confirmed
own-player XYZ/facing/pitch/speed into both canonical and fast views without
restamping; only an already owned mounted flight receives a takeoff/glide
fall exception. Missing or stale feedback waits without blind input.
Actual-project checks: 396 passed across 19 modules, including 18 new
regressions; 462 Python source parses. Numbered rows remain unchanged and
no whole requirement/gate is promoted. Post-fix flight remains
NOT_LIVE_VALIDATED. See LIVE_VALIDATION.md.

2026-10-25 follow-up: OFFLINE_TESTED active Skyriding main-bar projection,
page/revision-coherent FAST feedback and invalidation, context-aware selected
cache preflight, explicit pitch-binding evidence and receive-time transitions.
The final 12-module suite in the actual projekt folder passed 253 tests,
including 24 focused regressions; all 462 source Python files parse. Both
addon copies are byte-identical. Existing numbered rows
remain byte-for-byte unchanged; no whole requirement or acceptance gate is
promoted. V4/Design action-context and binding-inventory implementation is
partial; user-run course/landing/combat resumption remain NOT_LIVE_VALIDATED.
See LIVE_VALIDATION.md. Addon 0.9.77-12.1.0 requires installation and /reload.

2026-10-22 22:25:06 follow-up: LIVE evidence confirms three specific heals
(3/4) through the previous item chain. The fourth-subject continuation is
now OFFLINE_TESTED: bounded last-seen locations and objective TDB points
reuse canonical search coverage, with fresh server-identity handoff and
credited-site exclusion. 132 modules: 1269 passed / 1 skipped / 3 previously
control-reproduced discrepancies deselected; 454 source parses. Native
MMAP/replay checks are offline only. Fourth heal and turn-in remain
NOT_LIVE_VALIDATED. All 372 numbered rows remain unchanged; no full
requirement/gate is promoted. See LIVE_TEST_FIXES_20261022_222506.md.

2026-10-22 21:55:13 follow-up: OFFLINE_TESTED exact API quest-tool + literal
heal semantics, hidden-TDB-row-safe objective matching, server-GUID healer
acquisition through shared MOVE/TARGET/UseItemSkill, bounded per-GUID credit
memory and exclusion of healing objectives from ordinary kill acquisition.
128 modules: 1235 passed / 1 skipped / 3 explicitly deselected older
control-reproduced discrepancies. All 452 source Python files parse; the
372 numbered rows below are unchanged. Actual healing, 4/4 and turn-in are
NOT_LIVE_VALIDATED. The separate live fall/layer ambiguity remains open.
No input owner, binding, addon or capture dependency was changed; no full
requirement/gate is promoted. See LIVE_TEST_FIXES_20261022_215513.md.

2026-10-22 21:37:57 follow-up: OFFLINE_TESTED quest-level, live-pin-matched
TDB search-area containment and campaign-priority-aware turn-in batching.
The earlier route failure is distinct from the subsequent pixelstrip safety
wait. Actual native map probes retain the 44-degree walking policy and find
the hand-in route; no live slope or safety gate was relaxed. 101 scoped
modules: 868 passed / 1 skipped; 451 source AST parses. All 372 numbered
rows are unchanged. Post-fix stair traversal/hand-ins remain
NOT_LIVE_VALIDATED; see LIVE_TEST_FIXES_20261022_213757.md and
LIVE_VALIDATION.md. No full requirement or acceptance gate is promoted.

2026-10-22 20:28:57 recording follow-up: OFFLINE_TESTED bounded entity
coalescing/replay/backoff, server-selection vs. stream-health separation,
honest GUI semantic freshness, exact-GUID corpse rejection, hover freshness
and known-elite engagement gates. Direct edits in `projekt`, no second
planner/input owner. The visual hover/click mismatch root cause and real
elite recovery remain NOT_LIVE_VALIDATED. Four older test discrepancies
are reproduced separately with the new rules disabled in memory, not
silently counted as passing. All 372 numbered rows below are unchanged;
no M0/M1 gate promoted. See LIVE_TEST_FIXES_20261022_202857.md and
LIVE_VALIDATION.md for the final scoped regression results and limitations.
Actual-project checks: 90 modules, 973 passed / four explicitly deselected
control-reproduced older discrepancies; 451 source AST parses; numbered-row
SHA-256 unchanged. These are offline checks, not a completed real quest.

2026-10-22 19:49/19:52 follow-up: targeted OFFLINE_TESTED corrections join
soft-recipient/server-XYZ range recovery to the canonical Interact FSM /
NavigationService, prevent premature rescue handoff at known distant XY,
remove the unrelated friend-hint radius from exact server approaches, and
use finite navigation-owned TDB-hint coverage when no actor is observed.
Identity, freshness, MMAP/facing/arrival, deadline and verification authority
remain unchanged; no new brain or input owner exists. The 2/4 live counter
is observed, but the user may have pressed F7 for the second airborne
whelp, so it is not two autonomous successes. Airborne acquisition without
a verified recipient remains NOT_LIVE_VALIDATED. All 372 numbered rows
are unchanged and no whole requirement/M0/M1 gate is promoted. See
LIVE_TEST_FIXES_20261022_194827.md and LIVE_VALIDATION.md.
Actual-project post-publication checks: 810 passed / one known baseline
explicitly deselected, plus 140 architecture/identity tests passed.

2026-10-22 12:00 follow-up: narrow LIVE evidence now supports the previous
65760 arrival/turn-in and post-combat loot -> remount path; it does not
validate all navigation/mounting. New OFFLINE_TESTED corrections cover
bounded fully routed alternatives to a rejected centered walking edge,
stable MOVE failure identity/resume gates, and concrete non-proxy rescue
credit actors missing from TDB's named list. Saved/rescued objectives do
not become kill actions; a spellclick NPC keeps INTERACT, a holding object
keeps OBJECT_USE, and quest progress remains separate verification.
Real-MMAP saved-state queries and 84 focused passing tests are not live
rescue credit or walking evidence. The moving-mount failure remains open.
All 372 numbered ledger entries remain unchanged; no M0/M1 gate promoted.
See LIVE_TEST_FIXES_20261022_120016.md and LIVE_VALIDATION.md.

2026-10-22 11:31 follow-up: live MOVE arrival is disproved by its original
quest POI distance (~307 yards). Partial floor-localization legs must not
close a navigation/quest step. The shared service now retains/replans
these legs with strict bounds and an original-endpoint arrival guard.
Post-combat long-route mounting is observed/prepared through the existing
travel policy, planner, supervisor and single skill/input owner. These
corrections are OFFLINE_TESTED, including real-MMAP planning and a recording
executor flow; actual walking/remounting/arrival remain NOT_LIVE_VALIDATED.
All 372 numbered ledger entries remain unchanged, and no M0/M1 gate is
promoted. See LIVE_TEST_FIXES_20261022_113117.md and LIVE_VALIDATION.md.

2026-10-22 09:52 follow-up: addon 0.9.75 API quest marker, row click and
optional Sendrax credit now have narrow LIVE evidence. The next walking
failure exposes a retained airborne timer across recovery and inadequate
native walking costs/returned-anchor grade checking. These incremental
corrections are OFFLINE_TESTED with real-map route comparisons, not live
arrival. Geometry-based gentler/clearer path preference is implemented;
identification of the actual marked/textured road network remains ABSENT
without verified road metadata or learned route evidence. All 372 numbered
rows remain unchanged; no full quest, navigation or M0/M1 gate is promoted.
See LIVE_TEST_FIXES_20261022_095258.md and LIVE_VALIDATION.md.

2026-10-22 09:39 follow-up: the new 0.9.74 live test still loses the
third row's rendered quest label. This invalidates any inference that the
previous offline widget fixture proved live export. Targeted 0.9.75
OFFLINE_TESTED coverage exports Retail's runtime-enum quest-label flag and
uses it through the existing shared planner/pre-click proof. Narrow tests:
191 passed; actual export/click/credit pending. All 372 numbered ledger
rows are unchanged; no whole gossip/quest/M0/M1 gate is promoted. See
LIVE_TEST_FIXES_20261022_093950.md and LIVE_VALIDATION.md.

2026-10-22 09:19 follow-up: the prior server actor approach/F7 now has
narrow live evidence. Rendered gossip marker export and shared
planner/pre-click proof are targeted OFFLINE_TESTED corrections only.
Screenshots confirm a visible quest prefix absent from the API-name
telemetry. All 372 numbered rows and shared action authority remain
unchanged; no whole gossip/quest/M0/M1 gate is promoted. Actual 0.9.74
export/click/credit is pending. See LIVE_TEST_FIXES_20261022_091936.md.

2026-10-22 09:01 follow-up: targeted OFFLINE_TESTED conversation-actor
coverage resolves explicit Ask-about captions through exact TDB names, so
an observed phased server actor outside the six-name preview remains
eligible for the existing GUID/XYZ MOVE, facing and soft-interact flow.
The shared architecture and all 372 numbered rows remain unchanged. This
does not promote whole objective classification, escort/travel routing or
M0/M1 acceptance. Live approach/gossip credit remains pending. See
LIVE_TEST_FIXES_20261022_090125.md and LIVE_VALIDATION.md.

2026-10-21 19:00 follow-up: the existing conversation branch now recognises
an exact TDB-named receive-orders actor and gives a unique API `(Quest)`
gossip row precedence over lore, not a fixed row index. This is targeted
OFFLINE_TESTED coverage under the same WorldModel/Planner/skill/verifier.
The earlier Sendrax signal-flare transition is observed in the new user
test; Selistra's correction still needs a new live run. All 372 existing
numbered rows are unchanged; no whole requirement or acceptance gate is
promoted. See LIVE_TEST_FIXES_20261021_185729.md and LIVE_VALIDATION.md.

2026-10-21 18:14/18:38 follow-up: precise final approach and grounded NPC
conversation corrections are OFFLINE_TESTED. The planner honours the
requested sub-four-yard stop; TDB conversation intent resolves the actual
named actor rather than a technical credit ID; the existing UI skill can
use a fresh exact NPC-window owner without a selected hard target. Unknown
UI quest identity waits within the existing attempt instead of failing and
reclicking. The shared Planner/NavigationService/skill/verification ownership
is unchanged. All 372 existing numbered rows remain preserved and no whole
requirement or M0/M1 acceptance gate is promoted. See
LIVE_TEST_FIXES_20261021_181320.md and LIVE_VALIDATION.md.

2026-10-21 17:14 follow-up: targeted OFFLINE_TESTED corrections cover
startup packet-entity recovery, server-only MOVE/interaction handoff and
explicit BUY seller localisation. The existing WorldModel/Planner/skill/
verification ownership, selected-PID scope and freshness/identity guards
remain authoritative. All numbered V4/Design rows below are preserved.
No whole requirement or M0/M1/live acceptance gate is promoted by the
synthetic regressions. See LIVE_TEST_FIXES_20261021_1712.md and LIVE_VALIDATION.md.
Expanded check: 924 passed, 1 skipped, three baseline failures independently
reproduced before publication; final targeted facing/packet tests 105 passed.
All 372 existing V4/DESIGN/V5 rows, including 203 V4/DESIGN rows, are preserved.
Final-facing timeout no longer counts as arrival; this remains offline evidence.

2026-10-21 16:37–16:40 follow-up: V4-009/014/015/031/055/056/061/071/072
receive targeted OFFLINE_TESTED corrections for response windows, utility
vehicle objectives, gossip credit, server turn-in routing and UI retry
bookkeeping. All numbered V4/Design rows below remain preserved; none is
promoted to whole-requirement completion or M0/M1 acceptance. Four actual
checkpoint replays pass; broad related tests: 1135 passed, two independently
reproduced pre-existing visual vehicle-aim failures. Post-fix live validation
is pending. See LIVE_TEST_FIXES_20261021_1640.md and LIVE_VALIDATION.md.

2026-10-20 Exile's Reach regression follow-up: V4-007/009/014/015/031/034/
035/061/068/069/071/072 and Design-004/019/020/023/025/039/042/048/049/061/
069/070/075 receive targeted OFFLINE_TESTED corrections. Server identity
and coordinates lead the affected targeting/loot/turn-in branches; UI and
recipient evidence still gate input. All existing numbered rows below are
preserved. This is not completion of those requirements or M0/M1 acceptance.
See EXILES_REACH_FIXES_20261020.md and LIVE_VALIDATION.md. Post-fix live
validation is pending. The legacy MASTER_AGENT_PROMPT.md and
MASTER_ADDON_PROMPT.md referenced in the supplied outer AGENTS are absent
from this checkout; they were not recreated or silently reinterpreted.

2026-10-19 continuation/agenda follow-up: V4-045/046/061/063/064/065/071/072
and Design-018/019/020/063/064 remain PARTIAL at end-to-end/live level. The
existing Planner agenda now covers conditional offer/read/work/turn-in/next
discovery, keeps a verified continuation after turn-in, and represents empty
known-log discovery instead of an empty task list. Live offers/UI invalidate
the idle refresh immediately; expectations and missing-evidence/failure
branches remain plans, not quest truth. Available questgiver routes cannot
lose attention to regenerated generic SEEK; absent usable local quest cues,
map discovery precedes unrelated bodies. Addon 0.9.68 invalidates stale
quest-line request throttles after meaningful quest changes without async
request storms. These corrections are OFFLINE_TESTED, not live-validated.
The PID-5292 recording confirms quest 55879 turn-in but exposes continuation
failure in the pre-correction source. All 71 recorded post-pin snapshots now
prefer the live API questgiver MOVE; this is not an executed acceptance test.
Initial Giant Boar overrun, turn-in detours and the earlier cave probe defect
remain explicitly open. Every numbered requirement below remains tracked.
See LIVE_VALIDATION.md and QUEST_AGENDA_DESIGN.md for scope and evidence.
Final related offline regression: 184 modules, 1818 passed, two optional-image
skips and the one separately pre-existing cave short-probe failure. Python/Lua
syntax and addon mirror equality pass; all 203 V4/Design IDs are preserved.
The initial Windows-resource collection error was followed by a completed
user-requested retry. These results do not promote any whole live M0/M1 gate.

2026-10-19 quest-item / Giant Boar follow-up: V4-009/010/031/032/036/038/039/053
and matching Design item/interaction/verification requirements remain PARTIAL.
The shared read-only QuestToolResolver, addon 0.9.67 exact public item/target
readiness, compact recipient evidence, local item ownership and current-cursor
TARGET handoff are implemented and OFFLINE_TESTED. User-run telemetry observes
Re-Sizer 0/3 -> 3/3, its turn-in and acceptance of 55879; this is not general
item/quest or final-source live acceptance. The large Giant Boar exposed a
separate no-motion/range-error replay loop. Its canonical recovery now requires
actual forward steps, fences feedback per input and retains the original
quest baseline, retry limits and authority. That final recovery is offline
only until a new user test. No requirement rows or unresolved gates are removed.
See LIVE_VALIDATION.md and the new dated item/telemetry/Giant regression files.
Final related offline check: 1778 passed, two optional-image skips, the one
separately pre-existing ambiguous-floor probe failure; 179 modules. Python/Lua
syntax and package mirror equality passed. No full live acceptance follows.

2026-10-18 NPC handoff correction: V4-006/007/009/010/031/038/039/061/071/072
and the corresponding Design sensor/target/navigation/supervision requirements
remain PARTIAL. Addon 0.9.66 raises pixel-frame draw levels without mouse input;
canonical hover waits for its own feedback, bounded paged-STATE handling keeps
original clocks, and TARGET uses current proof at begin. Same-route visual cue
interrupts are bounded without suppressing fresh public NPC-ID evidence. A
terminal loop signal is supervised before admitting the replacement skill.
These corrections are OFFLINE_TESTED only. The user's second 2026-10-18 run
contains verified quest-state transitions but exposed the pre-correction
delays; it is not live acceptance of the changes. See LIVE_VALIDATION.md.
Every numbered row and all previously unresolved requirements remain tracked.
Expanded closure check: 1744 passed, two optional-image skips, one existing
ambiguous-floor short-probe failure, reproduced separately with pre-patch
sources loaded read-only. No navigation-layer implementation was changed.
Python syntax, Lua compilation and addon mirror equality checks passed.

2026-10-17 ID/GUID boundary follow-up: V4 identity, evidence, target,
interaction, combat, loot, navigation and corresponding Design requirements
remain PARTIAL. Shared pure comparison and per-attempt command checks,
public object_id transport, GUID-less object-ID interaction, UI owner pinning,
original sample clocks, selected-entity movement continuity and no-input
post-despawn verification are implemented and OFFLINE_TESTED. They do not
establish live public-ID availability, live quest completion, stable physical
identity without a GUID, or completion of a whole M0/M1 gate. Missing GUID
and object ID remain unknown; no hover XYZ or invented Z was added.
See ENTITY_IDENTITY.md and LIVE_VALIDATION.md. Every numbered row below is
preserved; no acceptance gate is promoted by adoption or synthetic tests.
Closure review 2026-10-18: final related regression is 1679 passed, two missing
optional-image skips and one explicitly excluded, separately OPEN probe-route
test; 171 modules. Static checks cover 37 touched Python production modules,
the new regression module, Lua compilation and primary/mirror byte equality.
No new live validation or whole-quest acceptance follows from these results.

This ledger tracks all three current user-supplied sources. Tracking is not implementation or live validation.

2026-10-16 Murloc handoff correction: the user-operated 09:00 test accepted
55122 but remained 0/6; it does not validate combat/loot or whole-quest M1.
V4-007/009/010/014/015/017 and corresponding Design search, identity,
navigation and verification requirements remain PARTIAL. Generic combat
subject/tooltip movement handoff, full/FAST/parallel original-sample clock
agreement, fast-to-medium yielding and COLLECT arrival/local-search continuity
are now offline-tested; all three actual recorded murloc snapshots pass the
SEEK -> TARGET handoff replay. These changes do not assert quest credit.
The existing ambiguous-floor short-probe route test remains OPEN and was
reproduced with pre-correction sources. See LIVE_VALIDATION for evidence,
the explicit final-suite exclusion and live checks still required.
Every numbered requirement below is preserved; no acceptance gate is closed.

The user's evening moving-target follow-up exposed redundant TARGET
re-hover and a feedback barrier continually advanced by pointer following.
Exact fresh current-cursor proof is now reused at canonical TARGET begin;
fallback tracking gives its own pointer move a bounded chance to receive
post-move GUID feedback. Target identity verification and timeouts remain
required. The 25 Hz / 60 ms synthetic case clicks at +120 ms, not a live
latency guarantee. These corrections are OFFLINE_TESTED; live moving-target
acceptance remains open. See LIVE_VALIDATION for the user logs and limits.
Final related combined regression: 1343 passed, 2 skipped, one explicitly
deselected pre-existing short-probe failure; a further canonical-launch test
passed separately. All ten changed production modules parse successfully.

2026-10-16 scoped WAIT correction supersedes the historical OPEN diagnoses
immediately below, without promoting whole numbered requirements to complete.
V4-009/014/015/016/049/056/074 and matching Design evidence, dialog, progress,
SPEAK and concurrency requirements remain PARTIAL. STATE/vertical-FAST cache
separation and recovery, exact fresh-button evidence, conservative short/full
NPC association, deterministic Ask-to-SPEAK and canonical-semantics area search
are now OFFLINE_VERIFIED. The 2026-10-15 23:54 selected-PID bounded live trial
did interact with Meredy, obtain option 50819, transform the character, receive
55981 objective credit 0/1 -> 1/1 and start the next objective's MOVE. Initial
selection/position were pre-existing, not autonomous discovery; the whole
quest was not completed. A live phasing GUID replacement caused a premature
verification failure despite later credit. Its no-input, no-rebind bounded
verification fix is OFFLINE_REPLAY_VERIFIED against the actual recording
(credit at +9.383 s), not subsequently live-validated. Final STOPPED/disarmed/
empty-keys/pump-stopped and GUI closure were verified. Prolonged live strip
recovery, live stale-button exception, optimal movement and continuous
all-skill cadence remain unaccepted. Full evidence is in LIVE_VALIDATION.
Final related offline regression: 801 passed (exit 0); all 18 touched Python
source modules parse successfully. Numbered requirements below are preserved.

2026-10-15 23:30 assistant-operated baseline was explicitly authorized by
the user and bounded to 30 seconds on verified PID 12512 / selected cache.
It did not complete Meredy's 0/1 objective or open the dialog. The short/full
name inconsistency also rejects the current friendly target in
SpeakObjectiveFlow and the real visual-search identity gate; both are
`OFFLINE_REPRODUCED / OPEN`. Failed SPEAK localization then led to a raw-KILL
area-search fallback in the recorded run. Final status was verified STOPPED,
disarmed, no held keys. No agent-code fix or general live acceptance follows
from this baseline. See the corresponding LIVE_VALIDATION entry.

2026-10-15 23:13 Meredy WAIT: quest dialog association is
`OFFLINE_REPRODUCED / OPEN`. Fresh addon option 50819 is exported, but the
dialog policy requires the full target name `Meredy Huntswell` inside an
objective that says only `Ask Meredy ...`, so it returns no proposal and the
planner waits about 40 seconds. Recorded UI detail age stays below 0.9 s;
STATE refresh works in this run, distinct from the earlier decoder stall.
Only a private diagnostic name substitution unblocks the real policy/registry;
no agent code/live identity was changed. See the matching LIVE_VALIDATION
entry. No autonomous-arrival or quest-completion acceptance is inferred.

2026-10-15 read-only STATE-stall diagnosis: decoder can promote the vertical
FAST geometry into the primary `_GRID_CACHE` during adaptive rediscovery,
then repeatedly return FAST without recovering a visible STATE strip. This
defect is `OFFLINE_REPRODUCED / OPEN`, not fixed: existing Lua drawing helpers
at 1345×697 reproduce primary-cache replacement on covered frame 60 and
FAST-only output after the original full image is restored. The live run's
STATE loss begins in MANUAL before FULL_AI; its private decoder cache is not
recorded, so the precise live initiating transition remains unproven. See
the matching `docs/LIVE_VALIDATION.md` diagnosis. No agent code or numbered
requirement acceptance was changed.

2026-10-15 22:26 user-run follow-up: parallel pump startup/liveness is now
`LIVE_OBSERVED / PARTIAL` through the actual SensorHub (61 FULL_AI status
samples enabled/running, no pump error; healthy-sample median control 24.24 Hz).
This does not accept all shared skills, continuous pointer cadence or a quest.
The user explicitly confirmed they moved the character to the NPC: arrival
is manually assisted, NOT validated autonomous navigation. Recorded approach
states/commands must not be treated as proof of agent-caused displacement.
The same run exposes a concrete availability blocker: fresh FAST CONTINUE /
COMPLETE button facts are rejected using a 63–70 s old FULL_STATE age; source
STATE page/full counters do not advance during the observed FULL_AI window.
Restoring STATE refresh and scoped button freshness remain OPEN, along with
repeated cue handoffs and full turn-in validation. No agent code was changed
by this review and no numbered source row is promoted to full acceptance.
See the 22:26 entry in `docs/LIVE_VALIDATION.md`.

2026-10-15 evening parallel startup correction — the earlier scoped
V4-002/003/006/008/009/031–037/074 and matching Design execution/concurrency
requirements remain `OFFLINE_VERIFIED / PARTIAL`. Both evening live runs had
the fast pump disabled: production SensorHub did not forward the buffered
producer's non-consuming API. Primary-source delegation, original receipt /
transition preservation, freshness/failure/close gates and explicit pump
startup/liveness diagnostics are now tested through the actual wrapper,
capture factory and MANUAL runtime lifecycle. Related offline suite:
303 passed, exit 0. No new user live run, input or autonomous quest acceptance
occurred. See `docs/PARALLEL_CONTROL_DESIGN.md`, `docs/LIVE_VALIDATION.md` and
`tests/test_parallel_runtime_wiring.py`. Restarted-GUI live concurrency,
real cadence and all-skill acceptance remain pending; numbered rows and
unimplemented requirements below are preserved, not promoted to complete.

2026-10-15 live rejection: the experimental local Ymir build-number change
reached connection recognition, then failed at NtReadVirtualMemory with
0xC0000005 and null arguments. No semantic game-event receipt was validated.
The artifact is FAILED, not an approved live producer. Its exposed memory-read
dependency conflicts with the current project source constraints; no repair of
that path or key retrieval was attempted. Existing parser/IPC tests do not
override this result. See the latest LIVE_VALIDATION entry.

2026-10-15 scope clarification: agent-managed live capture and a working
Retail network/session/decryption producer are `ABSENT`, not offline-verified
or live-validated. The packet work below verifies only the scoped prototype
parser/transport/inbox/evidence boundary. The user requested an integrated
sniffer; manual PKT following is not acceptance of that request. Official
Ymir availability for the observed 70391 build is unverified/blocked (published
Retail asset is 69933). See the latest LIVE_VALIDATION/PACKET_TELEMETRY notes.

2026-10-15 packet build/GUI follow-up — the same scoped V4/Design rows below
remain `OFFLINE_VERIFIED / PARTIAL`. The user's live log identified 12.1.5 build
70391, previously blocked. Explicit 70340/70391 opcode-family provenance and
top-detector-line receiver/receipt status are now offline-tested; neither
feature creates input authority or proves live packet receipt. Missing source,
broad payload semantics and live validation stay open. No numbered row is
removed or promoted to full acceptance. See the new LIVE_VALIDATION entry
(211-test related regression plus a separate localhost round-trip).

2026-10-15 packet sensor port — V4-001/002/008/009/010/073/074/079/085/086/096
and Design 3/4/5/11/86/88/89: `OFFLINE_VERIFIED / PARTIAL`.
Audited PID/context-scoped passive packet transport and reviewed 12.1 payload
prefixes feed only canonical observations/evidence/reducers. Input authority
still requires the selected client, exact bindings and fresh addon. Only
fresh same-player outgoing movement may enrich XYZ/facing; addon instance/UI
map and corpse/loot ownership remain distinct. No raw secret/chat payload
forwarding, process-memory/injection path or additional execution authority.
The library source defaults off; the three GUI BAT launchers explicitly enable
its passive inbox per the user's later request, without arming or capture.
UPDATE_OBJECT/HP/power, complete
quest/combat/loot parsers and real Npcap/Ymir validation remain absent/open.
See `docs/PACKET_TELEMETRY.md` and the matching `LIVE_VALIDATION.md` entry.
No numbered requirement is removed or promoted to full M0/M1 acceptance.

2026-10-15 scoped look-ahead update — V4-002/003/006/007/009/031/043–048/063
and Design planner/verification/memory/advisory-LLM requirements:
`OFFLINE_VERIFIED / PARTIAL`. Planner owns a conditional multi-quest agenda,
same-area batching, ender/follow-up read-ahead through the existing TDB and
learned SQLite provider, and a dependency-gated route preview. Only existing
available proposals can be ranked; no extra active FSM or quest-state writer
exists. Explicit primary/campaign policy and fresh interaction verification
remain authoritative. Optional SemanticAdvisor ordering cannot manufacture
steps or unblock prerequisites, and never stalls control. Fresh fast-frame
motion fitting gives bounded screen-space pointer lead, not entity identity
or long-offscreen ReID. See `docs/QUEST_AGENDA_DESIGN.md` and
`tests/test_quest_agenda.py`, `tests/test_agenda_reference_prefetch.py`,
`tests/test_target_motion_prediction.py`. Actual local-model answer quality,
normal-FPS live multi-quest completion, globally optimal routing/pass-through
and full M0/M1 live acceptance remain open. No numbered source row is removed
or promoted to complete acceptance by this scoped change.
Final related offline regression: 996 passed, 1 skipped (exit 0); see the
matching `docs/LIVE_VALIDATION.md` entry. This is not live quest acceptance.

2026-10-15 scoped parallel-execution update — V4-002/003/006/008/009,
V4-031 through V4-037 and the matching Design execution/verification ownership:
`OFFLINE_VERIFIED / PARTIAL`. A latest-only live pump advances the EXISTING
active FSMs with compatible pointer/locomotion channels, resource leases,
cast/channel holds and context/UI/input-safety gates. It neither creates a
second ActiveSkillRuntime nor chooses a quest/target independently. Terminal
bookkeeping stays in the medium engine; advisory visual recognition moves to
a bounded background reader. Direct offline runtime stepping remains
synchronous. See `tests/test_parallel_control.py`, `tests/test_live_debug_monitor.py`
and `docs/PARALLEL_CONTROL_DESIGN.md`. The unplugged low-FPS run is expressly
not representative validation. Full agenda/pass-through implementation,
instant-on-the-move actions and new normal-FPS live acceptance remain open.
This scoped entry does not remove, renumber or promote any requirement below.

2026-10-15 scoped update — V4-031/032/033/035/036/037
and the corresponding Design identity/interaction/verification requirements:
active-skill-owned track-bound pointer following and rejected selected-target
re-hover recovery are `OFFLINE_VERIFIED / PARTIAL`, not `LIVE_VALIDATED`.
The shared pointer helpers produce commands only; ActiveSkillRuntime,
NavigationService and CommandDispatcher retain their existing ownership.
Freshness, same-GUID/cursor checks, UI safety and click verification remain;
movement updates are not consumed by pointer following. The 0.9.64 thin STATE
layout/decoder/mask path is offline-tested with unchanged packet capacity and
legacy support. See `tests/test_active_pointer_tracking.py`,
`tests/test_visual_approach_recovery.py`, `tests/test_two_lane_strip_20261007.py`
and the matching entry in `docs/LIVE_VALIDATION.md`. Live cadence/quest
completion, long-offscreen semantic ReID and the separate total-launch
approach-budget policy remain open. No numbered requirement below is removed
or promoted to full acceptance by this scoped update.

| Requirement | Current source | Status |
|---|---|---|
| V4-000 | NON-NEGOTIABLE PROJECT CONSTRAINTS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:58) | UNCLEAR — Pure meta/process constraints (no LLM for core reliability, client-side-only, no wrapper refactors); not a discrete code unit to map to. Partially corroborated by absence of memory-injection code and presence of single-authority patterns elsewhere. |
| V4-001 | DEFINITIONS: OBSERVATION, BELIEF, FACT, INTENT, SKILL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:170) | UNCLEAR — Pure glossary/definitions section, no direct code artifact to check. Concepts realized structurally across `agent/world.py` (Evidence/Observation) and `runtime/contracts.py` (Intent, SkillResult). |
| V4-002 | FINAL RESPONSIBILITY MODEL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:240) | IMPLEMENTED_TESTED — `tests/test_final_responsibility_model.py` adds the missing single check: the spec's three headline invariants ("WorldModel never sends input", "Planner never presses keys", "Executor never understands quest semantics") plus presence confirmation for every named box in the dependency diagram (Sensors/Observation Ingest/WorldModel/WorldQuery/QuestRuntime/Supervisor/ObjectiveClassifier/ObjectiveLocator/ActiveSkillRuntime/Navigation/CombatService/Executor); complements the existing ~26 pairwise boundary tests in `tests/test_architecture_boundaries.py`. |
| V4-003 | ONE AUTHORITATIVE ACTIVE SKILL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:299) | IMPLEMENTED_TESTED — `runtime/active_skill.py:69` `ActiveSkillState` dataclass matches spec fields almost verbatim (runtime_id, skill_type, phase, attempt, local_retry_count, failure_history, timeout_policy, retry_policy, before_snapshot, skill_context, last_result); tests in `tests/test_active_skill_runtime.py`, `tests/test_active_skill_supervision.py`. |
| V4-004 | COMMON TYPED CONTRACTS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:344) | IMPLEMENTED_TESTED — `runtime/contracts.py:11-132` defines `SkillStatus`, `SkillResult`, `VerificationResult`, `NavigationStatus`, `ObjectiveLocationStatus` matching spec enums exactly; tests in `tests/test_navigation_contracts.py`, `tests/test_plan_skill_contract.py`, `tests/test_movement_contract.py`. |
| V4-005 | FAILURE TAXONOMY (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:418) | IMPLEMENTED_TESTED — `runtime/contracts.py:21-68` `FailureReason` StrEnum covers nearly every taxonomy entry; `runtime/failures.py` adds escalation stages; test in `tests/test_failure_manager.py`. |
| V4-006 | RUNTIME TICK CONTRACT (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:500) | IMPLEMENTED_TESTED — `agent/engine.py:563` `tick()` follows the conceptual loop (ingest observations → world model → supervisor.evaluate → active skill step → dispatch); tests in `tests/test_agent_runtime.py`. |
| V4-007 | REPLAN GATES (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:544) | IMPLEMENTED_TESTED — `runtime/supervisor.py` `SupervisorDirectiveKind` (CONTINUE/REPLAN/BLOCK) with evidence-gated `can_enter()` per state; tests in `tests/test_supervisor.py`, `tests/test_active_skill_supervision.py`. |
| V4-008 | WORLD MODEL RULES (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:568) | IMPLEMENTED_TESTED — `agent/world.py:208` `WorldModel` only stores data/history/evidence, never dispatches input; `agent/world_state_contract.py:34` projects a pure read-only projection; tests in `tests/test_world_state_contract.py`. |
| V4-009 | SENSOR FRESHNESS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:597) | IMPLEMENTED_TESTED — `agent/evidence_freshness.py` adds the explicit `FreshnessTier` (FRESH/STALE/EXPIRED) with per-source-category lifetime policy keyed by the spec's own worked examples (screen_space_bbox, local_entity_location, minimap_marker, quest_objective_text, quest_completion_state, world_map_objective_area); `Evidence` (`agent/world.py:169`) still carries at/expires/confidence/source; `runtime/freshness_gate.py` gates staleness at the runtime-loop level; tested in `tests/test_evidence_freshness.py`, `tests/test_freshness_gate.py`. Wired: `WorldQuery.evidence_freshness(key, now=...)` (`agent/world_query.py`) is a read-only projection that classifies the freshest stored `Evidence` for a key via `FreshnessTier`, mapping `Evidence.source` to a lifetime category (WORLD3D→screen_space_bbox, MINIMAP_CV→minimap_marker, WORLD_MAP_CV→world_map_objective_area); tested in `tests/test_world_query_evidence_freshness_wiring.py`. |
| V4-010 | EVIDENCE FUSION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:637) | IMPLEMENTED_TESTED — `agent/entity_belief.py` adds the spec's `EntityBelief` dataclass (entity_ref/type_belief/identity_belief/role_belief/hostility_belief/interactable_belief/location_belief/confidence/evidence/first_seen/last_seen) plus `fuse_identity()`: ranked-source resolution (addon/quest > target-frame/tooltip > nameplate > quest-marker+context > visual classifier), weak-visual-only confidence cap, contradiction penalty, and age decay; tested in `tests/test_entity_belief.py`. Existing `Evidence`/`ContradictionRecord` (`agent/world.py`) still own raw storage. Wired: `WorldEntityReducer.apply()` (`agent/world_entity_reducer.py`) now records each target/mouseover name observation as `IdentityEvidence` via `WorldModel._record_entity_identity_evidence()` into new bounded `WorldModel.entity_identity_evidence`, tagging it with the closest real spec source (`_identity_source_tag()`: ADDON_TELEMETRY target->target_frame_tooltip_name, ADDON_TELEMETRY mouseover->stable_nameplate_text, MINIMAP_CV/WORLD_MAP_CV->quest_marker_and_context, other CV sources->visual_appearance_classifier, anything else passed through unmapped rather than force-fit); `WorldQuery.entity_belief(entity_id, now=...)` fuses that recorded evidence via `fuse_identity()`. No `addon_quest_reference`-tagged evidence exists yet (no addon-quest-API name source in this build) -- documented rather than fabricated. Tested in `tests/test_entity_belief_wiring.py`. |
| V4-011 | UI CONTEXT MODEL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:672) | OFFLINE_VERIFIED — `agent/ui_context.py::resolve_ui_context` adds the unified `UiContext{primary_panel, overlays[], blocking_state, confidence}` with the full spec `PrimaryPanel` and `BlockingState` enums; blocking state resolves first. `agent/world_query.py::WorldQuery.ui_context()` is the canonical read-only projection and downstream next-quest resolution consumes it. Tested in `tests/test_ui_context.py` and `tests/test_world_query_ui_context_wiring.py`; selected-PID live proof remains open. |
| V4-012 | WORLD OF WARCRAFT QUEST INFORMATION HIERARCHY (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:724) | IMPLEMENTED_TESTED — `agent/quest_info_hierarchy.py` adds the missing single resolver: `QuestInfoSource` StrEnum naming all 8 sources in spec order (A quest tracker -> H temporal history) and `resolve_first_available()` which only falls through to `WORLD_3D` (E) when every higher-ranked source (A-D) is absent -- the literal "do not reduce the system to 3D object detection" guard; tested in `tests/test_quest_info_hierarchy.py`. Each source's own module already existed (`agent/quest_model.py`, `vision/adapters/world_map.py`/`minimap.py`, `vision/world3d/`, `vision/tooltip.py`, `agent/memory.py`); not yet wired as the canonical call site for cross-source quest queries. Investigated for wiring: no single real call site currently asks "where is source X for this same question" across all 8 sources at once -- the closest candidate (`agent/visual_search_planning.py`) already branches on ad hoc, individually-tested state conditions, and the other 7 sources' "is this available right now" signal would have to be invented rather than read from real stored state. Left standalone rather than force a refactor of tested branching logic or fabricate availability signals; a genuine wiring needs either new per-source instrumentation or an explicit decision to replace `visual_search_planning.py`'s branching, which is out of scope for an additive, low-risk change. |
| V4-013 | QUEST STATE NORMALIZATION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:742) | IMPLEMENTED_TESTED — `agent/quest_state.py:8-57` `QuestState`/`ObjectiveState` enums and `derive_quest_state`; `agent/quest_model.py:90-138` `QuestObjective`/`QuestRecord` closely mirror spec fields; test in `tests/test_quest_model.py`. |
| V4-014 | QUEST SUCCESS HAS TWO LEVELS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:793) | IMPLEMENTED_TESTED — `verification/quest.py` `QuestProgressVerifier` is a separate pure comparator from skill success; `skills/combat.py` `VERIFY_DEATH` phase is distinct from quest-credit checks; tests in `tests/test_m1_quest_progress_verifier.py`, `tests/test_m0_combat_loot_skills.py`. |
| V4-015 | QUEST CREDIT IS AUTHORITATIVE FOR OBJECTIVE PROGRESS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:829) | IMPLEMENTED_TESTED — `verification/quest.py:10-50` `QuestProgressVerifier.evaluate()` compares before/after objective counters, completion, turn-in state as primary evidence; test in `tests/test_m1_quest_progress_verifier.py`. |
| V4-016 | OBJECTIVE TYPE CLASSIFIER (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:850) | IMPLEMENTED_TESTED — `agent/quest_model.py::OBJECTIVE_TYPES`/`ObjectiveClassifier._canonical` extended (additive only, no existing alias/regex/API mapping changed) to cover every spec minimum type: INTERACT_NPC, KILL_NAMED, LOOT (kept aliased to COLLECT per pre-existing behavior), USE_ITEM_ON_TARGET, REACH_AREA, EMOTE, GOSSIP_CHOICE, VEHICLE, EXTRA_ACTION, QUEST_TOOL_BUTTON, SPECIAL_UI, SCRIPTED_EVENT, FIELD_TURN_IN, MULTI_STAGE; tested in `tests/test_objective_classifier_v4_016_types.py` (includes a regression guard confirming no pre-existing classification changed) plus existing `tests/test_m1_objective_classifier.py`. |
| V4-017 | OBJECTIVE LOCATOR: THE CORE M1 LOCATION SYSTEM (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:903) | IMPLEMENTED_TESTED — `agent/objective_locator.py:15-56` `ObjectiveLocator`/`ObjectiveLocation` returns `ObjectiveLocationStatus` matching spec's resolution order/result shape; test in `tests/test_m1_objective_locator.py`. |
| V4-018 | WORLD MAP RESOLVER (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:959) | OFFLINE_VERIFIED — `agent/world_map_absence_resolver.py::WorldMapAbsenceResolver` implements the bounded §18.1 procedure without turning absence into a fact. Both Retail addon packages export `active_map_id`, real `C_Map.GetMapInfo(...).parentMapID`/name/type and a cycle-safe four-level hierarchy on FULL plus compact FAST telemetry. `WorldAddonReducer` preserves this evidence; `WorldMapFallbackPolicy` is the canonical caller when a tracked quest marker remains absent, and emits a bounded `MAP_STEP_OUT` only to the addon-reported parent. `SkillRegistry` verifies success only when fresh addon map context changes to the expected parent; untracked/filter-uncertain absence stays UNKNOWN. Tests: `test_world_map_absence_resolver.py`, `test_map_search_planning_policy.py`, `test_map_zoom.py`, `test_world_addon_reducer.py`, `test_agent_transport.py`, `test_retail_addon_package.py`. Selected-PID behavior remains `LIVE_OPEN`. |
| V4-019 | SUPERTRACKING / NAVIGATION INDICATORS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1026) | IMPLEMENTED_TESTED — `agent/supertrack_navigation_cue.py` adds the missing explicit fallback chain: `resolve_navigation_cue()` uses SUPERTRACK_CUE when present, otherwise falls through MINIMAP_BELIEF -> WORLD_MAP_BELIEF -> LOCATION_BELIEF without ever treating cue-absence as "quest has no location"; `KNOWN_DISAPPEARANCE_REASONS` names the spec's 5 legitimate disappearance causes (focus/turn-in/map-context/objective change, unsupported route); tested in `tests/test_supertrack_navigation_cue.py`. Complements existing directional-cue detection in `vision/adapters/minimap.py` (`tests/test_minimap_quest_direction.py`, `tests/test_minimap_treasure_direction.py`); Wired: `WorldQuery.navigation_cue()` (`agent/world_query.py`) builds the real `available` mapping from stored state -- `map_markers("MINIMAP")`/`map_markers("WORLD_MAP")` for the two CV-derived beliefs and `get_best_search_region()` for the location-belief fallback -- and resolves it via `resolve_navigation_cue()`. `SUPERTRACK_CUE` is always absent here because no supertrack-specific signal is exported by this build's addon/vision yet; documented rather than fabricated, so the chain genuinely starts at MINIMAP_BELIEF today. Tested in `tests/test_world_query_navigation_cue_wiring.py`. |
| V4-020 | MINIMAP RESOLVER (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1054) | IMPLEMENTED_TESTED — `vision/adapters/minimap.py:19` `detect_minimap` plus symbol/target/direction-arrow detectors match spec's MinimapTarget responsibilities; extensive tests: `tests/test_minimap_m74.py`, `tests/test_minimap_symbols_m743.py`, `tests/test_minimap_heading_contract.py`, `tests/test_minimap_target_quest_separation_m746.py`/`_m747.py`. |
| V4-021 | 3D WORLD PERCEPTION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1110) | IMPLEMENTED_TESTED — `vision/world3d/pipeline.py:32` `_DETECTION_CLASSES` (NPC, HOSTILE, PLAYER, CORPSE, GAME_OBJECT) plus door/cave_entrance/stairs detection (`pipeline.py:589`, `learned_detector.py:85`); observation-only, no quest planning embedded; extensive tests `tests/test_world3d_*.py`. |
| V4-022 | INTERACT KEY / INTERACTION READINESS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1138) | IMPLEMENTED_TESTED — `agent/bindings.py:53` requires configured `INTERACTTARGET` binding; `skills/interact.py:33` sends `Command("BIND", "INTERACTTARGET")` using the configured binding rather than a hardcoded key; covered indirectly via `tests/test_m0_interact_skill.py` and `tests/test_binding_inventory.py`. |
| V4-023 | TWO NAVIGATION MODES (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1163) | IMPLEMENTED_TESTED — `navigation/navigation_mode.py::resolve_navigation_mode` adds the missing explicit mode selection: TELEMETRY_ASSISTED when reliable world position exists, else VISION_ONLY when any of the spec's 8 named cues (world-map location belief, minimap direction, heading change, scene motion, landmarks, objective marker trend, local entity acquisition, arrival/quest-state evidence) is present -- so it is never UNSUPPORTED merely for missing XYZ -- else UNSUPPORTED only when no evidence at all exists. Deliberately not a second navigation authority: it classifies evidence only, `NavigationService` (`navigation/service.py:221`) remains the sole mover/API for both modes. Tested in `tests/test_navigation_mode.py`. |
| V4-024 | CANONICAL NAVIGATION SERVICE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1210) | IMPLEMENTED_TESTED — `navigation/service.py:29` `NavigationService` composes route/local planning, stuck recovery, arrival, search — old systems exposed only as internal read accessors, not independent authorities; tests in `tests/test_navigation_engine.py`, `tests/test_navigation_contracts.py`. |
| V4-025 | NAVIGATION CONTEXT (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1253) | `OFFLINE_VERIFIED` — `NavigationSituationPolicy` is the production, input-free consumer of `NavigationService.current_navigation_context()`: every canonical movement intent receives typed context evidence and route expectation; an observed loading/map transition holds the stale route; supported boundary evidence is passed to transition handling. It creates no movement authority. Classification, production consumption and fail-closed transition behavior are covered by `tests/test_navigation_context.py`, `tests/test_navigation_situation_policy.py` and `tests/test_navigation_proposal_adapter.py`; selected-PID behavior remains live-open. |
| V4-026 | ENTRANCE / CAVE / MULTI-FLOOR HANDLING (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1276) | `OFFLINE_VERIFIED / PARTIAL` — the Planner's canonical navigation adapter consumes `TransitionResolver` after repeated route blockage or map-close/3D-absent evidence. A supported transition becomes one bounded `SEEK_VISUAL_CUE` with `SEARCH_ENTRANCE` capability and typed `ENTER_BUILDING`/`FIND_CAVE_ENTRANCE`/`CHANGE_FLOOR`/portal/transport/unknown intent; exhausted search escalates to existing map relocalization. Search remains under ActiveSkillRuntime and NavigationService remains the only mover. The 2026-10-06 layered-quest work adds sticky same-space dot focus, two-sample directional floor cues, one Z resolver with ambiguity held, 3D sweep/coverage/turn-in arrival guards; see `tests/test_cave_quest_layer_flow_20261006.py` and `docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md` §14. A heightless turn-in, first fix inside a stacked cave, entrance/exit selection and complete Retail quest credit remain unvalidated or unimplemented; synthetic replay is not live success. |
| V4-027 | ARRIVAL VERIFICATION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1308) | IMPLEMENTED_TESTED — `navigation/arrival.py:7` `ArrivalVerifier`; arrival/ARRIVED evidence exercised indirectly in `tests/test_navigation_engine.py`, `tests/test_navigation_contracts.py`, `tests/test_agent_core.py`. |
| V4-028 | STUCK DETECTOR (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1328) | IMPLEMENTED_TESTED — `navigation/stuck_classifier.py:9-30` `StuckKind`/`StuckClassifier`; `navigation/stuck_resolver.py:15-44` `StuckResolutionState`/`RecoveryDirective`/`StuckResolver` implementing a bounded recovery ladder; test in `tests/test_stuck_resolver.py`. |
| V4-029 | COMMON FACE CONTROLLER (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1368) | `OFFLINE_VERIFIED` — one NavigationService-owned FaceController is shared by interaction/combat approach, with begin/estimate/turn/alignment/tick/cancel lifecycle, bounded commands, timeout, missing-target failure and true enter/exit hysteresis. Live facing accuracy remains open. |
| V4-030 | M0 DEFINITION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1388) | IMPLEMENTED_TESTED — `runtime/m0_dispatch.py:14` `M0SkillDispatcher.CANONICAL` covers TARGET/INTERACT/COMBAT/LOOT/OBJECT_USE/QUEST_DIALOG etc. as the deterministic core with no quest reasoning; tests in `tests/test_m0_dispatch.py`, `tests/test_m0_acceptance_matrix.py`, `tests/test_m0_replay_contract.py`. |
| V4-031 | M0 TARGET SKILL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1415) | IMPLEMENTED_TESTED — `skills/target.py:16-21` `TargetPhase` (ACQUIRE_CANDIDATES/VALIDATE_IDENTITY/SELECT_TARGET/APPLY_TARGET/VERIFY_TARGET) matches spec FSM exactly; failure reasons map onto the shared `FailureReason` taxonomy; test in `tests/test_m0_target_skill.py`. |
| V4-032 | M0 MOVEMENT SKILL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1449) | OFFLINE_VERIFIED — `skills/movement_phase_contract.py` defines all eight named FSM phases. `MovementSkillRunner.step()` now classifies every real navigation assessment and returns the live phase on `MovementStep`, while all pathing/control remains delegated to the one `NavigationService`. `ProgressPhase` remains the separate progress-quality state machine. Tested directly in `tests/test_movement_phase_contract.py` and `tests/test_movement_skill_runner_phase_wiring.py`; selected-PID behavior remains live-open. |
| V4-033 | M0 INTERACT SKILL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1470) | IMPLEMENTED_TESTED — `skills/interact.py:13-22` `InteractPhase` (WAIT_INTERACTABLE/SEND_INTERACT/WAIT_RESULT etc.) matches spec FSM; test in `tests/test_m0_interact_skill.py`. |
| V4-034 | M0 COMBAT SKILL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1555) | IMPLEMENTED_TESTED — `skills/combat.py:17-26` `CombatPhase` (ACQUIRE_TARGET/VALIDATE_TARGET/ENGAGE/ROTATION/MONITOR/RECOVER_RANGE/RECOVER_FACING/RECOVER_LOS/VERIFY_DEATH) matches spec almost exactly, with local recovery routing by `FailureReason` (`combat.py:212-214`); test in `tests/test_m0_combat_loot_skills.py`. |
| V4-035 | M0 LOOT SKILL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1620) | IMPLEMENTED_TESTED — `skills/loot.py:11-16` `LootPhase` (LOCATE_CORPSE/APPROACH/INTERACT/WAIT_LOOT_STATE/VERIFY) matches spec FSM; uses `LootVerifier` for delta-based verification; test in `tests/test_m0_combat_loot_skills.py`. |
| V4-036 | M0 SEARCH SKILL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1647) | OFFLINE_VERIFIED — `skills/search_contract.py` defines the four required capabilities/outcomes and bounded `SearchContext`. `SearchSkill` now owns that typed context per active attempt, records origin/radius/query/scanned sectors and publishes typed FOUND/NOT_FOUND_WITHIN_BUDGET/CONTEXT_CHANGED results while continuing to delegate mechanics to the single `SeekVisualCueController`. A map/session transition terminates for replan instead of continuing an invalid sweep. Covered by `tests/test_search_contract.py` and `tests/test_m0_search_skill.py`; selected-PID live search remains open. |
| V4-037 | M0 CANCELLATION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1689) | IMPLEMENTED_TESTED — `runtime/active_skill.py::ActiveSkillHandle.cancel/finish` (lines 191-217) cancels token, transitions lifecycle, and `agent/engine.py` calls `executor.stop_movement()` on cancel; tested in `tests/test_m0_cancellation.py`. |
| V4-038 | M0 RETRY POLICY (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1713) | IMPLEMENTED_TESTED — `runtime/policies.py::RetryPolicy` (max_backoff_seconds, base_backoff_seconds, exponent_cap, non_backoff_reasons) is a typed centralized policy; tested in `tests/test_m0_policies.py`. |
| V4-039 | M0 TIMEOUT POLICY (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1734) | IMPLEMENTED_TESTED — `runtime/policies.py::TimeoutPolicy.domains` now maps all seven spec domains (movement/interaction/combat/loot/search/ui_wait/map_wait), with OPEN_MAP/CLOSE_MAP mapped to `map_wait`; tested in `tests/test_m0_policies.py`. |
| V4-040 | VERIFICATION PACKAGE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1753) | IMPLEMENTED_TESTED — `verification/` now has all seven named modules: added `base.py` (`Verifier` structural Protocol matching the existing no-input/no-mutation/no-retry/no-planner-call shape all verifiers already followed), `movement.py` (`MovementVerifier`, arrival-radius/progress evaluation), `ui.py` (`UiPanelVerifier`, panel open/close transition evaluation); existing combat.py/interaction.py/loot.py/quest.py/quest_dialog.py confirmed to structurally satisfy the new `Verifier` protocol; tested in `tests/test_verification_movement_and_ui.py` plus existing `tests/test_verification_engine.py`. |
| V4-041 | BEFORE / AFTER SNAPSHOTS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1777) | IMPLEMENTED_TESTED — `ActiveSkillState.before_snapshot` (`runtime/active_skill.py:82`) is populated and consumed by `verifier.evaluate(state.before_snapshot, ...)` in `skills/interact.py`, `combat.py`, `loot.py`; exercised widely, e.g. `tests/test_m0_interact_skill.py`, `tests/test_m0_combat_loot_skills.py`. |
| V4-042 | M0 ACCEPTANCE TEST (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1805) | IMPLEMENTED_TESTED — `tests/test_m0_acceptance_matrix.py::test_m0_terminal_matrix_is_deterministic_across_100_replays` runs range(100) iterations covering scenario-matrix style assertions (no double ActiveSkill, no held key after cancel, typed terminal reasons). |
| V4-043 | M1 DEFINITION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1872) | IMPLEMENTED_TESTED — `agent/quest_runtime.py::QuestExecutionRuntime` is the M1 state-only layer that classifies objectives/locates/verifies without sending input; tested in `tests/test_m1_primary_quest_runtime.py`. |
| V4-044 | CANONICAL QUEST EXECUTION FSM (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1894) | IMPLEMENTED_TESTED — `agent/quest_runtime.py` phase strings match spec exactly (SELECT_PRIMARY_QUEST, READ_QUEST_STATE, VERIFY_QUEST_PROGRESS, RESOLVE_COMPLETION_MODE, LOCATE_TURNIN, FIELD_TURN_IN); tested in `tests/test_m1_primary_quest_runtime.py`. |
| V4-045 | PRIMARY QUEST GOAL (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1958) | IMPLEMENTED_TESTED — `agent/quest_runtime.py::PrimaryQuestState` (quest_id, status, phase) holds the single primary goal; tested in `tests/test_m1_primary_quest_runtime.py`. |
| V4-046 | MAIN CAMPAIGN MODE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1971) | IMPLEMENTED_TESTED — `agent/quest_runtime.py:94` gates MAIN_CAMPAIGN mode and `agent/next_quest_resolver.py::NextQuestResolver` requires an explicit addon-confirmed campaign flag; tested in `tests/test_m1_next_quest_resolver.py`. |
| V4-047 | QUEST ACQUISITION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:1995) | IMPLEMENTED_TESTED — `agent/quest_offer_selector.py::QuestOfferSelector` and `agent/quest_dialog_planning.py` implement locate→gossip/offer detect→select→verify pipeline; tested in `tests/test_m1_quest_offer_selector.py`, `tests/test_quest_dialog_fast_lane.py`. |
| V4-048 | FIELD / REMOTE QUEST COMPLETION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2022) | IMPLEMENTED_TESTED — `agent/quest_runtime.py:201-221` classifies NPC_TURN_IN/FIELD_TURN_IN/AUTO_COMPLETE/SPECIAL_UI exactly per spec; covered in `tests/test_m1_primary_quest_runtime.py`. |
| V4-049 | SPEAK / INTERACT NPC OBJECTIVE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2042) | IMPLEMENTED_TESTED — `agent/quest_model.py::ObjectiveClassifier` produces SPEAK kind, paired with `agent/objective_locator.py` and `verification/quest.py::QuestProgressVerifier`; tested in `tests/test_m1_objective_classifier.py`, `tests/test_m1_objective_locator.py`. |
| V4-050 | KILL OBJECTIVE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2069) | IMPLEMENTED_TESTED — `agent/combat_planning.py` gates COMBAT proposals on quest-relevance/credit and `QuestObjective.current_count` drives completion (`agent/quest_model.py:99,207`); tested in `tests/test_combat_planning_policy.py`. |
| V4-051 | COLLECT OBJECTIVE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2093) | OFFLINE_VERIFIED — `CollectStrategyTracker` maintains per-objective GROUND_OBJECT/MOB_LOOT/DIRECT_INTERACT/QUEST_ITEM_MECHANIC/SCRIPTED/UNKNOWN belief. `QuestTerminalProcessor` strengthens/weakens it only from quest-credit outcomes, and the canonical Planner now consumes it before global ranking through `QuestDomain.apply_collect_strategy()`. Guidance only adds a bounded confidence-scaled bonus to already-existing proposals; UNKNOWN changes nothing and alternatives are never suppressed or fabricated. Tested in `test_collect_strategy.py` and `test_collect_strategy_wiring.py`. |
| V4-052 | INTERACT OBJECT OBJECTIVE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2122) | IMPLEMENTED_TESTED — `skills/object_use.py::ObjectUseSkill`; tested in `tests/test_m1_object_use_skill.py`. |
| V4-053 | QUEST ITEM / TOOL BUTTON OBJECTIVE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2138) | PARTIAL / OFFLINE_TESTED — `agent/quest_tool_resolver.py::QuestToolResolver` shares exact active-quest/item/selected-GUID public range/usability/cooldown evidence; canonical `skills/quest_item.py::UseItemSkill` rechecks it, supports verified item/actionbar/bag activation and quest-credit-only success. `skills/quest_tool.py::ExtraActionHandler` remains a separate resolver for explicitly identified Extra Action UI, not proof of universal quest-tracker tool-button discovery. New dated 20261018/20261019 tests cover unknown/stale/conflicting evidence, bounded FAST, local ownership, live-shaped Re-Sizer and Giant recovery; existing M1/core coverage remains. Real Re-Sizer state progress is observed in the user's 2026-10-19 run, but generic tracker discovery, final-source live API availability and broad M1 acceptance remain unresolved. |
| V4-054 | EXTRA ACTION BUTTON (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2165) | IMPLEMENTED_TESTED — `agent/quest_planning.py:152-180` detects/gates extra_action against configured allow_extra_action/extra_action_type/extra_action_id; tested in `tests/test_m1_extra_action_skill.py`. |
| V4-055 | VEHICLE / OVERRIDE BAR QUESTS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2183) | IMPLEMENTED_TESTED — `skills/vehicle.py::VehicleSkill` added: detect VEHICLE_OVERRIDE -> issue configured vehicle-specific BIND actions -> verify quest progress -> on exit mid-attempt, fail without faking success (invalidates vehicle state rather than claiming completion); `rotation_allowed()`/`is_vehicle_override_active()` expose the literal "do not let normal rotation fire into a vehicle override state" guard as a reusable predicate. Complements existing `InvalidationEvent.VEHICLE` context-reset in `runtime/state_invalidation.py`. Tested in `tests/test_vehicle_skill.py`. Not yet wired into `runtime/m0_dispatch.py` or called from `CombatSkill`'s rotation. |
| V4-056 | GOSSIP CHOICE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2205) | IMPLEMENTED_TESTED — `agent/quest_offer_selector.py::QuestOfferSelector.select` requires unambiguous/explicit selection else `quest_offer_selection_required`, used by `agent/quest_dialog_planning.py:70`; tested in `tests/test_m1_quest_offer_selector.py`. |
| V4-057 | DEFEND / WAIT / SCRIPTED EVENT (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2225) | IMPLEMENTED_TESTED — DEFEND is a first-class skill with contract (`agent/skills.py:147`) and planning logic (`agent/combat_planning.py:166`); WAIT/DEFEND/ESCORT tracked as objective events in `agent/quest_model.py:182`; tested in `tests/test_combat_planning_policy.py`, `tests/test_v5_m3_adaptive_quest_environment.py`. |
| V4-058 | FOLLOW / ESCORT (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2246) | IMPLEMENTED_TESTED — `agent/navigation_planning.py` implements following-distance-band logic with leader identity checks; tested in `tests/test_follow_distance_band.py`. |
| V4-059 | TRAVEL / REACH AREA (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2263) | IMPLEMENTED_TESTED — `agent/objective_locator.py::ObjectiveLocationStatus` values (LOCAL_MARKER, WORLD_MAP_LOCATION, KNOWN_LOCATION, SEARCH_AREA) match spec's location hierarchy; tested in `tests/test_m1_objective_locator.py`. |
| V4-060 | MULTI-STAGE QUESTS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2290) | IMPLEMENTED_TESTED — `agent/quest_runtime.py:238-245` recomputes stage_signature/stage_revision on every credit change, invalidating stale objective beliefs; tested in `tests/test_m1_primary_quest_runtime.py`. |
| V4-061 | TURN-IN (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2317) | IMPLEMENTED_TESTED — `agent/turnin_resolver.py::TurnInResolver` implements an evidence-ordered hierarchy (FIELD_UI→LOCAL_ENTITY→TURN_IN_LOCATION→QUEST_API_REGION→UNKNOWN); tested in `tests/test_m1_turnin_resolver.py`. |
| V4-062 | REWARD SELECTION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2343) | IMPLEMENTED_TESTED — `agent/quest_reward_selector.py::QuestRewardSelector` requires explicit policy or blocks with `reward_selection_policy_required`; tested in `tests/test_m1_quest_reward_selector.py`. |
| V4-063 | NEXT QUEST / CHAIN CONTINUATION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2360) | PARTIAL / OFFLINE_TESTED — `next_quest_source_hierarchy.py` and `WorldQuery.next_quest_source()` retain the ordered UI/same-NPC/local-marker/log/map/campaign projection without assuming same-NPC availability; the narrow `NextQuestResolver` still requires explicit campaign evidence. `QuestAgenda` now preserves verified turn-in continuation, supplies known-empty-log discovery, previews conditional offer/read/work/turn-in/discovery, and consumes existing Planner proposals. Addon 0.9.68 refreshes availability after quest changes; map discovery precedes unrelated bodies and API giver MOVE retains attention. Tested by source-hierarchy/world-query tests plus `test_agenda_continuation_20261019.py` and `test_quest_discovery_priority_20261019.py`. PID-5292 exposed the old live failure; correction is not yet live-validated. Static/remembered next IDs remain candidates, never acceptance authority. |
| V4-064 | MAP / MINIMAP / 3D RELOCALIZATION LOOP (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2379) | IMPLEMENTED_TESTED — `agent/quest_location_planning.py::propose_objective` branches on LOCAL_MARKER/WORLD_MAP_LOCATION/KNOWN_LOCATION/SEARCH_AREA mirroring the spec loop; exercised via `tests/test_m1_objective_locator.py`, `tests/test_navigation_proposal_adapter.py`, `tests/test_search_region_engine_handoff.py`. |
| V4-065 | SEARCH COVERAGE MEMORY (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2419) | IMPLEMENTED_TESTED — `navigation/search_coverage.py::SearchCoveragePlanner` tracks visited grid cells/visits, wired into `navigation/service.py`; tested in `tests/test_search_coverage.py`, `tests/test_search_region_engine_handoff.py` (no explicit tracking of failed entities/entrances as sub-fields). |
| V4-066 | PHASING / LOADING / TELEPORT (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2443) | IMPLEMENTED_TESTED — `runtime/state_invalidation.py::StateInvalidationPolicy` detects LOADING/TELEPORT/MAP_CONTEXT/PHASE/FLOOR transitions and resets visual/navigation context while preserving quest state; tested in `tests/test_state_invalidation.py`. |
| V4-067 | CINEMATIC HANDLING (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2469) | IMPLEMENTED_TESTED — `runtime/supervisor.py` gates `cinematic_playing` into the existing CRITICAL_RECOVERY state (blocks gameplay input, emits `CINEMATIC_STARTED` matching the pre-existing `events.py:38` priority entry, `FailureReason.CINEMATIC_PLAYING`); `runtime/state_invalidation.py::InvalidationEvent.CINEMATIC` fires on the falling edge (cinematic ending) and forces `invalidate_objective=True` alongside the standard context reset, refreshing WorldModel + quest state per spec; `runtime/cinematic_policy.py::CinematicSkipPolicy` is disabled by default and rate-limits/bounds skip attempts when opted in, so it can never spam skip input; tested in `tests/test_cinematic_handling.py`. Wired: `Supervisor.__init__(*, cinematic_skip_enabled=False)` now owns a live `cinematic_skip_policy` instance (still disabled by default, zero behavior change unless a caller opts in); `evaluate()`'s `cinematic_playing` branch calls `cinematic_skip_policy.reset()` exactly on the rising edge into CRITICAL_RECOVERY-via-cinematic (not on every tick while already inside it), and the new `Supervisor.cinematic_skip_decision(cinematic_playing=, now=)` exposes the bounded, rate-limited decision for a caller to act on -- the Supervisor itself still never presses input. Tested in `tests/test_cinematic_handling.py` (rising-edge reset, no reset mid-cinematic, disabled-by-default). |
| V4-068 | PLAYER DEATH / RECOVERY (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2487) | PARTIAL / OFFLINE_TESTED — shared Supervisor blocks ordinary work on death; DeathRecoveryPolicy owns exported release/reclaim buttons and common corpse navigation. The 2026-10-28 mounted-ghost MMAP handoff, bounded descent and ghost-state cancellation fixes have regression and retained-state replay evidence; user-run corpse travel/resurrection are pending. See the dated ledger note and LIVE_VALIDATION.md. |
| V4-069 | COMBAT INTERRUPTS QUEST INTERACTION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2511) | IMPLEMENTED_TESTED — `runtime/supervisor.py:208-211` issues REPLAN/suspend_active with COMBAT_STARTED reason when unexpected combat begins during a non-combat active skill; tested in `tests/test_supervisor.py`. |
| V4-070 | OBJECTIVE CREDIT FAILURE STRATEGY (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2535) | IMPLEMENTED_TESTED — `agent/credit_failure_escalation.py::CreditFailureEscalation` adds the tiered 1st (RECHECK) / 2nd (REDUCE_CONFIDENCE_CHANGE_CANDIDATE) / repeated (ESCALATE_TO_CLASSIFIER_OR_LOCATOR) / bounded (BLOCKED_UNSUPPORTED) ladder, maintaining the spec's named `failed_credit_candidates[]`/`failed_strategy_attempts[]` lists per (quest_id, objective_id); complements the existing single-target suppression in `agent/quest_planning.py::record_uncredited_target/credit_gate` and `agent/quest_failure_memory.py::QuestFailureMemory`; tested in `tests/test_credit_failure_escalation.py`. Not yet wired into `QuestDomain.propose()`. |
| V4-071 | PLANNER ANTI-LOOP RULE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2561) | IMPLEMENTED_TESTED — `runtime/loop_guard.py` (`LoopGuard`, signature-based repeat-failure detection) wired via self.loop_guard/last_plan_signature in `agent/engine.py:126,134,729-856`; covered by `tests/test_loop_guard.py`. |
| V4-072 | SUPERVISOR PRIORITY ORDER (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2578) | IMPLEMENTED_TESTED — `Supervisor`/`SupervisorStateSpec.priority` in `runtime/supervisor.py:12-221` enforces ordered gating; `tests/test_supervisor.py` (e.g. test_minimum_preemption_matrix_is_explicit_and_priority_safe). |
| V4-073 | EVENT BUS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2598) | IMPLEMENTED_TESTED — `EventBus` with named critical/coalescible events and priorities in `runtime/events.py:17-44`; emitted events like SKILL_PHASE_CHANGED in `runtime/active_skill.py:166`; tested in `tests/test_runtime_event_bus.py`. |
| V4-074 | THREADING / CONCURRENCY (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2643) | IMPLEMENTED_TESTED — Locks/threads centralized (threading.Thread watchdog in `execution/input_scheduler.py:35`; locks in engine/executor/sensor/live_capture); single-authority separation enforced by `tests/test_architecture_boundaries.py`. |
| V4-075 | EXECUTOR CONTRACT (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2670) | IMPLEMENTED_TESTED — `CommandDispatcher`/`stop_movement` in `execution/command_dispatch.py:14-56`, key-up cleanup/watchdog/cancellation in `execution/input_scheduler.py`; tested by `tests/test_command_dispatch.py`, `tests/test_input_scheduler.py`. |
| V4-076 | SAFE STOP (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2701) | IMPLEMENTED_TESTED — SAFE_STOP failure-reason mapping in `runtime/failures.py:86-88`; dedicated `tests/test_m0_safe_stop.py::test_executor_exception_forces_manual_safe_stop_and_finalizes_active_skill`. |
| V4-077 | ERROR HANDLING (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2718) | IMPLEMENTED_TESTED — Audited all 5 flagged sites: `spawn_catalog.py`'s two `except Exception:` blocks were a false positive (they `rollback()` + `raise`, not a silent swallow). The 4 genuine silent-swallow sites — `agent/dxgi_capture.py::close()`, `agent/memory.py::AgentMemory.close()`, `vision/entity_memory.py::EntityMemory.close()`, `vision/world_point_memory.py::WorldPointMemory.close()` — all guard resource-release-on-shutdown, so they still must not raise (would mask the caller's own shutdown), but now log via `logging.getLogger(__name__).warning(..., exc_info=True)` instead of silently hiding the failure. Typed `FailureManager`/`FailureReason` (`runtime/failures.py:50`) still own the recoverable-error path. Tested in `tests/test_error_handling_v4_077.py` (3 of 4 sites; `dxgi_capture.py` has no existing DXGI-mockable test harness). |
| V4-078 | STRUCTURED LOGGING (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2738) | IMPLEMENTED_TESTED — `StructuredLogger`/`StructuredLogEntry` in `runtime/structured_logger.py:9-47`; tested in `tests/test_structured_logger.py`. |
| V4-079 | REPLAY SYSTEM (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2769) | IMPLEMENTED_TESTED — `tests/test_m0_replay_contract.py::test_active_skill_runtime_never_admits_a_second_action_across_100_replays` and `tests/test_screenshot_session_replay.py` exercise deterministic replay; replay-related state in `agent/runtime.py`, `perception.py`, `memory.py`. |
| V4-080 | DEBUG OVERLAY (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2796) | IMPLEMENTED_TESTED — `AgentStatusProjection.build` (active_skill, vision_seek, skill_lifecycle) in `agent/status_projection.py:18-90`, GUI in `agent/gui.py`; tested by `tests/test_gui_status_bounds.py`, `tests/test_status_payload_bounds.py`. |
| V4-081 | REPOSITORY REFACTOR TARGET (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2823) | IMPLEMENTED_TESTED — Modular top-level dirs (runtime/, skills/, navigation/, verification/, vision/, execution/) roughly matching the target shape; responsibility boundaries enforced by `tests/test_architecture_boundaries.py` (20+ boundary tests). |
| V4-082 | PLANNER BREAKUP (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2898) | IMPLEMENTED_TESTED — Planner decomposed into domain modules (`quest_planning.py::QuestDomain`, `recovery_planning.py::RecoveryPlanner`, `combat_planning.py`, `navigation_planning.py`, `target_planning.py`, `planning_orchestration.py::PlanningOrchestrator`); boundary tests in `tests/test_architecture_boundaries.py`, `tests/test_recovery_planner.py`. |
| V4-083 | ENGINE/RUNTIME BREAKUP (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2921) | OFFLINE_VERIFIED — recognition stabilization, perception geometry/update, observation projection, diagnostics/maintenance/status, selected-PID safety, engine runtime projection, WorldModel trace projection and WorldModel prediction lifecycle now live in focused authority-neutral modules. `AgentRuntime` remains the sole orchestrator and the canonical agent retains the single ingest/plan/dispatch/finalize authorities. Static regressions forbid dispatcher/input/planner construction and skill finalization in the extracted phases. `runtime.py` is 542 lines (was 981), `engine.py` 891 (was 952), and `world.py` 827 (was 952). Locked by `tests/test_v4_083_095_module_size_reduction.py`, runtime/architecture suites and the full **1644 passed, 4 skipped** regression. |
| V4-084 | LEGACY / DEAD CODE AUDIT (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2938) | `OFFLINE_VERIFIED` — `docs/DEAD_CODE_AUDIT.md` records the retained adapters and removed duplicate lifecycle owner; `src/legacy_logging` remains isolated and `agent/skill_lifecycle.py` is absent. `tests/test_required_documentation_contract.py` locks the audit artifact and isolation/removal facts. |
| V4-085 | CONFIGURATION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2962) | IMPLEMENTED_TESTED — `TimeoutPolicy`/`RetryPolicy` centralize thresholds in `runtime/policies.py:10-38`; tested via `tests/test_m0_policies.py`. |
| V4-086 | PERFORMANCE RULE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:2990) | IMPLEMENTED_TESTED — `PerformanceMonitor` (latency/capture/queue-depth observation, no control authority) in `runtime/performance.py:21-97`; tested in `tests/test_runtime_performance.py`. |
| V4-087 | M0 UNIT TEST MATRIX (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3007) | IMPLEMENTED_TESTED — Dedicated files cover ActiveSkill/Movement/Interact/Combat/Loot/Search/SafeStop: `tests/test_m0_target_skill.py`, `test_m0_interact_skill.py`, `test_m0_interact_face_recovery.py`, `test_m0_combat_loot_skills.py`, `test_m0_search_skill.py`, `test_m0_safe_stop.py`, `test_active_skill_runtime.py`. |
| V4-088 | M1 UNIT TEST MATRIX (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3069) | IMPLEMENTED_TESTED — Dedicated files cover Classifier/WorldMap/Minimap/ObjectiveLocator/QuestProgressVerifier: `tests/test_m1_objective_classifier.py`, `test_m1_objective_locator.py`, `test_m1_quest_progress_verifier.py`, `test_world_map_calibration.py`, `test_minimap_m74.py`. |
| V4-089 | M1 INTEGRATION SCENARIOS (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3116) | OFFLINE_VERIFIED — all 25 scenarios have explicit regression evidence in `test_m1_integration_scenarios_index.py`. Scenario 16 now has a direct two-state regression in `test_agent_map_discovery.py`: a prior minimap cue disappears at the objective search area, and the planner selects bounded local `SEEK_VISUAL_CUE` rather than declaring failure or reopening the map. This remains deterministic offline evidence, not a live questline claim. |
| V4-090 | M0 COMPLETION GATE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3149) | IMPLEMENTED_TESTED — `tests/test_m0_completion_gate.py` turns all 11 DONE criteria into one automated check against concrete artifacts (one ActiveSkill authority, canonical NavigationService, the six deterministic skills, typed result/failure system, retry/timeout policies, the full 7-module verification split, safe cancellation, safe stop, replay test support, legacy CombatController authority removal per `docs/DEAD_CODE_AUDIT.md`), plus an explicit assertion that the gate does not itself claim live validation. `docs/M0_ACCEPTANCE_MATRIX.md` still documents the "offline replay foundation; not live-validated" status in prose. |
| V4-091 | M1 COMPLETION GATE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3170) | OFFLINE_VERIFIED — `tests/test_m1_completion_gate.py` binds every named capability to its production owner and requires all 25 deterministic scenario rows to have evidence. The gate explicitly reads `docs/M1_QUEST_EXECUTION.md` and requires its live-incomplete statement, so offline completeness cannot be misreported as selected-PID completion. |
| V4-092 | EXILE'S REACH / STARTING-ZONE ACCEPTANCE PRINCIPLE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3194) | IMPLEMENTED_TESTED — `navigation/exile_reach_seed.py` plus `tests/test_exile_reach_starting_mechanics.py` (generic objective-type tests: vendor, cooking, training, quest item) validate generic capability handling. |
| V4-093 | IMPLEMENTATION ORDER (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3222) | UNCLEAR — Pure process/phase-sequencing checklist (Phase 0 through Phase T) for the coding agent's workflow; not a code artifact to trace. |
| V4-094 | PHASE DONE CONTRACT (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3317) | UNCLEAR — Process/reporting checklist (CHANGED FILES, TESTS ADDED, etc.); no corresponding source code to audit. |
| V4-095 | CODING RULES (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3345) | `OFFLINE_VERIFIED` — modular design, typed state and dependency injection are enforced for new work. The formerly oversized observation/perception middle of `AgentRuntime.step` is now split into `runtime_perception_phase.py` and `runtime_observation_phase.py`; recognition, diagnostics/status, safety and engine projection already live in their focused modules. WorldModel trace and prediction concerns are independently extracted. `runtime.py` is 542 lines (was 981), `world.py` 827 (was 952), and `engine.py` 891 (was 952). Static authority tests prove the extracted runtime phases cannot dispatch input, construct a Planner/SkillExecutor, or finalize a skill; behavior is covered by runtime, scheduler, World3D-fusion and memory tests plus the full **1644 passed, 4 skipped** regression. This is offline architecture evidence, not selected-PID live validation. |
| V4-096 | DO NOT LIE ABOUT VALIDATION (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3368) | `OFFLINE_VERIFIED` — the source ledger distinguishes `OFFLINE_VERIFIED`/`OFFLINE_PARTIAL` and explicitly retains selected-PID work as live-open; live evidence stays in `docs/LIVE_VALIDATION.md`. `tests/test_required_documentation_contract.py` locks this vocabulary without converting offline results into live claims. |
| V4-097 | REQUIRED FINAL DELIVERABLES (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3388) | `OFFLINE_VERIFIED` — all named, nonempty deliverables are present: `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/M0_IMPLEMENTATION.md`, `docs/M1_QUEST_EXECUTION.md`, `docs/MIGRATION.md`, `docs/DEAD_CODE_AUDIT.md`, `docs/TEST_REPORT.md`, `docs/KNOWN_LIMITATIONS.md`. Presence/nonempty regressions are enforced by `tests/test_required_documentation_contract.py`. |
| V4-098 | FINAL OWNERSHIP TABLE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3411) | IMPLEMENTED_TESTED — Roles map to distinct modules: ObjectiveLocator (`agent/objective_locator.py`), world-map/minimap resolvers (`vision/world_map_calibration.py`, `minimap_geometry.py`), Supervisor, QuestProgressVerifier (`verification/quest.py`); separation enforced by `tests/test_architecture_boundaries.py`. |
| V4-099 | THE MOST IMPORTANT QUEST RULE (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3462) | IMPLEMENTED_TESTED — `ObjectiveLocator.locate` fallback chain (local entity match → objective/known location → location-candidate memory → search area → transition-required → unknown) in `agent/objective_locator.py:22-59`; tested in `tests/test_m1_objective_locator.py`. |
| V4-100 | FINAL COMMAND TO THE CODING AGENT (wow_agent_FINAL_M0_M1_master_prompt_v4.txt:3491) | UNCLEAR — Meta-instruction/summary directive to the coding agent about process discipline (no parallel controllers, don't assume success, etc.); not a discrete code requirement to trace to source. |
| DESIGN-001 | RENDSZERSZINTŰ ARCHITEKTÚRA (wow_agent_complete_functional_design_spec.txt:93) | UNCLEAR — pure architecture-layer enumeration (19 named layers + dependency-direction diagram), not a discrete testable requirement. The layering is realized structurally (capture: `agent/sensor.py`/`dxgi_capture.py` -> perception: `agent/perception.py` -> `agent/world.py` (WorldModel) -> `agent/world_query.py` -> `agent/goal_manager.py`/`runtime/supervisor.py`/`agent/planner.py` -> `runtime/active_skill.py` -> `skills/*.py` -> `execution/command_dispatch.py`), enforced at the boundary level by `tests/test_architecture_boundaries.py` (28 static import/source-grep assertions), but there is no single "system architecture" artifact to verify beyond that boundary suite. |
| DESIGN-002 | GLOBÁLIS ARCHITEKTURÁLIS INVARIÁNSOK (wow_agent_complete_functional_design_spec.txt:157) | `OFFLINE_VERIFIED` — `runtime/architecture_invariants.py` now contains one traceable registry entry for every INV-01…INV-20, naming its single owner and concrete enforcement evidence. The registry is not authority; it points to the production owners and tests. `tests/test_global_architecture_invariants.py` requires the exact complete ID set and existing evidence artifacts, and adds direct behavioral gates for INV-13 (finite FailureManager escalation through GOAL_FAILED) and INV-14 (finite sector/time visual search). Existing authority, safe-stop, stage/context invalidation, quest-credit separation, DecisionFingerprint, coordinate-space, UNKNOWN-first normalization and cue-navigation suites cover the remaining entries. Complete regression **1714 passed, 4 skipped**. Live behavior remains separately gated. |
| DESIGN-003 | KÖZÖS ADATMODELL (wow_agent_complete_functional_design_spec.txt:222) | `OFFLINE_VERIFIED` — common evidence-graph value objects now live in the dedicated `agent/world_models.py`: `Evidence` exposes stable ID, kind, value, confidence/reliability, freshness/age/effective-confidence functions and related entity/quest/objective references; typed immutable `Belief` carries status/value/confidence/evidence refs/contradictions/source/tier/resolution/context; `ContradictionRecord` and `WorldRelation` remain typed. `WorldModel.typed_belief()`/`WorldQuery.typed_belief()` provide the new contract while legacy dict `belief()` remains compatible. `Observation` now projects sensor, observation type and explicit/inferred coordinate space without changing its immutable JSON payload. `SkillResult`/`VerificationResult` remain in `runtime/contracts.py`. The models were extracted rather than enlarging `world.py`, which remains 793 lines under the architecture gate. Tests: `tests/test_common_data_model.py`; complete regression **1706 passed, 4 skipped**. |
| DESIGN-004 | EVENT BUS TERV (wow_agent_complete_functional_design_spec.txt:356) | `OFFLINE_VERIFIED` — `runtime/events.py` implements `publish()`/`publish_critical()`/`subscribe()` with dedupe-by-`event_id` and priority ordering; `runtime/contracts.py:81` `RuntimeEvent` carries event_type/at/metadata/event_id/source/correlation_id. Covered by `tests/test_runtime_event_bus.py` (8 tests: dedup, safety-before-observation ordering, correlated skill lifecycle idempotence, critical-event-never-dropped-under-full-queue, thread-safety). Selected-PID cross-process event ordering under live load remains live-open. |
| DESIGN-005 | SENSOR / CAPTURE RÉTEG (wow_agent_complete_functional_design_spec.txt:453) | OFFLINE_VERIFIED — `agent/sensor_hub.py::SensorHub` is the unified live-runtime owner for sensor lifecycle, latest-value freshness, health/failure state and rate control (`start/stop/poll_latest/publish_frame/sensor_health/set_rate/mark_sensor_failure`). `AgentRuntime` wraps its proven bounded `BufferedPixelSensor` in this hub, retaining the existing background capture and selected-PID behavior without adding a second perception loop. Covered by `tests/test_sensor_hub.py`, `tests/test_agent_buffered_sensor.py`, `tests/test_capture_backend_selection.py` and runtime tests; selected-PID sustained-rate proof remains live-open. |
| DESIGN-006 | PERCEPTION ORCHESTRATOR (wow_agent_complete_functional_design_spec.txt:522) | `OFFLINE_VERIFIED` — `agent/perception_pipeline.py::PerceptionPipeline` now provides the named `process_frame`/`process_world3d`/`process_minimap`/`process_world_map`/`process_ui`/`fuse`/`publish` contract. `PerceptionWorker` production scheduling dispatches through it, selects exactly one primary surface, suppresses minimap work while World Map is open, and retains one-in-flight/latest-frame backpressure. It delegates dynamically to the existing detector authorities rather than storing or duplicating detection state. Covered by `tests/test_perception_component_owners.py`, scheduler and perception regressions. Selected-PID cadence remains live-open. |
| DESIGN-007 | WORLD 3D PERCEPTION TERV (wow_agent_complete_functional_design_spec.txt:551) | `OFFLINE_VERIFIED` — the named stage seams now exist and are production-wired: `WorldSceneExtractor` creates the HUD-excluding ROI; `WorldCandidateDetector` delegates to the sole configured V3 detector; `WorldCandidateTracker` owns appearance/camera/motion association and now exposes `get_track`/`recent_tracks`/`lost_tracks`/`invalidate_all`; `SemanticFusion` is the canonical evidence-only facade over V4 fusion; `TargetedOCR` remains ROI/event-driven; `World3DValidator` delegates to the non-mutating batch validator. UNKNOWN-first semantics and source identity remain unchanged. Covered by `tests/test_perception_component_owners.py` and the existing World3D pipeline/tracking/validation suites. |
| DESIGN-008 | MINIMAP PERCEPTION TERV (wow_agent_complete_functional_design_spec.txt:657) | `OFFLINE_VERIFIED` — `vision/minimap_perception.py` now contains the named `MinimapDetector`, `MinimapTracker` and `MinimapResolver` beside the existing `MinimapGeometry`. Production marker association passes through `MinimapTracker`, which receives the existing shared `VisualTrackManager`; it therefore creates no second identity authority. Resolver methods expose best cue, local direction, trend and non-fatal disappearance interpretation while marker semantics remain hypotheses. Existing circle/rim/player-centre contracts and all minimap detector regressions remain intact. |
| DESIGN-009 | WORLD MAP PERCEPTION TERV (wow_agent_complete_functional_design_spec.txt:732) | `OFFLINE_VERIFIED` — `vision/world_map_perception.py` provides the named `WorldMapStateDetector`, `WorldMapMarkerDetector`, `MapContextResolver`, `MapMouseoverResolver` and production-wired `WorldMapResolver`. The resolver now exposes the full input-free contract: open/close requests, context resolution, quest/turn-in/parent evidence selection, bounded wrong-zoom recovery (maximum five zoom steps), mouseover normalization and best-evidence ranking. Existing calibration, graph vision, absence resolver and TDB-last-resort policy remain authoritative and no perception component dispatches input. Focused map/component suite passed 33 tests; complete suite **1728 passed, 4 skipped**. Selected-PID marker filtering and timing remain live acceptance gates, not offline implementation gaps. |
| DESIGN-010 | CROSS-VIEW FUSION (wow_agent_complete_functional_design_spec.txt:802) | `OFFLINE_VERIFIED` — `agent/cross_view.py::CrossViewResolver` is now the production runtime owner and extends the existing conservative `CrossViewAssociator`. It exposes map↔minimap, minimap↔World3D, tooltip↔track and exact addon-target↔entity association, explicit conflict downgrading, and best-identity selection. Appearance/color alone still cannot link surfaces; inferred links remain UNKNOWN/CANDIDATE and never use an unvalidated coordinate transform, while only an exact addon target GUID yields CONFIRMED identity. Focused cross-view/runtime tests passed 39 tests; complete suite **1731 passed, 4 skipped**. Live cross-surface calibration remains a separate acceptance gate. |
| DESIGN-011 | WORLD MODEL (wow_agent_complete_functional_design_spec.txt:839) | `OFFLINE_VERIFIED` — `agent/world.py:208` `WorldModel` matches the spec's authority boundary closely: `ingest()` (812), `add_evidence()` (685), `prune_expired_evidence()` ~ expire_evidence (787), `belief()` ~ update_belief (733), `link()` ~ record_relation (500), `_world_prediction()`/`record_action_graph()`/`record_verification_graph()` ~ record_prediction, `_emit_derived_event()` (307), `snapshot()`/`planning_snapshot()` (872). It contains no `plan()`/`move()`/`interact()`/`combat()` methods (confirmed absent), matching the spec's "Nem" list. Read-only boundary is separately enforced by `agent/world_query.py` and tested by `tests/test_world_state_contract.py`, `tests/test_world_snapshot_v2.py`. Selected-PID long-session evidence-expiry behavior remains live-open. |
| DESIGN-012 | WORLD QUERY API (wow_agent_complete_functional_design_spec.txt:871) | `OFFLINE_VERIFIED` — `agent/world_query.py::WorldQuery` implements the large majority of the spec's named queries: `player()`, `target()`, `ui_context()`, `entity()`, `find_entities()`, `entity_locations()`/`get_entity_locations()`, `entity_roles()`, `visual_tracks()` ~ recent_visual_tracks, `map_markers()` ~ world_map_state/minimap_state, `get_best_search_region()`, `get_recent_failures()`, `get_sensor_health()`, `navigation_cue()` ~ navigation_context, `get_world_uncertainties()` ~ uncertainties. It is explicitly deepcopy-guarded read-only (no `ingest`/mutation methods present). Minor gaps: no literal `combat()` or `current_quest()`/`active_quests()`/`current_objective()` methods (covered instead by `get_current_quest_objectives()`). Covered by `tests/test_world_query_evidence_freshness_wiring.py`, `test_world_query_navigation_cue_wiring.py`, `test_world_query_next_quest_source_wiring.py`, `test_world_query_ui_context_wiring.py`. Selected-PID live query-latency under full sensor load remains live-open. |
| DESIGN-013 | PLAYER STATE (wow_agent_complete_functional_design_spec.txt:903) | `OFFLINE_VERIFIED` — `WorldQuery.player()` now also returns `moving` (from real `state.is_moving`), `vehicle` (from real `state.in_vehicle`/`vehicle_ui`/`vehicle_camera`, the same OR-check `skills/vehicle.py::is_vehicle_override_active` uses), and `subzone` (from real addon-exported `state.subzone_name`, `AIPlayerControllerExport.lua:1318`), alongside the existing map_id/position/orientation/health/max_health/power/max_power/is_mounted/is_in_combat/is_dead/is_ghost/is_casting. `control_mode` is deliberately NOT projected: it is agent-level control authority (`AutonomousAgent.mode` in `agent/engine.py`), and folding it into this read-only WorldModel projection would blur the same WorldModel/agent boundary this codebase enforces elsewhere. Tested in new `tests/test_world_query_player_state_wiring.py` (3 tests) plus existing `tests/test_world_state_contract.py`/`test_world_snapshot_v2.py`. |
| DESIGN-014 | UI CONTEXT RESOLVER (wow_agent_complete_functional_design_spec.txt:933) | OFFLINE_VERIFIED — `UiContextResolver` now supplies the full stateful contract: monotonic `resolve`, fail-closed `is_blocking`, `stable_for(ms)`, accept/turn-in/world-interact capability gates and explicit `invalidate`. `WorldQuery` owns the canonical read-only resolver instance, and QuestDialog refuses input under every blocking state. Covered by `tests/test_ui_context.py`, `tests/test_world_query_ui_context_wiring.py` and `tests/test_m1_quest_dialog_skill.py`; selected-PID transition timing remains live-open. |
| DESIGN-015 | QUEST STATE NORMALIZER (wow_agent_complete_functional_design_spec.txt:982) | `OFFLINE_VERIFIED` — `agent/quest_model.py::QuestModel` implements `ingest()` (merges tracker/API objectives, builds history-signature stage-change detection at line 176-183), `apply_event()` (turn-in/complete/abandon transitions), `ready()`/`readiness()` (quest_graph-backed), `graph()`, `snapshot()`, plus `QuestRecord`/`QuestObjective` dataclasses matching the spec's QuestState/QuestObjective fields (tracked/completed/ready_for_turn_in ~ lifecycle_state, objectives[], confidence, credit_history ~ history). Backed by `agent/quest_graph.py::QuestGraph` and `agent/quest_state.py`. Covered by `tests/test_quest_model.py` (15 tests) and `tests/test_quest_understanding_patch.py`. Selected-PID live quest-tracker desync scenarios remain live-open. |
| DESIGN-016 | QUEST OBJECTIVE CLASSIFIER (wow_agent_complete_functional_design_spec.txt:1031) | `OFFLINE_VERIFIED` — `agent/quest_model.py::ObjectiveClassifier.classify()` (line 73) implements a real 3-tier resolver (ADDON_NORMALIZED type -> QUEST_API_TYPE -> TEXT_PATTERN regex, English+Hungarian) producing `ObjectiveClassification(type, confidence, evidence, canonical_kind)`, with `UNKNOWN` an explicit legitimate outcome (confidence 0 or .45) matching the spec's rule. `OBJECTIVE_TYPES` set covers all 24 spec-named types (SPEAK ~ TALK_TO, KILL, KILL_NAMED, COLLECT, LOOT, TRAVEL ~ TRAVEL_TO, REACH_AREA, FIELD_TURN_IN, MULTI_STAGE, etc). Tested by `tests/test_m1_objective_classifier.py` (2 tests) and `tests/test_objective_classifier_v4_016_types.py` (4 tests covering the V4-016 additive types). |
| DESIGN-017 | OBJECTIVE LOCATOR (wow_agent_complete_functional_design_spec.txt:1078) | `OFFLINE_VERIFIED` — `agent/objective_locator.py::ObjectiveLocator.locate()` implements the spec's priority chain in one method: validated local entity match (`_matches`) -> objective-API location -> quest known_locations -> location-candidate memory -> search_area -> transition_required -> UNKNOWN, returning `ObjectiveLocation(status, coordinates, confidence, evidence)` using the spec's exact `ObjectiveLocationStatus` enum (`runtime/contracts.py:125`: LOCAL_ENTITY/LOCAL_OBJECT/LOCAL_MARKER/WORLD_MAP_LOCATION/KNOWN_LOCATION/SEARCH_AREA/TRANSITION_REQUIRED/UNKNOWN). It is one consolidated method rather than the spec's separate `locate_local()`/`locate_from_minimap()`/`locate_from_world_map()`/`locate_from_memory()`/`build_search_area()` functions. Tested by `tests/test_m1_objective_locator.py` (5 tests). |
| DESIGN-018 | GOAL MANAGER (wow_agent_complete_functional_design_spec.txt:1121) | `OFFLINE_VERIFIED` — `agent/goal_manager.py::GoalManager` implements `set_goal()`, `transition()` (status/reason lifecycle ~ suspend/resume/complete/fail_goal), `snapshot()` (line 238), backed by `GoalTask`/`GoalLifecycleEvent` dataclasses with relevance/progress/cost/risk/uncertainty/expected_reward scoring not in the spec but additive. It contains no input-dispatch or skill-steering calls (matches "Nem feladata: skill steering"). Tested by `tests/test_goal_domain_manager.py` (13 tests). Selected-PID long-running goal-priority drift under live combat interrupts remains live-open. |
| DESIGN-019 | SUPERVISOR (wow_agent_complete_functional_design_spec.txt:1156) | `OFFLINE_VERIFIED` — `runtime/supervisor.py::Supervisor.evaluate()` implements the spec's exact priority order (death/ghost -> disconnect -> loading -> cinematic -> blocking modal -> combat-interrupt -> continue), returning `SupervisorDirective(kind, reason, ...)`; `_STATE_SPECS` encodes a numeric priority ladder (IDLE=0 ... DEATH_RECOVERY=100) covering FATAL/DISCONNECT/DEATH/LOADING-CINEMATIC/SURVIVAL-COMBAT tiers from the spec. Method names differ from the spec's `handle_events()`/`decide_replan()`/`next_intent()` list but the decision surface is equivalent (`evaluate()`, `enter()`, `state_spec()`). Tested by `tests/test_supervisor.py` (11 tests). Selected-PID live interrupt-timing races remain live-open. |
| DESIGN-020 | PLANNER (wow_agent_complete_functional_design_spec.txt:1188) | `OFFLINE_VERIFIED` — `agent/planner.py::Planner` composes the domain policies and only selects high-level proposals. The named anti-loop is now implemented by `agent/decision_fingerprint.py::DecisionFingerprintGuard`: it fingerprints decision+target+strategy+objective+goal, records exhausted/non-retryable terminal decisions, and production Planner filtering suppresses the exact repeat until relevant semantic quest/target/map/UI/position evidence changes. Frame IDs and timestamps cannot falsely unlock it. It owns no input, lifecycle, or recovery authority. Covered by `tests/test_decision_fingerprint.py`, `tests/test_planning_orchestration.py`, architecture guards and the full **1650 passed, 4 skipped** regression. |
| DESIGN-021 | ACTIVE SKILL RUNTIME (wow_agent_complete_functional_design_spec.txt:1223) | `OFFLINE_VERIFIED` — `runtime/active_skill.py::ActiveSkillRuntime` implements `start(intent, attempt, now, ...)` (line 111) and `cancel(now, reason)` (line 213), backed by `ActiveSkillState`/`SkillLifecycleState`/`SkillLifecycleTransition`/`CancellationToken` dataclasses storing skill_runtime_id-equivalent state, phase, timestamps, attempt, and correlation -- matching the spec's "Tarol" list closely as sole authoritative owner. Tested by `tests/test_active_skill_runtime.py` (6 tests) and cross-checked by `tests/test_architecture_boundaries.py`'s runner-cannot-dispatch/finish assertions for every skill runner. Selected-PID concurrent-skill-preemption timing remains live-open. |
| DESIGN-022 | SKILL BASE CONTRACT (wow_agent_complete_functional_design_spec.txt:1252) | `OFFLINE_VERIFIED` — `runtime/skill_contract.py` defines the runtime-checkable `SkillBaseContract` with the exact `start/tick/cancel/on_enter/on_exit/snapshot` surface and a stateless `SkillContractAdapter`. `M0SkillDispatcher` production routing now invokes every canonical M0 domain skill through that contract, adapting the existing proven `begin`/`verify` implementations without cloning their state. Cancellation returns a typed `SkillResult`; finalization and every lifecycle transition remain exclusively owned by `ActiveSkillRuntime`. Dedicated conformance and authority tests are in `tests/test_skill_base_contract.py`; dispatcher/executor/supervision regressions remain green. Complete suite **1724 passed, 4 skipped**. |
| DESIGN-023 | TARGET SKILL TERV (wow_agent_complete_functional_design_spec.txt:1272) | `OFFLINE_VERIFIED` — `skills/target.py::TargetSkill` implements a real bounded FSM with `TargetPhase` (ACQUIRE_CANDIDATES/APPLY_TARGET/VERIFY_TARGET, a subset of the spec's 7 states), `begin()` (line 41) and `verify()` (line 57) checking expected_guid/expected_name against observed target with deadline-bounded retry, returning `FailureReason.LOW_CONFIDENCE`/`TARGET_NOT_FOUND`/`IDENTITY_UNCERTAIN` matching spec's NO_CANDIDATE/LOW_CONFIDENCE/WRONG_TARGET/TARGET_LOST error set. Candidate-scoring (`build_candidate_query`/`score_candidate`/`select_best`) is simpler than spec (single click/restore-target command, no multi-candidate ranking) but `agent/target_manager.py::TargetManager`/`TargetScoringPolicy`/`TargetCandidate` (separately, agent-layer) does implement scoring. Tested by `tests/test_m0_target_skill.py` (5 tests) and `tests/test_target_manager.py` (6 tests). |
| DESIGN-024 | FACE CONTROLLER (wow_agent_complete_functional_design_spec.txt:1309) | `OFFLINE_VERIFIED` — canonical shared controller implements begin(), estimate_error(), turn_command(), is_aligned(), tick() and cancel(); narrow enter/wider exit thresholds prevent flapping. Selected-PID facing remains live-open. |
| DESIGN-025 | MOVEMENT SKILL (wow_agent_complete_functional_design_spec.txt:1331) | `OFFLINE_VERIFIED` — `skills/movement_phase_contract.py::MovementPhase` implements the spec's named phases almost verbatim (INIT/RESOLVE_DESTINATION/PLAN/MOVE/MONITOR_PROGRESS ~ MONITOR/LOCAL_CORRECTION ~ CORRECT/ARRIVAL_VERIFY ~ VERIFY_ARRIVAL/RECOVER_STUCK ~ RECOVER), explicitly documented in its docstring as an observational contract layer added on top of `skills/movement.py::MovementSkillRunner`, which delegates all pathing to `NavigationService.observe()`/`.command()` with no independent steering stack (confirmed: "Nem sajat steering stack" holds -- no direct input dispatch in `movement.py`, statically enforced by `test_movement_skill_runner_cannot_dispatch_input_or_finish_active_skill`). Tested by `tests/test_movement_phase_contract.py`, `tests/test_movement_skill_runner.py` (2), `tests/test_movement_skill_runner_phase_wiring.py`, `tests/test_movement_contract.py`. |
| DESIGN-026 | NAVIGATION SERVICE (wow_agent_complete_functional_design_spec.txt:1360) | `OFFLINE_VERIFIED` — `navigation/service.py::NavigationService` (559 lines) is the single navigation authority for the live agent (imported by `agent/engine.py::AutonomousAgent`, confirmed via `from wowbot.navigation.service import NavigationService`), composing `GlobalPlanner`, `LocalPlanner`, `ProgressMonitor`, `TransitionResolver`, `StuckResolver`, `StuckClassifier`, `FaceController` internally, matching the spec's "Belso" component list (using `LocalPlanner` rather than the separately-existing `LocalNavigator`, see DESIGN-028). Public surface (`start`, `start_request`, `move_to_entity`, `observe`, `command`, `begin_stuck_recovery`, `resolve_transition`, `face_entity`) covers the spec's intent though named differently. Tested by `tests/test_navigation_service.py` (7), `test_navigation_service_context_and_transition_wiring.py` (5), `test_navigation_service_mode_wiring.py` (4). |
| DESIGN-027 | GLOBAL NAVIGATOR (wow_agent_complete_functional_design_spec.txt:1391) | `OFFLINE_VERIFIED` — the production `navigation/global_planner.py::GlobalNavigator` is the same class/authority formerly imported as `GlobalPlanner` (a source-compatible alias remains). It exposes `resolve_global_route`, `choose_waypoint`, `advance_waypoint`, `replan_if_required` and `detect_map_context_change` over the existing mmap/danger-aware route implementation. `NavigationService` now instantiates it by the canonical name; no independent route state or input loop was introduced. Covered by `tests/test_navigator_contracts.py`, graph and service suites. |
| DESIGN-028 | LOCAL NAVIGATOR (wow_agent_complete_functional_design_spec.txt:1410) | `OFFLINE_VERIFIED` — the live `navigation/local_planner.py` implementation is now canonically named `LocalNavigator`, with `LocalPlanner` retained only as an alias to the exact same class. `NavigationService` instantiates this canonical class. It exposes `compute_local_intent`, hysteretic/deadzone-compatible `correct_heading`, `approach_target`, confirmed-traversability-only `avoid_immediate_obstacle`, and `stop_at_range`, while still returning the existing input-free `LocalMotionPlan`. Covered by `tests/test_navigator_contracts.py` and navigation service/V5 assertions. Complete suite **1727 passed, 4 skipped**. |
| DESIGN-029 | ROUTE PLANNER (wow_agent_complete_functional_design_spec.txt:1429) | `OFFLINE_VERIFIED` — `navigation/planner.py::RoutePlanner` is a literal name match implementing `plan(start, goal, context)`-style route construction with `PlannedRoute`/`NoRouteError`, backed by `navigation/graph.py`/`graph_builder.py`/`graph_localization.py` for cost-scored edge routing (distance/known-failure/success-history per spec's "Route cost" list). Tested by `tests/test_graph_planner.py` (2), `tests/test_graph_builder.py` (2), `tests/test_graph_localization.py`. Selected-PID live navmesh-derived route quality remains live-open. |
| DESIGN-030 | PROGRESS MONITOR (wow_agent_complete_functional_design_spec.txt:1453) | `OFFLINE_VERIFIED` — `navigation/progress.py::ProgressMonitor` is a literal name match, backed by `ProgressSample`/`ProgressPhase`(UNAVAILABLE/MAKING_PROGRESS/POSSIBLE_STUCK/HARD_STUCK/RECOVERED)/`ProgressScore`/`ProgressPolicy`, closely matching the spec's PROGRESSING/SLOW/NO_PROGRESS/UNKNOWN output classification (renamed but semantically equivalent). Tested by `tests/test_navigation_progress.py` (9 tests). Selected-PID live sample-rate tuning under real frame jitter remains live-open. |
| DESIGN-031 | ARRIVAL VERIFIER (wow_agent_complete_functional_design_spec.txt:1474) | `OFFLINE_VERIFIED` — `ArrivalVerifier` is used by production REACH with explicit arrival-radius precedence, finite-distance validation and evidence-sensitive hysteresis. `navigation/arrival_evidence.py` now produces every declared evidence family: exact fresh target bbox growth, scoped quest-area progress, exact-target UI interaction readiness, exact-marker temporal minimap convergence, and explicit expected map/instance transition. Wrong/stale/receding minimap markers and incidental map changes are rejected. `ReachMovementController` consumes a verified expected transition before treating the map mismatch as failure; semantic arrival finishes the full request even at an intermediate mmap waypoint, while distance arrival advances the route. Tests: `tests/test_arrival_evidence.py`, `tests/test_arrival_quest_area_evidence.py`, `tests/test_arrival_verifier.py`; complete regression **1702 passed, 4 skipped**. Live thresholds/calibration remain open. |
| DESIGN-032 | STUCK DETECTOR (wow_agent_complete_functional_design_spec.txt:1496) | `OFFLINE_VERIFIED` — `navigation/stuck_classifier.py::StuckClassifier` implements `StuckKind`/`StuckAssessment` with a state model close to the spec's NOT_STUCK/SUSPECTED/CONFIRMED (via `StuckAssessment`), consuming position-delta/progress evidence. Tested by `tests/test_stuck_resolver.py` (4 tests) and `tests/test_recover_obstacle_direction.py` (4 tests), and wired live into `NavigationService` (confirmed import). Selected-PID live collision-evidence sourcing (addon vs. visual) remains live-open. |
| DESIGN-033 | OBSTACLE RECOVERY (wow_agent_complete_functional_design_spec.txt:1524) | `OFFLINE_VERIFIED` — `navigation/stuck_resolver.py::StuckResolver` implements a real bounded, evidence-gated recovery ladder (`_LADDER`: BACKWARD->TURN->STRAFE->JUMP_FORWARD->NEW_LOCAL_WAYPOINT->LOCAL_REPLAN->MARK_DANGER->REBUILD_CORRIDOR->GLOBAL_REPLAN->BLACKLIST_TEMP, plus kind-specific ladders for DROP_OR_CLIFF/WRONG_HEADING/OSCILLATION/DYNAMIC_BLOCK/PATH_LOOP), matching the spec's "Letra"/"next_recovery_step(attempt, context)"/"Minden bounded" requirements closely even though the exact step names differ (no literal STOP/LEFT_FORWARD/RELOCALIZE). `begin()`/`observe_progress()`/`report_step_result()` gate every advance on evidence, never blind-stepping. Tested by `tests/test_stuck_resolver.py` (4 tests), `tests/test_recovery_planner.py` (7 tests -- note: this file exercises `agent/recovery_planning.py`, a related but separate planning-layer module, not `StuckResolver` itself). Selected-PID live obstacle-geometry-triggered recovery remains live-open. |
| DESIGN-034 | TRANSITION RESOLVER (wow_agent_complete_functional_design_spec.txt:1546) | `OFFLINE_VERIFIED` — `navigation/transition_resolver.py::TransitionResolver` implements typed evidence-only assessments and `NavigationService.resolve_transition()` owns the canonical adapter. `agent/navigation_planning.py` invokes `NavigationSituationPolicy`, whose production `adapt()` consumes the resolver after repeated blockage or map-close/3D-absent evidence, emits one bounded `SEARCH_ENTRANCE`, and escalates an exhausted search to map relocalization. It never creates a second movement authority. Covered by `tests/test_transition_resolver.py`, `tests/test_navigation_situation_policy.py`, `tests/test_navigation_service_context_and_transition_wiring.py` and planning-orchestration regressions. Retail entrance/floor accuracy remains live-open. |
| DESIGN-035 | SEARCH SKILL (wow_agent_complete_functional_design_spec.txt:1576) | `OFFLINE_VERIFIED` — `src/wowbot/skills/search.py` SearchSkill delegates to SeekVisualCueController via begin()/observe()/snapshot(); `src/wowbot/skills/search_contract.py` adds the typed SearchCapability/SearchOutcome/SearchContext with bounded scan+time budget (`is_budget_exhausted`) enforcing "do not spin forever." Horizontal scan steps are bounded player-yaw pulses so Retail follow-camera rotates with the character instead of opposing mouse-drag camera yaw. Tests: `tests/test_m0_search_skill.py`, `tests/test_search_contract.py`, `tests/test_vision_seek.py`; live sweep coverage accuracy remains live-open. |
| DESIGN-036 | CAMERA CONTROLLER (wow_agent_complete_functional_design_spec.txt:1604) | `OFFLINE_VERIFIED` — `src/wowbot/agent/camera_controller.py` CameraController implements begin()/observe()/snapshot() with a deterministic `camera_gesture()` preset table (SCAN_SECTOR, CENTER_TARGET, RECENTER, etc.) bounded to [.05,.95] and yaw/pitch accumulation from confirmed frame motion. `view_control_command()` maps horizontal intents to bounded `TURNLEFT`/`TURNRIGHT` player-yaw pulses and retains camera drag only for pitch/recenter intents that yaw cannot express; verification accepts authoritative player orientation change or supported camera flow. No quest planning lives inside it, per spec's "Nem: quest tervezes." Tests: `tests/test_camera_and_domain_1_0.py`, `tests/test_architecture_boundaries.py`, `tests/test_m0_acceptance_matrix.py`; live follow-camera calibration remains open. |
| DESIGN-037 | INTERACT SKILL (wow_agent_complete_functional_design_spec.txt:1626) | `OFFLINE_VERIFIED` — `src/wowbot/skills/interact.py` InteractSkill's `InteractPhase` enum (ACQUIRE_TARGET/VALIDATE_TARGET/APPROACH/FACE/HOVER/VERIFY_HOVER/WAIT_INTERACTABLE/SEND_INTERACT/WAIT_RESULT/VERIFY) matches the spec state list; hover-anchor confirmation is required before SEND_INTERACT ("Highlight/interact-ready fontos evidence"). Tests: `tests/test_m0_interact_skill.py`, `tests/test_m0_interact_face_recovery.py`, `tests/test_m0_completion_gate.py` -- pass. |
| DESIGN-038 | INTERACTION VERIFIER (wow_agent_complete_functional_design_spec.txt:1672) | `OFFLINE_VERIFIED` — `src/wowbot/verification/interaction.py` InteractionVerifier.evaluate() implements verify_ui_change (quest_ui/gossip_ui delta), verify_quest_delta (`_quest_signature`), and combine_evidence into a VerificationResult, matched against `expected_result` (GOSSIP_OPEN/QUEST_OFFER/etc.). Tests: `tests/test_m0_completion_gate.py`, `tests/test_verification_movement_and_ui.py` -- pass. |
| DESIGN-039 | COMBAT SKILL (wow_agent_complete_functional_design_spec.txt:1693) | `OFFLINE_VERIFIED` — `src/wowbot/skills/combat.py` CombatSkill's `CombatPhase` enum (ACQUIRE_TARGET/VALIDATE_TARGET/ENGAGE/ROTATION/MONITOR/RECOVER_RANGE/RECOVER_FACING/RECOVER_LOS/VERIFY_DEATH) maps directly onto the spec states, with local recovery via ActionErrorCorrelator before any replan ("Local recovery before planner"). Tests: `tests/test_combat_action_rotation.py`, `tests/test_combat_death_fusion.py`, `tests/test_m0_combat_loot_skills.py` -- pass. |
| DESIGN-040 | COMBAT CONTROLLER (wow_agent_complete_functional_design_spec.txt:1731) | `OFFLINE_VERIFIED` — `src/wowbot/agent/combat_controller.py` CombatController.observe()/choose_action()/needs_facing_recovery()/recovery_reason()/reset()/snapshot(); ability ranking via AbilityRuleEngine, target ranking via TargetManager kept strictly advisory (real client selection stays with TARGET skill -- "Planner nem spell selector"). Test: `tests/test_combat_controller_1_0.py` -- pass. |
| DESIGN-041 | COMBAT ERROR CLASSIFIER (wow_agent_complete_functional_design_spec.txt:1759) | `OFFLINE_VERIFIED` — `verification/combat_error_classifier.py::classify_combat_error(observations, combat_history)` is the single canonical classifier. It composes `CombatVerifier`, maps the design taxonomy onto the existing authoritative `FailureReason` equivalents (`RESOURCE_LOW`→`NOT_ENOUGH_RESOURCE`, `MOVING_CAST`→`CAST_INTERRUPTED`, `UNKNOWN`→`UI_UNKNOWN`), and is consumed by both `CombatSkill` and the compatibility `CombatController.recovery_reason()` projection. CombatSkill retains a bounded 12-observation history. A one-frame missing target is diagnostic only; terminal `TARGET_LOST` still requires CombatVerifier's temporal correlation, preserving target commitment. Tests: `tests/test_combat_error_classifier.py`, `tests/test_combat_error_classifier_wiring.py`, combat controller/death/runtime suites. |
| DESIGN-042 | LOOT SKILL (wow_agent_complete_functional_design_spec.txt:1779) | `OFFLINE_VERIFIED` — `src/wowbot/skills/loot.py` LootSkill's `LootPhase` (LOCATE_CORPSE/APPROACH/INTERACT/WAIT_LOOT_STATE/VERIFY) matches spec exactly, delegating credit to `src/wowbot/verification/loot.py` LootVerifier. Tests: `tests/test_m0_combat_loot_skills.py`, `tests/test_loot_runtime_runner.py` -- pass. |
| DESIGN-043 | USE ITEM SKILL (wow_agent_complete_functional_design_spec.txt:1806) | `OFFLINE_VERIFIED` — `skills/quest_item.py::UseItemSkill` is the canonical targeted-item component (`QuestItemSkill` is a compatibility alias). Its phases are VALIDATE_CONTEXT, RESOLVE_ITEM_ACTION, ACQUIRE_TARGET_IF_NEEDED, APPROACH, FACE, USE, WAIT and VERIFY, and it exposes `resolve_item()`, `target_required()`, `range_required()`, `cooldown_ready()`, `activate()` and `verify_credit()`. Out-of-range produces typed `OUT_OF_RANGE` for the existing navigation authority rather than adding a second mover; exact selected-cache binding and quest-credit-only success remain mandatory. `ObjectUseSkill` and `InstructedSpellSkill` remain distinct mechanics, not competing generic item owners. Tests: `tests/test_m1_quest_item_skill.py`, dispatch and Exile's Reach mechanic regressions. |
| DESIGN-044 | QUEST TOOL BUTTON RESOLVER (wow_agent_complete_functional_design_spec.txt:1831) | `OFFLINE_VERIFIED` — `src/wowbot/skills/quest_tool.py` QuestToolSkill (VALIDATE_CONTEXT/ACTIVATE_EXPORTED_ACTION/WAIT_QUEST_CREDIT/VERIFY) requires an exact addon-exported action_type/action_id match on EXTRAACTIONBUTTON1, fails closed to UNSUPPORTED_MECHANIC when unbound ("Nem random click"), success gated solely by QuestProgressVerifier. Test: `tests/test_m1_extra_action_skill.py` -- pass. |
| DESIGN-045 | EXTRA ACTION HANDLER (wow_agent_complete_functional_design_spec.txt:1850) | `OFFLINE_VERIFIED` — `skills/quest_tool.py::ExtraActionHandler` is now the canonical fail-closed component (`QuestToolSkill` remains a compatibility alias). It exposes `detect()`, `associate_context()`, `requires_target()`, `requires_range()`, `activate()` and `verify_transition()`. Exact addon action identity plus selected-cache binding are mandatory; declared target/range requirements fail with typed IDENTITY_UNCERTAIN/OUT_OF_RANGE, unknown or unbound mechanics remain UNSUPPORTED_MECHANIC, and only quest credit verifies success. It reuses the one ActiveSkillRuntime/input path rather than adding another handler authority. Tests: `tests/test_m1_extra_action_skill.py`, dispatcher regressions. |
| DESIGN-046 | GOSSIP RESOLVER (wow_agent_complete_functional_design_spec.txt:1867) | `OFFLINE_VERIFIED` — detection/reading are performed by `quest_dialog_planning.py`, transition verification by `verification/quest_dialog.py`, and `QuestOfferSelector` now owns `score_option_against_objective()` plus deterministic selection. Exact quest-ID is authoritative; exact normalized addon-exported quest/objective title may uniquely disambiguate multiple offers. Fuzzy or tied evidence remains fail-closed as `requires_explicit_selection`/WAIT, satisfying the low-confidence BLOCKED/gather-info rule without guessed clicks. Tests: `tests/test_m1_quest_offer_selector.py`, `tests/test_quest_dialog_fast_lane.py`, `tests/test_m1_quest_dialog_skill.py`. |
| DESIGN-047 | QUEST ACCEPT FLOW (wow_agent_complete_functional_design_spec.txt:1883) | `OFFLINE_VERIFIED` — `agent/quest_accept_flow.py::QuestAcceptFlow` is the input-free coordinator with the exact LOCATE_QUEST_SOURCE → INTERACT → READ_QUEST_OFFER → VALIDATE_QUEST → ACCEPT → WAIT_STATE → VERIFY_ACTIVE phase vocabulary and named `locate_source()`, `read_offer()`, `matches_goal()`, `accept_command()` and `verify_accepted()` contracts. `QuestDialogPlanningPolicy` consumes it in production: an explicit quest goal cannot accept a different open offer, while valid fast-lane coordinates remain supported. Existing Interact/QuestDialog skills remain the only executors, so this adds no click authority. Tests: `tests/test_quest_accept_flow.py`, quest-dialog fast-lane/skill/runtime acceptance suites. |
| DESIGN-048 | QUEST DIALOG SKILL (wow_agent_complete_functional_design_spec.txt:1906) | `OFFLINE_VERIFIED` — `src/wowbot/skills/quest_dialog.py` QuestDialogSkill's single begin()/verify() pair covers handle_quest_offer/handle_quest_complete/handle_reward/handle_gossip_transition/handle_confirmation via `_SUPPORTED_ACTIONS`, guarded by quest_ui open+action+coordinate match (UiContext-equivalent), failing UNSUPPORTED_MECHANIC/WRONG_QUEST_UI otherwise. Tests: `tests/test_m1_quest_dialog_skill.py` (6 tests), `tests/test_quest_dialog_fast_lane.py` -- pass. |
| DESIGN-049 | QUEST PROGRESS VERIFIER (wow_agent_complete_functional_design_spec.txt:1922) | OFFLINE_VERIFIED — `src/wowbot/verification/quest.py::QuestProgressVerifier` remains the authoritative, action-success-independent quest-credit owner used by M1 skills and now exposes `capture_baseline()`, `compare()`, the named status queries, and a typed `QuestProgressAssessment`. Its output distinguishes `NO_CHANGE`, `QUEST_STARTED`, `QUEST_PROGRESSING`, generic `PROGRESSED`, `OBJECTIVE_COMPLETE`, `STAGE_CHANGED`, `READY_TURNIN` and `QUEST_COMPLETE`; the two more precise start/progress states extend rather than remove the six states required by the design. Existing `evaluate()` callers retain the same `VerificationResult` and evidence tags. Tests cover acceptance/start, partial progress, objective completion, stage change, ready-for-turn-in and turned-in completion; related focused suite 34 passed, complete regression **1574 passed, 3 skipped in 83.49 seconds**. Live addon event ordering remains open. |
| DESIGN-050 | QUEST STRATEGY HISTORY (wow_agent_complete_functional_design_spec.txt:1950) | `OFFLINE_VERIFIED` — `agent/quest_strategy_history.py::QuestStrategyHistory` is the bounded, quest-local per-(quest, objective, candidate, strategy) ledger for attempts, action success, quest credit, no-credit penalties and confidence rewards. `CreditFailureEscalation` and `CollectStrategyTracker` share this one store inside `QuestDomain`; their older structures are compatibility projections, not independent decision confidence. `QuestFailureMemory` remains separate by design because it is a short execution cooldown, not strategy learning. Tests: `tests/test_quest_strategy_history.py`, collect-strategy and credit-escalation suites (28 focused tests). |
| DESIGN-051 | NO-CREDIT HANDLING (wow_agent_complete_functional_design_spec.txt:1976) | `OFFLINE_VERIFIED` — `src/wowbot/agent/credit_failure_escalation.py` CreditFailureEscalation implements the exact ladder: 1st no-credit -> RECHECK_QUEST_STATE_AND_IDENTITY, 2nd -> REDUCE_CONFIDENCE_CHANGE_CANDIDATE, >=3 -> ESCALATE_TO_CLASSIFIER_OR_LOCATOR, >=5 -> BLOCKED_UNSUPPORTED, matching "Elso/Masodik/Ismetelt/Vegul" verbatim. Tests: `tests/test_credit_failure_escalation.py`, `tests/test_credit_escalation_wiring.py` -- pass. Whether live callers actually act on each tier's declared action remains live-open. |
| DESIGN-052 | SPEAK OBJECTIVE (wow_agent_complete_functional_design_spec.txt:1993) | `OFFLINE_VERIFIED` — `agent/entity_objective_flows.py::SpeakObjectiveFlow` is the input-free orchestration seam for classify/locate/arrival/local-search/identity handoff. After navigation reaches the declared area without progress, `QuestLocationPlanningPolicy` emits one bounded SEARCH_LOCAL_ENTITY carrying the exact NPC ID/name; fresh addon-backed target evidence then suppresses repeat movement and hands the same objective to the canonical TALK → quest-dialog → QuestProgressVerifier path. It creates no input or interaction authority. Tests: `tests/test_entity_objective_flows.py` plus locator/interact/dialog suites. Selected-PID conversation remains live-open. |
| DESIGN-053 | KILL OBJECTIVE (wow_agent_complete_functional_design_spec.txt:2010) | `OFFLINE_VERIFIED` — `agent/entity_objective_flows.py::KillObjectiveFlow` now composes area arrival with bounded hostile search and explicit identity/hostility validation. Quest-scoped `SEEK_VISUAL_CUE` refuses a wrong/friendly mouseover even when the generic visual servo sees a GUID; matching addon evidence hands off to the one `CombatPlanningPolicy`/`CombatSkill` authority. Combat death and quest credit remain distinct, and an incomplete counter remains ready so the flow repeats against another valid target. Tests: `tests/test_entity_objective_flows.py`, `tests/test_vision_seek.py`, combat/loot/quest-model suites; complete regression **1698 passed, 4 skipped**. Live hostile acquisition remains open. |
| DESIGN-054 | COLLECT OBJECTIVE (wow_agent_complete_functional_design_spec.txt:2027) | `OFFLINE_VERIFIED` — `src/wowbot/agent/collect_strategy.py` CollectStrategyTracker implements the named strategies (GROUND_OBJECT/MOB_LOOT/DIRECT_INTERACT/QUEST_ITEM_MECHANIC/SCRIPTED/UNKNOWN) with infer_collection_strategy() realized as `best_guess()`, adapting from observed credit via `record_outcome()` (strengthen on progress, weaken otherwise) -- matches "Credit alapjan adaptal" directly. Tests: `tests/test_collect_strategy.py`, `tests/test_collect_strategy_wiring.py` -- pass. Concrete GROUND_OBJECT/MOB_LOOT execution is delegated to loot.py/object_use.py/quest_item.py per the spec's own design. |
| DESIGN-055 | INTERACT OBJECT OBJECTIVE (wow_agent_complete_functional_design_spec.txt:2045) | `OFFLINE_VERIFIED` — `agent/object_interaction_flow.py::ObjectInteractionFlow` now composes the full locate-area → bounded local UNKNOWN-cue search/visual approach → fresh addon-mouseover identity validation → canonical `OBJECT_USE` click → authoritative quest-credit verification chain. `QuestLocationPlanningPolicy` stops repeating the same MOVE after an unchanged-credit arrival and carries the exact expected object/item identity into `SEEK_VISUAL_CUE`; GUID-less world objects are accepted only from a fresh matching addon `object_id`/`item_id` (or exact normalized tooltip evidence when no ID exists), never from CV appearance. `skills/object_use.py` remains the sole click owner and `QuestProgressVerifier` the sole success authority. Tests: `tests/test_object_interaction_flow.py`, `tests/test_m1_object_use_skill.py`, `tests/test_vision_seek.py`; complete regression **1695 passed, 4 skipped**. Selected-PID object approach/use remains live-open. |
| DESIGN-056 | TRAVEL / REACH AREA OBJECTIVE (wow_agent_complete_functional_design_spec.txt:2059) | `OFFLINE_VERIFIED` — `ObjectiveLocator` retains World-Map-first location resolution and quest credit remains authoritative. `agent/travel_reach_fallback.py::TravelReachFallbackPolicy` is now wired into `QuestLocationPlanningPolicy`: once the exact map destination is reached and the scoped quest signature has not changed, it stops reproducing the same MOVE and emits one bounded local SEEK for an entrance, NPC, sub-area object or trigger. Explicit transition evidence selects SEARCH_ENTRANCE; entity evidence selects SEARCH_LOCAL_ENTITY; otherwise SEARCH_LOCAL_OBJECT/trigger is used. Search budgets are finite and execution remains in the canonical SearchSkill/NavigationService. New quest evidence invalidates the prior arrival assumption. Tests: `tests/test_travel_reach_fallback.py` plus locator/arrival/transition/search regressions. |
| DESIGN-057 | DEFEND / WAIT OBJECTIVE (wow_agent_complete_functional_design_spec.txt:2071) | `OFFLINE_VERIFIED` — `skills/defend_wait.py::DefendWaitSkill` implements the exact bounded phases WAIT_FOR_EVENT → MONITOR → COMBAT_IF_REQUIRED / VERIFY_PROGRESS → TIMEOUT_REEVALUATE. It emits no movement/input command, succeeds only from authoritative `QuestProgressVerifier` evidence, returns a typed combat interrupt so the existing canonical combat policy may choose DEFEND, and times out into controlled reevaluation. `QuestDomain` proposes `WAIT_EVENT` for ready WAIT/DEFEND objectives without a concrete route and explicitly does not replace a missing marker with SEARCH/MOVE/INSPECT wandering. It is installed under the existing `ActiveSkillRuntime`/`M0SkillDispatcher`, not as another authority. Tests: `tests/test_defend_wait_skill.py` plus dispatcher/executor/supervision/architecture regressions -- pass. Selected-PID scripted-event behavior remains live-open. |
| DESIGN-058 | ESCORT / FOLLOW OBJECTIVE (wow_agent_complete_functional_design_spec.txt:2086) | `OFFLINE_VERIFIED` — `agent/escort_follow.py::EscortFollowPolicy` provides `identify_escort_entity()`, `maintain_distance_band()`, `follow()`, `handle_stop()`, `handle_combat()`, `reacquire()` and `verify_progress()`. It creates FOLLOW for an exact addon-backed arbitrary quest NPC, not only the party leader. The same persistent `ReachMovementController` refreshes the moving entity position, holds the min/max band without overtaking, tolerates a short 2-second occlusion, then fails into the bounded SEARCH_LOCAL_ENTITY reacquire path. Combat remains a higher-priority existing interrupt and completion requires authoritative quest progress. Tests: `tests/test_escort_follow_policy.py`, `tests/test_follow_distance_band.py`, movement/navigation/quest-model regressions. |
| DESIGN-059 | VEHICLE MODE (wow_agent_complete_functional_design_spec.txt:2103) | `OFFLINE_VERIFIED` — `src/wowbot/skills/vehicle.py` VehicleSkill's `VehiclePhase` (DETECT_OVERRIDE/CANCEL_INCOMPATIBLE_ASSUMPTIONS/USE_VEHICLE_ACTIONS/VERIFY_QUEST_PROGRESS/EXIT_RESTORE_CONTEXT) plus `rotation_allowed()`, which `src/wowbot/skills/combat.py` imports to block normal rotation during vehicle override ("Normal combat rotation tiltva vehicle state-ben"). Tests: `tests/test_vehicle_skill.py`, `tests/test_combat_vehicle_override_guard.py` -- pass. |
| DESIGN-060 | FIELD TURN-IN (wow_agent_complete_functional_design_spec.txt:2122) | `OFFLINE_VERIFIED` — completion-mode detection remains in `quest_runtime.py`; `skills/field_turnin.py::FieldTurnInSkill` now owns the explicit DETECT_PROMPT/OPEN/COMPLETE/REWARD_IF_NEEDED/VERIFY_COMPLETED contract. It is mode-guarded (only confirmed FIELD_TURN_IN), delegates the actual safe click/verification to the existing canonical `QuestDialogSkill`, and runs under the same M0 dispatcher/ActiveSkillRuntime/VerificationEngine path, so there is no second input authority. `QuestDialogPlanningPolicy` emits FIELD_TURN_IN only for completion/reward actions with confirmed field mode; NPC dialogs remain QUEST_DIALOG. Tests: `tests/test_field_turnin_skill.py` plus dialog/runtime/planning/architecture suites. |
| DESIGN-061 | TURN-IN RESOLVER (wow_agent_complete_functional_design_spec.txt:2143) | `OFFLINE_VERIFIED` — `src/wowbot/agent/turnin_resolver.py` TurnInResolver.locate() implements the exact spec priority order (field UI action > live local turn-in-role target > declared TURN_IN known_location > mode-implied location > current Quest API waypoint > UNKNOWN), confidence-scored with evidence tags. Test: `tests/test_m1_turnin_resolver.py` -- pass. |
| DESIGN-062 | REWARD POLICY (wow_agent_complete_functional_design_spec.txt:2163) | `OFFLINE_VERIFIED` — `src/wowbot/agent/quest_reward_selector.py` now defines `RewardPolicy` StrEnum (USER_CONFIG/STAT_RULE/VALUE_RULE/TEST_FIRST_VALID/BLOCKED, verbatim) and `select()` handles all five: USER_CONFIG is the existing explicit choice_index/item_id path; STAT_RULE picks the highest real addon-exported `item_level` among `is_usable` rows, failing closed on a tie or missing data (never a fabricated stat); VALUE_RULE requires the caller to supply real `values` (quest rewards carry no price/value field of their own, unlike vendor items -- never invented internally), failing closed with `value_rule_requires_values` when omitted; TEST_FIRST_VALID deterministically picks the first row, documented as offline/test-only per "Elesben random valasztas tilos"; BLOCKED always fails closed. Tested in `tests/test_m1_quest_reward_selector.py` (+6 new tests). |
| DESIGN-063 | NEXT QUEST RESOLVER (wow_agent_complete_functional_design_spec.txt:2180) | `OFFLINE_VERIFIED` — `src/wowbot/agent/next_quest_source_hierarchy.py` resolve_next_quest_source() implements the exact ordered fallback (RESULTING_UI > SAME_NPC > LOCAL_MARKERS > TRACKER_LOG > WORLD_MAP > CAMPAIGN_CLASSIFICATION), explicitly documented as never assuming same-NPC ("Nem feltetlen same NPC"). `src/wowbot/agent/next_quest_resolver.py` handles the narrower campaign-continuation case. Tests: `tests/test_next_quest_source_hierarchy.py`, `tests/test_m1_next_quest_resolver.py` -- pass. |
| DESIGN-064 | QUEST EXECUTION RUNTIME (wow_agent_complete_functional_design_spec.txt:2198) | `OFFLINE_VERIFIED` — `src/wowbot/agent/quest_runtime.py` QuestExecutionRuntime.observe() is a canonical, single-owner state machine whose phases (SELECT_PRIMARY_QUEST, READ_QUEST_STATE, VERIFY_QUEST_PROGRESS, EXECUTE_OBJECTIVE, NAVIGATE_LOCAL, NAVIGATE_GLOBAL, SEARCH_LOCAL, RESOLVE_TRANSITION, LOCATE_TURNIN, FIELD_TURN_IN, VERIFY_COMPLETE) map onto the spec's canonical list under equivalent (not identical) names; `_observe_stage()` forces reclassification on stage change. Tests: `tests/test_m1_primary_quest_runtime.py` (6 tests), `tests/test_m1_runtime_acceptance.py` -- pass. Literal start()/tick()/on_skill_result() methods are not present -- observe() is the single entry point instead. |
| DESIGN-065 | MAIN CAMPAIGN MODE (wow_agent_complete_functional_design_spec.txt:2233) | `OFFLINE_VERIFIED` — `src/wowbot/agent/next_quest_resolver.py` NextQuestResolver.resolve(records, main_campaign=True) implements select_next_campaign_quest() exactly: requires an explicit MAIN_CAMPAIGN goal mode and only accepts a single addon-flagged `is_campaign` active quest, refusing to guess among several/none. Wired into `quest_runtime.py`'s continuation branch. Test: `tests/test_m1_next_quest_resolver.py` (asserts `source == "MAIN_CAMPAIGN_CONTINUATION"`) -- pass. |
| DESIGN-066 | MULTI-STAGE OBJECTIVE (wow_agent_complete_functional_design_spec.txt:2246) | `OFFLINE_VERIFIED` — `src/wowbot/agent/quest_runtime.py` `_observe_stage()` computes a (state, objectives-signature) tuple per record; on change it increments `stage_revision`, records `last_stage_transition`, clears the selected objective_id/type/location_status (invalidating the old locator selection) and clears failure memory, forcing the next observe() to reclassify -- matches handle_stage_transition(old,new). Test: `tests/test_m1_primary_quest_runtime.py` asserts `stage_revision == 1` -- pass. |
| DESIGN-067 | LOADING / PHASING / TELEPORT (wow_agent_complete_functional_design_spec.txt:2259) | `OFFLINE_VERIFIED` — reuses the same canonical `src/wowbot/runtime/state_invalidation.py` StateInvalidationPolicy verified under DESIGN-077: LOADING/TELEPORT/PHASE/FLOOR/MAP_CONTEXT all map to the shared context reset (clears visual tracks/navigation/camera/commitment/map-search) while leaving `invalidate_objective=False`, preserving quest goal/state exactly per "Megoriz: quest goal, quest state." Teleport is detected via a >=50-unit position jump (`_teleported()`). Test: `tests/test_state_invalidation.py` -- pass (same evidence base as the DESIGN-077 exemplar). |
| DESIGN-068 | CINEMATIC (wow_agent_complete_functional_design_spec.txt:2278) | `OFFLINE_VERIFIED` — `src/wowbot/runtime/supervisor.py` enters CRITICAL_RECOVERY on `cinematic_playing` (blocking gameplay dispatch = suspend_gameplay_input), `src/wowbot/runtime/cinematic_policy.py` CinematicSkipPolicy is an explicitly opt-in, rate-limited skip gate (disabled by default = spec's default "wait," matching "Skip csak policy szerint"), and `state_invalidation.py`'s CINEMATIC event fires on the falling edge (wait_end) forcing a full context+objective refresh (refresh_context). Test: `tests/test_cinematic_handling.py` (15 tests) -- pass. |
| DESIGN-069 | PLAYER DEATH (wow_agent_complete_functional_design_spec.txt:2294) | PARTIAL / OFFLINE_TESTED — Supervisor retains death priority and goal preservation; the existing shared death policy can use exported release/reclaim buttons and NavigationService for corpse recovery. The 2026-10-28 live failure established successful spirit release followed by blocked corpse travel; narrow ghost-only fallback/descent/cancellation fixes passed offline regression and retained-state replay. Real travel and resurrection with this fix remain unvalidated; see LIVE_VALIDATION.md. |
| DESIGN-070 | ACTION TARGETING / SOFT TARGETING INTEGRÁCIÓ (wow_agent_complete_functional_design_spec.txt:2313) | `OFFLINE_VERIFIED` — both Retail addon packages read the bounded `softenemy`/`softfriend`/`softinteract` unit-token set into FULL and compact FAST telemetry. `agent/soft_targeting.py::observe_soft_targets()` normalizes those rows as transient `CANDIDATE_HINT` evidence and `use_as_candidate_hint()` can only score an already-existing candidate (GUID > NPC id > normalized name); all results remain `confirmed=False`, `semantic_type=UNKNOWN`. `WorldAddonReducer` preserves/evidences the field on both lanes and `WorldQuery.soft_target_hints()`/`soft_target_match()` expose it read-only. The helper imports no Proposal or input authority. Tests: `tests/test_soft_targeting.py` plus addon/transport regressions -- pass. Selected-PID availability of Retail soft-unit tokens remains live-open. |
| DESIGN-071 | BINDING INVENTORY (wow_agent_complete_functional_design_spec.txt:2330) | `OFFLINE_VERIFIED` — `BindingInventory` (`src/wowbot/agent/binding_inventory.py:6-109`, `validate_actions`/`ingest`) plus `BindingsCache` (`src/wowbot/agent/bindings.py`: `reload()` L21, `resolve()` L37, `preflight()` L64, `required_actions()` L52) together cover the spec's function set; canonical actions never store raw keys (resolved through `.resolve(action)`). Tested in `tests/test_binding_inventory.py`, `tests/test_binding_completion.py`, `tests/test_agent_core.py` (`resolve`, `preflight`). Live client-binding export/PID correlation remains live-open. |
| DESIGN-072 | EXECUTOR (wow_agent_complete_functional_design_spec.txt:2350) | `OFFLINE_VERIFIED` — `RecordingExecutor`/`InputExecutor` in `src/wowbot/agent/executor.py` implement execute/execute_movement/stop/stop_movement/diagnostics with an F12 emergency check (`_check`, L112-114) and full key release on any exit path (`_release`); no quest-aware logic present, matching "Nem quest-aware." Command taxonomy differs from the spec's PRESS/HOLD/CLICK/WHEEL/enqueue-dispatch naming (actual kinds are BIND/CLICK/HOVER/MAP_ZOOM_IN/CAMERA_PAN with synchronous execute rather than a queue), so it is a real but differently-shaped design. Tested across `tests/test_m0_safe_stop.py`, `tests/test_input_scheduler.py`, `tests/test_agent_core.py`. |
| DESIGN-073 | COMMAND ACKNOWLEDGEMENT (wow_agent_complete_functional_design_spec.txt:2378) | `OFFLINE_VERIFIED` — bounded `CREATED → QUEUED → DISPATCHED → LOCAL_ACK/FAILED/CANCELLED` lifecycle in `execution/command_ack.py`; receipts correlate to `action_id` and explicitly do not represent world success. Selected-PID latency/failure evidence remains live-open. |
| DESIGN-074 | INPUT SAFETY (wow_agent_complete_functional_design_spec.txt:2394) | `OFFLINE_VERIFIED` — `InputExecutor._check()` (`executor.py:105-114`) enforces foreground ownership (`is_selected_foreground`), F12 emergency stop, and cancellation; `_release()` guarantees held-key release on every exit path including exceptions (`finally` block). `InputScheduler` (`src/wowbot/execution/input_scheduler.py`) adds a movement watchdog (`_watchdog_loop`). Tested via `tests/test_input_scheduler.py`, `tests/test_m0_safe_stop.py`, `tests/test_runtime_health.py`. |
| DESIGN-075 | RETRY POLICY (wow_agent_complete_functional_design_spec.txt:2410) | `OFFLINE_VERIFIED` — `RetryPolicy` (`src/wowbot/runtime/policies.py`) now carries `max_attempts`/`per_reason_limits` fields and pure, stateless `can_retry(attempt_number, reason, retryable=)`/`next_backoff()` (spec-named alias for `backoff()`)/`reset_if(reason)` methods -- no stored state, no side effects. Deliberately NOT wired to replace `FailureManager`'s own domain-budget attempt counting (`_BUDGETS`/`FailureRecord.attempt_number`, `record_failure()`'s `retry_allowed`), since that would create a second, competing retry authority and change live behavior for `FailureReason.INTERRUPTED` (in `RetryPolicy.non_backoff_reasons` but not in `FailureManager._TERMINAL`) without being asked to; `FailureManager` remains the sole live attempt-budget owner. Tested in `tests/test_m0_policies.py` (5 new tests: max_attempts default, per-reason override, non-backoff/retryable gating, reset_if). |
| DESIGN-076 | TIMEOUT POLICY (wow_agent_complete_functional_design_spec.txt:2430) | `OFFLINE_VERIFIED` — `TimeoutPolicy` (`src/wowbot/runtime/policies.py:10-35`) maps skill->domain (movement/interaction/combat/loot/search/ui_wait/map_wait) and `resolve(skill, configured_seconds, context)` tightens the deadline under loading/input_blocked, matching `deadline_for(skill, context)`. Tested in `tests/test_m0_policies.py`. |
| DESIGN-077 | STATE INVALIDATION POLICY (wow_agent_complete_functional_design_spec.txt:2447) | `OFFLINE_VERIFIED` — explicit matrix and runtime integration cover OBJECTIVE_CHANGED, LOADING, TELEPORT, MAP_CONTEXT, DEATH, PHASE, FLOOR and VEHICLE. Context resets cancel active work through the canonical lifecycle, clear transient anchors and reset navigation/camera/commitment/map search without acquiring input authority. Selected-PID transitions remain live-open. |
| DESIGN-078 | MEMORY (wow_agent_complete_functional_design_spec.txt:2467) | `OFFLINE_VERIFIED` — the final logical stores are explicitly owned: `EpisodeMemory` owns durable episodes/steps, `SpatialMemory` owns learned points, `EntityMemory` owns confirmed identity/visual/location knowledge, `NavigationMemory` owns route/segment outcomes, and the Planner/QuestRuntime-shared `QuestAttemptMemory` owns bounded quest attempts and strategy history. Supporting empirical stores are also separated: `LearningMemory` owns procedure/sensor trials, profiles, confusion/drift, reliability, expiry and consolidation; `RejectionMemory` owns zero-information suppression, contradictions, expiry and reliability. `AgentMemory` preserves its public API solely as a compatibility facade over these owners and the existing SQLite schema/data. Focused owner/core suites passed **110 tests**; complete regression **1735 passed, 4 skipped**. No current WorldModel truth is inferred from memory. |
| DESIGN-079 | ENTITY MEMORY (wow_agent_complete_functional_design_spec.txt:2492) | `OFFLINE_VERIFIED` — `EntityMemory` (`src/wowbot/vision/entity_memory.py:30`) implements `record_mouseover` (identity), `associate_visual`/`record_visual_outcome` (visual signature), `recognize_visual`, `find_by_name`, `locations`/`get_profile`/`summary` (confidence). Tested in `tests/test_entity_memory_m7113.py`, `tests/test_entity_memory_m79.py`, `tests/test_visual_signature_m711.py`. No literal `invalidate_stale()`; staleness is instead handled via `as_of`-bounded queries -- not independently confirmed as equivalent. |
| DESIGN-080 | SPATIAL MEMORY (wow_agent_complete_functional_design_spec.txt:2507) | `OFFLINE_VERIFIED` — `SpatialMemory` (`src/wowbot/agent/spatial_memory.py`) implements `spawn_reference`≈record_known_location query, `quest_role_reference`≈record_quest_role_location query, `ingest`, plus the previously-missing `get_candidate_locations(map_id, as_of=, max_age=)` (thin read over the live `WorldPointMemory` store), `cluster_locations(rows, ...)` (extracted from `quest_role_reference()`'s own inline nearby-row merge into a reusable, independently-tested static method -- `quest_role_reference()` now calls it, identical behavior, confirmed via its existing test `test_role_location_clusters_phase_variants_without_claiming_identity`), and `reliability_score(row, now=, max_age=)` (bounded [0,1] from the row's real `seen_count`/`last_seen` fields, no invented signal). Tested by `tests/test_agent_map_discovery.py`, `tests/test_spawn_catalog.py` (+3 new tests), `tests/test_map_location_provenance.py`. |
| DESIGN-081 | NAVIGATION MEMORY (wow_agent_complete_functional_design_spec.txt:2520) | `OFFLINE_VERIFIED` — `NavigationMemory` (`src/wowbot/navigation/memory.py:47`) implements `record_route`, `record_outcome`, `record_segment_outcome`, `get_experience`/`get_segment_experience`, and `RouteExperience.reliability_score()` (L25). Tested in `tests/test_learning.py`, `tests/test_memory.py`, `tests/test_memory_segments.py`, `tests/test_navigation_engine.py`. `known_blocked_segments()` not confirmed by that name. |
| DESIGN-082 | ACTIVE PERCEPTION (wow_agent_complete_functional_design_spec.txt:2533) | `OFFLINE_VERIFIED` — `ActivePerception` (`src/wowbot/agent/active_perception.py`) implements a bounded probe FSM (`request_probe`, `select_probe_action`, `mark_probe_dispatched`, `evaluate_probe`, `evaluate`, `rank_world3d`) that decides what sensory evidence is missing without issuing input itself ("Nem kozvetlen planner"). Tested in `tests/test_active_perception.py`, `tests/test_active_perception_fsm.py`. |
| DESIGN-083 | INFORMATION GATHERING POLICY (wow_agent_complete_functional_design_spec.txt:2553) | `OFFLINE_VERIFIED` — `src/wowbot/agent/quest_info_hierarchy.py` defines the ranked A-H source order (`QUEST_TRACKER > WORLD_MAP > SUPERTRACK_MARKER > MINIMAP > WORLD_3D > TOOLTIP > QUEST_UI > TEMPORAL_HISTORY`) and `resolve_first_available()` enforces "never fall back to 3D before A-D are exhausted," closely matching the spec's bounded escalation order; combined with `ActivePerception`'s bounded probe budget for the fail/block-when-exhausted step. Tested in `tests/test_quest_info_hierarchy.py`. |
| DESIGN-084 | REASONER / LLM (wow_agent_complete_functional_design_spec.txt:2569) | `OFFLINE_VERIFIED` — `OllamaReasoner` (`src/wowbot/agent/reasoner.py:11`, docstring: "Slow advisory loop. Can rank existing candidate IDs, never create commands") implements `advise(goal, world, proposals, now)` which only ranks existing proposals/candidates and returns a proposal with confidence, never issuing input directly. Tested in `tests/test_agent_runtime.py`. |
| DESIGN-085 | REJECTION MEMORY (wow_agent_complete_functional_design_spec.txt:2592) | `OFFLINE_VERIFIED` — `AgentMemory.record_rejection`/`record_rejection_contradiction`/`rejection_status` (`src/wowbot/agent/memory.py:501-605`) use `rejection_signature()` from `src/wowbot/agent/rejection.py`, track TTL-bound expiry (`ttl=86400.`, `expires_at`) so rejections are not permanent, and group correlated same-episode trials. Tested in `tests/test_map_zoom.py`, `tests/test_quest_understanding_patch.py`. |
| DESIGN-086 | RUNTIME SCHEDULER (wow_agent_complete_functional_design_spec.txt:2607) | `OFFLINE_VERIFIED` — `agent/runtime_scheduler.py::RuntimeCadenceScheduler` implements independent, thread-safe `should_capture()`, `should_run_world3d()`, `should_run_minimap()`, `should_run_map()`, `should_run_ocr()` and `rates()` gates; `BrainScheduler` delegates all of them alongside its event-driven `should_plan()`. Production wiring is real: BufferedPixelSensor uses the capture gate, PerceptionWorker uses independent World3D/minimap/map gates, and TargetedOCR uses the OCR gate; `AgentRuntime` shares the agent scheduler with perception. Gate rates/skips are diagnostic only and do not gate the separate FAST movement consumer. Tests: `tests/test_runtime_scheduler_1_0.py`, World3D/perception/sensor/runtime regressions -- pass. Selected-PID rate calibration remains open. |
| DESIGN-087 | PERFORMANCE MODEL (wow_agent_complete_functional_design_spec.txt:2626) | `OFFLINE_VERIFIED` — `PerformanceMonitor` (`src/wowbot/runtime/performance.py`) tracks bounded per-name latency windows with `p50_ms`/`p95_ms` (`LatencySummary`, `_percentile`), capture rate and queue depth; call sites record `capture_poll`, `perception`, `observation_build`, `agent_tick`, `world_detector`, `world_tracker`, `supervisor_tick`, `input_dispatch` (`agent/runtime.py:639-647`, `runtime/performance.py:107,124`). Tested in `tests/test_runtime_performance.py`. Domain coverage doesn't literally include named minimap/map/OCR/fusion/planner-latency channels. |
| DESIGN-088 | BACKPRESSURE (wow_agent_complete_functional_design_spec.txt:2646) | `OFFLINE_VERIFIED` — `runtime/backpressure.py` is the single input-free owner of the four requested primitives: `coalesce_latest()`, `drop_stale()`, `bound_queue()` and `prioritize_critical_event()`. `BufferedPixelSensor` uses the first three for its single-reader latest-state mailbox and bounded transition queue; `EventBus` delegates full-queue admission to the fourth, evicting ordinary events before critical ones and exposing all-critical overflow diagnostically. Existing bounded queues remain bounded and no planner/input authority was added. Tests: `tests/test_backpressure.py`, `tests/test_agent_buffered_sensor.py`, `tests/test_runtime_event_bus.py` -- pass. |
| DESIGN-089 | REPLAY RECORDER (wow_agent_complete_functional_design_spec.txt:2658) | OFFLINE_VERIFIED — `ReplayRecorder` implements typed append-only JSONL sessions with observation/event/world-delta/skill-transition/command/verification streams, checkpoints and close. `RuntimeReplayBridge` is wired opt-in through `AgentRuntime` (`replay_path` or `AIPC_REPLAY_PATH`), observes accepted observations, section revisions and the structured logger, and has no planner/input authority. Diagnostic sink exceptions are isolated. Covered by `tests/test_diagnostics_replay.py` and `tests/test_runtime_replay_bridge.py`; selected-PID file-volume measurement remains live-open. |
| DESIGN-090 | REPLAY PLAYER (wow_agent_complete_functional_design_spec.txt:2677) | OFFLINE_VERIFIED — `diagnostics/replay.py::ReplayPlayer` implements load/seek/step/run/offline-runtime injection and deterministic golden-trace comparison. The replay layer has no input-backend import and rejects consumers explicitly marked as real input executors. Covered by `tests/test_diagnostics_replay.py`; selected-PID traces remain live-open. |
| DESIGN-091 | GOLDEN TRACE (wow_agent_complete_functional_design_spec.txt:2693) | `OFFLINE_VERIFIED` — `tests/fixtures/golden_traces/m1_core.jsonl` contains seven canonical typed replay sessions: interact, combat-recovery, navigation-stuck, quest-speak, quest-kill, collect and turn-in. `diagnostics/golden_trace_catalog.py` requires SESSION_START/OBSERVATION/SKILL_TRANSITION/COMMAND/VERIFICATION/SESSION_END, checks the expected skill/terminal/command and demands positive verification evidence; `ReplayPlayer.compare_golden_trace()` confirms deterministic equality. It is diagnostics-only and has no executor/dispatch dependency. Tests: `tests/test_golden_trace_catalog.py` -- pass. These canonical offline traces are not claims of seven new selected-PID live successes. |
| DESIGN-092 | DEBUG OVERLAY / GUI (wow_agent_complete_functional_design_spec.txt:2708) | `OFFLINE_VERIFIED` — `AgentWindow._compact_detail` (`src/wowbot/agent/gui.py:231-306`) surfaces goal, plan, quest/objectives, target/mouseover, navigation route/authority, binding preflight, replan revision, vision tracks, and failures/events in a bounded projection without owning runtime authority. Tested in `tests/test_gui_compact_status.py`, `tests/test_gui_status_bounds.py`. |
| DESIGN-093 | ACCEPTANCE ACCUMULATOR (wow_agent_complete_functional_design_spec.txt:2734) | `OFFLINE_VERIFIED` — `AcceptanceAccumulator` (`src/wowbot/agent/acceptance.py`) remains the live/soak session-level PASS/FAIL gate unchanged (`tests/test_acceptance_and_golden_1_0.py`). New `agent/capability_acceptance.py::CapabilityAcceptanceTracker` adds the spec's separate "capability metrics" surface verbatim: `record_case()`/`record_success()`/`record_failure(capability, reason)`/`report_rate()`/`group_by_failure()`, bounded in-memory per named capability, independent of any one soak session. Tested in `tests/test_capability_acceptance.py` (5 tests). |
| DESIGN-094 | M0 TESTKATALÓGUS (wow_agent_complete_functional_design_spec.txt:2752) | `OFFLINE_VERIFIED` (offline scope only) — the M0 catalog (target/move/interact/combat/loot/safe-stop) is concretely covered by `tests/test_m0_target_skill.py`, `test_m0_visual_approach_skill.py`, `test_m0_interact_skill.py`, `test_m0_interact_face_recovery.py`, `test_m0_combat_loot_skills.py`, `test_m0_search_skill.py`, `test_m0_safe_stop.py`, `test_m0_acceptance_matrix.py` (runs canonical boundaries 100x deterministically). `docs/M0_ACCEPTANCE_MATRIX.md` self-reports "offline replay foundation; not live-validated" -- matches the spec's checklist honestly but confirms no live M0 gate has been passed yet. |
| DESIGN-095 | M1 TESTKATALÓGUS (wow_agent_complete_functional_design_spec.txt:2790) | `OFFLINE_VERIFIED` (offline scope only) — the M1 catalog (quest-giver visible/minimap/map, speak/kill/collect, quest tool, extra action, travel, multi-stage, turn-in, gossip, cave/floor/loading/cinematic/death/vehicle, next campaign quest) maps concretely onto `tests/test_m1_objective_classifier.py`, `test_m1_objective_locator.py`, `test_m1_quest_dialog_skill.py`, `test_m1_turnin_resolver.py`, `test_m1_extra_action_skill.py`, `test_m1_object_use_skill.py`, `test_m1_quest_item_skill.py`, `test_m1_next_quest_resolver.py`, `test_cinematic_handling.py`, `test_m1_integration_scenarios_index.py`, etc. Same live-validation caveat as DESIGN-094. |
| DESIGN-096 | LIVE VALIDATION TERV (wow_agent_complete_functional_design_spec.txt:2818) | UNCLEAR — this is a process/discipline document (M0-before-M1 gating, per-session logging, 9-category root-cause taxonomy). `docs/LIVE_VALIDATION.md` shows the discipline genuinely followed in practice (dated offline-change entries explicitly stating "no client input/FULL_AI session occurred," each flagging what a future live test must prove), and `docs/M0_ACCEPTANCE_MATRIX.md` gates M1 readiness on M0. However the specific PERCEPTION/LOCALIZATION/NAVIGATION/TARGET/INTERACTION/COMBAT/QUEST/UI/SYSTEM root-cause taxonomy has no code representation (a repo-wide search for it across `src` found nothing) -- it is not a discrete code requirement. |
| DESIGN-097 | CURRENT REPO → TARGET OWNERSHIP TERV (wow_agent_complete_functional_design_spec.txt:2849) | UNCLEAR — a migration/ownership plan, not a component. Spot check: every legacy module the plan says to retire/rename still exists verbatim (`agent/engine.py`, `agent/autonomy_loop.py`, `agent/planner.py`, `agent/movement_controller.py`, `agent/navigation.py`, `agent/combat_controller.py`, `agent/quest_model.py`, `agent/memory.py`, `agent/executor.py` all present), while newer canonical-named modules the plan targets also now exist alongside them (`runtime/supervisor.py:Supervisor`, `navigation/service.py:NavigationService`). This indicates partial, additive migration rather than the clean rename/retirement the plan describes -- worth flagging given this project's known fast/slow-lane dual-authority bug pattern, but out of scope to fully audit here. |
| DESIGN-098 | FUNKCIÓ-OWNERSHIP MÁTRIX (wow_agent_complete_functional_design_spec.txt:2916) | UNCLEAR — an ownership matrix, not a component. Spot check against real classes: mostly holds with renames (StuckDetector -> `navigation/stuck_classifier.py:StuckClassifier` + `stuck_resolver.py:StuckResolver`; RewardPolicy -> `agent/quest_reward_selector.py:QuestRewardSelector`; TargetSkill/InteractSkill/CombatSkill/LootSkill/ActiveSkillRuntime/QuestProgressVerifier/TurnInResolver all exist under their listed or closely-related names). GossipResolver has no single owning class -- gossip handling is spread across `agent/quest_dialog_planning.py`, `agent/quest_offer_selector.py`, `skills/quest_dialog.py`, matching the "structurally distributed, no clean owner" UNCLEAR case. |
| DESIGN-099 | DESIGN REVIEW CHECKLIST (wow_agent_complete_functional_design_spec.txt:2993) | UNCLEAR — pure process checklist (13 review questions for any new function); not a code requirement, nothing to verify against source. |
| DESIGN-100 | VÉGSŐ RENDSZERVISELKEDÉS (wow_agent_complete_functional_design_spec.txt:3016) | UNCLEAR — a narrative end-to-end trace (GoalManager->QuestRuntime->ObjectiveClassifier->...->NextQuestResolver) rather than a discrete component; every named actor in the trace independently exists in source (confirmed while auditing DESIGN-069/083/085/093/098 above), but this section itself is a worked example, not something to mark pass/fail on its own. |
| DESIGN-101 | KUTATÁSI ALAP ÉS WOW-SPECIFIKUS TERVEZÉSI MEGJEGYZÉSEK (wow_agent_complete_functional_design_spec.txt:3102) | UNCLEAR — design-rationale prose (WoW UI research notes: Map & Quest Log, world-map supertracking, Interact Key behavior, GLOBAL/REGIONAL/LOCAL/IMMEDIATE information-scale model). Not a discrete code requirement; the four-tier model is reflected loosely in `quest_info_hierarchy.py`'s A-H ranking but this section is background justification, not a spec to implement literally. |
| DESIGN-102 | DOKUMENTUM HASZNÁLATA (wow_agent_complete_functional_design_spec.txt:3133) | UNCLEAR — meta text describing how to use the design-spec document itself (relationship to "V4"/"V5" prompts, the 7-step implementation checklist). Pure documentation-about-documentation, no code mapping applies. |
| V5-000 | M1 — RUNTIME ARCHITECTURE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:571) | `OFFLINE_VERIFIED` — canonical EventBus/WorldModel/Supervisor/Planner/SkillExecutor/FailureManager/Execution boundaries are separated and enforced by architecture and completion-gate tests; selected-PID timing remains live-open. |
| V5-001 | M1 OBJECTIVE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:575) | `OFFLINE_VERIFIED` — one active skill, one movement/input authority, typed lifecycle/results, evidence-based progress/stuck and bounded recovery are exercised through production boundaries (focused audit: 89 passed). |
| V5-002 | M1.1 REPOSITORY AUDIT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:593) | `OFFLINE_VERIFIED` — `docs/M1_M6_AUDIT.md`, `docs/DEAD_CODE_AUDIT.md`, architecture-boundary tests and the coverage ledger record retained/replaced authorities, direct-input boundary, duplicate/dead paths and unresolved live gates. |
| V5-003 | M1.2 EVENT BUS INTERFACE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:628) | `OFFLINE_VERIFIED` — thread-safe bounded EventBus implements publish/subscribe/unsubscribe/critical/recent operations, observable depth, subscriber exception isolation, event-ID dedupe, low-value coalescing, critical preservation and stable producer ordering. Runtime-load behavior remains live-open. |
| V5-004 | M1.3 WORLD MODEL WRITE POLICY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:662) | `OFFLINE_VERIFIED` — designated reducers remain the only observation writers; every accepted observation records observation ID, monotonic update time, source timestamp, source and model revision for each affected major WorldState section through a stateless tracker. Planning exposure is immutable and diagnostic exposure is isolated. Live attribution remains open. |
| V5-005 | M1.4 WORLD STATE CONTRACT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:684) | `OFFLINE_VERIFIED` — planning snapshots expose an immutable normalized Version/UpdatedAt plus Player, Target, Entity, Combat, Navigation, Quest, Interaction, UI, Map, Environment and Recovery contract. EntityMap remains UNKNOWN-first until semantics are CONFIRMED. Selected-PID field accuracy remains live-open. |
| V5-006 | M1.5 SUPERVISOR FSM (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:767) | `OFFLINE_VERIFIED` — every required state has immutable priority, interruptibility, timeout and bounded retry metadata; explicit enter/tick/exit gates and the minimum preemption matrix are exercised through the production Supervisor. It remains input-free and the Agent retains cancellation, key release and finalization authority. Selected-PID preemption/recovery remains live-open. |
| V5-007 | M1.6 SKILL EXECUTOR (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:816) | `OFFLINE_VERIFIED` — the sole ActiveSkillRuntime exposes the complete CREATED/WAITING_PRECONDITIONS/RUNNING/VERIFYING/RETRYING/RECOVERING/SUCCESS/FAILED/PREEMPTED lifecycle and a typed eight-field SkillContext with observable cancellation. Every registered skill contract declares preconditions, expected postconditions, timeout, retry budget, recovery policy and verification method. Physical dispatch/finalization remains Agent-owned. Live timing remains open. |
| V5-008 | M1.7 VERIFICATION ENGINE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:854) | `OFFLINE_VERIFIED` — bare/start-routine SUCCESS remains pending and cannot author completion. Generic registry, movement, visual and typed M0/domain results reach terminal SUCCESS only through the single postcondition-confirmation boundary; verifier identity/evidence is observable. MOVE, INTERACT, KILL/combat and ACCEPT/quest-dialog postconditions have production-path tests. Selected-PID postcondition latency/accuracy remains live-open. |
| V5-009 | M1.8 FAILURE MANAGER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:878) | `OFFLINE_VERIFIED` — failures are normalized, counted per bounded correlation chain, budgeted and mapped to typed recovery. Exhaustion follows the finite SKILL_RETRY → DOMAIN_RECOVERY → PLANNER_REPLAN → GOAL_ALTERNATIVE → GOAL_FAILED ladder; the Agent/GoalManager consume replan/alternative/failure decisions without giving FailureManager input authority. Persistent goals suppress exhausted tasks. Live recovery effectiveness remains open. |
| V5-010 | M1.9 PROGRESS SCORE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:898) | `OFFLINE_VERIFIED` — configurable validated weights implement the specified five-source normalized score, renormalize only available evidence, reject invalid/nonfinite values and never invent progress. Exact 1.5s/3.0s/0.5s hysteretic possible/hard/recovered gates feed both MovementController and StuckClassifier; sensor dropout resets to UNAVAILABLE. Live calibration remains open. |
| V5-011 | M1.10 STUCK RESOLVER FSM (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:930) | `OFFLINE_VERIFIED` — all 15 required states exist and the finite ladder requires one verified result per emitted step through VERIFY_RECOVERY. NEW_LOCAL_WAYPOINT uses only validated NavigationService geometry and a normal verified MOVE; BLACKLIST_TEMP writes bounded danger memory then terminates/escalates. Cliff ladders exclude JUMP_FORWARD. No resolver input authority exists. Live recovery behavior remains open. |
| V5-012 | M1.11 ANTI-LOOP (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:978) | `OFFLINE_VERIFIED` — bounded rolling ActionSignature, SkillSignature, WorldStateSignature, RouteSegmentSignature and TargetFailureSignature contracts now separate equivalent action/no-state-delta, repeated skill, route failure, target reacquisition and interaction-click loops. Opposite movement commands detect bounded A-B-A-B oscillation. Defaults remain 3/10s SUSPECTED and 5/20s CONFIRMED. Evidence is latched into the sole Supervisor, which emits one interrupting REPLAN; only the Agent cancels/finalizes/releases input. Volatile vision/timestamp payloads do not manufacture state deltas, successful subject attempts clear their typed chains, and total signature storage is bounded. Covered by `tests/test_loop_guard.py`, `tests/test_supervisor.py`, `tests/test_terminal_result.py`, `tests/test_m0_interrupt_resume.py`; full regression 1409 passed, 3 skipped. Selected-PID loop calibration remains live-open. |
| V5-013 | M1.12 M1 ASSERTIONS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1007) | `OFFLINE_VERIFIED` — executable guards enforce all eight assertions: domain/planner/perception/WorldModel concrete-input boundaries (`tests/test_architecture_boundaries.py`), verifier-only terminal success (`tests/test_verification_engine.py`), observable preservation when an all-critical EventBus queue exceeds normal capacity (`tests/test_runtime_event_bus.py`), immediate movement-lease and NavigationService ownership release on combat preemption (`tests/test_m0_interrupt_resume.py`), and StuckResolver exit on recovered progress (`tests/test_stuck_resolver.py`, `tests/test_navigation_progress.py`). Focused assertion regression: 62 passed. Live ownership timing remains open. |
| V5-014 | M1 ACCEPTANCE TESTS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1037) | `OFFLINE_VERIFIED` — all four named deterministic acceptance paths run through production components and pass together; see V5-015..018 and `docs/OFFLINE_ACCEPTANCE_MATRIX.md`. Selected-PID acceptance remains live-open. |
| V5-015 | TEST M1-A NORMAL MOVEMENT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1040) | `OFFLINE_VERIFIED` — `test_arrival_not_first_small_progress_completes_reach` asserts Supervisor NAVIGATION ownership, ProgressScore >0.35, verified arrival SUCCESS and absence of stuck events while one persistent reach attempt is retained. Live motion quality remains open. |
| V5-016 | TEST M1-B STATIC BLOCK (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1054) | `OFFLINE_VERIFIED` — `test_static_block_emits_candidate_then_confirmed_stuck_once` proves delayed POSSIBLE_STUCK then STUCK_DETECTED, resolver entry, one bounded recovery action and verified resume of the original reach. Live obstacle behavior remains open. |
| V5-017 | TEST M1-C RECOVERY ESCALATION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1067) | `OFFLINE_VERIFIED` — StuckResolver tests prove every backward/turn/strafe and later recovery step requires prior failed verification, then LOCAL_REPLAN, REBUILD_CORRIDOR and GLOBAL_REPLAN occur finitely with no blind batch execution. Live recovery effectiveness remains open. |
| V5-018 | TEST M1-D PREEMPTION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1077) | `OFFLINE_VERIFIED` — combat preemption now explicitly releases the executor movement lease and resets NavigationService movement before cancellation, suspends the valid navigation intent, admits combat supervision, then resumes the same quest destination after combat. Selected-PID ownership timing remains open. |
| V5-019 | M1 DEFINITION OF DONE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1089) | `OFFLINE_VERIFIED` — EventBus, canonical WorldModel, explicit Supervisor, verifier-gated skill success, finite failure budgets/anti-loop, ProgressMonitor and StuckResolver are implemented and traced through structured runtime events. All named M1 offline gates pass; this does not claim live completion, and selected-PID telemetry/recovery acceptance remains open. |
| V5-020 | M2 — COMBAT + TARGETING + INTERACTION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1105) | `OFFLINE_VERIFIED` — the canonical TargetManager, CombatSkill, InteractionSkill and LootSkill compose through the single ActiveSkillRuntime, NavigationService and command dispatcher; all M2.1–M2.16 contracts and six named offline acceptance paths are covered. Selected-PID behavior remains live-open. |
| V5-021 | M2 OBJECTIVE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1108) | `OFFLINE_VERIFIED` — targeting, explainable ability selection, action-error correlation, bounded range/facing/LOS/identity recovery, evidence-fused death, closed-loop interaction and evidence-only loot completion are implemented without adding another input or movement authority. Live calibration remains open. |
| V5-022 | M2.1 TARGET MANAGER CONTRACT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1121) | `OFFLINE_VERIFIED` — the single composed `TargetManager` exposes all normalized TargetCandidate score fields, configurable suggested weights and both failure penalties; only live GUID candidates are actionable. Exact-margin ties retain the committed target and switching requires a strict configurable excess. The complete NONE→CANDIDATE→ACQUIRING→ACQUIRED→ENGAGED→OCCLUDED→REACQUIRING→DEAD/LOST/UNREACHABLE lifecycle preserves identity across bounded visual gaps and requires selected-target telemetry to confirm reacquisition. Focused target/combat regression: 15 passed. Live target-switch/occlusion behavior remains open. |
| V5-023 | M2.2 ABILITY MODEL (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1169) | `OFFLINE_VERIFIED` — `AbilityDefinition` exposes every identity, binding, range, timing, cost, targeting/facing/LOS and tag field with the complete nine-value `AbilityTag` vocabulary. Each evaluated action also carries an `AbilityRuntimeState` with explicit readiness, cooldown, resource, range, facing, LOS, usable-confidence, last-attempt and last-result beliefs; missing cooldown fails closed and unknown spatial facts remain uncertainty rather than invented truth. Focused ability/combat regression: 24 passed. Live action-bar field accuracy remains open. |
| V5-024 | M2.3 ABILITY RULE ENGINE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1213) | `OFFLINE_VERIFIED` — typed `AbilityRule` carries RuleId, AbilityId, priority, preconditions, forbidden conditions and expected postconditions. Evaluation returns AbilityCandidate with rule identity, eligibility, stable score and explicit rejection reasons, including named failed/forbidden conditions; it never dispatches or declares cast success. Combat diagnostics expose the bounded top five candidates with rule IDs and rejection reasons. Focused rule/combat regression: 26 passed. Live rotation policy calibration remains open. |
| V5-025 | M2.4 COMBAT FSM (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1241) | `OFFLINE_VERIFIED` — the sole active `CombatSkill` FSM now exposes all 15 required states (IDLE through FAILED). Its production path performs exact target acquisition, ability selection/dispatch/verification, bounded NavigationService-owned approach, typed range/facing/LOS/target recovery, kill confirmation and post-combat terminal verification without creating planner-level MOVE attempts. Focused FSM/runtime regression: 25 passed. Live combat transitions remain open. |
| V5-026 | M2.5 ACTION-ERROR CORRELATION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1284) | `OFFLINE_VERIFIED` — every dispatched combat ability creates a unique `AbilityAttempt` with ability/binding/target and before-state counters. Addon 0.9.26 exports each `UI_ERROR_MESSAGE` into the event stream plus `ui_error_at`, numeric `ui_error_code` and monotonic `ui_error_sequence` on FULL and FAST lanes. The correlator snapshots the pre-cast sequence and accepts only a newer sequence, avoiding both retained-text attribution and unsafe cross-process clock comparison. Matching cast failures, spell-ID gates, cast/resource/health changes and bounded no-effect evidence remain fused on the same COMBAT attempt. Covered by addon, correlation and combat regressions; selected-PID error latency/localization remains live-open. |
| V5-027 | M2.6 OUT OF RANGE RECOVERY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1300) | `OFFLINE_VERIFIED` — RECOVER_RANGE locks the committed GUID, pauses rotation and requests the sole NavigationService to approach at `clamp(maxRange*0.80, 2, 35)` (3.5 fallback only when range is unknown). Target validity is rechecked before every resume. Two direct world approaches are budgeted, then bounded local screen-space correction/replan evidence is attempted; a 3.5s deadline or exhausted correction budget returns typed target-unreachable metadata without further input. Range is verified by normal arrival plus a fresh retry cast, never route exhaustion alone. Focused range/runtime regression: 20 passed. Live distance-belief calibration remains open. |
| V5-028 | M2.7 FACING RECOVERY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1345) | `OFFLINE_VERIFIED` — RECOVER_FACING locks the intended GUID and delegates bounded bearing-derived turns to the shared NavigationService FaceController, with deadzone/hysteresis, continuous re-observation and the required 1.8s timeout. Missing bearing now emits a bounded ±15° active-perception probe request; a centered but contradictory anchor no longer invents a left turn. No full-spin/random-turn fallback exists. Focused facing/navigation/combat regression: 30 passed. Live visual-bearing calibration remains open. |
| V5-029 | M2.8 LOS RECOVERY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1374) | `OFFLINE_VERIFIED` — two evidence-ranked lateral probes are followed by at most one geometry-backed `REPOSITION_FOR_LOS` request through the sole NavigationService; that third step can consume the configured Trinity mmap route. Exhaustion records temporary LOS danger/reachability evidence and terminates. Covered by `tests/test_los_recovery.py`, combat/runtime/navigation and executor-authority tests; selected-PID LOS behavior remains live-open. |
| V5-030 | M2.9 INVALID TARGET RECOVERY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1408) | `OFFLINE_VERIFIED` — `InvalidTargetRecoveryPolicy` checks exact GUID, alive/hostile/targetable/lifecycle/quest relevance and a fresh confirmed anchor. `CombatSkill` clears a wrong selection only through a verified `CLEARTARGET` binding, reacquires the intended identity in the same attempt and exposes alternatives only as planner hints after bounded failure. Covered by `tests/test_invalid_target_recovery.py`. |
| V5-031 | M2.10 KILL VERIFICATION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1427) | `OFFLINE_VERIFIED` — `CombatVerifier` fuses deduplicated independent UNIT_DIED, target-dead, HP-zero, same-GUID corpse, objective-credit and combat-ended evidence with noisy-OR; threshold is 0.85 and combat-ended alone cannot confirm death. Stats/progress occur only after verified terminal success. Covered by `tests/test_combat_death_fusion.py` and M2 assertions. |
| V5-032 | M2.11 INTERACTION ENGINE FSM (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1449) | `OFFLINE_VERIFIED` — `InteractPhase` contains the exact 11-state IDLE→RESOLVE_TARGET→APPROACH→FACE→HOVER→VERIFY_HOVER→INTERACT→WAIT_RESULT→CLASSIFY_RESULT→RECOVER→SUCCESS/FAILED lifecycle. `InteractionRuntimeRunner` delegates movement/facing/LOS to NavigationService without dispatching or finalizing independently. |
| V5-033 | M2.12 HOVER VERIFICATION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1468) | `OFFLINE_VERIFIED` — up to four points are ranked learned-point, NPC upper torso, center and lateral samples; each pointer position waits at least 120 ms for fresh GUID/track/confidence-correlated mouseover before advancing. Exhaustion fails/replans rather than guessing. Covered by `tests/test_interaction_m2_matrix.py`. |
| V5-034 | M2.13 INTERACTION RESULT CLASSIFIER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1499) | `OFFLINE_VERIFIED` — `InteractionResultClassifier.classify_effect()` returns every specified GOSSIP/QUEST_DETAIL/QUEST_PROGRESS/QUEST_COMPLETE/MERCHANT/LOOT/OBJECT_ACTIVATED/TARGET_CHANGED/NOTHING/UNKNOWN result from explicit UI, event and state deltas. It does not itself claim skill success. |
| V5-035 | M2.14 INTERACTION FAILURE MATRIX (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1522) | `OFFLINE_VERIFIED` — typed TOO_FAR/FACING/LOS/CURSOR_MISS/WRONG_ENTITY/ENTITY_MOVED/UI_NOT_READY/TARGET_LOST/UNKNOWN rules map to bounded approach, face, reposition, resample, reacquire, wait or one observation. Budgets are finite and tested in `tests/test_interaction_m2_matrix.py`. |
| V5-036 | M2.15 LOOT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1559) | `OFFLINE_VERIFIED` — `LootVerifier` accepts correlated loot events, relevant inventory delta, objective delta where no explicit item contract exists, or fused loot-UI/corpse-state evidence; a click or open loot window alone never increments/claims loot. `LootRuntimeRunner` routes corpse approach through NavigationService. |
| V5-037 | M2.16 M2 ASSERTIONS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1574) | `OFFLINE_VERIFIED` — executable `tests/test_m2_assertions.py` guards no cast without target, no weak-evidence kill, finite range/LOS recovery, no click-only interaction success, intended-target preservation and absence of direct combat input/movement authority. |
| V5-038 | M2 ACCEPTANCE TESTS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1587) | `OFFLINE_VERIFIED` — all six named deterministic paths are green and referenced in `docs/OFFLINE_ACCEPTANCE_MATRIX.md`; focused M2 closure regression: 65 passed. Live rows remain open. |
| V5-039 | M2-A NORMAL COMBAT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1590) | `OFFLINE_VERIFIED` — production CombatController/CombatSkill tests cover acquire, eligible ability, dispatch, damage/cast observation, evidence-fused death and POST_COMBAT. |
| V5-040 | M2-B RANGE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1600) | `OFFLINE_VERIFIED` — correlated OUT_OF_RANGE enters RECOVER_RANGE, one persistent NavigationService approach owns movement, and rotation resumes only after arrival/identity recheck; finite budgets prevent cast spam while moving. |
| V5-041 | M2-C FACING (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1609) | `OFFLINE_VERIFIED` — facing error enters RECOVER_FACING, shared FaceController applies bounded bearing correction with verification, then the same attempt retries; missing bearing requests bounded active perception rather than a blind turn. |
| V5-042 | M2-D LOS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1617) | `OFFLINE_VERIFIED` — LOS uses two evidence-ranked lateral probes, then one geometry/mmap-capable local replan and terminates as TARGET_UNREACHABLE on exhaustion; no infinite casting. |
| V5-043 | M2-E TARGET OCCLUSION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1626) | `OFFLINE_VERIFIED` — `tests/test_v5_m2_target_occlusion_acceptance.py` proves OCCLUDED→REACQUIRING→ENGAGED retains the same GUID and TrackId and requires selected-target telemetry before resuming. |
| V5-044 | M2-F NPC INTERACTION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1633) | `OFFLINE_VERIFIED` — approach/face/hover/interact stay in one attempt; quest/gossip state delta is required for SUCCESS. Production runner and M0 acceptance replays cover the full path. |
| V5-045 | M2 DEFINITION OF DONE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1642) | `OFFLINE_VERIFIED` — combat is FSM-driven with explicit target/ability/error/recovery contracts; kill, interaction and loot are evidence-verified; all movement/input remains under canonical services. This closes offline M2 only; selected-PID acceptance remains live-open. |
| V5-046 | M3 — QUEST EXECUTION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1656) | `OFFLINE_VERIFIED` — the production WorldModel/QuestModel/QuestExecutionRuntime/Planner orchestrate existing Navigation, Combat, Interaction and Loot skills; the adaptive acceptance environment proves a complete multi-step lifecycle without a prerecorded input sequence. Selected-PID execution remains live-open. |
| V5-047 | M3 OBJECTIVE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1659) | `OFFLINE_VERIFIED` — quest logic normalizes WHAT/WHERE and proposes shared generic capabilities; it neither dispatches input nor embeds combat/movement implementations. Architecture assertions and adaptive acceptance cover the boundary. |
| V5-048 | M3.1 QUEST MODEL (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1668) | `OFFLINE_VERIFIED` — canonical `QuestState` includes every required lifecycle state; `QuestRecord` carries identity/title/state/confidence/dependencies/objectives/giver/turn-in/reward beliefs, typed chain relations, evidence history and monotonic update time. Missing quests become ABSENT, never fabricated completion. |
| V5-049 | M3.2 OBJECTIVE MODEL (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1700) | `OFFLINE_VERIFIED` — `QuestObjective` and `ObjectiveState` normalize required types, descriptors, counts, confidence, location/dependencies/status and failure-memory key. Ambiguous text remains UNKNOWN and undeclared list order does not invent dependency. |
| V5-050 | M3.3 OBJECTIVE → SKILL TEMPLATES (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1741) | `OFFLINE_VERIFIED` — `QuestDomain` plus Planner horizons map kill/collect/interact/use/travel/follow/escort/explore/turn-in objectives onto shared search, navigation, target, combat, loot, interaction and verification capabilities. Future steps are diagnostic only; the active skill remains singular. |
| V5-051 | M3.4 QUEST ACCEPT FLOW (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1799) | `OFFLINE_VERIFIED` — giver localization/approach/identity/dialog selection use shared services; `QuestDialogSkill` and `QuestProgressVerifier` require active-quest, accepted-event, tracker/log or equivalent state evidence. Click alone cannot confirm acceptance. |
| V5-052 | M3.5 TURN-IN FLOW (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1822) | `OFFLINE_VERIFIED` — completion mode, turn-in localization, dialog state, reward selection and turned-in event verification are explicit. Ambiguous rewards require policy rather than arbitrary clicking. Covered by quest-dialog/reward/runtime tests and the adaptive lifecycle. |
| V5-053 | M3.6 QUEST GRAPH (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1839) | `OFFLINE_VERIFIED` — objective readiness blocks unmet quest/objective/conditional dependencies and preserves completed history. The graph now exposes explicit quest nodes and normalized REQUIRES/UNLOCKS/FOLLOW_UP/EXCLUSIVE_WITH/SAME_AREA_SYNERGY edges without inferring relations from ID or list order; covered by `tests/test_quest_model.py`. |
| V5-054 | M3.7 BATCHING (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1859) | `OFFLINE_VERIFIED` — batching is conservative as permitted by the spec: only explicit `SAME_AREA_SYNERGY` is represented, while the single-primary-objective runtime refuses speculative interleaving when order/location confidence is insufficient. No objective state is invalidated by travel optimization. Positive live batching remains optional/live-open. |
| V5-055 | M3.8 SEARCH POLICY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1871) | `OFFLINE_VERIFIED` — localization/search planning consumes known track, recent/entity memory, location memory, minimap, world map and bounded local/broadened coverage in evidence order, then fails/replans after budget. It does not equate 3D absence with no objective. |
| V5-056 | M3.9 SEARCH COVERAGE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1888) | `OFFLINE_VERIFIED` — `SearchCoveragePlanner` stores region/cell visit state, emits each cell once, stops on detection and terminates exhausted coverage instead of rescanning indefinitely; covered by `tests/test_search_coverage.py`. |
| V5-057 | M3.10 QUEST PROGRESS FUSION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1902) | `OFFLINE_VERIFIED` — the authoritative `QuestProgressVerifier` fuses objective counters, active/complete/turn-in state and quest events. Combat/loot/item action success with unchanged quest telemetry is explicitly rejected by M3 acceptance tests. |
| V5-058 | M3.11 QUEST FAILURE MEMORY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1915) | `OFFLINE_VERIFIED` — bounded `QuestFailureMemory` keys failures by quest/objective/target/skill/reason and applies cooldown only to the same failed strategy; alternatives remain available. Covered by `tests/test_quest_failure_memory.py`. |
| V5-059 | M3.12 QUEST RECOVERY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1929) | `OFFLINE_VERIFIED` — no-credit escalation, failure memory, map/marker reinspection, bounded search broadening and typed skill failure feed the canonical replan path. The adaptive acceptance injects a failed interaction and proves bounded retry/resume to completion. |
| V5-060 | M3.13 M3 ASSERTIONS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1952) | `OFFLINE_VERIFIED` — tests enforce evidence-only quest transitions, no action-only objective increment, quest policy without input/movement/combat authority, shared Interaction/Combat skills and finite search escalation. |
| V5-061 | M3 ACCEPTANCE TEST (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1963) | `OFFLINE_VERIFIED` — `tests/test_v5_m3_adaptive_quest_environment.py` drives the production agent through offer, accept, movement, combat, loot credit, return, induced interaction failure/retry, turn-in and follow-up discovery. Observations react to the selected skill, so a wrong decision cannot advance the scenario. Focused M3 regression: 33 passed. |
| V5-062 | M3 DEFINITION OF DONE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:1988) | `OFFLINE_VERIFIED` — generic objective execution, explicit graph/readiness, bounded search coverage, evidence-only progress and recoverable quest failures are present without duplicated domain authority. This closes offline M3 only; a real beginning questline remains live-open. |
| V5-063 | M4 — WORLD3D / PERCEPTION / TEMPORAL TRACKING (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2000) | `OFFLINE_VERIFIED` — canonical frame-bound detection, UNKNOWN-first temporal tracking, motion/distance/bearing beliefs, traversability fusion, UI/map/tooltip adapters and bounded ActivePerception are integrated as evidence producers only. M4 acceptance and OBS-A–J are green; live calibration remains open. |
| V5-064 | M4 OBJECTIVE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2003) | `OFFLINE_VERIFIED` — domain consumers receive persistent tracks and fused temporal beliefs rather than single-frame semantic facts. Source FrameId, confidence, lifecycle and coordinate-space contracts are validated before publication. |
| V5-065 | M4.1 FRAME SOURCE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2010) | `OFFLINE_VERIFIED` — `WorldFrameObservation`/`World3DObservationBatch` preserve monotonic timestamp, client/frame identity and dropped-frame events; malformed/out-of-order frames fail closed in `tests/test_world3d_pipeline.py`. |
| V5-066 | M4.2 DETECTION CONTRACT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2028) | `OFFLINE_VERIFIED` — frame-bound detections carry id, class distribution, bbox, confidence/features and preserve UNKNOWN over false certainty; validation rejects cross-frame or non-normalized distributions. |
| V5-067 | M4.3 TRACKER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2054) | `OFFLINE_VERIFIED` — the learned production path now associates canonical client-pixel detections with Ultralytics BoT-SORT (Kalman, sparse-optical-flow camera compensation, bounded lost buffer and visual-family gating), while `WorldCandidateTracker` remains the explicit fallback. Background warm-up preserves the already-published public TrackId at cutover. Camera-pan, crossing-family, short-gap and non-blocking handoff tests preserve visual identity; selected-PID live validation remains open. |
| V5-068 | M4.4 TEMPORAL FILTER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2085) | `OFFLINE_VERIFIED` — raw detection geometry remains traceable while screen center, bbox, velocity, bearing and relative-distance trends are temporally smoothed. |
| V5-069 | M4.5 MOTION ESTIMATOR (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2100) | `OFFLINE_VERIFIED` — pipeline publishes camera/ego/entity motion and optical-flow summary with confidence; rotation is explicitly distinguished from translation. |
| V5-070 | M4.6 DISTANCE BELIEF (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2117) | `OFFLINE_VERIFIED` — distance is a confidence-bearing relative-scale bucket/trend with sources; exact meters remain absent unless genuinely calibrated. |
| V5-071 | M4.7 BEARING (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2147) | `OFFLINE_VERIFIED` — `BearingEstimate` exposes normalized camera-relative horizontal bearing in [-1,+1] with explicit coordinate space and confidence. |
| V5-072 | M4.8 FREE SPACE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2161) | `OFFLINE_VERIFIED` — local polar sectors expose traversable/blocked/danger/uncertain/unknown beliefs and confidence without requiring semantic obstacle class. |
| V5-073 | M4.8A WORLD3D OBSTACLE / TRAVERSABILITY SYSTEM (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2185) | `OFFLINE_VERIFIED` — `World3DPipeline` plus `TemporalTraversabilityFusion` form the dedicated evidence-only stack consumed through WorldModel/NavigationService, never an input path. |
| V5-074 | M4.8B TRAVERSABILITY CELL CONTRACT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2229) | `OFFLINE_VERIFIED` — sectors carry every required score/confidence/lifecycle/timestamp/evidence field and a non-fact marker; LocalPlanner consumes the contract. |
| V5-075 | M4.8C PRIMARY OBSERVATION CHANNELS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2269) | `OFFLINE_VERIFIED` — ground/free/boundary/depth/motion/collision/persistence/dynamic/failure evidence remain independent, optional inputs and are fused only when present. |
| V5-076 | M4.8D GROUND REGION ESTIMATOR (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2289) | `OFFLINE_VERIFIED` — lower-viewport ground evidence is region/texture/boundary based, confidence-bearing and temporally fused; it is not exposed as a semantic fact. Retail calibration remains live-open. |
| V5-077 | M4.8E FREE SPACE ESTIMATOR (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2328) | `OFFLINE_VERIFIED` — free-space confidence requires positive region evidence and is fused against boundary/motion evidence; dark/empty pixels alone do not create a hard free-space fact. |
| V5-078 | M4.8F VISUAL BOUNDARY ESTIMATOR (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2347) | `OFFLINE_VERIFIED` — stable obstacle/boundary overlap contributes configurable evidence but one ambiguous frame cannot hard-block. |
| V5-079 | M4.8G DEPTH DISCONTINUITY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2374) | `OFFLINE_VERIFIED` — optional relative depth-discontinuity confidence is represented honestly and omitted from fusion when unavailable; no fake metric depth is generated. |
| V5-080 | M4.8H MOTION-CONDITIONED OBSTACLE DETECTION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2399) | `OFFLINE_VERIFIED` — commanded forward motion is compared with observed progress; camera rotation cannot fabricate frontal collision. |
| V5-081 | M4.8I EGO-MOTION ESTIMATOR (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2439) | `OFFLINE_VERIFIED` — commanded/observed motion categories and confidence are kept separate; persistent mismatch produces typed evidence/event. |
| V5-082 | M4.8J COLLISION EVIDENCE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2472) | `OFFLINE_VERIFIED` — direction-aware collision evidence explains low progress but remains distinct from the agent-level stuck decision. |
| V5-083 | M4.8K OBSTACLE CONFIDENCE FUSION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2493) | `OFFLINE_VERIFIED` — configurable weighted fusion renormalizes only available channels; missing depth/motion cannot dilute evidence. |
| V5-084 | M4.8L TEMPORAL OBSTACLE FUSION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2533) | `OFFLINE_VERIFIED` — NEW/SUSPECTED/CONFIRMED/DYNAMIC/DECAYING/CLEARED lifecycle is bounded and tested; one clean/ambiguous frame does not create or erase a confirmed static block. |
| V5-085 | M4.8M DYNAMIC OBSTACLES (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2566) | `OFFLINE_VERIFIED` — high dynamic probability produces temporary `DYNAMIC` lifecycle/cost and `DYNAMIC_OBSTACLE_UPDATED`, never a permanent static blacklist. |
| V5-086 | M4.8N LOCAL OCCUPANCY MAP (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2600) | `OFFLINE_VERIFIED` — egocentric polar sectors expose free/occupied/danger/unknown state, age and dynamic/static belief without pretending global metric coordinates. |
| V5-087 | M4.8O TRAVERSABILITY COST MAP (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2627) | `OFFLINE_VERIFIED` — configurable local planner scoring prefers safe traversable sectors, retains uncertainty cost and treats confirmed/drop danger as prohibitive. |
| V5-088 | M4.8P CLIFF / DROP DETECTION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2653) | `OFFLINE_VERIFIED` — drop evidence is separate from wall evidence; first detection emits `CLIFF_SUSPECTED`, temporal confirmation emits `CLIFF_CONFIRMED`, and recovery forbids forward jump. |
| V5-089 | M4.8Q WATER / TERRAIN TRANSITION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2691) | `OFFLINE_VERIFIED` — explicit `TerrainTransition` evidence carries type/traversability belief/risk/confidence; water defaults to UNKNOWN policy, not globally forbidden. |
| V5-090 | M4.8R NARROW PASSAGE / DOORWAY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2710) | `OFFLINE_VERIFIED` — side-blocked/centre-free acceptance retains the central corridor and chooses centered local motion rather than blocking the doorway. |
| V5-091 | M4.8S MOTION PROBE / ACTIVE PERCEPTION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2727) | `OFFLINE_VERIFIED` — bounded, cancellable information probes have timeout/gain/terminal state and no independent input authority. |
| V5-092 | M4.8T STATIC VS DYNAMIC CLASSIFICATION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2756) | `OFFLINE_VERIFIED` — temporal persistence/motion evidence separates confirmed static blockage from temporary dynamic cost. |
| V5-093 | M4.8U TRAVERSABILITY EVENTS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2772) | `OFFLINE_VERIFIED` — all named update/suspect/confirm/clear/dynamic/cliff/mismatch/collision events include sector, confidence, evidence refs and timestamp. |
| V5-094 | M4.8V RELATION TO PROGRESS MONITOR (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2794) | `OFFLINE_VERIFIED` — obstacle explanation and objective progress remain distinct inputs to typed stuck classification. |
| V5-095 | M4.8W RELATION TO STUCK RESOLVER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2822) | `OFFLINE_VERIFIED` — resolver consumes progress/traversability/collision/dynamic/drop/recovery history and applies typed bounded ladders. |
| V5-096 | M4.8X FAILURE MEMORY INTEGRATION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2854) | `OFFLINE_VERIFIED` — repeated supported failures add TTL/decaying danger priors; one transient false positive cannot permanently poison routing. |
| V5-097 | M4.8Y OBSTACLE DEBUG OVERLAY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2866) | `OFFLINE_VERIFIED` — `diagnostics.obstacle_overlay()` provides a read-only `OBSTACLE_OVERLAY_V1` projection with ground/free/blocked/unknown/drop/dynamic confidence, traversal cost, expected/observed ego-motion, collision evidence and selected local waypoint. It never classifies, plans or sends input; covered by `tests/test_obstacle_overlay.py`. |
| V5-098 | M4.8Z OBSTACLE ACCEPTANCE TESTS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:2888) | `OFFLINE_VERIFIED` — `tests/test_v5_m4_obstacle_acceptance.py` executes OBS-A through OBS-J through production fusion, progress, stuck, local-planning, danger and active-perception boundaries. |
| V5-099 | M4.9 CLIFF / EDGE POLICY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3020) | `OFFLINE_VERIFIED` — confidence tiers produce observe/slow versus danger/hard-block behavior; no ambiguous single frame authorizes forward recovery. |
| V5-100 | M4.10 MINIMAP (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3033) | `OFFLINE_VERIFIED` — minimap adapters keep center/player contract, heading, movement, UNKNOWN markers/POI evidence and separate confidences; rim/cardinal decorations are excluded. |
| V5-101 | M4.11 WORLD MAP (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3048) | `OFFLINE_VERIFIED` — map state/calibration track open/map/zoom/pan/player/marker evidence without fixed-resolution assumptions. |
| V5-102 | M4.12 TOOLTIP (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3064) | `OFFLINE_VERIFIED` — tooltip observation carries text/name/type/relation/confidence/hover point/frame and only fuses when fresh point/track association holds. |
| V5-103 | M4.13 ACTIVE PERCEPTION FSM (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3081) | `OFFLINE_VERIFIED` — REQUESTED→SELECT_ACTION→EXECUTE_PROBE→WAIT_OBSERVATION→EVALUATE_GAIN→terminal FSM is bounded and safety-preemptible. |
| V5-104 | M4.14 UI PARSER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3115) | `OFFLINE_VERIFIED` — `vision.ui_parser` emits state/confidence/frame/timestamp for player, target, cast, quest, gossip, merchant, loot, tracker, error and loading recognizers. |
| V5-105 | M4.15 PERCEPTION FUSION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3137) | `OFFLINE_VERIFIED` — semantic fusion joins World3D/tooltip/mouseover/UI evidence by canonical identity and source family, preserving UNKNOWN and reducing correlated-source double counting. |
| V5-106 | M4.16 DATASET PIPELINE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3151) | `OFFLINE_VERIFIED` — YOLO dataset audit verifies taxonomy/labels/splits/duplicate leakage/full-frame boxes and `HardExampleCollector` captures uncertain/contradictory crops; no trained-model claim is made without an artifact. |
| V5-107 | M4.17 M4 ASSERTIONS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3169) | `OFFLINE_VERIFIED` — validation/tests require FrameId and bounded confidence, preserve tracks across one miss, reject stale target geometry, keep ActivePerception input-free and distinguish camera rotation from translation. |
| V5-108 | M4 ACCEPTANCE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3180) | `OFFLINE_VERIFIED` — all six named temporal-perception scenarios plus the ten obstacle scenarios pass through production components; focused M4 audit regression: 43 passed, overlay closure: 30 passed. |
| V5-109 | M4-A: (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3183) | `OFFLINE_VERIFIED` — tracking tests preserve the same NPC TrackId across movement and relation changes. |
| V5-110 | M4-B: (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3186) | `OFFLINE_VERIFIED` — a short miss produces OCCLUDED and matching return produces REACQUIRED rather than a new identity. |
| V5-111 | M4-C: (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3189) | `OFFLINE_VERIFIED` — camera rotation is represented as ego/camera motion and cannot fabricate collision or independent entity motion. |
| V5-112 | M4-D: (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3192) | `OFFLINE_VERIFIED` — fresh point/track-correlated tooltip evidence strengthens entity identity without making raw CV ground truth. |
| V5-113 | M4-E: (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3195) | `OFFLINE_VERIFIED` — repeated obstacle evidence updates temporal local traversability/cost while one transient frame decays. |
| V5-114 | M4-F: (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3198) | `OFFLINE_VERIFIED` — low-confidence evidence can request a bounded information probe which terminates SUCCESS/FAILED and may leave explicit UNKNOWN. |
| V5-115 | M4 DEFINITION OF DONE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3203) | `OFFLINE_VERIFIED` — temporal tracks, confidence-bearing UNKNOWN-first evidence, map/minimap/UI fusion, bounded ActivePerception and no single-frame action shortcut are present. Real-image/selected-PID calibration remains live-open. |
| V5-116 | M5 — NAVIGATION V5 (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3214) | `OFFLINE_VERIFIED` — the sole NavigationService composes global plan/corridor/local plan/movement/progress/stuck/danger/reachability/memory/follow/LOS/search/arrival, including optional Trinity mmap corridors for verified WORLD_YARDS endpoints. Named offline acceptance is green; live route quality remains open. |
| V5-117 | M5 OBJECTIVE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3217) | `OFFLINE_VERIFIED` — navigation is persistent, closed-loop and evidence-driven; Planner supplies destinations while NavigationService exclusively owns route/control/recovery. Local traversability can override static route guidance without creating a second authority. |
| V5-118 | M5.1 NAVIGATION REQUEST (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3224) | `OFFLINE_VERIFIED` — typed `NavigationRequest` carries identity/correlation/mode/destination/entity/range/arrival/combat policy/priority/timeout and rejects invalid coordinate authority. |
| V5-119 | M5.2 GLOBAL PLAN (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3251) | `OFFLINE_VERIFIED` — `GlobalPlanner` returns bounded routes with anchors/regions/cost/confidence/validity and replans on explicit invalidation, not control ticks; optional mmap is a read-only route source. |
| V5-120 | M5.3 PATH CORRIDOR (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3282) | `OFFLINE_VERIFIED` — `PathCorridorBuilder` produces route-bound segments/width/confidence while allowing LocalPlanner to choose safer non-centre local waypoints. |
| V5-121 | M5.4 LOCAL PLANNER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3298) | `OFFLINE_VERIFIED` — `LocalPlanner` scores traversability/corridor/danger/failure evidence and returns desired heading/local waypoint/mode/expected progress/validity; UNKNOWN geometry can block without semantic class. |
| V5-122 | M5.4A OBSTACLE/TRAVERSABILITY COUPLING (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3332) | `OFFLINE_VERIFIED` — closed loop is World3D traversability→LocalPlanner→MovementController→motion feedback→collision/progress/stuck; transient local obstacles do not force global replan. |
| V5-123 | M5.5 MOVEMENT CONTROLLER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3378) | `OFFLINE_VERIFIED` — persistent closed-loop movement owns steering/forward/stop with heading bands and fresh feedback; Planner never emits millisecond key pulses. |
| V5-124 | M5.6 PROGRESS MODEL (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3406) | `OFFLINE_VERIFIED` — configurable rolling fusion reports progress, direction consistency, oscillation and stuck probability from only available signals with hysteresis. |
| V5-125 | M5.7 STUCK CLASSIFIER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3426) | `OFFLINE_VERIFIED` — `StuckClassifier` covers static/corner/oscillation/no-progress/wrong-heading/dynamic/unreachable/path-loop/unknown using corroborated evidence. |
| V5-126 | M5.8 TYPE-AWARE RECOVERY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3458) | `OFFLINE_VERIFIED` — `StuckResolver` applies finite type-specific ladders and verification; cliff never jumps forward and only path-loop escalation requests global rebuild. |
| V5-127 | M5.9 DANGER MAP (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3489) | `OFFLINE_VERIFIED` — typed `DangerMap` entries carry region/radius/cost/confidence/source/expiry and decay; route scoring consumes them as bias. |
| V5-128 | M5.10 HOSTILE AGGRO REGION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3515) | `OFFLINE_VERIFIED` — hostile confidence creates approximate temporary cost; avoid/allow-combat policy and intended kill target exemptions are tested in danger routing. |
| V5-129 | M5.11 REACHABILITY MODEL (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3531) | `OFFLINE_VERIFIED` — per-target reachability retains confidence, recent failure types, success and cooldown; repeated navigation/LOS failures lower confidence. |
| V5-130 | M5.12 NAVIGATION MEMORY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3545) | `OFFLINE_VERIFIED` — success/failure route memory is bounded, TTL/decay aware and used as a cost bias rather than absolute truth. |
| V5-131 | M5.13 FOLLOW (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3568) | `OFFLINE_VERIFIED` — FOLLOW maintains a distance band, predicts/reacquires briefly and refuses indefinite pursuit of stale target position. |
| V5-132 | M5.14 REPOSITION FOR LOS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3590) | `OFFLINE_VERIFIED` — bilateral traversability-ranked LOS probes and one optional mmap geometry replan are finite; success requires improved LOS/probe evidence. |
| V5-133 | M5.15 SEARCH REGION (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3610) | `OFFLINE_VERIFIED` — bounded cell coverage tracks visited/detections/danger, avoids immediate repeats and terminates on target or exhaustion. |
| V5-134 | M5.16 ARRIVAL (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3626) | `OFFLINE_VERIFIED` — `ArrivalVerifier` requires a fresh location/range envelope, stabilized motion and no contradiction; route exhaustion alone cannot succeed. |
| V5-135 | M5.17 M5 ASSERTIONS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3640) | `OFFLINE_VERIFIED` — tests enforce one movement authority, typed coordinate spaces, progress-before-recovery, finite stuck escalation, traversability-aware local planning and arrival from fresh evidence rather than command/route exhaustion. |
| V5-136 | M5 ACCEPTANCE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3652) | `OFFLINE_VERIFIED` — all nine named V5 paths are green; focused navigation/mmap regression: 44 passed. Selected-PID execution remains live-open. |
| V5-137 | M5-A normal destination (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3655) | `OFFLINE_VERIFIED` — one persistent request follows its corridor and only fresh arrival evidence terminates it. |
| V5-138 | M5-B static obstacle local bypass (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3656) | `OFFLINE_VERIFIED` — confirmed traversability alters the local waypoint without immediately forcing global replan. |
| V5-139 | M5-C repeated block → failure memory + alternate route (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3657) | `OFFLINE_VERIFIED` — repeated supported failure writes bounded danger memory and rebuilds an alternative corridor. |
| V5-140 | M5-D hostile region → cost-based avoidance (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3658) | `OFFLINE_VERIFIED` — danger cost produces a safer detour whose waypoints execute sequentially. |
| V5-141 | M5-E moving NPC follow (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3659) | `OFFLINE_VERIFIED` — follow maintains a tested distance band and preserves leader identity. |
| V5-142 | M5-F Combat LOS reposition (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3660) | `OFFLINE_VERIFIED` — CombatSkill delegates bounded LOS reposition to NavigationService and resumes the same attempt. |
| V5-143 | M5-G Interaction approach to usable range (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3661) | `OFFLINE_VERIFIED` — interaction approach remains one active attempt and resumes only after navigation arrival. |
| V5-144 | M5-H Search region systematic coverage (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3662) | `OFFLINE_VERIFIED` — bounded cells are visited once and coverage stops on detection or exhaustion. |
| V5-145 | M5-I induced oscillation → detected and broken (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3663) | `OFFLINE_VERIFIED` — alternating movement is evidence-gated, detected, bounded and cleared on recovered progress. |
| V5-146 | M5 DEFINITION OF DONE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3665) | `OFFLINE_VERIFIED` — canonical persistent navigation, local/world route sources, obstacle coupling, progress/stuck/recovery, danger/reachability memory and all named acceptance paths are present. Live calibration remains open. |
| V5-147 | M6 — END-TO-END INTEGRATION / FULL ACCEPTANCE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3679) | `OFFLINE_PARTIAL` — all named deterministic M1–M6 component/integration scenarios are green, but the selected-PID autonomous questline, induced failures and long-run performance remain live-open; M6 is not release-complete. |
| V5-148 | M6 OBJECTIVE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3682) | `OFFLINE_PARTIAL` — production Planner/SkillExecutor completes an adaptive beginning-quest scenario with bounded recovery offline; live robustness/observability evidence is still required. |
| V5-149 | M6.1 CANONICAL PIPELINE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3696) | `OFFLINE_VERIFIED` — architecture-boundary and replay tests trace Goal→Plan→Supervisor→Skill→domain→ActionRequest→Input→Observation/Evidence/Event/WorldModel→Verification/Result through one authority. |
| V5-150 | M6.2 REFLEX CONTROLLER (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3719) | `OFFLINE_VERIFIED` — the low-level `InputScheduler` watchdog is bounded to key release/emergency stop; it logs diagnostics and contains no gameplay policy. |
| V5-151 | M6.3 CROSS-DOMAIN ENTITY ID (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3734) | `OFFLINE_VERIFIED` — `world_entity_id` canonicalization and `WorldEntity` tests keep combat/navigation/interaction/quest references on one identity. |
| V5-152 | M6.4 PLAN RESUME (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3746) | `OFFLINE_VERIFIED` — combat preemption releases movement, suspends intent data only and safely resumes/revalidates the same quest-navigation subgoal. |
| V5-153 | M6.5 DEATH RECOVERY (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3761) | `OFFLINE_VERIFIED` — death cancels skills/releases input, preserves the high-level goal and pauses MANUAL with an explicit external recovery condition; no blind revive script exists. |
| V5-154 | M6.6 LOADING / DISCONNECT / MODAL (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3780) | `OFFLINE_VERIFIED` — Supervisor priority gates block/cancel/release input and create explicit recovery checkpoints for loading, disconnect, cinematic and unexpected modal. |
| V5-155 | M6.7 STALE STATE GUARD (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3797) | `OFFLINE_VERIFIED` — freshness gates and per-domain verifiers refuse stale target/map/UI/quest evidence and reobserve or pause instead of acting. |
| V5-156 | M6.8 WATCHDOG (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3814) | `OFFLINE_VERIFIED` — `HealthMonitor`, input watchdog and loop guard expose capture/event/supervisor/input/repeat stalls; unsafe input is bounded/released and health reporting has no hidden gameplay authority. |
| V5-157 | M6.9 REPLAY PACKAGE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3832) | `OFFLINE_VERIFIED` — typed JSONL records session/observation/event/world delta/skill/command/verification/checkpoint and replays decision logic while explicitly forbidding a real input executor. |
| V5-158 | M6.10 STRUCTURED LOG FORMAT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3853) | `OFFLINE_VERIFIED` — bounded structured entries include timestamp/level/module/type/correlation/entity/message/payload and diagnostics sinks cannot alter control. |
| V5-159 | M6.11 PERFORMANCE BUDGET (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3876) | `OFFLINE_VERIFIED` — bounded `PerformanceMonitor` reports capture FPS, queue depth and p50/p95 named latency channels without changing failure semantics. Long-run selected-PID budget evidence remains open. |
| V5-160 | M6.12 END-TO-END ACCEPTANCE SCENARIO (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3891) | `OFFLINE_VERIFIED` — adaptive environment advances only in response to actual selected skills and covers accept→navigate→combat→kill→loot credit→return→failed interaction/retry→turn-in→follow-up. Selected-PID completion remains live-open. |
| V5-161 | M6.13 INDUCED FAILURE SUITE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3913) | `OFFLINE_VERIFIED` — all F01–F15 rows have deterministic linked evidence in `docs/M6_INDUCED_FAILURE_MATRIX.md`; every live column remains OPEN. |
| V5-162 | M6.14 EXAMPLE EXPECTED TRANSITIONS (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3941) | `OFFLINE_VERIFIED` — range/facing/LOS/stuck/interaction-miss production tests assert the requested typed, bounded recovery transitions. |
| V5-163 | M6.15 NO-FAKE-SUCCESS AUDIT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:3997) | `OFFLINE_VERIFIED` — verifier/terminal tests require observable postconditions before SUCCESS; combat death cannot fabricate quest credit and route exhaustion cannot fabricate arrival. |
| V5-164 | M6.16 PLACEHOLDER AUDIT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:4016) | `OFFLINE_VERIFIED` — static audit records remaining non-critical/dev-only markers; critical action paths are exercised by production-boundary tests rather than placeholder success. |
| V5-165 | M6.17 DIRECT INPUT AUDIT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:4034) | `OFFLINE_VERIFIED` — Windows `SendInput`/cursor calls exist only in the selected-PID backend; production domains route commands through CommandDispatcher/InputScheduler. |
| V5-166 | M6.18 DUPLICATION AUDIT (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:4048) | `OFFLINE_VERIFIED` — one NavigationService, ActiveSkillRuntime, WorldModel and interaction/combat domain authority are enforced by architecture-boundary tests; adapters do not own control. |
| V5-167 | M6.19 TEST REPORT MATRIX (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:4066) | `OFFLINE_VERIFIED` — `docs/OFFLINE_ACCEPTANCE_MATRIX.md` and `docs/M6_INDUCED_FAILURE_MATRIX.md` list scenario/status/evidence/recovery/remaining live proof; `LIVE_VALIDATION.md` remains separate. |
| V5-168 | M6.20 RELEASE GATE (wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt:4081) | `OFFLINE_PARTIAL` — offline architecture, bounded recovery and adaptive questline gates are green. Release remains explicitly blocked on selected-PID autonomous questline, live F01–F15 and long-run performance evidence. |

2026-10-15 DESIGN-007 tracker note: the detector-rate WorldCandidateTracker
bridge now carries tentative fallback detections into the same public ID used
after native confirmation, and has a bounded, conservative appearance ReID
gallery. Focused tests are offline evidence only; camera-turn ID continuity
and false-merge rate remain **live-open**, not live-validated. No semantic
NPC/GUID identity authority was added to the visual tracker. The context key
now ignores subpixel minimap measurement noise but retains true scene/frame
size invalidations. The 2026-10-15 user run showed long-turn continuity still
fails; Live Vision now exposes both presentation and V3 IDs plus bounded
transition diagnostics (`OFFLINE_VERIFIED` for observability only). Long-gap
ReID remains `PARTIAL`/live-open, not completed by this instrumentation.
The subsequent PID 10668 user run revealed a separate 35–70 ms `V3:437`/`V3:445`
same-box alternation, rather than a mid-run reset. Immediate-frame alias
reconciliation is `OFFLINE_VERIFIED` (87 related tests) and live-open; it does
not resolve the long-gap ReID requirement or establish semantic NPC identity.
The next PID 16548 run did not exercise that bridge (`exact_box_rebindings=0`):
three subject boxes passed the positional own-avatar anchor gate and four rapid
side-NPC ID switches occurred outside native BoT-SORT. A one-anchor-only
selection is now `OFFLINE_VERIFIED` (88 related tests), but still live-open.
The longer PID 10348 run showed this cardinality fix alone was insufficient:
249 of 254 rapid same-box subject ID switches involved anchor selection. A
lower-box/temporal-continuity anchor refinement is `OFFLINE_VERIFIED` (89
related tests; geometric replay 369→30 large anchor jumps) and remains
live-open. Downstream object rebinds and long-gap ReID are still `PARTIAL`.
The following PID 1296 pre-boar user run showed ~27.3 feed FPS and only two
rapid same-box feed-ID switches, both from the own-avatar anchor crossing a
one-pixel bottom gate. A narrow continuation gate is `OFFLINE_VERIFIED` by a
geometry replay and related tests, not live-validated. The same upstream V3
ID still acquired multiple displayed WORLD3D IDs; a canonical detector-kind
flip between obstacle and semantic subject caused at least part of the stable
layer split. V3-backed semantic-subject family normalization is
`OFFLINE_VERIFIED` by regression, while concurrent duplicates and long-gap
named-NPC ReID remain `PARTIAL` / live-open.
The following long PID 20864 run provided 34,576 feed frames at ~27.8 Hz and
stable V3 IDs for several minutes, but final diagnostics still showed 908 raw
upstream rebindings. A V3-backed semantic subject's obstacle/subject detector
label flip split source-local tracks despite stable upstream identity. Narrow
raw-family normalization is `OFFLINE_VERIFIED` (137 related tests passed, one
skipped); its effect on the live rebind count and long-offscreen ReID remain
`PARTIAL` / live-open pending a restarted user-run GUI.
The 14:21 PID 20864 run reduced raw rebindings from 26.26 to 1.48 per 1,000
detector frames (~94% lower across different user scenes), supporting the
family-continuity correction. A simultaneous V3:830/V3:923 alias conflict still
transferred a displayed ID. Earliest remembered visible upstream reservation
and existing-live-raw-owner priority are `OFFLINE_VERIFIED` (138 tests passed,
one skipped), with new live validation pending. Own-avatar feed handoffs and
long-offscreen semantic NPC continuity remain `PARTIAL` / live-open.

## Source hashes

- wow_agent_FINAL_M0_M1_master_prompt_v4.txt: `2a3134bcf89e1066a1e6157ea19a9029660b0dd0acf7589ee2cfeb08a65332c9`
- wow_agent_complete_functional_design_spec.txt: `537f19aed3027176f7b7ef46033607fd39d838ab6a15d5d27fa4c345e12b29bc`
- wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt: `ce4f475c05beb66260415fd60e757427ef2b81a4836d9bf74bde428d8cbfa2fc`
