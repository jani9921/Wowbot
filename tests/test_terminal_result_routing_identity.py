from types import SimpleNamespace

from wowbot.agent.models import Outcome, Prediction, Proposal
from wowbot.agent.terminal_result import TerminalResultProcessor


class FailureManager:
    def record_failure(self, **kwargs):
        record = SimpleNamespace(attempt_number=1, reason=kwargs["reason"])
        return SimpleNamespace(
            record=record, budget=1, retry_allowed=False,
            replan_required=True, backoff_seconds=0.,
            escalation_stage=SimpleNamespace(value="REPLAN"),
            recovery_action=None, domain_recovery_required=False,
            goal_alternative_required=False, goal_failed=False)


class LoopGuard:
    def record_attempt_failure(self, *args, **kwargs):
        return SimpleNamespace(level="NONE", count=0, signature="", kind="",
                               matching_signatures=())


def test_compact_terminal_result_preserves_transition_search_identity_only():
    proposal = Proposal.make("SEEK_VISUAL_CUE", "search", {
        "purpose": "SEARCH_ENTRANCE", "transition_kind": "CHANGE_FLOOR",
        "navigation_context": "MULTI_FLOOR", "large_payload": list(range(100))})
    prediction = Prediction("pred", "action", "expected", 1., 3., "obs:before")
    attempt = SimpleNamespace(
        proposal=proposal, prediction=prediction, action_id="action",
        plan_id="plan", observation_id="obs:before")
    result = TerminalResultProcessor(FailureManager(), LoopGuard()).assess(
        attempt, Outcome.FAILURE, "target_not_found", 2.,
        latest_observation_id="obs:after").result_projection
    assert result["purpose"] == "SEARCH_ENTRANCE"
    assert result["transition_kind"] == "CHANGE_FLOOR"
    assert result["navigation_context"] == "MULTI_FLOOR"
    assert "large_payload" not in result
