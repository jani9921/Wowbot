"""Live 2026-10-25 21:03-21:30 Skytop race runs: what stopped and misled the flights.

* 21:05:51 / 21:09:38: the race start line rooted the rider while a walk to a
  quest NPC held the attempt; it gathered "stuck" evidence and a recovery,
  and the race MOVE started 15 s after the scene;
* 21:10:05: a 65-90 yd/s glide moved > 50 yd between medium ticks; the
  "teleport" cancelled the course MOVE and reset navigation; the restarted
  MOVE began with a Surge tap that went out as a movement lease
  ("Érvénytelen movement lease") and the agent fell to MANUAL;
* 21:23: after the completed race the turn-in on the Skytop dome (server
  z 363.2) had no flight plan -- the projection chose the rock under the
  dome -- and 180 yd walked into "no navmesh route"; map markers of quests
  not in the log then drew the flying agent to Valdrakken and Ohn'ahra.
"""
import math
from types import SimpleNamespace

import pytest

from wowbot.agent.action_launch import ActionLaunchCoordinator
from wowbot.agent.models import Command, Goal, Proposal
from wowbot.agent.skyriding_control import SkyridingControl
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.execution import DispatchLane
from wowbot.navigation.flight_path import FlightPath
from wowbot.navigation.flight_route import landing_candidates, plan_flight
from wowbot.runtime import InvalidationEvent, StateInvalidationPolicy


def test_a_flight_ability_tap_at_skill_start_uses_the_discrete_lane():
    move = Proposal.make("MOVE", "course", {"x": 1., "y": 2.})
    tap = (Command("BIND", "ACTIONBUTTON1", .05),)
    assert ActionLaunchCoordinator.dispatch_lane(move, tap) is DispatchLane.DISCRETE
    assert ActionLaunchCoordinator.dispatch_lane(move, (Command("BIND", "TURNLEFT", .1),)) is DispatchLane.MOVEMENT


def flight_state(x, at, airborne):
    return {"active_quests": [], "loading": False, "map_id": 2022, "is_dead": False,
            "movement": {"flying": airborne}, "position": {"x": .5 + x/1e5, "y": .5},
            "player_world_position": {"x": x, "y": 0., "z": 300., "sample_time": at}}


def test_a_fast_glide_is_not_a_teleport_but_a_real_jump_still_is():
    policy = StateInvalidationPolicy()
    before = policy.context(flight_state(0., 10., True))
    assert policy.detect(before, policy.context(flight_state(90., 11., True))) == ()          # 90 yd/s
    assert InvalidationEvent.TELEPORT in policy.detect(before, policy.context(flight_state(600., 11., True)))
    walking = policy.context(flight_state(0., 10., False))
    assert InvalidationEvent.TELEPORT in policy.detect(walking, policy.context(flight_state(90., 11., False)))


def test_a_rooted_rider_fails_a_walk_at_once_instead_of_collecting_stuck_evidence():
    from wowbot.navigation.service import NavigationService
    nav = NavigationService()
    state = {"player_world_position": {"x": 0., "y": 0., "z": 0., "instance_id": 2444,
                                       "coordinate_space": "WORLD_YARDS"},
             "movement_rooted": {"rooted": True, "sampled_at": 100.}}
    nav.start_skill_request("MOVE", {"x": 40., "y": 0., "coordinate_space": "WORLD_YARDS",
                                     "instance_id": 2444}, state, "o1", 100.)
    result = nav.observe(state, "o2", 100.5)
    assert result.terminal and not result.success and result.reason == "player_rooted"


def test_a_ring_scene_starting_interrupts_any_other_move():
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    walk = SimpleNamespace(proposal=Proposal.make("MOVE", "npc", {"purpose": "APPROACH_SERVER_NPC", "x": 1., "y": 1.}))
    course = SimpleNamespace(proposal=Proposal.make("MOVE", "race", {"purpose": "SCENE_COURSE", "x": 1., "y": 1.}))
    state = {"packet_scene": {"active": True, "package_id": 3562, "start_position": {"x": 1821.45, "y": 46.16}},
             "player_world_position": {"x": 1821.45, "y": 46.16, "instance_id": 2444}}
    assert movement_visual_interrupt(walk, state)["kind"] == "SCENE_COURSE_STARTED"
    assert (movement_visual_interrupt(course, state) or {}).get("kind") != "SCENE_COURSE_STARTED"
    cinematic = {**state, "packet_scene": {**state["packet_scene"], "package_id": 1505}}
    assert (movement_visual_interrupt(walk, cinematic) or {}).get("kind") != "SCENE_COURSE_STARTED"


class Dome:
    """The Skytop dome: rock at 359.8 under a dome surface at 363.2; the
    navmesh has the dome top only as a nearby polygon."""

    def supports(self, instance_id):
        return True

    def terrain_height(self, instance_id, x, y):
        return 359.6, False

    def vmap_surfaces_at(self, instance_id, point):
        return [363.15, 306.95] if math.hypot(point["x"]-2448., point["y"]+1344.) < 30 else []

    def project_position(self, instance_id, point, z_hint=None):
        return {"x": point["x"], "y": point["y"], "z": 359.75}

    def walkable_points_near(self, instance_id, point, radius):
        return [{"x": 2445.76, "y": -1340.05, "z": 362.85}, {"x": 2442.1, "y": -1351.5, "z": 209.0}]


def test_the_turn_in_on_the_dome_lands_on_the_dome_layer():
    known = landing_candidates(Dome(), 2444, {"x": 2447.95, "y": -1343.77, "z": 363.23})
    assert known[0]["z"] == pytest.approx(362.85)
    plan, reason = plan_flight(Dome(), 2444, {"x": 2414., "y": -1168., "z": 345.7}, {"x": 2448., "y": -1344.},
                               min_distance=0.)
    assert reason == "planned" and plan.landing["z"] == pytest.approx(362.85)      # covered rock skipped


def test_a_known_height_without_navmesh_lands_off_mesh_and_arrives_at_touchdown():
    class Bare(Dome):
        def walkable_points_near(self, instance_id, point, radius):
            return []
    (landing,) = landing_candidates(Bare(), 2444, {"x": 2447.95, "y": -1343.77, "z": 363.23})
    assert landing["navmesh"] is False and landing["z"] == pytest.approx(363.23)
    path = FlightPath.from_dict({"instance_id": 2444, "mode": "SKYRIDING", "waypoints": [],
                                 "landing": {"x": 2447.95, "y": -1343.77, "z": 363.23},
                                 "checkpoint_conditions": [], "radius": 15., "landing_on_navmesh": False,
                                 "landing_radius": 6.})
    control = SkyridingControl(path)
    control.was_airborne = True
    far = {"is_mounted": True, "movement": {"flying": False}, "player_world_position": {"x": 2460., "y": -1343.77}}
    assert control.assess(far, 1.) == ("MOVING", "skyriding_off_mesh_relaunch")
    assert [c.binding for c in control.commands(far, 1.)] == ["JUMP"]                # lands again
    control.was_airborne = True
    near = {**far, "player_world_position": {"x": 2450., "y": -1343.77}}
    assert control.assess(near, 2.) == ("ARRIVED", "skyriding_landed_off_navmesh")


def test_on_the_drake_a_short_unwalkable_trip_flies():
    from test_skyriding_fast_control_20261025 import skyriding_world
    world, move = skyriding_world(mounted=True, yards=180.)
    (flight,) = TravelModePolicy().apply([move], Goal.parse("Questelj", 100.), world, 100.)
    assert flight.parameters["flight"] is True
    on_foot, move = skyriding_world(mounted=False, yards=180.)
    assert not TravelModePolicy().apply([move], Goal.parse("Questelj", 100.), on_foot, 100.)[0].parameters.get("flight")


def test_a_far_map_marker_of_a_quest_not_in_the_log_is_no_work():
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy()
    def world_with(x):
        return SimpleNamespace(session_id="test:far", query=SimpleNamespace(remembered_locations=lambda kinds: []),
                               state={
            "player_world_position": {"x": 2414., "y": -1168., "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
            "active_quests": [{"quest_id": 70132, "objectives": []}],
            "quest_locations": [{"quest_id": 82672, "world_position": {"x": x, "y": -975., "instance_id": 2444,
                                                                       "coordinate_space": "WORLD_YARDS"}}]})
    far = [p for p in policy.propose_known_locations(world_with(61.)) if p.parameters.get("quest_id") == 82672]
    near = [p for p in policy.propose_known_locations(world_with(2000.)) if p.parameters.get("quest_id") == 82672]
    assert far == [] and len(near) == 1
