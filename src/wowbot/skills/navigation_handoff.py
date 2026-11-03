"""Shared subflow boundary; the active skill and NavigationService keep ownership."""
from dataclasses import dataclass

from wowbot.runtime import FailureReason, SkillResult, SkillStatus
from wowbot.value_helpers import number


def deadline(active):
    return number(getattr(getattr(active, 'attempt', None), 'deadline', None))


@dataclass(frozen=True)
class ApproachPreparation:
    pending: bool = False
    terminal: SkillResult | None = None


def prepare(navigation, active, state, now, *, allow_route_queries=True):
    end = deadline(active)
    if end is not None and now >= end:
        navigation.cancel_movement()
        return ApproachPreparation(terminal=SkillResult(SkillStatus.FAILURE, FailureReason.TIMEOUT,
            retryable=True, replan_required=True, metadata={'legacy_reason':'movement_safety_deadline'}))
    resume = getattr(navigation, 'resume_owned_route', None)
    if callable(resume) and not resume(state, now, allow_route_queries=allow_route_queries):
        return ApproachPreparation(pending=True)
    return ApproachPreparation()


def start_options(active=None, *, allow_route_queries=True, end=None):
    options = {} if allow_route_queries else {'defer_plan':True}
    end = deadline(active) if end is None else end
    if end is not None:
        options['deadline'] = end
    return options


def failure_detail(navigation, assessment):
    movement = navigation.movement_snapshot()
    return {'reason':assessment.reason, **{key:movement.get(key) for key in
        ('phase','steering_mode','final_facing','latest_sample','control_updates','position_acquisition','route_feedback')}}
