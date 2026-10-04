# M0 Phase B — canonical navigation-service selection

Validation status: **UNIT_VALIDATED**. No live client movement was performed.

## Audit result

`wowbot.navigation.engine.NavigationEngine` is tested in isolation but has no
construction/call site in the live `AutonomousAgent` path. The active path was
instead split between `AgentNavigator` (measured route knowledge and obstacle
evidence) and `ReachMovementController` (persistent reach/progress/stuck
control), with visual approach/search as separate local capabilities.

## Canonical choice

`wowbot.navigation.service.NavigationService` is now the only navigation
authority constructed by `AutonomousAgent`. It privately owns the two active
components as route knowledge and movement control. The engine calls the
service for every route permit, waypoint, progress sample, command, recovery,
topology update and snapshot.

`VisualApproachController` and `SeekVisualCueController` remain temporary
local visual-acquisition adapters. They must be brought under this service's
local-navigation/search API in the next M0 increment; they are not a second
coordinate-route authority.

## Changed files / migrated call sites

- `src/wowbot/navigation/service.py`: canonical API for the existing live
  route/movement path.
- `src/wowbot/agent/engine.py`: migrated every direct live route/movement call
  to `self.navigation`.
- `src/wowbot/navigation/__init__.py`: exports the service.
- `tests/test_navigation_service.py`: ownership/start/observe/snapshot test.

The `agent.navigator` and `agent.movement` names remain read-only diagnostic
and test projections. They do not hold independent state; they will be
removed after external diagnostics have moved to `agent.navigation`.

## Tests

- Navigation service, movement, graph engine, core agent and runtime group:
  **126 passed**.
- Complete repository regression after the subsequent TargetSkill migration: **701 passed, 3
  skipped** (two file partitions; the host limits a single command to about
  30 seconds).
- No M0 navigation acceptance or live validation is claimed yet. In
  particular, route graph coverage, vision-only navigation, cave transitions,
  FaceController and unified search remain outstanding.

## Legacy disposition

| Component | Disposition |
| --- | --- |
| `NavigationService` | KEEP — canonical live navigation authority |
| `AgentNavigator` | MIGRATED PRIVATE COMPONENT |
| `ReachMovementController` | MIGRATED PRIVATE COMPONENT |
| `NavigationEngine` | ADAPTER_TEMPORARY / audit for deletion after graph-route API is either migrated or removed |
| `VisualApproachController` | ADAPTER_TEMPORARY — local visual final approach |
| `SeekVisualCueController` | ADAPTER_TEMPORARY — bounded visual acquisition/search |

The following TargetSkill increment is documented separately in
`M0_PHASE_B_TARGET.md`.
