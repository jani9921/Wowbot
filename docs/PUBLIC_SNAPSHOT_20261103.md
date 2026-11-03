# Public source snapshot — 2026-11-03

This snapshot synchronizes the current `projekt` source into `jani9921/Wowbot`.
It includes source, tests and fixtures, tools, the addon, configuration defaults,
native navigation components, and project/migration documentation. Historical
documentation is retained; its older completion claims do not certify new code.

## Current direction and work included

- `START_AGENT.bat` explicitly selects `AIPC_RUNTIME_PROFILE=SERVER`. Packet/GUID
  evidence and structured addon state drive decisions; world vision is being retired.
- REV4 architecture and combat/character plans are under
  [reform/rev4-20261029/input](reform/rev4-20261029/input).
- [Combat/navigation responsibility split](reform/rev4-20261029/P5_P7_RESPONSIBILITY_SPLIT.md).
- [Quest mechanic graph](reform/rev4-20261029/P8_QUEST_GRAPH_PLAN.md) and
  [travel/quest implementation status](reform/rev4-20261029/SPEC_30_32_TRAVEL_QUEST.md).
- [It's Alive! item/actor relationship fix](LIVE_TEST_FIXES_20261102_GOLEM_ITEM.md):
  item 57954 targets the original golem, rather than treating its summoned vehicle
  credit as a kill instruction. The targeted regression run passed 419 tests;
  successful live execution after this fix remains unverified. The November 3
  follow-up for server-confirmed feign death and explicit item corpse-target
  permission is included as well; its new tests are part of the publication run.

## Machine-specific prerequisites

- Windows and Python 3.13; see `requirements.txt` and `requirements-packet.txt`.
- The currently configured capture build is **12.1.5.70575**. Its local Ymir path is
  `runtime/ymir/ymir_retail_12.1.5.70575_PORT_CANDIDATE_V3.exe`, with SHA-256
  `77cc8a63b94ee52c47090290a69f3d6fa3db3995ded3c7534c886c85dcbec6b9`.
  The executable is not bundled. A different client build is not assumed compatible.
  The capture backend requires its local Npcap dependency. Consult
  [packet telemetry documentation](PACKET_TELEMETRY.md) before starting capture.
- Install the supplied addon in the selected WoW installation. Structured addon/UI
  telemetry remains necessary even though world vision is disabled in SERVER.
- Select the actual client PID and verify its bindings cache. The example cache is
  reference material, not automatic input authority.
- Supply local MMAP/VMAP/maps for navigation and the optional TDB/client-supplement
  catalogs needed by reference-assisted mechanics. Database builders/export tools
  are included; the third-party and learned databases themselves are not. See
  [TDB setup](TDB_SETUP.md) and [client supplement status](CLIENT_DB2_ITEM_EFFECT.md).

The existing install wizard retains historical vision/GPU steps. Publishing this
snapshot does not claim a new-machine installation or all live quests were tested.

## Publication boundary

The repository excludes login files, local configuration overrides, personal binding
caches, learned memory, runtime logs/screenshots, raw packet dumps, local database
files, generated source-backup ZIPs and local capture executables/candidates.
Regression fixtures and reviewed text/JSON/XML test reports remain included.
References to omitted local archives/captures in evidence reports identify the
original local evidence; they are not downloadable public artifacts.

Tests and live acceptance are separate. Individual validation records remain in
[LIVE_VALIDATION.md](LIVE_VALIDATION.md); a successful offline test run is not proof
that a real quest completed autonomously.

The publication check exposed three client/TDB integration tests that depended on
the developer's extracted database. They now use a temporary synthetic SQLite
catalog with the real catalog reader and world projection, so these checks do not
require distributing that database. Export regression tests also verify that raw
captures/login files are excluded and an existing Git checkout cannot be deleted
by rebuilding an export.

Publication validation on the exported checkout: **522 passed, 0 failed, 0 skipped**
across 34 targeted test modules (90.95 seconds including the test runner). All 1,426 exported Python files
also parsed successfully. These are targeted offline checks, not the complete
test suite or a new live run. The publication scan found no local login values,
token/private-key patterns or raw capture/database paths in the selected files.
