"""Quest-specific effects of an already terminal skill result."""
from __future__ import annotations

from dataclasses import dataclass

from .collect_strategy import CollectStrategy
from .models import Attempt, Goal, Outcome

# V4-051: which collect-source strategy a skill action is evidence for, when
# it completes against a tracked quest/objective. Combat (KILL) is
# deliberately excluded -- killing is not itself a collection source.
_COLLECT_SKILL_STRATEGY = {
    "LOOT": CollectStrategy.MOB_LOOT,
    "OBJECT_USE": CollectStrategy.GROUND_OBJECT,
    "INTERACT": CollectStrategy.DIRECT_INTERACT,
    "TALK": CollectStrategy.DIRECT_INTERACT,
    "QUEST_ITEM": CollectStrategy.QUEST_ITEM_MECHANIC,
    "QUEST_TOOL": CollectStrategy.QUEST_ITEM_MECHANIC,
}


@dataclass(frozen=True)
class QuestTerminalAssessment:
    quest_ids: tuple
    objective_ids: tuple
    credit: object | None
    events: tuple[tuple[str, dict], ...]


class QuestTerminalProcessor:
    """Apply quest credit/failure memory without owning skill completion."""

    def __init__(self, verifier, quest_runtime, quest_domain) -> None:
        self.verifier = verifier
        self.quest_runtime = quest_runtime
        self.quest_domain = quest_domain

    def process(self, attempt: Attempt, outcome: Outcome, reason: str,
                state: dict, goal: Goal | None, now: float) -> QuestTerminalAssessment:
        params = attempt.proposal.parameters
        quest_ids = tuple(params.get("quest_ids") or (() if params.get("quest_id") is None
                                                       else (params.get("quest_id"),)))
        objective_ids = tuple(params.get("objective_ids") or (() if params.get("objective_id") is None
                                                               else (params.get("objective_id"),)))
        credit = None
        events: list[tuple[str, dict]] = []
        if quest_ids or objective_ids:
            credit = self.verifier.evaluate(
                attempt.baseline, state, quest_ids=quest_ids, objective_ids=objective_ids)
            if credit.success:
                events.append(("QUEST_CREDIT_OBSERVED", {
                    "action_id": attempt.action_id, "skill": attempt.proposal.skill,
                    "evidence": list(credit.evidence),
                }))
                # V4-070: real credit clears the no-credit escalation ladder
                # for every objective this attempt targeted.
                escalation = getattr(self.quest_domain, "credit_escalation", None)
                if escalation is not None:
                    for quest_id in (quest_ids or (None,)):
                        for objective_id in (objective_ids or (None,)):
                            escalation.clear(quest_id, objective_id)
        if goal is not None and goal.domain == "QUEST":
            if outcome == Outcome.FAILURE:
                failure = self.quest_runtime.record_failure(
                    skill=attempt.proposal.skill, parameters=params, reason=reason, now=now)
                if failure is not None:
                    events.append(("QUEST_FAILURE_RECORDED", {
                        "quest_id": failure.quest_id, "objective_id": failure.objective_id,
                        "target_ref": failure.target_ref, "skill": failure.skill,
                        "reason": failure.reason, "suppress_until": failure.suppress_until,
                    }))
            elif outcome == Outcome.SUCCESS:
                self.quest_runtime.record_success(skill=attempt.proposal.skill, parameters=params)
        if (outcome == Outcome.SUCCESS and attempt.proposal.skill == "COMBAT"
                and credit is not None and not credit.success
                and self.quest_domain.record_uncredited_target(
                    params.get("guid"), quest_ids, objective_ids, state, now)):
            events.append(("QUEST_CREDIT_AWAITING", {
                "action_id": attempt.action_id, "guid": params.get("guid"),
                "quest_ids": list(quest_ids), "objective_ids": list(objective_ids),
            }))
        # V4-051: strengthen/weaken the collect-strategy belief whenever a
        # collection-flavored skill completed against a tracked objective.
        strategy = _COLLECT_SKILL_STRATEGY.get(attempt.proposal.skill)
        if strategy is not None and outcome == Outcome.SUCCESS and credit is not None:
            tracker = getattr(self.quest_domain, "collect_strategy", None)
            if tracker is not None:
                for quest_id in (quest_ids or (None,)):
                    for objective_id in (objective_ids or (None,)):
                        tracker.record_outcome(quest_id, objective_id, strategy=strategy,
                                               objective_progressed=credit.success)
        return QuestTerminalAssessment(quest_ids, objective_ids, credit, tuple(events))
