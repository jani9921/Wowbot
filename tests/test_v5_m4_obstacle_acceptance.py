"""Executable V5 M4.8Z OBS-A through OBS-J acceptance scenarios."""

from wowbot.agent.active_perception import ActivePerception
from wowbot.navigation.contracts import ArrivalEnvelope, NavigationRequest
from wowbot.navigation.corridor import PathCorridorBuilder
from wowbot.navigation.danger import DangerMap
from wowbot.navigation.global_planner import GlobalPlanner
from wowbot.navigation.local_planner import LocalPlanner
from wowbot.navigation.progress import ProgressMonitor, ProgressPhase
from wowbot.navigation.stuck_classifier import StuckClassifier, StuckKind
from wowbot.navigation.stuck_resolver import StuckResolutionState, StuckResolver
from wowbot.vision.world3d import TemporalTraversabilityFusion


def sector(*, free=.1, blocked=.8, unknown=.1, name="CENTER", **extra):
    return {"sector": name, "free_probability": free,
            "blocked_probability": blocked, "unknown_probability": unknown,
            "evidence": ["synthetic_replay"], "fact": False, **extra}


def update(fusion, row, at, *, progress=None, motion_kind="TRANSLATION"):
    return fusion.update(
        {"coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "sectors": [row]},
        observed_at=at,
        ego_motion={"motion_kind": motion_kind},
        motion_feedback={"commanded_motion": "FORWARD", "progress_score": progress}
        if progress is not None else {})["sectors"][0]


def hard_stuck_progress(**extra):
    return {"latest": {"phase": "HARD_STUCK",
                       "sources": ["position", "optical_flow"], **extra}}


def test_obs_a_clear_path_has_free_traversability_and_positive_progress():
    fused = update(
        TemporalTraversabilityFusion(),
        sector(free=.92, blocked=.02, unknown=.06,
               free_space_confidence=.95, boundary_confidence=.02),
        1., progress=.9)
    progress = ProgressMonitor().observe_signals(
        1., optical_flow=.9, minimap_displacement=.8, movement_state=1.)

    assert fused["free_space_confidence"] >= .9
    assert fused["traversability_score"] >= .8
    assert fused["obstacle_confidence"] < .2
    assert progress.score > .7


def test_obs_b_static_wall_confirms_collision_and_static_stuck():
    fusion = TemporalTraversabilityFusion()
    raw = sector(boundary_confidence=.9, free_space_confidence=.05,
                 motion_mismatch_confidence=.9)
    first = update(fusion, raw, 1., progress=0.)
    second = update(fusion, raw, 1.1, progress=0.)
    assessment = StuckClassifier().classify(
        {"local_traversability": {"sectors": [second]}}, hard_stuck_progress())

    assert first["obstacle_lifecycle"] == "SUSPECTED"
    assert second["motion_mismatch_confidence"] >= .9
    assert second["collision_evidence_confidence"] >= .5
    assert second["state"] == "BLOCKED"
    assert assessment.supported and assessment.kind is StuckKind.STATIC_BLOCK


def test_obs_c_unknown_collision_blocks_without_semantic_class():
    fusion = TemporalTraversabilityFusion()
    raw = sector(boundary_confidence=.75, free_space_confidence=.05,
                 semantic_type="UNKNOWN")
    update(fusion, raw, 1., progress=0.)
    fused = update(fusion, raw, 1.1, progress=0.)

    assert raw["semantic_type"] == "UNKNOWN"
    assert fused["state"] == "BLOCKED"
    assert fused["obstacle_lifecycle"] == "CONFIRMED"
    assert "motion_conditioned_collision_evidence" in fused["evidence"]


def test_obs_d_camera_rotation_never_fabricates_collision():
    fused = update(
        TemporalTraversabilityFusion(),
        sector(free=.8, blocked=0., unknown=.2,
               free_space_confidence=.8, boundary_confidence=0.),
        1., progress=0., motion_kind="ROTATION")

    assert fused["collision_evidence_confidence"] == 0
    assert fused["state"] != "BLOCKED"


def test_obs_e_dynamic_npc_cost_is_temporary_and_clears():
    fusion = TemporalTraversabilityFusion()
    dynamic = sector(free=.1, blocked=.8, dynamic_probability=.9,
                     boundary_confidence=.8, free_space_confidence=.1)
    update(fusion, dynamic, 1.)
    blocked = update(fusion, dynamic, 1.1)
    clear = update(
        fusion,
        sector(free=.9, blocked=.02, unknown=.08,
               dynamic_probability=0., boundary_confidence=.02,
               free_space_confidence=.9),
        2.7)

    assert blocked["dynamic_probability"] == .9
    assert blocked["traversability_score"] < .2
    assert blocked["state"] != "BLOCKED"  # dynamic is not a static blacklist
    assert blocked["obstacle_lifecycle"] == "DYNAMIC"
    assert clear["state"] == "TRAVERSABLE"


def test_dynamic_obstacle_emits_temporary_update_event():
    fusion = TemporalTraversabilityFusion()
    result = fusion.update(
        {"coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "sectors": [
            sector(dynamic_probability=.9, boundary_confidence=.8,
                   free_space_confidence=.1)]}, observed_at=1.)

    assert result["sectors"][0]["obstacle_lifecycle"] == "DYNAMIC"
    assert result["sectors"][0]["state"] == "UNCERTAIN"
    assert any(event["event_type"] == "DYNAMIC_OBSTACLE_UPDATED"
               for event in result["events"])


def test_obs_f_cliff_is_dangerous_and_recovery_never_jumps_forward():
    fused = update(
        TemporalTraversabilityFusion(),
        sector(free=.35, blocked=.1, unknown=.55, drop_confidence=.95),
        1.)
    assessment = StuckClassifier().classify(
        {"local_traversability": {"sectors": [fused]}}, hard_stuck_progress())
    resolver = StuckResolver()
    resolver.begin("cliff:1", 1., stuck_kind=assessment.kind.value)
    actions = []
    for index in range(6):
        directive = (resolver.observe_progress(ProgressPhase.HARD_STUCK, 1.1)
                     if index == 0 else resolver.report_step_result(
                         success=False, now=1.1 + index))
        if directive.action:
            actions.append(directive.action)
        if directive.terminal:
            break

    assert fused["state"] == "DANGEROUS"
    assert assessment.kind is StuckKind.DROP_OR_CLIFF
    assert StuckResolutionState.JUMP_FORWARD.value not in actions
    assert actions[0] == StuckResolutionState.MARK_DANGER.value


def test_repeated_drop_evidence_confirms_cliff():
    fusion = TemporalTraversabilityFusion()
    row = sector(free=.35, blocked=.1, unknown=.55, drop_confidence=.95)
    first = fusion.update({"sectors": [row]}, observed_at=1.)
    second = fusion.update({"sectors": [row]}, observed_at=1.1)

    assert any(event["event_type"] == "CLIFF_SUSPECTED" for event in first["events"])
    assert any(event["event_type"] == "CLIFF_CONFIRMED" for event in second["events"])


def test_water_transition_is_evidence_and_not_automatically_blocked():
    result = TemporalTraversabilityFusion().update(
        {"coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "sectors": [
            sector(free=.8, blocked=.05, unknown=.15, water_confidence=.88,
                   terrain_transition={"type": "WATER", "risk": .25})]},
        observed_at=1.)
    fused = result["sectors"][0]

    assert fused["terrain_transition"]["type"] == "WATER"
    assert fused["terrain_transition"]["traversability_belief"] == "UNKNOWN"
    assert fused["state"] != "BLOCKED"
    assert any(event["event_type"] == "TERRAIN_TRANSITION_UPDATED"
               for event in result["events"])


def test_obs_g_narrow_doorway_retains_central_corridor():
    request = NavigationRequest(
        "door:1", "obs:door", "MOVE_TO_LOCATION", {"x": 10., "y": 0.},
        arrival=ArrivalEnvelope(radius=1.))
    state = {"position": {"x": 0., "y": 0.}}
    corridor = PathCorridorBuilder().build(GlobalPlanner().plan(request, state, 1.))
    local = {"schema": "WORLD3D_TRAVERSABILITY_V5", "sectors": [
        {"sector": "CENTER_LEFT", "state": "BLOCKED", "obstacle_lifecycle": "CONFIRMED",
         "obstacle_confidence": .9, "traversability_score": .05},
        {"sector": "CENTER", "state": "TRAVERSABLE", "obstacle_lifecycle": "CONFIRMED",
         "obstacle_confidence": .05, "traversability_score": .9},
        {"sector": "CENTER_RIGHT", "state": "BLOCKED", "obstacle_lifecycle": "CONFIRMED",
         "obstacle_confidence": .9, "traversability_score": .05},
    ]}
    plan = LocalPlanner().plan(
        {**state, "local_traversability": local}, corridor,
        destination=request.destination)

    assert plan.motion_mode == "FOLLOW_CORRIDOR"
    assert "local_bypass_preference" not in plan.local_waypoint


def test_obs_h_single_false_positive_decays_without_confirmation():
    fusion = TemporalTraversabilityFusion()
    suspected = update(fusion, sector(free=.35, blocked=.45, unknown=.2), 1.)
    clear = update(
        fusion, sector(free=.92, blocked=.01, unknown=.07,
                       boundary_confidence=.01, free_space_confidence=.92), 1.1)

    assert suspected["obstacle_lifecycle"] == "SUSPECTED"
    assert clear["obstacle_lifecycle"] == "DECAYING"
    assert clear["state"] != "BLOCKED"


def test_obs_i_repeated_failed_region_changes_route_prior():
    danger = DangerMap()
    danger.add(
        danger_id="failed:centre", kind="NAVIGATION_FAILURE",
        x=5., y=0., radius=2., cost=20., confidence=.95,
        now=1., ttl=60., source="STUCK_RESOLVER")
    request = NavigationRequest(
        "route:1", "obs:route", "MOVE_TO_LOCATION", {"x": 10., "y": 0.},
        avoid_combat=True)
    route = GlobalPlanner().plan(
        request, {"position": {"x": 0., "y": 0.}}, 2., danger_map=danger)

    assert len(route.anchors) == 3
    assert route.anchors[1]["danger_detour"] == "failed:centre"
    assert route.regions[0]["danger_adapted"] is True


def test_obs_j_active_perception_probe_is_bounded_and_terminal():
    perception = ActivePerception()
    perception.request_probe(
        probe_id="obstacle:1", track_id="WORLD3D:obstacle",
        baseline_confidence=.5, at=1.)
    perception.select_probe_action("small_camera_turn", at=1.1)
    perception.mark_probe_dispatched(at=1.2, timeout=.3)
    result = perception.evaluate_probe(at=1.3, confidence=.7)

    assert result["state"] == "SUCCESS"
    assert result["history"][-1]["result"] == "confidence_increased"
    assert result["action_authority"] == "NONE"
    assert result["input_sent"] is False
