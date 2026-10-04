from types import SimpleNamespace

from wowbot.agent.models import Command
from wowbot.runtime import FailureReason, SkillResult, SkillStatus
from wowbot.skills import LootRuntimeRunner


class Navigation:
    def __init__(self, assessment=None):
        self.assessment = assessment
        self.cancelled = 0

    def observe(self, *args, **kwargs): return self.assessment
    def cancel_movement(self): self.cancelled += 1
    def command(self, *args): return (Command("BIND", "MOVEFORWARD"),)
    def movement_snapshot(self): return {"phase": "test"}
    def move_to_entity(self, state, guid, observation_id, now, stop_distance, allow_dead=False):
        return {"guid": guid, "allow_dead": allow_dead}


class Loot:
    def __init__(self, *, resumed=None, verified=None):
        self.resumed, self.verified = resumed, verified

    def resume_after_approach(self, active, state): return self.resumed
    def verify(self, active, state, now): return self.verified


def test_loot_approach_continues_on_movement_lane():
    nav = Navigation(SimpleNamespace(terminal=False))
    step = LootRuntimeRunner(nav, Loot()).continue_approach(object(), {}, "obs", 1.)
    assert step.movement_lane is True
    assert step.event_type == "LOOT_APPROACH_CONTROL_UPDATE"


def test_loot_arrival_resumes_interaction_without_finalizing():
    nav = Navigation(SimpleNamespace(terminal=True, success=True, reason="arrived"))
    resumed = SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),))
    step = LootRuntimeRunner(nav, Loot(resumed=resumed)).continue_approach(object(), {}, "obs", 1.)
    assert step.movement_lane is False
    assert step.event_type == "LOOT_APPROACH_ARRIVED"
    assert nav.cancelled == 1


def test_loot_verification_starts_dead_entity_approach():
    nav = Navigation()
    result = SkillResult(SkillStatus.RUNNING, metadata={
        "approach_request": {"corpse_guid": "corpse", "stop_distance": 3.5}})
    step = LootRuntimeRunner(nav, Loot(verified=result)).step_verification(object(), {}, "obs", 1.)
    assert step.movement_lane is True
    assert step.event_type == "LOOT_APPROACH_STARTED"
    assert step.set_segment_baseline is True
    assert step.diagnostics["destination"]["allow_dead"] is True


def test_missing_corpse_for_approach_is_typed_failure():
    nav = Navigation()
    nav.move_to_entity = lambda *args, **kwargs: None
    result = SkillResult(SkillStatus.RUNNING, metadata={
        "approach_request": {"corpse_guid": "gone"}})
    step = LootRuntimeRunner(nav, Loot(verified=result)).step_verification(object(), {}, "obs", 1.)
    assert step.terminal_result.reason is FailureReason.CORPSE_NOT_FOUND


def test_terminal_loot_verification_is_returned_typed():
    result = SkillResult(SkillStatus.SUCCESS, evidence=("loot_opened",))
    step = LootRuntimeRunner(Navigation(), Loot(verified=result)).step_verification(
        object(), {}, "obs", 1.)
    assert step.terminal_result is result
