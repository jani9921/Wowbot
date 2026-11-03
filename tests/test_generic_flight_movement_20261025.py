"""Task-independent flight/ground phases and declarative verification."""
from copy import deepcopy
from types import SimpleNamespace
import ast
from pathlib import Path

import pytest

from wowbot.agent.models import Goal, Proposal
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.navigation.flight_path import FlightPath
from wowbot.navigation.flight_route import FlightPlan
from wowbot.navigation.service import NavigationService
from wowbot.verification.conditions import evaluate_condition
from test_skyriding_landing_handoff_20261025 import WalkingMesh


def condition(key, minimum=1):
    return {"kind": "COUNTER_AT_LEAST", "minimum": minimum,
            "paths": [{"path": ["route_counters", key]}]}


def path(offset=0):
    return FlightPath.from_dict({"instance_id": 42, "mode": "SKYRIDING",
        "waypoints": [{"x": offset+10, "y": 0, "z": 10}, {"x": offset+20, "y": 10, "z": 10}],
        "landing": {"x": offset+30, "y": 10, "z": 0},
        "checkpoint_conditions": [condition("alpha"), condition("beta")], "arrival_condition": condition("done")})


def scene(at=10, offset=0, *, airborne=False, counters=None):
    return {"session_id": "test:generic", "monotonic_time": at, "is_mounted": True,
            "orientation": 0., "movement": {"flying": airborne, "falling": False},
            "route_counters": counters or {}, "map_id": 123,
            "player_world_position": {"x": offset+21., "y": 10., "z": 0., "z_observed": True,
                "coordinate_space": "WORLD_YARDS", "instance_id": 42, "sample_time": at}}


def destination(route):
    return {**route.landing, "flight_path": route.to_dict(), "instance_id": 42,
            "coordinate_space": "WORLD_YARDS", "stop_distance": route.radius}


@pytest.mark.parametrize("offset", [0, 1000, -350])
def test_any_route_uses_the_same_ground_handoff_without_quests_or_lesson_ids(offset):
    nav = NavigationService(navmesh=WalkingMesh())
    route = path(offset)
    nav.start_skill_request("MOVE", destination(route), scene(offset=offset, airborne=True), "same-owner", 10.)
    before = nav._active_request.correlation_id
    ground = scene(11, offset, counters={"alpha": 1, "beta": 1})
    assessment = nav.observe(ground, "ground", 11.)
    assert not assessment.terminal and nav._movement.flight is None
    assert nav._active_request.correlation_id == before
    assert nav._active_request.destination["require_navmesh"] is True
    assert any(c.binding == "MOVEFORWARD" for c in nav.command(ground, "ground", 11.))


def test_air_checkpoint_cannot_be_skipped_merely_because_player_is_grounded():
    nav = NavigationService(navmesh=WalkingMesh())
    nav.start_skill_request("MOVE", destination(path()), scene(counters={"alpha": 1}), "route", 10.)
    assert nav._movement.flight is not None


def test_ground_request_is_chosen_at_start_when_the_required_air_segment_is_already_verified():
    nav = NavigationService(navmesh=WalkingMesh())
    nav.start_skill_request("MOVE", destination(path()), scene(counters={"alpha": 1, "beta": 1}), "route", 10.)
    assert nav._movement.flight is None and nav._active_request.destination["require_navmesh"]


def test_steady_flight_touchdown_uses_the_same_ground_controller_without_retakeoff():
    nav = NavigationService(navmesh=WalkingMesh())
    state = scene()
    plan = FlightPlan(42, {"x": 0., "y": 0., "z": 0.}, {"x": 30., "y": 10., "z": 0.},
                      30., ((0., 0.), (30., 0.)))
    # The steady flight leg is already planned by the shared geometry planner.
    nav.start_skill_request("MOVE", {"x": 30., "y": 10., "z": 0., "instance_id": 42,
        "coordinate_space": "WORLD_YARDS", "flight_plan": plan.to_dict()}, state, "steady", 10.)
    from wowbot.agent.flight_control import FlightControl
    nav._movement.flight = FlightControl(plan)
    nav._movement.flight.phase = "CRUISE"
    from dataclasses import replace
    nav._active_route = replace(nav._active_route, anchors=(*nav._active_route.anchors[:-1],
                              {**nav._active_route.anchors[-1], "flight_plan": plan.to_dict()}))
    nav.observe(scene(11), "touchdown", 11.)
    assert nav._movement.flight is None
    assert all(c.binding != "JUMP" for c in nav.command(scene(11), "touchdown", 11.))


def test_mounted_ordinary_move_never_becomes_a_flight_without_a_validated_flight_route():
    nav = NavigationService(navmesh=WalkingMesh())
    state = scene()
    nav.start_skill_request("MOVE", {"x": 100., "y": 10., "instance_id": 42,
        "coordinate_space": "WORLD_YARDS", "require_navmesh": True}, state, "walk", 10.)
    assert nav._movement.flight is None
    assert all(c.binding not in {"JUMP", "PITCHUP", "PITCHDOWN"} for c in nav.command(state, "walk", 10.))


def test_geometry_does_not_fabricate_a_required_arrival_signal():
    nav = NavigationService(navmesh=WalkingMesh())
    state = scene(counters={"alpha": 1, "beta": 1})
    state["player_world_position"].update(path().landing)
    nav.start_skill_request("MOVE", destination(path()), state, "verify", 10.)
    assessment = nav.observe(state, "arrived", 10.1)
    assert not assessment.terminal and assessment.reason == "awaiting_arrival_evidence"
    assert nav.command(state, "arrived", 10.1) == ()
    state["route_counters"]["done"] = 1
    assessment = nav.observe(state, "verified", 10.2)
    assert assessment.terminal and assessment.success


@pytest.mark.parametrize("value, expected", [(None, None), (False, None), (0, False), (1, True), (2, True)])
def test_declarative_conditions_distinguish_unknown_from_confirmed(value, expected):
    before = {"route_counters": {"x": value}}
    frozen = deepcopy(before)
    assert evaluate_condition(condition("x"), before) is expected
    assert before == frozen


def test_mount_selection_is_in_shared_travel_policy_for_a_nonquest_path():
    state = scene()
    state.update(is_mounted=False, mount_capability={"has_collected_mount": True, "riding_capability_confirmed": True},
                 actionbar=[{"kind": "summonmount", "id": 99, "action": "MULTIACTIONBAR1BUTTON1",
                    "binding_primary": "F4", "is_usable": True,
                    "mount": {"mount_type_id": 402, "mount_usable": True}}])
    candidates = [Proposal.make("MOVE", "generic route", destination(path()), priority=50)]
    proposals = TravelModePolicy().apply(candidates, Goal.parse("Menj oda", 10.), SimpleNamespace(state=state), 10.)
    assert next(p for p in proposals if p.skill == "MOUNT").parameters["binding"] == "MULTIACTIONBAR1BUTTON1"


def test_movement_implementation_never_imports_a_quest_adapter():
    root = Path(__file__).parents[1] / "src/wowbot"
    for relative in ["agent/skyriding_control.py", "agent/movement_controller.py", "navigation/service.py"]:
        source = (root / relative).read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any("quests" in item or "lesson" in item for item in imports)
        assert "skyriding_lesson_planning" not in source


@pytest.mark.parametrize("change", [{"sample_time": 8.}, {"sample_time": 11.}, {"instance_id": 99},
                                    {"sample_time": None}])
def test_geometric_checkpoint_needs_current_same_instance_measurement(change):
    route = FlightPath.from_dict({"mode": "SKYRIDING", "instance_id": 42,
        "waypoints": [{"x": 10, "y": 0, "z": 10}], "landing": {"x": 30, "y": 0, "z": 0}})
    state = {"monotonic_time": 10., "player_world_position": {
        "x": 10, "y": 0, "z": 10, "instance_id": 42, "sample_time": 10.}}
    assert route.progress(state) == 1
    state["player_world_position"].update(change)
    assert route.progress(state) == 0


def test_new_air_path_at_same_destination_cannot_reuse_previous_checkpoint_index():
    from wowbot.agent.movement_controller import ReachMovementController
    controller = ReachMovementController()
    original = path()
    controller.start(destination(original), scene(airborne=True), "first", 10.)
    controller.flight.index = 1
    changed = original.to_dict()
    changed["waypoints"][0]["x"] = 100.
    replacement = FlightPath.from_dict(changed)
    controller.start(destination(replacement), scene(11, airborne=True), "second", 11.)
    assert controller.flight.path.identity == replacement.identity
    assert controller.flight.index == 0
    controller.start({k: v for k, v in destination(replacement).items() if k != "flight_path"},
                     scene(12), "walk", 12.)
    assert controller.flight is None


def test_invalid_declarative_path_is_rejected_as_invalid_evidence():
    with pytest.raises(ValueError):
        evaluate_condition({"kind": "COUNTER_AT_LEAST", "minimum": 1,
                            "paths": [{"path": [{"field": "x", "equals": 1}]}]}, {})
