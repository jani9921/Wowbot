"""15:33 live regression: land, delayed credit, relaunch, unreachable overshoot."""
from copy import deepcopy
import math
from types import SimpleNamespace

import pytest

from test_active_pointer_tracking import attempt
from test_skyriding_lesson_wiring_20261025 import lesson_state
from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.fast_movement_lane import advance_fast_movement
from wowbot.agent.models import Mode, Observation
from wowbot.agent.skyriding_control import SkyridingControl
from wowbot.quests.client_catalog import ClientCatalog
from wowbot.quests.scene_path_planning import QuestScenePathPolicy, course_path
from wowbot.agent.turnin_resolver import TurnInResolver
from wowbot.navigation.mmap_navmesh import NavMeshPath
from wowbot.navigation.service import NavigationService

COURSE = ClientCatalog().courses()["65118"]
TARGET = COURSE["target"][:3]


def landed(*, airborne=False, rings=5, credited=False, at=100.):
    state = lesson_state(mounted=True, rings=rings, airborne=airborne)
    state.update(session_id="test:landing", frame_id=f"f:{at}", timestamp=at, monotonic_time=at)
    point = {**state["player_world_position"], "x": 2216.31445, "y": 80.45276,
             "z": 150.36 if airborne else 143.26, "sample_time": at}
    state["player_world_position"] = point
    state["orientation"] = math.atan2(TARGET[1]-point["y"], TARGET[0]-point["x"])
    state["packet_flight"].update(sample_time=at, adv_flying=airborne, flying=False,
                                  falling=False, position=deepcopy(point), facing=state["orientation"])
    if credited:
        state["packet_quest_credits"]["65118"]["182847"] = {"count": 1}
        state["active_quests"][0]["is_complete"] = True
    return state


def controller():
    return SkyridingControl(course_path(COURSE))


def test_touchdown_after_all_rings_never_relaunches_while_target_credit_lags():
    flight = controller()
    state = landed()
    flight.assess(state, 100.)
    assert flight.commands(state, 100.) == ()
    assert state["active_quests"][0].get("is_complete") is not True


def test_final_approach_never_uses_an_ascent_boost():
    flight = controller()
    state = landed(airborne=True)
    state["packet_flight"]["forward_velocity"] = 1.
    state["packet_flight"]["position"]["z"] = 140.
    flight.assess(state, 100.)
    assert all(c.binding != "JUMP" for c in flight.commands(state, 100.))


def test_credited_airborne_landing_turns_back_toward_the_target():
    flight = controller()
    state = landed(airborne=True, credited=True)
    state["packet_flight"]["position"]["x"] = 2301.54
    state["packet_flight"]["facing"] = 0.
    flight.assess(state, 100.)
    commands = flight.commands(state, 100.)
    assert any(c.binding in {"TURNLEFT", "TURNRIGHT"} or
               set(c.simultaneous) & {"TURNLEFT", "TURNRIGHT"} for c in commands)


def test_landing_timeout_is_failure_rather_than_airborne_arrival():
    flight = controller()
    flight.assess(landed(airborne=True, credited=True), 100.)
    assert flight.assess(landed(airborne=True, credited=True, at=126.), 126.) == (
        "FAILED", "skyriding_landing_timeout")


def test_mount_walks_the_remaining_landing_area_when_all_rings_are_done():
    (proposal,) = QuestScenePathPolicy().propose(landed())
    assert proposal.skill == "MOVE" and proposal.parameters.get("flight_path")
    assert proposal.parameters["purpose"] == "QUEST_SCENE_PATH"


def test_an_unfinished_ring_still_requires_the_explicit_course_flight():
    (proposal,) = QuestScenePathPolicy().propose(landed(rings=4))
    assert proposal.parameters.get("flight_path")


def test_standing_in_the_target_area_waits_for_credit_without_restarting_a_move():
    state = landed()
    state["player_world_position"].update(zip(("x", "y", "z"), TARGET))
    (proposal,) = QuestScenePathPolicy().propose(state)
    assert proposal.skill == "MOVE"
    assert proposal.parameters["flight_path"]["arrival_condition"]


def test_course_preflight_requires_an_explicit_forward_binding_for_the_ground_leg(tmp_path):
    from test_skyriding_actionbar_context_20261025 import cache
    selected = cache(tmp_path, omit=("MOVEFORWARD",))
    check = selected.preflight("QUEST", context="SKYRIDING")
    assert check["ready"] is False and "MOVEFORWARD" in check["missing"]


class WalkingMesh:
    def __init__(self, blocked=False):
        self.calls = 0
        self.blocked = blocked

    def find_path(self, instance_id, start, end):
        self.calls += 1
        if self.blocked:
            return None
        def anchor(point):
            return {**point, "instance_id": instance_id, "coordinate_space": "WORLD_YARDS",
                    "source": "TRINITYCORE_MMAP"}
        return NavMeshPath((anchor(start), anchor(end)), 2, 1, 12.)


@pytest.mark.parametrize("credited", [False, True])
def test_same_navigation_owner_hands_landing_to_a_verified_ground_walk(credited):
    mesh = WalkingMesh()
    nav = NavigationService(navmesh=mesh)
    state = landed(airborne=True, rings=4)
    (proposal,) = QuestScenePathPolicy().propose(state)
    nav.start_skill_request("MOVE", proposal.parameters, state, "same-action", 100.)
    correlation = nav._active_request.correlation_id
    ground = landed(credited=credited, at=101.)
    before = deepcopy(ground)
    result = nav.observe(ground, "ground", 101.)
    assert not result.terminal
    assert nav._movement.flight is None
    assert nav._active_request.correlation_id == correlation
    assert nav._active_request.destination["require_navmesh"] is True and mesh.calls > 0
    commands = nav.command(ground, "ground", 101.)
    assert commands and any(c.binding == "MOVEFORWARD" for c in commands)
    assert all(c.binding != "JUMP" and .04 <= c.duration <= .35 for c in commands)
    assert ground == before


def test_ground_handoff_cannot_bypass_a_missing_navmesh_path():
    mesh = WalkingMesh(blocked=True)
    nav = NavigationService(navmesh=mesh)
    state = landed(airborne=True, rings=4)
    nav.start_skill_request("MOVE", QuestScenePathPolicy().propose(state)[0].parameters, state, "flight", 100.)
    result = nav.observe(landed(at=101.), "landed", 101.)
    assert result.terminal and not result.success
    assert result.reason == "required_navmesh_route_unavailable"
    assert nav.command(landed(at=101.), "landed", 101.) == ()


def test_mounted_ground_leg_arrives_without_restarting_flight():
    nav = NavigationService(navmesh=WalkingMesh())
    state = landed(airborne=True, rings=4)
    nav.start_skill_request("MOVE", QuestScenePathPolicy().propose(state)[0].parameters, state, "flight", 100.)
    nav.observe(landed(at=101.), "ground", 101.)
    request = nav._active_request.request_id
    arrival = landed(at=102.)
    arrival["player_world_position"].update(zip(("x", "y", "z"), TARGET))
    assessment = nav.observe(arrival, "arrived", 102.)
    assert not assessment.terminal and assessment.reason == "awaiting_arrival_evidence"
    assert nav.command(arrival, "arrived", 102.) == ()
    arrival["packet_quest_credits"]["65118"]["182847"] = {"count": 1}
    assessment = nav.observe(arrival, "credited", 102.2)
    assert assessment.terminal and assessment.success, assessment
    assert nav._active_request.request_id == request and nav._movement.flight is None
    assert arrival["is_mounted"] is True


@pytest.mark.parametrize("parallel", [False, True])
def test_fast_lane_yields_ground_route_planning_to_the_canonical_medium_step(parallel):
    mesh = WalkingMesh()
    agent = AutonomousAgent(RecordingExecutor(), navmesh=mesh)
    agent.set_mode(Mode.FULL_AI)
    airborne = landed(airborne=True, rings=4)
    proposal = QuestScenePathPolicy().propose(airborne)[0]
    agent.navigation.start_skill_request("MOVE", proposal.parameters, airborne, "flight", 100.)
    agent.pending = attempt("MOVE", proposal.parameters)
    ground = landed(at=101.)
    agent.world.ingest(Observation.create(ground, 101.))
    payload = {**ground, "transport_kind": "FAST", "fast_sequence": 1}
    if parallel:
        agent.parallel_control.enabled = True
        result = agent.parallel_control.tick(payload, 101., None, 101.)
        assert not agent.parallel_control.drives(agent.pending, 101.)
        # A repeat of the same FAST frame must not reclaim the pending
        # medium-lane handoff before the route can actually be planned.
        agent.parallel_control.tick(payload, 101., None, 101.04)
        assert not agent.parallel_control.drives(agent.pending, 101.04)
    else:
        result = advance_fast_movement(agent, payload, 101., {"MOVE"})
    assert result.get("force_medium") and not result.get("dispatched"), result
    assert mesh.calls == 0 and agent.executor.commands == []
    assert agent.pending.action_id == "a"


def test_completed_course_hands_back_to_the_existing_turn_in_resolver():
    state = landed(credited=True)
    assert QuestScenePathPolicy().propose(state) == []
    guid = "Creature-0-3769-2444-47-183141-0001D824BE"
    state["packet_entities"] = {guid: {
        "guid": guid, "kind": "CREATURE", "entry_id": 183141, "map_id": 2444,
        "position": {"x": 2228.118, "y": 68.924, "z": 143.256,
                     "coordinate_space": "WORLD_YARDS", "age": 1.},
        "quest_giver": {"reward_ready": True, "age": 1.}}}
    resolved = TurnInResolver().locate(SimpleNamespace(quest_id="65118", known_locations=()), state)
    assert resolved.entity_guid == guid
    assert resolved.location["stop_distance"] == 3.
