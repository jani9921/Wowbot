"""Live 2026-10-04 09:09: the character walked into a rock; BACKWARD did not
move it and the ladder chose JUMP_FORWARD, but the planner's next query got
"awaiting step result" without an action, so SEEK and a fresh MOVE into the
same rock ran instead of the jump."""
from pathlib import Path
import tempfile

from test_agent_core import binding_file

from wowbot.agent.bindings import BindingsCache
from wowbot.navigation import ProgressPhase
from wowbot.navigation.service import NavigationService


def test_ladder_step_chosen_on_failure_is_handed_to_the_next_query():
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))))
    nav.begin_stuck_recovery("move-1", 1.)
    first = nav._stuck.observe_progress(ProgressPhase.HARD_STUCK, 2.)
    assert first.action == "BACKWARD"
    chosen = nav.report_recovery_result(success=False, now=3.)
    assert chosen.action == "JUMP_FORWARD"
    handed = nav.next_stuck_recovery("recover-1", 3.5, {})
    assert handed.action == "JUMP_FORWARD"
    # Handed out once: asking again without a result does not repeat it.
    assert nav.next_stuck_recovery("recover-1", 3.6, {}).action is None


def test_stuck_obstacle_is_marked_without_an_active_route_and_detoured():
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))))
    state = {"player_world_position": {"x": 0., "y": 0., "instance_id": 2175,
                                       "coordinate_space": "WORLD_YARDS"}, "orientation": 0.}
    assert nav.mark_current_route_danger(state, 10., correlation_id="stuck:move-1")
    danger = nav._danger
    assert danger.has_navigation_failures(11.)
    # The next straight route through the rock (just ahead, +x) gets a detour.
    anchors = ({"x": -5., "y": 0.}, {"x": 30., "y": 0.})
    detoured = danger.avoidance_anchors(anchors, 11.)
    assert len(detoured) == 3 and abs(detoured[1]["y"]) > 3.
