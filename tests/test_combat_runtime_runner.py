from types import SimpleNamespace

from wowbot.agent.models import Command
from wowbot.runtime import FailureReason, SkillResult, SkillStatus
from wowbot.skills import CombatRuntimeRunner


class Navigation:
    def __init__(self, assessment=None):
        self.assessment = assessment
        self.cancelled = 0
    def observe(self, *args, **kwargs): return self.assessment
    def cancel_movement(self): self.cancelled += 1
    def command(self, *args): return (Command("BIND", "MOVEFORWARD"),)
    def movement_snapshot(self): return {"phase": "test"}
    def move_to_entity(self, state, guid, observation_id, now, stop_distance): return {"guid": guid}
    def local_combat_reposition(self, state, request): return (Command("BIND", "STRAFELEFT"),)
    def snapshot(self, now): return {"los_recovery": {"phase": "TRY_LATERAL_A"}}
    def reposition_for_los(self, state, guid, observation_id, now, desired_range):
        return {"target_guid": guid, "purpose": "LOS_REPOSITION"}


class Combat:
    def __init__(self, resumed): self.resumed = resumed
    def resume_after_approach(self, active, state, now): return self.resumed


def test_combat_approach_continues_on_movement_lane():
    nav = Navigation(SimpleNamespace(terminal=False))
    step = CombatRuntimeRunner(nav, Combat(None)).continue_approach(object(), {}, "obs", 1.)
    assert step.movement_lane is True
    assert step.event_type == "COMBAT_APPROACH_CONTROL_UPDATE"


def test_combat_arrival_resumes_rotation_without_finalizing():
    nav = Navigation(SimpleNamespace(terminal=True, success=True, reason="arrived"))
    resumed = SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "ACTIONBUTTON1"),))
    step = CombatRuntimeRunner(nav, Combat(resumed)).continue_approach(object(), {}, "obs", 1.)
    assert step.movement_lane is False
    assert step.event_type == "COMBAT_APPROACH_ARRIVED"
    assert nav.cancelled == 1


def test_combat_verification_routes_local_reposition_to_movement():
    result = SkillResult(SkillStatus.RUNNING, metadata={"local_navigation_request": {"side": "LEFT"}})
    step = CombatRuntimeRunner(Navigation(), Combat(None)).step_verification({}, result, "obs", 1.)
    assert step.movement_lane is True
    assert step.event_type == "COMBAT_LOCAL_NAVIGATION_UPDATE"


def test_combat_third_los_step_starts_persistent_navigation_replan():
    result = SkillResult(
        SkillStatus.RUNNING,
        metadata={"los_reposition_request": {
            "expected_guid": "mob-1", "stop_distance": 4.5}})
    step = CombatRuntimeRunner(Navigation(), Combat(None)).step_verification(
        {}, result, "obs-los", 2.)
    assert step.movement_lane is True
    assert step.event_type == "COMBAT_LOS_REPLAN_STARTED"
    assert step.set_segment_baseline is True
    assert step.diagnostics["navigation_mode"] == "REPOSITION_FOR_LOS"


def test_missing_entity_for_approach_is_typed_target_moved():
    nav = Navigation()
    nav.move_to_entity = lambda *args, **kwargs: None
    result = SkillResult(SkillStatus.RUNNING, metadata={"approach_request": {"expected_guid": "gone"}})
    step = CombatRuntimeRunner(nav, Combat(None)).step_verification({}, result, "obs", 1.)
    assert step.terminal_result.reason is FailureReason.TARGET_MOVED
