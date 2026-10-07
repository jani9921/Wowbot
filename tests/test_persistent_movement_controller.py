import math

from wowbot.agent.movement_controller import MovementPhase, ReachMovementController
from test_agent_core import agent, state


DESTINATION = {"map_id": 1609, "x": .5, "y": .4}


def moving_state(at, y=.5, *, speed=0., moving=False, orientation=0., candidates=()):
    return state(at, position={"x": .5, "y": y}, orientation=orientation,
                 movement={"speed": speed, "moving": moving},
                 visual_candidates=list(candidates))


def test_reach_keeps_one_high_level_attempt_across_control_pulses():
    bot, executor = agent("Menj oda", {"destination": DESTINATION})
    bot.tick(moving_state(1), 1)
    action_id = bot.pending.action_id
    plan_id = bot.pending.plan_id
    bot.tick(moving_state(1.3, .4995, speed=7., moving=True), 1.3)
    bot.tick(moving_state(1.6, .4990, speed=7., moving=True), 1.6)
    assert len(executor.commands) == 3
    assert bot.pending.action_id == action_id
    assert bot.pending.plan_id == plan_id
    assert bot.movement.phase == MovementPhase.MOVING
    assert bot.goal.completed_steps == 0


def test_one_action_budget_counts_reach_once_not_each_control_update():
    bot, executor = agent("Menj oda", {"destination": DESTINATION})
    bot.action_budget = 1
    bot.tick(moving_state(1), 1)
    action_id = bot.pending.action_id
    assert bot.action_budget == 0
    bot.tick(moving_state(1.3, .4995, speed=7., moving=True), 1.3)
    bot.tick(moving_state(1.6, .4990, speed=7., moving=True), 1.6)
    assert bot.mode.value == "FULL_AI"
    assert bot.pending.action_id == action_id
    assert len(executor.commands) == 3


def test_fast_movement_lane_uses_canonical_navigation_without_world_fusion():
    bot, executor = agent("Menj oda", {"destination": DESTINATION})
    bot.tick(moving_state(1), 1)
    original_world_observation = bot.world.latest.observation_id
    before = len(executor.commands)
    fast = moving_state(1.05, .499, speed=7., moving=True) | {
        "transport_kind": "FAST", "fast_sequence": 2,
    }

    result = bot.fast_movement_control(fast, 1.05)

    assert result["consumed"] is True
    assert len(executor.commands) == before + 1
    assert bot.world.latest.observation_id == original_world_observation
    assert bot.pending is not None and bot.pending.proposal.skill == "MOVE"


def test_one_fast_observation_can_refresh_at_most_one_movement_lease():
    bot, executor = agent("Menj oda", {"destination": DESTINATION})
    bot.tick(moving_state(1), 1)
    fast = moving_state(1.05, .499, speed=7., moving=True) | {
        "transport_kind": "FAST", "fast_sequence": 2,
    }
    bot.fast_movement_control(fast, 1.05)
    after_first = len(executor.commands)

    repeated = bot.fast_movement_control(fast, 1.06)

    assert repeated["consumed"] is True
    assert repeated["dispatched"] is False
    assert len(executor.commands) == after_first


def test_turning_without_translation_is_control_progress_not_stuck():
    controller = ReachMovementController()
    controller.start({"map_id": 1609, "x": .7, "y": .5}, moving_state(1), "o1", 1)
    controller.command(moving_state(1), "o1", 1)
    for index, facing in enumerate((.15, .3, .45, .6, .75), 2):
        result = controller.observe(moving_state(index*.3, orientation=facing), f"o{index}", index*.3)
    assert result.phase == MovementPhase.STEERING
    assert not result.terminal
    assert controller.snapshot()["no_progress_samples"] == 0


def test_stuck_requires_repeated_time_separated_multi_source_evidence():
    controller = ReachMovementController()
    controller.start(DESTINATION, moving_state(1), "o1", 1)
    controller.command(moving_state(1), "o1", 1)
    phases = []
    for index, at in enumerate((1.4, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6), 2):
        result = controller.observe(moving_state(at), f"o{index}", at)
        phases.append(result.phase)
        if not result.terminal:
            controller.command(moving_state(at), f"o{index}", at)
    assert phases[0] == MovementPhase.NO_PROGRESS_YET
    assert MovementPhase.CANDIDATE_STUCK in phases
    assert phases[-1] == MovementPhase.SUPPORTED_STUCK
    assert result.terminal and not result.success
    assert set(controller.snapshot()["stuck_evidence_sources"]) == {
        "MOTION_TELEMETRY_STOPPED", "POSITION_NO_PROGRESS"}


def test_high_rate_observations_cannot_overwrite_stuck_time_window():
    controller = ReachMovementController()
    controller.start(DESTINATION, moving_state(1), "o0", 1)
    controller.command(moving_state(1), "o0", 1)
    result = None
    # Reproduce the live 40 Hz path. The temporal evidence must retain the
    # V5 hard-stuck window rather than letting high-rate frames overwrite it.
    for index in range(1, 180):
        at = 1 + index * .025
        result = controller.observe(moving_state(at), f"o{index}", at)
        if result.terminal:
            break
        controller.command(moving_state(at), f"o{index}", at)
    assert result is not None
    assert result.phase == MovementPhase.SUPPORTED_STUCK
    assert result.reason == "supported_stuck"
    assert controller.snapshot()["progress"]["latest"]["phase"] == "HARD_STUCK"


def test_running_animation_and_soft_steering_cannot_mask_wall_contact():
    """Regression for the post-combat resume wall loop on 2026-09-28."""
    controller = ReachMovementController()
    initial = moving_state(1, speed=7., moving=True, orientation=.32)
    controller.start(DESTINATION, initial, "o0", 1.)
    controller.command(initial, "o0", 1.)
    result = None
    # Retail continued to report moving=true/speed=7 while world position was
    # frozen. Alternating soft steering must not reset physical no-progress.
    for index, at in enumerate((1.4, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6), 1):
        sample = moving_state(
            at, speed=7., moving=True,
            orientation=.32 if index % 2 else -.32)
        result = controller.observe(sample, f"o{index}", at)
        if result.terminal:
            break
        controller.command(sample, f"o{index}", at)
    assert result is not None
    assert result.phase == MovementPhase.SUPPORTED_STUCK
    assert result.reason == "supported_stuck"
    snapshot = controller.snapshot()
    assert "MOTION_POSITION_MISMATCH" in snapshot["stuck_evidence_sources"]
    assert snapshot["progress"]["latest"]["phase"] == "HARD_STUCK"


def test_agent_only_selects_recover_after_supported_stuck():
    bot, executor = agent("Menj oda", {"destination": DESTINATION})
    bot.tick(moving_state(1), 1)
    for index, at in enumerate((1.4, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6), 2):
        bot.tick(moving_state(at), at)
    assert bot.last_result["skill"] == "MOVE"
    assert bot.last_result["reason"] == "supported_stuck"
    # A hard-stuck report starts with an evidence-gathering stop, not a blind
    # strafe. The independent resolver unlocks BACKWARD only after that fresh
    # observation still confirms the stuck condition.
    assert bot.last_decision["skill"] == "WAIT"
    assert bot.navigation.snapshot(4.6)["stuck_resolver"]["state"] == "STOP_AND_OBSERVE"


def test_arrival_not_first_small_progress_completes_reach():
    bot, executor = agent("Menj oda", {"destination": DESTINATION})
    bot.tick(moving_state(1), 1)
    bot.tick(moving_state(1.3, .49, speed=7., moving=True), 1.3)
    assert bot.pending is not None and bot.goal.completed_steps == 0
    assert bot.supervisor.snapshot()["state"] == "NAVIGATION"
    progress = bot.navigation.snapshot(1.3)["movement"]["progress"]["latest"]
    assert progress["score"] > .35
    bot.tick(moving_state(1.6, .402, speed=7., moving=True), 1.6)
    assert bot.pending is None
    assert bot.last_result["outcome"] == "SUCCESS"
    assert bot.last_result["reason"] == "reach_arrival_verified"
    event_types = {entry["event_type"] for entry in bot.structured_logger.snapshot(64)}
    assert "POSSIBLE_STUCK" not in event_types
    assert "STUCK_DETECTED" not in event_types


def test_reached_quest_poi_is_not_reissued_after_camera_observation_drift():
    bot, _ = agent()
    quest = {"quest_id": 55122, "objectives": [{
        "type": "COLLECT", "raw_type": "item",
        "description": "0/6 First Aid Kits recovered from defeated Murlocs",
        "current": 0, "required": 6}]}
    poi = {"quest_id": 55122, "map_id": 1609, "x": .5, "y": .4,
           "source": "QUEST_POI", "coordinate_space": "NORMALIZED_MAP"}
    bot.tick(state(1, position={"x": .5, "y": .409}, orientation=0.,
                   active_quests=[quest], quest_locations=[poi]), 1)
    assert bot.pending and bot.pending.proposal.skill == "MOVE"
    bot.tick(state(2, position={"x": .5, "y": .407}, orientation=0.,
                   active_quests=[quest], quest_locations=[poi]), 2)
    assert bot.last_result["skill"] == "MOVE"
    assert bot.last_result["outcome"] == "SUCCESS"
    assert bot.last_decision["skill"] != "MOVE"
    bot.tick(state(3, position={"x": .5, "y": .412}, orientation=0.,
                   active_quests=[quest], quest_locations=[poi]), 3)
    assert bot.last_decision["skill"] != "MOVE"


def test_stale_frame_never_accumulates_stuck_evidence():
    controller = ReachMovementController()
    controller.start(DESTINATION, moving_state(1), "same", 1)
    for at in (2, 3, 4, 5):
        result = controller.observe(moving_state(at), "same", at)
    assert result.reason == "awaiting_fresh_progress_observation"
    assert controller.snapshot()["no_progress_samples"] == 0


def object_state(at, player_x, target_x=110., orientation=0.):
    return moving_state(at, orientation=orientation) | {
        "player_world_position": {"x": player_x, "y": 100., "z": 3.,
                                  "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "target": {"guid": "jaina", "dead": False,
                   "world_position": {"x": target_x, "y": 100., "z": 3.,
                                      "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}},
    }


def test_reach_object_tracks_live_endpoint_and_arrives_in_yards():
    destination = {"target_guid": "jaina", "x": 110., "y": 100.,
                   "coordinate_space": "WORLD_YARDS", "stop_distance": 4.5}
    controller = ReachMovementController()
    controller.start(destination, object_state(1, 100.), "o1", 1)
    assert not controller.observe(object_state(2, 103., target_x=111.), "o2", 2).terminal
    assert controller.destination["x"] == 111.
    result = controller.observe(object_state(3, 107., target_x=111.), "o3", 3)
    assert result.terminal and result.success
    assert result.reason == "reach_arrival_verified"


def test_large_heading_error_turns_in_place_then_hysteresis_allows_forward():
    destination = {"target_guid": "jaina", "x": 110., "y": 100.,
                   "coordinate_space": "WORLD_YARDS", "stop_distance": 4.5}
    controller = ReachMovementController()
    wrong = object_state(1, 100., orientation=math.pi)
    controller.start(destination, wrong, "o1", 1)
    command = controller.command(wrong, "o1", 1)[0]
    assert command.binding in {"TURNLEFT", "TURNRIGHT"}
    assert command.simultaneous == ()
    aligned = object_state(2, 100., orientation=0.)
    controller.observe(aligned, "o2", 2)
    command = controller.command(aligned, "o2", 2)[0]
    assert command.binding == "MOVEFORWARD"


def test_turn_leases_are_short_and_heading_overshoot_is_damped():
    destination = {"target_guid": "jaina", "x": 110., "y": 100.,
                   "coordinate_space": "WORLD_YARDS", "stop_distance": 4.5}
    controller = ReachMovementController()
    first = object_state(1, 100., orientation=math.pi)
    controller.start(destination, first, "o1", 1)
    initial = controller.command(first, "o1", 1)[0]
    assert initial.duration <= .12
    # Desired heading is zero. Crossing from positive to negative wrapped
    # error is authoritative evidence that the previous correction overshot.
    before = object_state(2, 100., orientation=.35)
    controller.observe(before, "o2", 2)
    controller.command(before, "o2", 2)
    after = object_state(3, 100., orientation=math.tau-.35)
    controller.observe(after, "o3", 3)
    damped = controller.command(after, "o3", 3)[0]
    assert controller.steering_reversals == 1
    assert controller.turn_duration_scale < 1.
    assert damped.duration <= .08


def test_reach_object_target_identity_change_is_terminal_not_blind_motion():
    destination = {"target_guid": "jaina", "x": 110., "y": 100.,
                   "coordinate_space": "WORLD_YARDS", "stop_distance": 4.5}
    controller = ReachMovementController()
    controller.start(destination, object_state(1, 100.), "o1", 1)
    changed = object_state(2, 100.)
    changed["target"]["guid"] = "other"
    result = controller.observe(changed, "o2", 2)
    assert result.terminal and not result.success
    assert result.reason == "reach_object_identity_or_position_lost"


def test_fast_combat_or_death_transition_stops_movement_immediately():
    # Issue #70: a FAST combat/death transition must not keep the reach going
    # until the next medium tick.
    for transition in ({"is_in_combat": True}, {"is_dead": True}, {"is_ghost": True}):
        bot, executor = agent("Menj oda", {"destination": DESTINATION})
        bot.tick(moving_state(1), 1)
        before = len(executor.commands)
        fast = moving_state(1.05, .499, speed=7., moving=True) | {
            "transport_kind": "FAST", "fast_sequence": 2, **transition}
        result = bot.fast_movement_control(fast, 1.05)
        assert result == {"consumed": False, "force_medium": True,
                          "reason": "fast_combat_or_death_transition"}
        assert len(executor.commands) == before


def test_fast_movement_already_in_combat_is_not_a_transition():
    # A reach the medium loop kept running while the world model already
    # knows about combat (e.g. a planner-approved LOS move) is not preempted.
    bot, executor = agent("Menj oda", {"destination": DESTINATION})
    bot.tick(moving_state(1), 1)
    assert bot.pending is not None and bot.pending.proposal.skill == "MOVE"
    bot.world.state["is_in_combat"] = True
    fast = moving_state(1.05, .499, speed=7., moving=True) | {
        "transport_kind": "FAST", "fast_sequence": 2, "is_in_combat": True}
    assert bot.fast_movement_control(fast, 1.05)["consumed"] is True
