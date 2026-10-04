from types import SimpleNamespace

from wowbot.agent.models import Command
from wowbot.runtime import FailureReason, SkillResult, SkillStatus
from wowbot.skills import InteractionRuntimeRunner


class Navigation:
    def __init__(self, assessment, commands=()):
        self.assessment, self.commands = assessment, commands
        self.cancelled = 0

    def observe(self, state, observation_id, now, commanded):
        return self.assessment

    def command(self, state, observation_id, now):
        return self.commands

    def cancel_movement(self):
        self.cancelled += 1

    def movement_snapshot(self):
        return {"phase": "test"}

    def move_to_entity(self, state, guid, observation_id, now, stop_distance):
        return {"guid": guid, "stop_distance": stop_distance}

    def face_entity(self, state, guid):
        return SimpleNamespace(commands=(Command("BIND", "TURNLEFT"),))

    def local_combat_reposition(self, state, request):
        return (Command("BIND", "STRAFELEFT", .3),)


class Interact:
    def __init__(self, result):
        self.result = result

    def resume_after_approach(self, active, state):
        return self.result


class VisualApproach:
    def __init__(self, result):
        self.result = result

    def observe(self, active, state, observation_id, now):
        return self.result

    def begin(self, active, state, observation_id, now, parameters):
        return self.result

    def snapshot(self, active):
        return {"phase": "tracking"}


def test_world_entity_approach_returns_movement_commands_without_dispatch():
    nav = Navigation(SimpleNamespace(terminal=False), (Command("BIND", "MOVEFORWARD"),))
    runner = InteractionRuntimeRunner(nav, Interact(None))

    step = runner.step_world_entity(object(), {}, "obs", 1.)

    assert step.movement_lane is True
    assert step.event_type == "INTERACT_APPROACH_CONTROL_UPDATE"
    assert len(step.commands) == 1
    assert step.terminal_result is None


def test_failed_arrival_becomes_typed_terminal_result_and_releases_navigation():
    nav = Navigation(SimpleNamespace(terminal=True, success=False, reason="supported_stuck"))
    step = InteractionRuntimeRunner(nav, Interact(None)).step_world_entity(object(), {}, "obs", 1.)

    assert step.terminal_result.status is SkillStatus.FAILURE
    assert step.terminal_result.reason is FailureReason.STUCK
    assert nav.cancelled == 1


def test_successful_arrival_resumes_same_interaction_attempt():
    resumed = SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),))
    nav = Navigation(SimpleNamespace(terminal=True, success=True, reason="arrived"))
    step = InteractionRuntimeRunner(nav, Interact(resumed)).step_world_entity(object(), {}, "obs", 1.)

    assert step.movement_lane is False
    assert step.event_type == "INTERACT_APPROACH_ARRIVED"
    assert step.commands[0].binding == "INTERACTTARGET"
    assert nav.cancelled == 1


def test_visual_approach_routes_servo_to_movement_lane_but_never_dispatches():
    visual = VisualApproach(SkillResult(
        SkillStatus.RUNNING, commands=(Command("BIND", "MOVEFORWARD"),)))
    runner = InteractionRuntimeRunner(
        Navigation(SimpleNamespace()), Interact(None), visual)

    step = runner.step_visual(object(), {}, "visual", 1.)

    assert step.movement_lane is True
    assert step.stop_movement is False
    assert step.event_type == "INTERACT_VISUAL_APPROACH_CONTROL_UPDATE"


def test_visual_arrival_stops_movement_and_resumes_interaction():
    visual = VisualApproach(SkillResult(SkillStatus.SUCCESS))
    resumed = SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),))
    runner = InteractionRuntimeRunner(
        Navigation(SimpleNamespace()), Interact(resumed), visual)

    step = runner.step_visual(object(), {}, "visual", 1.)

    assert step.stop_movement is True
    assert step.movement_lane is False
    assert step.event_type == "INTERACT_VISUAL_APPROACH_READY"
    assert step.commands[0].binding == "INTERACTTARGET"


def test_start_world_entity_approach_returns_destination_and_baseline_request():
    nav = Navigation(SimpleNamespace(), (Command("BIND", "MOVEFORWARD"),))
    runner = InteractionRuntimeRunner(nav, Interact(None))

    step = runner.start_approach(
        object(), {}, "obs", 1.,
        {"kind": "WORLD_ENTITY", "expected_guid": "npc", "stop_distance": 3.})

    assert step.set_segment_baseline is True
    assert step.movement_lane is True
    assert step.diagnostics["destination"]["guid"] == "npc"


def test_start_visual_approach_preserves_discrete_hover_lane():
    visual = VisualApproach(SkillResult(
        SkillStatus.RUNNING, commands=(Command("HOVER", x=.5, y=.4),)))
    runner = InteractionRuntimeRunner(
        Navigation(SimpleNamespace()), Interact(None), visual)

    step = runner.start_approach(object(), {}, "visual", 1., {"purpose": "INTERACT"})

    assert step.movement_lane is False
    assert step.event_type == "INTERACT_VISUAL_APPROACH_STARTED"


def test_running_verification_routes_face_request_through_navigation():
    result = SkillResult(SkillStatus.RUNNING, metadata={
        "local_face_request": {"expected_guid": "npc"}})
    runner = InteractionRuntimeRunner(
        Navigation(SimpleNamespace()), Interact(None), VisualApproach(None))

    step = runner.step_verification(
        object(), {}, result, world_observation_id="world",
        visual_observation_id="visual", now=1.)

    assert step.event_type == "INTERACT_FACE_UPDATE"
    assert step.movement_lane is True


def test_running_verification_preserves_discrete_interact_retry():
    result = SkillResult(
        SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),))
    runner = InteractionRuntimeRunner(
        Navigation(SimpleNamespace()), Interact(None), VisualApproach(None))

    step = runner.step_verification(
        object(), {}, result, world_observation_id="world",
        visual_observation_id="visual", now=1.)

    assert step.event_type == "INTERACT_RETRY"
    assert step.movement_lane is False


def test_running_verification_routes_los_through_shared_navigation_lane():
    result = SkillResult(SkillStatus.RUNNING, metadata={
        "local_los_request": {"reason": "LINE_OF_SIGHT",
                              "expected_guid": "npc", "attempt": 0}})
    runner = InteractionRuntimeRunner(
        Navigation(SimpleNamespace()), Interact(None), VisualApproach(None))
    step = runner.step_verification(
        object(), {}, result, world_observation_id="world",
        visual_observation_id="visual", now=1.)
    assert step.event_type == "INTERACT_LOS_REPOSITION"
    assert step.movement_lane is True
    assert step.commands[0].binding == "STRAFELEFT"
