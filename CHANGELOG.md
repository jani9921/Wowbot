# Changelog

## 2026-10-28 — classic escort (playbook E2) from server facts: Black Wagon Flight (live 12:05–13:04)

- Run 11:59–13:04 (user away). 66780 and 66779 were completed and turned in
  (Left and Right by the server NPC). 65793 Black Wagon Flight was accepted at
  12:04:07, and "Let's get moving." was selected at Sabellian at 12:05:11.
- Dump: at 12:05:11 the server removed the static wagon 191020 and Sabellian
  190937. It summoned our own Inconspicuous Wagon 190935, Sabellian 191640,
  Wrathion 191737 and two Expedition Shires, all `created_by` us, at
  (1835, 1158).
  - The only plan was the quest's map POI MOVE (`LOCATE_QUEST_OBJECTIVE_REGION`,
    priority 40+16). That POI is the escort's destination, 535 yd south; it
    was flown (Skyriding) in 15 s.
  - The group left our view at 12:05:23. After arrival (12:05:37) the planner
    had no candidate ("Több adat szükséges…", WAIT priority 0), with RECOVER
    every 2 min, for 59 minutes.
  - The old `EscortFollowPolicy` (2026-09) only looks at the addon target and
    the vision entity list; in server mode its SEEK_VISUAL_CUE is
    unavailable.
- New `agent/escort_planning.EscortPolicy` (wired in `QuestPlanner._propose`):
  - Open objectives with mechanism ESCORT and TDB `escort_creatures`. These
    are templates named by the objective's subject ("Escort the wagon" →
    "wagon"), nearest the credit entry. Subject = a server unit of those
    entries created/summoned by us.
  - Beyond 12 yd: MOVE `ESCORT_FOLLOW` to it (its spline end when within
    25 yd), stop 6 yd, priority 101.
  - Within 12 yd: WAIT_EVENT `objective_kind: ESCORT`, priority 101.
    `DefendWaitSkill` cancels it (replan) as soon as the subject is 12+ yd
    away or out of view, and re-checks every 8 s. No timeout failure, and no
    passive-WAIT budget that would hand the turn to another quest.
  - Out of view: MOVE `ESCORT_RETURN` to where we last saw it (in-process
    memory, 30 min). If it is not there either (within 15 yd), the memory is
    dropped.
  - Combat stays with the combat policies (the escort proposes nothing in
    combat).
- `TDBKnowledgeProvider.escort_creatures` / objective `escort_creatures`.
- Planner-level check on the 13:04 state with the wagon injected 30 yd away:
  the only candidate is the escort MOVE (105). Without the wagon it is still
  the old WAIT.
- Tests: `test_escort_wagon_20261028.py` (6). Full suite: 14 failed, all
  from the known baseline list. Offline only.

## 2026-10-28 — a POI walk yields to the server's objective NPC; a lower-floor route fails sooner (live 10:53–10:55)

- Run 10:53:41–10:54:53 (Claimant to the Throne 66780, "Speak with Left and
  Right", Obsidian Citadel), user: "oda vissza szaladgál csak":
  - The only plan was a TDB-POI walk (`LOCATE_QUEST_OBJECTIVE_REGION`,
    priority 96+12+4 = 112), chosen 1.7 s before the server sent Left
    (191710) and Right (191711) 12 yd away on the same floor (z 387.6, gossip
    flag). The reference knowledge already had both entries in
    `talk_creatures`; the walk was simply never replanned.
  - Its mmap route had been planned on a floor 10 yd below the observed own
    height (waypoint 2 at z 377.6). The player stood 1.8 yd flat from it, the
    controller measured 8.5 yd with the layer excess and turned left/right
    for 70 s. `route_on_observed_other_layer` needed more than 12 yd.
- Fixes:
  - `server_npc_planning.objective_npc_available` plus a movement interrupt
    `SERVER_OBJECTIVE_NPC_AVAILABLE` (fast lane and medium tick, CANCELLED).
    A POI search of a quest yields as soon as a talkable objective NPC of
    that quest is within 80 yd. Only NPCs created after the walk started
    count, so an NPC that was just talked to cannot cancel every later
    search. The replanned server NPC MOVE ranks 102+12+4 = 118. Cost 0.2 ms
    per tick.
  - `NavigationService.OBSERVED_LAYER_YARDS` 12 → 7: a route waypoint 7+ yd
    from the server-observed own height within 6 yd flat fails after 2 s, and
    the next plan starts from the observed floor. A 5 yd step/slope stays.
- Why the route started on the lower floor (follow-up):
  - The runtime process restarted at 10:53:01. The forwarder replays only
    entity facts to a new context; own movement is deliberately never
    restamped (`test_old_movement_and_quest_credit_are_dropped_not_restamped_or_replayed`).
    So, standing still, our height stayed unknown until the first own
    movement packet.
  - The plan (1150645.1) came while the snapshot was still replaying
    (9 → 73 → 96 entities, 64 per 0.5 s). The route was planned from a
    guessed floor.
  - `_height_probe` skipped the jump because we were mounted. The walk's
    own first TURNLEFT 0.12 s brought z 387.6 with the next sample, x/y
    unchanged.
- Fixes (follow-up):
  - The height probe is a 0.06 s turn tap toward the heading (mounted too),
    not a jump.
  - A route planned without an observed own height
    (`_route_own_z_unobserved`) fails at the first contradicting server
    height, without the 2 s wait. The flag clears once a fresh server
    height agrees with the waypoint floor.
  - `SnapshotReplayForwarder`/`EntitySnapshot.replay` also replay the
    "unit" slot. The 2026-10-27 UnitData round stored it, but never re-sent
    it.
- The "11 ms per `movement_visual_interrupt` call" was a measurement
  artefact: the first call imports `scene_path_planning` once (~220 ms),
  warm calls take ≤0.2 ms. Live, the planner imports it before any MOVE.
- Tests: `test_server_objective_npc_interrupt_20261028.py` (5),
  `test_bridge_landing_20261027.py` (probe test updated). Full suite: 14
  failed, all from the known baseline list (one of them now passes).
  Offline only.

## 2026-10-27 — creature UnitData from packets; the bridge arbalest from below (live 16:59–17:07)

- WPP list item 1 (user-agreed order), creature UnitData:
  - `update_object._unit_tail` (create) and `_values_unit` (value update,
    change-mask bits 6–55) read, per WPP UpdateFieldsHandler1215 /
    V12_1_5_70340:
    - health, max health, level, faction template;
    - unit flags 1–3;
    - bounding radius, combat reach;
    - the unit's target;
    - SummonedBy / CreatedBy.
  - Implausible values reject only the unit part.
  - Captures: 896/896, 634/634 and 1468/1468 unit creates decoded. The 16:35
    capture gave 3417 health and 2654 target updates; a Qalashi fell
    120033 → 119783 while targeting us.
  - New event `ENTITY_UNIT_UPDATE`; the `ENTITY_CREATED` allowlist is
    extended; the snapshot slot is "unit".
  - The reducer keeps `entity["unit"]`. Other players' GUIDs never enter:
    a target or creator becomes `targets_me` / `summoned_by_me` /
    `created_by_me` or a creature `target_entity`.
- Uses:
  - `attackers(state)`: live, attackable creatures targeting us, nearest
    in 3D. The DEFEND Tab pin uses it. Live 16:39:39 and 17:03:00: the pin
    was any nearest unit and DEFEND failed OUT_OF_RANGE 3×.
  - `kill_objective_units` skips dead (health 0) and NON_ATTACKABLE /
    IMMUNE_TO_PC / NOT_SELECTABLE units.
  - The kill hunt halves the cost of a mob already targeting us.
- East Siege Arbalest (z 245.6 on a bridge), run 16:59:
  - A region flight without a target height came in at z 212, below the
    deck. Combat (17:02:59) landed it on the ground under the bridge
    (z 200), and the on-foot route to the arbalest ended under it (no path
    up).
  - The walk "arrived", facing failed and the agent waited from 17:04
    (user: "megint alászállt").
  - Fixes:
    - The navmesh-surface projection keeps the server-measured height
      (`observed_z`). The other-level arrival checks
      (`destination_distance.observed_height`, `_level_distance`) use it;
      the projection had dropped `z_observed`.
    - TravelMode flies to a known target more than 12 yd above our server
      height (`CLIMB_FLIGHT_YARDS`), however close it is flat; 44 yd was
      under the 60/250 yd flight minimum.
  - User question "miért a szélén akar leszállni?": the navmesh shows the
    deck open 8/8 around the arbalest at 3 and 5 yd. The touchdown under it
    came from the height-less region flight plus the combat landing, not an
    edge landing point.
- Tests: `test_unit_fields_20261027.py`, `test_bridge_landing_20261027.py`
  (+1), `test_travel_mode_20261020.py` (+1). Offline only.

## 2026-10-27 — landing under the bridge; height probe at a standing start (live 16:34–16:46)

- Run 16:34 (live):
  - `route_on_observed_other_layer` stopped the courtyard route at 16:39:35;
    the arbalest MOVE followed and the South Siege Arbalest F7 was pressed at
    16:40:24 ("South Siege Arbalest destroyed" 1/1).
- East Siege Arbalest (376901, z 245.6 on a bridge):
  - The flight touched down under the bridge (z 200) 1.6 yd from it flat.
    The MOVE counted as arrived, the facing turn toward a point straight
    above failed (`facing_failed`), WAIT followed, and it flew up and landed
    under it again.
  - User: "mindig az arbalest alá száll, és WAIT-el".
  - Fixes:
    - `destination_distance.arrived`/`other_level`: a known destination
      height more than 12 yd from our server height is never arrival.
    - `_facing_after_arrival` fails `arrived_on_other_level` instead of
      turning.
    - `FlightPlan.target_z`: within descent + lookahead of the landing, the
      cruise is at least landing z + clearance. The 16:41 approach came in at
      ~216 over the gorge under a 247 deck.
- Height probe: `ReachMovementController._height_probe` jumps once in place
  when the packet lane is live and our server height is unknown (at most
  once per 30 s; not mounted, flying, in a vehicle or in combat).
  - Live 16:39:18–16:39:28: the agent started with the character standing,
    no own movement packet and no height, until the user jumped.
- Tests: `test_bridge_landing_20261027.py`. Offline only.

## 2026-10-27 — one target cost across objectives; own server height kept (user-agreed)

User: "valami elsőbbséget fel kéne vegyen, hogy ami közelebb van, vagy egy
z-n van vele ... wrathion vitt fel a híd tetejére ahol van az arbalest". All
five agreed points, plus "nem mindenhol vesszük a Z-t a szervertől?".

- New `objective_choice.py`: the ranker adds one bounded adjustment to every
  objective-pursuit proposal (objective MOVE purposes, OBJECT_USE / TARGET /
  INTERACT / USE_ON_TARGET / ASSIST with a quest). It is visible as
  `candidate_utilities[].objective`.
  1. Route cost: flat yards + 3 × (height difference − 4) with our own
     server height, −1 per 15 yd, at most −8.
  2. Placed here: +6 for targets within 80 yd and 10 yd of height of the
     landing point, for 2 min. `ObjectiveContext` sees taxi/vehicle exit,
     scene end, map transfer and a > 40 yd jump.
  3. Counted kills: −3 for an unfinished "N/M slain" objective (M ≥ 3)
     whose target is farther than 25 yd.
  4. Fresh quest: +1.5 for 2 min after accept.
  5. `AutonomousLoop.choose(..., scores=)` releases a commitment
     (`BETTER_OBJECTIVE`) when the top proposal serves another objective
     and scores ≥ 6 more than anything matching the commitment.
     - Not in combat, not within 3 s of committing, and not away from a
       selected committed unit.
- `ServerKillTargetPolicy`: our own server height (z_observed) beats the
  resolved layer for target choice. In the 16:10:41 state it now picks a
  wall-level Qalashi (z 261.7) instead of the courtyard one.
  - With the adjustment, the arbalest MOVE scores 102.6 against the kill
    MOVE's 95.6.
- Own server height:
  - `SMSG_NEW_WORLD` x,y,z become the last own position until we move;
  - the standing-still hold is 1.5 yd (was 0.75 yd: 11 of 52 wall samples
    lost the height);
  - a layer-probe route stops at the first contradicting server height.
- Tests: `test_objective_choice_20261027.py`,
  `test_server_positions_20261020.py` (+1),
  `test_observed_layer_route_20261027.py` (+1). Offline only.

## 2026-10-27 — wall-top route on the courtyard floor; server cosmetic map for geometry (live 16:07–16:11)

- Run 16:07 confirmed live that the cosmetic-map entity fix works: from 16:10:32
  96 server entities were visible, including the South Siege Arbalist (376253,
  objective 423829, 0xc204, wall level z 256).
- New `NavigationService._route_on_observed_other_layer`:
  - It fails a MOVE (`route_on_observed_other_layer`) when the own height
    from packets (`z_observed` / own movement packets, at most 2 s old) is
    more than 12 yd from the current route waypoint's layer, within 6 yd
    horizontally, for 2 s. Falls and flights are excluded.
  - Live: the MOVE to a Qalashi started at 16:10:27 while the own height was
    unknown, and was planned on the courtyard floor (z 216). Wrathion had
    left the player on the wall top (packets: z 260).
  - It ran back and forth around intermediate waypoint 1 for 40 s. The
    final-waypoint layer check never ran, and the arbalest (known from
    16:10:32) could not win.
- Server cosmetic map for world geometry:
  - The reducer projects `packet_server_map`: from `SMSG_NEW_WORLD`
    (`MAP_CHANGED`, live 15:45:40 → 2534) or from the GUID maps of the
    recent creates around us.
  - `NavigationSearch.observe_topology` passes it to
    `WorldGeometryService.set_server_map`. `map_for` answers maps/vmaps/mmaps
    queries from map 2534 wherever it has its own mmtile (16 tiles in
    mmaps.zip), and from 2444 elsewhere.
  - The route in this run's spot is identical on both maps, so this fixes no
    observed failure; it keeps geometry consistent where the narrative map
    differs.
- Tests: `test_observed_layer_route_20261027.py`,
  `test_cosmetic_map_entities_20261027.py` (+2). Offline only.
- Open: target choice prefers a flat-distance Qalashi 45 yd below over the
  same-level linked objective. Discussed with the user as one shared target
  cost: route cost, placed-here bonus, one-shot before counted kills,
  mid-MOVE switch.

## 2026-10-27 — cosmetic narrative maps keep server entities; no speculative speech hold (live 15:43–15:56)

- `world_packet_reducer.same_world_map`: an entity GUID's map is accepted
  when it equals the player's instance or shares its cosmetic root (client
  DB2 Map `CosmeticParentMapID`, cached).
  - Live: after the scene into the Obsidian Citadel (15:45:33) every unit and
    object came on map 2534 "Black Dragon Citadel - Narrative Version"
    (cosmetic parent 2444). The addon kept 2444, and all were dropped as
    another map's spawns.
  - The entity table froze at 10 old units. In both runs the agent saw no
    Qalashi and no Siege Arbalest; it fought only attackers and searched the
    map.
  - Replaying the 15:51 capture now keeps 32 live Qalashi and the South Siege
    Arbalist (376253, objective 423829, Activate).
- `ObjectiveSpeechHold` waits only after the NPC actually speaks after the
  talk; the speculative first-line wait is gone.
  - Live 15:45:07 and 15:52:32: Wrathion said nothing. Each hold lasted 15 s
    (WAIT_EVENT minimum).
  - The second blocked his reopened gossip row for 7 s.
- Tests: `test_cosmetic_map_entities_20261027.py` (a real 2534 create),
  `test_objective_speech_hold_20261026.py` (silent NPC). Offline only.

## 2026-10-26 night — quest mechanisms read ahead: census, objective field, playbooks

User: prepare for quest kinds ahead ("followeres quest, akkor az így meg úgy
néz ki"), so that live runs only need small fixes, not mechanic rewrites.

- New `src/wowbot/quests/objective_mechanics.py`: one pure `classify(facts)`
  names an objective's mechanism. Two fact sources share one interface:
  - `TdbQueryFacts` (runtime, per-entry SQL with caches);
  - `TdbIndexFacts` + `Db2IndexFacts` (census, preloaded; the client index
    takes 0.16 s and the runtime uses it too).
- Structural facts:
  - KillCredit sources, TDB spawns, spellclick and vehicle, gossip actors,
    conversation actors;
  - DB2 KILL_CREDIT spells and the spells that trigger them (2 hops), with
    their casters (game object Data0/Data10, spellclick spell, creature
    spell);
  - quest items; quest-item and loot-table item sources.
- When no source is found, the objective's verb decides (`FROM_TEXT`): TALK,
  ARRIVE, WITNESS, ESCORT, EMOTE, USE_ITEM, INTERACT, KILL. A named creature
  without TDB spawns counts as KILL (`NO_TDB_SPAWN`).
- `TDBKnowledgeProvider` sets `objective['mechanism']` and
  `['mechanism_tags']` (knowledge only; live state still decides).
  - 66048 → TALK ×3 + CREDIT_OBJECT; 66078 → GOSSIP_ACTOR; 70061 →
    SPELLCLICK_VEHICLE; 66116 → MOUNT + TALK.
- `COVERAGE`: per mechanism the handler, status (LIVE/PARTIAL/NONE) and live
  evidence.
- New `tools/quest_mechanics_census.py` (2.5 s, read-only) writes:
  - `docs/QUEST_MECHANICS.md`: per-expansion counts (DF/TWW/Midnight),
    coverage, backlog, examples;
  - `output/quest_mechanics.json`.
  - Of 61 511 objectives, the unresolved share of recent expansions fell from
    4059 to 150. The rest is script-driven (`SPELL_CREDIT`, `PROXY_UNKNOWN`,
    `CRITERIA_TREE`, hidden collect rows).
- New `docs/QUEST_PLAYBOOKS.md`: recognition (static + live), step order,
  done signal, pitfalls and today's status per mechanism.
  - Escort splits into three: a companion following us, classic escort, and
    defending a place.
  - Build order: E2 escort, USE_ITEM via DB2 ItemEffect, ARRIVE, WITNESS.
- Tests: `test_objective_mechanics_20261026.py` (classifier, text hints, the
  query and index sources agree on one fixture, census end-to-end).

## 2026-10-26 night — sparring partners (Sharp Practice) and the speech hold behind an open window (live 23:01–23:11)

- Speech hold fix: while a dialog is open, the planner returns early with the
  dialog policy only. `ObjectiveSpeechHold` never saw Edress's window, so it
  never waited (live 23:06:34; the user held the character).
  - The open-dialog branch now calls `ObjectiveSpeechHold.observe`.
  - The talk partner also comes from the server: an unfinished objective's
    NPC within 6 yd (`credit_name` / `named_creatures`). F7 talked through
    soft-interact.
  - Planner-level test: `test_the_planner_records_the_talk_while_the_window_owns_the_input`
    (fails without the fix).
- Sharp Practice (66078), "0/8 Blacktalon tested", credit 187158 via
  KillCredit of Blacktalon Avenger/Assassin 187187/187189:
  - They stand around friendly with npc_flags 1 ("I'm here to test your combat
    skills."). The kill hunt skipped them as service NPCs, the talk policy
    skipped kill credits, and the agent waited 1.5 yd from one (23:09–23:11).
  - In run 17:41 Tab on them failed `target_not_found` five times.
- New `packet_entity_facts.sparring_entries`: kill-objective creatures the
  server shows with the gossip flag. The flow is walk → F7 → gossip option →
  fight.
  - `ServerNpcInteractionPolicy` talks to them.
  - The dialog picks the option for the credited quest (SCRIPTED_COMBAT
    transition), without the 45 s wave hold.
- After the option, the selected target that the addon reports attackable is
  a kill target even with its gossip flag (`kill_objective_units`). It is no
  longer a talk partner.
  - User: "megtámad vagy én támadom meg". If it attacks, combat/DEFEND owns
    it; otherwise the hunt attacks.
- Tests: `test_sparring_gossip_20261026.py`,
  `test_objective_speech_hold_20261026.py`. Offline only.

## 2026-10-26 night — NO_INTERACT closes an activated quest object (battle plans, live 22:46:42)

- New `packet_entity_facts.go_flags_usable`: a game object is usable when
  Activate (0x4) is set **and** NO_INTERACT (0x80) is clear.
  - Live: after the quest was re-accepted, the battle plans went 0xc204 →
    0xc284 and stayed so until Fao's gossip (user: the table is not active
    before the talk).
  - The agent walked to them and pressed F7 → OUT_OF_RANGE, more than once.
- The check is used by:
  - `server_object_interactable` (OBJECT_USE identity and usability);
  - `linked_object_entries` (planning);
  - `objective_objects` ("usable");
  - the approach abort in `object_interaction_flow`.
- Replaying run 22:42: the agent now talks to Fao instead of pressing F7 on
  the closed table.
- Test: `test_linked_quest_object_20261026.py`. Offline only.

## 2026-10-26 night — the objective NPC's speech is waited out (Edress, live 21:52:58)

- New `ObjectiveSpeechHold` (`objective_speech_planning.py`, wired next to
  `ScriptedRideHold`): it proposes WAIT_EVENT at priority 121 while an NPC we
  just talked to keeps speaking.
  - Live: after the gossip, Archivist Edress spoke four lines over ~37 s
    (CHAT_MSG_MONSTER_SAY → NPC_INSTRUCTION), walking while she talked.
  - "Archivist Edress consulted" came after her last line. Meanwhile the
    agent followed her, hunted a 66078 mob, got stuck and left.
- User: wait only if the talk gives quest credit. The hold needs all of:
  - the speaker named in an unfinished objective's text;
  - our own talk with that unit (quest/gossip window open; one talk = windows
    within 10 s);
  - a line received from ≤3 s before the talk or later.
  - Greetings while walking up (Kavia, 5 s before) start nothing.
- The hold ends on:
  - the credit;
  - a usable credit object of the quest (the scope after Kavia's line);
  - 8 s without a first line, or 20 s of silence;
  - combat, or 90 s.
- Line time = receipt time. The event's own epoch stamp ran ~4 s behind the
  state clock live.
- Replaying run 21:50: one continuous hold 130.6 s → credit at 164.4 s.
- Test: `test_objective_speech_hold_20261026.py`. Offline only.

## 2026-10-26 night — an objective's credit-spell object (Scouting Scope, live 21:54)

- `ClientCatalog.kill_credit_spells`: DB2 spells with KILL_CREDIT (90/134)
  for a creature entry (`spell_effects.misc1`).
- `TDBKnowledgeProvider.credit_objects`: for kind-0 objectives, game-object
  templates whose use spell is one of those spells become
  `objective['credit_objects']`. The spell is SPELLCASTER (22) Data0 or
  GOOBER (10) Data10.
  - Talonstalker Kavia consulted (189507): Scouting Scope 376824, spell
    309772, KILL_CREDIT 189507.
- `packet_entity_facts.credit_object_entries`: such a server GO, for an
  unfinished objective, once the server drops GO_NO_INTERACT (0x80).
  - Live: 0x8080 until Kavia's gossip, 0x8000 at 21:54:17.
  - User: the object becomes active only after the talk.
  - `server_object_interactable` accepts it with basis
    `OBJECTIVE_CREDIT_SPELL`.
- `linked_object_entries` includes these, so the existing step-up → F7 path
  (2 yd, facing, no other soft-interact unit) uses the scope instead of
  re-talking to Kavia.
  - Live: talk → `wrong_quest_ui` → zone sweep → back → talk → WAIT.
- Fao's battle plans need no such link: the server sent `quest_objective_id`.
  Their spell 372265 → 372271 is a dummy; Fao's credit 186331 is spell
  372292, cast by the server script.
- Test: `test_credit_spell_object_20261026.py`. Offline only.

## 2026-10-26 night — the linked quest object goes before a nearer NPC (live 21:46)

- `ServerNpcInteractionPolicy.propose`: server-linked usable objects of an
  open objective are tried before the other candidates.
  - Live: Fao stood 1.9 yd away and the battle plans 8.2 yd.
    Nearest-first re-talked to Fao every ~10 s, while the table was usable
    from 21:46:06, before any talk.
  - Replaying the recorded states: the policy now walks to the table, and
    the full agent proposes it once no dialog window is open.
- Test: `test_linked_quest_object_20261026.py`. Offline only.

## 2026-10-26 night — objective-linked quest objects (Best Plans and Intentions, live 21:35)

- `server_npc_planning.linked_object_entries`: a game object linked to an
  open quest's objective (`quest_objective_id`) and marked Activate is
  handled like any other quest object, whatever the objective's credit kind.
  - Live: after Fao's gossip ("review the battle plans") the battle plans
    table (377106/377111, GOOBER, linked to 427169 "Fao the Relentless
    consulted") stood 3.7 yd away, usable.
  - The agent re-talked to Fao in a loop (gossip → no credit → close →
    again).
- `ServerNpcInteractionPolicy.propose`: for such an object it steps up
  (stop 1.2 yd, facing it). F7 (`OBJECT_USE` INTERACT_KEY_PACKET) goes only
  within 2 yd, facing it, with no other unit as the client's interact
  recipient. It never falls through to the next NPC.
- `objective_objects` counts the server's link to any objective of the
  quest.
- Test: `test_linked_quest_object_20261026.py`.
- Checked on the recorded 21:36 state: walk to the table, then F7. Offline
  only.

## 2026-10-26 night — wrong-level arrival after a flight; open landing spot on the layer

- `ReachMovementController._observe_flight`: a flight verdict ARRIVED more
  than 12 yd off a known destination height ends the MOVE as
  `arrived_on_other_level`, so the next plan starts from where the agent
  stands. Live 18:05:15: Skyriding to z 188 "arrived" at z 259. The
  17:30 level check had covered the ground branch only.
- `flight_route.landing_candidates`: with a known height, open spots on the
  destination's layer (±6 yd) up to 40 yd out follow the 12 yd ones.
  - Live 17:22–17:34: the turn-in point at z 95 lay under a platform at
    z 183–188. Every landing within 12 yd was covered, so no flight was
    planned.
  - On the real mmaps the plan now lands at (1088.6, 386.2, 94.3), and a
    navmesh walk of 25.9 to the point exists.
- Tests:
  - `test_other_level_arrival_20261026.py`;
  - `test_flight_plan_20261025.py`.
- Offline only.

## 2026-10-26 late — arrival on the wrong level (Proto-Fight turn-in, live 17:22–17:23)

- `ReachMovementController._level_distance`: a destination with a known
  height more than 12 yd above or below is not arrival. Live: the TDB
  turn-in point was at z 95 and the agent landed on a ledge at z 185.6
  straight above it; the flat test "arrived" ~20 times in a row while it
  stood there.
- `TravelModePolicy._skyriding_travel`: the distance to a destination with
  a known height is 3D. The 90 yd drop counted as 0 yd before, so it was
  never flown.
- Tests:
  - `test_other_level_arrival_20261026.py`;
  - `test_travel_mode_20261020.py`.
- Offline only.

## 2026-10-26 late — Proto-Fight run 17:03–17:06: Tab under the drake

- `tab_target_check(..., max_yards=)`. `ServerKillTargetPolicy` checks a
  flying quest mob (> 8 yd above) in 3D with a 35 yd reach and no floor
  rule.
  - Live: under the drake the ground check said OTHER_FLOOR on every
    sample, so no Tab came.
  - On the recorded samples < 15 yd under a drake the new check is READY in
    35 of 54.
- A selected flying quest mob is left to COMBAT, which opens with F7. Before,
  the agent walked toward its point in the air.
- Observed: DISMOUNT pressed CTRL-Q (MULTIACTIONBAR1BUTTON1, the mount, usable)
  at 17:04:52 during an 8 s telemetry stall (17:04:51.5–17:05:00). It did not
  dismount; the cause is unknown, so retest it.
- Offline only.

## 2026-10-26 late — Proto-Fight: Tab, F7 (harpoon), then the fight

- `packet_entity_facts.use_on_target_opener` + `CombatSkill._next_action`:
  a COMBAT on a credit creature of a quest that carries a quest-log item and
  a "Use …" objective opens with Interact (F7), then runs the rotation.
  - Live 16:54:49: the first press was Charge at a drake in the air
    ("No path available").
  - Live 14:28:03: an F7 had fired the harpoon and brought the drake down.
  - User: "odamegy, tab, F7, utána megtámadja és megöli".
- `ServerKillTargetPolicy`: the "flying" threshold is now 8 yd (was 25).
  Drakes ~20 yd above the ground still failed the walk to their point.
- Exile's Reach item-use quests (Re-sizing the Situation, no combat) are
  unaffected; their tests pass.
- Test: `test_use_on_target_opener_20261026.py`. Offline only.

## 2026-10-26 late — useless NPC windows are closed (4 s)

- `Planner._close_unhelpful_dialog`: an NPC window with gossip or quest
  rows the dialog logic takes nothing from is closed (`CLOSE_DIALOG`, i.e.
  Escape = Goodbye). It needs 4 s and a fresh full snapshot ("legyen 4s").
  A vendor window stays with the vendor flow, and a fully empty window keeps
  its existing 6 s rule.
- User 2026-10-26: such windows left the agent in WAIT.
- Test: `test_live_utility_vehicle_dialog_20261021.py`. Offline only.

## 2026-10-26 late — corpse run from a tower top; elite credit creatures

- `DeathRecoveryPolicy`: a flying ghost (`movement.flying`) more than 40 yd
  from its corpse flies straight (no navmesh). Live 16:39: on a tower top at
  z 336, 430 yd from the corpse, the navmesh corpse run failed
  `required_navmesh_route_unavailable` and the agent waited.
- `CombatPlanningPolicy`: an elite whose entry is a reference credit creature
  of an open kill objective (`kill_objective_entries`) is an explicit kill
  target. Proto-Fight's "Proto-dragons slain" names only the generic
  Proto-dragon, and the agent waited "Elit target: nincs igazolt …" at the
  Rumbling / Galestrike Proto-Dragons.
- Tests:
  - `test_ghost_flying_mount_20261021.py`;
  - `test_elite_defence_safety_20261022.py`: verified to fail without the
    fix.
- Offline only.

## 2026-10-26 evening — Proto-Fight (66122): flying kill targets

- `ServerKillTargetPolicy._move`: a quest mob more than 25 yd above the
  player is approached on the ground below, with no z (navmesh projection)
  and stop 10 yd (`airborne_target`). Live 14:28–14:39: walks to the
  proto-dragons' point in the air (z 217–241, ground 96–130) had no navmesh
  route, again and again.
- Observed: the harpoon (Ruby Spear) fired via COMBAT's F7 on a Rumbling
  Proto-Dragon (14:28:03 → credit 14:28:05 → kill 14:28:13).
- Unresolved:
  - DEFEND `FACING_FAILED` ×6 for 40 s, then death (14:31:19–14:31:58,
    attackers 187209/187203). Telemetry rotated; a freeze/root is
    suspected, not shown.
- Offline only.

## 2026-10-26 evening — mounted combat, mob hopping, scripted rides (live 11:00 and 14:02–15:14)

- `TravelModePolicy`:
  - attacked on a mount on the ground, it gets off first: DISMOUNT
    `COMBAT_DISMOUNT`, above the fight. Before, DEFEND failed
    OUT_OF_RANGE again and again and the agent stood still (live 14:14).
  - attacked in the air, it never dismounts there: a `COMBAT_LANDING` MOVE
    to the ground below, then the dismount.
  - no mount for a kill-target hop under 120 yd (`hunting_nearby`). Before,
    there was a 1.5 s mount cast before every 40–60 yd hop.
- `Supervisor.combat_admissible`: `COMBAT_DISMOUNT` and `COMBAT_LANDING` are
  allowed in combat.
- `ServerKillTargetPolicy`: the chosen mob stays chosen unless another is
  clearly nearer (×0.7 and 5 yd). Before, the nearest flipped between plans
  and the agent walked to and fro.
- `Planner`: Leave Vehicle only on a seat with a vehicle UI or vehicle bar.
  A scripted ride that completed its quest on boarding got 3× VEHICLEEXIT
  (live 11:00:48).
- On the Skyriding bar a mount on a multi-action-bar button keeps its key,
  and `mount_action` finds it (test). The user can put the mount there as
  the dismount key.
- Not changed: ghost mounting for corpse runs. The death path returns
  before travel mode, and a flying ghost mount was trouble on 2026-10-21.
  This needs telemetry from the next death.
- Tests in `test_travel_mode_20261020.py`, `test_server_vehicle_combat_20261025.py`
  and `test_vehicle_bar_20261004.py`. Offline only.

## 2026-10-26 evening — whelp: own Tab and the upside-down pitch

- `HoverControl`:
  - upside down (|pitch| > 90°), only Sit is pressed, until straight down;
    from there Jump turns forward. A key turns the pitch the shortest way to
    its own vertical, so the wrapped error had swung it at ~180° for
    minutes (live 13:41).
  - `tab_guid`: a `VEHICLE_ATTACK_APPROACH` ends `hover_tab_ready` as soon as
    its unit is Tab-ready with nothing selected. Before, ready moments passed
    during long approaches and the agent Tabbed 4× in 16 min.
- `MovementController` passes `server_entity_guid` as `tab_guid`.
- Tests: the pitch simulator models the live key behaviour, with
  upside-down starts; tab-ready arrival.
- Offline only.

## 2026-10-26 — flying vehicle selects a target but waits instead of aiming/shooting

- Keep hover pitch/height correction through proposal ranking, combat
  supervision and target commitments.
- Preserve the air destination and the target's Z through NavigationService;
  retain flight capability from the vehicle's packet evidence.
- Exclude empty slots and pure speed buffs from attack selection; report
  named attack cooldown waits and preserve area-ability use mode.
- Nine new regressions; related suite 210 passed, two documented legacy
  visual-aim failures excluded. Six recorded checkpoints replayed without
  input. Post-change live validation pending; see LIVE_VALIDATION.md.

## 2026-10-26 afternoon — whelp run 12:13–12:22: range, patrol paths, button choice

Pitch steering held live: |pitch| ≤ 1.41 rad. No press, for these reasons
(`docs/LIVE_VALIDATION.md`):

- `update_object.decode_monster_move` reads every spline point.
  `pkt.SMSG_ON_MONSTER_MOVE` names the last point as the destination, for
  multi-point paths too. A patrolling unit's return leg is no longer parked
  at its turn.
- `ServerVehicleCombatPolicy._engage`: a vehicle button's `in_range` False
  counts only after that button has said True in this vehicle; otherwise
  the server 3D distance decides. The whelp's bar said False always.
- `vehicle_abilities`:
  - harmful periodic auras count in `spell_shape` (Call of Life: CLOSE);
  - per target kind, `learn_effect` records `hit_entries` / `miss_entries`;
  - `choose_attack_action` puts a button cast 4× on that kind without
    credit last, and one that credited on it first.
- Tests updated and added. Offline only.

## 2026-10-26 noon — the pitch-steered whelp (live 11:27–11:36)

Evidence in `docs/LIVE_VALIDATION.md`: Jump/Sit swing the whelp's pitch to
±90° rather than climbing. Burning Bark flies along the pitch, so the
agent's casts at +77° missed.

- `HoverControl`:
  - `COUPLED` learns per vehicle entry whether Jump/Sit turn the packet
    pitch, from one 0.1 s probe press;
  - on such a seat the pitch is steered with measured taps toward the climb
    angle (≤ 1.2 rad, never the stop), and Move Forward flies along it;
  - `face` / `aim`: arrival means facing the unit and pitched at it, judged
    on a pose sampled after the last turn/pitch key;
  - `vehicle_sample` / `pitch_steerable` helpers.
- `WorldPacketReducer`:
  - `can_fly` (MOVE_CAN_FLY) is decoded and validated;
  - `packet_vehicle_pose` holds the vehicle mover's last sample for 60 s,
    because a hovering vehicle sends nothing;
  - in a vehicle only a vehicle-mover sample counts.
- `ServerVehicleCombatPolicy`:
  - waits ≤ 3 s after boarding for the vehicle's first packet;
  - a CAN_FLY vehicle plans in the air, even landed;
  - height and facing come from the vehicle sample;
  - hover approaches carry `face_towards` + `aim_pitch`;
  - a DEST_TRAJ button (`db2_trajectory`) is aimed with the pitch before
    the press (`VEHICLE_AIM`);
  - re-arriving three times skips the unit for 30 s.
- Tests:
  - `test_vehicle_flight_20261026.py` (extended);
  - `test_hover_pitch_sim_20261026.py`, a closed-loop pitch seat with the
    measured rates and pose latency;
  - `test_server_vehicle_combat_20261025.py` (hover point).
- Offline only.

## 2026-10-26 — Vehicle buttons from the client DB2; race retry; flying and ground vehicles

User: "there are tons of vehicles in the game, it should do all of them by
itself"; "the vehicle driving, flying and on the ground — the whelp quest
is next, and the Giant Boar".

- **Use mode from the DB2** (`vehicle_abilities.spell_shape` / `db2_mode`,
  `ClientCatalog.spell_effects`): a button's SpellEffect rows and their
  trigger chain decide the mode. Nothing is keyed to a spell or vehicle.
  - FORWARD_DASH: charge/leap/jump to the caster's front.
  - TARGETED: damage or a charge at the selected target, or an aimed missile.
  - CLOSE: damage around the caster or in a cone.
  - A movement under a missile's impact does not count.
  - Order: learned effect > DB2 > tooltip words > LLM > range. The English
    word list is now only the fallback.
  - A scripted button (Trample 305556 is a bare DUMMY) is read through the
    spells the vehicle/pet casts right after the press. They are learned as
    `follow_up`, persisted with the ability effects; for Trample that is
    321627, CHARGE_DEST to the front.
  - Checked on the real tables:
    - Burning Bark: TARGETED;
    - Trample plus 321627: FORWARD_DASH;
    - Thunder Clap and Whirlwind: CLOSE;
    - Multi-Shot: TARGETED.
- **Scene ClientActors** (`ServerVehicleCombatPolicy._scene_actors`): an
  objective creature a running client scene spawns has no server unit. It
  is attacked at its DB2 spawn points (`ClientCatalog.scene_actor_spawns`;
  Giant Boar scene 2712: 8 Monstrous Cadavers, 165150).
  - A dash button lines up 12 yd short, facing the actor, and fires within
    18 yd and 0.2 rad.
  - An around-you button fires next to the actor.
  - A targeted button never fires (a ClientActor cannot be selected).
  - A credit within 6 s crosses the actor off; two dashes without credit
    give it up.
  - `combat_planning` passes the mode.
- **Flying vehicles** (live 11:05–11:06, Ruby Whelpling):
  - the vehicle mover's own movement packets are the player's;
  - `HoverControl` climbs, descends and steers to a hover point 6 yd above
    and 6 yd short of the target;
  - a passenger's root no longer fails a vehicle MOVE;
  - Tab from the air is checked in 3D;
  - climbing turns use a valid lease (`turn_lease`).
- **Race retry** (`SceneCourseRetryPolicy`): a failed ring course is retried
  from its starter's gossip option, at most 3 times.
- Tests:
  - `test_vehicle_ability_shapes_20261026.py`;
  - `test_vehicle_flight_20261026.py`;
  - `test_scene_course_20261025.py` (retry).
- Offline only. Restart the agent before the next live test.

## 2026-10-25 late — Skytop race live fixes (race completed live at 21:23)

Fixes from the 21:03 and 21:19 runs (`docs/LIVE_VALIDATION.md`):

- `ActionLaunchCoordinator.dispatch_lane`: a flight-ability tap at skill
  start goes on the discrete lane. Before, the movement lease was rejected
  and the agent fell to MANUAL.
- `StateInvalidationPolicy`: in the air a position jump is a teleport only
  beyond 100 yd/s × elapsed + 30 yd. A fast glide no longer cancels the
  MOVE and resets navigation.
- `NavigationService`: a rooted rider's walk fails as `player_rooted`;
  the flight loop waits for the start (`flight_path.rooted`).
- `movement_visual_interrupt`: a resolvable ring scene interrupts any other
  MOVE (`SCENE_COURSE_STARTED`, also in the fast lane);
  `active_scene_course` is memoized.
- `flight_route.landing_candidates`:
  - the known layer first;
  - then the nearest uncovered layer;
  - a known height without navmesh lands off-mesh.
  `FlightPath.landing_on_navmesh` / `landing_radius`; SkyridingControl
  arrives at the touchdown, relaunching at most twice.
  `ground_transition_required` stays False for off-mesh landings.
- `TravelModePolicy`: already on a gliding mount, trips ≥ 60 yd fly.
- `QuestLocationPlanningPolicy`: a map marker of a quest not in the log only
  counts within 800 yd.
- Tests: `test_skyriding_race_live_20261025.py`.

## 2026-10-25 evening — Skyriding on fresh feedback, abilities, travel flights, live scene courses

User: "use the Skyriding spells and optimize — it circles around a ring";
"not only for this quest: fly from one quest to the next this way too";
"take the courses from the DB2"; "remove what blocks the medium lane".
Evidence: the agent's own 77345 course (live 17:26–17:30, 116 s with loops)
and the 68796 Skytop race (20:46–20:47, WAIT while the race ran out).

- **Why it circled** (decoded own movement packets + thread profile):
  - the packet inbox was drained only by the medium tick (1–3 Hz, seconds
    under SQLite load), so the 20 Hz flight loop steered on a facing and
    pitch 0.3–0.6 s old and turned ~1.3 rad past every heading;
  - the medium tick held the engine lock 0.1–0.45 s (once 6 s), and the
    fast loop skipped ~50 % of its samples (`busy_skips`);
  - turn keys rotate 2.35 rad/s, not π (795 packet pairs: p50 2.34, p90
    2.37); pitch keys rotate ~1.4 rad/s;
  - a ring abeam inside the turn circle was orbited;
  - Surge Forward was never used (the one Surge in that run was the user's).
- **Fresh feedback:**
  - `PacketEventInbox.peek_movement` → `RuntimePacketSource.peek_own_movement`
    → `WorldPacketReducer.peek_own_movement`;
  - the fast lane reads the newest own movement packet under the same
    authentication, context and semantic checks, without consuming it;
  - an airborne MOVE gets a 1 s medium tick beside the parallel lane.
- **SkyridingControl:**
  - measured rates;
  - a lease-ledger predictor (facing, pitch and position from the keys held
    since the sample);
  - a turn-circle escape;
  - the next ring is steered at provisionally until the server credit
    arrives (2 s);
  - Surge Forward from the Skyriding bar (spell 372608, a bare action-button
    tap on the discrete lane; `flight_ability_tap`);
  - dives for speed; boosts toward a final point more than 10 yd above;
  - waits while rooted on a race start line.
- **Skyriding travel (quest to quest):**
  - `TravelModePolicy` turns long MOVEs (≥ 250 yd), and any MOVE in the
    air, into `flight` + `flight_style: SKYRIDING` MOVEs, and mounts the drake;
  - `skyriding_blockers`: no flying riding skill is needed;
  - `flight_route.skyriding_path` turns the terrain plan into waypoints;
  - the movement controller flies them with SkyridingControl;
  - an air-ending (truncated) leg completes in the air;
  - a touchdown near the landing walks on; if the landing cannot be walked
    to, the drake takes off again (at most twice);
  - a failed flight walks for 60 s;
  - a `flight` MOVE that cannot be planned walks the navmesh, never a
    straight line.
- **Live scene courses (no hand binding):**
  - the decoder adds `SCENE_STARTED` / `SCENE_ENDED` / `SCENE_EVENT`
    (Checkpoint / RaceComplete only) and own `MOVEMENT_ROOT` (70340
    family, layout `RETAIL_70575_CAPTURE_VERIFIED_V1`);
  - the reducer adds `packet_scene`, `route_counters.scene` and
    `movement_rooted`;
  - `ClientCatalog.scene_course` picks the ring path of the running package,
    from a current-quest PlayerCondition, the only path, or the only path
    starting within 60 yd of the scene start (ambiguous → None);
  - `SceneCoursePolicy` adds the MOVE.
  - Result: the four lessons resolve to exactly their reviewed routes, and
    Skytop (package 3562) resolves to path 43699.
- **Medium lane in server mode:**
  - no screen-track recognition against remembered looks;
  - no EntityMemory objective hypotheses;
  - the diagnostics-only memory metrics wait until FULL_AI is disarmed.
- **Simulator:**
  - recalibrated: measured rates, delayed packets and credits, the
    scheduler's lease replacement, Surge, vigor and stall;
  - on 77345 the old controller takes 136 s and the new one 37.5–59 s;
  - the new controller holds 38–40 s under 0.15–0.5 s lock gaps, which the
    old one fails.
- Also: `runtime.py` is back under 600 lines; the addon version test
  expects 0.9.77.
- Tests:
  - `test_skyriding_fast_control_20261025.py`;
  - `test_scene_course_20261025.py`;
  - `test_server_mode_medium_lane_20261025.py`;
  - `test_skyriding_lessons_20261025.py` (rewritten).
- Status: OFFLINE_TESTED. Nothing here is live-validated yet.

## 2026-10-25 — Flight groundwork: Steady Flight plan/control, Skyriding telemetry

User: "first plain riding in the air, then vehicles in the air"; then the
Skyriding lessons (68795 → 65118 glide, 65120 dive, 65133 momentum: five
rings, then land in the target area).

- **Addon 0.9.76** (not installed yet; it also carries the bag-item fix):
  - `flight` (IsFlyableArea, IsAdvancedFlyableArea, gliding);
  - `mount_capability.flying_riding_known`;
  - per summon-mount slot: `mount` (type id, usable, active, steady flight);
  - `skyriding_bar` (bonus bar 5);
  - while airborne, the fast lane carries `movement.pitch`,
    `movement.gliding` and `movement.forward_speed`.
- **Ymir movement packets:**
  - pitch and the 12.1 optional blocks (WPP `ReadMovementStats1210`): fall,
    inertia, and **AdvFlying forward/up velocity**;
  - flags `flying`, `adv_flying`, `falling`;
  - new state `packet_flight`.
  - Verified on the user's 10:00 capture: launch up 44 yd/s, a level glide
    holds the height, a dive to the 65 yd/s cap, a pull-up trades speed for
    height.
- **Steady Flight, offline only:**
  - `navigation/flight_route.py`: a straight-line plan over MAPS + VMAPS
    ground (12 yd clearance above the next 60 yd, a navmesh landing point;
    fails closed on unknown ground or a covered landing);
  - `agent/flight_capability.py`: a fail-closed gate;
  - `agent/flight_control.py`: takeoff / Jump-Sit altitude hold / landing
    with a 3D stall watchdog;
  - `MovementController` delegates a `flight_plan` destination;
  - `GlobalNavigator` plans `flight` MOVEs; `NavigationService` keeps the
    packet height in the air.
  - Not done yet: wiring `travel_mode` to the flying mount, and Skyriding
    control (it needs the user's ring capture).
- Tests: `test_flight_plan_20261025.py`, `test_skyriding_movement_packets_20261025.py`.

## 2026-10-25 — Exile's Reach run 10:23-11:00 fixes (Ymir 70575 live)

User-reported, each traced in the profile journal, the telemetry, the run's
Ymir dump (decoded offline) and the thread profile:

- **First Aid Kit on Kee-La, Bjorn and Austin; Scout-o-Matic; Giant Boar**
  were hunted with Tab, which never selects a friendly unit.
  - Each has TDB `npc_spellclick_spells`. A monster objective on such a unit
    is now `credit_action=SPELLCLICK` (`tdb_knowledge.py`).
  - It is no kill target. `ServerNpcInteractionPolicy` walks to the unit and
    presses F7 (`OBJECTIVE_SPELLCLICK`, verified by quest credit or by vehicle
    entry).
  - When the client's soft-interact recipient is exactly that unit, up to
    6.5 yd counts as reach. The hovering Scout-o-Matic was 5.3 yd away
    (4.8 yd above), and the old 4 yd gate re-walked to it six times.
- **Loot after every kill**: the next kill walk was 116 (100 + agenda 12 +
  campaign 4), while the corpse walk was 112 and the press 108. Server loot is
  now 120/122 (`server_loot_planning.py`).
- **Campfire never used**: the server named Campfire 339769 with the cook
  objective 394179 and set our Activate flag the moment the 5th meat was
  looted.
  - Described item rows that only objects yield now use that server object
    (`hidden_object_sources(described=True)`).
  - Learned-place walks and sweeps stay limited to hidden rows.
- **Vendor**:
  - "Any item purchased from / sold to Quartermaster Richter" now name
    Richter (`_BUY_VENDOR`), so the agent walks to him.
  - Addon **0.9.76** reads bag items through `C_Item.GetItemInfo` (the global
    is gone in Retail 11+, so every sell price was 0) and exports the
    client's `hasNoValue`. SELL accepts `has_no_value is False`.
- **Combat WAIT until the mob died**: three instant out_of_range failures
  made COMBAT UNRESOLVED for 120 s. A fight against a live attacker is never
  parked (`GoalManager.filter(live_combat=...)`).
- **Running ender re-planned every second** (Westward Bound):
  - The walk targets the server spline's end (`travel_position`).
  - The drift tolerance grows with distance.
- **Tent not in vmaps/mmaps**: every repeated stuck on the same spot widens
  the avoided circle: 3 → 4.75 → 6.5 yd, max 7.5.
- **MANUAL froze the GUI**: a lock-order deadlock between the tick's
  `memory.batch()` and `set_mode`. The tick now takes the engine lock first.
- **Slow tail**: in server mode the creature-look cosine is skipped. It only
  orders screen probes and was the hottest stack.
- **WPP**:
  - `quest_objectives.ConditionalAmount` is misparsed for 70448/70575 (text
    bytes), so it is no longer merged.
  - `tools/import_ymir_dumps_tdb.py --revert-column
    quest_objectives.ConditionalAmount` undoes the 98 logged updates. It has
    not been run yet, because the TDB was open in the user's SQLite browser.
- Tests: `test_exile_reach_live_20261025.py`, `test_manual_deadlock_20261025.py`,
  `test_wpp_unreliable_columns_20261025.py`.
- Open:
  - Steering the boar vehicle (planned together with the whelp vehicle
    movement).
  - Fast-state Hz outside MOVE (parked with the server-first cleanup).

## 2026-10-25 — Ymir 70575 (the user's V3) is the pinned capture

- User: "itt van az exe, bekéne tenni a helyére, elvileg mukodik faszán";
  the client is 12.1.5.70575.
- Checked before installing:
  - the user's 70575 dump decodes with our reviewed decoder (154 entity
    creates, all TDB templates, 22 quest-giver statuses, positions sane);
  - WPP aliases 70575 to the 70340 opcode table, and that table's SHA-256
    equals the one already pinned.
- `runtime/ymir/ymir_retail_12.1.5.70575_PORT_CANDIDATE_V3.exe` (+ manifest)
  is copied in. The 70448 V2 stays on disk but is no longer started.
- Pins updated:
  - `ymir_bridge.py`: SHA-256 `77cc8a63…`, `EXPECTED_BUILD = 70575`;
  - `gui.py` starts V3;
  - `builds.py`: 70575 joins the 70340 family (70529 does not, as it was
    never captured);
  - `pkt_dump_import.py` accepts dumps of 70448 and 70575;
  - `AGENTS.md`: the Ymir exception names the new pin.
- Tests: `tests/test_ymir_70575_install_20261025.py`. This includes a decode
  of the user's real dump, skipped when the dump is absent.
- Open: the first live agent run with V3.

## 2026-10-25 — Ymir dumps into the TrinityCore TDB itself (WowPacketParser)

- User: "the original TDB, not the learned one -- everything should be
  updated in it", from the Ymir dumps, by a GUI button, with progress; the
  existing dumps imported, then deleted.
- TrinityCore's WowPacketParser is built from source in
  `native/WowPacketParser` (.NET 10, supports V12_1_5_70448 and 70575);
  its settings (Midnight target, SQL only, the world tables) live in
  `config/wpp/WowPacketParser.dll.config` and are copied beside the exe.
- `wowbot/agent/wpp_tdb_import.py` merges WPP's SQL row by row instead of
  its DELETE+INSERT: an existing row gets only the sniffed columns that
  differ (`VerifiedBuild` follows; ScriptName, AIName ... stay), a missing
  row is inserted, a sniffed spawn is inserted only where the TDB has no
  spawn of that entry on that map within 20 yd (creature) / 2 yd (object),
  under GUIDs from 9 000 000 000 000, its addon / spawn-tracking rows
  following; `UNKNOWN` values and rows with unresolved variables are
  skipped. Every change is logged (`aipc_wpp_changes` with old/new values),
  every dump is imported once (`aipc_wpp_dumps`), and the untouched TDB is
  copied to `*.before-wpp-import.sqlite3` before the first write.
- `tools/import_ymir_dumps_tdb.py` fills the learned TDB first, then the
  TrinityCore TDB; with `--recycle` a dump that both hold goes to the
  Windows Recycle Bin (recoverable; emptying it stays with the user).
  Progress: `output/agent/ymir-bootstrap/tdb_import_progress.json`.
- GUI: "Ymir dumpok -> TDB most (WPP)" button, "Ymir leállításkor is"
  checkbox (persisted in `output/agent/tdb_import.json`) and a progress
  line (dumps, new spawns, new/updated rows, recycled, errors, time).
- Tests: `tests/test_wpp_tdb_import_20261025.py`. A copy of the TDB took
  two dumps in 37 s (43 new creature spawns, 295 covered; gossip, quest
  objective and template rows merged); a second run imported nothing.
- Run on the real TDB (user's request, nothing else running): 65 dumps in
  three passes (fixes between them: a transport spawn's UNKNOWN map, a
  64-bit flag beyond SQLite INTEGER, header-only dumps), 7 687 logged
  changes, `quick_check ok`: 1 937 creature and 401 object spawns (1 799 /
  380 on map 2444), 2 202 creature addons, 730 creature templates and 665
  difficulty rows updated, 422 conversation rows, 96 gossip rows, 50 quest
  givers and 48 enders, 92 quest objectives updated, 28 vendor items, 26
  spellclicks. All 67 dump files are in the Recycle Bin; the backup is
  `TDB_full_world_...before-wpp-import.sqlite3` beside the TDB (it already
  holds the three empty `aipc_wpp_*` tables, no changed rows).
- Not covered: `data/tdb_spawn_catalog.sqlite3` (built from the TDB's SQL
  text for spatial memory) is not rebuilt from the updated SQLite TDB.

## 2026-10-25 — quest-vehicle combat by server positions (flying vehicles too)

- Recording 01:12:27 (2026-10-23), Training Wings (70061) in the flying
  Ruby Whelpling (button 1 "Burning Bark", harmful, 20 yd): the
  screen-driven vehicle attack is off in server mode; the one remaining
  MOVE was forced onto the navmesh by `_guard_physical_move` (a flying
  vehicle has no walking route), COMBAT/DEFEND reported
  unsupported_mechanic, and the quest's description-less kill rows
  matched no live objective.
- `vehicle_combat_planning.ServerVehicleCombatPolicy` (server mode, any
  vehicle with an attack button): a selected live objective unit -- or in
  combat any selected live enemy -- in range (the client's `in_range`)
  and in front gets the button (existing VEHICLE_ABILITY skill); out of
  range or facing away: approach its server point to 60 % of the range
  and face it; nothing selected: Tab with a GUID check when the nearest
  objective unit is straight ahead within Tab range, else approach it.
  Over the unit but still out of range while flying: one bounded descent
  step (at most every 2.5 s, 6 per unit).
- A flying vehicle's MOVE (`direct_flight`) is no navmesh request; the
  supervisor admits VEHICLE_ABILITY and vehicle approach/descent in
  combat.
- Kill rows without a description bind by their non-proxy credit name
  ("Agitated Weedling" -> "0/12 Agitated Weedling slain"); "Speak to /
  Talk to / Ask / Meet ..." rows are never kill targets (Skyriding listed
  Lord Andestrasz as one).
- Tests: `tests/test_server_vehicle_combat_20261025.py`. Replay of the
  recorded vehicle tail: the server vehicle approach replaces the navmesh
  failures and the elite WAITs. Not live-validated; flight altitude
  control beyond the bounded descent is not built.

## 2026-10-25 — stairs over hillsides, single-row talk, egg pickup, soft-unit F7

- Recording 01:12:27 (2026-10-23, Waking Shores -> Ruby Lifeshrine): the
  single-row gossip ("I am ready." at Sendrax, 01:17:45), the egg carry,
  the ride to the queen, 66114/66115 turn-ins and four "(Quest)" talk rows
  ran live. Stalls: the egg was not picked up (the user did it), the ender
  at the Lifeshrine waited behind another NPC, and Training Wings (Ruby
  Whelpling vehicle, flying) found no route and no vehicle attack.
- Stairs (user: "it struggles up the hillside while a staircase goes up
  beside it"): native `aipc_detour_walking_v3.dll` charges `NAV_STRUCTURE`
  (0x20) polygons a quarter of the slope cost and no riser penalty. A
  route with a steep climb (>= 24 degrees, >= 1.5 yd) marks the built
  polygons within 30 yd of that climb -- a corner >= 1.5 yd above MAPS
  terrain, inside a VMAPS model box, a model surface within 1 yd (short
  ray) -- in a 0.6 s budget, then routes again. Built segments may climb
  up to 60 degrees. 60 random uphill routes at the Life-Binder ruins: 13
  changed, steep terrain climbing 127 -> 92 yd. `AIPC_STRUCTURE_STAIRS=0`
  switches it off.
- Single-row conversations (user: a quest NPC to talk to with one row --
  choose it): the dialog NPC must be the open objective's own credit or
  named creature; several rows keep the text matching.
- Pick-up objectives ("Pick up / Use / Open / Carry ..."): their named
  units are no kill targets; the unit that is the soft-interact recipient
  within 4 yd gets F7 (credit-verified, `OBJECTIVE_PICKUP`). User: in
  combat the egg is put down and must be picked up again -- while a carry
  objective is open, the same unit beside the player (<= 10 yd) is picked
  up again even though the log keeps "1/1 Pick up"; never in combat, never
  the far first egg.
- A wanted quest NPC that is the soft-interact unit while its server
  point is implausible (> 80 yd, platform-relative) is pressed with F7.
- Tests: `tests/test_structure_stairs_20261023.py`,
  `tests/test_single_row_actor_gossip_20261023.py`,
  `tests/test_objective_pickup_20261025.py`. Not live-validated (except
  the single-row gossip). Restart the agent: the v3 DLL loads at start.

## 2026-10-23 — step-downs, unreachable learned places, server-mode POI sweep

- Recording 00:45:11 (agent restarted, so the opened chests were not
  remembered): the learned place of 376945 was crossed off on arrival
  (no usable chest there), then the walk to 376944 failed
  `required_navmesh_route_unavailable` three times and the agent waited.
  User: "a steep-like staircase has to be climbed there".
- Cause: two centred micro-segments that went DOWN 0.8 and 1.1 yd (49.7
  and 80.9 degrees) rejected the whole 419 yd route; the uncentred path
  had none. `_walking_segments_supported` now accepts a descent of at
  most 1.5 yd (`STEP_DOWN_YARDS`); climbing keeps the 44 degree limit.
  376944/43/42 now route (419-430 yd, 20-24 yd of lava).
- That failed route also ran the deferred VMAPS wading pass for 9 s; the
  pass now measures the polygons nearest the segment first within 0.5 s
  (`WADE_SLOW_BUDGET_SECONDS`), the rest stay deferred.
- A learned place or sweep cell whose MOVE failed is skipped for 300 s and
  the next one is taken. User idea: with no learned place left and nothing
  in server view, walk the quest POI polygon (`SERVER_ZONE_SWEEP`, nearest
  cell not within 80 yd of the trail walked, at most two passes); the
  server sends the objects near the way and the server steps take over.
- Tests: `tests/test_hidden_object_sources_20261023.py` (6). Replay of the
  recorded tail: MOVE to the next learned place instead of WAIT. Not
  live-validated.

## 2026-10-23 — far quest objects from their learned place

- Recording 00:32:47: the hidden-object fix worked live -- book chests
  376946 (00:38:33), 376941 (00:40:30) and 376945 (00:40:49) were walked
  to by server position, opened with F7 and credited (3/4 Books saved).
  Then WAIT from 00:40:58: the server only sends nearby objects and had
  dropped the unopened chests 376944/376943/376942 (296-351 yd), although
  their exact positions were learned from it earlier (LEARNED_SPAWN).
- `ObjectInteractionFlow.remembered_object_spot`: with no server-visible
  usable object, the nearest learned/TDB spawn of the quest's hidden
  object rows that was not opened in this acceptance is a navmesh MOVE
  target (`LOCATE_REMEMBERED_QUEST_OBJECT`, out of combat); near it the
  server names the chest again and the server steps take over. A credited
  object's entry is remembered (from its GUID); a place where the server
  shows no usable object for 4 s within 30 yd is crossed off; a dropped
  quest progress (taken again) clears both.
- Replay of the recorded tail with the navmesh: MOUNT, then MOVE to the
  learned place instead of WAIT. Tests extended in
  `tests/test_hidden_object_sources_20261023.py`. Not live-validated.

## 2026-10-23 — quest objects named only by hidden item rows (book chests)

- Recording 00:17:27: the book quest giver was pressed by the agent itself
  (00:19:05 F7 on GameObject 377499, 66000 accepted 00:19:06) and the route
  crossed the lava. Then Library of Alexstrasza stalled in WAIT (00:21:15
  on): the live objective "0/4 Books saved" is a [DNT] kill credit; the
  TDB's description-less item rows come from book chests 376941-376946,
  and the server named each chest's objective (quest_objective_id 427692,
  427709, ...) with our Activate flag set, 122-200 yd away.
- `hidden_object_sources` lists such rows; `objective_objects` links a
  server object by them, `packet_use_spot` accepts an open quest that has
  them, and the quest objective planner runs the existing server object
  steps (walk to the exact chest, face it, F7 out of combat) for any open
  objective of that quest. The steps are one helper now
  (`_server_object_steps`), shared with game-object objectives.
- Replay of the recorded WAIT tail with the navmesh: MOVE to chest 376945
  (route 172 yd, 9 yd of lava) instead of WAIT. Tests:
  `tests/test_hidden_object_sources_20261023.py`. Not live-validated.

## 2026-10-23 — quest givers that are objects (a book on the ground)

- Recording 00:02:20: the progress-bar fix worked live -- the agent hunted
  the Erupting elementals by server position, 66998 completed at 00:09:06
  and was handed in at 00:09:12. Then Library of Alexstrasza (66000) had
  to be taken from a book, GameObject 377499 "On the Origin of Draconic
  Species" (type 2): the server showed it with a "!", 4.3 yd away, as the
  client's soft-interact recipient, but the agent waited 00:11:13-00:11:21
  until the user pressed F7. `ServerNpcInteractionPolicy` considered
  creatures only.
- A game object with a server quest marker (quest available or reward
  ready) is now walked up to and pressed with F7 when it is exactly the
  soft-interact recipient; the identity gate uses its `object_id`, and an
  object without a marker is never a giver. Replay of the recorded states:
  MOVE from 00:11:09, INTERACT from 00:11:13.8 with ID_GUID_CONFIRMED.
- Tests: `tests/test_gameobject_quest_giver_20261023.py`. Not live-validated.

## 2026-10-23 — progress-bar quests: hunt the hidden kill credits

- Recording 23:45:53 (Waking Shores): 65998/65999 were handed in to the
  following Ruby Egg Guardian a minute after start (F7 soft-interact fix
  live). Then Fighting Fire with... Water (66998) stalled in the Erupting
  Cavern: its only live objective is the bar "Erupting Cavern contained";
  every Erupting Droplet killed in self-defence added 4 % (0 -> 24 %), but
  the agent hunted none and waited.
- The TDB holds the bar (objective type 15) plus description-less creature
  credits (Erupting Droplet 191517/191983, Lasher 191944, Magma 191917).
  `kill_objective_entries` now binds such hidden rows to the open live
  progress bar whose text contains the TDB bar's description; no bar row,
  a finished bar or another bar's text maps nothing. On the recorded final
  state 53 server units become kill targets.
- The quest item (Bottled Water Elemental, ground-targeted helper, 30 s
  cooldown) is not needed for credit. Ground/target quest-item use is
  planned (AGENT_MILESTONES C6) and on hold by the user.
- Tests: `tests/test_progress_bar_kill_credits_20261022.py`. Not
  live-validated. The cave-to-campaign-giver route still fails on a slope
  (`walking_segment_grade_rejected`), unrelated to liquid.

## 2026-10-22 — shallow liquid fords (lava, slime, water) and a following quest ender

- User: the character had to walk through lava to get from one place to
  another, but the navmesh forbids every liquid; allow every liquid where the
  feet reach the floor (no swimming), and cross it, do not walk along it.
  Recording 22:57:08 (Waking Shores, Life-Binder Conservatory): the Human
  walked in lava at 1.85 yd MAPS depth (liquid_z - terrain_z; the player's Z
  equalled MAPS terrain_z) and swam at 2.03 yd; the routes across the lava
  failed with `required_navmesh_route_unavailable`.
- Native Detour `aipc_detour_walking_v2.dll` (new name; v1 stays as the
  fallback a running agent may hold locked): `aipc_nav_polys_with_flags`,
  `aipc_nav_add_poly_flags`, `aipc_nav_liquid_costs`. The walking filter
  multiplies the cost of a liquid polygon: water x3, magma/slime x10, so
  A* crosses at the narrowest point and a dry detour wins unless it is many
  times longer. ABI 807 unchanged; the native filter test covers the costs.
- `TrinityMMapNavMesh`: project flag `NAV_WADE` (0x10, never in a TC tile).
  Liquid polygons near the start-end segment are measured once (centre and
  every vertex) with `WorldGeometryService.liquid_depth`: MAPS for ADT
  liquid (exact; a bank above the liquid is depth 0; TC's -2000 level is no
  liquid), VMAPS for a WMO/M2 liquid such as cave lava. Only when every
  sample has a known floor within 1.6 yd does the polygon get NAV_WADE;
  deep or floorless liquid stays excluded. The MAPS pass costs at most
  ~0.1 s per new area; the VMAPS rays (~4 ms each) run only after a route
  failed without them. Diagnostics: `liquid_wading`, `wade_pass`,
  `wade_newly_marked`, `wade_deferred`, `wade_yards`.
  `AIPC_LIQUID_WADING=0` switches it off; the Python fallback router stays
  land-only.
- Offline on the real Waking Shores data: 17 of the 24 distinct failed
  routes of that recording are found now (lava crossings of 7-33 yd), the
  rest fail for slope/layer reasons unrelated to liquid.
- Follower quest ender (23:11-23:13): the Ruby Egg Guardian walked with the
  player with a server "?" and was the client's soft-interact unit, but was
  known from monster moves only (no NPC flags) and never pressed. A unit
  with a server quest marker that is the verified F7 recipient is now
  pressed; otherwise the agent walks to its server point. Replay: 69/69
  ticks propose F7.
- Three tests realigned with the earlier assistant's behaviour changes
  (5 s DISMOUNT, `note_dispatched` after a press, `planner.blocked_until`).
- Tests: `tests/test_liquid_wading_20261022.py`,
  `tests/test_follower_turn_in_20261022.py`. Nothing here is live-validated.
  Restart the agent (the new DLL loads at start); addon 0.9.73 + `/reload`.

## 2026-10-22 — continue healing search after 3/4 and packet range loss

- PID 9812 confirms three actual item heals; generic WAIT at 22:28:15
  followed loss of the fourth actor from the current packet projection.
  Last-seen locations now remain bounded search hints, separate from live
  interaction identity. Mixed-height objective POIs use the existing finite
  NavigationService coverage, shared with rescue quests, with individual Z.
- Credited sites are skipped, failed cells advance, and fresh server actors
  hand search back to exact-GUID approach/target/item execution. A short
  post-credit deferral prevents immediately reacquiring newly appearing
  departing actors; no GUIDs or credit are merged.
- 1269 tests passed, 1 skipped, 3 known older discrepancies deselected.
  Recorded-state replay selects the missing NPC's search region and native
  MMAP finds a complete ~211-yard route. Fourth heal is not live-validated.
  Details: `docs/LIVE_TEST_FIXES_20261022_222506.md`. GUI restart required;
  no addon, binding, capture, database or walking-policy change.

## 2026-10-22 — healing quest-tool identity, acquisition and hidden objective rows

- PID 14544, recording 21:55:13: the local semantic hint turned "Injured
  drakonids healed" into DEFEND, producing repeated 15-second WAIT_EVENT
  attempts although the addon exported special item 193917. A literal heal
  clause plus that exact API tool now grounds USE_ITEM_ON_TARGET; the LLM
  cannot demote it into a defend/event wait. Original API evidence remains.
- Static objective matching uses exact IDs or unique normalized descriptions,
  not visible-array order across hidden TDB rows. The Sendrax objective maps
  to 429977, not hidden credit 430207. The same rule feeds TDB location gates.
- Concrete non-proxy healer entry + current same-instance server GUID/XYZ
  use the existing MOVE/facing -> friendly TARGET -> exact-item skill chain.
  Friendly selection is bounded and verified after Ctrl+Tab; F7 still needs
  fresh exact-item/target/recipient readiness. A wrong GUID, corpse or
  attackable recipient cannot receive the healing item.
- A credit-verified heal temporarily retires that GUID for this objective.
  No item click/cast alone is completion. Healing credit entries are excluded
  from ordinary server kill targeting, without disabling real self-defence.
- 128 scoped modules: 1235 passed, 1 skipped, 3 explicitly deselected older
  discrepancies already control-reproduced in the earlier audit. All 452
  source Python files parse. Post-fix live healing remains unvalidated;
  the separate recorded fall/layer ambiguity is not declared fixed.
- Direct `projekt` edits; no addon, binding, DLL, capture backend or database
  change. See `docs/LIVE_TEST_FIXES_20261022_215513.md`.

## 2026-10-22 — quest-area pins and campaign hand-in WAIT after MOVE

- Recording 21:37:57 (selected PID 8220): after arriving at one task-area
  pin, generic location planning tried another pin inside the same TDB
  polygon. A validated same-map polygon matching the live API pin now gates
  generic area travel; it does not complete an objective or supply entity Z.
- A nearby unfinished side/bonus quest no longer defers finished campaign
  hand-ins. Same-priority nearby quest batching, floor checks, time bounds
  and per-quest hysteresis remain in place.
- The initial route failure predates the reported pixelstrip freeze; fresh
  telemetry recovery retried navigation. Offline native geometry checks find
  a complete hand-in path with the unchanged 44-degree walking policy.
- Actual-project checks: 101 modules, 868 passed / 1 skipped; source AST
  checks pass. No addon, binding, packet backend or native slope setting
  changed. Post-fix movement/hand-in remains NOT_LIVE_VALIDATED. See
  `docs/LIVE_TEST_FIXES_20261022_213757.md` and `docs/LIVE_VALIDATION.md`.

## 2026-10-22 — stable server selection, bounded packet recovery and target safety

- The 20:28:57 recording exposes stale packet queues, a snapshot resend loop
  and a silent return to visual search/loot. Server selection now survives
  stale/empty health across planning, admission, pointer and loot boundaries.
- Coalesce entity state outside the discrete FIFO, prune stale queued state,
  pace current-cache replay and bound resync attempts/backoff. Socket receipt
  no longer masquerades as fresh semantic data in the GUI.
- Reject fresh exact-GUID corpse evidence missing from compact FAST; require
  fresh/coherent hover confirmation. Known elite defence requires actual
  attacker evidence or an explicit kill objective, including at dispatch.
- Written directly in `projekt`; offline tests only. The underlying visual
  misassociation and live elite recovery remain to be validated. No addon,
  bindings, parser schema, capture binary or database was changed.
- See `docs/LIVE_TEST_FIXES_20261022_202857.md` and `docs/LIVE_VALIDATION.md`
  for the live evidence, regression results and four separately reproduced
  older test discrepancies. No requirement/acceptance gate promoted.

## 2026-10-22 — server rescue range recovery and bounded search beyond visible actors

- The 19:49/19:52 user-run attempts (PID 19020) expose two WAIT causes:
  a known whelpling at 85.868 yards was excluded by a 70-yard policy limit;
  later a fresh range error failed INTERACT because only addon selected-
  target XYZ, not the soft recipient's known server XYZ, could drive reach.
- Exact same-instance live rescue actors no longer inherit the friend-tab
  hint radius. A soft hint / old interact-near boolean at 8.5 yards cannot
  interrupt the server approach early. Airborne vertical separation alone
  does not veto a fresh known near recipient; a usable recipient is still
  mandatory before F7. No flight state or missing identity is invented.
- Existing INTERACT -> NavigationService.move_to_entity now supports a
  pinned soft recipient and selected targets whose XYZ is only in packet
  evidence. It retains the original attempt, finite deadline/reposition
  budget, navmesh/arrival/facing guards and the final fresh F7-recipient
  identity check. Removed/dead/wrong-map/lootable/nonfinite actors fail closed.
- When no live actor exists, matching TDB objective POI points can seed
  finite canonical navigation coverage (no vision/TAB/combat search). Points
  are search hints, not NPC identities/spawns or a proven polygon/floor.
  Explicit per-point heights, objective/map/condition matching and live-POI
  agreement are retained. Visited, failed or timed-out cells retire;
  search yields to a new live actor and exhausts explicitly, not infinitely.
- The user clarifies the second, airborne rescue may have been their own
  F7. The 0/4 -> 1/4 -> 2/4 counter is observed but two autonomous rescues
  are NOT claimed. The earlier 807-pass broad sweep retains the known old
  dismount baseline failure; final focused checks: 107 passed. Real-map
  saved-state queries are offline evidence only. Restart GUI/runtime;
  addon, bindings, client installation, databases and backend are unchanged.
  After hash-verified publication, the actual project passes 810 regression
  tests (one known baseline explicitly deselected) plus 140 architecture/
  entity-identity tests. All 450 source files parse; 372 ledger rows remain.
  See docs/LIVE_TEST_FIXES_20261022_194827.md.

## 2026-10-22 — rejected walking corner, stable route retry identity, concrete rescue actor

- The 12:00 recording (selected PID 14540) reaches and turns in Reporting
  for Duty, accepts quests 65989/65990, completes the Djaradin counter and
  remounts after combat/loot. The whelpling rescue stays 0/4; subsequent
  corpse/quest routes repeatedly fail and end in WAIT.
- A native complete corridor contained a centered segment above the
  configured walking grade. After the existing wider centerings fail,
  try at most six projected nearby pivots with two fully routed legs.
  Both original endpoint polygons, pivot connectivity, allowed flags,
  clearance margin, grade/step limits and finite route limits must pass.
  No direct-line, partial-path or relaxed-slope fallback is added.
- MOVE retry identity ignores only navigation explanation/resume metadata
  and a duplicate same-instance alias. Physical coordinates, GUID, floor
  and safety parameters still distinguish requests. Supervisor resumes
  obey planner cooldown and task quarantine. A required-mesh failure is
  PATH_BLOCKED, not INTERNAL_ERROR.
- Rescue matching also consumes an exact, non-proxy creature-credit entry
  when TDB's separate named-creature list is empty. A matching live
  spellclick actor is approached at its server XYZ through the existing
  navigation service, then the existing identity-checked INTERACT/F7 flow
  applies. A holding game object keeps OBJECT_USE. Raw monster/KILL credit
  does not turn a saved/rescued objective into a kill action.
- Offline checks: 731 passed plus the independently reproduced old
  dismount baseline failure in a 70-module sweep; final interaction/
  rescue/navigation selection 84 passed. Real-map saved-state replay
  returns complete gentle alternatives and a route to the rescue actor's
  correct floor. These are not live rescue/arrival successes.
  Addon, native DLL, bindings and databases are unchanged; restart runtime.
  See docs/LIVE_TEST_FIXES_20261022_120016.md.

## 2026-10-22 — keep partial navigation legs separate from arrival; remount after combat

- The 11:31 recording (PID 20884) reports MOVE success around 11:33:35
  while the actual quest POI remains about 307 yards away. An uncertain-Z
  30-yard localization leg was mistaken for the final route destination,
  so reached-location bookkeeping suppressed further movement to the POI.
- Localization legs now stay nonterminal within the same MOVE/request.
  Their final anchor does not inherit the goal's interaction radius/facing;
  the original endpoint is retained and re-resolved for the next leg.
  Simplified long edges are clipped on the validated polyline to respect
  the actual 12/30-yard limits; initial, danger/TTL and fall replans share it.
  Probes retain one finite request deadline. A mesh endpoint outside the
  original arrival envelope fails as PATH_BLOCKED, never as success.
- Mount/dismount transitions are observed on fresh ticks even when combat
  or a pending skill bypasses ordinary planning. A confirmed combat
  dismount does not start an extra 20-second on-foot penalty after combat.
  Ordinary intentional dismount hysteresis and mount-failure backoff stay.
- A resumed long MOVE receives the normal travel preparation before
  walking. MOUNT preserves supervisor/recovery resume ownership until MOVE
  actually starts; a LOCATION commitment cannot bypass that preparation.
  Nearby loot/object work, capability, bindings, mount usability,
  cooldowns, death, vehicles, unsafe context and retry gates remain.
- Offline tests and real-map geometry checks only; no new live success is
  claimed. Restart GUI/runtime; addon and bindings are unchanged.
  See docs/LIVE_TEST_FIXES_20261022_113117.md.

## 2026-10-22 — safer walking costs and no inherited fall after recovery

- Live 09:52 test confirms addon 0.9.75 API flags, exact gossip click and
  actual optional Sendrax objective credit (1/1). The following route,
  not the dialogue, now fails. Two supported stuck results followed by
  `fall_in_progress` trigger the existing three-failure/120-second task
  quarantine, surfaced misleadingly as a generic server-mode WAIT.
- Navigation cancellation/reset clears the old airborne episode timer;
  an explicitly grounded new request does too. A separate brief ledge step
  after RECOVER cannot inherit the previous attempt's elapsed fall time.
  Confirmed ledge hazards persist in the same context; a genuinely ongoing
  fall still stops steering and may terminate the route.
- Native Detour now uses geometry-based walking costs: gentler movement,
  less rough surface and clearance from known mesh-boundary edges can beat
  a shorter scramble. Flags/area permissions remain authoritative. This
  is NOT a semantic road network: the loaded data has no verified ROAD label.
- Returned centered anchors are checked against the configured slope with
  a 0.6-yard ordinary-step allowance. At most two wider same-endpoint
  centerings are tried if corner offsetting creates a steep segment.
  Unsupported routes fail closed, never fall back to a direct line.
  Service-level corner offsets also respect the same grade bound.
- Versioned `native/bin/aipc_detour_walking_v1.dll` is built with the
  virtual filter enabled and its capability is checked. The old loaded DLL
  need not be overwritten. GUI/runtime restart is required; addon unchanged.
- Real-data offline comparison at four recorded positions changes an
  old 62.8–77.8 degree approach into 24–30 degree canonical route segments,
  for a somewhat longer walk. No actual new-route arrival is claimed.
  See docs/LIVE_TEST_FIXES_20261022_095258.md for checks and live limitations.

## 2026-10-22 — repeated gossip WAIT: export Retail's actual quest-label flag

- The new 09:39 recording confirms addon 0.9.74 was loaded, server arrival
  and F7 succeeded, but the third displayed `(Quest)` row still lost its
  label in telemetry. The previous rendered-text correction is NOT live
  validated; only the first ordinary row received `display_name`.
- Retail addon 0.9.75 exports API `flags` and optional boolean
  `quest_label_prepend`, resolved with the client's own QuestLabelPrepend
  enum and FlagsUtil. No numeric mask, quest/NPC ID or row index is guessed.
  This is the same semantic flag used by Retail's UI to prepend the label.
- The existing shared planner/pre-click evidence helper prefers that
  actual boolean. A known false API label outranks decorated/stale text.
  Unknown flag evidence retains the previous guarded text fallback.
  NPC ownership, freshness, option ID/name/point, ambiguity and quest-credit
  requirements are unchanged. No new action owner is introduced.
- Text fallback now supports named-color escapes and Button:GetFontString.
  The row lookup also honours Retail's nested elementData.info option ID
  before inspecting shared sizing/prototype objects.
- 36 new regressions; targeted suite 191 passed. Wider checks: 694 passed
  plus the independently reproduced, unchanged dismount baseline failure.
  See docs/LIVE_TEST_FIXES_20261022_093950.md. The new API export/click/credit
  still requires a user-operated live test after addon reload and GUI restart.

## 2026-10-22 — rendered quest gossip marker survives addon export

- Retail addon 0.9.74 preserves the matching visible gossip row's bounded
  `display_name`, independently of the unchanged API name/option ID. In
  the latest Sendrax test the third row visibly had `(Quest)`, but the
  API name did not, so Python had no marker evidence and waited.
- Only visible text whose normalized body matches that same option title
  is exported. Marked text wins over a plain getter on the same row.
  Hidden, secret and unrelated text cannot lend a marker to another option.
- A shared pure UI-evidence helper validates either an API prefix or a
  same-body rendered prefix. The existing planner and skill use it, with
  marker/availability rechecked before returning the click. No global
  text-match threshold or NPC identity guard is relaxed.
- Actual screenshot/telemetry disagreement is documented in
  docs/LIVE_TEST_FIXES_20261022_091936.md. Twenty-seven new regression cases
  include real Lua sensor -> AIPC5 transport -> assembler -> Planner ->
  skill, plus marker loss between planning and dispatch. Post-fix live
  export and quest credit remain pending.
- Both identical Retail packages are 0.9.74 (Interface 120100, AIPC5,
  schema 4 unchanged). Update/reload the installed addon AND restart the
  GUI/runtime; Python-only restart cannot restore an unexported UI label.

## 2026-10-22 — server-present conversation actor no longer lost behind the name preview

- Explicit `Ask <exact NPC> about/regarding ...` creature-credit objectives
  resolve their conversation actor through the existing exact TDB name
  lookup, not the six-template generic name preview. The live Sendrax
  variant 193363 was present in packets but absent from that preview,
  preventing the existing server approach from being proposed at all.
- The unchanged server NPC policy now supplies its GUID/XYZ navmesh MOVE,
  facing and exact soft-interact handoff. No NPC/quest ID, alternate action
  owner, fabricated GUID or relaxed interaction guard is added. Normal
  approach remains three yards; this is not a stop-radius change.
- Eighteen new regressions; narrow conversation suite 70 passed. Thirteen
  fresh saved checkpoints reproduce the lost actor before enrichment and
  return its exact server MOVE afterward, without sending game input.
  See docs/LIVE_TEST_FIXES_20261022_090125.md for the broader test result and
  remaining full-chain live checks. Restart GUI/runtime; addon unchanged.

## 2026-10-21 — 19:00 follow-up: explicit quest-marked gossip before lore

- The existing gossip policy recognises the addon's API-exported colored
  `(Quest)` prefix. A unique usable quest row takes precedence over lore
  text similarity, independent of its position in the list. It still needs
  a fresh exact NPC-window identity and an open conversation objective at
  that NPC. Multiple possible quests/quest-marked rows do not silently pick
  the first; an explicit row quest ID can identify its related quest.
- Direct `Orders/Instructions/Briefing received/heard from <exact NPC>`
  objectives resolve to conversation actors through exact TDB templates,
  including phased actors beyond the generic six-row name preview. A
  technical kill-credit ID is not a physical creature to attack.
- Invalid API row IDs, unavailable rows, invalid points, stale/unknown
  owners and completed objectives remain blocked. Existing quest skill and
  verification own the one click and wait for real quest progress.
- Four actual saved Selistra checkpoints replay through the shared Planner
  and skill without game input. See docs/LIVE_TEST_FIXES_20261021_185729.md
  for regressions and the separately reproduced existing dismount failure.
  Restart GUI/runtime; addon, databases and bindings are unchanged.

## 2026-10-21 — 18:14/18:38 follow-up: precise handoff and grounded gossip

- Explicit positive WORLD_YARDS stop/arrival radii below four yards are
  respected by the planner. The requested final 0.8-yard turn-in close-in
  cannot be discarded as already reached at three yards. Invalid radii
  cannot prove arrival; ordinary routes retain their default tolerance.
- A single explicit TDB instruction naming an exact NPC can ground its
  uniquely matching conversation objective. Technical credit/proxy IDs are
  not physical NPC candidates; completed/future objective rows do not keep
  directing the player back. No quest/NPC/option ID is hardcoded.
- Fresh addon-owned NPC UI GUIDs can authorize the existing gossip skill
  after the hard target clears. Exact template/GUID, row ID/name/point,
  clock/freshness and removed/conflicting-identity guards remain mandatory.
  Ambiguous rows are withheld. Only actual quest credit verifies progress.
- GOSSIP_SELECT treats zero/empty UI quest identity as pending, not an
  immediate wrong-quest failure. It sends no repeat click while waiting;
  a different real quest still fails and the existing deadline still ends
  an unverified attempt.
- Both recorded tests replay offline, including the newer three-TALK/WAIT
  run. Verification details and baseline failures are recorded in
  docs/LIVE_TEST_FIXES_20261021_181320.md. No post-fix live success claimed.
  Restart GUI/runtime; addon and the pinned Ymir executable are unchanged.

## 2026-10-21 — 17:14 live follow-up: startup packet backlog and server interaction handoff

- Stale entity events consumed after a slow startup request a fresh replay
  from the existing producer's bounded current snapshot. The authenticated
  PID/session/map context and two-second freshness gate remain unchanged.
  Requests are rate-limited; failed descriptor writes retry without new
  input. Diagnostics distinguish emitted observations, stale/context/time
  discards and snapshot requests. Removed entities replay as bounded
  tombstones rather than silently remaining alive at the receiver.
- Server-mode MOVE cannot hand off to disabled mouseover targeting or
  declare arrival from a minimap zone. Pointer TARGET proposals are filtered
  before planning and denied again at dispatch admission. Exact server
  ender/soft-recipient handoffs and configured key-target paths stay enabled.
- Scripted BUY objectives (including raw type 14) resolve the explicitly
  named seller through exact TDB creature names and live server entries.
  They are not kill targets, and a completed purchase does not keep asking
  to revisit the seller while a later read/use objective remains open.
- Shared final facing uses the actor's actual world bearing, not the
  smoothed travel heading or projected navmesh endpoint. A bounded turn
  timeout is FACING_FAILED, not ARRIVED; heading-only feedback can finish
  a stationary turn. The user's newer purchase/Disc boarding were manual,
  not evidence of autonomous success.
- Offline regression and syntax checks recorded in
  docs/LIVE_TEST_FIXES_20261021_1712.md. Post-fix live validation is pending.
  Restart the GUI/runtime and its Python Ymir bridge; addon 0.9.73 is unchanged.

## 2026-10-21 — 16:37–16:40 live follow-up: utility vehicles, scripted talks and turn-in loops

- Utility vehicle objectives use an unambiguous exact match between the
  open objective caption and a live, ready, zero-range vehicle ability.
  The shared VEHICLE_ABILITY path checks the current spell/binding and
  verifies that objective's credit, not just a cast or another objective.
  Unknown/ambiguous bars wait; known attack/dash vehicles keep their path.
- Boarding edges yield the FAST movement lease to canonical fusion.
  Stationary utility vehicles cannot start/continue ground routes or stale
  jump/strafe recovery; their buttons own the same existing skill runtime.
- Scripted gossip progress has a 45 s no-input observation window. NPC
  replacement during a conversation never authorizes another click; actual
  quest credit or the deadline ends the attempt.
- Empty-dialog timing restarts for each window; multiple gossip rows are
  content. The existing two-empty-window/120 s suppression covers exact
  server objective/turn-in paths too and expires on a quest/session change.
  A fresh soft recipient can identify the NPC when no hard target exists.
- Canonical server turn-in destinations suppress the duplicate map-POI
  route for that quest, avoiding repeated handoff/cancel/restart cycles.
- Server NPC press cooldowns start only after actual dispatch, not proposal
  construction. Ride interaction waits for delayed vehicle entry (5 s
  response grace, at least 6 s attempt); dismount has a 5 s observation floor.
  These windows never cause an extra press and do not override safety gates.
- Offline validation: 1135 passed; two pre-existing visual vehicle-aim tests
  still fail identically on the unchanged project baseline. Four actual
  checkpoint replays pass (Disc, Sendrax, turn-in, dismount). No live input.
  Addon remains 0.9.73. Runtime/GUI restart and user-run validation pending.

## 2026-10-21 — Vendor gossip purchase, talk/ride credits, no screen steps or pointer moves in server mode

- **Vendor behind a gossip row (addon 0.9.73):**
  - The addon exports every gossip option (`quest_ui.gossip_options`: id,
    name, icon, available, row point), and every vendor item with the page
    offset applied and the page buttons.
  - A BUY objective naming the NPC whose window is open clicks the vendor
    row (`QUEST_DIALOG` `GOSSIP_VENDOR`, verified by the shop opening) and
    buys the item the objective names, even when it is priced in a
    currency.
  - A window closed empty twice is not reopened for two minutes (live
    15:52:59–15:53:21 at Cataloger Jakes: a close/reopen loop).
- **Talk and ride credits:** TDB credits named "Talk to <NPC>" become talk
  targets (every creature template of that name) and "Ride Vehicle" credits
  make the named creatures vehicles. Neither is hunted as a kill. Sendrax
  and the Surveyor's Disc are walked up to at their server position and
  pressed with F7. In the talk NPC's window, the gossip row sharing the most
  words with the objective is chosen. Live 16:13–16:15 the agent bounced
  between three such quests. The talk NPC's TDB and learned spawns
  (`tdb_learned`: Sendrax at four places) are the objective's spawn
  candidates.
- **Mid-route mount:** a walk with more than 80 yd left stops once (every
  30 s at most) to mount when mounting is allowed again.
- **Server mode, no screen at all:**
  - Also dropped: OPEN_MAP, VISUAL_APPROACH, REACQUIRE_TARGET,
    CAMERA_CONTROL, the minimap dot and floor-arrow MOVEs and the local
    visual search, including as a navigation or recovery replacement.
  - No entrance search or map relocalisation.
  - The command dispatcher withholds HOVER, POINTER, CAMERA_GLANCE and
    CAMERA_PAN, so the mouse is not moved onto screen tracks. UI clicks
    stay.

## 2026-10-21 — Several attackers: the next one is fought at once

- **Defence Tab:** in combat with no live attackable target (nothing
  selected, or the first attacker dead), `TARGET` with
  `activation_source: TAB_DEFEND` presses Tab (TARGETNEARESTENEMY) at most
  every 1.5 s. Its verify accepts any live attackable selection. It is
  pinned to the nearest live server unit within 30 yd (else the dead
  target) and allowed only in combat with the Tab binding.
  `ACQUIRE_TARGET` stays unavailable.
- **Immediate retry:** any failed COMBAT/DEFEND while in combat with a live
  attackable target is retried after 0.5 s instead of the failure backoff.
  Before, only `facing_failed` was; live 15:24:50–58 an `identity_uncertain`
  left the agent idle for 8 s while the whelp kept hitting.
- **Start Attack:** with no usable ability (no rage) the melee auto-attack
  starts through a STARTATTACK key when the client export shows one bound.
  The order is: F7 when its recipient is exactly the target, then Start
  Attack, then the screen hover. Live 15:24:47–50 the soft-interact unit was
  the first whelp's corpse, F7 was rightly withheld, and nothing attacked.

## 2026-10-21 — Near server work first; objective rows without a description

- **No more back-and-forth:** a live server unit of any open objective within
  40 yd counts as local work, so a far TDB objective route (96 + agenda 12 +
  campaign 4) no longer outranks the server walk to a nearby objective mob
  (100 + 4). Live 15:21:17–15:22:06 the two swapped every 0.5–1 s: the far
  route dropped below only while an elemental was under the cursor.
- **Objective row without a description:** a TDB objective row with an
  empty description matches its quest's only open objective of the same
  kind (item/kill) when it is the quest's only row of that kind (Practice
  Materials 70124: the Primal Proto-Whelps that drop the scales are now
  hunted; live 15:26:13 the agent waited beside a dozen of them).

## 2026-10-21 — Ghost on a flying mount; persistent loops stop FULL_AI

- **Hovering ghost:** a ghost that is airborne (flying, or mounted — only a
  flying ghost mount exists) with no navmesh route to its corpse descends
  with Sit/Move Down (`RECOVER` step `DESCEND`, 3 × 0.3 s per step, at most
  15 steps, stops after 3 steps without losing 0.5 yd). Still routeless,
  or never airborne, the corpse run goes straight there
  (`require_navmesh: false`). Live 11:29–12:00 the ghost hovered ~35 yd
  above the ground and the navmesh-only corpse run failed 4300 times.
- **Walk cost cache:** the start height is part of the cache key (a route
  from 63.7 yd did not exist, from 58 yd it did; the old key returned the
  stale "no route" for 15 s).
- **Persistent loop stop:** a CONFIRMED loop of one signature that keeps
  repeating for 180 s (gaps under 30 s) switches FULL_AI to MANUAL with
  `persistent_loop_stopped` in the result.
- **Addon 0.9.72:** every transport tier carries `movement.flying`; the fast
  lane used to drop it, so the agent never saw IsFlying.

## 2026-10-21 — Server-only loot, rescue by Ctrl+Tab, held entity facts

- **Server-only loot:** with `server_mode.active` the screen corpse search
  is off: no tooltip-anchor LOOT, no corpse VISUAL_APPROACH, no hover-cell
  search and no step-back reveal. The killed GUID's server x,y,z is walked
  to and Interact is pressed. Interact now loots whichever of our lootable
  corpses it acts on within 5 yd (the selected corpse, else the
  soft-interact unit), not only the nearest one (live 10:57:49: three
  whelps on one spot, no press, then `corpse_not_found`).
- **Rescue by Ctrl+Tab:** around a rescue NPC seen in the last 180 s
  (within 70 yd), TARGETNEARESTFRIEND selects him (verified by GUID); while
  he is selected and the addon says he is within interact distance,
  Interact is pressed with no hover. Never while another unit is the
  soft-interact recipient.
- **Rescue credit:** a rescue Interact waits up to 5 s for the objective
  credit (FAST quest digest or completed objective) and counts it as
  success (live 10:57:08: freed 3.5 s after the press, booked
  `no_response`).
- **Held entity facts:** server entity facts that arrive while the addon
  session/context is still settling (same character, instance and build)
  are held for 15 s and applied once it matches (live 10:57:06: the cage
  holding Professor Cogcatcher was never known and the agent waited).
- **Addon 0.9.71:** the target row carries `interact_near`
  (`CheckInteractDistance(target, 3)`), also in the fast lane and every
  transport tier.

## 2026-10-21 — Server mode never searches the screen

- With `server_mode.active`, SEEK_VISUAL_CUE and INSPECT are dropped from
  every planning cycle (live 10:34–10:35: 45 s of screen search while the
  rescue target was out of server range). Walking the quest area remains;
  with nothing else a WAIT (`server_mode_no_server_option`) is proposed.

## 2026-10-21 — Server-first mode (vision is the fallback)

- `agent/server_mode.py`: `state.server_mode.active` when a Ymir packet
  arrived within 20 s and server entities are in view; shown in the status.
  `AIPC_SERVER_MODE=0` restores vision-first.
- Active: any server-driven proposal (server_* evidence, SERVER_LIVE
  turn-in, server GUID, packet F7, server Tab) silences INSPECT,
  SEEK_VISUAL_CUE, OPEN_MAP and search-cell / minimap-dot MOVEs; a running
  MOVE is no longer stopped by unidentified World3D boxes or learned
  quest-object boxes (server hand-offs and exact mouseover identities still
  stop it).
- Stale or empty stream: everything works as before; vision keeps running.

## 2026-10-21 — Smoother runs, spawn danger, Ymir-filled learned TDB, safe resurrection

Ideas from reading PixelBuddy's controller and path service; own
implementations on our data. All offline-tested; not live-validated.

- **Bend blending:** within up to 10 yd of a route bend the heading leans
  up to 40 % toward the next waypoint. The navigation grants a bend window
  only where the controller's own law, simulated, stays on walkable ground
  1 yd to each side (never over the pit spiral's drop).
- **Strafe trim:** while running, a heading error below the soft-steer
  threshold (2–9°) is trimmed by holding the strafe key for |error|/45° of
  the time; W stays down, facing and camera stay still.
- **Mounted pass radius:** 3 yd instead of 1.5 yd at a bend that is safe to
  blend.
- **Spawn danger:** `world_geometry/faction_templates.py` reads the client's
  `FactionTemplate.db2` (WDC5); `navigation/spawn_threats.py` marks hostile,
  attackable, non-service TDB spawns, learned spawns and live Ymir units.
  Elites, rares and camps of 3+ within 15 yd are avoided on every non-combat
  trip, single mobs only when the trip avoids combat. Quest objective
  creatures, objective/turn-in NPCs and the trip's target are exempt. Detour
  points are joined by navmesh paths and kept only if cheaper with danger.
- **Ymir fills the learned TDB:** every server-shown creature/gameobject is
  merged into `tdb_learned.sqlite3` once per GUID per session (exact server
  position, `source = YMIR_PACKET`), written by a background thread every
  10 s. Quest spawn candidates, role NPCs and route danger read it.
- **Spawn choice by walking length:** the 5 nearest TDB/learned candidates
  are re-ranked by navmesh walking length (`NavigationService.walk_cost`);
  an unreachable one loses to any reachable one.
- **Safe resurrection:** with hostile creatures near the corpse, the ghost
  walks to the reachable spot within 34 yd of the corpse that is farthest
  from them (enough at 30 yd) and resurrects there.

## 2026-10-20 — Take-off and landing spots under open sky (planning only)

- `navigation/flight_trip.py`: a vertical take-off or landing needs open sky
  (no VMAPS surface above). Under a roof/tent/tree the nearest open spot on
  the same walkable layer (MMAPS, ±15 yd) is found in rings up to 70 yd and
  joined by a navmesh walk (≤ 120 yd, ≤ 3× the distance + 15); the shortest
  walk wins. `plan_trip` = walk to take-off, flight, walk from landing.
- Real Waking Shores data: the live 18:43–19:07 spot (roof 15 yd overhead)
  gets a take-off spot 6 yd away; a target in a walled pocket under a pier
  correctly gets none. ~0.1 s per spot once the native navmesh is loaded.
- Idea from PixelBuddy's remote PlanLanding service; own implementation on
  our MAPS/VMAPS/MMAPS. Not used by the agent yet.

## 2026-10-20 — Flight route planner (planning only)

- `navigation/flight_planner.py`: take-off above the start, cruise, land on
  the target. At each candidate cruise height a grid A* goes around
  whatever reaches within 10 yd of it (TrinityCore MAPS terrain/liquid;
  VMAPS models checked along the legs, re-planned on a hit); unknown
  heights are blocked. Heights: low above the endpoints, a few steps up,
  and over everything on the straight line. The fastest wins (horizontal
  yards + 2× climb + descent), so it goes over only when that is faster.
- No take-off or landing under a roof/ceiling.
- `TrinityVMaps.surfaces_above`: the same answer as `surfaces_at(bottom=)`
  for many points at one height, without scanning every spawn per point.
- Real Waking Shores maps: 0.17–0.8 s per route; no surface within 10 yd
  of the cruise height under any flown leg. No flight controller yet
  (ascend/descend bindings, flyable-area and pitch telemetry missing);
  not used by the agent.

## 2026-10-20 — Travel mode: mount only with a real mount and riding

- MOUNT/DISMOUNT moved into one TravelModePolicy (WALK / GROUND_MOUNT /
  KEEP_CURRENT_MODE). MOUNT needs the addon capability (owned mount and
  confirmed riding; unknown fails closed), a usable mount action, a long
  MOVE that no on-foot action outranks, and a safe context (not indoors,
  swimming, falling, in a vehicle, on a taxi, casting or in combat).
- The mount key is the goal's `mount_binding` or an action-bar mount slot
  (`summonmount`, e.g. Summon Random Favorite Mount) that has a key bound;
  dispatch still checks the bindings cache.
- No remount for 20 s after any dismount; a failed MOUNT is not retried for
  30 s within 30 yd. Mounted routes keep the mount; on-foot work dismounts,
  but never while airborne (`movement.flying`).
- The decision and its reason are in the status as `travel_mode`.
- Flying (take-off / cruise / landing) is not implemented: a flying mount
  is ridden on the ground. Not live-validated (the level-10 test warrior
  has no mount).

## 2026-10-20 — Server loot on a bare soft-interact GUID; Tab alternatives; turn step cap

- A corpse the server marks lootable for us (0x4) is looted when the
  client's soft-interact GUID is that corpse, even without a dead flag; its
  walk-up ranks above the next kill walk-up.
- A Tab that selects another current objective mob counts as success.
- The combat facing turn is one input step (≤ 0.34 s); a larger error is
  finished on the next tick.
- Not live-validated.

## 2026-10-20 — Exile's Reach live-run regressions and server-first turn-in

- Combat admission is shared by Planner and Supervisor. Survival candidates
  still pass ordinary availability/cooldown/ranking; quest MOVE/map/dialog
  cannot be restarted under a combat interrupt. Input-free WAIT is not
  cancelled as a new combat start.
- Combat facing/autoattack no longer sends F7 to a foreign soft recipient.
  Use a configured, known harmful action or the existing verified-hover
  attack fallback; preserve the final ID/GUID guard.
- Server corpse position/lootability override stale screen anchors. Confirmed
  own corpses may be approached up to 100 yd (ordinary search remains 40 yd),
  with same-instance/floor checks; corpse approach precedes suspended routes.
- User-directed server-first turn-in: a running quest POI route yields as
  soon as the matching server ender is known. The exact server route is not
  interrupted by visual boxes. Walk/face, then F7 via a fresh exact
  soft-interact GUID, without INSPECT/TARGET first. Wrong/stale recipients
  never authorize F7. Verified height differences prevent cross-floor use.
- A historical ender ID is not a veto over live server evidence. With one
  finished quest and one server reward marker, a replacement NPC takes
  precedence even while the old spawn remains visible. This is a candidate,
  not a confirmed quest/NPC relation: the quest UI must establish the quest
  ID, and a real completion event/receipt must prove turn-in. Multiple
  unrelated quests/markers remain ambiguous. Explicit server no-reward
  status also outranks an old ender location.
- Ghost corpse runs remain navmesh MOVE, never living entrance searches.
  Stuck recovery uses a finite, validated waypoint/replan budget. Death
  notifications are emitted on transitions rather than every control tick.
- Addon 0.9.69 exports bounded persistent QUEST_TURNED_IN receipts on STATE
  and FAST. Reaccepting a quest clears its previous receipt. WorldModel uses
  the existing event reducer/dedupe; verification requires a new receipt for
  the same quest/session/character, not mere disappearance from the log.
- Validation: 1027 selected offline tests pass, including the new live-run
  regressions; Python/Lua syntax and addon mirrors checked. Two recorded
  combat/loot snapshots also replayed through the corrected pure policies.
  No live client input was sent. Full GUI restart and addon update/reload are
  required; live revalidation remains pending.

## 2026-10-20 — Server-first targeting fixes: searches yield, exact combat facing, corpses, big objects

- **Searches yield to server targets.** While the server-position kill
  targeting proposes a walk or a Tab, these proposals are dropped:
  - screen searches (SEEK_VISUAL_CUE, INSPECT);
  - the map search (OPEN_MAP);
  - objective-region, minimap-dot and search-cell MOVEs.
  The server walk-up priority also rises to 100. Live 16:52–16:54 it was
  preempted again and again, a WORLD_YARDS MOVE ranking 20 lower.
- **Exact combat facing.** COMBAT turns toward the selected mob by its exact
  position (server, else the addon's target world position):
  - first, when the mob is more than ~70° to the side or behind;
  - and in answer to "facing the wrong way", turn + attack, before the blind
    sweep.
  Live 16:46–16:47 had `facing_wrong_way` ×3.
- **Corpses.** A mob the addon names dead or "Corpse", or one that an ideally
  placed Tab did not select, is skipped (dead 10 min, Tab miss 2 min). Live
  17:03:10 Tab aimed at a murloc corpse killed by someone else.
- **Big objects** (Catapult Destruction):
  - A walk that stops getting closer within 8 yd of a quest object, without
    turning, has met its edge; the reach is learned per object and entry.
  - F7 is tried from that edge, and later objects of that entry are
    approached only that far.
  - A use from a learned reach that brings no credit forgets it.
  - Decorations (generic, trap, spell focus) no longer block the Interact
    key.
- Not live-validated.

## 2026-10-20 — Server targeting for "collect the drop" objectives

- A COLLECT objective whose quest item drops from creatures now uses the same
  server targeting as KILL. Example: Murloc Mania, "First Aid Kits recovered
  from defeated Murlocs" drop from murlocs 150228/150229.
  - Walk to the mob's server position and face it.
  - Tab with the server nearest-ahead check, then verify the GUID; COMBAT
    takes over from there.
  - Loot the corpse the server marks lootable.
- Vendors and containers are not targets.
- Not live-validated.

## 2026-10-20 — Quest mobs and own corpses by server position; smoother routes

- **Kill targets.** Out of combat the agent walks toward the nearest live mob
  that an open KILL objective names and faces it. The mob comes from the
  objective's credit entry, the TDB named creatures, or creatures whose
  KillCredit gives that credit (e.g. "Harpies and cohorts slain": Harpy
  Snatchers, Ambushers, Hunting Worgs).
  - Tab is pressed only when the server shows exactly that unit as the
    nearest one straight ahead, within 20 yd on our level.
  - The new target must carry that GUID, so a wrong pick is never attacked.
  - The agent then closes in until a harmful action is in range and COMBAT
    takes over.
  - Lootable corpses, service NPCs and "[DNT]"/credit proxies are never
    targeted.
- **Loot.** A corpse the server marks lootable for us (unit flag 0x4) is
  walked to and faced. Interact is pressed only when the client's
  soft-interact unit is exactly that corpse, at most 2 presses per corpse.
- **Smoother routes.** While running, a route bend up to ~77° is taken with
  forward and turn held together instead of stopping to turn in place. The
  running state carries over to the next route leg. Sharp hairpins, a fresh
  start and points right beside a final destination still turn in place. No
  corner is cut early, which keeps the pit spiral safe.
- Not live-validated.

## 2026-10-20 — Rescue an NPC by opening what holds it

- "X rescued / freed / released / saved" objectives no longer rely on the KILL
  search alone. When the server shows the named NPC inside a door, button,
  chest or goober within 2.5 yd, the agent:
  - walks to the object's exact position and faces it;
  - presses Interact once per attempt, out of combat, with no unit as the
    soft target.
- Example: Explorers in Peril, Professor Cogcatcher in the Protodragon Rib
  Cage.
- A per-player Activate flag is no longer required for such an object. It
  marks a quest highlight, not usability.
- Not live-validated.

## 2026-10-20 — Scripted rides, turn-in after a blocked quest, vendor objective NPCs

- **Scripted ride hold.** When an objective NPC turns into a client-scene
  actor of the same name right after Interact, the agent waits in place until
  the ride sets it down or credits. Example: Ralia Dreamchaser, Who Lurks in
  the Pit. A WAIT_EVENT may ask for a longer window (`wait_seconds`, at most
  90 s).
- **Goal tasks.**
  - Quest-level tasks are keyed by quest and purpose, so a failed floor-cue
    walk no longer blocks the turn-in walk for 120 s.
  - Any quest progress lifts that quest's blocks.
- **Server NPC walk-up.** Vendor, repair, trainer, innkeeper, flight-master,
  banker and stable-master objective NPCs qualify too. Example: Repair
  Yourself, Quartermaster Richter, server flags 0x1280. An open vendor window
  stops further presses.
- Not live-validated.

## 2026-10-20 — Pit cocoons in spiral order, no walking past, no double press

- **Next object.** The next server quest object on another floor is ranked by
  walking cost (horizontal distance + 3 × height difference) instead of
  straight-line 3D. From the top Pit cocoon this is the next spiral level,
  not the bottom cocoon right below. The search radius is now 150 yd.
- **Stop for an object on the way.** A walk to a quest object now hands back
  to the planner when:
  - another usable objective object on the same level comes within 6 yd;
  - its target is spent or removed;
  - without Ymir, the cursor is on a quest-tooltip-certified object at a
    spawn in use range.
  Live 09:36–09:37: the walk passed two cocoons at 4.5 and 2.1 yd.
- **No double press.** A credited server object is not pressed again for
  60 s, even if the server has not removed it yet. The quest log credit
  arrived 0.7 s before the removal.
- Tests: `tests/test_pit_cocoon_order_20261020.py`. Not live-validated.

## 2026-10-20 — Quest pickup walks up to the server "!" giver too

- `ServerNpcInteractionPolicy` now also takes units the server shows with a
  "!" (or a yellow "?") within 30 yd. The agent walks to their exact server
  x,y,z, faces them, and presses F7 only when the soft-interact GUID is that
  giver, so a vendor standing beside the giver is never pressed.
- Farther side givers stay with the campaign-first map-POI policy.
- Live 2026-10-20: pickups so far used the server "!" on the selected NPC
  (seven times); the exact-position walk-up is new and not live-validated.

## 2026-10-20 — Own height and turn-in NPC position from the server

- **Own position** (user: "we know our own x,y,z from the server too"):
  - Own movement packets now mark the height `z_observed`. Before, only
    `z_known` was set, which the Z resolver ignores, and the newer addon
    sample replaced the packet position almost always.
  - While the addon x/y stays within 0.75 yd of the last own movement packet,
    that packet's z is kept as an observed height
    (`PACKET_CLIENT_MOVEMENT_HELD`). This targets the guessed-layer failures
    ("ambiguous player layer after fall").
- **Turn-in NPC** (user: "near the turn-in we know the NPC position too"):
  - The resolver uses the server position of the known ender entry (TDB,
    learned or remembered) even without a yellow "?" status. A unit the server
    marks as only in progress for us is skipped.
  - `ServerNpcInteractionPolicy` also walks up to the enders of finished
    quests, faces them and presses F7 on a soft-target GUID match.
- New tests: `tests/test_server_positions_20261020.py`. Not live-validated.

## 2026-10-20 — Objective NPCs by server position; scripted rescue events

- **Live result:** the server-identified totem use worked; Purge the Totems
  was completed with four verified credits.
- **`objective_named_unit`:** a quest-linked friendly unit named by an open
  objective is relevant even when the objective is a KILL.
  - Live case: Meredy Huntswell, whose rescue starts by talking to her.
- **Scripted-event hold:** after a SCRIPTED_COMBAT gossip option has started
  a fight, a bounded WAIT_EVENT keeps the agent in place between waves until
  the quest credit arrives.
- **New `ServerNpcInteractionPolicy`** (user request):
  - walks to the exact server x,y,z of a talkable NPC that an open TDB
    objective names, and faces it;
  - presses F7 only when the soft-interact GUID is that NPC;
  - never runs in combat.
- New tests: `tests/test_scripted_event_meredy_20261020.py`. The Meredy event
  is not yet live-validated.

## 2026-10-20 — Quest objects usable by the client's quest tooltip (no Ymir needed)

- **New `QUEST_OBJECT_TOOLTIP` identity certification** for a hovered game
  object. It requires:
  - no GUID and no object ID;
  - `quest_related` with the objective's quest id;
  - the objective object name (falling back to the TDB reference
    objectives);
  - a quest object spawn within 4 yd;
  - no combat.
- It is shared by the planner, skill availability, ObjectUseSkill and the
  command guard.
- A certified object counts as at hand even when its quest is not primary.
- Live 2026-10-19/20: every Harpy Totem was hovered with the exact quest
  tooltip but never used, because input demanded an object ID that Retail
  never exposes. A telemetry replay now chooses the use at all three totems.
- New tests: `tests/test_quest_object_tooltip_20261020.py`.

## 2026-10-20 — Entity backlog restamp (login creates no longer lost)

- `SnapshotReplayForwarder` re-sends, stamped now, any entity fact that is
  older than the open runtime context and was therefore rejected. This
  covers CREATED, POSITION, FLAGS, QUEST_GIVER_STATUS and REMOVED.
- Live 08:16: the Ymir stream reads the PKT from its first record after PID
  binding, when the context is already open. The context-change replay had
  fired on an empty snapshot, and the totem creates were then dropped one by
  one.
- Reproduced: 0/19 creates before the fix, 19/19 after. A regression test
  was added.

## 2026-10-19 — Server-identified quest objects (totems/cocoons) and login entity replay

- **Diagnosis** (live 15:23–15:25, Purge the Totems): three totems were
  reached but none was used.
  - GameObject hover identity can never pass: the addon gives `object_id 0`.
  - The login creates were dropped before the packet context existed.
  - Non-primary objectives were skipped.
  - The only F7 ran in combat, and its cast was broken after 0.26 s.
- **`EntitySnapshot` / `SnapshotReplayForwarder`:** the Ymir bridge re-sends
  the current entity facts, freshly stamped, to every new runtime context.
- **OBJECT_USE `INTERACT_KEY_PACKET`:** the server GUID plus the live-verified
  GO Activate flag (0x4) identify the objective object.
  - The press needs ≤3.5 yd, facing, no unit soft target, no nearer object
    and no combat.
  - `server_object_recipient` guards the command.
  - Otherwise the agent walks to the exact server position and faces it.
- **Planning:**
  - a server-usable object ≤12 yd is worked even when its quest is not
    primary;
  - the soft-target F7 waits for combat to end.
- **Fix:** server GUIDs in MOVE params moved from `target_guid` (cancelled by
  navigation as a selected-unit approach) to `server_entity_guid`. This also
  affects the giver and turn-in moves added earlier today.
- New tests: `tests/test_packet_object_use_20261019.py`. Not live-validated.

## 2026-10-19 — Planner uses server quest markers; dialog stall and focus diagnostics

- **QuestGiverStatus fix (from the 14:47 live run):** the plain `*Reward`
  bits (0x2000–0x80000) are the grey in-progress "?" and are now
  `quest_incomplete`. `reward_ready` is only RepeatableTurnin or
  `*RewardComplete*`.
- **New `agent/packet_entity_facts.py`:** read-only helpers over
  `state["packet_entities"]`.
  - Create positions and arrived spline destinations now stay valid until
    the unit moves or is removed, so standing givers keep their position.
- **Planner wiring:**
  - friendly-NPC relevance follows the server marker, or the missing
    QuestGiver NPC flag, before vision, pins and memory;
  - API "!" pins are replaced by the exact server giver GUID and position;
    server givers without a pin become pickups;
  - a selected server "!" unit is spoken to, and soft-interact skips empty
    units;
  - the turn-in resolver targets the server yellow-"?" ender;
  - remembered-offer and post-turn-in re-talks are dropped when a newer
    server marker shows no "!".
- **Dialog stall fix:** a CONTINUE/COMPLETE/TURN_IN panel with no button
  point is treated as an empty NPC window and closed after 6 s (live
  14:47:53: 55 s stall).
- **Focus-loss diagnostic:** the runtime records the foreground owner's PID
  and executable name (no title) in `foreground_loss` when WoW loses focus,
  and marks the 15 s MANUAL demotion.
- New tests: `tests/test_packet_planner_20261019.py`. Not live-validated.

## 2026-10-19 — SMSG_UPDATE_OBJECT entity lifecycle from the pinned WPP layout

- **Source download (user-authorised):** the WowPacketParser source at the
  pinned commit 1a72288 was downloaded to `..\_external\wpp-src` (outside the
  project) and read as a specification only.
  - No code was copied and nothing from it runs.
  - Its V12_1_5_70340 opcode table matches the pinned hash.
- **New reader `packetio/update_object.py`:**
  - It reproduces WPP's bit-reader semantics and reads SMSG_UPDATE_OBJECT:
    create blocks (full movement block, ObjectData, leading UnitData /
    GameObjectData fields), destroyed / out-of-range lists, and the
    dynamic-flag part of values updates.
  - SMSG_ON_MONSTER_MOVE is now parsed in full: spline start, first point and
    move time.
  - A record that does not end exactly where the layout says yields nothing.
- **Validation on the real 70448 dump:**
  - All 389 update and 531 monster-move records parse exactly.
  - 0 GUID / EntryID mismatches.
  - NPC flags agree with the TDB.
  - 166/175 spline destinations match the next spline start.
- **New allowlisted events:** ENTITY_CREATED, ENTITY_REMOVED and ENTITY_FLAGS,
  plus destination / move time on ENTITY_POSITION.
  - Only creature, vehicle and game-object GUIDs are emitted.
  - Health, power and cooldowns are intentionally not decoded (secret values
    for the addon).
- **WorldModel `packet_entities`:**
  - Now carries create info, raw dynamic flags, removal, distance and a
    linear spline estimate.
  - Server "!"/"?" quest givers come first, then the rest nearest-first.
- Dynamic-flag bit meanings and planner use are not validated or wired yet.

## 2026-10-19 — Server-side creature facts from Ymir 70448 packets

- Decode SMSG_ON_MONSTER_MOVE (spline-start world position) and
  SMSG_QUEST_GIVER_STATUS(_MULTIPLE) (uint64 status grouped into
  available / reward / trivial / future) for the 12.1.5 family only.
  Layouts were checked byte-exact on a real 70448 Ymir capture. They carry
  their own `RETAIL_70448_CAPTURE_VERIFIED_V1` provenance, which cannot
  confirm any other event kind.
- Player and pet GUIDs never become entity facts. SMSG_MOVE_UPDATE, which
  carried only player movers in the capture, stays undecoded. Transport-
  relative, zero and non-finite positions and trailing or truncated bytes
  are rejected.
- WorldModel keeps a bounded `state["packet_entities"]` table:
  - keyed by the addon UnitGUID string; the conversion was confirmed by
    the same session's addon log;
  - limited to the current world map;
  - position kept ≤ 60 s and quest-giver status ≤ 900 s;
  - cleared on session, character or world-map change, but kept across
    UI-map steps.
- The inbox coalesces entity positions per GUID. These are facts, not
  derived events or input authority. Planner use is not wired yet, and
  nothing here is live-validated.

## 2026-10-19 — Quest availability first and conditional agenda continuity

- Preserve API questgiver MOVE attention instead of regenerating unrelated
  UNKNOWN SEEKs. An empty known quest log with no usable local quest cue
  requests map discovery before random-body inspection; existing bounded
  local-cue handoff, input authority and map anti-churn limits remain.
- Addon 0.9.68 refreshes quest-line availability immediately after meaningful
  quest changes; async replies reread pins without requesting recursively.
  Both Retail packages remain identical; installed addon was not overwritten.
- Extend Planner's existing agenda through offer, live quest read, work,
  turn-in and next-quest discovery. Empty-log discovery and verified turn-in
  continuity no longer disappear. Future steps retain evidence dependencies,
  expected results and failure/missing-evidence replanning branches.
- Availability/UI changes refresh the plan immediately. Existing proposals,
  keys, binding/identity checks, canonical skills and verification remain the
  only execution path; optional LLM is not required or enabled by this change.
- New focused regressions and a read-only comparison of 71 actual post-pin
  snapshots pass. New source is not yet live-validated; initial approach and
  turn-in irregularities remain open in LIVE_VALIDATION.md.
- Final related regression: 184 modules, 1818 passed, 2 optional-image skips,
  one pre-existing cave short-probe failure. Python/Lua syntax, addon mirror
  equality and preservation of all numbered coverage IDs verified.

## 2026-10-19 — Exact quest-item readiness and Giant Boar range recovery

- Preserve near F7 item use, but require fresh exact public item range,
  usability, cooldown, selected GUID and current recipient. Unknown authority
  falls back to a verified item UI/armed-cursor click, approach or safe wait,
  not attacking the item subject. Addon 0.9.67 / Interface 120100, mirrored.
- Keep compact item/recipient evidence on bounded FAST with original clocks;
  omissions and inaccessible values remain unknown. No client memory/secret
  bypass or hover XYZ. Exact item TARGETs reuse the current-cursor fast path;
  a matching selected item subject no longer loses local work to zone sweeps.
- User's subsequent 0.9.67 recording shows Re-Sizer 0/3 -> 3/3, turn-in 56034
  and acceptance of 55879. It also exposes the separate Giant Boar no-motion
  interaction loop; final recovery changes are not yet live-validated.
- Range recovery now carries real forward-step requirements, does not reuse
  combat range for NPC interaction, and does not replay old UI errors as new
  feedback. Each interaction retry has a fresh response timer/error fence;
  original quest/attempt baseline, ID checks and safety budgets remain.
- Targeted tests pass offline. Final combined results and the separately
  existing cave short-probe failure are documented in LIVE_VALIDATION.md.
  No assistant-operated client input/FULL_AI or installed-addon deployment.
- Final related regression: 1778 passed, two optional-image skips, one known
  pre-existing cave probe failure; 179 modules. Python/Lua syntax and addon
  mirror equality passed. Giant recovery still needs a new user live test.

## 2026-10-18 — NPC hover/turn-in feedback and route handoff (offline-tested)

- Addon 0.9.66: protect the STATE/FAST pixel frames from hover-tooltip text
  using explicit draw levels; frames do not intercept mouse/motion input.
  No telemetry strip resizing, tooltip hiding or per-frame layer jitter.
- TARGET uses fresh current-world handoff proof. The first HOVER also gets
  a bounded feedback hold; paged STATE can reply before another pointer move
  invalidates it. Exact ID/GUID, original clocks and deadlines are preserved.
- Same unknown visual cue cannot immediately cancel the same quest route
  repeatedly; bounded per-route/session suppression does not block a fresh
  matching public NPC-ID handoff or a different cue.
- Consume terminal anti-loop supervision before admitting a replacement skill,
  avoiding cancellation of a new TARGET for the previous attempt's signal.
- User's second PID-8364 recording and remaining live checks are documented in
  LIVE_VALIDATION.md. All new behavior still requires user-operated live
  validation; no assistant-started FULL_AI or client input.
- Regression: 1744 passed, 2 optional-image skips, 1 previously OPEN cave
  short-probe failure reproduced with pre-patch sources. Lua compilation,
  Python syntax and addon package equality passed.

## 2026-10-17 — Shared entity identity at skill boundaries (offline-tested)

- Addon 0.9.65 preserves typed object_id in mouseover, target and soft-target compact projections, including bounded FAST profiles; exports public quest-UI owner GUID when available. Primary and versioned packages are kept equal. No installed-addon deployment was performed.
- Share ID/GUID comparison and per-attempt pins across target, interaction, combat, loot, quest object/item/spell/extra-action and targeted vehicle boundaries. Names/tracks cannot override known IDs; fresh pointer proof is required for a world click. Known soft-interact recipient must agree before F7.
- Keep GUID-less GameObjects actionable through a real fresh object_id; do not invent GUIDs or turn historical name-only Cocoon samples into numeric proof. Missing both remains inspect/search-only. Blind F7 at a remembered spawn is removed.
- Keep original sample clocks, clear omitted soft recipient authority, preserve immutable observations and bound entity-directed visual/navigation motion after identity loss, including intermediate waypoints. UI-only/coordinate/self actions retain their own contracts; no-input quest credit may verify after despawn.
- The earlier moving-target current-cursor fast path remains. No hover world XYZ, process-memory inspection, injection, secret bypass or new running-skill owner was introduced. The user operates the next live test after addon update/reload and GUI restart. See `docs/ENTITY_IDENTITY.md` and `docs/LIVE_VALIDATION.md` for scope, tests and limits.
- Final report checked 2026-10-18: **1679 passed, 2 skipped, 1 explicitly deselected**, 171 related test modules, zero executed-case failures/errors. The separately OPEN probe-route test remains excluded, not fixed. Final Python/Lua syntax checks and addon mirror equality pass; live validation remains open.

## 2026-10-16 — Murloc acquisition and COLLECT zone continuity (offline-tested)

- Evening moving-target follow-up: consume exact fresh cursor/GUID proof once instead of re-hovering the predicted bbox and awaiting another sensor roundtrip. Keep stale/displaced proof on hover recovery; selected GUID still verifies success. Bound pointer-feedback waiting so continuous following cannot forever advance the confirmation barrier. The 25 Hz / 60 ms synthetic case now clicks at +120 ms; live latency remains unvalidated after this follow-up.
- Let fresh, coherent addon-confirmed quest hostiles interrupt search/navigation using the existing generic objective/tooltip rules, not an exact full-name substring. The canonical runtime cancels MOVE and replans TARGET; the fast lane only releases movement and yields to it. A found unit is not falsely booked as region arrival.
- Give full STATE identity/cursor samples their original packet time, as FAST already does. Preserve explicit old/unknown times and use the same rule in the parallel view; never turn receipt time or an omitted field into fresh click evidence. Exclude players from generic NPC identification and enforce declared hostility.
- Retain verified COLLECT-region arrival through item-count increases and use navigation's eight-yard arrival radius before bounded local search / existing zone sweep. Changed destinations and map/instance mismatches do not reuse the arrival; quest credit remains authoritative.
- Replay of all three actual murloc hover snapshots now reaches SEEK identity -> correct TARGET offline. The user operates the next live test after GUI restart; no new live run, client input or whole-quest success is claimed. A pre-existing ambiguous-floor probe-route test is separately reproduced and remains open; see `docs/LIVE_VALIDATION.md`.
- Final related regression including moving-target follow-up: **1343 passed, 2 skipped, 1 explicitly deselected** (the pre-existing probe-route failure); a further real-launcher recording-only integration test passed separately. Ten touched production modules parse successfully. Latest user-operated agent status at handoff: selected PID 12384 STOPPED/disarmed, no held keys.

## 2026-10-16 — STATE / quest UI / SPEAK identity and verification corrections

- Keep vertical FAST discovery out of the primary STATE cache; recover old polluted caches and hidden STATE origins, retain bounded rediscovery and continue known FAST decoding through capture/sensor throttles.
- Preserve co-sampled FAST button evidence (session, sample/receipt, action, quest, point). Only exact fresh CONTINUE/COMPLETE/TURN_IN may bypass stale paged detail; both admission and canonical dispatch recheck it. Detailed acceptance/list/reward decisions remain guarded.
- Recognize `Ask NPC to ...` without an LLM, share conservative whole-token short/full NPC matching across acquisition/location/interaction/gossip, reject explicit-ID mismatch, player/dead/hostile and known ambiguous names. Do not reinterpret resolved SPEAK as raw KILL-area roaming.
- Distinguish conversation quest progress from scripted fight initiation. Verify with canonical quest credit; following a script's spawn-GUID replacement, issue no further input/rebinding while waiting within the existing deadline. The actual live recording verifies delayed credit at +9.383 s after the option.
- Bounded selected-PID live trial obtained Meredy's option 50819, transformed the player, advanced 55981's first objective 0/1 -> 1/1 and began the next objective route. Initial position/selection were pre-existing; no manual in-game assistant input. The final GUID/phasing verifier follow-up is offline replay/test verified only, not a second live run or a completed whole quest. Agent/GUI stopped and disarmed with no held keys. See `docs/LIVE_VALIDATION.md`.
- Final related offline regression: **801 passed**, exit 0; syntax validation passed for all 18 touched Python source modules.

## 2026-10-15 — Parallel pump now starts through the real SensorHub (offline-tested)

- The two evening runs never started the independent fast lane: production wrapped BufferedPixelSensor in SensorHub, but the hub exposed no non-consuming `peek_latest`; startup silently returned False. Reproducing tests fail with both wrapped stacks before the fix while the old direct-sensor test passes.
- Forward primary producer snapshots without polling, stealing medium transitions or re-stamping receipt. Explicit capability plus stale/future/failure/closure gates keep unsupported or dead sources from authorizing input.
- Added `parallel_control.pump` startup/liveness/error diagnostics, single-start protection and accurate disabled/stopped final status. Existing user startup prints are retained. No second planner, active skill, navigation or executor was introduced.
- Related offline regression: **303 passed**, including the real wrapper, capture factory, threaded blocked-medium control, MANUAL lifecycle, safety and M0/M1 paths. The user restarts the GUI and operates the next live test; no assistant-started live FULL_AI/input or claimed live FPS improvement. See `docs/PARALLEL_CONTROL_DESIGN.md` and `docs/LIVE_VALIDATION.md`.

## 2026-10-15 — Actual 70391 packet build and top GUI receipt status (offline-tested)

- User-run inspection found 12.1.5 build 70391 rather than the earlier reported 69587; the old family gate explained the inactive context and zero accepted packets. Added a separately pinned 70340/70391 family, not a 69214 fallback. All 106 bundled identifiers match both pinned full tables; manifest/semantic provenance remains family-specific and unknown builds are rejected.
- The upper detector line now displays packet receiver status and recent actual receipt separately, including unsupported build/errors, no data, receiving count, pauses and closure. Receipt ages on the GUI clock, and old-context receipt cannot make a new context look active. No IPC key/raw payload is displayed.
- The existing `tools/run_packet_sidecar.py` CLI remains the separate explicitly sourced sender; GUI BATs enable only the inbox. Related offline suite: 211 passed / 1 deselected, plus the real-localhost round-trip passed separately. Live capture, first real receipt and GUI rendering after restart remain unvalidated; no assistant-started client input or FULL_AI.

## 2026-10-15 — Audited packet sensor port into current architecture (offline only)

- Audited the older workspace's packet package, then integrated it into current runtime observation/lifecycle/diagnostics and WorldModel reducers instead of overwriting runtime/world/gui. Source files remain unchanged; fresh agenda, parallel control and tracking paths are preserved.
- Explicit pinned WPP 69214 opcode family includes the reported 69587 build; no arbitrary nearby-build fallback. Corrected packed combat GUIDs, attack-error bit order, NEW_WORLD floor fields and world-map/UI-map separation. Unparsed data stays UNKNOWN and only reviewed prefixes can become semantic evidence.
- Added authenticated local runtime/addon-context IPC, age/order/PID gates, bounded per-mover coalescing and queue diagnostics. Only fresh exact own-Player outgoing movement can enrich XYZ/facing without changing addon map/instance. Packet receipt grants neither addon liveness nor loot ownership. Packet observations are ephemeral rather than repeated SQLite rows.
- Corrected TCP overlap/wrap/reconnect bounds and PKT rotation/codec reset/Windows file-handle lifetime; sidecar descriptor reads and parser compaction are bounded. The runtime option defaults off; the user's later request explicitly enables the inbox in START_AGENT / DXGI / LIVE_VISION BATs. This does not arm FULL_AI, launch capture or install Npcap. See `docs/PACKET_TELEMETRY.md`; UPDATE_OBJECT/HP/power, broad quest/loot parsing and live validation remain open.
- Verification: broad related suite 1084 passed / 1 skipped / 1 deselected; full packet-specific loopback-enabled suite 84 passed; final focused metadata/launcher/runtime/GUI/architecture check 170 passed / 1 deselected (overlapping cases, offline only). Source-workspace files and user gameplay were not modified.

## 2026-10-15 — Conditional quest agenda, TDB/SQLite look-ahead and fast target forecasting (offline-tested)

- Planner retains an inspectable multi-step quest agenda while the existing single skill runs: real offers → verified acceptance → objective strategy/work → verified completion → ordered turn-ins → check continuation. Same-area cohorts can defer a distant hand-in while other executable work remains; known different cave levels stay separate. An unavailable preferred task yields to an existing available alternative, without bypassing anti-loop keys or inventing input. Local object use, combat, loot and modal UI do not lose priority to a boosted search.
- Existing read-only TDB and learned SQLite knowledge prepare ender regions and explicit next-quest starters. Real gossip offers now also get bounded reference read-ahead; an objective area may be previewed before acceptance, but work stays blocked. Static chains remain `REQUIRES_LIVE_AVAILABILITY`, not permission to accept. Field/automatic/special completion does not fabricate an NPC return trip.
- The existing optional SemanticAdvisor can asynchronously suggest only supplied task-ID orderings. Dependency/invention checks and deterministic fallback remain; an LLM answer never changes quest truth or the active target. A bounded, hypothetical 24-step route rollout leaves all real statuses untouched; navmesh still owns actual movement.
- Target prediction now fits fresh fast-frame screen motion, suppresses reversal/jumps/occlusion/camera/epoch changes and leads pointer aiming within fixed bounds. It neither reassigns IDs nor authorizes clicks. Status and live-debug expose `grounded-quest-agenda-v1` and `bounded-target-motion-v1`. See `docs/QUEST_AGENDA_DESIGN.md`; new user live validation is required, and the unplugged low-FPS run is not a benchmark.
- Bounded TDB spawn views reserve typed role/objective groups before proximity fill, so many nearby objective spawns do not automatically hide a distant ender. Final related offline regression: **996 passed, 1 skipped**; no assistant-operated live test or real local-LLM answer validation is claimed.

## 2026-10-15 — Shared fast control channels, advisory recognition off the hot path (offline-tested)

- A live-only independent pump advances the existing active approach/search/target/interaction/combat/loot/object-use FSMs alongside track-bound pointer following, not just MOVE. It uses non-consuming fresh sensor/perception snapshots and the original ActiveSkillRuntime, NavigationService and dispatcher. Busy canonical ownership never creates another controller; stale input still expires. Matching terminal results return to the medium engine once for normal verification/bookkeeping.
- The medium loop retains fusion/safety/planning but does not duplicate a recently fast-driven FSM on lagging state. Short atomic resource leases prevent attention from stealing the interaction mouse. Cast/channel holds locomotion/turning while verification can observe progress; UI, fall, combat, context, focus and stale-sensor boundaries stop/yield safely. No blanket non-blocking click or instant-spell assumption was added.
- Live advisory visual recognition runs in a bounded background reader with one-second per-track/epoch caching. Offline direct-step callers remain synchronous. Diagnostics and live-debug expose `shared-fast-channels-v1`, actual parallel control/pointer cadence, resource ownership and the recognition queue separately from the medium runtime poll rate.
- Delayed item-target hover-confirm commands now reach the shared dispatcher instead of being dropped by the generic pending-result projection. Object/item pre-click stages do not advance during cast/channel while their input is held. The live medium decision clock is refreshed after projection without restamping samples or repeating a newer fast FSM update. Final related regression: **950 passed, 1 skipped** (offline only).
- `projekt_parallel` was used as a reference, not overwritten or copied over current fixes. Full agenda/pass-through navigation and all-skill live acceptance remain open. The user explicitly excluded the unplugged low-FPS 16:45 run as a representative benchmark. See `docs/PARALLEL_CONTROL_DESIGN.md` and `docs/LIVE_VALIDATION.md`; a new GUI and user-operated normal-FPS run are needed.

## 2026-10-15 — Track-bound mouse following, Henry re-hover recovery, thin STATE strip (offline-tested)

- Active visual approach, visual search, explicit-target MOVE/FOLLOW/REACH and World3D INSPECT follow their committed live track with pointer-only updates, capped at 30/s. Nested interaction/loot navigation also retains its target. Pointer updates use the existing dispatcher and do not replace forward/steering updates or release the movement lease. TARGET/LOOT/item-target hover confirmation, INTERACT and object-use confirmation follow their own live box while awaiting addon identity; clicking still requires a post-hover/post-follow sample and bounded deadlines remain.
- Lost/coasting/stale/self-player boxes, changed selected GUIDs, client safety blocks and open interaction/map UI do not authorize new following. Object persistence is not permission to aim at an old box. Existing screen-motion lead and object-lock turn compensation remain; no new detector, tracker, input owner or named-NPC shortcut was introduced.
- The Henry run's rejected track can now be re-probed at a fresh selected-GUID-bound position. The old remembered cursor point expires; matching fresh mouseover at the new probe, not the remembered World3D binding alone, authorizes resuming movement.
- Addon 0.9.64 makes the top-left STATE lane up to 384 columns of 3 px cells: 1152×33 instead of 512×132 physical pixels at 1600×829 (about 44% less area). Its 1024-byte page capacity, changed-byte painting and independent right-side FAST lane are unchanged. The YOLO mask is shallower; small-window legacy transport remains supported. Six-resolution Lua drawing→pixel decoding regressions pass. Both addon packages and the installed Retail addon have matching four-file hashes. Restart the GUI and reload the addon for user live validation; offline tests are not a live quest result.

## 2026-10-15 — Returning V3 source retains its identity after an alias conflict (offline-tested)

- In the 14:21 user run, raw rebindings were 37 versus 908 previously (~94% fewer per detector frame), supporting the preceding label-family correction. A separate failure remained: a new nearby source inherited an absent subject's ID and kept it when both sources became visible.
- Simultaneously visible upstream aliases now reserve the existing raw track for its earliest remembered visible source. Stable presentation also lets established live raw owners claim their objects before newcomers. A reproduced V3:830/V3:923 identity-transfer regression fails before the change and passes afterward; related suite: 138 passed, one skipped. The new fix needs a GUI restart and user live validation. Own-avatar feed-ID changes on box deformation and long-offscreen NPC ReID remain open.

## 2026-10-15 — Raw World3D V3 subject family continuity (offline-tested)

- The user-run PID 20864 held several `V3` IDs for minutes, but its raw World3D layer still created fresh tracks for the same upstream subject; final diagnostics recorded 908 upstream rebindings. One reproducible mechanism was a canonical `obstacle_candidate`/`unknown_subject_candidate` label flip on a V3-backed semantic subject.
- Source-local association now uses a stable subject family for this narrow case while preserving the actual `detector_kind` in output and detector votes. Two nearby, distinct V3 subjects remain separate. The reproducing regression failed before the fix (five raw births for two subjects) and passes afterward (two births); 137 related tests passed, one skipped. This does not prove all 908 rebindings are resolved or establish long-offscreen named-NPC ReID. A GUI restart and user-operated live retest are required.

## 2026-10-15 — Pre-boar tracker test (PID 1296): feed continuity versus displayed-ID churn

- In the user-run FULL_AI test, only the 116 s before mounting the Giant Boar were assessed for track identity. The feed processed 3,167 frames (~27.3 Hz), stayed in one generation at 920×518, and had two near-identical consecutive-frame ID switches. Both were the own-avatar box crossing the screen-anchor bottom threshold by one pixel (`V3:9` to `V3:3` and back); a narrow recent-anchor continuation gate fixes this case in geometry replay (18/18 affected frames versus 1/18 before).
- The downstream displayed `WORLD3D` ID for the same `WORLD3D_V3:9` nonetheless changed multiple times (`14`, `8`, `102`, `273`, `283`, `439`, with brief later alternates). The raw and displayed ID spaces must not be conflated. A concrete cause is that a V3 subject candidate alternated canonical `obstacle_candidate`/`unknown_subject_candidate` labels and the stable layer treated these as different object families. A V3-backed semantic subject now stays in the subject family even with the obstacle detector label; unrelated obstacles retain their original family.
- The 26 s absence of this candidate from sampled agent telemetry and brief same-upstream duplicate presentations are not resolved by that narrow fix. Neither this replay nor the 104 passing related tests is a new live validation. NPC long-turn ReID remains open; the measured V3:9 was the own avatar, not proof of named NPC continuity.

## 2026-10-15 — Long live tracker run: screen-anchor hopping (offline-tested fix)

- PID 10348 produced 14,608 feed frames in 556.65 s (~26.2 Hz) across four generations; the final generation held 12,924 frames. The main-generation tracker ended with one screen anchor and only two exact-box rebindings, but the feed trace still had 254 near-identical consecutive-frame subject ID switches. Of those, 249 involved the screen-anchor selection. Downstream diagnostics still reported 105 upstream rebinds and 617 duplicate merges; visual ID continuity is **not live-validated**.
- The anchor's old centre-first choice hopped between upper NPC and lower avatar boxes. A 96–99 px height fluctuation around the old 15%-of-frame gate also toggled anchored/native assignment. The gate now requires a lower box with a tolerant 12% height minimum, prioritizes the bottom-most plausible subject, and keeps a recent overlapping anchor rather than hopping to another NPC during a one-frame dropout. Reset/invalidation clears the anchor history.
- Geometry-only replay of the recorded detections reduced large selected-anchor box jumps (IoU < 0.5) from 369 to 30, while anchor on/off transitions rose from 386 to 453 due to the deliberate one-second fail-closed hold. This replay does **not** rerun YOLO/MOT or prove live ID stability. Related regressions: 89 passed. Long-gap NPC ReID and downstream object churn remain open.

## 2026-10-15 — Screen-anchor cardinality after second user track-ID run

- The user-run PID 16548 trace had 1,778 feed frames in one generation. Five near-identical consecutive-frame boxes changed feed IDs; four were subjects flanking the own avatar, and the fifth was a symbol whose previous ID was simultaneously used by a different box. `exact_box_rebindings=0`, so this run does **not** validate the preceding exact-box patch.
- The two flanking subjects and the avatar all passed the broad positional screen-anchor gate. Anchoring all three removed the NPCs from native BoT-SORT and allowed ID alternation. The feed now selects at most one best-centred/lower subject for screen anchoring; other subjects stay in the native tracker. Diagnostics expose `screen_anchor_candidates` separately from the selected `screen_anchored` count.
- A regression using the live box coordinates plus related vision/feed tests pass (88 total). This new change is **offline-tested only**; live track continuity and long camera-turn ReID are still open.

## 2026-10-15 — Same-box feed ID alternation (offline-tested fix)

- The user-run PID 10668 feed trace shows `V3:437` and `V3:445` alternating on virtually the same visible box in 35–70 ms, without a mid-run World3D reset. Native BoT-SORT assignments and tentative fallback publication alternated; the downstream object often retained one ID but repeatedly rebound its upstream source.
- The feed now reconciles two public IDs only for one unambiguous, same-family, appearance-compatible box with at least 0.90 IoU on the immediately preceding frame (maximum 0.15 s), never for simultaneous boxes or long offscreen gaps. The native/fallback aliases converge, and `exact_box_rebindings` is diagnostic.
- A reproduced alternating-native-ID regression, false-merge guards and the surrounding vision/feed tests pass (87 total). The correction is **offline-tested, not live-validated**; 32-second camera-turn ReID remains open.

## 2026-10-15 — Live Vision dual-ID diagnostics after failed long-turn ReID test

- The overlay now shows both the displayed `WORLD3D` object ID and the
  detector-rate `V3` ID. The last 32 source-track births/upstream rebinds and
  presentation-object births/raw rebinds are exposed in perception diagnostics
  for the user-operated next run; no new disk write occurs in the fast loop.
- The 2026-10-15 PID 18408 user test disproved full camera-turn identity
  continuity. Tested the existing colour histogram and appearance embedding
  against saved Jaina/Austyn crops: both misrank this pair. Long-term visual
  ReID is therefore not enabled from these features; a stronger identity
  signal/model and false-merge validation remain open.

## 2026-10-15 — World3D track-ID continuity on camera turns (offline-tested)

- The BoT-SORT/ByteTrack public-ID bridge now also covers detections still
  tentative in the native tracker. Their fallback ID is reconciled before
  publication, and native confirmation inherits the same public ID.
- A bounded eight-second colour-histogram ReID gallery can reconnect a
  previously stable visual track after a longer camera turn. It rejects
  contradictory appearance, ambiguous lookalikes and expired entries; this
  remains visual track continuity, not proof of a named NPC or GUID.
- Explicit world invalidation clears the gallery. The native BoT-SORT neural
  ReID remains disabled; the lightweight descriptor measured about 0.43 ms
  for 12 boxes on a synthetic 1600×900 frame. Live ID stability is unverified.
- Minimap center/radius values are rounded only in the context-reset key, so
  subpixel telemetry noise no longer wipes tracks. Real frame-size changes,
  map changes and loading still invalidate visual identity.

## 2026-10-09 — completed objective routing and full-state object hover (offline-tested)

- Completed live or normalized quest objectives no longer yield TDB objective
  destinations. Partly completed multi-spawn objectives require a matching
  live yellow minimap dot or a verified consumed-spawn exclusion; progress
  alone cannot identify which individual TDB spawn remains.
- A fresh complete `STATE_Z` hover/cursor sample can authorize an exact
  quest-object right-click when separate FAST field timestamps are absent.
  Object identity and quest-credit verification remain mandatory.
- The 2026-10-08 totem run predates these corrections; no post-fix live
  validation has been claimed.

## 2026-10-08 — élő POI-val egyeztetett TDB-úticélok (offline-tested)

- Aktív objective-nél az aktuális játékbeli world-POI-t összevetjük a TDB
  objektív-területével; egyezésnél a pontos TDB-spawn is navmesh-köteles
  úticéljelölt lehet, ismeretlen fázis esetén is. Eltérésnél a játékbeli
  POI marad. Több spawn közül az élő sárga minimap-pöttyel egyezőt választjuk.
- Questfelvétel és -leadás esetén a TDB NPC-helyet az élő azonos szerepű
  world-POI-val egyeztetjük, ha az rendelkezésre áll.
- TDB-úticélra haladva a generikus vizuális doboz nem szakítja meg a MOVE-ot
  a célpont közeléig; megerősített quest-hover továbbra is prioritást kap.
  Élő interakció és quest-credit ellenőrzés nélkül a TDB nem bizonyít sikert.


## 2026-10-08 — primary read-only TDB knowledge (offline-tested)

- Audited all 247 tables in the selected Retail WORLD SQLite structurally,
  including row/build counts and explicit runtime/query/deferred dispositions.
- Promoted TDB quest roles, objectives, spawns and POI search regions from a
  last-resort fallback to the shared planner's primary static candidates;
  live identity, navmesh and quest-state verification still gate actions.
- Added typed quest-chain, GO objective name, item-source and NPC service
  queries. Selects the newest VerifiedBuild per logical POI while retaining
  distinct spawn GUIDs and exposing superseded counts and provenance.
- TDB gameobject objectives now supply a reversible type and exact ID/name
  hypothesis where the live objective is incomplete. ID-less exact tooltip
  confirmation is carried through the planner **and** the `OBJECT_USE` skill's
  fresh-hover recheck; conflicting explicit IDs still block right-click.
- Added bounded geometry/floor/phase safeguards and offline regressions.
  No new live test or autonomous client input was performed for this change.

## 2026-09-29 — camera-compensated YOLO track association

- The production learned-World3D path now uses Ultralytics BoT-SORT instead
  of the local fixed-distance detector association. Full-scene and foveal
  detections are associated only after conversion to canonical client-pixel
  coordinates.
- BoT-SORT uses sparse-optical-flow camera-motion compensation, a 30-refresh
  lost-track buffer and a visual-family gate so subject, symbol and object
  tracks cannot exchange IDs merely because their boxes overlap.
- Continuous latest-frame YOLO remains enabled. The high-rate CPU patch
  tracker and the slower canonical WorldModel/evidence cadence are unchanged.
- Ultralytics tracker loading is warmed in a background thread. Until ready,
  the legacy tracker continues publishing; the first native tracks inherit
  those already-published public IDs, avoiding both startup blocking and an
  ID discontinuity at cutover.
- `AIPC_WORLD3D_TRACKER=LEGACY|BYTETRACK|BOTSORT` provides an explicit A/B or
  rollback switch (`AUTO` selects BoT-SORT when the learned detector exists).
  `AIPC_WORLD3D_TRACK_BUFFER`, `AIPC_WORLD3D_GMC` and
  `AIPC_WORLD3D_GMC_DOWNSCALE` expose bounded calibration controls.
- Focused World3D/perception regression: **188 passed, 2 skipped**. The full
  canonical test directory completed **1864 passed, 4 skipped, 18 unrelated
  pre-existing failures**. No live-control run was performed.

## 2026-09-28 — continuous latest-frame World3D detector

- Removed the artificial 8/10/12/15 Hz learned-detector throttle. The runtime
  now keeps one inference in flight and immediately submits the newest frame
  after completion, with no stale-frame queue.
- Canonical WorldModel publication remains independently bounded, so faster
  visual refresh does not restore the former high-frequency evidence churn.
- Added detector cadence and throughput diagnostics plus
  `AIPC_WORLD3D_CONTINUOUS_DETECTOR=0` as an explicit legacy-cadence rollback.
- A production-path replay at a requested 40 Hz completed **36.32 detector
  refreshes/s**; complete refresh latency was **13.89 ms p50 / 17.73 ms p95**.
  Focused World3D/capture/runtime regression: **90 passed**. Status:
  **offline-tested, pending user-operated live validation**. Python restart is
  required; this scheduling change needs no addon update.

## 2026-09-28 — responsive GUI telemetry/runtime startup

- The Tk event thread no longer constructs `AgentRuntime` synchronously.
  Database, navmesh, capture, telemetry and perception initialization now run
  in a dedicated connection worker while the GUI continues processing window
  events and displays elapsed startup time.
- Worker results and errors are handed back to Tk through a thread-safe queue;
  the worker never touches Tk objects. Auto-FULL_AI waits for completed runtime
  startup before focusing the selected PID and requesting the normal safety
  gate.
- Reconnecting immediately demotes the old runtime to MANUAL before its slow
  shutdown continues off the UI thread. Focused GUI/runtime regression: **41
  passed, 1 pre-existing replay expectation failed**.
- Follow-up live evidence showed a roughly seven-second status gap on a second
  FULL_AI click. Goal/mode/test controls can wait for the agent lock, so they
  now use a serialized GUI control worker as well. Tk displays the active
  control operation and elapsed time instead of blocking.
- Rotating the bounded live-capture segment no longer joins an in-flight JPEG
  encoder. Each queued frame carries its original segment paths, allowing an
  old segment's final frame and a new run's first frame to drain safely.
- Repeated FULL_AI is now idempotent while FULL_AI is merely suspended by the
  foreground/telemetry safety gate. Returning focus to the selected WoW window
  resumes normally; an explicit MANUAL then FULL_AI remains the restart path.
- Updated focused GUI/runtime/live-capture regression: **47 passed, 1
  pre-existing replay expectation failed**.

## 2026-09-28 — Retail two-offer gossip-row recovery

- Addon 0.9.33 locates visible quest-list rows through bounded nested
  ScrollBox element data and exact title-region matching, fixing the live
  `x=0,y=0` export seen for Austin Huxworth's two available quests.
- An open quest list whose rows remain unaddressable now emits a high-priority
  safe WAIT instead of allowing World3D navigation or visual approach behind
  the modal UI.
- Focused regressions pass; live validation remains open.

## 2026-09-28 — bounded turn-in map relocalization

- A nearby turn-in POI with no selected NPC no longer invents an unknown
  entrance transition; local questgiver acquisition retains control unless
  explicit transition/blockage evidence exists.
- A failed World Map relocalization is now evidence-gated for the complete
  quest/session/map context. It cannot reopen repeatedly after an empty scan
  or user close without a quest, map-context, or target-identity change.
- Combined quest-dialog/navigation regression: **86 passed**; live validation
  remains open.

## 2026-09-26 — persistent combat visual follow and canonical rotation

- The canonical `CombatSkill` now owns per-attempt ability usage history and
  records a bounded ability-attempt trace. FAST `actionbar_fast` usability,
  range and cooldown values are used through the shared `AbilityRuleEngine`,
  so the next ready ability can be selected after a cast instead of stalling
  on stale slow-snapshot state.
- Added data-only starter Warrior metadata: Charge is the ranged gap closer;
  Shield Slam is preferred in melee while ready; Slam remains a melee
  fallback. Live WoW usability/range/cooldown stays authoritative.
- Added GUID-committed combat visual follow. Fresh selected-target tracks
  produce bounded facing corrections, repeated out-of-range samples produce
  persistent `COMBAT_TRACK_APPROACH`, and a temporarily off-screen target is
  reacquired only in its last supported bearing for at most 1.8 seconds.
  NavigationService remains the sole movement/facing command authority.
- COMBAT/DEFEND now request the fast visual-servo tracker profile (nominal
  60 Hz scheduling, measured runtime remains hardware/capture bounded).
- Addon 0.9.32 exports spell min/max range when Retail exposes it. Both addon
  source directories remain byte-identical; installation was not performed.
- Focused regression: **66 passed**. Complete suite: **1795 passed, 4 skipped,
  15 existing unrelated failures** after updating the addon-version contract.
  Combat tracking frequency, behind-target reacquisition and rotation remain
  **LIVE OPEN**.

## 2026-09-26 — quest-progress MMAP routing and Murloc loop correction

- Audited selected-PID 8260 run `live-debug-20260926-182316.jsonl`. YOLO was
  not blind to the Murlocs: the exact runtime crop from
  `0180-182617-568-critical.jpg` produced several `creature_unit_like`
  proposals, led by confidence `0.563`, `0.314` and `0.152`. Earlier in the
  same run addon identity confirmed `Murloc Spearhunter`, combat ran and loot
  was verified.
- The post-loot loop was a planning error: the in-progress Quest POI used
  normalized map coordinates for direct MOVE, then the close-marker/no-target
  heuristic invented an `UNKNOWN_TRANSITION`, producing
  `SEARCH_ENTRANCE -> OPEN_MAP -> WAIT` instead of local objective search.
- Active objective and in-progress quest-location movement now preserves the
  addon `C_MAP_WORLD_POS` endpoint, requires `WORLD_YARDS + instance_id`, and
  routes only through the canonical `NavigationService` with
  `require_navmesh=True`. A normalized UI-map point alone cannot launch MOVE.
- Plain quest-objective arrival no longer invents an entrance transition
  without explicit transition or repeated-blockage evidence. Successful POI
  arrival also retains its originating marker key so the same route is not
  reissued before local target/object search.
- Focused quest/navigation/combat regression: **85 passed**. Live validation
  remains open; restart the Python agent. Addon update is not required because
  the live payload already contained instance `2175` WORLD_YARDS coordinates.

## 2026-09-26 — visible quest marker retained through World3D evidence

- Audited selected-PID 8260 capture `0068-181050-761-critical.jpg`. The v4
  model detects Jaina's real overhead marker at confidence `0.01725` on the
  exact 512px World3D runtime crop, but the fixed top-right minimap exclusion
  deleted it afterward even though no minimap occupied that region.
- Learned subject and overhead-symbol proposals may now cross optional HUD
  rectangles. They remain UNKNOWN observations; temporal grouping, evidence
  and mouseover telemetry still perform identification.
- A temporally `SUPPORTED` UNKNOWN `symbol ABOVE subject` group is now eligible
  for `SEEK_VISUAL_CUE` even without hard-coded badge colour or body geometry.
  This closes the live WAIT loop where supported groups existed but the
  planner rejected every one of them.
- Focused World3D/SEEK regression: **78 passed**. Restart the Python agent
  before live validation; the addon is unchanged.

## 2026-09-26 — repeated World Map scan and opaque WAIT correction

- Audited the selected-PID 8260 live trace. WAIT followed a successfully
  selected Combat Dummy because Slam lacked resource and Attack had no verified
  binding; the generic message did not expose that unavailable COMBAT proposal.
- WAIT now records its exact capability/evidence category and the unavailable,
  cooling-down and blocked proposal skills.
- Rejected outer-edge World Map cursor/tooltips as navigable marker locations.
  The live false point was `x=1.0, y=.153` from the objective tracker and had
  incorrectly kept map search non-exhausted, causing a second full scan after
  the OPEN_MAP cooldown.
- A selected living attackable target now prevents a new map fallback cycle;
  its combat/interaction state must be resolved in World3D first.
- Focused regression: **163 passed**. Restart the Python agent before live
  retest; the addon is unchanged.

## 2026-09-26 — self-avatar mask removed from World3D detection

- Removed the third-person self-avatar rectangle from World3D UI exclusions.
  Learned, legacy and generic detector paths now receive the original pixels,
  so a nearby NPC/object/symbol cannot disappear merely because it overlaps the
  controlled character on screen.
- Retained the rectangle as non-semantic post-detection metadata. A large,
  centred and bottom-anchored UNKNOWN subject receives an
  `ATTENTION_SUPPRESS_ONLY` hint instead of being deleted or recognized as the
  player.
- SEEK and INSPECT ignore an uncorroborated likely self-avatar track, while an
  overhead relation, supported visual group or badge evidence overrides the
  hint for a nearby overlapping NPC.
- World3D regression: **135 passed, 1 skipped**. Selected-PID overlap behavior
  remains **LIVE OPEN**; no addon update is required, but restart the Python
  agent before testing.

## 2026-09-26 — distant overhead-cue recall gate

- Lowered the raw learned-detector observation gate from 0.05 to 0.01 and the
  `overhead_symbol_like` evidence gate from 0.08 to 0.01.
- Replaced SEEK's alternating left/right camera whips with a slow one-way
  four-step sweep. Both the empty-scene scan and IDENTIFY-track reacquisition
  now use 160 ms bounded drags separated by a 900 ms observation window.
- Kept the subject/object class gates and per-class budgets unchanged: weak
  overhead output remains UNKNOWN visual evidence and cannot directly assert a
  quest role.
- Added a regression proving a 0.02 overhead cue survives while a 0.02 weak
  humanoid proposal remains rejected; camera/seek focused suite: 54 passed.

## 2026-09-26 — combined 2794 v4 World3D runtime promotion

- Promoted `world3d_annotation_assist_combined_2794_v4` to the canonical
  learned World3D runtime revision.
- Built machine-local static FP16 TensorRT engines for the 512 global scan and
  640 foveal scan paths; the v4 PyTorch checkpoint remains the portable
  fallback.
- Kept UNKNOWN-first evidence semantics and the existing detector/tracker
  authority boundaries unchanged.
- Added a regression guard for the selected runtime model revision.
- Held-out Exile's Reach comparison showed improved aggregate mAP and improved
  creature/quest-object AP, but lower precision/recall at the operating point
  and a material corpse-class regression. Selected-PID live validation remains
  open.

## 2026-09-25 — learned World3D runtime recall correction

- Lowered the YOLO backend observation gate to 0.30 and retained conservative
  class-specific acceptance thresholds and candidate budgets.
- Stopped broad quest-tracker/nameplate overlay rectangles from deleting real
  learned subject detections behind translucent UI.
- Added an explicit self-avatar ROI so the controlled player remains
  suppressed without masking right/left world subjects.
- Corrected automatic NVIDIA selection and diagnostics to report the actual
  Ultralytics inference device (`cuda:0`).
- Real-frame replay now retains the 0.796 worg and rejects the controlled
  avatar; full regression: 1758 passed, 4 skipped.

## 2026-09-25 — stale quest reward UI invalidation

- Fixed a live WAIT/reward-selection loop while the active objective was only
  1/6 complete and no quest dialog was visible.
- Addon 0.9.30 gates retained quest reward choices behind effective UI
  visibility.
- Fresh FAST dialog-closed telemetry now invalidates the stale nested full-state
  quest dialog immediately.
- Regression: 1756 passed, 4 skipped; live retest remains open.

## 2026-09-24 — learned World3D model connected to live runtime

- Connected `world3d_annotation_assist_combined_1077_v1.pt` to the canonical
  GUI runtime perception path.
- Preserved UNKNOWN-first semantics and the single World3D V2/V3 pipeline.
- Added conservative class-specific confidence thresholds, per-class caps and
  a ten-candidate learned-output budget to reduce preview-style box floods.
- Moved model/CUDA warm-up off the perception lane; cheap CV remains active
  while the learned backend initializes.
- Added runtime model/device/threshold diagnostics and environment overrides.
- Offline regression: 1754 passed, 4 skipped; live validation remains open.

## 2026-09-16 — M0 audit closure: Combat reach, Loot credit, Search and safe stop

- An explicit Combat `OUT_OF_RANGE` response now starts one persistent,
  same-attempt `NavigationService.move_to_entity()` reach when the exact live
  hostile and player have same-instance world coordinates. Arrival revalidates
  the selected GUID before Combat resumes; screen-local correction remains a
  bounded fallback rather than a second movement owner.
- Loot now treats a confirmed before/after quest-objective delta as success
  evidence only when no exact expected item ID was declared. An explicit item
  contract still requires that item; deadline failure is now the typed
  `EXPECTED_ITEM_NOT_RECEIVED`.
- Added direct M0 coverage for Search sector coverage/exhaustion and discovery,
  selected-target destination refresh, Combat facing/lost-target/player-dead/
  timeout paths, and executor-exception safe stop.
- Removed the engine's remaining tick-by-tick legacy CombatController update.
  Combat proposal admission is now stateless, while runtime diagnostics read
  the canonical `ActiveSkillRuntime` combat context.
- Offline regression after this audit: **800 passed, 2 skipped**. This did not
  start a client, addon, or live controller and is not live validation.

## 2026-09-16 — M0 Interact owns approach and retry

- `INTERACT`/`TALK` no longer fail and hand control back to the planner after
  one confirmed client `OUT_OF_RANGE` response. The same active attempt now
  owns `APPROACH -> FACE -> INTERACT -> VERIFY`.
- `NavigationService.move_to_entity()` accepts only an exact selected GUID and
  live, same-instance target/player world positions. It refuses to invent a
  destination from screen pixels and retains the existing persistent movement
  controller as the sole world-space movement authority.
- If world coordinates are unavailable, a bounded fallback uses only a fresh
  GUID-associated World3D/mouseover anchor and the existing per-attempt visual
  servo. No new planner action is created between the range error and the next
  client interaction probe.
- Loot now applies the same-attempt world-coordinate recovery to an exact dead
  target only. A loot UI opening is no longer a completion signal; receipt or
  meaningful inventory evidence is required, and an explicitly declared item
  ID must match the received/gained item.
- Added unit and deterministic-acceptance coverage for the same-attempt
  recovery, coordinate/identity gates, visual-anchor gate, and one-recovery
  budget. This is offline evidence only; no selected client, addon, or live
  controller was started. Full offline regression: **791 passed, 2 skipped**.

## 2026-09-16 — M1 canonical world-object use boundary

- Structured quest world objects no longer emit the generic `USE` proposal.
  They use canonical `OBJECT_USE` through `ObjectUseSkill` and the one active
  M0 dispatch authority.
- Before its one right click, the skill rechecks that the exact current addon
  mouseover object/item identity and normalized cursor coordinate still match
  the intent. A stale crop, moved cursor, or different hovered object fails
  before input.
- `OBJECT_USED` acknowledgement is diagnostic only. The skill succeeds only
  when the declared normalized quest/objective receives credit.
- Complete offline regression: **776 passed, 3 skipped**. No client input,
  controller start, addon install, or live test occurred.

## 2026-09-16 — M1 canonical instructed-spell boundary

- `FOLLOW_INSTRUCTION` no longer has any generic-registry execution route.
  `InstructedSpellSkill` requires one confirmed living hostile target GUID,
  an exact live action-bar spell ID/name/binding matching the fresh NPC
  instruction, and the explicitly selected bindings cache before it sends
  one binding.
- Its only success signal is matching normalized quest/objective credit.
  Casting acknowledgement, cooldown movement, an action-bar row, or a phrase
  that merely resembles a spell name cannot complete the objective.
- `USE_ON_TARGET` was aligned with the same authoritative-cache rule: missing
  selected bindings now blocks rather than allowing a test-only implicit
  execution path. Duplicate legacy lifecycle membership was removed.

## 2026-09-16 — M1 canonical targeted quest-item boundary

- `USE_ON_TARGET` no longer dispatches through the generic registry. The
  canonical `QuestItemSkill` rechecks the selected target GUID, living state,
  exact item ID, current usable action-bar binding and selected bindings cache
  immediately before sending one key.
- The legacy generic verifier can no longer promote an `ITEM_USED` event or a
  cooldown transition into objective completion; `QuestItemSkill` accepts only
  matching normalized quest/objective credit.
- The same canonical boundary now owns `ASSIST` for friendly quest targets and
  rejects harmful action-bar items before dispatch.
- Complete offline regression: **776 passed, 3 skipped**. No live client input
  or controller start occurred.

## 2026-09-16 — M1 exact Extra Action quest-tool boundary

- Addon 0.9.25 exports the visible/usable state plus the actual Extra Action
  slot's `action_type` and `action_id`; the export remains read-only.
- `EXTRA_ACTION` is a canonical active skill. It requires the selected
  bindings cache to contain `EXTRAACTIONBUTTON1`, rechecks the live exported
  action identity immediately before dispatch, and treats only matching quest
  objective credit as success.
- The planner may automatically use only an item-type Extra Action whose ID
  exactly matches the active quest's Quest API `special_item`; other action
  types require an explicit goal policy carrying the same exported type/ID.
  A visible button, UI position, or guessed hotkey is never enough.
- Extra Action telemetry is carried in the FAST lane, but has not been
  installed or live-validated. Complete offline regression: **770 passed, 3
  skipped**.

## 2026-09-16 — M1 explicit gossip/reward transition and ownership cleanup

- `QUEST_DIALOG` no longer has a generic registry click or verifier path; only
  `QuestDialogSkill` may execute it, and old direct calls fail closed.
- Addon-exported `AVAILABLE`/`COMPLETE` gossip rows now become an explicit
  `GOSSIP_SELECT` action.  It must transition to a named action for the same
  quest before ACCEPT/COMPLETE/TURN_IN can run.
- Added the V4 handoff documents: migration status, dead-code audit, M0/M1
  implementation descriptions, test report, and known limitations.
- Multiple offered quest IDs now fail closed until the goal explicitly selects
  one; this policy is isolated in `QuestOfferSelector` rather than embedded in
  Planner.
- Addon 0.9.22 exports bounded reward-choice rows and their UI coordinates.
  `QuestRewardSelector` only permits an exact requested item/index, or a
  separately requested one-choice `FIRST_UNAMBIGUOUS` policy.
- Addon 0.9.23 exports the supported Quest API campaign flag. The runtime may
  continue only an explicit `MAIN_CAMPAIGN` goal into one unambiguous active
  campaign quest; it never guesses from titles, map markers, or side quests.
- Focused regression: 104 passed; complete offline suite: 765 passed, 3
  skipped. Live completion status is intentionally unchanged until
  user-operated evidence exists.

## 2026-09-26 — independent fast perception pump and blind-TAB guard

- Moved live World3D scheduling onto a latest-frame background pump so slow
  planner/SQLite ticks can no longer starve the fast tracker lane.
- Raised the tracker contract to 30 Hz (24 Hz while idle) while retaining an
  independently throttled detector and 4 Hz canonical evidence publication.
- Added explicit target/actual tracker diagnostics and background-worker
  health reporting. Offline measurement on the live-machine code path reached
  23.47 Hz tracker output; live WoW validation remains open.
- Removed quest-domain `TARGETNEARESTENEMY` as a search primitive. The binding
  remains available only as an in-combat defensive fallback.
- A TAB-selected GUID now proves identity only. It cannot become a persistent
  movement target without a fresh screen anchor or positive harmful-action
  range evidence; otherwise the commitment is released with
  `BLIND_TARGET_UNLOCATABLE`.
- An off-screen selected GUID no longer suppresses active World3D search; the
  camera may seek a visible candidate until hover/vision supplies localization.
- Focused target/search regressions pass. Complete repository regression:
  **1801 passed, 4 skipped, 15 pre-existing unrelated failures**; the remaining
  failures are the already-recorded navigation/search fixture debt.

## 2026-09-26 — tracker cadence headroom and live-frame annotations

- Raised the latest-frame perception pump to 120 Hz and tracker-only admission
  to 40 Hz. Detector refresh remains independently throttled and no frame
  queue is introduced.
- Offline production-path measurement improved from 23.47 to **33.11 tracker
  Hz**, with 4.09 detector Hz and 3.76 canonical Hz. Background `update()` p95
  was 0.27 ms; the periodic canonical path remains the only ~9 ms tail.
- Manually reviewed ten PID 8260 live frames. The set contains 24
  `creature_unit_like` boxes, one `corpse_like` box, and one explicit empty
  World Map hard-negative. The own player and UI/nameplates are excluded.
- Export audit: 10 images, 25 boxes, zero invalid/missing/orphan labels, zero
  split overlap, `training_ready=true`.

## 2026-09-16 — M0/M1 V4 audit and Phase A foundation

- Added the V4 repository/authority audit in `docs/M0_M1_V4_AUDIT.md`.
- Repaired the real-screenshot overhead-symbol → subject-probe temporal
  relation regression without assigning NPC/quest semantics to CV output.
- Added canonical typed runtime contracts and `ActiveSkillRuntime`.
- Migrated `AutonomousAgent`'s active `pending` attempt into that canonical
  runtime; the old lifecycle display is now derived state.
- Added the Supervisor interrupt gate and single-threaded runtime event bus.
- Added and adopted `NavigationService` as the active engine's canonical
  route/movement authority.
- Migrated the active `TARGET` execution/verification path to the typed M0
  TargetSkill FSM.
- Migrated `INTERACT`/`TALK`, `COMBAT`/`DEFEND`, and `LOOT` to canonical M0
  skills with pure before/after verifiers. User/manual cancel now closes only
  the canonical active skill after stopping input.
- Added deterministic one-active-skill replay coverage (100 iterations).
- Centralized active-engine timeout resolution and typed bounded retry backoff.
- Added M1 primary-quest ownership, deterministic objective-classification
  facade, and separately recorded quest-credit verification evidence.
- Full offline regression after M1 Phase A: **718 passed, 3 skipped**.
- Extracted M0 skill dispatch and M1 objective location resolution from the
  active engine/planner paths; their targeted regression selection is green.
- Full offline regression after this migration: **710 passed, 3 skipped**.
  No live validation claimed.
- Added a stable M1 primary-objective execution state machine consumed by the
  shared planner, plus bounded no-quest-credit target suppression after a
  successful combat result. Full deterministic regression: **733 passed, 3
  skipped**.
- Migrated bounded `SEEK_VISUAL_CUE` state into the canonical active-skill
  context through `SearchSkill`; engine-owned search state is now diagnostic
  compatibility only.
- Migrated `VISUAL_APPROACH` servo ownership into `VisualApproachSkill` and
  the canonical active-skill context without changing movement tuning.
- Added the Functional Design Specification reconciliation ledger, including
  V4 precedence, UNKNOWN-first perception reconciliation, and per-domain
  ownership/status mapping.
- Added bounded same-attempt combat local recovery: only an identity-matched,
  fresh screen-space target can request `NavigationService` to produce a short
  LOS/range/facing correction, followed by a controlled re-cast.
- Added event IDs, bounded event-bus idempotence and deterministic runtime
  event priority for safety/replay boundaries.
- Migrated `QUEST_DIALOG` to canonical `QuestDialogSkill`; exact addon-exported
  reward rows are now selectable only through the explicit `QuestRewardSelector`
  policy boundary (ambiguous/default clicks remain blocked).
- Added supervisor-owned suspend/resume: a combat interrupt cancels the only
  active skill, then may resume one precondition-valid intent once after the
  interrupt clears. Manual mode/goal replacement discards it.
- Added `TurnInResolver`, which prevents generic memory waypoints from being
  treated as an NPC turn-in destination and preserves field UI/local role
  priority over map-region fallback.
- Added explicit M1 quest stage-transition tracking. A fresh normalized stage
  invalidates the prior objective/location selection before reclassification.
- Full deterministic regression after the current M0/M1 increment: **749
  passed, 3 skipped**. This remains offline evidence only.
# 2026-09-26 — Fast camera tracking and detector cadence

- World3D detector profiles now request 8 Hz balanced, 10 Hz navigation,
  12 Hz quest search and 15 Hz combat refreshes.
- Detector scheduling is start-to-start. The existing single in-flight future
  remains the back-pressure boundary, so inference time no longer receives a
  second unnecessary cooldown and stale frames still cannot queue.
- The CPU patch tracker now accepts larger confidence-validated global camera
  translations and searches a wider residual neighbourhood for perspective
  motion. This addresses track loss while running or rotating the camera.
- Active tracker admission is 45 Hz with a 40 Hz completed-rate target.
- Focused World3D tests: 36 passed. Runtime/profile regression subset: 65
  relevant tests passed after cadence expectations were updated; one unrelated
  pre-existing replay command-count assertion remains outside this change.
# 2026-09-26 — Learned humanoid inspection handoff

- Stable `humanoid_unit_like` / `creature_unit_like` detections now remain
  UNKNOWN but become eligible for mouseover INSPECT at confidence 0.22 after
  three stable frames and at the model admission threshold after six frames.
- A nameplate is no longer a mandatory gate for learned subject proposals.
- Self-avatar attention suppression, combat target ownership, temporal
  stability, rejection memory and mouseover semantic confirmation remain in
  force.
- Focused inspection/seek/target regression: 72 passed.
# 2026-09-26 — Five-percent learned subject admission

- Runtime YOLO admission for `humanoid_unit_like` and
  `creature_unit_like` is now `0.05`.
- A temporally stable learned subject uses the same `0.05` gate for INSPECT;
  it remains UNKNOWN until mouseover/addon confirmation.
- Other class thresholds, self-avatar suppression, per-class box budgets,
  temporal stability and rejection memory are unchanged.
- Focused regression: 55 passed.

# 2026-09-28 — Quest-offer reward preview classification

- Addon `0.9.34` no longer interprets `GetNumQuestChoices()` as sufficient
  evidence of a selectable reward dialog. Retail may expose a reward preview
  while the quest-detail `Accept` button is visible.
- `REWARD_SELECT` is now exported only in a visible completion/turn-in
  context, and a visible `QuestFrameAcceptButton` takes precedence over stale
  completion hints.
- Focused addon/quest-dialog/reward regressions: **38 passed**. Live validation
  remains pending.

# 2026-09-28 — Combat FAST fallback preserves defensive response

- Addon `0.9.35` adds a bounded combat-priority FAST fallback. A field-rich
  hostile target can no longer evict `is_in_combat`, player life state, exact
  target identity, or the four-slot `actionbar_fast` readiness data.
- This prevents ability admission from degrading to `cooldown_unknown` and
  prevents quest-map MOVE from resurfacing while the player is being attacked.
- Focused transport/combat/interrupt regression: **112 passed**. Live
  validation remains pending.

# 2026-09-28 — Post-combat MOVE wall-contact detection

- The movement progress score no longer treats Retail's
  `moving=true/speed=7` run-animation state as proof of physical translation.
  Positive progress must come from position/visual displacement evidence;
  a stopped flag remains valid negative evidence.
- A commanded running state combined with an unchanged authoritative position
  is recorded as `MOTION_POSITION_MISMATCH`, allowing the existing bounded
  stuck-recovery path to activate.
- Turn-only heading corrections pause accumulated no-progress evidence;
  forward soft-steering no longer clears it. Focused navigation/resume
  regression: **58 passed**, with one unrelated existing quest-POI planner
  fixture deselected.
# 2026-09-28 - Navmesh cliff-transition rejection

- Live Exile's Reach evidence showed the mmap route jumping from `z=59.5` to
  `z=69.1` over only 7.7 horizontal yards at the Quilboar Briarpatch. Retail
  collision rejected that approximately 45-degree transition and the agent
  repeatedly ran into the cliff.
- Polygon A* now rejects transitions at or above the observed unwalkable
  slope and searches for a gentler connected mmap corridor. It still fails
  closed when no supported route exists; no direct-line fallback was added.
- Added a regression proving that a 45-degree shortcut is rejected in favour
  of a supported flat detour. Focused mmap/navigation regression: **88
  passed**; live validation remains open.

# 2026-09-28 - Targeted quest special items outside the action bar

- Addon `0.9.36` preserves Retail's raw `monster` objective type but
  normalizes it to `USE_ITEM` when the authoritative quest-log special-item
  name occurs exactly in the objective text. This fixes objectives such as
  `Re-Sizer v9.0.1 tested on Wandering Boars` without quest-ID hard-coding.
- The shared quest planner and canonical `UseItemSkill` now support an exact
  active-quest special item from a visible bag slot when it is absent from the
  action bar. The path opens bags, revalidates item ID + bag + slot + addon UI
  coordinate, right-clicks once, and still requires objective-progress credit.
- Focused addon/quest/planner/skill regressions: **72 passed**. Addon package
  `0.9.36` was installed byte-identically; live validation remains pending
  after `/reload` and a user-operated FULL_AI run.

