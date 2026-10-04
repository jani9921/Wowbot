from types import SimpleNamespace

from wowbot.agent.camera_controller import (
    CAMERA_ACTIONS, CameraController, camera_gesture, view_control_command,
)
from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Attempt, Goal, Mode, Outcome, Prediction, Proposal
from wowbot.agent.planner import DungeonDomain, PvPDomain
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import Observation, WorldModel


def _world(**extra):
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
        "map_id": 1, "position": {"x": .5, "y": .5}, "orientation": 0,
        "health": 100, "max_health": 100, "player_present": True, **extra}, 1))
    return world


def test_horizontal_view_actions_turn_player_while_pitch_actions_keep_camera_drag():
    controller = CameraController()
    registry = SkillRegistry()
    world = _world(world_map_open=False, is_in_combat=False)
    for action in CAMERA_ACTIONS:
        raw = ({"camera_action": action, "target_x": .7, "target_y": .5}
               if action in {"CENTER_TARGET", "REACQUIRE_TRACK", "INSPECT_REGION"}
               else {"camera_action": action})
        params = camera_gesture(raw)
        assert 0 < params["x"] < 1 and 0 < params["y"] < 1
        proposal = Proposal.make("CAMERA_CONTROL", "test", params)
        assert registry.available(proposal, world)
        command = registry.commands(proposal, world)[0]
        if action in {"LOOK_UP", "LOOK_DOWN", "LOOK_AHEAD", "RECENTER"}:
            assert command.kind == "CAMERA_PAN"
        else:
            assert command.kind == "BIND"
            assert command.binding in {"TURNLEFT", "TURNRIGHT"}
        controller.begin(params, 1.)
    assert set(controller.snapshot()["supported_actions"]) == set(CAMERA_ACTIONS)

    assert view_control_command({"camera_action": "LOOK_LEFT"}).binding == "TURNLEFT"
    assert view_control_command({"camera_action": "LOOK_RIGHT"}).binding == "TURNRIGHT"
    assert view_control_command({"camera_action": "CENTER_TARGET",
                                 "target_x": .7, "target_y": .5}).binding == "TURNRIGHT"


def test_reacquire_target_is_explicit_committed_camera_capability():
    world = _world(world_map_open=False, is_in_combat=False,
                   target={"guid": "jaina", "is_attackable": False})
    world.set_runtime_context(commitment={"target_guid": "jaina"})
    registry = SkillRegistry()
    proposal = Proposal.make("REACQUIRE_TARGET", "occluded committed target",
                             {"guid": "jaina", "target_x": .62, "target_y": .4})
    assert registry.available(proposal, world)
    command = registry.commands(proposal, world)[0]
    assert command.kind == "BIND" and command.binding == "TURNRIGHT"


def test_camera_control_verifies_player_orientation_change_with_follow_camera():
    registry = SkillRegistry()
    baseline = _world(orientation=0.).state.copy()
    current = _world(orientation=.2)
    attempt = SimpleNamespace(
        observation_id="before-turn", deadline=7., started_at=1., baseline=baseline,
        proposal=Proposal.make("CAMERA_CONTROL", "scan", {"camera_action": "LOOK_RIGHT"}),
        commands=(view_control_command({"camera_action": "LOOK_RIGHT"}),),
    )

    assert registry.verify(attempt, current, 2.) == (
        Outcome.SUCCESS, "expected_observation_verified")


def test_legacy_inspect_camera_pan_request_now_turns_player_toward_region():
    registry = SkillRegistry()
    world = _world(world_map_open=False, is_in_combat=False)
    proposal = Proposal.make(
        "INSPECT", "scan region", {"camera_pan": True, "x": .3, "y": .45})

    command = registry.commands(proposal, world)[0]

    assert command.kind == "BIND"
    assert command.binding == "TURNLEFT"


def test_camera_verification_waits_for_paged_snapshot_but_real_receive_loss_disarms():
    agent = AutonomousAgent(RecordingExecutor())
    agent.set_goal("questelj", 1)
    agent.set_mode(Mode.FULL_AI)
    payload = {**_world().latest.payload, "state_age": 19.5}
    observation = Observation.create(payload, 1)
    agent.world = WorldModel()
    assert agent.world.ingest(observation)
    proposal = Proposal.make("CAMERA_CONTROL", "scan", {"camera_action": "LOOK_LEFT"})
    prediction = Prediction("prediction", "action", "camera_motion_verified", 1, 8,
                            observation.observation_id)
    agent.pending = Attempt("action", proposal, agent.world.state.copy(),
                            observation.observation_id, 1, 8, (), prediction, "plan")

    status = agent.tick(None, 2)
    assert status["mode"] == "FULL_AI"
    assert status["decision"]["reason"] == "awaiting_fresh_telemetry_after_camera"
    assert agent.pending is not None

    status = agent.tick(None, 7.1)
    assert status["mode"] == "MANUAL"
    assert agent.pending is None


def test_dungeon_follow_mechanic_gate_and_pvp_retreat_share_generic_skills():
    dungeon = _world(instance_state={"inside": True, "mechanic_active": True,
        "mechanic_id": 9, "safe_location": {"map_id": 1, "x": .6, "y": .6}},
        group_state={"ready": False, "leader_position": {"map_id": 1, "x": .55, "y": .5}})
    goal = Goal.parse("dungeon", 1)
    proposals = DungeonDomain().propose(dungeon, goal)
    assert {item.skill for item in proposals} >= {"FOLLOW", "MOVE", "WAIT"}

    pvp = _world(health=20, max_health=100, pvp_state={"match_active": True,
        "objective_id": "flag", "objective_location": {"map_id": 1, "x": .7, "y": .7},
        "retreat_location": {"map_id": 1, "x": .4, "y": .4}})
    proposals = PvPDomain().propose(pvp, Goal.parse("pvp", 1))
    assert proposals[0].parameters["pvp_policy"] == "RETREAT"
    assert proposals[0].priority == 95
