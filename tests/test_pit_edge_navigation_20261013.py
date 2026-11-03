"""Live 2026-10-13 17:44-17:57 (Hrun's pit spiral, user screenshots): a
~50 yd wide walkway between a fence at the drop and the cave wall; the
route hugged the fence, a running jump / a backward recovery step threw
the character into the pit, and after a short drop it slid at a walkway
edge for 25 s."""
import math
from types import SimpleNamespace

from wowbot.navigation import NavigationService
from wowbot.navigation.contracts import GlobalRoute
from wowbot.navigation.z_resolver import ResolvedPosition


class _Ledge:
    """Walkway at z 25 for y >= 0, the pit (z -19) for y < 0."""

    def walkable_heights_at(self, instance_id, point, radius=2.5):
        return [25.] if point["y"] >= 0 else [-19.]


def _nav():
    nav = NavigationService(navmesh=_Ledge())
    nav._z.player = ResolvedPosition(0., 1., 25., .9, "MMAP", 2175, at=1.)
    return nav


def _state(facing, x=0., y=1.):
    return {"player_world_position": {"x": x, "y": y, "instance_id": 2175}, "orientation": facing}


def test_a_recovery_step_toward_the_drop_is_refused():
    nav = _nav()
    # Facing +y (pi/2): backwards is -y, the pit.
    assert nav.recovery_step_drops(_state(math.pi/2), "BACKWARD")
    assert not nav.recovery_step_drops(_state(math.pi/2), "JUMP_FORWARD")
    # Facing -y: the running jump would clear the fence into the pit.
    assert nav.recovery_step_drops(_state(-math.pi/2), "JUMP_FORWARD")
    assert nav._movement.__dict__["jump_guard"](_state(-math.pi/2))


def test_the_recovery_planner_turns_instead_of_stepping_into_the_pit():
    from wowbot.agent.recovery_planning import RecoveryPlanner
    from wowbot.navigation.stuck_resolver import RecoveryDirective, StuckResolutionState
    directive = RecoveryDirective(StuckResolutionState.BACKWARD, "c", "BACKWARD")
    safe = RecoveryPlanner._safe_step(directive, _nav(), _state(math.pi/2))
    assert safe.action == "TURN"
    assert RecoveryPlanner._safe_step(directive, _nav(), _state(-math.pi/2)).action == "BACKWARD"


def test_route_corners_are_pushed_away_from_the_drop():
    nav = _nav()
    anchors = tuple({"x": float(x), "y": 1., "z": 25., "instance_id": 2175} for x in range(0, 41, 10))
    route = nav._away_from_drops(GlobalRoute("r", anchors, (), 1., 1., 0., 1.))
    inner = route.anchors[1:-1]
    assert all(anchor.get("drop_offset") and anchor["y"] > 5. for anchor in inner)
    assert route.anchors[0] == anchors[0] and route.anchors[-1] == anchors[-1]


def test_slipping_at_an_edge_is_stuck():
    nav = _nav()
    assert not nav._slipping_in_place(_state(0.), 1.)
    assert not nav._slipping_in_place(_state(0., x=.8), 2.)
    assert nav._slipping_in_place(_state(0., x=.3), 3.)
    # Falls spread along the route are not slipping.
    nav = _nav()
    assert not any(nav._slipping_in_place(_state(0., x=8.*k), float(k)) for k in range(4))


def test_distance_to_the_rest_of_the_route():
    nav = _nav()
    nav._active_route = GlobalRoute("r", ({"x": 0., "y": 0.}, {"x": 10., "y": 0.}), (), 1., 1., 0., 1.)
    nav._route_waypoint_index = 1
    assert nav._off_route_yards(_state(0., x=5., y=4.)) == 4.


def test_no_running_jump_with_the_drop_beside_the_character():
    """18:08:52: clear straight ahead, the pit to the side; the jump's arc
    carried the character over the edge."""
    nav = _nav()
    # Facing +x along the ledge; the pit (y < 0) is 1 yd to the right.
    assert nav.recovery_step_drops(_state(0.), "JUMP_FORWARD")
    nav._z.player = ResolvedPosition(0., 9., 25., .9, "MMAP", 2175, at=1.)
    assert not nav.recovery_step_drops(_state(0., y=9.), "JUMP_FORWARD")
