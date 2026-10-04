from test_agent_core import state
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel
from wowbot.navigation.service import NavigationService


def test_navigation_service_owns_active_movement_and_route_components():
    service = NavigationService()
    world = WorldModel()
    world.ingest(Observation.create(state(1, position={"x": .1, "y": .1}, orientation=0), 1))
    destination = {"map_id": world.state["map_id"], "x": .2, "y": .1}
    service.start(destination, world.state, world.latest.observation_id, 1)
    assessment = service.observe(world.state, world.latest.observation_id + ":next", 1.1)
    assert assessment.phase.value in {"MOVING", "STEERING", "NO_PROGRESS_YET"}
    snapshot = service.snapshot(1.1)
    assert snapshot["authority"] == "NavigationService"
    assert "route" in snapshot and "movement" in snapshot
    assert snapshot["movement"]["progress"]["phase"] in {"MAKING_PROGRESS", "UNAVAILABLE"}


def test_navigation_service_local_combat_correction_requires_matching_visual_target():
    service = NavigationService()
    request = {"expected_guid": "mob-1", "reason": "LINE_OF_SIGHT",
               "target_screen_x": .72, "target_screen_y": .48}
    live = {"target": {"guid": "mob-1"}}
    command = service.local_combat_reposition(live, request)
    assert command and command[0].binding == "STRAFERIGHT"
    assert .30 <= command[0].duration <= .35
    assert service.snapshot(1.)["los_recovery"]["phase"] == "TRY_LATERAL_A"
    assert service.local_combat_reposition({"target": {"guid": "other"}}, request) == ()


def test_navigation_service_executes_bounded_combat_track_follow_and_reacquire():
    service = NavigationService()
    live = {"target": {"guid": "mob-1"}}
    follow = {"expected_guid": "mob-1", "reason": "COMBAT_TRACK_FOLLOW",
              "target_screen_x": .8, "target_screen_y": .5}
    commands = service.local_combat_reposition(live, follow)
    assert commands[0].binding == "TURNRIGHT"
    assert .035 <= commands[0].duration <= .09

    reacquire = {**follow, "reason": "COMBAT_TRACK_REACQUIRE",
                 "target_screen_x": .2}
    commands = service.local_combat_reposition(live, reacquire)
    assert commands[0].binding == "TURNLEFT"
    assert commands[0].duration == .075

    approach = {**follow, "reason": "COMBAT_TRACK_APPROACH"}
    commands = service.local_combat_reposition(live, approach)
    assert commands[0].binding == "MOVEFORWARD"
    assert commands[0].simultaneous == ("TURNRIGHT",)


def test_facing_recovery_never_invents_turn_direction_for_centered_anchor():
    service = NavigationService()
    request = {"expected_guid": "mob-1", "reason": "FACING_WRONG_WAY",
               "target_screen_x": .5, "target_screen_y": .5}
    assert service.local_combat_reposition(
        {"target": {"guid": "mob-1", "screen_position": {"x": .5}}}, request) == ()


def test_move_to_entity_requires_live_matching_identity_and_same_instance_coordinates():
    service = NavigationService()
    live = {
        "target": {"guid": "npc-1", "world_position": {"x": 19., "y": 11., "z": 2., "instance_id": 4}},
        "player_world_position": {"x": 2., "y": 3., "z": 2., "instance_id": 4},
        "orientation": 0.,
    }
    destination = service.move_to_entity(live, "npc-1", "obs-1", 1.)
    assert destination is not None
    assert destination["target_guid"] == "npc-1"
    assert destination["coordinate_space"] == "WORLD_YARDS"
    assert service.movement_snapshot()["destination"]["target_guid"] == "npc-1"
    assert service.move_to_entity(live, "other", "obs-2", 2.) is None
    wrong_instance = {**live, "player_world_position": {"x": 2., "y": 3., "instance_id": 9}}
    assert service.move_to_entity(wrong_instance, "npc-1", "obs-3", 3.) is None


def test_move_to_entity_refuses_a_stale_target_position_sample():
    service = NavigationService()
    stale = {
        "monotonic_time": 10., "target_sample_time": 7.,
        "target": {"guid": "npc-1", "world_position": {"x": 19., "y": 11., "instance_id": 4}},
        "player_world_position": {"x": 2., "y": 3., "instance_id": 4}, "orientation": 0.,
    }
    assert service.move_to_entity(stale, "npc-1", "obs-stale", 10.) is None

    fresh = {**stale, "target_sample_time": 10.}
    assert service.move_to_entity(fresh, "npc-1", "obs-fresh", 10.) is not None


def test_move_to_entity_refreshes_the_same_reach_when_selected_target_moves():
    service = NavigationService()
    live = {
        "target": {"guid": "npc-1", "world_position": {"x": 19., "y": 11., "instance_id": 4}},
        "player_world_position": {"x": 2., "y": 3., "instance_id": 4}, "orientation": 0.,
    }
    assert service.move_to_entity(live, "npc-1", "obs-1", 1.) is not None
    moved = {**live, "target": {"guid": "npc-1",
                                 "world_position": {"x": 23., "y": 16., "instance_id": 4}}}
    assessment = service.observe(moved, "obs-2", 1.2)
    assert not assessment.terminal
    destination = service.movement_snapshot()["destination"]
    assert (destination["x"], destination["y"]) == (23., 16.)


def test_move_to_entity_allows_confirmed_corpse_only_for_loot_callers():
    service = NavigationService()
    corpse = {
        "target": {"guid": "corpse-1", "dead": True,
                   "world_position": {"x": 19., "y": 11., "instance_id": 4}},
        "player_world_position": {"x": 2., "y": 3., "instance_id": 4}, "orientation": 0.,
    }
    assert service.move_to_entity(corpse, "corpse-1", "dead-1", 1.) is None
    destination = service.move_to_entity(corpse, "corpse-1", "dead-2", 1., allow_dead=True)
    assert destination and destination["target_guid"] == "corpse-1"


def test_stuck_local_waypoint_reuses_only_validated_navigation_geometry():
    service = NavigationService()
    live = {"map_id": 1, "position": {"x": .1, "y": .1}, "orientation": 0.}
    service.start_skill_request(
        "MOVE", {"map_id": 1, "x": .8, "y": .7}, live, "obs:1", 1.)
    service.begin_stuck_recovery("stuck:1", 1.1, live)
    waypoint = service.new_local_recovery_waypoint(live, "obs:2", 1.2)
    assert waypoint is not None
    assert waypoint["_stuck_recovery_waypoint"] is True
    assert waypoint["stuck_correlation"] == "stuck:1"
    assert isinstance(waypoint["x"], float) and isinstance(waypoint["y"], float)


def test_stuck_stop_and_observe_uses_one_fresh_stationary_telemetry_frame():
    service = NavigationService()
    blocked = {
        "frame_id": "frame:1", "monotonic_time": 1.,
        "position": {"x": .5, "y": .5},
        "movement": {"moving": False, "speed": 0.},
    }
    first = service.next_stuck_recovery("move:blocked", 1., blocked)
    assert first.action == "STOP_AND_OBSERVE"

    # Re-reading the same frame is not independent confirmation.
    repeated = service.next_stuck_recovery("move:blocked", 1., blocked)
    assert repeated.action is None

    fresh = {**blocked, "frame_id": "frame:2", "monotonic_time": 1.6}
    recovery = service.next_stuck_recovery("move:blocked", 1.6, fresh)
    assert recovery.action == "BACKWARD"


def test_stuck_stop_and_observe_cancels_recovery_when_fresh_position_progresses():
    service = NavigationService()
    blocked = {
        "frame_id": "frame:1", "monotonic_time": 1.,
        "position": {"x": .5, "y": .5},
        "movement": {"moving": False, "speed": 0.},
    }
    service.next_stuck_recovery("move:blocked", 1., blocked)
    progressed = {
        **blocked, "frame_id": "frame:2", "monotonic_time": 1.6,
        "position": {"x": .501, "y": .5},
    }
    result = service.next_stuck_recovery("move:blocked", 1.6, progressed)
    assert result.terminal is True
    assert result.reason == "STUCK_RECOVERED"
    assert service.stuck_recovery_active is False
