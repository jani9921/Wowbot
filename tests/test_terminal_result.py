from wowbot.agent.models import Attempt, Outcome, Prediction, Proposal
from wowbot.agent.terminal_result import TerminalResultProcessor
from wowbot.runtime import FailureManager, LoopGuard, SkillStatus


def attempt(skill="INTERACT", params=None):
    proposal = Proposal.make(skill, "test", params or {"guid": "npc-1"})
    prediction = Prediction("prediction", "action", "dialog_open", 1., 5., "before")
    return Attempt("action", proposal, {"target": None}, "before", 1., 5., (), prediction, "plan")


def test_success_builds_verification_and_typed_success_without_failure_chain():
    manager = FailureManager()
    processor = TerminalResultProcessor(manager, LoopGuard())

    result = processor.assess(attempt(), Outcome.SUCCESS, "dialog_opened", 2.,
                              latest_observation_id="after")

    assert result.skill_result.status is SkillStatus.SUCCESS
    assert result.skill_result.reason is None
    assert result.failure_decision is None
    assert result.verification.evidence == ("before", "after")
    assert result.result_projection["outcome"] == str(Outcome.SUCCESS)
    assert manager.snapshot()["active_chains"] == {}


def test_failure_is_normalized_budgeted_and_loop_correlated_by_skill_and_entity():
    manager = FailureManager()
    guard = LoopGuard()
    processor = TerminalResultProcessor(manager, guard)
    current = attempt()

    results = [processor.assess(current, Outcome.FAILURE, "out_of_range", float(index),
                                latest_observation_id=f"after-{index}")
               for index in range(2, 5)]

    assert results[-1].skill_result.status is SkillStatus.FAILURE
    assert results[-1].skill_result.retryable is True
    assert results[-1].failure_decision.record.attempt_number == 3
    assert results[-1].loop_decision.level == "SUSPECTED"
    assert results[-1].result_projection["failure_budget"]["attempt"] == 3
    assert results[-1].result_projection["loop_guard"]["count"] == 3


def test_cancelled_result_does_not_consume_failure_budget():
    manager = FailureManager()
    result = TerminalResultProcessor(manager, LoopGuard()).assess(
        attempt("MOVE"), Outcome.CANCELLED, "interrupted", 2., latest_observation_id=None)

    assert result.skill_result.status is SkillStatus.CANCELLED
    assert result.failure_decision is None
    assert manager.snapshot()["active_chains"] == {}
