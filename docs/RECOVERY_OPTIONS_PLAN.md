# Recovery options and outcome evidence

Status: **PARTIAL**. This is a design and implementation map, not a claim
that every WAIT can already recover or that overnight operation is validated.
The user operates live tests; offline checks never count as quest completion.

The 2026-10-27 user direction is to try different plausible solutions to a
blocked task, verify the result, and retain enough evidence to explain which
change helped. Extend the existing RecoveryPlanner, NavigationService,
interaction flow and skill verification. Do not add a second action loop.

## What is present

| Situation | Existing response | Status and limitation |
| --- | --- | --- |
| An existing quest playbook offers another ready step after a failed option or verified approach | Shared playbook definitions guide the existing candidate ranking. The old location commitment can yield to the same objective's ready action; target commitment retains its GUID. QuestAttemptMemory records the trial and its preceding failure. | OFFLINE_TESTED / PARTIAL. Only existing grounded candidates and implemented skills can run; no new flight landing or missing mechanic is fabricated. |
| Final interaction facing is improving slowly | Shared ReachMovementController continues measured in-place turning; 2.5 s without improvement or 8 s total ends the attempt. Progress timestamps/error are in its snapshot. | OFFLINE_TESTED. Post-change live coal/NPC approaches remain unvalidated. |
| Short final approach with delayed pose feedback | Speed and pose age limit the forward pulse; InputScheduler expires its explicit translation lease without requiring another observation. Positive gaps receive at least the executor's legal 40 ms pulse. | OFFLINE_TESTED, including the real executor/scheduler against a fake backend. No input is sent to the game in these checks. |
| Speak-with objective completed, next task is travel with the actor | The speech hold no longer treats ARRIVE text as speech credit. Current named server vehicles can resolve through the cached exact-entry catalogue; ordinary MOVE / INTERACT verifies the current soft recipient and vehicle entry. | OFFLINE_TESTED. Recorded Wrathion entry 191669 resolves without hover; real boarding remains unvalidated. |
| Large quest object is usable only from a side | ObjectApproachSearch supplies up to six MMAP approach probes in 90 s. Failed contacts cannot immediately relearn the same edge. Use/credit remains separately verified. | OFFLINE_TESTED; user reported the forge fix worked. Manual interventions prevent treating the whole quest as autonomous validation. |
| Supported movement stuck | Existing stopped observation, bounded physical recovery, validated local waypoint, corridor rebuild and expiring route danger/blacklist ladder. | Existing implementation; it does not cover every navigation failure reason. |
| Travel flight lands where final walking path is unavailable | Existing NavigationService can relaunch the same request at most twice. Known wrong-level arrival is rejected. | PARTIAL. Repeating the original landing is not a general search over different landing surfaces. |

## Next common recovery contract

Retain the original task and expected outcome while a bounded recovery episode
tries alternate options. A recovery action is a normal owned skill intent,
executed by the canonical executor. It cannot assert its own success.

An episode needs one context key: session/character, map/instance, quest and
objective, current entity GUID or location, and relevant floor evidence.
Progress, a newly observed actor or a genuinely changed floor can invalidate
old alternatives. Merely switching skill names must not reset the budget.

For each option, record:

- episode ID and failed action ID;
- typed failure, observation ID and evidence time;
- option name, target GUID, candidate point/surface and rejection reason;
- start/end time and attempt/time budget remaining;
- resulting skill status and observed change;
- verification evidence, or why the attempt remained unverified;
- next selected option and reason.

The 2026-10-28 playbook binding adds a bounded cross-skill trial journal to
the existing QuestAttemptMemory. A unique active objective, mechanism,
session/map and progress define an episode; each candidate retains its
current GUID or location. The journal links the next result to the previous
failed action and keeps action verification separate from objective credit.
The last twenty trials are projected in status; structured trial events keep
the full bounded record fields. Sampling/camera churn cannot reset this
context, and F7 aliases do not count as different physical options.

This contract remains **PARTIAL**: navigation surface rejection details and
remaining time/attempt budgets are still in their existing navigation/failure
logs rather than fully joined into the episode journal. A successful command
dispatch or elapsed timeout must not be logged as a solved bug. A diagnosis
may remain uncertain even when an alternate approach succeeds.

## Options to extend, in priority order

1. **Interaction:** stop, turn toward the current actor, verify alignment,
   attempt configured interaction once, inspect the result. A fresh range
   error permits a smaller approach; missing recipient or failed credit can
   permit a different validated side contact. Retain current GUID authority
   throughout. Do not retry the same ineffective contact indefinitely.
2. **Wrong floor or blocked final approach:** compare measured own Z with the
   target and candidate navmesh surfaces. Select another surface/contact only
   when its path and relevant height are validated. An arbitrary higher Z is
   not a landing destination.
3. **Flight alternative:** where flight is available and appropriate, rank
   alternate landing candidates around the objective, reject prior failed
   surfaces, and verify a walkable path from landing to interaction range.
   Use the existing flight MOVE owner. A different landing-point selector,
   its rejection memory and full verification are still **UNIMPLEMENTED**.
4. **Route failure:** avoid repeating an unchanged failed corridor. Try a
   validated local alternative, rebuild from the observed position, or use a
   proven entrance/transition. Preserve the objective and distinguish route
   progress from reaching the actual quest actor/object.
5. **Exhausted task:** preserve a diagnostic episode, temporarily defer that
   task and select another eligible agenda task where one exists. Unknown
   input authority, stale telemetry and user cancellation still stop input;
   recovery must not convert those states into experimental commands.

## Acceptance evidence still needed

- Live Wrathion talk-to-vehicle handoff with VEHICLE_ENTERED evidence.
- Live coal/fragment and mounted NPC approach without repeated facing WAITs
  or invalid movement leases.
- Live confirmation that the same GUID/context cannot regain unlimited
  retries by changing skills. Offline checks preserve proposal keys/cooldowns
  and group equivalent F7 aliases as one option.
- Wrong-floor landing leads to a different validated landing when possible;
  an absent valid alternative gives an explicit reason, not fabricated arrival.
- Logs connect failure, selected alternative and actual quest/vehicle/UI
  feedback. No result is attributed to the agent after manual intervention
  without separate evidence.

Relevant requirements: V4 sections 25–29, 32–33 and Design retry/timeout
policies 75–76. No acceptance gate is promoted by this plan.
