# Known limitations

- Full M0 and M1 completion gates have not passed; only the documented portions
  are offline-tested.
- The user, not the assistant, operates live client tests.  No test result is
  valid without the selected PID, fresh telemetry, and authoritative bindings.
- Quest rewards are fail-closed unless an exact exported row is selected by
  `reward_item_id`, `reward_choice_index`, or explicitly requested
  `FIRST_UNAMBIGUOUS` with one row. Any gossip UI not represented as an exact
  exported quest row remains fail-closed; no arbitrary button selection is
  allowed.
- Visual detections are evidence, not entity facts.  Identity requires matching
  mouseover/addon telemetry or other defined ground truth.
- TDB/NPC data is fallback location knowledge only; it does not prove current
  spawn/phasing or authorize a target interaction.
- No memory inspection, injection, or secret-value bypass is used.

## Deferred live block — movement / MMAPS / VMAPS / FAST Hz (2026-09-23)

This block is deliberately **not closed** while the remaining coverage work
continues:

- MMAPS route selection is active, but Exile's Reach waypoint following,
  arrival overshoot and occasional backtracking still require another
  selected-PID live run with the newest Python process.
- The addon FAST producer was healthy in the latest captures (about 29–33 Hz).
  The canonical movement consumer improved from about 4.74 Hz to 17.30–18.75
  Hz, but the newest one-second stable-REACH scheduling window has not yet
  been live-validated.  This must remain visible as a consumer-rate issue; it
  must not be hidden by shorter W leases or synthetic key-up workarounds.
- MAPS terrain and MMAPS reachability are integrated.  VMAPS collision/LOS is
  still a separate, unfinished geometry input; file discovery is not runtime
  collision or line-of-sight integration.
- Latest evidence: `live-debug-20260923-220737.jsonl` and
  `live-debug-20260923-221642.jsonl`.  No addon reinstall is required for the
  pending Python-side scheduler validation, but the Python agent must be
  restarted.

Return to this block after the remaining offline coverage wiring.  Do not mark
MMAPS/VMAPS/movement/FAST Hz complete based on unit tests or replay alone.
