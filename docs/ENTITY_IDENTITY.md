# Entity identity at skill boundaries

Status: implemented / offline-tested, **not live-validated** after this change.
Addon package: **0.9.65**, Interface **120100**; both addon directories match.

## One rule, distinct kinds of evidence

`runtime/entity_identity.py` compares public GUID / numeric ID constraints.
`runtime/skill_identity.py` applies that rule to entity-directed commands.
The pin is stored in the existing `ActiveSkillState.skill_context`; there is
no second executor, planner, running-skill store or persistent identity brain.

- GUID identifies a physical instance for the lifetime of an attempt.
- `npc_id` / `object_id` identify a template, not an individual spawn.
- `track_id` identifies a visual box. It can choose a pointer/steering candidate,
  but cannot authorize selection, casting, interaction or success.
- Names, appearance, tooltip text, TDB coordinates and quest symbols remain
  useful search hints. They never override missing or contradictory known IDs.
- A full public Retail GUID may prove its embedded template entry. Opaque
  compatibility GUIDs are not parsed heuristically. Visual/template reference
  strings cannot be turned into GUIDs. GUID string normalization itself is
  not proof of provenance: the selected-PID addon/evidence path remains required.
- Every supplied numeric/GUID constraint must agree. A matching GUID does not
  repair an explicitly malformed or conflicting ID, including after repeated
  identity normalization.
- A template-only object pin can acquire a public GUID when a matching hover
  later supplies it. After that upgrade, a different GUID cannot replace it,
  even if the object ID and appearance still match.

## Skill surfaces

| Surface | Identity required before entity-directed input |
| --- | --- |
| TARGET | Known public identity, current verified mouseover/cursor; success requires the selected GUID. No name-only or TAB acquisition. |
| INTERACT / TALK | Pinned unit GUID and any known NPC ID; F7 additionally checks the current soft-interact recipient. |
| COMBAT / DEFEND / target-required item, spell and extra action | Same selected GUID plus all supplied template constraints on each input-producing retry/resume. |
| LOOT | Pinned corpse GUID; pointer click must prove that corpse, not merely a different selected corpse. Existing loot eligibility and loot-result verification still apply. |
| OBJECT_USE / GATHER / HERB / MINE | Current public object identity under the cursor or an explicitly verified soft recipient. A GameObject need not be a selected unit. |
| Targeted VEHICLE / VEHICLE_ABILITY | Same shared selected-recipient gate. Targetless configured vehicle actions do not invent a recipient. The standalone VehicleSkill is not newly wired into production by this change. |
| VISUAL_APPROACH / selected-entity navigation / facing | Keep the committed identity through fast command refreshes and intermediate waypoints. Missing, changed or stale identity stops entity-directed motion. IDENTIFY remains bounded search, not confirmed interaction. |
| QUEST_DIALOG / FIELD_TURN_IN / vendor UI | Existing exact quest/action/option/item/slot contract; an available public UI-owner GUID is additionally pinned. Remote field turn-in can legitimately have no NPC owner. |
| Coordinate MOVE / search / inspection / self-only actions | Their own existing spatial/UI/binding contracts; no unrelated unit GUID requirement. |

The shared gate is applied at canonical skill begin/verify/resume boundaries
and the legacy command route. Visual steering and NavigationService also
check before renewing movement, including when the visual frame is unchanged.
Input dispatch and terminal finalization remain in the canonical runtime.
Completion evidence such as quest credit may still finish a no-input verifier
after a target despawns or a script changes its GUID; no rebinding/input is
authorized by that exception.

## Thick Cocoon and other GUID-less objects

A synthetic Thick Cocoon test demonstrates:

1. The addon reports a real `mouseover.object_id`, with no GUID.
2. HOVER acquires a fresh, co-sampled cursor and matching object ID.
3. A verified right-click, or verified same-recipient F7 fallback, is allowed.
4. Actual quest objective credit verifies success; the click alone does not.

This does **not** manufacture a GUID or a stable physical-instance identity
for two cocoons sharing one template. If both GUID and public object ID are
absent, the name/box remains search evidence and actionable identity is unknown.
The old name-only click and blind F7-at-a-TDB-spawn branch are deliberately
unavailable. Recorded old name-only Cocoon samples have not been relabelled as
ID-bearing live evidence. Real Retail Cocoon ID availability still needs a
user-operated test; an inaccessible/secret value is never bypassed.

## Telemetry and freshness

Primary and versioned-mirror addon packages preserve `object_id` through
target, mouseover, soft-interact and bounded FAST projections. `item_id` remains
typed item identity, not a guessed NPC/object ID. Public GameObject soft GUIDs
can be read when `UnitExists` is false, but only through the normal guarded
API path. Quest UI exports its public owner GUID when available.

Python promotes only typed tooltip IDs. Historical MOUSEOVER_CHANGED text
cannot refresh an old object ID into current cursor proof. Identity/cursor
sample times belong to their original STATE/FAST packet; omitted fields do
not acquire a new clock. An explicit unknown per-field time remains unknown,
even when the packet has a current monotonic time. A bounded FAST packet
omitting soft targets clears the recipient hint and marks its time unknown, rather than making old F7
recipient evidence look current. Packet enrichment retains credit/error
fields when adding a soft-target list fits the configured byte limit.

Mouseover-to-cursor checks retain freshness, co-sampling and verified-point
bounds. The previous fresh-current-cursor fast TARGET path is retained: no
new mandatory hover roundtrip or minimum delay was added.

**No hover world X/Y/Z navigation was introduced.** The user corrected that
Retail 12.1 does not provide these hover coordinates. Existing legitimate
coordinate sources retain their own measurement time; missing Z is not
invented from the player's floor.

## Deployment and validation

The project files changed; the installed WoW addon was not overwritten and
no live GUI/FULL_AI/client input was started by the assistant. Install the
updated addon package, `/reload` the game UI, then restart the agent GUI.
The user operates the live test. Check exported addon version 0.9.65, actual
GO ID availability, same-GUID/new-box behavior, wrong-instance rejection,
moving-target click timing, F7 recipient, quest credit, loot and safe STOP.

Offline results and the separately open pre-existing short-probe route test
are recorded in `LIVE_VALIDATION.md`; synthetic replay is not live acceptance.
Final related regression: **1679 passed, 2 skipped, 1 explicitly deselected**
across 171 test modules. Report inspected 2026-10-18; no live run is inferred.
